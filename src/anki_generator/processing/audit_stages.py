"""Semantic comparison, explicit concept coverage, and workload metrics."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from anki_generator.database.entities import (
    Card,
    Concept,
    Revision,
    Run,
)
from anki_generator.processing.contracts import (
    PROMPT_VERSION,
    CoverageReview,
    DuplicateDecision,
)

from .state import entity_data


class AuditStages:
    def _deduplicate(self) -> None:
        with self.sessions() as session:
            cards = [
                entity_data(c)
                for c in session.scalars(
                    select(Card)
                    .where(
                        Card.course_id == self.course_id,
                        Card.archived.is_(False),
                        Card.verification_status == "verified",
                        Card.review_status != "rejected",
                    )
                    .order_by(Card.created_at)
                )
            ]
        self._stage("deduplication", total=len(cards))
        accepted: list[dict[str, Any]] = []
        for card in cards:
            tokens = set(re.findall(r"\w+", (card["question"] + " " + card["answer"]).casefold()))
            retrieved = []
            for other in accepted:
                other_tokens = set(
                    re.findall(r"\w+", (other["question"] + " " + other["answer"]).casefold())
                )
                score = len(tokens & other_tokens) / max(len(tokens | other_tokens), 1)
                if card["concept_id"] == other["concept_id"] or score >= 0.18:
                    retrieved.append(
                        (score + int(card["concept_id"] == other["concept_id"]), other)
                    )
            retrieved.sort(key=lambda item: item[0], reverse=True)
            candidates = [item[1] for item in retrieved[:8]]
            if not candidates:
                accepted.append(card)
                self._progress("deduplication", card["id"], "no_candidate_pairs")
                continue
            decision = self._call(
                "deduplication",
                card["id"],
                {"candidate": card, "retrieved_cards": candidates},
                DuplicateDecision,
            )
            valid_duplicate = decision.duplicate and decision.redundant_with in {
                c["id"] for c in candidates
            }
            if decision.duplicate and not valid_duplicate:
                self._warning(
                    "A semantic duplicate proposal referenced an unknown card and was ignored."
                )
            self._save_verification(
                card["id"],
                card["revision_number"],
                "deduplication",
                {
                    "verdict": "duplicate" if valid_duplicate else "pass",
                    **decision.model_dump(mode="json"),
                },
            )
            if (
                valid_duplicate
                and not card["manually_edited"]
                and card["review_status"] != "approved"
            ):
                with self.sessions() as session:
                    stored = session.get(Card, card["id"])
                    stored.verification_status = "duplicate"
                    stored.issues = [
                        *stored.issues,
                        {
                            "category": "redundancy",
                            "severity": "warning",
                            "message": decision.reason,
                            "instruction": f"Compare with card {decision.redundant_with}.",
                        },
                    ]
                    session.commit()
            else:
                accepted.append(card)
        self._stage("deduplication", complete=True)

    def _coverage(self, *, generate_missing: bool) -> None:
        rounds = (
            min(max(int(self.config.get("coverage_rounds", 1)), 0), 3) if generate_missing else 0
        )
        eligible = self._eligible_concepts()
        by_key = {c["metadata_json"].get("canonical_key", c["id"]): c for c in eligible}
        for round_number in range(rounds + 1):
            with self.sessions() as session:
                accepted = [
                    entity_data(c)
                    for c in session.scalars(
                        select(Card).where(
                            Card.course_id == self.course_id,
                            Card.archived.is_(False),
                            Card.verification_status == "verified",
                            Card.review_status != "rejected",
                        )
                    )
                ]
                mappings = {}
                for card in accepted:
                    latest = session.scalar(
                        select(Revision).where(
                            Revision.card_id == card["id"],
                            Revision.revision_number == card["revision_number"],
                        )
                    )
                    concept_ids = latest.snapshot.get("concept_ids", []) if latest else []
                    mappings[card["id"]] = list(
                        dict.fromkeys(
                            [*concept_ids, *([card["concept_id"]] if card["concept_id"] else [])]
                        )
                    )
            covered_ids = {concept_id for ids in mappings.values() for concept_id in ids}
            result = self._call(
                "coverage",
                f"course:round-{round_number}",
                {
                    "inventory": [{**c, "key": key} for key, c in by_key.items()],
                    "accepted_cards": accepted,
                    "explicit_card_concept_mappings": mappings,
                    "source_roles": [
                        {
                            "document_id": d["id"],
                            "role": d["category"],
                            "filename": d["filename"],
                            "extraction_status": d["extraction"]["status"],
                        }
                        for d in self.documents
                    ],
                    "criteria": self.config.get("criteria", {}),
                    "deterministic_uncovered_keys": [
                        key for key, c in by_key.items() if c["id"] not in covered_ids
                    ],
                },
                CoverageReview,
            )
            gaps = {gap.concept_key: gap for gap in result.gaps if gap.concept_key in by_key}
            missing_keys = {key for key, c in by_key.items() if c["id"] not in covered_ids} | set(
                gaps
            )
            for warning in result.warnings + result.neglected_sources:
                self._warning(warning)
            with self.sessions() as session:
                for key, concept in by_key.items():
                    stored = session.get(Concept, concept["id"])
                    stored.coverage_status = (
                        "uncovered"
                        if stored.id not in covered_ids
                        else ("partial" if key in gaps else "covered")
                    )
                    if key in gaps:
                        stored.metadata_json = {
                            **stored.metadata_json,
                            "coverage_gap": gaps[key].model_dump(mode="json"),
                        }
                    else:
                        metadata = dict(stored.metadata_json)
                        metadata.pop("coverage_gap", None)
                        stored.metadata_json = metadata
                run = session.get(Run, self.run_id)
                unresolved_sources = sum(
                    d["extraction"].get("effective_status", d["extraction"]["status"]) != "complete"
                    for d in self.documents
                )
                run.metrics = {
                    **run.metrics,
                    "concepts_total": len(by_key),
                    "concepts_covered": len(by_key) - len(missing_keys),
                    "coverage_gaps": [
                        {
                            "concept_key": k,
                            "title": by_key[k]["title"],
                            "reason": gaps[k].reason
                            if k in gaps
                            else "No verified card maps to this concept.",
                        }
                        for k in sorted(missing_keys)
                    ],
                    "unresolved_sources": unresolved_sources,
                    "overrepresented": result.overrepresented,
                    "coverage_complete": not missing_keys and unresolved_sources == 0,
                }
                session.commit()
            self._stage("coverage", complete=True)
            if not missing_keys or round_number == rounds:
                return
            targets = [
                by_key[k]
                for k in sorted(missing_keys)
                if not by_key[k]["metadata_json"].get("uncertain")
                and not by_key[k]["metadata_json"].get("conflicts")
            ]
            if not targets:
                return
            for target in targets:
                key = target["metadata_json"].get("canonical_key", target["id"])
                if key in gaps:
                    target["coverage_feedback"] = gaps[key].model_dump(mode="json")
            self._generate(targets, gap_round=round_number + 1)
            self._deduplicate()

    def _metrics(self) -> None:
        with self.sessions() as session:
            cards = list(
                session.scalars(
                    select(Card).where(Card.course_id == self.course_id, Card.archived.is_(False))
                )
            )
            run = session.get(Run, self.run_id)
            counts = {
                status: sum(card.verification_status == status for card in cards)
                for status in {card.verification_status for card in cards}
            }
            run.metrics = {
                **run.metrics,
                "cards_total": len(cards),
                "verification_counts": counts,
                "human_approved": sum(c.review_status == "approved" for c in cards),
                "human_rejected": sum(c.review_status == "rejected" for c in cards),
                "estimated_review_minutes": round(
                    sum(max(10, len(c.answer.split()) * 0.8) for c in cards) / 60, 1
                ),
                "review_estimate_basis": (
                    "10 seconds minimum per card, 0.8 seconds per answer word; "
                    "workload estimate, not provider cost."
                ),
                "prompt_version": PROMPT_VERSION,
            }
            run.progress = {
                **run.progress,
                "cards": len(cards),
                "verified": counts.get("verified", 0),
            }
            session.commit()
