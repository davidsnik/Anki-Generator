"""Durable worker submission, progress, and checkpoint controls."""

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Course, Run
from anki_generator.domain import RunInput
from anki_generator.services.records import require, run_view

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/runs")
def list_runs(request: Request, course_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        return [
            run_view(session, run)
            for run in session.scalars(
                select(Run)
                .where(Run.course_id == course_id)
                .order_by(Run.created_at.desc())
                .limit(100)
            )
        ]


@router.post("/courses/{course_id}/runs", status_code=202)
def submit_run(request: Request, course_id: str, values: RunInput) -> dict[str, Any]:
    from anki_generator.services.run_submission import submit_run as submit

    return submit(runtime(request), course_id, values)


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    with runtime(request).sessions() as session:
        return run_view(session, require(session, Run, run_id))


@router.post("/runs/{run_id}/retry-stage", status_code=202)
def retry_selected_stage(request: Request, run_id: str, values: dict[str, Any]) -> dict[str, Any]:
    from anki_generator.services.run_submission import retry_stage

    return retry_stage(runtime(request), run_id, values)


@router.post("/runs/{run_id}/{action}")
def control_run(request: Request, run_id: str, action: str) -> dict[str, Any]:
    rt = runtime(request)
    if action not in {"pause", "resume", "cancel", "retry"}:
        raise LookupError("Unknown processing action")
    with rt.sessions() as session:
        require(session, Run, run_id)
    getattr(rt.runner, action)(run_id)
    with rt.sessions() as session:
        return run_view(session, require(session, Run, run_id))
