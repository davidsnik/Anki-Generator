"""Bounded SQL browsing and explicit revision-aware selection operations."""

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import String, cast, func, or_, select, text

from anki_generator.api.courses import ensure_idle
from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Card, Concept, Course, Document, Revision
from anki_generator.domain import CardPatch, InputModel, ReviewInput, RunInput
from anki_generator.services.records import card_view, edit_card, record_dict, require, review_card

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/cards-page")
def browse_cards(
    request: Request,
    course_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=100),
    q: str = Query(default="", max_length=1000),
    sort: Literal["newest", "question", "status"] = "newest",
    review_status: str | None = None,
    verification_status: str | None = None,
    card_type: str | None = None,
    concept_id: str | None = None,
    document_id: str | None = None,
) -> dict:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        conditions = [Card.course_id == course_id, ~Card.archived]
        if q.strip():
            needle = (
                "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            conditions.append(
                or_(
                    *[
                        column.ilike(needle, escape="\\")
                        for column in (
                            Card.question,
                            Card.answer,
                            Card.explanation,
                            cast(Card.tags, String),
                        )
                    ]
                )
            )
        if review_status:
            if review_status not in {"pending", "approved", "rejected"}:
                raise ValueError("Unknown human review filter")
            conditions.append(Card.review_status == review_status)
        if verification_status == "needs_attention":
            conditions.append(
                or_(Card.review_status == "pending", Card.verification_status != "verified")
            )
        elif verification_status:
            conditions.append(Card.verification_status == verification_status)
        if card_type:
            if card_type not in {"basic", "cloze"}:
                raise ValueError("Unknown note type")
            conditions.append(Card.card_type == card_type)
        if concept_id:
            concept = require(session, Concept, concept_id)
            if concept.course_id != course_id:
                raise ValueError("Topic belongs to another course")
            conditions.append(Card.concept_id == concept_id)
        if document_id:
            document = require(session, Document, document_id)
            if document.course_id != course_id:
                raise ValueError("Source belongs to another course")
            conditions.append(
                text(
                    "EXISTS (SELECT 1 FROM json_each(cards.sources) AS source "
                    "WHERE json_extract(source.value, '$.document_id') = :document_filter)"
                )
            )
        query = select(Card).where(*conditions)
        params = {"document_filter": document_id} if document_id else {}
        total = session.scalar(select(func.count()).select_from(query.subquery()).params(**params))
        order = {
            "newest": (Card.updated_at.desc(), Card.id),
            "question": (func.lower(Card.question), Card.id),
            "status": (Card.review_status, Card.verification_status, Card.id),
        }[sort]
        cards = list(
            session.scalars(query.order_by(*order).offset(offset).limit(limit).params(**params))
        )
        facets = {
            "card_types": list(
                session.scalars(
                    select(Card.card_type)
                    .where(Card.course_id == course_id, ~Card.archived)
                    .distinct()
                )
            ),
            "verification_statuses": list(
                session.scalars(
                    select(Card.verification_status)
                    .where(Card.course_id == course_id, ~Card.archived)
                    .distinct()
                )
            ),
            "sources": [
                {"id": item.id, "name": item.filename}
                for item in session.scalars(
                    select(Document)
                    .where(Document.course_id == course_id)
                    .order_by(Document.filename)
                )
            ],
            "topics": [
                {"id": item.id, "title": item.title}
                for item in session.scalars(
                    select(Concept).where(Concept.course_id == course_id).order_by(Concept.title)
                )
            ],
        }
        return {
            "items": [card_view(session, card) for card in cards],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(cards) < total,
            "facets": facets,
        }


class BulkInput(InputModel):
    card_ids: list[str] = Field(min_length=1, max_length=500)
    expected_revisions: dict[str, int]
    action: Literal["approve", "reject", "pending", "tags", "topic", "regenerate"]
    reason: str = Field(default="", max_length=10000)
    tags_add: list[str] = Field(default_factory=list, max_length=100)
    tags_remove: list[str] = Field(default_factory=list, max_length=100)
    concept_id: str | None = None
    consent: bool = False
    instruction: str = Field(default="", max_length=20000)
    confirm: bool = False
    overwrite_manual: bool = False

    @model_validator(mode="after")
    def exact_selection(self):
        if len(set(self.card_ids)) != len(self.card_ids):
            raise ValueError("Select each card once")
        if set(self.expected_revisions) != set(self.card_ids):
            raise ValueError("Provide the expected revision for exactly the selected cards")
        if any(len(tag) > 200 or not tag.strip() for tag in self.tags_add + self.tags_remove):
            raise ValueError("Tags must contain 1–200 characters")
        return self


@router.post("/courses/{course_id}/cards/bulk")
def bulk_cards(request: Request, course_id: str, values: BulkInput) -> dict:
    rt = runtime(request)
    if values.action in {"reject", "topic", "regenerate"} and not values.confirm:
        raise ValueError("Confirm this bulk action for the explicitly selected cards")
    with rt.sessions.begin() as session:
        require(session, Course, course_id)
        ensure_idle(session, course_id)
        cards = [require(session, Card, identifier) for identifier in values.card_ids]
        if any(card.course_id != course_id or card.archived for card in cards):
            raise ValueError("Selection must contain active cards from this course only")
        if any(card.revision_number != values.expected_revisions[card.id] for card in cards):
            raise ValueError("A selected card changed; reload the selection before applying")
        if values.action == "regenerate":
            if not values.consent or not rt.secrets.get():
                raise ValueError("Configure a key and confirm external processing for regeneration")
            if (
                any(
                    card.manually_edited or card.review_status in {"approved", "rejected"}
                    for card in cards
                )
                and not values.overwrite_manual
            ):
                raise ValueError("Explicitly confirm replacement of human-edited or reviewed cards")
            if not session.scalar(
                select(Document.id).where(Document.course_id == course_id).limit(1)
            ):
                raise ValueError("Import sources before regeneration")
        else:
            for card in cards:
                if values.action in {"approve", "reject", "pending"}:
                    decision = {"approve": "approved", "reject": "rejected", "pending": "pending"}[
                        values.action
                    ]
                    review_card(session, card, ReviewInput(decision=decision, reason=values.reason))
                else:
                    if values.action == "tags":
                        tags = sorted(
                            (set(card.tags) | set(values.tags_add)) - set(values.tags_remove)
                        )
                        edit_card(
                            session,
                            card,
                            CardPatch(tags=tags, expected_revision=card.revision_number),
                        )
                    else:
                        edit_card(
                            session,
                            card,
                            CardPatch(
                                concept_id=values.concept_id, expected_revision=card.revision_number
                            ),
                        )
            session.flush()
            return {
                "affected": len(cards),
                "card_ids": values.card_ids,
                "items": [card_view(session, card) for card in cards],
            }
    from anki_generator.services.run_submission import submit_run

    # Prepare the whole selection before waking the worker. Prepared runs are not
    # active and cannot be picked up until all selection validation has succeeded.
    prepared = []
    try:
        for identifier in values.card_ids:
            run = submit_run(
                rt,
                course_id,
                RunInput(
                    mode="revise",
                    card_id=identifier,
                    consent=True,
                    overwrite_manual=values.overwrite_manual,
                    expected_revision=values.expected_revisions[identifier],
                    instruction=values.instruction,
                ),
                enqueue=False,
            )
            prepared.append(run)
        for run in prepared:
            rt.runner.enqueue(run["id"])
        return {"affected": len(prepared), "card_ids": values.card_ids, "runs": prepared}
    except Exception:
        from sqlalchemy import delete

        from anki_generator.database.entities import Run

        with rt.sessions.begin() as session:
            session.execute(
                delete(Run).where(
                    Run.id.in_([run["id"] for run in prepared]), Run.status == "prepared"
                )
            )
        raise


class RestoreRevisionInput(InputModel):
    revision_number: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    confirm: bool = False


@router.post("/cards/{card_id}/restore")
def restore_revision(request: Request, card_id: str, values: RestoreRevisionInput) -> dict:
    if not values.confirm:
        raise ValueError("Confirm restoration; this appends a revision and resets current checks")
    with runtime(request).sessions.begin() as session:
        card = require(session, Card, card_id)
        ensure_idle(session, card.course_id)
        if card.revision_number != values.expected_revision:
            raise ValueError("Card changed since opening; reload before restoring")
        previous = session.scalar(
            select(Revision).where(
                Revision.card_id == card_id, Revision.revision_number == values.revision_number
            )
        )
        if previous is None:
            raise LookupError("Revision not found")
        fields = {
            key: value
            for key, value in previous.snapshot.items()
            if key in CardPatch.model_fields and key not in {"archived", "expected_revision"}
        }
        old_revision = card.revision_number
        edit_card(session, card, CardPatch(**fields, expected_revision=values.expected_revision))
        if card.revision_number == old_revision:
            raise ValueError("Selected revision already has the current content")
        session.flush()
        revision = session.scalar(
            select(Revision).where(
                Revision.card_id == card_id, Revision.revision_number == card.revision_number
            )
        )
        revision.origin = "human_restore"
        revision.instruction = (
            f"Restored content from revision {values.revision_number}; "
            "previous checks were not restored."
        )
        return card_view(session, card, detail=True)


@router.get("/cards/{card_id}/revision-diff")
def revision_diff(
    request: Request,
    card_id: str,
    before: int = Query(ge=1),
    after: int | None = Query(default=None, ge=1),
) -> dict:
    with runtime(request).sessions() as session:
        card = require(session, Card, card_id)
        snapshots = []
        for number in (before, after or card.revision_number):
            revision = session.scalar(
                select(Revision).where(
                    Revision.card_id == card_id, Revision.revision_number == number
                )
            )
            if revision is None:
                raise LookupError("Revision not found")
            snapshots.append(record_dict(revision))
        fields = (
            "question",
            "answer",
            "explanation",
            "tags",
            "sources",
            "image_refs",
            "concept_id",
        )
        return {
            "before": snapshots[0],
            "after": snapshots[1],
            "fields": [
                {
                    "field": name,
                    "before": snapshots[0]["snapshot"].get(name),
                    "after": snapshots[1]["snapshot"].get(name),
                    "changed": snapshots[0]["snapshot"].get(name)
                    != snapshots[1]["snapshot"].get(name),
                }
                for name in fields
            ],
        }
