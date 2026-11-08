"""Course synthesis, evidence-grounded cards, and independent bounded reviews."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from anki_generator.database.entities import (
    Course,
    Run,
    Stage,
    now,
)
from anki_generator.llm import ProviderError
from anki_generator.llm.provider import DEFAULT_MODEL
from anki_generator.processing.contracts import (
    PROMPT_VERSION,
)
from anki_generator.processing.evidence import EvidenceIndex

from .audit_stages import AuditStages
from .extraction_stages import ExtractionStages
from .generation_stages import GenerationStages
from .knowledge_stages import KnowledgeStages
from .quality_stages import QualityStages
from .state import atomic_json, digest, entity_data


class CoursePipeline(
    ExtractionStages, KnowledgeStages, GenerationStages, QualityStages, AuditStages
):
    def __init__(self, runner: Any, run_id: str):
        self.runner = runner
        self.run_id = run_id
        self.sessions = runner.session_factory
        self.root = runner.data_root
        with self.sessions() as session:
            run = session.get(Run, run_id)
            course = session.get(Course, run.course_id)
            self.course_id = run.course_id
            self.config = dict(run.config)
            self.request = dict(run.request)
            self.mode = run.mode
            self.course = entity_data(course)
        self.provider = None
        self.evidence: EvidenceIndex
        self.concepts: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []

    def execute(self) -> None:
        self._extract()
        if self.mode == "extract":
            return
        if not self.request.get("consent"):
            raise ValueError(
                "Confirm which source text and images will be sent to OpenAI before processing."
            )
        self._interpret()
        self.evidence = EvidenceIndex(self.documents, self.root)
        if self.mode == "revise":
            self._load_concepts()
            self._revise_requested()
            self._coverage(generate_missing=False)
            return
        self._knowledge()
        self._generate()
        self._deduplicate()
        self._coverage(generate_missing=True)
        self._metrics()

    def _check(self) -> None:
        self.runner.checkpoint(self.run_id)

    def _warning(self, text: str) -> None:
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.warnings = list(dict.fromkeys([*run.warnings, text]))
            session.commit()

    def _stage(self, name: str, *, total: int | None = None, complete: bool = False) -> None:
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.current_stage = name
            stage = session.scalar(
                select(Stage).where(Stage.run_id == self.run_id, Stage.name == name)
            )
            if stage is None:
                stage = Stage(run_id=self.run_id, name=name, started_at=now())
                session.add(stage)
            stage.status = "completed" if complete else "running"
            stage.error = None
            if total is not None:
                stage.total = total
            if complete:
                stage.finished_at = now()
            session.commit()

    def _progress(self, stage_name: str, key: str, artifact: str = "") -> None:
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            stage = session.scalar(
                select(Stage).where(Stage.run_id == self.run_id, Stage.name == stage_name)
            )
            artifacts = dict(stage.artifacts)
            artifacts[key] = artifact
            stage.artifacts = artifacts
            stage.completed = len(artifacts)
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
        }
        model = self.config.get("models", {}).get(aliases.get(stage, stage), DEFAULT_MODEL)
        # Older settings may wrap a model ID in a model/effort object.
        return model.get("model", DEFAULT_MODEL) if isinstance(model, dict) else model

    @staticmethod
    def _prompt_contracts() -> dict[str, str]:
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files("anki_generator.prompts").iterdir()
            if path.name.endswith(".txt")
        }

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
        prompt_path = files("anki_generator.prompts").joinpath(f"{stage}.txt")
        prompt = prompt_path.read_text(encoding="utf-8")
        execution_contract = digest(
            {
                "prompt": prompt,
                "schema": schema.model_json_schema(),
                "model": self._model(stage),
                "effort": self.config.get("reasoning_effort", "high"),
                "output_budget": self.config.get("max_output_tokens", 16000),
            }
        )
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            saved_path = run.checkpoints.get(f"{stage}:{key}")
        if isinstance(saved_path, str):
            saved = (self.root / saved_path).resolve()
            if saved.is_relative_to(self.root) and saved.is_file():
                artifact = json.loads(saved.read_text(encoding="utf-8"))
                if artifact.get("execution_contract") == execution_contract:
                    data = schema.model_validate(artifact["data"])
                    self._progress(stage, key, saved_path)
                    return data
        image_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in images or []]
        fingerprint = digest(
            {
                "stage": stage,
                "prompt": prompt,
                "payload": payload,
                "schema": schema.model_json_schema(),
                "images": image_hashes,
                "model": self._model(stage),
                "reasoning": self.config.get("reasoning_effort", "high"),
                "max_output_tokens": self.config.get("max_output_tokens", 16000),
            }
        )
        path = self.root / "cache" / "llm" / self.course_id / f"{fingerprint}.json"
        reused = path.exists()
        if reused:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            data = schema.model_validate(artifact["data"])
        else:
            if self.provider is None:
                key_value = self.runner.key_getter()
                if not key_value:
                    raise ProviderError(
                        "Configure an OpenAI API key in Settings before generating cards.",
                        kind="authentication",
                    )
                self.provider = self.runner.provider_factory(key_value, self.config)
            response = self.provider.structured(
                stage,
                payload,
                schema,
                model=self._model(stage),
                images=images,
                settings={
                    "reasoning_effort": self.config.get("reasoning_effort", "high"),
                    "max_output_tokens": self.config.get("max_output_tokens", 16000),
                },
            )
            data = schema.model_validate(response.data.model_dump())
            artifact = {
                "data": data.model_dump(mode="json"),
                "usage": response.usage,
                "model": response.model,
                "response_id": response.response_id,
                "prompt_version": PROMPT_VERSION,
                "fingerprint": fingerprint,
                "created_at": now(),
                "execution_contract": execution_contract,
                "request_payload": payload,
                "image_hashes": image_hashes,
            }
            atomic_json(path, artifact)
        relative = path.relative_to(self.root).as_posix()
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            checkpoint_key = f"{stage}:{key}"
            existing = run.checkpoints.get(checkpoint_key)
            if existing != relative:
                run.checkpoints = {**run.checkpoints, checkpoint_key: relative}
                usage = dict(run.usage)
                usage["cached_calls"] = int(usage.get("cached_calls", 0)) + int(reused)
                usage["api_calls"] = int(usage.get("api_calls", 0)) + int(not reused)
                if not reused:
                    for token_key in ("input_tokens", "output_tokens", "total_tokens"):
                        usage[token_key] = int(usage.get(token_key, 0)) + int(
                            artifact["usage"].get(token_key, 0)
                        )
                estimate = artifact["usage"].get("estimated_cost_usd")
                if not reused:
                    if estimate is None:
                        usage["unpriced_calls"] = int(usage.get("unpriced_calls", 0)) + 1
                    else:
                        usage["estimated_cost_usd"] = round(
                            float(usage.get("estimated_cost_usd") or 0) + float(estimate), 8
                        )
                usage["cost_is_estimate"] = True
                run.usage = usage
            session.commit()
        self._progress(stage, key, relative)
        self._check()
        return data
