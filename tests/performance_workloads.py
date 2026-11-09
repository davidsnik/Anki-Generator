"""Reproducible offline engineering workloads, never a model-quality benchmark.

Run: uv run python tests/performance_workloads.py --output /tmp/performance.json
Uses actual local ingestion, SQL persistence, context checks, vector retrieval,
concurrent pipeline and recovery with an explicitly simulated test provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import tempfile
from pathlib import Path
from time import perf_counter

import pymupdf as fitz
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from support.controlled_provider import ControlledProvider

from anki_generator.database.entities import Base, Card, Course, Document, Run
from anki_generator.orchestration.runner import DurableRunner


def workload(root: Path, name: str, documents: int, *, pdf=False, recover=False):
    from anki_generator.api import app  # noqa: F401 -- register additive entities only in parent

    root.mkdir()
    engine = create_engine(
        f"sqlite:///{root / 'application.sqlite'}", connect_args={"check_same_thread": False}
    )
    queries = 0

    @event.listens_for(engine, "before_cursor_execute")
    def count(*args):
        nonlocal queries
        queries += 1

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        course = Course(name=name, deck_name=name)
        session.add(course)
        session.flush()
        course_id = course.id
        for index in range(documents):
            suffix = ".pdf" if pdf else ".txt"
            path = root / f"source-{index}{suffix}"
            text = (
                "For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is necessary.\n"
            )
            if pdf:
                document = fitz.open()
                for page_index in range(4):
                    page = document.new_page()
                    page.insert_text((40, 50), text)
                    page.draw_line((40, 80), (180, 80 + page_index))
                document.save(path)
                document.close()
            else:
                path.write_text(text)
            data = path.read_bytes()
            session.add(
                Document(
                    course_id=course_id,
                    filename=path.name,
                    relative_path=path.name,
                    storage_path=path.name,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    mime_type="application/pdf" if pdf else "text/plain",
                    category="exercises" if index % 3 == 1 else "lecture",
                    authority="official",
                )
            )
    provider = ControlledProvider()
    if recover:
        provider.fail_stage = "pedagogical"
        provider.fail_once = True
    runner = DurableRunner(
        sessions, root, lambda: "controlled-offline-only", lambda key, config: provider
    )

    def run():
        with sessions.begin() as session:
            job = Run(
                course_id=course_id,
                request={"consent": True},
                config={
                    "coverage_rounds": 0,
                    "processing": {"concurrency": 4, "api_concurrency": 2},
                },
            )
            session.add(job)
            session.flush()
            identifier = job.id
        started = perf_counter()
        runner.run_now(identifier)
        recovery = None
        with sessions() as session:
            job = session.get(Run, identifier)
            if job.status == "failed" and recover:
                recovery = {
                    "initial_checkpoints": len(job.checkpoints),
                    "initial_calls": sum(provider.calls.values()),
                }
        if recovery:
            # A fresh runner instance models process restart using the same DB/artifacts.
            restarted = DurableRunner(
                sessions, root, lambda: "controlled-offline-only", lambda key, config: provider
            )
            restarted.retry(identifier)
            restarted.run_now(identifier)
            restarted.stop()
            recovery["final_calls"] = sum(provider.calls.values())
        elapsed = perf_counter() - started
        with sessions() as session:
            job = session.get(Run, identifier)
            if job.status != "completed":
                raise RuntimeError(job.error)
            return {
                "elapsed_seconds": elapsed,
                "recovery": recovery,
                "usage": job.usage,
                "stage_unit_seconds": job.metrics.get("stage_seconds"),
                "cards": job.metrics.get("cards_total"),
                "context_budget": 24000,
            }

    started_queries = queries
    cold = run()
    hot = run()
    result = {
        "name": name,
        "documents": documents,
        "pages": documents * (4 if pdf else 1),
        "cold": cold,
        "cached": hot,
        "sql_statements": queries - started_queries,
        "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "provider": "explicit_test_simulation_no_live_latency_or_quality_claim",
    }
    runner.stop()
    engine.dispose()
    return result


def retrieval_and_collection(root: Path, size: int):
    import numpy as np

    from anki_generator.services.semantic import SemanticIndex

    rng = np.random.default_rng(42)
    vectors = {str(index): list(rng.normal(size=128)) for index in range(size)}
    started = perf_counter()
    index = SemanticIndex(vectors)
    for query in list(vectors.values())[:100]:
        index.search(query, limit=12)
    retrieval = perf_counter() - started
    engine = create_engine(f"sqlite:///{root / 'collection.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        course = Course(name="collection", deck_name="collection")
        session.add(course)
        session.flush()
        course_id = course.id
        session.add_all(
            Card(
                course_id=course_id,
                question=f"Target {number}",
                answer="Answer",
                tags=["performance"],
            )
            for number in range(size)
        )
    started = perf_counter()
    with sessions() as session:
        rows = list(
            session.scalars(
                select(Card)
                .where(Card.course_id == course_id)
                .order_by(Card.created_at, Card.id)
                .offset(size // 2)
                .limit(25)
            )
        )
    page_seconds = perf_counter() - started
    engine.dispose()
    return {
        "cards": size,
        "retrieval_build_and_100_queries_seconds": retrieval,
        "matrix_bytes": index.matrix.nbytes,
        "paginated_25_cards_seconds": page_seconds,
        "returned": len(rows),
        "vectors": "seeded_random_for_memory_and_runtime_only",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="anki-performance-") as temporary:
        root = Path(temporary)
        reports = [
            workload(root / name, name, count, pdf=pdf)
            for name, count, pdf in [
                ("small", 3, False),
                ("medium", 24, False),
                ("large", 100, False),
                ("many_short", 200, False),
                ("mathematics_visual", 3, True),
            ]
        ]
        reports.append(workload(root / "restart_recovery", "restart_recovery", 24, recover=True))
        collections = [retrieval_and_collection(root, size) for size in (1000, 10000)]
    args.output.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "measured_at": "2026-11-09",
                "pipeline": reports,
                "collections": collections,
                "limitations": [
                    "No real API calls; token usage is simulated and cost cannot be inferred.",
                    "RSS is the process cumulative high-water mark; "
                    "memory is not isolated per workload.",
                    "Timings are local single-run observations, not service-level guarantees.",
                ],
            },
            indent=2,
        )
    )
    print(args.output)


if __name__ == "__main__":
    main()
