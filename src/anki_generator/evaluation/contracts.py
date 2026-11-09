"""Portable benchmark format and validated local evaluation commands."""

from typing import Any, Literal

from pydantic import Field, model_validator

from anki_generator.domain import InputModel

JudgmentLabel = Literal[
    "correct_useful",
    "needs_improvement",
    "incorrect",
    "ambiguous",
    "redundant",
    "not_worth_memorizing",
]
Provenance = Literal["synthetic", "unreviewed", "human_reference"]


class ReferenceConcept(InputModel):
    id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=2000)
    topic: str = Field(default="", max_length=1000)
    kind: str = Field(default="concept", max_length=100)
    importance: float = Field(default=1, ge=0, le=3)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    competencies: list[str] = Field(default_factory=list, max_length=100)
    source: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=10000)


class ReferenceCard(InputModel):
    id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=30000)
    answer: str = Field(default="", max_length=30000)
    concept_ids: list[str] = Field(default_factory=list, max_length=100)
    expected_label: JudgmentLabel = "correct_useful"
    label_origin: Literal["synthetic", "human", "model"] = "synthetic"
    dimensions: dict[str, bool | None] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=10000)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    reviewer: str = Field(default="", max_length=200)
    independent: bool = False


class DatasetInput(InputModel):
    schema_version: Literal["1"] = "1"
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    course_id: str | None = None
    provenance: Provenance = "unreviewed"
    reference_concepts: list[ReferenceConcept] = Field(default_factory=list, max_length=10000)
    reference_cards: list[ReferenceCard] = Field(default_factory=list, max_length=10000)
    annotations: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    reviewer: str = Field(default="", max_length=200)
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def consistent_references(self):
        keys = [concept.id for concept in self.reference_concepts]
        if len(set(keys)) != len(keys):
            raise ValueError("Reference concept IDs must be unique")
        card_keys = [card.id for card in self.reference_cards]
        if len(set(card_keys)) != len(card_keys):
            raise ValueError("Reference card IDs must be unique")
        if any(set(card.concept_ids) - set(keys) for card in self.reference_cards):
            raise ValueError("Reference cards must map to existing reference concepts")
        if self.provenance == "human_reference" and not self.reviewer.strip():
            raise ValueError("Identify the reviewer declaring these human reference labels")
        return self


class ExperimentVariant(InputModel):
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


class ExperimentInput(InputModel):
    name: str = Field(min_length=1, max_length=200)
    course_id: str | None = None
    variants: list[ExperimentVariant] = Field(min_length=1, max_length=8)
    consent: bool = False
    blind: bool = True

    @model_validator(mode="after")
    def unique_names(self):
        if len({variant.name for variant in self.variants}) != len(self.variants):
            raise ValueError("Experiment variant names must be unique")
        return self


class QualityDimensions(InputModel):
    factual_correct: bool | None = None
    mathematical_correct: bool | None = None
    assumptions_complete: bool | None = None
    atomic: bool | None = None
    source_correct: bool | None = None
    useful: bool | None = None
    unambiguous: bool | None = None


class JudgmentInput(InputModel):
    case_id: str
    label: JudgmentLabel
    origin: Literal["human", "synthetic", "model"] = "human"
    reviewer: str = Field(default="Local reviewer", min_length=1, max_length=200)
    independent: bool = False
    dimensions: QualityDimensions = Field(default_factory=QualityDimensions)
    reference_concept_ids: list[str] = Field(default_factory=list, max_length=1000)
    rationale: str = Field(default="", max_length=20000)


class AnnotationInput(InputModel):
    kind: Literal["missing_concept", "interpretation_error"]
    label: str = Field(min_length=1, max_length=2000)
    source: dict[str, Any] = Field(default_factory=dict)
    expected: str = Field(default="", max_length=30000)
    actual: str = Field(default="", max_length=30000)
    rationale: str = Field(default="", max_length=10000)
    origin: Literal["human", "synthetic", "model"] = "human"
