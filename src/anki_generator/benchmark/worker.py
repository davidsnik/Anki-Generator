"""Isolated developer worker; imports the selected production revision, never a GUI.

Execute this file by path so the same harness can measure an archived source tree.
Private source text and parser diagnostics stay in the private run directory.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import multiprocessing
import re
import resource
import sys
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4


def _save(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    path.chmod(0o600)


def _source_destination(output: Path, source_id: str) -> Path:
    """Contain even direct worker requests within the private experiment directory."""
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{24}", source_id):
        raise ValueError("Source identity must be a generated 24-character hexadecimal ID")
    root = output.resolve(strict=True)
    destination = root / source_id
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise ValueError("Source output escapes the experiment directory")
    destination.mkdir(mode=0o700)
    return destination


def _usage() -> dict:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    factor = 1 if sys.platform == "darwin" else 1024
    return {
        "parent_peak_rss_bytes": own.ru_maxrss * factor,
        "child_peak_rss_bytes": children.ru_maxrss * factor,
        "parent_cpu_seconds": own.ru_utime + own.ru_stime,
        "child_cpu_seconds": children.ru_utime + children.ru_stime,
        "memory_scope": "isolated workload parent and maximum waited child, not their sum",
    }


def portable_retrieval_cases(cases: list[dict], objects: dict, run_indices: dict) -> list[dict]:
    """Keep actual rankings reviewable; unavailable query identity stays unpairable."""
    occurrences: Counter = Counter()
    results = []
    for case in cases:
        run_id = case.get("production_run_id")
        repetition = run_indices.get(run_id)
        query = case["query"]
        bound = objects.get((query["kind"], query["id"], run_id)) or objects.get(
            (query["kind"], query["id"])
        )
        eligible = bool(bound and bound.get("pairing_eligible", True) and bound.get("sources"))
        query_identity = bound["id"] if bound else f"unresolved:{run_id}:{query['id']}"
        key = (case["stage"], query_identity, repetition)
        occurrences[key] += 1
        identity = hashlib.sha256(json.dumps([*key, occurrences[key]]).encode()).hexdigest()[:24]
        hits = []
        for hit in case["hits"]:
            target = objects.get((case["candidate_kind"], hit["id"]))
            hits.append(
                {
                    **hit,
                    "production_id": hit["id"],
                    "id": target["id"] if target else f"unresolved:{hit['id']}",
                    "object": target,
                    "source_binding_status": "bound" if target else "unresolved",
                }
            )
        results.append(
            {
                **case,
                "id": f"retrieval-{identity}",
                "repetition": repetition,
                "query": {**query, "production_id": query["id"], "object": bound},
                "hits": hits,
                "sources": bound.get("sources", []) if bound else [],
                "pairing_eligible": eligible,
                "pairing_basis": "Bound query target, stage, repetition and occurrence; "
                "not human-confirmed semantic equivalence",
                "query_binding_status": "bound" if bound else "unresolved; inspect saved requests",
                "object_context_scope": "Final saved object state; observed IDs/ranks are exact, "
                "but query-time text/revisions were not captured",
                "relevance_status": "pending independent judgments; no labels inferred",
            }
        )
    return results


def _page_case(source: dict, data: dict, page: dict, destination: Path) -> dict:
    regions = [
        {**region, "image_path": str(destination / region["image_path"])}
        for region in page["regions"]
    ]
    return {
        "id": f"{source['id']}:p{page['page_number']}",
        "source_id": source["id"],
        "document_sha256": source["sha256"],
        "course_id": source["course_id"],
        "page_number": page["page_number"],
        "method": f"native_{data['source_type']}_extractor_{data['extractor_version']}",
        "transcription": page["text"],
        "reference_transcription": None,
        "reference_origin": None,
        "width": page["width"],
        "height": page["height"],
        "coordinate_system": page["coordinate_system"],
        "needs_vision": page["needs_vision"],
        "status": page["status"],
        "warnings": page["warnings"],
        "regions": regions,
        "image_path": regions[0]["image_path"] if regions else None,
        "image_scope": "first bounded region; all original-coordinate regions listed",
        "sources": [
            {
                "source_id": source["id"],
                "document_sha256": source["sha256"],
                "page_number": page["page_number"],
            }
        ],
    }


def portable_case(data: dict, source_by_document: dict, *, identity: str | None, kind: str) -> dict:
    """Bind output to original hashes; fresh database UUIDs never imply paired identity."""
    sources = []
    for reference in data.get("sources", []):
        source = source_by_document.get(reference.get("document_id"))
        if source is None:
            continue
        sources.append(
            {
                **reference,
                "source_id": source["id"],
                "document_sha256": source["sha256"],
            }
        )
    binding = sorted(
        [
            {
                key: reference[key]
                for key in ("source_id", "document_sha256", "page_number", "region_id", "bbox")
                if reference.get(key) is not None
            }
            for reference in sources
        ],
        key=lambda value: json.dumps(value, sort_keys=True),
    )
    identity_data = {"identity": identity, "sources": binding}
    if kind == "card":
        identity_data["concept_target"] = data.get("concept_target_id")
    if not identity:
        identity_data["content"] = {
            key: data.get(key) for key in ("question", "answer", "title", "description")
        }
    key = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()[:32]
    return {
        **data,
        "production_id": data["id"],
        "id": f"{kind}-{key}",
        "sources": sources,
        "unresolved_source_references": len(data.get("sources", [])) - len(sources),
        "pairing_eligible": True,
        "pairing_basis": (
            "model-declared target and identical original sources; not human equivalence"
        )
        if identity
        else "identical frozen content and original sources only",
    }


def portable_card_case(
    data: dict, source_by_document: dict, *, identity: str | None, concept_targets: dict[str, str]
) -> dict:
    """Respect the production card identity's concept scope without pairing database UUIDs."""
    production_concept = data.get("concept_id")
    concept_target = concept_targets.get(production_concept)
    # A missing generated concept is unresolved, rather than a shared global scope.
    scoped_identity = (
        json.dumps({"card_target": identity, "concept_target": concept_target}, sort_keys=True)
        if identity and (production_concept is None or concept_target is not None)
        else None
    )
    case = portable_case(
        {**data, "concept_target_id": concept_target},
        source_by_document,
        identity=scoped_identity,
        kind="card",
    )
    return (
        _unpairable_case(case, "Generated concept identity is missing or ambiguous")
        if production_concept is not None and concept_target is None
        else case
    )


def _unpairable_case(case: dict, reason: str) -> dict:
    return {
        **case,
        "id": f"unpairable-{uuid4().hex}",
        "ambiguous_target_id": case["id"],
        "pairing_eligible": False,
        "unpairable_reason": reason,
        "pairing_basis": f"Cross-run pairing prohibited: {reason}",
    }


def distinct_output_cases(cases: list[dict]) -> list[dict]:
    """Preserve ambiguous duplicate targets as distinct, explicitly unpairable outputs."""
    counts = Counter(case["id"] for case in cases)
    return [
        _unpairable_case(
            case, "Multiple outputs share the same declared target and original sources"
        )
        if counts[case["id"]] > 1
        else case
        for case in cases
    ]


def local_extract(request: dict, output: Path) -> dict:
    from anki_generator.ingestion.extraction import ExtractionOptions, extract_document_safely

    options = ExtractionOptions.model_validate(request["extraction"])
    fidelity, sources = [], []
    started = time.perf_counter()
    for source in request["sources"]:
        source_path = Path(source["path"])
        with source_path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != source["sha256"]:
                raise ValueError("Source hash changed after dataset inventory")
        destination = _source_destination(output, source["id"])
        unit_start = time.perf_counter()
        try:
            result = extract_document_safely(
                source_path,
                destination,
                options=options,
                page_numbers=source.get("page_numbers"),
            )
            data = result.model_dump(mode="json")
            _save(destination / "extraction.json", data)
            status = data["status"]
            for page in data["pages"]:
                fidelity.append(_page_case(source, data, page, destination))
            sources.append(
                {
                    "source_id": source["id"],
                    "course_id": source["course_id"],
                    "status": status,
                    "total_pages": data["total_pages"],
                    "extracted_pages": len(data["pages"]),
                    "native_characters": sum(len(page["text"]) for page in data["pages"]),
                    "regions": sum(len(page["regions"]) for page in data["pages"]),
                    "render_pixels": sum(
                        region["pixel_width"] * region["pixel_height"]
                        for page in data["pages"]
                        for region in page["regions"]
                    ),
                    "warnings": data["warnings"],
                    "parser_measurements": data.get("measurements"),
                    "elapsed_seconds": time.perf_counter() - unit_start,
                    "artifact": str(destination / "extraction.json"),
                }
            )
        except Exception as exc:
            sources.append(
                {
                    "source_id": source["id"],
                    "course_id": source["course_id"],
                    "status": "failed",
                    "error_kind": type(exc).__name__,
                    "error": str(exc)[:2000],
                    "elapsed_seconds": time.perf_counter() - unit_start,
                }
            )
    elapsed = time.perf_counter() - started
    observed = [
        source["parser_measurements"]
        for source in sources
        if source.get("parser_measurements") is not None
    ]

    def observed_sum(key):
        values = [measurement[key] for measurement in observed if measurement.get(key) is not None]
        return sum(values) if values else None

    return {
        "sources": sources,
        "cards": [],
        "concepts": [],
        "fidelity": fidelity,
        "retrieval": [],
        "measurements": {
            "wall_seconds": elapsed,
            "pages_per_second": len(fidelity) / elapsed if elapsed else None,
            "source_units": len(sources),
            "pages": len(fidelity),
            "api_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0,
            "cost_basis": "No API requests; no model execution",
            "parser_measurement_sources": len(observed),
            "pdf_render_seconds": observed_sum("pdf_render_seconds"),
            "parser_worker_cpu_seconds": observed_sum("worker_cpu_seconds"),
            "parser_worker_wall_seconds": observed_sum("worker_wall_seconds"),
            **_usage(),
        },
        "status": "completed" if all(s["status"] != "failed" for s in sources) else "partial",
    }


def production_pipeline(request: dict, output: Path) -> dict:
    """Run the same durable pipeline as the app, with explicit external consent."""
    import threading

    from sqlalchemy import select

    from anki_generator.api.runtime import Runtime
    from anki_generator.database.entities import Card, Concept, Course, Document, Revision, Run
    from anki_generator.llm.provider import OpenAIProvider, ProviderError
    from anki_generator.services.records import card_view
    from anki_generator.services.run_submission import submit_run
    from anki_generator.services.storage import store_bytes

    live = request["execution"] == "live_pipeline"
    if live and (not request.get("consent") or not request.get("live")):
        raise ValueError("Live benchmarks require both --live and --consent")
    runtime = Runtime(output / "application")
    started = time.perf_counter()
    deadline = started + request["max_elapsed_seconds"]
    remaining = request["max_api_requests"]
    budget_lock = threading.Lock()

    class BoundedProvider(OpenAIProvider):
        def _request(self, call, *, model, operation):
            def guarded():
                nonlocal remaining
                with budget_lock:
                    if remaining <= 0 or time.perf_counter() > deadline:
                        raise ProviderError(
                            "Benchmark request/time budget reached; saved results are retained.",
                            kind="benchmark_budget",
                        )
                    remaining -= 1
                return call()

            return super()._request(guarded, model=model, operation=operation)

    if live:
        runtime.runner.provider_factory = lambda key, config: BoundedProvider(key)
    if live and not runtime.secrets.get():
        raise ValueError("No OpenAI key configured; live benchmarks were not executed")
    retrieval_capture = None
    try:
        from anki_generator.benchmark.retrieval_capture import RetrievalCapture
        from anki_generator.services.measurements import PipelineMeasurements

        retrieval_capture = RetrievalCapture()
        runtime.runner.profiler_factory = lambda run_id: PipelineMeasurements(
            retrieval_observer=lambda event: retrieval_capture({**event, "run_id": run_id})
        )
    except ImportError:
        pass  # The archived baseline predates developer instrumentation.
    try:
        import_started = time.perf_counter()
        with runtime.sessions.begin() as session:
            course = Course(name=request["name"], deck_name=request["name"])
            session.add(course)
            session.flush()
            course_id = course.id
            for source in request["sources"]:
                content = Path(source["path"]).read_bytes()
                relative, sha = store_bytes(runtime.data_root, content, Path(source["path"]).suffix)
                if sha != source["sha256"]:
                    raise ValueError("Source changed since the benchmark inventory")
                roles = source["role_candidates"]
                session.add(
                    Document(
                        course_id=course_id,
                        filename=Path(source["path"]).name,
                        relative_path=source["relative_path"],
                        storage_path=relative,
                        sha256=sha,
                        size_bytes=len(content),
                        mime_type=mimetypes.guess_type(source["path"])[0]
                        or "application/octet-stream",
                        category=roles[0] if len(roles) == 1 else "reference",
                        authority="unknown",
                    )
                )
        source_import_seconds = time.perf_counter() - import_started
        configuration = request["pipeline"]
        configuration = {
            key: configuration[key]
            for key in (
                "models",
                "criteria",
                "extraction",
                "processing",
                "prompt_overrides",
                "reasoning_effort",
                "max_revisions",
                "role_influence",
            )
        }
        configuration["extraction"] = request["extraction"]
        repetitions = []
        for index in range(request["repetitions"]):
            run = submit_run(
                runtime,
                course_id,
                {"consent": live, "mode": "generate" if live else "extract"},
                configuration,
                enqueue=False,
            )
            run_started = time.perf_counter()
            runtime.runner.enqueue(run["id"])
            runtime.runner.run_now(run["id"])
            with runtime.sessions() as session:
                observed = session.get(Run, run["id"])
                repetitions.append(
                    {
                        "index": index,
                        "cache_state": "cold" if index == 0 else "same_workspace_repeat",
                        "run_id": observed.id,
                        "status": observed.status,
                        "wall_seconds": time.perf_counter() - run_started,
                        "metrics": observed.metrics,
                        "usage": observed.usage,
                        **_usage(),
                    }
                )
            if repetitions[-1]["status"] != "completed":
                break
        with runtime.sessions() as session:
            record = session.get(Run, run["id"])
            source_by_path = {source["relative_path"]: source for source in request["sources"]}
            source_by_document = {}
            fidelity = []
            source_results = []
            for document in session.scalars(
                select(Document).where(Document.course_id == course_id)
            ):
                data = document.extraction
                source = source_by_path[document.relative_path]
                source_by_document[document.id] = source
                artifact = runtime.data_root / data.get("artifact_dir", "")
                fidelity.extend(
                    _page_case(source, data, page, artifact) for page in data.get("pages", [])
                )
                source_results.append(
                    {
                        "source_id": source["id"],
                        "course_id": source["course_id"],
                        "status": data.get("status", "failed"),
                        "extracted_pages": len(data.get("pages", [])),
                    }
                )
            concepts = distinct_output_cases(
                [
                    portable_case(
                        {
                            "id": concept.id,
                            "title": concept.title,
                            "description": concept.description,
                            "kind": concept.kind,
                            "importance": concept.importance,
                            "metadata": concept.metadata_json,
                            "exercise_analysis": concept.exercise_analysis,
                            "relationships": concept.relationships,
                            "sources": concept.sources,
                        },
                        source_by_document,
                        identity=concept.metadata_json.get("canonical_key"),
                        kind="concept",
                    )
                    for concept in session.scalars(
                        select(Concept).where(Concept.course_id == course_id)
                    )
                ]
            )
            concept_targets = {
                concept["production_id"]: concept["id"]
                for concept in concepts
                if concept["pairing_eligible"]
            }
            cards = []
            for card in session.scalars(select(Card).where(Card.course_id == course_id)):
                revision = session.scalar(
                    select(Revision)
                    .where(Revision.card_id == card.id)
                    .order_by(Revision.created_at.desc())
                    .limit(1)
                )
                identity = revision.snapshot.get("identity_key") if revision else None
                cards.append(
                    portable_card_case(
                        card_view(session, card, detail=True),
                        source_by_document,
                        identity=identity,
                        concept_targets=concept_targets,
                    )
                )
            cards = distinct_output_cases(cards)
            retrieval, retrieval_observations = [], None
            if retrieval_capture is not None:
                from anki_generator.database.pipeline_entities import SourceCoverageTarget

                objects = {
                    (kind, item["production_id"]): item
                    for kind, collection in (("card", cards), ("concept", concepts))
                    for item in collection
                }
                for target in session.scalars(
                    select(SourceCoverageTarget).where(SourceCoverageTarget.course_id == course_id)
                ):
                    objects[("source_target", target.target_key, target.run_id)] = portable_case(
                        {
                            "id": target.id,
                            "title": target.title,
                            "statement": target.statement,
                            "kind": target.kind,
                            "sources": target.sources,
                            "origin": "model source audit; not independent reference truth",
                        },
                        source_by_document,
                        identity=target.target_key,
                        kind="source_target",
                    )
                captured = retrieval_capture.snapshot()
                retrieval = portable_retrieval_cases(
                    captured.pop("cases"),
                    objects,
                    {item["run_id"]: item["index"] for item in repetitions},
                )
                retrieval_observations = captured
            return {
                "status": record.status,
                "production_run_id": record.id,
                "cards": cards,
                "concepts": concepts,
                "fidelity": fidelity,
                "retrieval": retrieval,
                "retrieval_capture": retrieval_observations,
                "sources": source_results,
                "usage": record.usage,
                "metrics": record.metrics,
                "effective_configuration": record.config,
                "repetitions": repetitions,
                "measurements": {
                    "wall_seconds": time.perf_counter() - started,
                    "source_import_seconds": source_import_seconds,
                    "bounded_pipeline_attempts": request["max_api_requests"] - remaining,
                    "api_requests": request["max_api_requests"] - remaining,
                    "input_tokens": None if live else 0,
                    "output_tokens": None if live else 0,
                    "estimated_cost_usd": None if live else 0,
                    "usage_scope": "Per-repetition observed usage is retained separately; "
                    "local extraction makes no model requests",
                    **_usage(),
                },
            }
    finally:
        runtime.runner.stop()


def main() -> int:
    request_path = Path(sys.argv[1]).resolve()
    request = json.loads(request_path.read_text())
    implementation = Path(request["implementation_root"]).resolve()
    sys.path.insert(0, str(implementation / "src"))
    import anki_generator

    imported = Path(anki_generator.__file__).resolve()
    if not imported.is_relative_to(implementation):
        raise RuntimeError("Worker imported a different implementation than the requested revision")
    output = request_path.parent
    try:
        function = local_extract if request["execution"] == "local_extract" else production_pipeline
        result = function(request, output)
        result["implementation_path"] = str(imported)
        _save(output / "worker-result.json", result)
        return 0
    except Exception as exc:
        _save(
            output / "worker-result.json",
            {
                "status": "failed",
                "error_kind": type(exc).__name__,
                "error": "Benchmark worker failed; private exception arguments are omitted.",
            },
        )
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
