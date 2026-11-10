"""Actual ranking traces stay pending until independent relevance is supplied."""
# ruff: noqa: F811 -- pytest intentionally reuses the shared isolated fixture.

import json

import pytest
from sqlalchemy import select
from test_pipeline_jobs import setup_course  # noqa: F401

from anki_generator.benchmark.retrieval_capture import RetrievalCapture
from anki_generator.database.entities import Card, Run
from anki_generator.domain import ExportInput
from anki_generator.services.exporting import create_export
from anki_generator.services.measurements import PipelineMeasurements
from anki_generator.services.semantic import SemanticIndex


def test_capture_matches_actual_ranked_results_and_does_not_invent_relevance():
    capture = RetrievalCapture(max_queries=2, max_hits=1)
    recorder = PipelineMeasurements(retrieval_observer=capture)
    index = SemanticIndex({"closest": [1.0, 0.0], "other": [0.0, 1.0]}, measurements=recorder)
    actual = index.search(
        [1.0, 0.0], query_id="query-1", stage="source_matching", query_kind="source_target"
    )
    index.search([0.0, 1.0], query_id="query-2")
    index.search([1.0, 0.0], query_id="dropped-query")
    report = capture.snapshot()
    assert report["observed_queries"] == 3 and report["captured_queries"] == 2
    assert report["dropped_queries"] == 1 and report["truncated_hits"] == 2
    first = report["cases"][0]
    assert [(hit["id"], hit["score"]) for hit in first["hits"]] == actual[:1]
    assert first["observed_hit_count"] == 2 and first["capture_truncated"]
    assert first["query"] == {"id": "query-1", "kind": "source_target"}
    assert first["judgment_status"] == "pending" and "relevance" not in first
    assert "vectors" not in first
    assert "cases" not in recorder.snapshot()  # Traces belong to private benchmark artifacts.
    report["cases"].clear()
    assert len(capture.snapshot()["cases"]) == 2


def test_observer_failure_is_explicit_sanitized_and_default_search_is_unchanged():
    def fail(event):
        raise ValueError("private source must not leak through an observer error")

    index = SemanticIndex(
        {"candidate": [1.0, 0.0]},
        measurements=PipelineMeasurements(retrieval_observer=fail),
    )
    with pytest.raises(RuntimeError, match="Developer retrieval capture failed") as caught:
        index.search([1.0, 0.0])
    assert "private" not in str(caught.value)
    assert index.measurements.snapshot()["counts"]["retrieval"]["capture_failures"] == 1
    assert SemanticIndex({"candidate": [1.0, 0.0]}).search([1.0, 0.0]) == [("candidate", 1.0)]


def test_actual_pipeline_semantic_queries_are_captured_with_production_identities(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    capture = RetrievalCapture()
    runner.profiler_factory = lambda run_id: PipelineMeasurements(
        retrieval_observer=lambda event: capture({**event, "run_id": run_id})
    )
    first = new_run()
    runner.run_now(first)
    original = provider.structured

    def structured(stage, payload, schema, **kwargs):
        result = original(stage, payload, schema, **kwargs)
        if stage == "knowledge":
            result.data.concepts[0].key = "reworded-same-target"
            result.data.concepts[0].title = "Reworded right-triangle relation"
        return result

    provider.structured = structured
    second = new_run()
    with sessions.begin() as session:
        run = session.get(Run, second)
        run.config = {**run.config, "prompt_overrides": {"knowledge": "Force identity lookup"}}
    runner.run_now(second)
    with sessions() as session:
        assert session.get(Run, second).status == "completed"
    cases = capture.snapshot()["cases"]
    assert {case["stage"] for case in cases} >= {
        "deduplication",
        "source_matching",
        "target_coverage",
        "identity",
    }
    assert all(case["query"]["id"] for case in cases)
    assert all(case["production_run_id"] in {first, second} for case in cases)
    assert all(case["judgment_status"] == "pending" for case in cases)
    assert any(case["hits"] for case in cases)
    assert "For a right triangle" not in json.dumps(cases)


def test_export_measurements_record_success_and_failures_without_bypassing_approval(setup_course):
    sessions, runner, _, new_run, course_id = setup_course
    run_id = new_run()
    runner.run_now(run_id)
    recorder = PipelineMeasurements()
    with sessions.begin() as session:
        card = session.scalar(select(Card).where(Card.course_id == course_id))
        values = ExportInput(format="apkg", card_ids=[card.id])
        with pytest.raises(ValueError, match="human-approved"):
            create_export(session, runner.data_root, course_id, values, measurements=recorder)
        card.review_status, card.verification_status = "approved", "failed"
        with pytest.raises(ValueError, match="human-approved"):
            create_export(session, runner.data_root, course_id, values, measurements=recorder)
        card.verification_status = "verified"
        result = create_export(session, runner.data_root, course_id, values, measurements=recorder)
        assert (runner.data_root / result.storage_path).is_file()
        assert result.card_count == 1
    report = recorder.snapshot()
    assert report["spans"]["export"]["apkg"]["count"] == 3
    assert report["spans"]["export"]["apkg"]["failed"] == 2
    assert report["counts"]["export"] == {"completed_exports": 1, "cards_exported": 1}
