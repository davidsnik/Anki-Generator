"""Real threaded admission/retry behavior; transports never make network calls."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from anki_generator.llm.provider import OpenAIProvider, ProviderError, retry_after_seconds
from anki_generator.orchestration.resources import GlobalResources
from anki_generator.processing.pipeline import CoursePipeline
from anki_generator.services.task_options import TaskOptions


def wait_for(predicate):
    deadline = time.monotonic() + 4
    while not predicate():
        assert time.monotonic() < deadline, "Expected synchronized resource state was not reached"
        threading.Event().wait(0.005)


class Stopped(Exception):
    pass


class Answer(BaseModel):
    answer: str


class StatusError(Exception):
    def __init__(self, status, headers=None):
        self.status_code = status
        self.response = SimpleNamespace(headers=httpx.Headers(headers or {}))
        super().__init__("Private provider message with secret-key and source contents")


def structured_response():
    return SimpleNamespace(
        status="completed",
        output_parsed=Answer(answer="Supported"),
        output=[],
        usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 1, "output_tokens": 1}),
        model="controlled",
        id="controlled-response",
    )


def invoke(provider):
    return provider.structured("factual", {}, Answer, model="controlled")


def test_fair_api_queue_alternates_jobs_and_is_fifo_within_each_job():
    resources = GlobalResources(TaskOptions(api_concurrency=1))
    admitted = []

    def request(job, index):
        with resources.api(job, "model"):
            admitted.append((job, index))

    with ThreadPoolExecutor(max_workers=6) as workers:
        with resources.api("occupant", "model"):
            futures = []
            for job in ("a", "b"):
                for index in range(3):
                    futures.append(workers.submit(request, job, index))
                    wait_for(
                        lambda j=job, n=index + 1: (
                            resources.snapshot()["api_waiting_by_job"].get(j) == n
                        )
                    )
        for future in futures:
            future.result(timeout=4)
    assert admitted == [(job, index) for index in range(3) for job in ("a", "b")]
    assert resources.snapshot()["api_active"] == resources.snapshot()["api_waiting"] == 0


def test_global_and_per_job_limits_prove_independent_jobs_overlap():
    resources = GlobalResources(TaskOptions(api_concurrency=2, per_job_api_concurrency=1))
    release = threading.Event()
    active = set()
    lock = threading.Lock()
    maximum = 0

    def request(job):
        nonlocal maximum
        with resources.api(job, "model"):
            with lock:
                active.add(job)
                maximum = max(maximum, len(active))
            assert release.wait(timeout=5)
            with lock:
                active.remove(job)

    with ThreadPoolExecutor(max_workers=6) as workers:
        futures = [workers.submit(request, job) for job in ("a", "a", "a", "b", "b", "b")]
        try:
            wait_for(lambda: resources.snapshot()["api_active"] == 2)
            wait_for(lambda: resources.snapshot()["api_waiting"] == 4)
            assert active == {"a", "b"}
            assert resources.snapshot()["api_active_by_job"] == {"a": 1, "b": 1}
            assert resources.snapshot()["api_waiting"] == 4
        finally:
            release.set()
        for future in futures:
            future.result(timeout=4)
    assert maximum == 2


def test_saturated_model_does_not_block_other_models():
    resources = GlobalResources(TaskOptions(api_concurrency=3, per_model_concurrency={"slow": 1}))
    release = threading.Event()
    other_entered = threading.Event()

    def request(job, model):
        with resources.api(job, model):
            if model == "other":
                other_entered.set()
            assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as workers:
        with resources.api("first", "slow"):
            slow = workers.submit(request, "second", "slow")
            wait_for(lambda: resources.snapshot()["api_waiting"] == 1)
            other = workers.submit(request, "third", "other")
            try:
                assert other_entered.wait(timeout=3)
                assert resources.snapshot()["api_active_by_model"] == {"slow": 1, "other": 1}
            finally:
                release.set()
        slow.result(timeout=4)
        other.result(timeout=4)


def test_live_limit_changes_drain_existing_requests_and_wake_waiters():
    resources = GlobalResources(TaskOptions(api_concurrency=1))
    entered = threading.Event()
    release = threading.Event()

    def pending():
        with resources.api("new", "model"):
            entered.set()
            assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as workers:
        with resources.api("existing", "model"):
            future = workers.submit(pending)
            wait_for(lambda: resources.snapshot()["api_waiting"] == 1)
            resources.configure(TaskOptions(api_concurrency=2))
            try:
                assert entered.wait(timeout=3)
                resources.configure(TaskOptions(api_concurrency=1))
                assert resources.snapshot()["api_active"] == 2
            finally:
                release.set()
        future.result(timeout=4)
    assert resources.snapshot()["api_active"] == 0
    assert resources.snapshot()["api_concurrency"] == 1


def test_vision_bytes_are_read_and_encoded_only_after_shared_admission(tmp_path, monkeypatch):
    resources = GlobalResources(TaskOptions(api_concurrency=1))
    image = tmp_path / "region.png"
    image.write_bytes(b"Small synthetic image content for request admission")
    reads = []
    original_read = Path.read_bytes

    def read(path):
        if path == image:
            reads.append(path)
            assert resources.snapshot()["api_active_by_job"] == {"vision": 1}
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    provider = OpenAIProvider(
        "synthetic",
        resources=resources,
        job_id="vision",
        client=SimpleNamespace(
            responses=SimpleNamespace(parse=lambda **kwargs: structured_response())
        ),
    )
    with ThreadPoolExecutor(max_workers=1) as worker:
        with resources.api("occupant", "model"):
            future = worker.submit(
                provider.structured, "factual", {}, Answer, model="controlled", images=[image]
            )
            wait_for(lambda: resources.snapshot()["api_waiting"] == 1)
            assert reads == []
        assert future.result(timeout=3).data.answer == "Supported"
    assert reads == [image]


def test_failed_sdk_request_is_not_retained_during_backoff():
    import gc
    import weakref

    references = []

    def request(**kwargs):
        if not references:
            error = StatusError(429, {"Retry-After": "1"})
            error.private_large_request = bytearray(1024)
            references.append(weakref.ref(error))
            raise error
        return structured_response()

    def backoff(delay):
        gc.collect()
        assert references[0]() is None

    provider = OpenAIProvider(
        "synthetic",
        sleep=backoff,
        client=SimpleNamespace(responses=SimpleNamespace(parse=request)),
    )
    assert invoke(provider).usage["retry_count"] == 1


def test_waiting_job_can_stop_without_occupying_or_leaking_capacity():
    resources = GlobalResources(TaskOptions(api_concurrency=1))
    stopped = threading.Event()

    def checkpoint():
        if stopped.is_set():
            raise Stopped()

    def waiting():
        with resources.api("cancelled", "model", checkpoint=checkpoint):
            pytest.fail("Cancelled waiter was admitted")

    with ThreadPoolExecutor(max_workers=1) as workers:
        with resources.api("other", "model"):
            future = workers.submit(waiting)
            wait_for(lambda: resources.snapshot()["api_waiting"] == 1)
            stopped.set()
            with pytest.raises(Stopped):
                future.result(timeout=3)
            assert resources.snapshot()["api_waiting"] == 0
            assert resources.snapshot()["api_active"] == 1
    assert resources.snapshot()["api_active"] == 0


def test_stop_after_admission_prevents_request_work_and_releases_capacity():
    resources = GlobalResources()

    def checkpoint():
        if resources.snapshot()["api_active"]:
            raise Stopped()

    with pytest.raises(Stopped):
        with resources.api("pausing", "model", checkpoint=checkpoint):
            pytest.fail("Work started after interruption at admission")
    assert resources.snapshot()["api_active"] == resources.snapshot()["api_waiting"] == 0


def test_local_subprocess_budget_is_bounded_and_separate_from_api_capacity():
    resources = GlobalResources(TaskOptions(local_concurrency=2, api_concurrency=1))
    release = threading.Event()

    def local(job):
        with resources.local(job):
            assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=3) as workers:
        futures = [workers.submit(local, job) for job in ("a", "b", "c")]
        try:
            wait_for(lambda: resources.snapshot()["local_active"] == 2)
            wait_for(lambda: resources.snapshot()["local_waiting"] == 1)
            with resources.api("independent", "model"):
                assert resources.snapshot()["api_active"] == 1
                assert resources.snapshot()["local_active"] == 2
        finally:
            release.set()
        for future in futures:
            future.result(timeout=3)
    assert resources.snapshot()["local_active"] == 0


@pytest.mark.parametrize("value,expected", [("7", 7), ("2.5", 2.5), ("-1", 0), ("NaN", None)])
def test_retry_after_seconds_are_finite_and_nonnegative(value, expected):
    assert retry_after_seconds(StatusError(429, {"Retry-After": value})) == expected


def test_retry_after_supports_http_dates_and_precise_sdk_milliseconds():
    now = 1700000000
    date = format_datetime(datetime.fromtimestamp(now + 13, UTC), usegmt=True)
    assert retry_after_seconds(StatusError(429, {"Retry-After": date}), now=now) == 13
    assert retry_after_seconds(StatusError(429, {"Retry-After-Ms": "250"})) == 0.25
    assert retry_after_seconds(StatusError(429, {"Retry-After": "not a date"})) is None


@pytest.mark.parametrize("status", [401, 403, 400, 404, 422])
def test_permanent_errors_fail_immediately_and_diagnostics_omit_private_messages(status):
    events = []
    sleeps = []
    calls = []

    def request(**kwargs):
        calls.append(True)
        raise StatusError(status, {"Retry-After": "5"})

    provider = OpenAIProvider(
        "synthetic-secret",
        client=SimpleNamespace(responses=SimpleNamespace(parse=request)),
        resources=GlobalResources(),
        on_event=events.append,
        sleep=sleeps.append,
    )
    with pytest.raises(ProviderError):
        invoke(provider)
    assert len(calls) == 1 and not sleeps
    assert events[-1]["kind"] == "api_failure"
    assert "secret" not in str(events) and "source contents" not in str(events)
    assert provider.resources.snapshot()["api_active"] == 0


@pytest.mark.parametrize(
    "failure",
    [StatusError(429, {"Retry-After": "1"}), TimeoutError(), StatusError(503)],
    ids=["rate-limit", "timeout", "overload"],
)
def test_retrying_job_releases_global_slot_during_backoff_for_other_job(failure):
    resources = GlobalResources(TaskOptions(api_concurrency=1))
    backoff_entered = threading.Event()
    allow_retry = threading.Event()
    attempts = []

    def limited(**kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise failure
        return structured_response()

    def sleep(delay):
        assert delay == 1
        backoff_entered.set()
        assert allow_retry.wait(timeout=5)

    first = OpenAIProvider(
        "synthetic",
        client=SimpleNamespace(responses=SimpleNamespace(parse=limited)),
        resources=resources,
        job_id="limited",
        sleep=sleep,
        jitter=lambda: 0.5,
    )
    second = OpenAIProvider(
        "synthetic",
        client=SimpleNamespace(
            responses=SimpleNamespace(parse=lambda **kwargs: structured_response())
        ),
        resources=resources,
        job_id="independent",
    )
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(invoke, first)
        try:
            assert backoff_entered.wait(timeout=3)
            assert resources.snapshot()["api_active"] == 0
            assert invoke(second).data.answer == "Supported"
        finally:
            allow_retry.set()
        assert future.result(timeout=4).usage["retry_count"] == 1
    assert len(attempts) == 2 and resources.snapshot()["api_active"] == 0


def test_pause_interrupts_real_backoff_without_becoming_provider_error():
    stopped = threading.Event()
    retry_started = threading.Event()
    attempts = []

    def checkpoint():
        if stopped.is_set():
            raise Stopped()

    def request(**kwargs):
        attempts.append(True)
        raise StatusError(503, {"Retry-After": "30"})

    def event(value):
        if value["kind"] == "api_retry":
            retry_started.set()

    resources = GlobalResources()
    provider = OpenAIProvider(
        "synthetic",
        client=SimpleNamespace(responses=SimpleNamespace(parse=request)),
        resources=resources,
        checkpoint=checkpoint,
        on_event=event,
    )
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(invoke, provider)
        try:
            assert retry_started.wait(timeout=3)
            stopped.set()
            with pytest.raises(Stopped):
                future.result(timeout=3)
        finally:
            stopped.set()
    assert len(attempts) == 1 and resources.snapshot()["api_active"] == 0


def test_server_delay_beyond_bounded_policy_does_not_retry_early():
    calls = []
    sleeps = []

    def request(**kwargs):
        calls.append(True)
        raise StatusError(429, {"Retry-After": "121"})

    provider = OpenAIProvider(
        "synthetic",
        client=SimpleNamespace(responses=SimpleNamespace(parse=request)),
        sleep=sleeps.append,
    )
    with pytest.raises(ProviderError, match="automatic retry limit"):
        invoke(provider)
    assert len(calls) == 1 and not sleeps


def test_embeddings_and_responses_share_one_physical_request_budget():
    resources = GlobalResources(TaskOptions(api_concurrency=1))
    response_entered = threading.Event()
    release_response = threading.Event()
    embedding_entered = threading.Event()

    def response(**kwargs):
        response_entered.set()
        assert release_response.wait(timeout=5)
        return structured_response()

    def embedding(**kwargs):
        embedding_entered.set()
        return SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[1.0, 0.0])],
            model="embedding",
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 1, "total_tokens": 1}),
        )

    client = SimpleNamespace(
        responses=SimpleNamespace(parse=response), embeddings=SimpleNamespace(create=embedding)
    )
    first = OpenAIProvider("synthetic", client=client, resources=resources, job_id="responses")
    second = OpenAIProvider("synthetic", client=client, resources=resources, job_id="embeddings")
    with ThreadPoolExecutor(max_workers=2) as workers:
        response_future = workers.submit(invoke, first)
        assert response_entered.wait(timeout=3)
        embedding_future = workers.submit(second.embed, ["target"], model="embedding", dimensions=2)
        try:
            wait_for(lambda: resources.snapshot()["api_waiting"] == 1)
            assert not embedding_entered.is_set()
        finally:
            release_response.set()
        assert response_future.result(timeout=4).data.answer == "Supported"
        assert embedding_future.result(timeout=4).vectors == [[1.0, 0.0]]
    assert resources.snapshot()["api_active"] == 0


def test_sdk_client_ownership_closes_internal_clients_once_and_preserves_injected_clients(
    monkeypatch,
):
    closed = []
    client = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: client)
    owned = OpenAIProvider("synthetic")
    bound = owned.with_resources(GlobalResources(), "job")
    assert bound.close_owned_client() and bound.close_owned_client()
    assert closed == [True]
    shared = OpenAIProvider("synthetic", client=client)
    assert shared.with_resources(GlobalResources(), "another-job").close_owned_client()
    assert closed == [True]


@pytest.mark.parametrize("outcome", [None, Stopped(), ProviderError("Curated failure")])
def test_pipeline_finally_closes_owned_transport_on_success_pause_and_failure(monkeypatch, outcome):
    closed = []
    monkeypatch.setattr(
        "openai.OpenAI", lambda **kwargs: SimpleNamespace(close=lambda: closed.append(True))
    )
    pipeline = CoursePipeline.__new__(CoursePipeline)
    pipeline._state_lock = threading.RLock()
    pipeline.provider = OpenAIProvider("synthetic")

    def execute_work():
        if outcome:
            raise outcome

    pipeline._execute = execute_work
    if outcome:
        with pytest.raises(type(outcome)) as caught:
            pipeline.execute()
        assert caught.value is outcome
    else:
        pipeline.execute()
    assert pipeline.provider is None and closed == [True]
