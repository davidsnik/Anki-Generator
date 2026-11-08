"""Validated HTTP/application inputs. Model responses have separate stage contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentCategory = Literal["personal_notes", "lecture", "exercises", "solutions", "reference"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GenerationCriteria(InputModel):
    coverage: Literal["focused", "balanced", "comprehensive"] = "comprehensive"
    theory_emphasis: float = Field(default=1, ge=0, le=3)
    methods_emphasis: float = Field(default=1, ge=0, le=3)
    conceptual_emphasis: float = Field(default=1, ge=0, le=3)
    card_types: list[Literal["basic", "cloze"]] = Field(default_factory=lambda: ["basic", "cloze"])
    answer_detail: Literal["concise", "balanced", "detailed"] = "concise"
    include_explanations: bool = True
    proof_treatment: Literal["exclude", "key_steps", "strategies"] = "key_steps"
    example_treatment: Literal["exclude", "transfer", "include"] = "transfer"
    include_diagrams: bool = True
    topic_exclusions: list[str] = Field(default_factory=list, max_length=1000)
    instructions: str = Field(default="", max_length=20000)

    @field_validator("card_types")
    @classmethod
    def nonempty_types(cls, values: list[str]) -> list[str]:
        if not values or len(values) != len(set(values)):
            raise ValueError("Choose at least one distinct card type")
        return values


class StageModels(InputModel):
    interpretation: str = "gpt-6-astra"
    knowledge: str = "gpt-6-astra"
    generation: str = "gpt-6-astra"
    factual: str = "gpt-6-astra"
    pedagogical: str = "gpt-6-astra"
    coverage: str = "gpt-6-astra"

    @field_validator("*")
    @classmethod
    def reasonable_id(cls, value: str) -> str:
        if not value.strip() or len(value) > 200 or any(char.isspace() for char in value):
            raise ValueError("Invalid model identifier")
        return value


class RoleInfluence(InputModel):
    lecture: float = Field(default=1, ge=0, le=3)
    personal_notes: float = Field(default=0.7, ge=0, le=3)
    exercises: float = Field(default=1.2, ge=0, le=3)
    solutions: float = Field(default=1, ge=0, le=3)
    reference: float = Field(default=0.8, ge=0, le=3)


class CourseInput(InputModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    deck_name: str = Field(default="", max_length=200)
    language: str = Field(default="English", min_length=1, max_length=100)
    archived: bool = False
    criteria: GenerationCriteria = Field(default_factory=GenerationCriteria)


class CoursePatch(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    deck_name: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None
    criteria: GenerationCriteria | None = None


class DocumentPatch(InputModel):
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    category: DocumentCategory | None = None
    authority: Literal["official", "student", "unknown"] | None = None
    linked_document_id: str | None = None
    reprocess: bool = False


class SourceReference(InputModel):
    document_id: str
    document_name: str = ""
    page_number: int = Field(default=1, ge=1)
    region_id: str | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    quote: str = ""
    section: str | None = ""


class CardInput(InputModel):
    concept_id: str | None = None
    card_type: Literal["basic", "cloze"] = "basic"
    kind: str = Field(default="conceptual", max_length=100)
    question: str = Field(min_length=1, max_length=30000)
    answer: str = Field(default="", max_length=30000)
    explanation: str = Field(default="", max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    sources: list[SourceReference] = Field(default_factory=list)
    image_refs: list[SourceReference] = Field(default_factory=list)


class CardPatch(InputModel):
    concept_id: str | None = None
    card_type: Literal["basic", "cloze"] | None = None
    kind: str | None = Field(default=None, max_length=100)
    question: str | None = Field(default=None, min_length=1, max_length=30000)
    answer: str | None = Field(default=None, max_length=30000)
    explanation: str | None = Field(default=None, max_length=50000)
    tags: list[str] | None = Field(default=None, max_length=100)
    sources: list[SourceReference] | None = None
    image_refs: list[SourceReference] | None = None
    archived: bool | None = None
    expected_revision: int | None = None


class ReviewInput(InputModel):
    decision: Literal["approved", "rejected", "pending"]
    reason: str = Field(default="", max_length=10000)


class RunInput(InputModel):
    consent: bool = False
    mode: Literal["generate", "extract", "revise", "topic"] = "generate"
    card_id: str | None = None
    topic_id: str | None = None
    instruction: str = Field(default="", max_length=20000)
    overwrite_manual: bool = False


class ExportInput(InputModel):
    format: Literal["apkg", "json", "csv"] = "apkg"
    card_ids: list[str] | None = None
    deck_name: str | None = Field(default=None, min_length=1, max_length=200)
