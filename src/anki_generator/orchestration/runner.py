"""Durable, bounded concurrent course jobs with a SQLite admission boundary."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import Any

from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

from anki_generator.database.entities import Run, Stage
from anki_generator.llm import OpenAIProvider, Provider, ProviderError
from anki_generator.orchestration.job_states import EXECUTING, RECOVERABLE, transition
from anki_generator.services.task_events import add_event
from anki_generator.services.task_order import queued_order


class RunInterrupted(Exception):
    """A requested safe checkpoint was reached."""


class DurableRunner:
    def __init__(
        self,
        session_factory: Callable[..., Any],
        data_root: Path,
        key_getter: Callable[[], str | None],
        provider_factory: Callable[[str, dict[str, Any]], Provider] | None = None,
    ):
        from anki_generator.orchestration.resources import GlobalResources
        from anki_generator.services.settings import get_settings

        self.session_factory = session_factory
        self.data_root = data_root.resolve()
        self.key_getter = key_getter
        self.provider_factory = provider_factory or (lambda key, config: OpenAIProvider(key))
        self.resources = GlobalResources(get_settings(session_factory).tasks)
        self._wake = threading.Event()
        self._stop = threading.Event()
        # Backup/restore owns this gate to exclude new admissions. Job work never
        # holds it; independent course pipelines therefore execute concurrently.
        self._run_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._active: dict[str, threading.Thread] = {}
        self._courses: dict[str, str] = {}
        self._managed: set[str] = set()
        self._recovered = False
        self._scheduler_error: str | None = None

    @contextmanager
    def _write(self) -> Iterator[Any]:
        # Claim/control transactions are short, serialized SQLite writes. No
        # parser, provider call or semaphore wait occurs inside this transaction.
        with self.session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def wake(self) -> None:
        self._wake.set()

    def scheduler_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "active_run_ids": list(self._active),
                "dispatcher_running": bool(self._thread and self._thread.is_alive()),
                "stopping": self._stop.is_set(),
                "max_concurrent_jobs": self.resources.max_concurrent_jobs,
                "error": self._scheduler_error,
            }

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                if self._stop.is_set():
                    raise ValueError("The previous processing workers are still stopping.")
                return
            with self._state_lock:
                if self._stop.is_set() and any(t.is_alive() for t in self._active.values()):
                    raise ValueError("The previous processing workers are still stopping.")
            self._stop.clear()
            self._recovered = False
            # Usually recovery is synchronous at startup. A held maintenance gate
            # defers it to the dispatcher without blocking the maintenance owner.
            if self._run_lock.acquire(blocking=False):
                try:
                    self._recover()
                finally:
                    self._run_lock.release()
            self._thread = threading.Thread(
                target=self._work, name="anki-job-scheduler", daemon=True
            )
            self._thread.start()

    def _recover(self) -> None:
        with self._state_lock:
            owned = set(self._active)
        with self._write() as session:
            query = select(Run).where(Run.status.in_(RECOVERABLE))
            if owned:
                query = query.where(Run.id.not_in(owned))
            for run in session.scalars(query):
                previous = run.status
                target = (
                    "cancelled" if run.cancel_requested or previous == "cancelling" else "paused"
                )
                durable_end = run.updated_at
                if previous in EXECUTING:
                    transition(session, run, "interrupted", ended_at=durable_end)
                transition(
                    session,
                    run,
                    target,
                    message="Interrupted processing recovered; checkpoints were retained.",
                    ended_at=durable_end,
                    details={"interrupted_state": previous, "clock_basis": "last_durable_update"},
                )
                run.recovery_count = int(run.recovery_count or 0) + 1
                if target == "paused":
                    run.error = (
                        "Processing was interrupted by application shutdown. "
                        "Resume to reuse saved checkpoints."
                    )
                for stage in session.scalars(
                    select(Stage).where(Stage.run_id == run.id, Stage.status.in_(RECOVERABLE))
                ):
                    stage.status = target
        self._recovered = True

    def stop(self, timeout: float = 5) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            self.wake()
            deadline = monotonic() + max(0, timeout)
            dispatcher = self._thread
            if dispatcher:
                if dispatcher is threading.current_thread():
                    raise ValueError("The scheduler cannot join its own thread during shutdown.")
                dispatcher.join(timeout=max(0, deadline - monotonic()))
            with self._state_lock:
                workers = list(self._active.values())
            for worker in workers:
                if worker is not threading.current_thread():
                    worker.join(timeout=max(0, deadline - monotonic()))
            if (dispatcher and dispatcher.is_alive()) or any(
                worker.is_alive() for worker in workers
            ):
                raise ValueError(
                    "A processing worker is still finishing an in-flight operation. "
                    "Storage was not released; wait for a safe checkpoint "
                    "before retrying maintenance."
                )
            self._thread = None

    def enqueue(self, run_id: str) -> None:
        with self._write() as session:
            run = self._get_run(session, run_id)
            if run.status == "prepared":
                transition(session, run, "queued")
            elif run.status not in {"queued", *EXECUTING}:
                raise ValueError("Use resume or retry for this job's current state.")
        self.wake()

    def pause(self, run_id: str) -> None:
        with self._write() as session:
            run = self._get_run(session, run_id)
            if run.status == "queued":
                transition(session, run, "paused")
            elif run.status == "running":
                transition(
                    session,
                    run,
                    "pausing",
                    message="Pause requested; waiting for a safe checkpoint.",
                )
            elif run.status not in {"pausing", "paused"}:
                raise ValueError("Only a queued or running job can be paused.")
        self.wake()

    def cancel(self, run_id: str) -> None:
        with self._write() as session:
            run = self._get_run(session, run_id)
            if run.status in {"running", "pausing"}:
                transition(
                    session,
                    run,
                    "cancelling",
                    message="Cancellation requested; in-flight work may finish.",
                )
            elif run.status in {
                "prepared",
                "queued",
                "paused",
                "failed",
                "interrupted",
                "recovering",
            }:
                transition(session, run, "cancelled")
            elif run.status not in {"cancelling", "cancelled"}:
                raise ValueError("This job is already finished.")
        self.wake()

    def resume(self, run_id: str) -> None:
        self._resume(run_id, {"paused"})

    def retry(self, run_id: str) -> None:
        self._resume(run_id, {"failed"})

    def _resume(self, run_id: str, allowed: set[str]) -> None:
        with self._write() as session:
            run = self._get_run(session, run_id)
            if run.status not in allowed:
                raise ValueError("This run cannot be resumed or retried in its current state.")
            transition(session, run, "queued")
        self.wake()

    @staticmethod
    def _get_run(session: Any, run_id: str) -> Run:
        run = session.get(Run, run_id)
        if run is None:
            raise ValueError("Processing run does not exist.")
        return run

    def checkpoint(self, run_id: str) -> None:
        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            if run.status not in EXECUTING:
                raise RunInterrupted
            requested = run.cancel_requested or run.pause_requested or self._stop.is_set()
        if not requested:
            return
        with self._write() as session:
            run = self._get_run(session, run_id)
            if run.status not in EXECUTING:
                raise RunInterrupted
            if run.cancel_requested or run.status == "cancelling":
                target = "cancelling"
            elif run.pause_requested or run.status == "pausing" or self._stop.is_set():
                target = "pausing"
            else:
                return
            transition(session, run, target)
        raise RunInterrupted

    def _settle_interruption(self, run_id: str) -> None:
        # CoursePipeline unwinds bounded_map's executor before this point. Every
        # in-flight provider/local unit has finished saving or failed; only now
        # are terminal controls safe for course edits and backup maintenance.
        with self._write() as session:
            run = self._get_run(session, run_id)
            if run.status not in EXECUTING:
                return
            target = "cancelled" if run.cancel_requested or run.status == "cancelling" else "paused"
            transition(session, run, target)
            for stage in session.scalars(
                select(Stage).where(Stage.run_id == run_id, Stage.status.in_(EXECUTING))
            ):
                stage.status = target

    def _reserve(self, run_id: str) -> tuple[bool, bool]:
        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            course_id = run.course_id
            if run.status != "queued":
                return False, False
        current = threading.current_thread()
        with self._state_lock:
            if run_id in self._active:
                return self._active[run_id] is current, run_id in self._managed
            if (
                len(self._active) >= self.resources.max_concurrent_jobs
                or course_id in self._courses.values()
            ):
                return False, False
            self._active[run_id] = current
            self._courses[run_id] = course_id
        return True, False

    def _claim(self, run_id: str) -> bool:
        while not self._stop.is_set():
            if self._run_lock.acquire(timeout=0.1):
                break
        else:
            return False
        try:
            if self._stop.is_set():
                return False
            with self._write() as session:
                run = self._get_run(session, run_id)
                if run.status != "queued":
                    return False
                active = session.scalar(
                    select(func.count()).select_from(Run).where(Run.status.in_(EXECUTING))
                )
                course_active = session.scalar(
                    select(Run.id)
                    .where(Run.course_id == run.course_id, Run.status.in_(EXECUTING))
                    .limit(1)
                )
                if active >= self.resources.max_concurrent_jobs or course_active:
                    return False
                transition(session, run, "running", message="Job started from the durable queue.")
            return True
        finally:
            self._run_lock.release()

    def run_now(self, run_id: str) -> None:
        """Synchronously execute one eligible job, with the same admission limits."""
        from anki_generator.processing.pipeline import CoursePipeline

        admitted, managed = self._reserve(run_id)
        if not admitted:
            return
        try:
            if not self._claim(run_id):
                return
            try:
                CoursePipeline(self, run_id).execute()
                self.checkpoint(run_id)
                from anki_generator.evaluation.service import capture_completed_run

                capture_completed_run(self.session_factory, run_id)
            except RunInterrupted:
                self._settle_interruption(run_id)
            except Exception as error:
                self._fail(run_id, error)
        finally:
            if not managed:
                self._release(run_id)

    def _fail(self, run_id: str, error: Exception) -> None:
        message = (
            str(error)
            if isinstance(error, (ProviderError, ValueError))
            else (
                "Processing failed unexpectedly. Saved checkpoints are intact; retry the run. "
                f"Diagnostic category: {type(error).__name__}."
            )
        )
        with self._write() as session:
            run = session.get(Run, run_id)
            if run is None:
                return
            if run.status in {"paused", "cancelled", "completed", "failed"}:
                add_event(session, run.id, "unit_error", message, level="warning")
                return
            target = (
                "cancelled"
                if run.cancel_requested
                else "paused"
                if run.pause_requested
                else "failed"
            )
            transition(session, run, target, message=message)
            if target == "failed":
                run.error = message
            for stage in session.scalars(
                select(Stage).where(Stage.run_id == run_id, Stage.status.in_(EXECUTING))
            ):
                stage.status = target
                stage.error = message
                stage.finished_at = run.finished_at

    def _release(self, run_id: str) -> None:
        with self._state_lock:
            if self._active.get(run_id) is threading.current_thread():
                self._active.pop(run_id, None)
                self._courses.pop(run_id, None)
                self._managed.discard(run_id)
        self.wake()

    def _run_dispatched(self, run_id: str) -> None:
        try:
            self.run_now(run_id)
        except Exception as error:
            self._fail(run_id, error)
        finally:
            self._release(run_id)

    def _schedule(self) -> None:
        while not self._stop.is_set():
            with self._state_lock:
                if len(self._active) >= self.resources.max_concurrent_jobs:
                    return
                other = aliased(Run)
                query = select(Run.id, Run.course_id).where(
                    Run.status == "queued",
                    ~exists(
                        select(other.id).where(
                            other.course_id == Run.course_id, other.status.in_(EXECUTING)
                        )
                    ),
                )
                if self._courses:
                    query = query.where(Run.course_id.not_in(set(self._courses.values())))
                with self.session_factory() as session:
                    candidate = session.execute(query.order_by(*queued_order()).limit(1)).first()
                if candidate is None:
                    return
                worker = threading.Thread(
                    target=self._run_dispatched,
                    args=(candidate.id,),
                    name=f"anki-job-{candidate.id[:8]}",
                    daemon=True,
                )
                self._active[candidate.id] = worker
                self._courses[candidate.id] = candidate.course_id
                self._managed.add(candidate.id)
                worker.start()

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                if not self._recovered:
                    if not self._run_lock.acquire(timeout=0.1):
                        continue
                    try:
                        self._recover()
                    finally:
                        self._run_lock.release()
                self._schedule()
                self._scheduler_error = None
            except SQLAlchemyError as error:
                self._scheduler_error = (
                    "The durable queue could not be read; the scheduler will retry. "
                    f"Diagnostic category: {type(error).__name__}."
                )
            self._wake.wait(timeout=0.25)
            self._wake.clear()
