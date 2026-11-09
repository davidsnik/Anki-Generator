"""Small persisted event records for observable task state and safe diagnostics."""

from typing import Any

from anki_generator.database.task_entities import JobEvent


def add_event(
    session: Any,
    run_id: str,
    kind: str,
    message: str,
    *,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> JobEvent:
    event = JobEvent(run_id=run_id, kind=kind, message=message, level=level, details=details or {})
    session.add(event)
    return event
