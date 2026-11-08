"""Course and conceptual inventory endpoints."""

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import delete, select

from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Concept, Course, Document, ExportRecord, Run
from anki_generator.domain import CourseInput, CoursePatch, InputModel
from anki_generator.services.cleanup import remove_owned_directory, remove_unreferenced_blob
from anki_generator.services.records import course_view, record_dict, require, source_view
from anki_generator.services.settings import get_settings

router = APIRouter(prefix="/api")


@router.get("/courses")
def list_courses(request: Request) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        return [
            course_view(session, course)
            for course in session.scalars(select(Course).order_by(Course.updated_at.desc()))
        ]


@router.post("/courses", status_code=201)
def create_course(request: Request, values: CourseInput) -> dict[str, Any]:
    with runtime(request).sessions.begin() as session:
        payload = values.model_dump()
        if "criteria" not in values.model_fields_set:
            payload["criteria"] = get_settings(runtime(request).sessions).criteria.model_dump()
        payload["name"] = payload["name"].strip()
        if not payload["name"]:
            raise ValueError("Enter a course name")
        payload["deck_name"] = payload["deck_name"].strip() or payload["name"]
        course = Course(**payload)
        session.add(course)
        session.flush()
        return course_view(session, course)


@router.get("/courses/{course_id}")
def get_course(request: Request, course_id: str) -> dict[str, Any]:
    with runtime(request).sessions() as session:
        return course_view(session, require(session, Course, course_id))


def ensure_idle(session: Any, course_id: str) -> None:
    active = session.scalar(
        select(Run)
        .where(
            Run.course_id == course_id,
            Run.status.in_(["queued", "running", "pausing", "cancelling"]),
        )
        .limit(1)
    )
    if active:
        raise ValueError("Pause or cancel the active processing run before modifying course inputs")


@router.patch("/courses/{course_id}")
def update_course(request: Request, course_id: str, values: CoursePatch) -> dict[str, Any]:
    with runtime(request).sessions.begin() as session:
        course = require(session, Course, course_id)
        payload = values.model_dump(exclude_unset=True)
        if any(value is None for value in payload.values()):
            raise ValueError("Course settings cannot be null")
        if "criteria" in payload:
            ensure_idle(session, course_id)
        for key, value in payload.items():
            if isinstance(value, str) and key in {"name", "deck_name", "language"}:
                value = value.strip()
                if not value:
                    raise ValueError(f"{key} cannot be blank")
            setattr(course, key, value)
        session.flush()
        return course_view(session, course)


@router.delete("/courses/{course_id}")
def delete_course(request: Request, course_id: str) -> dict[str, bool]:
    rt = runtime(request)
    with rt.sessions.begin() as session:
        require(session, Course, course_id)
        ensure_idle(session, course_id)
        documents = list(session.scalars(select(Document).where(Document.course_id == course_id)))
        blobs = [(document.id, document.storage_path) for document in documents]
        export_paths = list(
            session.scalars(
                select(ExportRecord.storage_path).where(ExportRecord.course_id == course_id)
            )
        )
        run_ids = list(session.scalars(select(Run.id).where(Run.course_id == course_id)))
        session.execute(delete(Course).where(Course.id == course_id))
    for document_id, relative in blobs:
        remove_unreferenced_blob(rt.sessions, rt.data_root, relative)
        remove_owned_directory(rt.data_root, f"artifacts/{document_id}")
    for identifier in run_ids:
        remove_owned_directory(rt.data_root, f"runs/{identifier}")
    remove_owned_directory(rt.data_root, f"cache/llm/{course_id}")
    from anki_generator.services.storage import safe_storage_path

    for relative in export_paths:
        safe_storage_path(rt.data_root, relative).unlink(missing_ok=True)
    return {"deleted": True}


@router.get("/courses/{course_id}/concepts")
def list_concepts(request: Request, course_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        return [
            {
                **record_dict(concept),
                "sources": [source_view(session, ref) for ref in concept.sources],
            }
            for concept in session.scalars(
                select(Concept)
                .where(Concept.course_id == course_id)
                .order_by(Concept.importance.desc(), Concept.title)
            )
        ]


class ConceptPatch(InputModel):
    excluded: bool


@router.patch("/concepts/{concept_id}")
def update_concept(request: Request, concept_id: str, values: ConceptPatch) -> dict[str, Any]:
    with runtime(request).sessions.begin() as session:
        concept = require(session, Concept, concept_id)
        ensure_idle(session, concept.course_id)
        concept.excluded = values.excluded
        return record_dict(concept)
