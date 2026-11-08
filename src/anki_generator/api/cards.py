"""Card browsing, human revision, and review decisions."""

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from anki_generator.api.courses import ensure_idle
from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Card, Course, Revision
from anki_generator.domain import CardInput, CardPatch, ReviewInput
from anki_generator.services.records import (
    card_view,
    create_card,
    edit_card,
    record_dict,
    require,
    review_card,
)

router = APIRouter(prefix="/api")


@router.get("/courses/{course_id}/cards")
def list_cards(request: Request, course_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Course, course_id)
        return [
            card_view(session, card)
            for card in session.scalars(
                select(Card).where(Card.course_id == course_id).order_by(Card.updated_at.desc())
            )
        ]


@router.post("/courses/{course_id}/cards", status_code=201)
def add_card(request: Request, course_id: str, values: CardInput) -> dict[str, Any]:
    with runtime(request).sessions.begin() as session:
        ensure_idle(session, course_id)
        return card_view(session, create_card(session, course_id, values))


@router.get("/cards/{card_id}")
def get_card(request: Request, card_id: str) -> dict[str, Any]:
    with runtime(request).sessions() as session:
        return card_view(session, require(session, Card, card_id), detail=True)


@router.patch("/cards/{card_id}")
def update_card(request: Request, card_id: str, values: CardPatch) -> dict[str, Any]:
    with runtime(request).sessions.begin() as session:
        card = require(session, Card, card_id)
        ensure_idle(session, card.course_id)
        edit_card(session, card, values)
        session.flush()
        return card_view(session, card, detail=True)


@router.post("/cards/{card_id}/review")
def decide_card(request: Request, card_id: str, values: ReviewInput) -> dict[str, Any]:
    with runtime(request).sessions.begin() as session:
        card = require(session, Card, card_id)
        review_card(session, card, values)
        session.flush()
        return card_view(session, card, detail=True)


@router.get("/cards/{card_id}/revisions")
def card_revisions(request: Request, card_id: str) -> list[dict[str, Any]]:
    with runtime(request).sessions() as session:
        require(session, Card, card_id)
        return [
            record_dict(revision)
            for revision in session.scalars(
                select(Revision)
                .where(Revision.card_id == card_id)
                .order_by(Revision.revision_number.desc())
            )
        ]
