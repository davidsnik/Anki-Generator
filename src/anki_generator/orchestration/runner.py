"""A single local worker backed by SQLite, not request-scoped background tasks."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select

from anki_generator.database.entities import Run, Stage, now
from anki_generator.llm import OpenAIProvider, Provider, ProviderError


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
        self.session_factory = session_factory
        self.data_root = data_root.resolve()
        self.key_getter = key_getter
        self.provider_factory = provider_factory or (lambda key, config: OpenAIProvider(key))
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._run_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # No uncheckpointed request is assumed completed after an abrupt restart.
        with self.session_factory() as session:
            for run in session.scalars(select(Run).where(Run.status == "running")):
                run.status = "paused"
                run.error = (
                    "Processing was interrupted by application shutdown. "
                    "Resume to reuse saved checkpoints."
                )
                for stage in session.scalars(
                    select(Stage).where(Stage.run_id == run.id, Stage.status == "running")
                ):
                    stage.status = "paused"
            session.commit()
        self._stop.clear()
        self._thread = threading.Thread(target=self._work, name="anki-durable-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, run_id: str) -> None:
        with self.session_factory() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError("Processing run does not exist.")
            if run.status in {"completed", "cancelled"}:
                raise ValueError("Create a new run to process completed or cancelled work.")
            if run.status != "running":
                run.status = "queued"
                run.pause_requested = False
                run.cancel_requested = False
                run.error = None
            session.commit()
        self._wake.set()

    def pause(self, run_id: str) -> None:
        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            if run.status == "queued":
                run.status = "paused"
            elif run.status == "running":
                run.pause_requested = True
            else:
                raise ValueError("Only a queued or running job can be paused.")
            session.commit()

    def cancel(self, run_id: str) -> None:
        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            if run.status == "running":
                run.cancel_requested = True
            elif run.status in {"queued", "paused", "failed"}:
                run.status = "cancelled"
                run.finished_at = now()
            else:
                raise ValueError("This job is already finished.")
            session.commit()

    def resume(self, run_id: str) -> None:
        self._resume(run_id, {"paused"})

    def retry(self, run_id: str) -> None:
        self._resume(run_id, {"failed"})

    def _resume(self, run_id: str, allowed: set[str]) -> None:
        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            if run.status not in allowed:
                raise ValueError("This run cannot be resumed or retried in its current state.")
        self.enqueue(run_id)

    @staticmethod
    def _get_run(session: Any, run_id: str) -> Run:
        run = session.get(Run, run_id)
        if run is None:
            raise ValueError("Processing run does not exist.")
        return run

    def checkpoint(self, run_id: str) -> None:
        with self.session_factory() as session:
            run = self._get_run(session, run_id)
            if run.cancel_requested:
                run.status = "cancelled"
                run.finished_at = now()
            elif run.pause_requested or self._stop.is_set():
                run.status = "paused"
            else:
                return
            for stage in session.scalars(
                select(Stage).where(Stage.run_id == run_id, Stage.status == "running")
            ):
                stage.status = run.status
            session.commit()
        raise RunInterrupted

    def run_now(self, run_id: str) -> None:
        """Execute one persisted run; used by the worker and credential-free tests."""
        from anki_generator.processing.pipeline import CoursePipeline

        with self._run_lock:
            with self.session_factory() as session:
                run = self._get_run(session, run_id)
                if run.status != "queued":
                    return
                run.status = "running"
                run.started_at = run.started_at or now()
                run.finished_at = None
                run.error = None
                session.commit()
            try:
                CoursePipeline(self, run_id).execute()
                self.checkpoint(run_id)
                with self.session_factory() as session:
                    run = self._get_run(session, run_id)
                    run.status = "completed"
                    run.current_stage = "completed"
                    run.finished_at = now()
                    session.commit()
            except RunInterrupted:
                pass
            except Exception as exc:
                # Provider errors contain carefully curated, credential-free messages.
                # Do not persist arbitrary parser/SDK exception strings with source data.
                message = (
                    str(exc)
                    if isinstance(exc, (ProviderError, ValueError))
                    else (
                        "Processing failed unexpectedly. Saved checkpoints are "
                        "intact; retry the run. "
                        f"Diagnostic category: {type(exc).__name__}."
                    )
                )
                with self.session_factory() as session:
                    run = session.get(Run, run_id)
                    if run is not None:
                        run.status = "failed"
                        run.error = message
                        run.finished_at = now()
                        for stage in session.scalars(
                            select(Stage).where(Stage.run_id == run_id, Stage.status == "running")
                        ):
                            stage.status = "failed"
                            stage.error = message
                            stage.finished_at = now()
                        session.commit()

    def _work(self) -> None:
        while not self._stop.is_set():
            with self.session_factory() as session:
                next_id = session.scalar(
                    select(Run.id).where(Run.status == "queued").order_by(Run.created_at).limit(1)
                )
            if next_id:
                self.run_now(next_id)
            else:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
