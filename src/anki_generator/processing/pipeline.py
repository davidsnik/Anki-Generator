"""Context-bounded, independently audited processing with durable concurrent units."""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from time import monotonic
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from anki_generator.database.entities import Course, Run, Stage, now
from anki_generator.llm import ProviderError
from anki_generator.llm.embeddings import EmbeddingResult
from anki_generator.llm.provider import DEFAULT_MODEL, OpenAIProvider
from anki_generator.orchestration.concurrency import bounded_map
from anki_generator.processing.evidence import EvidenceIndex
from anki_generator.services.context_budget import ensure_request_budget
from anki_generator.services.pipeline_options import ProcessingOptions
from anki_generator.services.semantic import ensure_vectors

from .audit_stages import AuditStages
from .extraction_stages import ExtractionStages
from .generation_stages import GenerationStages
from .knowledge_stages import KnowledgeStages
from .quality_stages import QualityStages
from .source_coverage import SourceCoverageStages
from .state import atomic_json, digest, entity_data


class CoursePipeline(
    ExtractionStages,
    KnowledgeStages,
    GenerationStages,
    QualityStages,
    AuditStages,
    SourceCoverageStages,
):
    def __init__(self, runner: Any, run_id: str):
        self.runner, self.run_id = runner, run_id
        self.resources = runner.resources
        self.sessions, self.root = runner.session_factory, runner.data_root
        with self.sessions() as session:
            run = session.get(Run, run_id)
            self.course_id, self.mode = run.course_id, run.mode
            self.config, self.request = dict(run.config), dict(run.request)
            self.course = entity_data(session.get(Course, run.course_id))
            self.course.update(self.config.get("course_snapshot", {}))
        processing = dict(self.config.get("processing", {}))
        if "coverage_rounds" in self.config and "coverage_rounds" not in processing:
            processing["coverage_rounds"] = self.config["coverage_rounds"]
        self.options = ProcessingOptions.model_validate(processing)
        self.provider = None
        self.evidence: EvidenceIndex
        self.concepts: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self._state_lock = threading.RLock()
        self._api_slots = threading.BoundedSemaphore(self.options.api_concurrency)
        self._request_locks: dict[str, threading.RLock] = {}
        self._resolved_card_ids: dict[str, str] = {}
        self._forced_vector_types: set[str] = set()
        self._forced_embedding_keys: set[str] = set()

    def execute(self) -> None:
        try:
            self._execute()
        finally:
            self.close()

    def close(self) -> None:
        with self._state_lock:
            provider, self.provider = self.provider, None
        if isinstance(provider, OpenAIProvider) and not provider.close_owned_client():
            self._resource_event({"kind": "provider_cleanup_failed"})

    def _execute(self) -> None:
        self._extract()
        self._overlay_corrections()
        if self.mode == "extract":
            return
        if not self.request.get("consent"):
            raise ValueError(
                "Confirm which source text, images and semantic inputs will be sent to OpenAI."
            )
        self._interpret()
        self._overlay_corrections()
        self.evidence = EvidenceIndex(self.documents, self.root)
        if self.mode == "interpret":
            return
        if self.mode == "revise":
            self._load_concepts()
            self._revise_requested()
            self._coverage(generate_missing=False)
            return
        self._knowledge()
        self._source_audit()
        self._generate()
        self._deduplicate()
        self._coverage(generate_missing=True)
        self._metrics()

    def _overlay_corrections(self) -> None:
        from anki_generator.services.source_corrections import apply_corrections

        with self.sessions() as session:
            for document in self.documents:
                document["extraction"] = apply_corrections(
                    session,
                    document["id"],
                    document["extraction"],
                    data_root=self.root,
                    replace_human=self.request.get("replace_human", False),
                )

    def _parallel(self, tasks, work):
        return bounded_map(tasks, work, workers=self.options.concurrency, checkpoint=self._check)

    def _check(self) -> None:
        self.runner.checkpoint(self.run_id)

    def _resource_event(self, event: dict[str, Any]) -> None:
        from anki_generator.services.task_events import add_event

        messages = {
            "resource_wait": "Waiting for shared processing capacity.",
            "resource_acquired": "Shared processing capacity became available.",
            "api_retry": "A temporary provider failure will be retried after backoff.",
            "api_failure": "The provider request could not complete.",
            "provider_cleanup_failed": "The provider connection could not be fully closed.",
        }
        kind = event["kind"]
        with self._state_lock, self.sessions.begin() as session:
            add_event(
                session,
                self.run_id,
                kind,
                messages.get(kind, "Processing resource event."),
                level="warning"
                if kind in {"api_retry", "api_failure", "provider_cleanup_failed"}
                else "info",
                details={key: value for key, value in event.items() if key != "kind"},
            )

    def _local_work(self):
        return self.resources.local(
            self.run_id, checkpoint=self._check, on_event=self._resource_event
        )

    @contextmanager
    def _api_work(self, model: str):
        # Preserve the run's stage cap as well as live application-wide limits.
        while not self._api_slots.acquire(timeout=0.2):
            self._check()
        try:
            self._check()
            provider = self._get_provider()
            if isinstance(provider, OpenAIProvider):
                # Official transport admits each physical retry separately.
                yield provider
            else:
                # Explicit test transports still obey the same shared budgets.
                with self.resources.api(
                    self.run_id, model, checkpoint=self._check, on_event=self._resource_event
                ):
                    yield provider
        finally:
            self._api_slots.release()

    def _warning(self, text: str) -> None:
        with self._state_lock, self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.warnings = list(dict.fromkeys([*run.warnings, text]))
            session.commit()

    def _stage(self, name: str, *, total: int | None = None, complete: bool = False) -> None:
        with self._state_lock, self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.current_stage = name
            stage = session.scalar(
                select(Stage).where(Stage.run_id == self.run_id, Stage.name == name)
            )
            if stage is None:
                stage = Stage(run_id=self.run_id, name=name, started_at=now())
                session.add(stage)
            stage.status, stage.error = ("completed" if complete else "running"), None
            if total is not None:
                stage.total = max(stage.completed or 0, total)
            if complete:
                stage.finished_at = now()
            session.commit()

    def _progress(self, stage_name: str, key: str, artifact: str = "") -> None:
        with self._state_lock, self.sessions() as session:
            run = session.get(Run, self.run_id)
            stage = session.scalar(
                select(Stage).where(Stage.run_id == self.run_id, Stage.name == stage_name)
            )
            stage.artifacts = {**stage.artifacts, key: artifact}
            stage.completed = len(stage.artifacts)
            stage.total = max(stage.total, stage.completed)
            run.progress = {
                **run.progress,
                "stage": stage_name,
                "completed": stage.completed,
                "total": stage.total,
            }
            session.commit()

    def _model(self, stage: str) -> str:
        aliases = {
            "consolidation": "knowledge",
            "revision": "generation",
            "mathematical": "factual",
            "deduplication": "factual",
            "identity": "factual",
            "source_audit": "coverage",
            "source_matching": "coverage",
            "target_coverage": "coverage",
        }
        model = self.config.get("models", {}).get(aliases.get(stage, stage), DEFAULT_MODEL)
        return model.get("model", DEFAULT_MODEL) if isinstance(model, dict) else model

    def _prompt_text(self, stage: str) -> str:
        override = self.config.get("prompt_overrides", {}).get(stage)
        if override:
            return (
                files("anki_generator.prompts").joinpath("generic.txt").read_text()
                + "\n"
                + override
            )
        return files("anki_generator.prompts").joinpath(f"{stage}.txt").read_text()

    def _prompt_contracts(self) -> dict[str, str]:
        return {
            path.name: digest(self._prompt_text(path.name.removesuffix(".txt")))
            for path in files("anki_generator.prompts").iterdir()
            if path.name.endswith(".txt")
        }

    def _get_provider(self):
        with self._state_lock:
            if self.provider is None:
                key = self.runner.key_getter()
                if not key:
                    raise ProviderError(
                        "Configure an OpenAI API key in Settings before processing.",
                        kind="authentication",
                    )
                self.provider = self.runner.provider_factory(key, self.config)
                if isinstance(self.provider, OpenAIProvider):
                    self.provider = self.provider.with_resources(
                        self.resources,
                        self.run_id,
                        checkpoint=self._check,
                        on_event=self._resource_event,
                    )
            return self.provider

    def _record_artifact(
        self, stage: str, key: str, path: Path, artifact: dict, *, reused: bool
    ) -> None:
        relative = path.relative_to(self.root).as_posix()
        with self._state_lock, self.sessions() as session:
            run = session.get(Run, self.run_id)
            checkpoint_key = f"{stage}:{key}"
            if run.checkpoints.get(checkpoint_key) != relative:
                run.checkpoints = {**run.checkpoints, checkpoint_key: relative}
                usage = dict(run.usage)
                usage["cached_calls"] = int(usage.get("cached_calls", 0)) + int(reused)
                usage["api_calls"] = int(usage.get("api_calls", 0)) + int(not reused)
                if not reused:
                    for token_key in (
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                        "retry_count",
                    ):
                        usage[token_key] = int(usage.get(token_key, 0)) + int(
                            artifact["usage"].get(token_key, 0)
                        )
                    estimate = artifact["usage"].get("estimated_cost_usd")
                    if estimate is None:
                        usage["unpriced_calls"] = int(usage.get("unpriced_calls", 0)) + 1
                    else:
                        usage["estimated_cost_usd"] = round(
                            float(usage.get("estimated_cost_usd") or 0) + estimate, 8
                        )
                usage["cost_is_estimate"] = True
                run.usage = usage
                timings = dict(run.metrics.get("stage_seconds", {}))
                timings[stage] = round(
                    float(timings.get(stage, 0))
                    + float(artifact.get("elapsed_seconds", 0)) * int(not reused),
                    5,
                )
                run.metrics = {**run.metrics, "stage_seconds": timings}
            session.commit()
        self._progress(stage, key, relative)

    def _force_unit(self, stage: str, payload: dict[str, Any]) -> bool:
        if self.request.get("retry_stage") != stage:
            return False
        selected_docs = set(self.request.get("document_ids") or [])
        selected_pages = set(self.request.get("page_numbers") or [])
        selected_regions = set(self.request.get("region_ids") or [])

        def references(value):
            if isinstance(value, list):
                return [ref for item in value for ref in references(item)]
            if not isinstance(value, dict):
                return []
            found = []
            if "document_id" in value and "page_number" in value:
                visuals = value.get("visual_interpretations", [])
                found.extend(
                    {**value, "region_id": item["region_id"]}
                    for item in visuals
                    if item.get("region_id")
                )
                if not visuals:
                    found.append(value)
            for field in ("sources", "card", "existing_card", "concept", "concepts", "targets"):
                if field in value:
                    found.extend(references(value[field]))
            return found

        refs = references(payload)
        if not refs:
            return True  # aggregate stages are recomputed from all retained inputs
        return any(
            (not selected_docs or ref.get("document_id") in selected_docs)
            and (not selected_pages or ref.get("page_number") in selected_pages)
            and (not selected_regions or ref.get("region_id") in selected_regions)
            for ref in refs
        )

    def _call(
        self,
        stage: str,
        key: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        images: list[Path] | None = None,
    ) -> BaseModel:
        self._check()
        self._stage(stage)
        with self._state_lock:
            lock = self._request_locks.setdefault(f"{stage}:{key}", threading.RLock())
        with lock:
            prompt = self._prompt_text(stage)
            budget = ensure_request_budget(
                payload,
                prompt,
                schema.model_json_schema(),
                budget=self.options.input_token_budget,
                images=len(images or []),
            )
            contract = digest(
                {
                    "prompt": prompt,
                    "schema": schema.model_json_schema(),
                    "model": self._model(stage),
                    "effort": self.config.get("reasoning_effort", "high"),
                    "output_budget": self.options.output_token_budget,
                }
            )
            with self.sessions() as session:
                saved_path = session.get(Run, self.run_id).checkpoints.get(f"{stage}:{key}")
            force = self._force_unit(stage, payload)
            if isinstance(saved_path, str) and not force:
                saved = (self.root / saved_path).resolve()
                if saved.is_relative_to(self.root) and saved.is_file():
                    artifact = json.loads(saved.read_text())
                    if artifact.get("execution_contract") == contract:
                        data = schema.model_validate(artifact["data"])
                        self._progress(stage, key, saved_path)
                        return data
            image_hashes = []
            for image in images or []:
                with image.open("rb") as stream:
                    image_hashes.append(hashlib.file_digest(stream, "sha256").hexdigest())
            fingerprint = digest({"contract": contract, "payload": payload, "images": image_hashes})
            path = self.root / "cache" / "llm" / self.course_id / f"{fingerprint}.json"
            reused = path.is_file() and not force
            if reused:
                artifact = json.loads(path.read_text())
                data = schema.model_validate(artifact["data"])
            else:
                self._check()
                started = monotonic()
                with self._api_work(self._model(stage)) as provider:
                    response = provider.structured(
                        stage,
                        payload,
                        schema,
                        model=self._model(stage),
                        images=images,
                        settings={
                            "reasoning_effort": self.config.get("reasoning_effort", "high"),
                            "max_output_tokens": self.options.output_token_budget,
                            "instructions_override": prompt,
                        },
                    )
                data = schema.model_validate(response.data.model_dump())
                artifact = {
                    "data": data.model_dump(mode="json"),
                    "usage": response.usage,
                    "model": response.model,
                    "response_id": response.response_id,
                    "prompt_version": digest(prompt),
                    "fingerprint": fingerprint,
                    "execution_contract": contract,
                    "request_payload": payload,
                    "image_hashes": image_hashes,
                    "context_budget": budget,
                    "elapsed_seconds": monotonic() - started,
                    "created_at": now(),
                }
                atomic_json(path, artifact)
            self._record_artifact(stage, key, path, artifact, reused=reused)
            self._check()
            return data

    def _embed(self, texts: list[str], key: str) -> EmbeddingResult:
        self._check()
        self._stage("embeddings")
        contract = {
            "model": self.options.embedding_model,
            "dimensions": self.options.embedding_dimensions,
            "texts": texts,
        }
        path = self.root / "cache" / "embeddings" / self.course_id / f"{digest(contract)}.json"
        with self._state_lock:
            lock = self._request_locks.setdefault(
                f"embeddings:{digest(contract)}", threading.RLock()
            )
        with lock:
            force = (
                self.request.get("retry_stage") == "embeddings"
                and key not in self._forced_embedding_keys
            )
            self._forced_embedding_keys.add(key)
            reused = path.is_file() and not force
            if reused:
                artifact = json.loads(path.read_text())
            else:
                started = monotonic()
                with self._api_work(self.options.embedding_model) as provider:
                    response = provider.embed(
                        texts,
                        model=self.options.embedding_model,
                        dimensions=self.options.embedding_dimensions,
                    )
                artifact = {
                    "vectors": response.vectors,
                    "model": response.model,
                    "usage": response.usage,
                    "elapsed_seconds": monotonic() - started,
                    "created_at": now(),
                    "representation": "neural_embeddings",
                }
                atomic_json(path, artifact)
            self._record_artifact("embeddings", key, path, artifact, reused=reused)
        self._stage("embeddings", complete=True)
        self._check()
        return EmbeddingResult(artifact["vectors"], artifact["model"], artifact["usage"])

    def _vectors(self, objects: list[dict[str, Any]], object_type: str):
        force = (
            self.request.get("retry_stage") == "embeddings"
            and object_type not in self._forced_vector_types
        )
        self._forced_vector_types.add(object_type)
        return ensure_vectors(
            self.sessions,
            self.course_id,
            objects,
            object_type=object_type,
            model=self.options.embedding_model,
            dimensions=self.options.embedding_dimensions,
            embed_call=self._embed,
            batch_size=self.options.embedding_batch_size,
            force=force,
        )
