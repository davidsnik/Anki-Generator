"""Paginated original-source coverage, explicit identity decisions and export review."""

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from anki_generator.api.courses import ensure_idle
from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Concept, Course, Run
from anki_generator.database.pipeline_entities import IdentityProposal, SourceCoverageTarget
from anki_generator.domain import ExportInput
from anki_generator.processing.state import entity_data
from anki_generator.services.export_preview import export_preview
from anki_generator.services.identity_resolution import IdentityResolution, resolve_identity
from anki_generator.services.records import require

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/export-preview")
def preview_get(
    request: Request,
    course_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    with runtime(request).sessions() as session:
        return export_preview(session, course_id, offset=offset, limit=limit)


@router.post("/courses/{course_id}/export-preview")
def preview_post(
    request: Request,
    course_id: str,
    values: ExportInput,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    with runtime(request).sessions() as session:
        return export_preview(session, course_id, values.card_ids, offset=offset, limit=limit)


@router.get("/courses/{course_id}/identity-proposals")
def proposals(
    request: Request,
    course_id: str,
    status: str = "pending",
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        query = select(IdentityProposal).where(IdentityProposal.course_id == course_id)
        if status != "all":
            query = query.where(IdentityProposal.state == status)
        count = session.scalar(select(func.count()).select_from(query.subquery()))
        items = session.scalars(
            query.order_by(IdentityProposal.created_at).offset(offset).limit(limit)
        )
        return {
            "items": [entity_data(item) for item in items],
            "total": count,
            "offset": offset,
            "limit": limit,
        }


@router.post("/identity-proposals/{proposal_id}/resolve")
def resolve(request: Request, proposal_id: str, values: IdentityResolution):
    with runtime(request).sessions.begin() as session:
        proposal = require(session, IdentityProposal, proposal_id)
        ensure_idle(session, proposal.course_id)
        return resolve_identity(session, proposal_id, values)


@router.get("/courses/{course_id}/coverage-targets")
def targets(
    request: Request,
    course_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    kind: str | None = None,
    status: str | None = None,
    topic_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        if run_id:
            if require(session, Run, run_id).course_id != course_id:
                raise ValueError("Coverage run belongs to another course")
        else:
            run_id = session.scalar(
                select(SourceCoverageTarget.run_id)
                .join(Run, Run.id == SourceCoverageTarget.run_id)
                .where(SourceCoverageTarget.course_id == course_id)
                .order_by(Run.created_at.desc())
                .limit(1)
            )
        query = select(SourceCoverageTarget).where(
            SourceCoverageTarget.course_id == course_id, SourceCoverageTarget.run_id == run_id
        )
        summary = {
            "by_kind": dict(
                session.execute(
                    select(SourceCoverageTarget.kind, func.count())
                    .where(
                        SourceCoverageTarget.course_id == course_id,
                        SourceCoverageTarget.run_id == run_id,
                    )
                    .group_by(SourceCoverageTarget.kind)
                ).all()
            ),
            "by_status": dict(
                session.execute(
                    select(SourceCoverageTarget.status, func.count())
                    .where(
                        SourceCoverageTarget.course_id == course_id,
                        SourceCoverageTarget.run_id == run_id,
                    )
                    .group_by(SourceCoverageTarget.status)
                ).all()
            ),
        }
        if kind:
            query = query.where(SourceCoverageTarget.kind == kind)
        if status:
            query = query.where(SourceCoverageTarget.status == status)
        if topic_id:
            topic = require(session, Concept, topic_id)
            if topic.course_id != course_id:
                raise ValueError("Coverage topic belongs to another course")
            pairs = list(
                session.execute(
                    select(Concept.id, Concept.parent_id).where(Concept.course_id == course_id)
                )
            )
            descendants = {topic_id}
            while True:
                additions = {
                    identifier for identifier, parent in pairs if parent in descendants
                } - descendants
                if not additions:
                    break
                descendants.update(additions)
            refs = func.json_each(SourceCoverageTarget.mapped_concept_ids).table_valued(
                "key", "value"
            )
            query = query.where(
                select(1).select_from(refs).where(refs.c.value.in_(descendants)).exists()
            )
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = list(
            session.scalars(
                query.order_by(SourceCoverageTarget.created_at, SourceCoverageTarget.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return {
            "items": [entity_data(row) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
            "run_id": run_id,
            "summary": summary,
        }
