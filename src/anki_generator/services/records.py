"""CRUD and read models, including revision-aware human edits and evidence checks."""

import math
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from anki_generator.database.entities import (
    Card,
    Concept,
    Course,
    Document,
    ExportRecord,
    Page,
    ReviewDecision,
    Revision,
    Run,
    Stage,
    Verification,
    now,
)
from anki_generator.domain import CardInput, CardPatch, ReviewInput


def record_dict(record: Any) -> dict[str, Any]:
    return {column.key: getattr(record, column.key) for column in inspect(type(record)).columns}


def require(session: Session, entity: type, identifier: str) -> Any:
    record = session.get(entity, identifier)
    if record is None:
        raise LookupError(f"{entity.__name__} not found")
    return record


def course_view(session: Session, course: Course) -> dict[str, Any]:
    result = record_dict(course)
    documents = session.scalar(
        select(func.count()).select_from(Document).where(Document.course_id == course.id)
    )
    cards = session.scalars(select(Card).where(Card.course_id == course.id, ~Card.archived)).all()
    last_run = session.scalar(
        select(Run).where(Run.course_id == course.id).order_by(Run.created_at.desc()).limit(1)
    )
    result["stats"] = {
        "documents": documents,
        "cards": len(cards),
        "pending_review": sum(card.review_status == "pending" for card in cards),
        "approved": sum(card.review_status == "approved" for card in cards),
        "verified": sum(card.verification_status == "verified" for card in cards),
        "concepts": session.scalar(
            select(func.count()).select_from(Concept).where(Concept.course_id == course.id)
        ),
        "last_status": last_run.status if last_run else "not_started",
    }
    return result


def document_view(document: Document) -> dict[str, Any]:
    result = record_dict(document)
    result.pop("storage_path", None)
    result.pop("extraction", None)
    result["page_count"] = len(document.extraction.get("pages", []))
    result["source_url"] = f"/api/documents/{document.id}/source"
    return result


def page_view(document_id: str, page: Page) -> dict[str, Any]:
    result = record_dict(page)
    result["regions"] = [
        {**region, "image_url": f"/api/documents/{document_id}/regions/{region['id']}"}
        for region in page.regions
    ]
    return result


def source_view(session: Session, source: dict[str, Any]) -> dict[str, Any]:
    result = dict(source)
    document = session.get(Document, source.get("document_id"))
    if document:
        result["document_name"] = document.filename
        result["source_url"] = f"/api/documents/{document.id}/source"
        if source.get("region_id"):
            result["image_url"] = f"/api/documents/{document.id}/regions/{source['region_id']}"
    return result


def card_view(session: Session, card: Card, *, detail: bool = False) -> dict[str, Any]:
    result = record_dict(card)
    result["sources"] = [source_view(session, source) for source in card.sources]
    result["image_refs"] = [source_view(session, image) for image in card.image_refs]
    if detail:
        result["verifications"] = [
            record_dict(item)
            for item in session.scalars(
                select(Verification)
                .where(Verification.card_id == card.id)
                .order_by(Verification.created_at.desc())
            )
        ]
        result["review_history"] = [
            record_dict(item)
            for item in session.scalars(
                select(ReviewDecision)
                .where(ReviewDecision.card_id == card.id)
                .order_by(ReviewDecision.created_at.desc())
            )
        ]
    return result


def run_view(session: Session, run: Run) -> dict[str, Any]:
    """Merge the mode's pending plan with authoritative stage checkpoints.

    Planned rows describe possible work, not persisted progress. Conditional
    checks may never run; their unknown item totals must remain unknown.
    """
    result = record_dict(run)
    recorded = {
        stage.name: record_dict(stage)
        for stage in session.scalars(
            select(Stage).where(Stage.run_id == run.id).order_by(Stage.started_at, Stage.name)
        )
    }
    plan = _run_stage_plan(run.mode)
    stages = []
    interpretation_passed = any(name not in {"extraction", "interpretation"} for name in recorded)
    for name, condition in plan:
        if name in recorded:
            stages.append(recorded.pop(name))
            continue
        if run.status == "completed":
            status = "skipped"
            message = "No separate work was recorded for this completed run."
        elif name == "interpretation" and interpretation_passed:
            status = "skipped"
            message = "No visual interpretation was needed before later processing began."
        elif run.status == "cancelled":
            status = "not_run"
            message = "Not started before this run was cancelled."
        else:
            status = "pending"
            message = "Waiting for earlier work."
            if run.status == "failed":
                message = "Not started; retry can continue from saved checkpoints."
        if condition:
            message = f"{message} {condition}"
        stages.append({"run_id": run.id, "name": name, "status": status, "message": message})
    # Retain real stages introduced by another application version or extension.
    stages.extend(recorded.values())
    result["stages"] = stages
    return result


def _run_stage_plan(mode: str) -> list[tuple[str, str | None]]:
    interpretation = (
        "interpretation",
        "Only when extracted source regions require visual interpretation.",
    )
    factual = ("factual", "When new or revised candidates require factual checks.")
    pedagogical = ("pedagogical", "When new or revised candidates require pedagogical checks.")
    mathematical = (
        "mathematical",
        "Only for mathematical candidates; suitable symbolic checks are part of this review.",
    )
    revision = (
        "revision",
        "Only for actionable defects while the configured revision limit allows another attempt.",
    )
    if mode == "extract":
        return [("extraction", None)]
    if mode == "revise":
        return [
            ("extraction", None),
            interpretation,
            ("revision", None),
            factual,
            pedagogical,
            mathematical,
            ("deduplication", None),
            ("coverage", None),
        ]
    return [
        ("extraction", None),
        interpretation,
        ("knowledge", None),
        ("consolidation", None),
        ("generation", None),
        factual,
        pedagogical,
        mathematical,
        revision,
        ("deduplication", None),
        ("coverage", None),
    ]


def export_view(export: ExportRecord) -> dict[str, Any]:
    result = record_dict(export)
    result.pop("storage_path", None)
    result["download_url"] = f"/api/exports/{export.id}/download"
    return result


def validate_sources(
    session: Session,
    course_id: str,
    references: list[dict[str, Any]],
    *,
    require_region: bool = False,
) -> list[dict[str, Any]]:
    validated = []
    for ref in references:
        document = require(session, Document, ref["document_id"])
        if document.course_id != course_id:
            raise ValueError("Source evidence must belong to the same course")
        page = session.scalar(
            select(Page).where(
                Page.document_id == document.id, Page.page_number == ref["page_number"]
            )
        )
        if page is None:
            raise ValueError("Source page is not extracted; run local extraction first")
        region_id = ref.get("region_id")
        region = next((item for item in page.regions if item["id"] == region_id), None)
        if (region_id or require_region) and region is None:
            raise ValueError("Source image region does not exist on that page")
        bbox = ref.get("bbox")
        if bbox is not None and (
            len(bbox) != 4
            or not all(math.isfinite(value) for value in bbox)
            or not (0 <= bbox[0] < bbox[2] <= page.width and 0 <= bbox[1] < bbox[3] <= page.height)
        ):
            raise ValueError("Source bounding box must be finite, ordered, and inside the page")
        clean = {key: value for key, value in ref.items() if key not in {"image_url", "source_url"}}
        clean["document_name"] = document.filename
        if region:
            clean["bbox"] = region["bbox"]
        validated.append(clean)
    return validated


def snapshot_card(card: Card) -> dict[str, Any]:
    return {
        key: getattr(card, key)
        for key in (
            "question",
            "answer",
            "explanation",
            "card_type",
            "kind",
            "tags",
            "concept_id",
            "sources",
            "image_refs",
            "verification_status",
            "review_status",
            "issues",
        )
    }


def create_card(session: Session, course_id: str, values: CardInput) -> Card:
    require(session, Course, course_id)
    payload = values.model_dump()
    validate_concept(session, course_id, payload.get("concept_id"))
    payload["sources"] = validate_sources(session, course_id, payload["sources"])
    payload["image_refs"] = validate_sources(
        session, course_id, payload["image_refs"], require_region=True
    )
    card = Card(course_id=course_id, manually_edited=True, **payload)
    session.add(card)
    session.flush()
    session.add(
        Revision(card_id=card.id, revision_number=1, snapshot=snapshot_card(card), origin="human")
    )
    return card


def validate_concept(session: Session, course_id: str, identifier: str | None) -> None:
    if identifier and require(session, Concept, identifier).course_id != course_id:
        raise ValueError("The concept must belong to the same course")


def edit_card(session: Session, card: Card, values: CardPatch) -> Card:
    payload = values.model_dump(exclude_unset=True)
    expected = payload.pop("expected_revision", None)
    if expected is not None and expected != card.revision_number:
        raise ValueError("This card changed since it was opened. Reload before saving.")
    if "concept_id" in payload:
        validate_concept(session, card.course_id, payload["concept_id"])
    for name in ("sources", "image_refs"):
        if name in payload:
            if payload[name] is None:
                raise ValueError(f"{name} must be a list")
            payload[name] = validate_sources(
                session, card.course_id, payload[name], require_region=name == "image_refs"
            )
    content_changed = any(
        getattr(card, key) != value for key, value in payload.items() if key != "archived"
    )
    for key, value in payload.items():
        if value is None and key not in {"concept_id"}:
            raise ValueError(f"{key} may not be null")
        setattr(card, key, value)
    if content_changed:
        card.revision_number += 1
        card.manually_edited = True
        card.verification_status = "unverified"
        card.review_status = "pending"
        card.issues = ["Human edit invalidated prior verification; review this revision."]
        card.updated_at = now()
        session.add(
            Revision(
                card_id=card.id,
                revision_number=card.revision_number,
                snapshot=snapshot_card(card),
                origin="human",
            )
        )
    return card


def review_card(session: Session, card: Card, values: ReviewInput) -> Card:
    if values.decision == "approved" and card.verification_status in {
        "failed",
        "rejected",
        "duplicate",
    }:
        raise ValueError("Resolve failed verification before approving this revision")
    if (
        values.decision == "approved"
        and card.verification_status != "verified"
        and not values.reason.strip()
    ):
        raise ValueError("Provide a human-review rationale when approving an unverified card")
    card.review_status = values.decision
    session.add(
        ReviewDecision(
            card_id=card.id,
            revision_number=card.revision_number,
            decision=values.decision,
            reason=values.reason,
        )
    )
    return card
