"""Semantic comparison, explicit concept coverage, and workload metrics."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from anki_generator.database.entities import (
    Card,
    Concept,
    Revision,
    Run,
    Stage,
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
        from anki_generator.services.semantic import SemanticIndex

        vectors = self._vectors(cards, "card") if cards else {}
        index = SemanticIndex(vectors)
        by_id = {card["id"]: card for card in cards}
        accepted: list[dict[str, Any]] = []
        candidate_pairs = 0
        for card in cards:
            nearest = index.search(
                vectors[card["id"]],
                limit=self.options.semantic_candidates,
                exclude={card["id"]},
                allowed={item["id"] for item in accepted},
            )
            candidates = [by_id[identifier] for identifier, score in nearest if score >= 0.2]
            candidate_pairs += len(candidates)
            if not candidates:
                accepted.append(card)
                self._progress("deduplication", card["id"], "no_candidate_pairs")
                continue
            decision = self._call(
                "deduplication",
                card["id"],
                {
                    "candidate": {
                        key: card[key]
                        for key in ("id", "question", "answer", "card_type", "concept_id", "kind")
                    },
                    "retrieved_cards": [
                        {
                            key: c[key]
                            for key in (
                                "id",
                                "question",
                                "answer",
                                "card_type",
                                "concept_id",
                                "kind",
                            )
                        }
                        for c in candidates
                    ],
                    "retrieval": "neural_embeddings_cosine_candidates_not_equivalence",
                },
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
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.metrics = {
                **run.metrics,
                "semantic_dedup": {
                    "vectors": len(vectors),
                    "candidate_pairs": candidate_pairs,
                    "confirmed_duplicates": sum(
                        c.verification_status == "duplicate"
                        for c in session.scalars(
                            select(Card).where(Card.course_id == self.course_id)
                        )
                    ),
                    "representation": "neural_embeddings",
                    "verifier": "independent_llm_comparison",
                },
            }
            session.commit()
        self._stage("deduplication", complete=True)

    def _coverage(self, *, generate_missing: bool) -> None:
        rounds = self.options.coverage_rounds if generate_missing else 0
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
            from anki_generator.services.context_budget import bounded_batches

            units = []
            for key, concept in by_key.items():
                mapped_cards = [card for card in accepted if concept["id"] in mappings[card["id"]]]
                units.append(
                    {
                        "key": key,
                        "id": concept["id"],
                        "title": concept["title"],
                        "kind": concept["kind"],
                        "statement": concept["description"],
                        "assumptions": concept["metadata_json"].get("assumptions", []),
                        "exercise_analysis": concept["exercise_analysis"][:4],
                        "mapped_cards_total": len(mapped_cards),
                        "card_selection": "bounded_mapped_representatives",
                        "cards": [
                            {
                                field: card[field]
                                for field in ("id", "question", "answer", "kind", "concept_id")
                            }
                            for card in mapped_cards[: self.options.semantic_candidates]
                        ],
                    }
                )
            results = []
            batches = bounded_batches(
                units,
                max_bytes=self.options.input_token_budget // 2,
                max_items=self.options.coverage_batch_size,
            )
            self._stage("coverage", total=len(batches))
            for batch_index, batch in enumerate(batches):
                concept_ids = {unit["id"] for unit in batch}
                results.append(
                    self._call(
                        "coverage",
                        f"course:round-{round_number}:batch-{batch_index}",
                        {
                            "inventory": [
                                {key: value for key, value in unit.items() if key != "cards"}
                                for unit in batch
                            ],
                            "accepted_cards": [card for unit in batch for card in unit["cards"]],
                            "explicit_card_concept_mappings": {
                                cid: ids for cid, ids in mappings.items() if concept_ids & set(ids)
                            },
                            "criteria": self.config.get("criteria", {}),
                            "deterministic_uncovered_keys": [
                                key
                                for key, c in by_key.items()
                                if c["id"] in concept_ids and c["id"] not in covered_ids
                            ],
                        },
                        CoverageReview,
                    )
                )
            result = CoverageReview(
                gaps=[gap for r in results for gap in r.gaps],
                overrepresented=[v for r in results for v in r.overrepresented],
                neglected_sources=[v for r in results for v in r.neglected_sources],
                warnings=[v for r in results for v in r.warnings],
            )
            source_gaps = self._audit_source_targets(accepted)
            gaps = {gap.concept_key: gap for gap in result.gaps if gap.concept_key in by_key}
            missing_keys = {key for key, c in by_key.items() if c["id"] not in covered_ids} | set(
                gaps
            )
            source_gap_ids = {cid for target in source_gaps for cid in target["mapped_concept_ids"]}
            missing_keys |= {
                key for key, concept in by_key.items() if concept["id"] in source_gap_ids
            }
            for warning in result.warnings + result.neglected_sources:
                self._warning(warning)
            with self.sessions() as session:
                for key, concept in by_key.items():
                    stored = session.get(Concept, concept["id"])
                    stored.coverage_status = (
                        "uncovered"
                        if stored.id not in covered_ids
                        else ("partial" if key in missing_keys else "covered")
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
                    "coverage_complete": not missing_keys
                    and unresolved_sources == 0
                    and run.metrics.get("independent_inspection", {}).get("unresolved_findings", 0)
                    == 0
                    and self.options.source_audit
                    and bool(run.metrics.get("source_coverage", {}).get("targets_total"))
                    and run.metrics.get("source_coverage", {}).get("unresolved", 1) == 0,
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
                independent = [
                    gap for gap in source_gaps if target["id"] in gap["mapped_concept_ids"]
                ]
                if independent:
                    target["coverage_feedback"] = {
                        "inventory_feedback": target.get("coverage_feedback"),
                        "source_competency_gaps": [
                            {
                                "title": gap["title"],
                                "kind": gap["kind"],
                                "competency": gap["metadata_json"].get("competency"),
                                "missing_aspects": gap["metadata_json"].get("missing_aspects"),
                                "reason": gap["metadata_json"].get("assessment_reason"),
                            }
                            for gap in independent
                        ],
                    }
            targets.sort(key=lambda concept: -concept["importance"])
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
            from datetime import datetime

            wall_times = {
                stage.name: max(
                    0,
                    (
                        datetime.fromisoformat(stage.finished_at)
                        - datetime.fromisoformat(stage.started_at)
                    ).total_seconds(),
                )
                for stage in session.scalars(select(Stage).where(Stage.run_id == self.run_id))
                if stage.started_at and stage.finished_at
            }
            run.metrics = {
                **run.metrics,
                "stage_wall_seconds": wall_times,
                "stage_timing_basis": (
                    "Wall windows may overlap; stage_seconds sums measured "
                    "API-unit elapsed time including queue waits."
                ),
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
            if run.progress.get("task_counter_version"):
                by_id = {card.id: card for card in cards}
                markers = {
                    key: value
                    for key, value in run.checkpoints.items()
                    if key.startswith("task-card:")
                }
                run.progress = {
                    **run.progress,
                    "cards_verified": sum(
                        bool(
                            by_id.get(key.removeprefix("task-card:"))
                            and by_id[key.removeprefix("task-card:")].verification_status
                            == "verified"
                        )
                        for key in markers
                    ),
                }
            session.commit()
