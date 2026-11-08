"""Semantic card targets, incremental reuse, and requested revisions."""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from anki_generator.database.entities import (
    Card,
    Concept,
    Revision,
)
from anki_generator.processing.contracts import (
    CardCandidate,
    EvidenceReference,
    GeneratedCards,
)

from .state import digest, entity_data


class GenerationStages:
    def _generation_payload(self, concepts: list[dict[str, Any]]) -> dict[str, Any]:
        refs = [EvidenceReference.model_validate(r) for c in concepts for r in c["sources"]]
        return {
            "course": self.course["name"],
            "language": self.course["language"],
            "criteria": self.config.get("criteria", self.course["criteria"]),
            "instruction": self.request.get("instruction", ""),
            "concepts": [
                {
                    **{
                        name: c[name]
                        for name in (
                            "id",
                            "title",
                            "description",
                            "kind",
                            "parent_id",
                            "importance",
                            "sources",
                            "relationships",
                            "exercise_analysis",
                        )
                    },
                    "key": c["metadata_json"].get("canonical_key", c["id"]),
                    "assumptions": c["metadata_json"].get("assumptions", []),
                    "uncertain": c["metadata_json"].get("uncertain", False),
                    "conflicts": c["metadata_json"].get("conflicts", []),
                }
                for c in concepts
            ],
            "original_evidence": self.evidence.sources(refs),
            "available_media": [
                f"{r.document_id}:{region['id']}"
                for r in refs
                for region in self.evidence.pages.get((r.document_id, r.page_number), {}).get(
                    "regions", []
                )
            ],
        }

    def _generate(
        self, target_concepts: list[dict[str, Any]] | None = None, *, gap_round: int = 0
    ) -> None:
        concepts = self._eligible_concepts() if target_concepts is None else target_concepts
        self._stage("generation", total=len(concepts))
        for concept in concepts:
            key = concept["metadata_json"].get("canonical_key", concept["id"])
            payload = self._generation_payload([concept])
            if gap_round:
                payload["coverage_repair"] = {
                    "round": gap_round,
                    "feedback": concept.get(
                        "coverage_feedback",
                        {
                            "reason": "No verified card explicitly maps to this learning target. "
                            "Generate a supported missing target, avoiding existing cards."
                        },
                    ),
                }
            policy = digest(
                {
                    "payload": payload,
                    "models": self.config.get("models", {}),
                    "effort": self.config.get("reasoning_effort", "high"),
                    "max_revisions": self.config.get("max_revisions", 2),
                    "extraction": self.config.get("extraction", {}),
                    "prompts": self._prompt_contracts(),
                }
            )
            if not gap_round and self.mode == "generate" and not self.request.get("instruction"):
                with self.sessions() as session:
                    stored = session.get(Concept, concept["id"])
                    prior = stored.metadata_json.get("generation_policy")
                    prior_ids = stored.metadata_json.get("generated_card_ids")
                    if (
                        prior == policy
                        and prior_ids is not None
                        and all(session.get(Card, cid) is not None for cid in prior_ids)
                    ):
                        self._progress("generation", f"{key}:reused", "unchanged_generation_policy")
                        continue
            with self.sessions() as session:
                existing = [
                    entity_data(c)
                    for c in session.scalars(
                        select(Card).where(
                            Card.course_id == self.course_id, Card.archived.is_(False)
                        )
                    )
                ]
            payload["existing_targets"] = [
                {"id": c["id"], "question": c["question"], "answer": c["answer"]}
                for c in existing
                if c["concept_id"] == concept["id"]
            ]
            generated = self._call(
                "generation",
                f"{key}:gap-{gap_round}",
                payload,
                GeneratedCards,
                images=self.evidence.image_paths(
                    [EvidenceReference.model_validate(r) for r in concept["sources"]]
                ),
            )
            for omission in generated.omissions:
                self._warning(f"{concept['title']}: {omission}")
            for candidate in generated.cards:
                self._process_candidate(candidate)
            if not gap_round:
                with self.sessions() as session:
                    stored = session.get(Concept, concept["id"])
                    stored.metadata_json = {
                        **stored.metadata_json,
                        "generation_policy": policy,
                        "generated_card_ids": [self._candidate_id(c) for c in generated.cards],
                    }
                    session.commit()
        self._stage("generation", complete=True)

    def _candidate_id(self, candidate: CardCandidate) -> str:
        if not candidate.identity_key.strip():
            raise ValueError("A generated card is missing a stable semantic target identity.")
        # Wording never participates in identity. Existing IDs survive regeneration.
        concept_ids = sorted(
            c["id"]
            for c in self.concepts
            if c["metadata_json"].get("canonical_key", c["id"]) in candidate.concept_keys
        )
        scope = ":".join(concept_ids or sorted(candidate.concept_keys))
        return str(uuid5(NAMESPACE_URL, f"{self.course_id}:card:{scope}:{candidate.identity_key}"))

    def _revise_requested(self) -> None:
        card_id = self.request.get("card_id")
        with self.sessions() as session:
            card = session.get(Card, card_id)
            if card is None or card.course_id != self.course_id:
                raise ValueError("The requested card does not exist in this course.")
            if (
                card.manually_edited or card.review_status in {"approved", "rejected"}
            ) and not self.request.get("overwrite_manual"):
                raise ValueError(
                    "Confirm replacement of the human-edited or reviewed card before regeneration."
                )
            data = entity_data(card)
            latest = session.scalar(
                select(Revision).where(
                    Revision.card_id == card_id, Revision.revision_number == card.revision_number
                )
            )
            semantic_key = latest.snapshot.get("identity_key", card_id) if latest else card_id
        concepts = [c for c in self.concepts if c["id"] == data["concept_id"]]
        generated = self._call(
            "revision",
            f"human:{card_id}",
            {
                **self._generation_payload(concepts),
                "existing_card": data,
                "identity_key": semantic_key,
                "instruction": self.request.get("instruction", ""),
                "original_evidence": self.evidence.sources(
                    [EvidenceReference.model_validate(r) for r in data["sources"]]
                ),
            },
            GeneratedCards,
            images=self.evidence.image_paths(
                [EvidenceReference.model_validate(r) for r in data["sources"]]
            ),
        )
        if len(generated.cards) != 1:
            raise ValueError(
                "The model could not produce one supported revision. The original "
                "card is preserved."
            )
        self._stage("revision", complete=True)
        generated.cards[0].identity_key = semantic_key
        self._process_candidate(generated.cards[0], card_id=card_id, origin="requested_revision")
        self._deduplicate()
        self._metrics()
