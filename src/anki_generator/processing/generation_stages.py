"""Semantic card targets, incremental reuse, and requested revisions."""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from anki_generator.database.entities import (
    Card,
    Concept,
    Revision,
    Run,
)
from anki_generator.processing.contracts import (
    CardCandidate,
    EvidenceReference,
    GeneratedCards,
)

from .state import digest, entity_data


class GenerationStages:
    def _generation_payload(self, concepts: list[dict[str, Any]]) -> dict[str, Any]:
        # Keep the complete evidence inventory in persistence. Each generation
        # unit receives bounded, role-diverse supporting references; the independent
        # source audit still visits every original page/region.
        from anki_generator.services.context_budget import token_upper_bound

        selected_concepts = []
        refs = []
        for concept in concepts:
            selected = []
            roles = set()
            total = 0
            ordered = sorted(
                concept["sources"],
                key=lambda ref: (
                    self.evidence.documents.get(ref["document_id"], {}).get("category", ""),
                    ref["document_id"],
                    ref["page_number"],
                ),
            )
            for diverse in (True, False):
                for ref in ordered:
                    role = self.evidence.documents.get(ref["document_id"], {}).get("category", "")
                    if ref in selected or (diverse and role in roles):
                        continue
                    size = token_upper_bound(ref)
                    if selected and (
                        len(selected) >= 3 or total + size > self.options.input_token_budget // 6
                    ):
                        continue
                    selected.append(ref)
                    roles.add(role)
                    total += size
            selected_concepts.append(
                {
                    **concept,
                    "sources": selected,
                    "exercise_analysis": concept["exercise_analysis"][:4],
                    "evidence_inventory": {
                        "total_sources": len(concept["sources"]),
                        "included_sources": len(selected),
                        "inventory_hash": digest(concept["sources"]),
                        "total_exercise_analyses": len(concept["exercise_analysis"]),
                        "selection": "bounded_role_diverse_support",
                    },
                }
            )
            refs.extend(EvidenceReference.model_validate(ref) for ref in selected)
        concepts = selected_concepts
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
                            "evidence_inventory",
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
            "available_media": list(
                dict.fromkeys(
                    [
                        f"{r.document_id}:{region['id']}"
                        for r in refs
                        for region in self.evidence.pages.get(
                            (r.document_id, r.page_number), {}
                        ).get("regions", [])
                    ]
                )
            )[: self.options.vision_batch_images],
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
            if (
                not gap_round
                and self.mode == "generate"
                and not self.request.get("instruction")
                and not self.request.get("retry_stage")
            ):
                with self.sessions() as session:
                    stored = session.get(Concept, concept["id"])
                    prior = stored.metadata_json.get("generation_policy")
                    prior_ids = stored.metadata_json.get("generated_card_ids")
                    if (
                        prior == policy
                        and prior_ids is not None
                        and all(session.get(Card, cid) is not None for cid in prior_ids)
                    ):
                        for identifier in prior_ids:
                            self._record_task_card(session, session.get(Card, identifier))
                        session.commit()
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
            ][: self.options.semantic_candidates]
            generated = self._call(
                "generation",
                f"{key}:gap-{gap_round}",
                payload,
                GeneratedCards,
                images=self.evidence.image_paths(
                    [
                        EvidenceReference.model_validate(r)
                        for c in payload["concepts"]
                        for r in c["sources"]
                    ],
                    limit=min(self.options.vision_batch_images, 2),
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
                        "generated_card_ids": [
                            self._resolved_card_ids.get(
                                self._candidate_id(c), self._candidate_id(c)
                            )
                            for c in generated.cards
                        ],
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

    def _check_requested_revision(self, session, card) -> None:
        expected = self.request.get("expected_revision")
        owned = session.get(Run, self.run_id).checkpoints.get(f"requested-revision:{card.id}")
        if expected is not None and card.revision_number not in {expected, owned}:
            raise ValueError(
                "The selected card changed after this run was prepared. "
                "Reload and submit a new revision request; the newer edit was preserved."
            )

    def _revise_requested(self) -> None:
        card_id = self.request.get("card_id")
        with self.sessions() as session:
            card = session.get(Card, card_id)
            if card is None or card.course_id != self.course_id:
                raise ValueError("The requested card does not exist in this course.")
            self._check_requested_revision(session, card)
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
