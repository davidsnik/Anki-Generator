"""Priority/FIFO queue with a starvation bound for long-waiting tasks."""

from sqlalchemy import case, func

from anki_generator.database.entities import Run

QUEUE_AGING_MINUTES = 30


def queued_order() -> tuple:
    entered = func.coalesce(Run.queued_at, Run.created_at)
    aged = func.julianday(entered) <= func.julianday("now", f"-{QUEUE_AGING_MINUTES} minutes")
    return (
        case((aged, 0), else_=1),
        case((aged, 0), else_=Run.priority).desc(),
        entered,
        Run.id,
    )
