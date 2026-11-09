"""Bounded task read models; full configuration and checkpoints stay in detail."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select

from anki_generator.database.entities import (
    Card,
    Concept,
    Course,
    Document,
    Run,
    Stage,
    Verification,
)
from anki_generator.database.task_entities import JobEvent
from anki_generator.services.records import record_dict, run_view
from anki_generator.services.task_order import queued_order

STATUSES = (
    "prepared",
    "queued",
    "running",
    "pausing",
    "paused",
    "cancelling",
    "cancelled",
    "completed",
    "failed",
    "interrupted",
    "recovering",
)
EXECUTING = ("running", "pausing", "cancelling")
ACTIVE = ("queued", *EXECUTING, "recovering")


def actions(run: Run) -> list[str]:
    return {
        "queued": ["pause", "cancel"],
        "running": ["pause", "cancel"],
        "pausing": ["cancel"],
        "paused": ["resume", "cancel"],
        "failed": ["retry", "cancel"],
        "interrupted": ["cancel"],
        "prepared": ["cancel"],
        "recovering": ["cancel"],
    }.get(run.status, [])


def counts(session: Any) -> dict[str, int]:
    result = dict.fromkeys(STATUSES, 0)
    result.update(
        dict(session.execute(select(Run.status, func.count()).group_by(Run.status)).all())
    )
    result["active"] = sum(result[key] for key in EXECUTING)
    result["total"] = sum(value for key, value in result.items() if key not in {"active", "total"})
    return result


def elapsed(run: Run) -> float:
    seconds = run.active_seconds or 0
    if not seconds and not run.resumed_at and run.started_at and not run.recovery_count:
        stop = datetime.fromisoformat(run.finished_at) if run.finished_at else datetime.now(UTC)
        seconds = max(0, (stop - datetime.fromisoformat(run.started_at)).total_seconds())
    if run.resumed_at and run.status in EXECUTING:
        seconds += max(
            0, (datetime.now(UTC) - datetime.fromisoformat(run.resumed_at)).total_seconds()
        )
    return round(seconds, 2)


def queue_positions(session: Any, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    position = func.row_number().over(order_by=queued_order())
    queued = (
        select(Run.id.label("id"), position.label("position"))
        .where(Run.status == "queued")
        .subquery()
    )
    return dict(
        session.execute(
            select(queued.c.id, queued.c.position).where(queued.c.id.in_(run_ids))
        ).all()
    )


def statistics(session: Any, runs: list[Run]) -> dict[str, dict[str, int]]:
    """A fixed number of grouped queries for every bounded task page."""
    if not runs:
        return {}
    course_ids = {run.course_id for run in runs}
    run_ids = [run.id for run in runs]
    documents = dict(
        session.execute(
            select(Document.course_id, func.count())
            .where(Document.course_id.in_(course_ids))
            .group_by(Document.course_id)
        ).all()
    )
    concepts = dict(
        session.execute(
            select(Concept.course_id, func.count())
            .where(Concept.course_id.in_(course_ids))
            .group_by(Concept.course_id)
        ).all()
    )
    cards = {
        course_id: (total, verified)
        for course_id, total, verified in session.execute(
            select(
                Card.course_id,
                func.count(),
                func.sum(case((Card.verification_status == "verified", 1), else_=0)),
            )
            .where(Card.course_id.in_(course_ids), ~Card.archived)
            .group_by(Card.course_id)
        )
    }
    extraction = dict(
        session.execute(
            select(Stage.run_id, Stage.completed).where(
                Stage.run_id.in_(run_ids), Stage.name == "extraction"
            )
        ).all()
    )
    return {
        run.id: {
            **output_counters(run),
            "documents_total": documents.get(run.course_id, 0),
            "documents_processed": extraction.get(run.id, 0),
            "pages_processed": run.progress.get("pages", 0),
            "concepts_current": concepts.get(run.course_id, 0),
            "cards_current": cards.get(run.course_id, (0, 0))[0],
            "cards_verified_current": cards.get(run.course_id, (0, 0))[1],
        }
        for run in runs
    }


def output_counters(run: Run) -> dict[str, int | None]:
    known = bool(run.progress.get("task_counter_version"))
    return {
        "concepts_extracted": run.progress.get("concepts", 0) if known else None,
        **{
            key: int(run.progress.get(key, 0)) if known else None
            for key in ("cards_generated", "cards_reused", "cards_new", "cards_verified")
        },
    }


def summary_view(run: Run, course_name: str, position: int | None = None) -> dict[str, Any]:
    fields = (
        "id",
        "course_id",
        "mode",
        "status",
        "current_stage",
        "error",
        "priority",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "progress",
        "usage",
        "metrics",
        "warnings",
        "pause_requested",
        "cancel_requested",
        "recovery_count",
    )
    return {
        **{key: getattr(run, key) for key in fields},
        "metrics": {
            key: run.metrics[key]
            for key in ("cards_total", "verification_counts", "stage_wall_seconds")
            if key in run.metrics
        },
        "warnings": run.warnings[-5:],
        "warnings_total": len(run.warnings),
        "course_name": course_name,
        "queue_position": position,
        "elapsed_seconds": elapsed(run),
        "elapsed_basis": (
            "Legacy wall time; active intervals were not recorded"
            if run.started_at
            and not run.active_seconds
            and not run.resumed_at
            and not run.recovery_count
            else "Active processing time; queue and paused time excluded"
        ),
        "allowed_actions": actions(run),
    }


def events_view(session: Any, run_id: str, offset: int = 0, limit: int = 25) -> dict[str, Any]:
    query = select(JobEvent).where(JobEvent.run_id == run_id)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    records = session.scalars(
        query.order_by(JobEvent.created_at.desc(), JobEvent.id.desc()).offset(offset).limit(limit)
    )
    return {
        "items": [record_dict(item) for item in records],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def detail_view(session: Any, run: Run) -> dict[str, Any]:
    course = session.get(Course, run.course_id)
    result = run_view(session, run)
    result.update(summary_view(run, course.name, queue_positions(session, [run.id]).get(run.id)))
    result["metrics"], result["warnings"] = run.metrics, run.warnings
    extraction = session.scalar(
        select(Stage).where(Stage.run_id == run.id, Stage.name == "extraction")
    )
    card_count = session.scalar(
        select(func.count())
        .select_from(Card)
        .where(Card.course_id == run.course_id, ~Card.archived)
    )
    verified = session.scalar(
        select(func.count())
        .select_from(Card)
        .where(
            Card.course_id == run.course_id, ~Card.archived, Card.verification_status == "verified"
        )
    )
    result["statistics"] = {
        **output_counters(run),
        "documents_total": len(run.inputs)
        or session.scalar(
            select(func.count()).select_from(Document).where(Document.course_id == run.course_id)
        ),
        "documents_processed": extraction.completed if extraction else 0,
        "pages_processed": run.progress.get("pages", 0),
        "concepts_current": session.scalar(
            select(func.count()).select_from(Concept).where(Concept.course_id == run.course_id)
        ),
        "cards_current": card_count,
        "cards_verified_current": verified,
        "cards_checked_this_run": session.scalar(
            select(func.count(func.distinct(Verification.card_id))).where(
                Verification.run_id == run.id
            )
        ),
    }
    result["events"] = events_view(session, run.id)
    result["outputs"] = {
        "cards_url": f"/courses/{run.course_id}/cards",
        "concepts_url": f"/courses/{run.course_id}/knowledge",
        "exports_url": f"/courses/{run.course_id}/exports",
    }
    return result
