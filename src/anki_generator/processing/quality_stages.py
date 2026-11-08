"""Independent factual, pedagogical, and mathematical checks with finite repair."""

from __future__ import annotations

import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel
from sqlalchemy import select

from anki_generator.database.entities import (
    Card,
    Revision,
    Run,
    Verification,
)
from anki_generator.processing.contracts import (
    PROMPT_VERSION,
    CardCandidate,
    EvidenceReference,
    GeneratedCards,
    QualityIssue,
    QualityReview,
)
from anki_generator.processing.mathematics import check_identity

from .state import digest


class QualityStages:
    def _persist_candidate(
        self, candidate: CardCandidate, *, card_id: str | None = None, origin: str = "generated"
    ) -> tuple[str, int] | None:
        card_id = card_id or self._candidate_id(candidate)
        candidate.sources = self.evidence.enrich(candidate.sources)
        concept_by_key = {
            c["metadata_json"].get("canonical_key", c["id"]): c for c in self.concepts
        }
        concept_ids = [
            concept_by_key[k]["id"] for k in candidate.concept_keys if k in concept_by_key
        ]
        errors = self.evidence.validate(candidate.sources)
        if not concept_ids or any(key not in concept_by_key for key in candidate.concept_keys):
            errors.append("The card does not map completely to existing course concepts.")
        eligible_ids = {c["id"] for c in self._eligible_concepts()}
        if any(concept_id not in eligible_ids for concept_id in concept_ids):
            errors.append("The card maps to an excluded concept or a topic outside this run.")
        criteria = self.config.get("criteria", self.course.get("criteria", {}))
        if candidate.card_type not in criteria.get("card_types", ["basic", "cloze"]):
            errors.append("The card type is excluded by the generation criteria.")
        if candidate.category == "proof" and criteria.get("proof_treatment") == "exclude":
            errors.append("Proof cards are excluded by the generation criteria.")
        if candidate.category == "example" and criteria.get("example_treatment") == "exclude":
            errors.append("Example cards are excluded by the generation criteria.")
        if not criteria.get("include_explanations", True):
            candidate.explanation = ""
        if not criteria.get("include_diagrams", True):
            candidate.media = []
        image_refs, image_errors = self.evidence.media(candidate.media)
        errors.extend(image_errors)
        if candidate.card_type == "cloze" and not re.search(
            r"\{\{c[1-9]\d*::.+?\}\}", candidate.question, re.DOTALL
        ):
            errors.append("A cloze card has no valid Anki cloze deletion.")
        if not candidate.question.strip() or (
            candidate.card_type == "basic" and not candidate.answer.strip()
        ):
            errors.append("A card question or answer is empty.")
        with self.sessions() as session:
            card = session.get(Card, card_id)
            if (
                card
                and (card.manually_edited or card.review_status in {"approved", "rejected"})
                and not self.request.get("overwrite_manual")
            ):
                self._warning(
                    "A human-edited or reviewed card was preserved. Explicitly "
                    "confirm replacement to regenerate it."
                )
                return None
            snapshot = candidate.model_dump(mode="json")
            snapshot["concept_ids"] = concept_ids
            if card is None:
                card = Card(
                    id=card_id,
                    course_id=self.course_id,
                    question=candidate.question,
                    concept_id=concept_ids[0] if concept_ids else None,
                    note_guid=str(uuid5(NAMESPACE_URL, f"anki-note:{card_id}")),
                )
                session.add(card)
                revision_number = 1
            else:
                previous = session.scalar(
                    select(Revision).where(
                        Revision.card_id == card_id,
                        Revision.revision_number == card.revision_number,
                    )
                )
                revision_number = (
                    card.revision_number
                    if previous and previous.snapshot == snapshot
                    else card.revision_number + 1
                )
            existing_revision = session.scalar(
                select(Revision).where(
                    Revision.card_id == card_id, Revision.revision_number == revision_number
                )
            )
            if existing_revision is None:
                session.add(
                    Revision(
                        card_id=card_id,
                        revision_number=revision_number,
                        snapshot=snapshot,
                        origin=origin,
                        instruction=self.request.get("instruction", ""),
                    )
                )
            card.card_type = candidate.card_type
            card.kind = candidate.category
            card.question = candidate.question
            card.answer = candidate.answer
            card.explanation = candidate.explanation
            card.tags = candidate.tags
            card.sources = [r.model_dump(mode="json") for r in candidate.sources]
            card.image_refs = image_refs
            card.concept_id = concept_ids[0] if concept_ids else None
            card.verification_status = "needs_review" if errors else "unverified"
            card.review_status = "pending"
            card.manually_edited = False
            card.revision_number = revision_number
            card.issues = [
                {
                    "category": "evidence",
                    "severity": "error",
                    "message": e,
                    "instruction": "Inspect the original and correct the reference or claim.",
                }
                for e in errors
            ]
            session.commit()
        return card_id, revision_number

    def _review(
        self, card_id: str, revision_number: int, stage: str, candidate: CardCandidate
    ) -> QualityReview:
        payload = {
            "card": candidate.model_dump(mode="json"),
            "original_evidence": self.evidence.sources(candidate.sources),
            "criteria": self.config.get("criteria", {}),
            "evidence_validation_errors": self.evidence.validate(candidate.sources),
        }
        images = (
            self.evidence.image_paths(candidate.sources, limit=100000)
            if stage in {"factual", "mathematical"}
            else []
        )
        batches = [images[offset : offset + 12] for offset in range(0, len(images), 12)] or [[]]
        reviews = []
        for batch_index, batch in enumerate(batches):
            batch_payload = {
                **payload,
                "visual_batch_index": batch_index,
                "visual_batches_total": len(batches),
            }
            reviews.append(
                self._call(
                    stage,
                    f"{card_id}:revision-{revision_number}:visual-{batch_index}",
                    batch_payload,
                    QualityReview,
                    images=batch,
                )
            )
        priority = {"pass": 0, "uncertain": 1, "revise": 2, "reject": 3}
        review = QualityReview(
            verdict=max((r.verdict for r in reviews), key=priority.__getitem__),
            issues=[issue for result in reviews for issue in result.issues],
            reasoning="\n".join(result.reasoning for result in reviews),
            checked_assumptions=list(
                dict.fromkeys(a for result in reviews for a in result.checked_assumptions)
            ),
            criteria=list(dict.fromkeys(c for result in reviews for c in result.criteria)),
        )
        # A contradictory structured result cannot pass because its verdict says so.
        if review.verdict == "pass" and any(i.severity == "error" for i in review.issues):
            review.verdict = "revise"
        self._save_verification(card_id, revision_number, stage, review)
        self._stage(stage, complete=True)
        return review

    def _save_verification(
        self, card_id: str, revision: int, stage: str, review: QualityReview | dict[str, Any]
    ) -> None:
        value = review.model_dump(mode="json") if isinstance(review, BaseModel) else review
        with self.sessions() as session:
            existing = session.scalar(
                select(Verification).where(
                    Verification.card_id == card_id,
                    Verification.run_id == self.run_id,
                    Verification.revision_number == revision,
                    Verification.stage == stage,
                )
            )
            if existing is None:
                existing = Verification(
                    card_id=card_id,
                    run_id=self.run_id,
                    revision_number=revision,
                    stage=stage,
                    verdict=value["verdict"],
                )
                session.add(existing)
            existing.verdict = value["verdict"]
            existing.issues = value.get("issues", [])
            existing.evidence = self.evidence.sources(
                [EvidenceReference.model_validate(r) for r in session.get(Card, card_id).sources]
            )
            existing.model = "sympy-bounded-ast" if stage == "symbolic" else self._model(stage)
            existing.prompt_version = PROMPT_VERSION
            existing.details = value
            session.commit()

    def _process_candidate(
        self, candidate: CardCandidate, *, card_id: str | None = None, origin: str = "generated"
    ) -> None:
        mathematical_kinds = {"theorem", "property", "assumption"}
        mapped = [
            c
            for c in self.concepts
            if c["metadata_json"].get("canonical_key", c["id"]) in candidate.concept_keys
        ]
        if any(c["kind"] in mathematical_kinds for c in mapped) or re.search(
            r"[=<>∑∫∀∃≤≥]|\\(?:frac|sum|int|forall|exists|mathbb|begin)",
            candidate.question + " " + candidate.answer,
        ):
            candidate.mathematical = True
        original_id = card_id or self._candidate_id(candidate)
        final_key = f"card-final:{original_id}:{digest(candidate.model_dump(mode='json'))}"
        with self.sessions() as session:
            if final_key in session.get(Run, self.run_id).checkpoints:
                return
        maximum = min(max(int(self.config.get("max_revisions", 2)), 0), 5)
        for attempt in range(maximum + 1):
            self._check()
            saved = self._persist_candidate(candidate, card_id=card_id, origin=origin)
            if saved is None:
                return
            card_id, revision = saved
            with self.sessions() as session:
                evidence_issues = list(session.get(Card, card_id).issues)
            factual = self._review(card_id, revision, "factual", candidate)
            pedagogical = self._review(card_id, revision, "pedagogical", candidate)
            reviews = [factual, pedagogical]
            if candidate.mathematical:
                mathematical = self._review(card_id, revision, "mathematical", candidate)
                reviews.append(mathematical)
                checks = [check_identity(check) for check in candidate.symbolic_checks]
                if checks:
                    verdict = (
                        "revise"
                        if any(c["verdict"] == "revise" for c in checks)
                        else (
                            "uncertain"
                            if any(c["verdict"] == "uncertain" for c in checks)
                            else "pass"
                        )
                    )
                    self._save_verification(
                        card_id,
                        revision,
                        "symbolic",
                        {"verdict": verdict, "checks": checks, "issues": [], "formal_proof": False},
                    )
                    if verdict != "pass":
                        reviews.append(
                            QualityReview(
                                verdict=verdict,
                                reasoning="See bounded symbolic checks.",
                                checked_assumptions=[],
                                criteria=[],
                                issues=[
                                    QualityIssue(
                                        category="symbolic",
                                        severity="error" if verdict == "revise" else "warning",
                                        message=c["reason"],
                                        instruction=(
                                            "Check the equality and its "
                                            "domain against the original."
                                        ),
                                    )
                                    for c in checks
                                    if c["verdict"] != "pass"
                                ],
                            )
                        )
            issues = evidence_issues + [
                i.model_dump(mode="json") for review in reviews for i in review.issues
            ]
            uncertain_concepts = [
                c
                for c in self.concepts
                if c["metadata_json"].get("canonical_key") in candidate.concept_keys
                and (c["metadata_json"].get("uncertain") or c["metadata_json"].get("conflicts"))
            ]
            if uncertain_concepts:
                issues.append(
                    {
                        "category": "conflicting_evidence",
                        "severity": "warning",
                        "message": "A mapped concept has unresolved uncertainty or conflicts.",
                        "instruction": "Resolve the source conflict before approval.",
                    }
                )
            passed = (
                not evidence_issues
                and not uncertain_concepts
                and all(r.verdict == "pass" for r in reviews)
            )
            rejected = any(r.verdict == "reject" for r in reviews)
            with self.sessions() as session:
                card = session.get(Card, card_id)
                card.verification_status = (
                    "verified" if passed else ("rejected" if rejected else "needs_review")
                )
                card.issues = issues
                session.commit()
            if passed or rejected or attempt == maximum:
                self._finish_candidate(final_key, card_id, revision)
                return
            if any(r.verdict == "uncertain" for r in reviews) and not any(
                r.verdict == "revise" for r in reviews
            ):
                self._finish_candidate(final_key, card_id, revision)
                return
            revised = self._call(
                "revision",
                f"{card_id}:attempt-{attempt + 1}",
                {
                    **self._generation_payload(
                        [
                            c
                            for c in self.concepts
                            if c["metadata_json"].get("canonical_key") in candidate.concept_keys
                        ]
                    ),
                    "card": candidate.model_dump(mode="json"),
                    "feedback": [r.model_dump(mode="json") for r in reviews],
                    "evidence_errors": evidence_issues,
                },
                GeneratedCards,
                images=self.evidence.image_paths(candidate.sources),
            )
            if not revised.cards:
                self._stage("revision", complete=True)
                self._warning(
                    "A candidate could not be revised using available evidence and remains flagged."
                )
                self._finish_candidate(final_key, card_id, revision)
                return
            if len(revised.cards) != 1:
                raise ValueError(
                    "A targeted card revision returned multiple cards; retry with a "
                    "supported model."
                )
            self._stage("revision", complete=True)
            replacement = revised.cards[0]
            replacement.identity_key = candidate.identity_key
            if replacement.model_dump() == candidate.model_dump():
                self._finish_candidate(final_key, card_id, revision)
                return
            candidate = replacement
            origin = "revision"

    def _finish_candidate(self, final_key: str, card_id: str, revision: int) -> None:
        with self.sessions() as session:
            run = session.get(Run, self.run_id)
            run.checkpoints = {
                **run.checkpoints,
                final_key: {"card_id": card_id, "revision": revision},
            }
            session.commit()
