"""Real durable scheduling and pipelines; barriers prove independent overlap."""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from support.controlled_provider import ControlledProvider

from anki_generator.database.connection import open_database
from anki_generator.database.entities import Card, Concept, Course, Document, Run, Stage
from anki_generator.database.task_entities import JobEvent
from anki_generator.llm import ProviderError
from anki_generator.orchestration.job_states import transition
from anki_generator.orchestration.runner import DurableRunner
from anki_generator.services.settings import ApplicationSettings
from anki_generator.services.source_corrections import snapshot_source_state
from anki_generator.services.task_options import TaskOptions


class BarrierProvider(ControlledProvider):
    def __init__(self, label: str):
        super().__init__()
        self.label = label
        self.entered = threading.Event()
        self.release = threading.Event()
        self.failure: str | None = None

    def structured(self, stage, payload, schema, **kwargs):
        if stage == "knowledge" and not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(15):
                raise ValueError("Controlled concurrency barrier was not released")
            if self.failure:
                raise ProviderError(
                    f"Controlled {self.failure} failure",
                    kind=self.failure,
                    retryable=self.failure in {"rate_limit", "timeout"},
                )
        result = super().structured(stage, payload, schema, **kwargs)
        if stage == "generation":
            for card in result.data.cards:
                card.question = f"[{payload['course']}] {card.question}"
        return result


class Jobs:
    def __init__(self, root: Path):
        self.root = root
        self.sessions = open_database(root)
        self.providers: dict[str, BarrierProvider] = {}
        self.counter = 0
        self.runner = DurableRunner(
            self.sessions,
            root,
            lambda: "controlled-offline-key",
            lambda key, config: self.providers[config["criteria"]["instructions"]],
        )

    def create(self, label: str, *, course_id: str | None = None, priority: int = 0):
        self.providers[label] = BarrierProvider(label)
        self.counter += 1
        with self.sessions.begin() as session:
            if course_id is None:
                course = Course(name=label, deck_name=label)
                session.add(course)
                session.flush()
                course_id = course.id
                relative = f"originals/{course.id}.txt"
                path = self.root / relative
                path.parent.mkdir(exist_ok=True)
                content = (
                    b"For a right triangle, a^2 + b^2 = c^2.\n"
                    b"The right-angle assumption is necessary.\n"
                )
                path.write_bytes(content)
                session.add(
                    Document(
                        course_id=course_id,
                        filename=f"{label}.txt",
                        relative_path=f"{label}.txt",
                        storage_path=relative,
                        sha256=hashlib.sha256(content).hexdigest(),
                        size_bytes=len(content),
                        mime_type="text/plain",
                        category="lecture",
                        authority="official",
                    )
                )
                session.flush()
            course = session.get(Course, course_id)
            config = ApplicationSettings().model_dump()
            config["criteria"]["instructions"] = label
            config["processing"].update(concurrency=1, api_concurrency=1, coverage_rounds=0)
            config["max_revisions"] = 0
            config["prompt_overrides"] = {
                "knowledge": f"Preserve evidence and assumptions. Variant {label}."
            }
            config["course_snapshot"] = {
                field: getattr(course, field)
                for field in ("name", "description", "deck_name", "language")
            }
            documents = list(
                session.scalars(select(Document).where(Document.course_id == course_id))
            )
            run = Run(
                course_id=course_id,
                request={"consent": True},
                config=config,
                priority=priority,
                created_at=(
                    datetime(2026, 11, 9, tzinfo=UTC) + timedelta(seconds=self.counter)
                ).isoformat(),
                inputs=[
                    {
                        "document_id": document.id,
                        "sha256": document.sha256,
                        "category": document.category,
                        "authority": document.authority,
                        "linked_document_id": document.linked_document_id,
                        **snapshot_source_state(session, document),
                    }
                    for document in documents
                ],
            )
            session.add(run)
            session.flush()
            return run.id, course_id

    def status(self, identifier):
        with self.sessions() as session:
            return session.get(Run, identifier).status

    def wait(self, identifier, expected, *, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.sessions() as session:
                run = session.get(Run, identifier)
                if run.status in expected:
                    return run.status
                if run.status == "failed" and "failed" not in expected:
                    pytest.fail(run.error)
            time.sleep(0.01)
        pytest.fail(f"Job {identifier} remained {self.status(identifier)}, expected {expected}")

    def release_all(self):
        for provider in self.providers.values():
            provider.release.set()

    def close(self):
        self.release_all()
        self.runner.stop()
        self.sessions.kw["bind"].dispose()


@pytest.fixture
def jobs(tmp_path):
    scenario = Jobs(tmp_path)
    try:
        yield scenario
    finally:
        scenario.close()


def test_two_courses_overlap_third_waits_then_automatically_starts_with_isolated_outputs(jobs):
    a, course_a = jobs.create("Alpha")
    b, course_b = jobs.create("Beta")
    c, course_c = jobs.create("Gamma")
    jobs.runner.start()
    assert jobs.providers["Alpha"].entered.wait(8)
    assert jobs.providers["Beta"].entered.wait(8)
    assert jobs.status(a) == jobs.status(b) == "running"
    assert jobs.status(c) == "queued"
    assert not jobs.providers["Gamma"].entered.is_set()
    jobs.runner.run_now(c)  # synchronous callers cannot bypass the global budget
    assert jobs.status(c) == "queued" and not jobs.providers["Gamma"].entered.is_set()
    jobs.providers["Alpha"].release.set()
    assert jobs.providers["Gamma"].entered.wait(10)
    assert jobs.status(b) == "running"  # Beta is still at its independent barrier.
    # A completed course can be inspected, reviewed and exported while unrelated
    # jobs still own their provider calls; no global idle screen is required.
    from anki_generator.domain import ExportInput, ReviewInput
    from anki_generator.services.exporting import create_export
    from anki_generator.services.records import review_card

    with jobs.sessions.begin() as session:
        first_card = session.scalar(select(Card).where(Card.course_id == course_a))
        assert first_card.verification_status == "verified"
        review_card(
            session, first_card, ReviewInput(decision="approved", reason="Controlled workflow test")
        )
        exported = create_export(session, jobs.root, course_a, ExportInput())
        assert exported.card_count == 1 and (jobs.root / exported.storage_path).is_file()
    assert jobs.status(b) == jobs.status(c) == "running"
    jobs.release_all()
    for identifier in (a, b, c):
        assert jobs.wait(identifier, {"completed"}) == "completed"
    with jobs.sessions() as session:
        for identifier, course_id, label in (
            (a, course_a, "Alpha"),
            (b, course_b, "Beta"),
            (c, course_c, "Gamma"),
        ):
            run = session.get(Run, identifier)
            assert run.config["criteria"]["instructions"] == label
            assert run.active_seconds > 0 and run.resumed_at is None
            card = session.scalar(select(Card).where(Card.course_id == course_id))
            concept = session.scalar(select(Concept).where(Concept.course_id == course_id))
            assert card and concept and card.question.startswith(f"[{label}]")
            assert all(
                session.get(Document, ref["document_id"]).course_id == course_id
                for ref in card.sources
            )
            assert all(
                session.get(Document, ref["document_id"]).course_id == course_id
                for ref in concept.sources
            )
            events = list(session.scalars(select(JobEvent).where(JobEvent.run_id == identifier)))
            assert {event.details.get("to") for event in events} >= {"running", "completed"}


@pytest.mark.parametrize(
    "action, pending, terminal",
    [("pause", "pausing", "paused"), ("cancel", "cancelling", "cancelled")],
)
def test_pause_or_cancel_one_job_preserves_other_job_and_releases_capacity(
    jobs, action, pending, terminal
):
    a, _ = jobs.create("Alpha")
    b, course_b = jobs.create("Beta")
    c, _ = jobs.create("Gamma")
    jobs.runner.start()
    assert jobs.providers["Alpha"].entered.wait(8)
    assert jobs.providers["Beta"].entered.wait(8)
    getattr(jobs.runner, action)(a)
    assert jobs.status(a) == pending
    assert jobs.status(b) == "running"
    jobs.providers["Alpha"].release.set()
    assert jobs.wait(a, {terminal}) == terminal
    assert jobs.providers["Gamma"].entered.wait(8)
    jobs.release_all()
    jobs.wait(b, {"completed"})
    jobs.wait(c, {"completed"})
    with jobs.sessions() as session:
        run = session.get(Run, a)
        assert run.checkpoints  # the completed in-flight result was saved
        assert session.scalar(select(Card).where(Card.course_id == course_b))
    if action == "pause":
        calls = jobs.providers["Alpha"].calls.copy()
        jobs.runner.resume(a)
        jobs.wait(a, {"completed"})
        assert jobs.providers["Alpha"].calls["knowledge"] == calls["knowledge"]


@pytest.mark.parametrize("failure", ["authentication", "invalid_output", "rate_limit", "timeout"])
def test_provider_failure_isolated_from_an_independent_running_job(jobs, failure):
    a, _ = jobs.create("Alpha")
    b, course_b = jobs.create("Beta")
    jobs.providers["Alpha"].failure = failure
    jobs.runner.start()
    assert jobs.providers["Alpha"].entered.wait(8)
    assert jobs.providers["Beta"].entered.wait(8)
    jobs.providers["Alpha"].release.set()
    jobs.wait(a, {"failed"})
    assert jobs.status(b) == "running"
    jobs.providers["Beta"].release.set()
    jobs.wait(b, {"completed"})
    with jobs.sessions() as session:
        assert failure in session.get(Run, a).error
        assert (
            session.scalar(select(Card).where(Card.course_id == course_b)).verification_status
            == "verified"
        )


def test_same_course_jobs_are_sequential_and_do_not_block_other_courses(jobs):
    a, course_a = jobs.create("First")
    again, _ = jobs.create("Second", course_id=course_a)
    other, _ = jobs.create("Other")
    jobs.runner.start()
    assert jobs.providers["First"].entered.wait(8)
    assert jobs.providers["Other"].entered.wait(8)
    assert jobs.status(again) == "queued"
    jobs.providers["First"].release.set()
    assert jobs.providers["Second"].entered.wait(10)
    assert jobs.status(other) == "running"
    assert jobs.status(a) == "completed"
    jobs.release_all()
    jobs.wait(again, {"completed"})
    jobs.wait(other, {"completed"})
    with jobs.sessions() as session:
        assert len(list(session.scalars(select(Card).where(Card.course_id == course_a)))) == 1


def test_priority_then_fifo_order_and_live_job_capacity_changes(jobs):
    jobs.runner.resources.configure(TaskOptions(max_concurrent_jobs=1))
    first, _ = jobs.create("First")
    high, _ = jobs.create("Priority", priority=10)
    last, _ = jobs.create("Last")
    jobs.runner.start()
    assert jobs.providers["Priority"].entered.wait(8)
    assert jobs.status(first) == jobs.status(last) == "queued"
    jobs.providers["Priority"].release.set()
    assert jobs.providers["First"].entered.wait(8)
    assert jobs.status(last) == "queued"
    jobs.runner.resources.configure(TaskOptions(max_concurrent_jobs=2))
    jobs.runner.wake()
    assert jobs.providers["Last"].entered.wait(8)
    assert jobs.status(first) == "running"
    jobs.runner.resources.configure(TaskOptions(max_concurrent_jobs=1))
    assert jobs.status(first) == jobs.status(last) == "running"  # draining does not stop work
    jobs.release_all()
    for identifier in (first, high, last):
        jobs.wait(identifier, {"completed"})


def test_global_api_limit_one_bounds_calls_across_two_real_jobs(jobs):
    jobs.runner.resources.configure(TaskOptions(api_concurrency=1, per_job_api_concurrency=1))
    a, _ = jobs.create("Alpha")
    b, _ = jobs.create("Beta")
    jobs.runner.start()
    deadline = time.monotonic() + 8
    while not any(provider.entered.is_set() for provider in jobs.providers.values()):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    entered = [label for label, provider in jobs.providers.items() if provider.entered.is_set()]
    assert len(entered) == 1
    other = "Beta" if entered[0] == "Alpha" else "Alpha"
    assert jobs.status(a) == jobs.status(b) == "running"
    assert jobs.runner.resources.snapshot()["api_active"] == 1
    jobs.providers[entered[0]].release.set()
    assert jobs.providers[other].entered.wait(8)
    jobs.release_all()
    jobs.wait(a, {"completed"})
    jobs.wait(b, {"completed"})


def test_restart_recovers_each_job_state_and_preserves_checkpoints(jobs):
    identifiers = []
    for label, state in (
        ("Running", "running"),
        ("Pausing", "pausing"),
        ("Cancelling", "cancelling"),
    ):
        identifier, _ = jobs.create(label)
        identifiers.append(identifier)
        with jobs.sessions.begin() as session:
            run = session.get(Run, identifier)
            run.status = state
            run.checkpoints = {"knowledge:page": "cache/preserved.json"}
            run.resumed_at = "2026-11-09T00:00:00+00:00"
            session.add(
                Stage(run_id=identifier, name="knowledge", status=state, completed=2, total=5)
            )
    jobs.runner.start()
    jobs.runner.stop()
    with jobs.sessions() as session:
        for identifier, expected in zip(
            identifiers, ("paused", "paused", "cancelled"), strict=True
        ):
            run = session.get(Run, identifier)
            assert run.status == expected and run.recovery_count == 1
            assert run.checkpoints == {"knowledge:page": "cache/preserved.json"}
            assert run.resumed_at is None
            stage = session.scalar(select(Stage).where(Stage.run_id == identifier))
            assert stage.status == expected and stage.completed == 2


def test_restarted_paused_job_reuses_real_completed_provider_checkpoint(jobs):
    identifier, _ = jobs.create("Original")
    jobs.runner.start()
    assert jobs.providers["Original"].entered.wait(8)
    jobs.runner.pause(identifier)
    jobs.providers["Original"].release.set()
    jobs.wait(identifier, {"paused"})
    jobs.runner.stop()
    calls = jobs.providers["Original"].calls.copy()
    with jobs.sessions.begin() as session:
        run = session.get(Run, identifier)
        run.status = "running"  # simulate a crash after the durable result existed
    replacement = DurableRunner(
        jobs.sessions,
        jobs.root,
        lambda: "controlled-offline-key",
        lambda key, config: jobs.providers[config["criteria"]["instructions"]],
    )
    jobs.runner = replacement
    replacement.start()
    assert jobs.status(identifier) == "paused"
    replacement.resume(identifier)
    jobs.wait(identifier, {"completed"})
    assert jobs.providers["Original"].calls["knowledge"] == calls["knowledge"]


def test_controls_validate_terminal_states_and_exclude_queued_time(jobs, monkeypatch):
    from anki_generator.orchestration import job_states

    identifier, _ = jobs.create("Controls")
    with jobs.sessions.begin() as session:
        run = session.get(Run, identifier)
        monkeypatch.setattr(job_states, "now", lambda: "2026-11-09T01:00:00+00:00")
        transition(session, run, "running")
        monkeypatch.setattr(job_states, "now", lambda: "2026-11-09T01:00:10+00:00")
        transition(session, run, "pausing")
        transition(session, run, "paused")
        assert run.active_seconds == 10
        transition(session, run, "queued")
        monkeypatch.setattr(job_states, "now", lambda: "2026-11-09T03:00:00+00:00")
        transition(session, run, "running")
        monkeypatch.setattr(job_states, "now", lambda: "2026-11-09T03:00:05+00:00")
        transition(session, run, "completed")
        assert run.active_seconds == 15
    for control in (jobs.runner.pause, jobs.runner.cancel, jobs.runner.resume, jobs.runner.retry):
        with pytest.raises(ValueError):
            control(identifier)


@pytest.mark.parametrize(
    "action, pending, terminal",
    [("pause", "pausing", "paused"), ("cancel", "cancelling", "cancelled")],
)
def test_control_remains_pending_until_all_parallel_calls_finish_before_maintenance(
    jobs, action, pending, terminal
):
    from types import SimpleNamespace

    from anki_generator.orchestration.runner import RunInterrupted
    from anki_generator.services.backups import maintenance

    identifier, _ = jobs.create("Parallel")
    provider = jobs.providers["Parallel"]
    provider.release.set()
    factual_entered, pedagogy_entered = threading.Event(), threading.Event()
    factual_release, pedagogy_release = threading.Event(), threading.Event()
    first_checkpoint = threading.Event()
    original_call = provider.structured
    original_check = jobs.runner.checkpoint

    def structured(stage, payload, schema, **kwargs):
        if stage in {"factual", "pedagogical"}:
            entered = factual_entered if stage == "factual" else pedagogy_entered
            release = factual_release if stage == "factual" else pedagogy_release
            entered.set()
            assert release.wait(10)
        return original_call(stage, payload, schema, **kwargs)

    def checkpoint(run_id):
        try:
            return original_check(run_id)
        except RunInterrupted:
            if factual_release.is_set() and not pedagogy_release.is_set():
                first_checkpoint.set()
            raise

    provider.structured = structured
    jobs.runner.checkpoint = checkpoint
    with jobs.sessions.begin() as session:
        run = session.get(Run, identifier)
        config = dict(run.config)
        config["processing"] = {**config["processing"], "concurrency": 2, "api_concurrency": 2}
        run.config = config
    jobs.runner.start()
    try:
        assert factual_entered.wait(8) and pedagogy_entered.wait(8)
        getattr(jobs.runner, action)(identifier)
        factual_release.set()
        assert first_checkpoint.wait(5)
        assert jobs.status(identifier) == pending
        assert identifier in jobs.runner.scheduler_snapshot()["active_run_ids"]
        rt = SimpleNamespace(
            access_lock=threading.Lock(),
            maintenance_mode=False,
            active_requests=0,
            sessions=jobs.sessions,
            runner=jobs.runner,
        )
        with pytest.raises(ValueError, match="active processing"):
            with maintenance(rt):
                pytest.fail("Maintenance admitted a job with an unfinished physical request")
    finally:
        factual_release.set()
        pedagogy_release.set()
    assert jobs.wait(identifier, {terminal}) == terminal


def test_aged_queued_job_cannot_be_starved_by_new_higher_priority_job(jobs):
    jobs.runner.resources.configure(TaskOptions(max_concurrent_jobs=1))
    aged, _ = jobs.create("Aged", priority=-10)
    urgent, _ = jobs.create("Urgent", priority=100)
    with jobs.sessions.begin() as session:
        session.get(Run, aged).queued_at = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    jobs.runner.start()
    assert jobs.providers["Aged"].entered.wait(8)
    assert jobs.status(urgent) == "queued"
    jobs.providers["Aged"].release.set()
    assert jobs.providers["Urgent"].entered.wait(8)
    jobs.release_all()
    jobs.wait(aged, {"completed"})
    jobs.wait(urgent, {"completed"})
