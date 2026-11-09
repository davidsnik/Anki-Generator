"""A deterministic test provider; deliberately unavailable from production code."""

from collections import Counter
from typing import Any

from anki_generator.llm import ModelResult


class ControlledProvider:
    def __init__(self):
        self.calls = Counter()
        self.payloads: list[tuple[str, dict[str, Any]]] = []
        self.fail_stage = None
        self.fail_once = False
        self.missing_evidence = False
        self.bad_first_card = False
        self.uncertain_visual = False
        self.duplicate = False
        self.extra_card = False
        self.conflicting_concepts = False
        self.on_call = None

    def embed(self, texts, *, model, dimensions):
        """Explicit test-only vectors; this fixture makes no neural quality claim."""
        from anki_generator.llm.embeddings import EmbeddingResult

        self.calls["embeddings"] += 1
        return EmbeddingResult(
            [[1.0] + [0.0] * (dimensions - 1) for _ in texts],
            model,
            {"input_tokens": 30, "output_tokens": 0, "total_tokens": 30},
        )

    def structured(self, stage, payload, schema, *, model, images=None, settings=None):
        from anki_generator.llm import ProviderError

        self.calls[stage] += 1
        self.payloads.append((stage, payload))
        if self.on_call:
            self.on_call(stage, payload)
        if stage == self.fail_stage:
            if self.fail_once:
                self.fail_stage = None
            raise ProviderError(
                "Controlled provider timeout; retry saved work.", kind="network", retryable=True
            )
        if stage == "interpretation":
            data = {
                "transcription": "For a right triangle, a^2 + b^2 = c^2.",
                "description": "A right triangle with legs a,b and hypotenuse c.",
                "uncertain": self.uncertain_visual,
                "uncertainties": ["Unclear label"] if self.uncertain_visual else [],
                "equations": ["a^2+b^2=c^2"],
            }
        elif stage == "knowledge":
            quote = "For a right triangle, a^2 + b^2 = c^2."
            text = payload.get("text", "")
            if quote not in text and not payload.get("visual_interpretations"):
                quote = text.strip().splitlines()[0] if text.strip() else quote
            ref = {
                "document_id": payload["document_id"],
                "page_number": payload["page_number"],
                "quote": quote,
                "region_id": None,
                "bbox": None,
                "section": None,
            }
            concept = {
                "key": "pythagoras",
                "title": "Pythagorean theorem",
                "kind": "theorem",
                "parent_key": None,
                "statement": "For a right triangle, a^2 + b^2 = c^2.",
                "assumptions": ["right triangle"],
                "relationships": [],
                "importance": 0.9,
                "importance_reason": "Lecture and repeated exercises.",
                "exercise_frequency": int(payload["role"] == "exercises"),
                "sources": [ref],
                "uncertain": self.conflicting_concepts,
                "conflicts": ["Official lecture and student note disagree about the sign."]
                if self.conflicting_concepts
                else [],
            }
            exercises = []
            if payload["role"] == "exercises":
                exercises = [
                    {
                        "label": "Triangle exercise",
                        "concepts": ["pythagoras"],
                        "techniques": ["Identify hypotenuse"],
                        "prerequisites": ["Right angles"],
                        "reasoning_steps": ["Locate right angle", "Apply identity"],
                        "reusable_strategy": "Check for a right angle before applying the theorem.",
                        "pitfalls": ["Applying to non-right triangles"],
                        "new_application": False,
                        "sources": [ref],
                    }
                ]
            data = {"concepts": [concept], "exercises": exercises, "warnings": [], "conflicts": []}
        elif stage == "source_audit":
            text = payload.get("text", "")
            quote = "For a right triangle, a^2 + b^2 = c^2."
            if quote not in text and text.strip():
                quote = text.strip().splitlines()[0]
            data = {
                "targets": [
                    {
                        "concept": {
                            "key": "pythagoras",
                            "title": "Pythagorean theorem",
                            "kind": "theorem",
                            "parent_key": None,
                            "statement": "For a right triangle, a^2 + b^2 = c^2.",
                            "assumptions": ["right triangle"],
                            "relationships": [],
                            "importance": 0.9,
                            "importance_reason": "Explicit original source theorem",
                            "exercise_frequency": 0,
                            "sources": [
                                {
                                    "document_id": payload["document_id"],
                                    "page_number": payload["page_number"],
                                    "quote": quote,
                                    "region_id": payload.get("region_id"),
                                    "bbox": payload.get("bbox"),
                                    "section": None,
                                }
                            ],
                            "uncertain": False,
                            "conflicts": [],
                        },
                        "dimension": "theorem",
                        "competency": "State the right-triangle identity",
                        "exercise_pattern": None,
                    }
                ],
                "warnings": [],
                "unresolved": [],
            }
        elif stage == "source_matching":
            target = payload["targets"][0]
            existing = payload["retrieved_concepts"]
            key = target["concept"]["key"]
            found = next(
                (
                    c
                    for c in existing
                    if c["key"] == key
                    or (
                        c.get("statement") == target["concept"]["statement"]
                        and c.get("kind") == target["concept"]["kind"]
                    )
                ),
                None,
            )
            data = {
                "matches": [
                    {
                        "target_key": target["target_key"],
                        "concept_key": found["key"] if found else None,
                        "relation": "same" if found else "new",
                        "reason": "Controlled target comparison",
                    }
                ]
            }
        elif stage == "target_coverage":
            cards = payload["retrieved_cards"]
            data = {
                "assessments": [
                    {
                        "target_id": payload["targets"][0]["id"],
                        "status": "covered" if cards else "uncovered",
                        "card_ids": [c["id"] for c in cards],
                        "missing_aspects": [] if cards else ["No card tests the source target"],
                        "reason": "Controlled independent coverage comparison",
                    }
                ],
                "warnings": [],
            }
        elif stage == "identity":
            data = {
                "relation": "different",
                "existing_id": None,
                "assumptions_preserved": True,
                "reason": "Controlled distinct identity",
            }
        elif stage == "consolidation":
            concepts = [c for analysis in payload["analyses"] for c in analysis.get("concepts", [])]
            concept = dict(concepts[0])
            concept["sources"] = [ref for c in concepts for ref in c["sources"]]
            concept["exercise_frequency"] = sum(c["exercise_frequency"] for c in concepts)
            data = {"concepts": [concept], "terminology": [], "conflicts": [], "unresolved": []}
        elif stage in {"generation", "revision"}:
            concept = payload["concepts"][0]
            sources = concept["sources"]
            if self.missing_evidence:
                sources = [{**sources[0], "quote": "This quotation is fabricated."}]
            answer = "a^2 + b^2 = c^2, where c is the hypotenuse."
            if self.bad_first_card and stage == "generation":
                answer = "a^2 - b^2 = c^2."
            data = {
                "cards": [
                    {
                        "identity_key": "pythagoras:identity",
                        "concept_keys": [concept.get("key", "pythagoras")],
                        "card_type": "basic",
                        "category": "theorem",
                        "question": (
                            "For a right triangle with legs a,b and hypotenuse c, "
                            "state the Pythagorean identity."
                        ),
                        "answer": answer,
                        "explanation": "The right-angle assumption is necessary.",
                        "tags": ["geometry", "theorem"],
                        "sources": sources,
                        "media": [],
                        "mathematical": True,
                        "symbolic_checks": [],
                    }
                ],
                "omissions": [],
            }
        elif stage in {"factual", "pedagogical", "mathematical"}:
            bad = "a^2 - b^2" in payload["card"]["answer"]
            data = {
                "verdict": "revise" if bad else "pass",
                "issues": (
                    [
                        {
                            "category": "mathematics",
                            "severity": "error",
                            "message": "Sign error.",
                            "instruction": "Replace subtraction with addition.",
                        }
                    ]
                    if bad
                    else []
                ),
                "reasoning": "Checked against original statement and right-angle assumption.",
                "checked_assumptions": ["right triangle"],
                "criteria": ["correctness", "standalone"],
            }
        elif stage == "deduplication":
            data = {
                "duplicate": self.duplicate,
                "redundant_with": payload["retrieved_cards"][0]["id"] if self.duplicate else None,
                "reason": "Same target" if self.duplicate else "Distinct target",
                "useful_distinction": None,
            }
        elif stage == "coverage":
            data = {"gaps": [], "overrepresented": [], "neglected_sources": [], "warnings": []}
        else:
            raise AssertionError(f"Unexpected stage {stage}")
        if self.extra_card and stage == "generation":
            extra = {
                **data["cards"][0],
                "identity_key": "pythagoras:paraphrase",
                "question": "What equation relates the side lengths of a right triangle?",
            }
            data["cards"].append(extra)
        return ModelResult(
            schema.model_validate(data),
            {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            model,
            f"test-{stage}",
        )
