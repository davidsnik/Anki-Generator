"""Durable worker submission, progress, and checkpoint controls."""

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from anki_generator.api.courses import ensure_idle
from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Card, Concept, Course, Document, Run
from anki_generator.domain import RunInput
from anki_generator.services.records import require, run_view
from anki_generator.services.settings import get_settings

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/runs")
def list_runs(request: Request, course_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        return [
            run_view(session, run)
            for run in session.scalars(
                select(Run).where(Run.course_id == course_id).order_by(Run.created_at.desc())
            )
        ]


@router.post("/courses/{course_id}/runs", status_code=202)
def submit_run(request: Request, course_id: str, values: RunInput) -> dict[str, Any]:
    rt = runtime(request)
    if values.mode != "extract":
        if not values.consent:
            raise ValueError(
                "Confirm that selected course excerpts and rendered source regions "
                "may be sent to OpenAI"
            )
        if not rt.secrets.get():
            raise ValueError("Configure an OpenAI API key in Settings before starting analysis")
    settings = get_settings(rt.sessions).model_dump()
    with rt.sessions.begin() as session:
        course = require(session, Course, course_id)
        ensure_idle(session, course_id)
        documents = list(session.scalars(select(Document).where(Document.course_id == course_id)))
        if not documents:
            raise ValueError("Import course documents before starting processing")
        if values.mode == "revise":
            if not values.card_id:
                raise ValueError("Select a card to regenerate")
            card = require(session, Card, values.card_id)
            if card.course_id != course_id:
                raise ValueError("Card belongs to another course")
            if card.manually_edited and not values.overwrite_manual:
                raise ValueError(
                    "Confirm replacement of this manually edited card before regeneration"
                )
        if values.topic_id and require(session, Concept, values.topic_id).course_id != course_id:
            raise ValueError("Topic belongs to another course")
        settings["criteria"] = course.criteria or settings["criteria"]
        settings["language"] = course.language
        run = Run(
            course_id=course_id,
            mode=values.mode,
            config=settings,
            inputs=[
                {
                    "document_id": doc.id,
                    "sha256": doc.sha256,
                    "category": doc.category,
                    "authority": doc.authority,
                    "linked_document_id": doc.linked_document_id,
                }
                for doc in documents
            ],
            request=values.model_dump(),
        )
        session.add(run)
        session.flush()
        result = run_view(session, run)
        identifier = run.id
    rt.runner.enqueue(identifier)
    return result


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    with runtime(request).sessions() as session:
        return run_view(session, require(session, Run, run_id))


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
