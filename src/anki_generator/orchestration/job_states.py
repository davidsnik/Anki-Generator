"""Validated durable transitions, active processing clocks and task events."""

from datetime import datetime
from typing import Any

from sqlalchemy import select

from anki_generator.database.entities import Run, Stage, now
from anki_generator.services.task_events import add_event

EXECUTING = frozenset({"running", "pausing", "cancelling"})
RECOVERABLE = EXECUTING | {"interrupted", "recovering"}
TRANSITIONS = {
    "prepared": {"queued", "cancelled"},
    "queued": {"running", "paused", "cancelled", "failed"},
    "running": {"pausing", "cancelling", "paused", "completed", "failed", "interrupted"},
    "pausing": {"paused", "cancelling", "completed", "failed", "interrupted"},
    "cancelling": {"cancelled", "completed", "failed", "interrupted"},
    "paused": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "interrupted": {"recovering", "paused", "cancelled", "queued"},
    "recovering": {"paused", "cancelled", "queued", "failed"},
    "completed": set(),
    "cancelled": set(),
}


def transition(
    session: Any,
    run: Run,
    target: str,
    *,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    ended_at: str | None = None,
) -> None:
    previous = run.status
    if previous == target:
        return
    if target not in TRANSITIONS.get(previous, set()):
        raise ValueError(f"Cannot change job state from {previous} to {target}.")
    timestamp = now()
    if previous in RECOVERABLE and target not in EXECUTING and run.resumed_at:
        # Restart recovery ends the known active interval at the last durable DB
        # update, excluding unknown crash/offline time from measured processing.
        stop = datetime.fromisoformat(ended_at or timestamp)
        began = datetime.fromisoformat(run.resumed_at)
        run.active_seconds = float(run.active_seconds or 0) + max(0, (stop - began).total_seconds())
        run.resumed_at = None
    run.status = target
    if target == "running":
        run.started_at = run.started_at or timestamp
        run.resumed_at = timestamp
        run.finished_at = None
        run.error = None
        run.pause_requested = False
        run.cancel_requested = False
    elif target == "queued":
        run.queued_at = timestamp
        run.finished_at = None
        run.error = None
        run.pause_requested = False
        run.cancel_requested = False
    elif target == "pausing":
        run.pause_requested = True
    elif target == "cancelling":
        run.cancel_requested = True
    elif target == "paused":
        run.pause_requested = False
    elif target == "cancelled":
        run.finished_at = timestamp
        run.cancel_requested = True
    elif target in {"completed", "failed"}:
        run.finished_at = timestamp
    if target == "completed":
        run.current_stage = "completed"
    add_event(
        session,
        run.id,
        "state",
        message or f"Job {target}.",
        level="error" if target == "failed" else "info",
        details={"from": previous, "to": target, **(details or {})},
    )


def settle_completion(session: Any, run: Run) -> str:
    """Honor a control accepted before the atomic completion boundary commits."""
    target = (
        "cancelled"
        if run.cancel_requested or run.status == "cancelling"
        else "paused"
        if run.pause_requested or run.status == "pausing"
        else "completed"
    )
    transition(session, run, target)
    if target != "completed":
        for stage in session.scalars(
            select(Stage).where(Stage.run_id == run.id, Stage.status.in_(EXECUTING))
        ):
            stage.status = target
    return target
