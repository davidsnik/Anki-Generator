"""Persistent aliases plus source/semantic reconciliation; ambiguity needs a human."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from anki_generator.database.entities import Card, Revision
from anki_generator.database.pipeline_entities import IdentityAlias, IdentityProposal
from anki_generator.processing.contracts import IdentityMatchResult
from anki_generator.processing.state import digest
from anki_generator.services.semantic import SemanticIndex


def source_locations(refs: list[dict[str, Any]]) -> set[tuple[str, int]]:
    return {(ref["document_id"], ref["page_number"]) for ref in refs}


def reconcile(
    pipeline: Any,
    entity_type: str,
    semantic_key: str,
    payload: dict[str, Any],
    proposed_id: str,
    existing: list[dict[str, Any]],
) -> str:

    def unchanged(record):
        if entity_type == "concept":
            return (
                record["title"] == payload.get("title")
                and record["description"] == payload.get("statement")
                and record.get("metadata_json", {}).get("assumptions", [])
                == payload.get("assumptions", [])
            )
        return all(
            record.get(field) == payload.get(field) for field in ("question", "answer", "card_type")
        )

    with pipeline.sessions() as session:
        alias = session.scalar(
            select(IdentityAlias).where(
                IdentityAlias.course_id == pipeline.course_id,
                IdentityAlias.entity_type == entity_type,
                IdentityAlias.semantic_key == semantic_key,
            )
        )
        alias_record = next(
            (record for record in existing if alias and record["id"] == alias.entity_id), None
        )
        exact_record = next((record for record in existing if record["id"] == proposed_id), None)
        if alias and alias_record and unchanged(alias_record):
            return alias.entity_id
        if exact_record and unchanged(exact_record):
            _alias(
                session,
                pipeline.course_id,
                entity_type,
                semantic_key,
                proposed_id,
                payload,
                "exact_existing_identity",
            )
            session.commit()
            return proposed_id
    if not existing:
        with pipeline.sessions() as session:
            _alias(
                session,
                pipeline.course_id,
                entity_type,
                semantic_key,
                proposed_id,
                payload,
                "new_target",
            )
            session.commit()
        return proposed_id
    vectors = pipeline._vectors(existing, entity_type)
    query_id = f"candidate:{digest((semantic_key, payload))}"
    query = pipeline._vectors([{"id": query_id, **payload}], f"{entity_type}_candidate")[query_id]
    index = SemanticIndex(vectors)
    nearest = index.search(query, limit=min(pipeline.options.semantic_candidates, 8))
    by_id = {item["id"]: item for item in existing}
    candidate_locations = source_locations(payload.get("sources", []))
    candidates = []
    for identifier, score in nearest:
        prior = by_id[identifier]
        locations = source_locations(prior.get("sources", []))
        overlap = len(candidate_locations & locations) / max(
            1, len(candidate_locations | locations)
        )
        related_concept = (
            entity_type == "card"
            and prior.get("concept_id") == payload.get("concept_id")
            and bool(prior.get("concept_id"))
        )
        candidates.append(
            {
                "id": identifier,
                "score": score,
                "provenance_overlap": overlap,
                "related_concept": related_concept,
                **{
                    key: prior.get(key)
                    for key in ("title", "description", "question", "answer", "kind")
                },
                "assumptions": prior.get("metadata_json", {}).get("assumptions", []),
                "sources": prior.get("sources", [])[:4],
            }
        )
    relevant = [
        item
        for item in candidates
        if item["score"] >= 0.65
        and (item["provenance_overlap"] > 0 or item["related_concept"] or item["score"] >= 0.95)
    ]
    if not relevant:
        decision, chosen, reason = (
            "new",
            proposed_id,
            "No sufficiently related semantic/provenance candidate.",
        )
    else:
        review = pipeline._call(
            "identity",
            f"{entity_type}:{semantic_key}",
            {
                "entity_type": entity_type,
                "candidate": {**payload, "sources": payload.get("sources", [])[:4]},
                "source_inventory": {
                    "total": len(payload.get("sources", [])),
                    "hash": digest(payload.get("sources", [])),
                },
                "retrieved_items": relevant,
            },
            IdentityMatchResult,
        )
        pipeline._stage("identity", complete=True)
        chosen_record = next((item for item in relevant if item["id"] == review.existing_id), None)
        scores = sorted([item["score"] for item in relevant], reverse=True)
        margin = scores[0] - scores[1] if len(scores) > 1 else 1
        high_confidence = (
            chosen_record is not None
            and review.relation == "same"
            and review.assumptions_preserved
            and chosen_record["score"] >= pipeline.options.identity_similarity
            and margin >= pipeline.options.identity_margin
            and (chosen_record["provenance_overlap"] >= 0.5 or chosen_record["related_concept"])
        )
        if high_confidence:
            decision, chosen, reason = "semantic_source_match", chosen_record["id"], review.reason
        elif review.relation == "different":
            decision, chosen, reason = "new", proposed_id, review.reason
        else:
            from uuid import NAMESPACE_URL, uuid5

            # A changed meaning must never overwrite its old key/identity while
            # the human decision is pending.
            chosen = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{pipeline.course_id}:{entity_type}:pending:{semantic_key}:{digest(payload)}",
                )
            )
            decision, reason = "pending", review.reason
            with pipeline.sessions() as session:
                proposal = session.scalar(
                    select(IdentityProposal).where(
                        IdentityProposal.run_id == pipeline.run_id,
                        IdentityProposal.entity_type == entity_type,
                        IdentityProposal.candidate_key == semantic_key,
                    )
                )
                if proposal is None:
                    session.add(
                        IdentityProposal(
                            course_id=pipeline.course_id,
                            run_id=pipeline.run_id,
                            entity_type=entity_type,
                            candidate_key=semantic_key,
                            candidate_id=chosen,
                            candidate_payload=payload,
                            candidates=relevant,
                            sources=payload.get("sources", []),
                            reason=reason,
                        )
                    )
                session.commit()
            pipeline._warning(
                "An identity match is ambiguous. Inspect the reconciliation "
                "proposal before exporting affected cards."
            )
    if decision == "new" and any(record["id"] == chosen for record in existing):
        from uuid import NAMESPACE_URL, uuid5

        chosen = str(
            uuid5(
                NAMESPACE_URL,
                f"{pipeline.course_id}:{entity_type}:new:{semantic_key}:{digest(payload)}",
            )
        )
    if decision != "pending":
        with pipeline.sessions() as session:
            _alias(
                session, pipeline.course_id, entity_type, semantic_key, chosen, payload, decision
            )
            session.commit()
    return chosen


def _alias(session, course_id, entity_type, key, entity_id, payload, origin):
    alias = session.scalar(
        select(IdentityAlias).where(
            IdentityAlias.course_id == course_id,
            IdentityAlias.entity_type == entity_type,
            IdentityAlias.semantic_key == key,
        )
    )
    if alias is not None:
        alias.entity_id = entity_id
        alias.origin = origin
        alias.provenance = {
            "sources": payload.get("sources", []),
            "assumptions": payload.get("assumptions", []),
        }
    else:
        session.add(
            IdentityAlias(
                course_id=course_id,
                entity_type=entity_type,
                semantic_key=key,
                entity_id=entity_id,
                provenance={
                    "sources": payload.get("sources", []),
                    "assumptions": payload.get("assumptions", []),
                },
                origin=origin,
            )
        )


def unresolved_for_cards(session, cards: list[Card]) -> list[IdentityProposal]:
    if not cards:
        return []
    ids = {card.id for card in cards}
    concepts = {card.concept_id for card in cards if card.concept_id}
    for card in cards:
        revision = session.scalar(
            select(Revision).where(
                Revision.card_id == card.id, Revision.revision_number == card.revision_number
            )
        )
        if revision:
            concepts.update(revision.snapshot.get("concept_ids", []))
    return [
        proposal
        for proposal in session.scalars(
            select(IdentityProposal).where(
                IdentityProposal.course_id == cards[0].course_id,
                IdentityProposal.state == "pending",
            )
        )
        if proposal.candidate_id in (ids if proposal.entity_type == "card" else concepts)
    ]
