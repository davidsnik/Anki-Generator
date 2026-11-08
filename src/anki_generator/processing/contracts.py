"""Structured model outputs. These are claims requiring separate verification."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROMPT_VERSION = "2026-11-08.1"


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceReference(Output):
    document_id: str
    page_number: int = Field(ge=1)
    quote: str
    region_id: str | None = None
    bbox: list[float] | None = None
    section: str | None = None

    @model_validator(mode="after")
    def bounding_box(self) -> EvidenceReference:
        if self.bbox is not None and (
            len(self.bbox) != 4 or self.bbox[2] < self.bbox[0] or self.bbox[3] < self.bbox[1]
        ):
            raise ValueError("Evidence bounding boxes require ordered x0,y0,x1,y1")
        return self


class VisualInterpretation(Output):
    transcription: str
    description: str
    uncertain: bool
    uncertainties: list[str]
    equations: list[str]


class ExerciseAnalysis(Output):
    label: str
    concepts: list[str]
    techniques: list[str]
    prerequisites: list[str]
    reasoning_steps: list[str]
    reusable_strategy: str
    pitfalls: list[str]
    new_application: bool
    sources: list[EvidenceReference]


class CandidateConcept(Output):
    key: str
    title: str
    kind: Literal[
        "topic",
        "definition",
        "theorem",
        "property",
        "method",
        "algorithm",
        "proof",
        "misconception",
        "example",
        "concept",
        "assumption",
    ]
    parent_key: str | None
    statement: str
    assumptions: list[str]
    relationships: list[str]
    importance: float = Field(ge=0, le=1)
    importance_reason: str
    exercise_frequency: int = Field(ge=0)
    sources: list[EvidenceReference]
    uncertain: bool
    conflicts: list[str]


class DocumentKnowledge(Output):
    concepts: list[CandidateConcept]
    exercises: list[ExerciseAnalysis]
    warnings: list[str]
    conflicts: list[str]


class CourseKnowledge(Output):
    concepts: list[CandidateConcept]
    terminology: list[str]
    conflicts: list[str]
    unresolved: list[str]


class SymbolicCheck(Output):
    lhs: str
    rhs: str
    variables: list[str]
    assumptions: list[str]
    purpose: str


class CardCandidate(Output):
    identity_key: str
    concept_keys: list[str]
    card_type: Literal["basic", "cloze"]
    category: Literal[
        "conceptual",
        "definition",
        "theorem",
        "method",
        "assumption",
        "misconception",
        "example",
        "proof",
        "recall",
    ]
    question: str
    answer: str
    explanation: str
    tags: list[str]
    sources: list[EvidenceReference]
    media: list[str]
    mathematical: bool
    symbolic_checks: list[SymbolicCheck]


class GeneratedCards(Output):
    cards: list[CardCandidate]
    omissions: list[str]


class QualityIssue(Output):
    category: str
    severity: Literal["info", "warning", "error"]
    message: str
    instruction: str


class QualityReview(Output):
    verdict: Literal["pass", "revise", "uncertain", "reject"]
    issues: list[QualityIssue]
    reasoning: str
    checked_assumptions: list[str]
    criteria: list[str]


class DuplicateDecision(Output):
    duplicate: bool
    redundant_with: str | None
    reason: str
    useful_distinction: str | None


class CoverageGap(Output):
    concept_key: str
    reason: str
    suggested_targets: list[str]


class CoverageReview(Output):
    gaps: list[CoverageGap]
    overrepresented: list[str]
    neglected_sources: list[str]
    warnings: list[str]
