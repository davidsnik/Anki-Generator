"""Explicit human identity decisions preserve GUIDs and every content revision."""

from typing import Literal

from pydantic import Field
from sqlalchemy import select

from anki_generator.database.entities import Card, Concept, Revision, now
from anki_generator.database.pipeline_entities import (
    IdentityAlias,
    IdentityProposal,
    SourceCoverageTarget,
)
from anki_generator.domain import InputModel
from anki_generator.processing.state import entity_data
from anki_generator.services.records import require


class IdentityResolution(InputModel):
    decision: Literal["match", "new", "split", "merge"]
    existing_id: str | None = None
    rationale: str = Field(min_length=1, max_length=10000)
    replace_reviewed: bool = False


def _mapped_ids(session, card):
    latest = session.scalar(
        select(Revision).where(
            Revision.card_id == card.id, Revision.revision_number == card.revision_number
        )
    )
    return list(
        dict.fromkeys(
            [
                *(latest.snapshot.get("concept_ids", []) if latest else []),
                *([card.concept_id] if card.concept_id else []),
            ]
        )
    )


def _revise_mapping(session, card, concept_id, mapped_ids=None):
    latest = session.scalar(
        select(Revision).where(
            Revision.card_id == card.id, Revision.revision_number == card.revision_number
        )
    )
    prior = dict(latest.snapshot) if latest else {}
    card.concept_id = concept_id
    card.revision_number += 1
    card.verification_status = "needs_review"
    card.review_status = "pending"
    snapshot = {
        **prior,
        **{
            key: value
            for key, value in entity_data(card).items()
            if key not in {"created_at", "updated_at"}
        },
    }
    snapshot["concept_ids"] = (
        mapped_ids if mapped_ids is not None else ([concept_id] if concept_id else [])
    )
    session.add(
        Revision(
            card_id=card.id,
            revision_number=card.revision_number,
            snapshot=snapshot,
            origin="identity_resolution",
            instruction="Human identity reconciliation",
        )
    )


def resolve_identity(session, proposal_id: str, values: IdentityResolution):
    proposal = require(session, IdentityProposal, proposal_id)
    if proposal.state != "pending":
        raise ValueError("This identity proposal has already been resolved")
    entity = Card if proposal.entity_type == "card" else Concept
    candidate = require(session, entity, proposal.candidate_id)
    selected = candidate.id
    if values.decision in {"match", "merge"}:
        if not values.existing_id or values.existing_id == candidate.id:
            raise ValueError("Choose a distinct existing identity to preserve")
        previous = require(session, entity, values.existing_id)
        if previous.course_id != proposal.course_id:
            raise ValueError("The existing identity belongs to another course")
        if proposal.entity_type == "card":
            if (
                previous.manually_edited or previous.review_status in {"approved", "rejected"}
            ) and not values.replace_reviewed:
                raise ValueError(
                    "Confirm replacement of the existing human-edited or reviewed card"
                )
            for field in (
                "concept_id",
                "card_type",
                "kind",
                "question",
                "answer",
                "explanation",
                "tags",
                "sources",
                "image_refs",
                "mathematical",
                "issues",
            ):
                if hasattr(candidate, field):
                    setattr(previous, field, getattr(candidate, field))
            previous.archived = False
            _revise_mapping(
                session, previous, candidate.concept_id, _mapped_ids(session, candidate)
            )
            candidate.archived = True
        else:
            affected = [
                (card, _mapped_ids(session, card))
                for card in session.scalars(
                    select(Card).where(Card.course_id == proposal.course_id)
                )
            ]
            affected = [(card, ids) for card, ids in affected if candidate.id in ids]
            if not values.replace_reviewed and any(
                card.manually_edited or card.review_status in {"approved", "rejected"}
                for card, _ in affected
            ):
                raise ValueError("Confirm remapping the affected human-edited or reviewed cards")
            for card, ids in affected:
                remapped = list(
                    dict.fromkeys(
                        previous.id if identifier == candidate.id else identifier
                        for identifier in ids
                    )
                )
                _revise_mapping(
                    session,
                    card,
                    previous.id if card.concept_id == candidate.id else card.concept_id,
                    remapped,
                )
            for concept in session.scalars(
                select(Concept).where(Concept.course_id == proposal.course_id)
            ):
                if concept.parent_id == candidate.id:
                    concept.parent_id = (
                        candidate.parent_id if concept.id == previous.id else previous.id
                    )
                    if concept.parent_id in {concept.id, candidate.id}:
                        concept.parent_id = None
                if candidate.id in concept.relationships:
                    concept.relationships = list(
                        dict.fromkeys(
                            previous.id if identifier == candidate.id else identifier
                            for identifier in concept.relationships
                            if identifier != concept.id
                        )
                    )
            for target in session.scalars(
                select(SourceCoverageTarget).where(
                    SourceCoverageTarget.course_id == proposal.course_id
                )
            ):
                if candidate.id in target.mapped_concept_ids:
                    target.mapped_concept_ids = list(
                        dict.fromkeys(
                            previous.id if identifier == candidate.id else identifier
                            for identifier in target.mapped_concept_ids
                        )
                    )
            candidate.metadata_json = {
                **candidate.metadata_json,
                "active_in_inventory": False,
                "reconciled_into": previous.id,
            }
            candidate.coverage_status = "out_of_scope"
        selected = previous.id
    elif values.decision == "split" and not values.existing_id:
        raise ValueError("Record the original identity for an explicit split")
    if values.decision == "split":
        previous = require(session, entity, values.existing_id)
        if previous.course_id != proposal.course_id:
            raise ValueError("The original split identity belongs to another course")
    alias = session.scalar(
        select(IdentityAlias).where(
            IdentityAlias.course_id == proposal.course_id,
            IdentityAlias.entity_type == proposal.entity_type,
            IdentityAlias.semantic_key == proposal.candidate_key,
        )
    )
    if alias is None:
        alias = IdentityAlias(
            course_id=proposal.course_id,
            entity_type=proposal.entity_type,
            semantic_key=proposal.candidate_key,
            entity_id=selected,
        )
        session.add(alias)
    alias.entity_id = selected
    alias.origin = f"human_{values.decision}"
    alias.provenance = {
        "proposal_id": proposal.id,
        "sources": proposal.sources,
        "rationale": values.rationale,
        "previous_id": values.existing_id,
    }
    proposal.state = values.decision
    proposal.selected_id = selected
    proposal.rationale = values.rationale
    proposal.resolved_at = now()
    session.flush()
    return entity_data(proposal)
