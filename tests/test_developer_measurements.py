"""Opt-in measurements preserve pipeline behavior and distinguish observed scopes."""
# ruff: noqa: F811 -- pytest intentionally reuses the shared isolated fixture.

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from test_pipeline_jobs import setup_course  # noqa: F401

from anki_generator.database.entities import Run
from anki_generator.llm.provider import OpenAIProvider, ProviderError
from anki_generator.processing.contracts import EvidenceReference
from anki_generator.processing.evidence import EvidenceIndex
from anki_generator.services.measurements import PipelineMeasurements


def test_thread_safe_counts_failed_spans_and_scope_labels():
    recorder = PipelineMeasurements()

    def work(_):
        for _ in range(100):
            recorder.count("retrieval", "queries")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, range(4)))
    with pytest.raises(ValueError), recorder.measure("symbolic", operation="calculation"):
        raise ValueError("Untrusted course text does not belong in telemetry")
    report = recorder.snapshot()
    assert report["counts"]["retrieval"]["queries"] == 400
    span = report["spans"]["symbolic"]["calculation"]
    assert span["count"] == span["failed"] == 1
    assert span["wall_seconds_sum"] >= 0
    assert span["initiating_thread_cpu_seconds_sum"] >= 0
    assert "Untrusted course text" not in json.dumps(report)
    assert "shared" in report["scopes"]["memory"]
    assert "excludes child processes" in report["scopes"]["cpu"]
    report["counts"]["retrieval"]["queries"] = 0
    assert recorder.snapshot()["counts"]["retrieval"]["queries"] == 400


def test_usage_has_partial_costs_and_never_invents_failure_tokens():
    recorder = PipelineMeasurements()
    recorder.record_usage(
        "generation",
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 40},
            "retry_count": 2,
            "estimated_cost_usd": 0.012,
            "private_field": "NEVER-COPY-RAW-USAGE",
        },
        model="known-test-model",
    )
    recorder.record_usage("generation", {"input_tokens": 10}, model="unknown-test-model")
    recorder.provider_measurement(
        {
            "kind": "api_attempt",
            "operation": "generation",
            "outcome": "failed",
            "wall_seconds": 0.1,
            "thread_cpu_seconds": 0.02,
            "error": "private provider message",
        }
    )
    report = recorder.snapshot()
    row = report["usage"]["generation"]
    assert row["responses"] == 2 and row["input_tokens"] == 110
    assert row["cached_input_tokens"] == 40
    assert row["retry_count_successful_responses"] == 2
    assert row["unpriced_responses"] == 1
    assert row["unmeasured_response_fields"]["output_tokens"] == 1
    assert row["estimated_cost_usd_known_sum"] == 0.012
    assert report["counts"]["generation"]["physical_api_failures"] == 1
    assert "private" not in json.dumps(report)


def test_missing_usage_is_unknown_and_worker_resources_have_separate_scope():
    recorder = PipelineMeasurements()
    recorder.record_usage("factual", {}, model="unknown-model")
    recorder.record_subprocess(
        "extraction",
        {
            "worker_wall_seconds": 1.2,
            "worker_cpu_seconds": 0.6,
            "worker_peak_rss_bytes": 1024,
            "pdf_render_seconds": 0.3,
            "pdf_regions_rendered": 4,
            "source_text": "never save this content",
        },
    )
    recorder.record_subprocess("extraction", {"worker_peak_rss_bytes": 512})
    report = recorder.snapshot()
    assert report["usage"]["factual"]["input_tokens"] is None
    assert report["usage"]["factual"]["cached_input_tokens"] is None
    assert report["usage"]["factual"]["unmeasured_response_fields"]["input_tokens"] == 1
    child = report["subprocesses"]["extraction"]
    assert child["reports"] == 2 and child["worker_peak_rss_bytes_max"] == 1024
    assert child["pdf_render_seconds_sum"] == 0.3 and child["pdf_regions_rendered"] == 4
    assert "never save" not in json.dumps(report)
    recorder.record_usage(
        "invalid-metadata", {"input_tokens": 10**1000, "output_tokens": float("nan")}, model="test"
    )
    assert recorder.snapshot()["usage"]["invalid-metadata"]["input_tokens"] is None
    with pytest.raises(ValueError, match="finite"):
        recorder.count("invalid-metadata", "unsafe-count", 10**1000)


def test_original_source_retrieval_measures_counts_without_logging_evidence(tmp_path):
    image = tmp_path / "original-region.png"
    image.write_bytes(b"Synthetic file used only for safe path selection")
    recorder = PipelineMeasurements()
    evidence = EvidenceIndex(
        [
            {
                "id": "doc",
                "filename": "PRIVATE-NAME.pdf",
                "category": "lecture",
                "extraction": {
                    "artifact_dir": ".",
                    "pages": [
                        {
                            "page_number": 1,
                            "text": "PRIVATE-SOURCE-CONTENT",
                            "regions": [
                                {
                                    "id": "p1-r1",
                                    "image_path": image.name,
                                    "bbox": [0, 0, 100, 100],
                                }
                            ],
                        }
                    ],
                },
            }
        ],
        tmp_path,
        measurements=recorder,
    )
    refs = [EvidenceReference(document_id="doc", page_number=1, quote="PRIVATE-SOURCE-CONTENT")]
    assert evidence.sources(refs)[0]["text"] == "PRIVATE-SOURCE-CONTENT"
    assert evidence.image_paths(refs) == [image]
    report = recorder.snapshot()
    assert report["counts"]["source_retrieval"]["pages_returned"] == 1
    assert report["counts"]["source_retrieval"]["image_paths_returned"] == 1
    assert "PRIVATE" not in json.dumps(report) and str(tmp_path) not in json.dumps(report)


def test_actual_sdk_invocation_attempts_count_retries_and_permanent_failure():
    class Answer(BaseModel):
        answer: str

    responses = iter(
        [
            TimeoutError("KEY-and-private-source"),
            SimpleNamespace(
                status="completed",
                output=[],
                output_parsed=Answer(answer="Observed test response"),
                usage=SimpleNamespace(
                    model_dump=lambda: {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "total_tokens": 12,
                    }
                ),
                model="test-model",
                id="test-response",
            ),
        ]
    )

    def parse(**kwargs):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    recorder = PipelineMeasurements()
    provider = OpenAIProvider(
        "KEY-and-private-source",
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
        sleep=lambda _: None,
        on_measurement=recorder.provider_measurement,
        on_event=recorder.resource_event,
    )
    result = provider.structured("factual", {"source": "private"}, Answer, model="test-model")
    recorder.record_usage("factual", result.usage, model=result.model)
    row = recorder.snapshot()["counts"]["factual"]
    assert row["physical_api_attempts"] == 2
    assert row["physical_api_completions"] == row["physical_api_failures"] == 1
    assert row["retry_events"] == 1
    assert "KEY-and-private-source" not in json.dumps(recorder.snapshot())
    provider.client.responses.parse = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("unexposed SDK failure")
    )
    with pytest.raises(ProviderError):
        provider.structured("factual", {}, Answer, model="test-model")
    assert recorder.snapshot()["counts"]["factual"]["physical_api_attempts"] == 3
    assert recorder.snapshot()["usage"]["factual"]["responses"] == 1


def test_pipeline_opt_in_measurements_persist_cache_and_failure_without_gui_changes(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    recorders = {}

    def factory(run_id):
        recorder = PipelineMeasurements()
        recorders[run_id] = recorder
        return recorder

    runner.profiler_factory = factory
    first = new_run()
    runner.run_now(first)
    with sessions() as session:
        run = session.get(Run, first)
        assert run.status == "completed", run.error
        data = run.metrics["developer_measurements"]
        assert sum(item["responses"] for item in data["usage"].values()) == sum(
            provider.calls.values()
        )
        assert data["counts"]["semantic_vectors"]["cache_misses"] > 0
        assert data["spans"]["retrieval"]["cosine_search"]["count"] > 0
    before = dict(provider.calls)
    second = new_run()
    runner.run_now(second)
    with sessions() as session:
        run = session.get(Run, second)
        assert run.status == "completed", run.error
        data = run.metrics["developer_measurements"]
        assert data["usage"] == {}
        assert data["counts"]["semantic_vectors"]["cache_hits"] > 0
    assert dict(provider.calls) == before
    assert first in recorders and second in recorders

    failed = new_run()
    with sessions.begin() as session:
        run = session.get(Run, failed)
        run.config = {**run.config, "prompt_overrides": {"knowledge": "Force a new test call"}}
    provider.fail_stage = "knowledge"
    runner.run_now(failed)
    with sessions() as session:
        run = session.get(Run, failed)
        assert run.status == "failed"
        data = run.metrics["developer_measurements"]
        assert data["spans"]["pipeline"]["stage"]["failed"] == 1
        assert data["spans"]["knowledge"]["response_unit"]["failed"] >= 1
        assert len(run.metrics["developer_measurement_attempts"]) == 1
    provider.fail_stage = None
    runner.retry(failed)
    runner.run_now(failed)
    with sessions() as session:
        run = session.get(Run, failed)
        assert run.status == "completed", run.error
        assert len(run.metrics["developer_measurement_attempts"]) == 2
        first_attempt, second_attempt = run.metrics["developer_measurement_attempts"]
        assert first_attempt["spans"]["pipeline"]["stage"]["failed"] == 1
        assert second_attempt["spans"]["pipeline"]["stage"]["failed"] == 0
