"""Centralized paged task inventory, observable resource limits and queue priority."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import load_only

from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Course, Run, now
from anki_generator.domain import InputModel
from anki_generator.services.records import require
from anki_generator.services.settings import get_settings
from anki_generator.services.task_events import add_event
from anki_generator.services.task_views import (
    ACTIVE,
    STATUSES,
    counts,
    detail_view,
    events_view,
    queue_positions,
    statistics,
    summary_view,
)

router = APIRouter(prefix="/api/tasks")
SUMMARY_FIELDS = [
    getattr(Run, name)
    for name in (
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
        "active_seconds",
        "resumed_at",
        "recovery_count",
    )
]


@router.get("/summary")
def task_summary(request: Request) -> dict:
    rt = runtime(request)
    with rt.sessions() as session:
        # At most eight active execution slots; queued histories remain paged.
        current = session.execute(
            select(Run, Course.name)
            .join(Course)
            .options(load_only(*SUMMARY_FIELDS))
            .where(Run.status.in_(ACTIVE))
            .order_by(
                case((Run.status.in_(["running", "pausing", "cancelling"]), 0), else_=1),
                Run.priority.desc(),
                Run.created_at,
                Run.id,
            )
            .limit(100)
        ).all()
        positions = queue_positions(session, [run.id for run, _ in current])
        return {
            "counts": counts(session),
            "limits": get_settings(rt.sessions).tasks.model_dump(),
            "active_runs": [
                summary_view(run, name, positions.get(run.id)) for run, name in current
            ],
            "active_runs_truncated": len(current) == 100,
            "server_time": now(),
            "resources": rt.runner.resources.snapshot(),
        }


@router.get("")
def task_list(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
    course_id: str | None = None,
    status: str | None = None,
    mode: Literal["generate", "extract", "interpret", "revise", "topic"] | None = None,
    q: str = Query("", max_length=200),
    sort: Literal["newest", "oldest", "priority"] = "newest",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    if status and status not in {*STATUSES, "active"}:
        raise ValueError("Unknown task status")
    date_from = (
        date_from.replace(tzinfo=UTC) if date_from and date_from.tzinfo is None else date_from
    )
    date_to = date_to.replace(tzinfo=UTC) if date_to and date_to.tzinfo is None else date_to
    date_from = date_from.astimezone(UTC) if date_from else None
    date_to = date_to.astimezone(UTC) if date_to else None
    if date_from and date_to and date_from > date_to:
        raise ValueError("The start date must not follow the end date")
    with runtime(request).sessions() as session:
        query = select(Run, Course.name).join(Course)
        if course_id:
            query = query.where(Run.course_id == course_id)
        if status:
            query = query.where(
                Run.status.in_(ACTIVE) if status == "active" else Run.status == status
            )
        if mode:
            query = query.where(Run.mode == mode)
        if date_from:
            query = query.where(Run.created_at >= date_from.isoformat())
        if date_to:
            query = query.where(Run.created_at <= date_to.isoformat())
        if q.strip():
            escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            query = query.where(
                or_(Course.name.ilike(pattern, escape="\\"), Run.id.ilike(pattern, escape="\\"))
            )
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        ordering = {
            "newest": (Run.created_at.desc(), Run.id.desc()),
            "oldest": (Run.created_at, Run.id),
            "priority": (Run.priority.desc(), Run.created_at, Run.id),
        }[sort]
        rows = session.execute(
            query.options(load_only(*SUMMARY_FIELDS))
            .order_by(*ordering)
            .offset(offset)
            .limit(limit)
        ).all()
        positions = queue_positions(session, [run.id for run, _ in rows])
        measured = statistics(session, [run for run, _ in rows])
        return {
            "items": [
                {**summary_view(run, name, positions.get(run.id)), "statistics": measured[run.id]}
                for run, name in rows
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
            "summary": counts(session),
        }


@router.get("/{run_id}")
def task_detail(request: Request, run_id: str) -> dict:
    with runtime(request).sessions() as session:
        return detail_view(session, require(session, Run, run_id))


@router.get("/{run_id}/events")
def task_events(
    request: Request,
    run_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
) -> dict:
    with runtime(request).sessions() as session:
        require(session, Run, run_id)
        return events_view(session, run_id, offset, limit)


class PriorityInput(InputModel):
    priority: int = Field(ge=-100, le=100)


@router.post("/{run_id}/priority")
def prioritize_task(request: Request, run_id: str, values: PriorityInput) -> dict:
    rt = runtime(request)
    with rt.sessions.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        run = require(session, Run, run_id)
        if run.status != "queued":
            raise ValueError("Only queued tasks can change priority")
        if run.priority != values.priority:
            run.priority = values.priority
            add_event(
                session,
                run.id,
                "priority",
                "Queue priority changed",
                details={"priority": values.priority},
            )
        session.flush()
        result = detail_view(session, run)
    rt.runner._wake.set()
    return result
