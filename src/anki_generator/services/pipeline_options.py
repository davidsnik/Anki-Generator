"""Validated execution budgets and reproducible per-run experiment overrides."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from anki_generator.domain import validate_model_identifier


class ProcessingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    concurrency: int = Field(default=2, ge=1, le=8)
    api_concurrency: int = Field(default=2, ge=1, le=8)
    input_token_budget: int = Field(default=24000, ge=4000, le=128000)
    output_token_budget: int = Field(default=12000, ge=1000, le=64000)
    coverage_rounds: int = Field(default=1, ge=0, le=3)
    coverage_batch_size: int = Field(default=8, ge=1, le=24)
    source_chunk_characters: int = Field(default=10000, ge=1000, le=24000)
    vision_batch_images: int = Field(default=4, ge=1, le=12)
    semantic_candidates: int = Field(default=12, ge=2, le=50)
    embedding_model: str = Field(default="text-embedding-3-small", min_length=1, max_length=200)
    embedding_dimensions: int = Field(default=512, ge=64, le=3072)
    embedding_batch_size: int = Field(default=32, ge=1, le=128)
    identity_similarity: float = Field(default=0.92, ge=0.8, le=1)
    identity_margin: float = Field(default=0.07, ge=0, le=0.3)
    source_audit: bool = True

    @field_validator("embedding_model")
    @classmethod
    def valid_embedding_model(cls, value: str) -> str:
        return validate_model_identifier(value)

    @model_validator(mode="after")
    def supported_dimensions(self):
        if self.embedding_model == "text-embedding-3-small" and self.embedding_dimensions > 1536:
            raise ValueError("text-embedding-3-small supports at most 1536 dimensions")
        return self


PROMPT_STAGES = frozenset(
    {
        "interpretation",
        "knowledge",
        "consolidation",
        "generation",
        "factual",
        "pedagogical",
        "mathematical",
        "revision",
        "deduplication",
        "coverage",
        "source_audit",
        "source_matching",
        "target_coverage",
        "identity",
    }
)


def validate_prompt_overrides(value: dict[str, str]) -> dict[str, str]:
    if set(value) - PROMPT_STAGES:
        raise ValueError("Prompt override contains an unsupported processing stage")
    for body in value.values():
        if not body.strip() or len(body) > 50000:
            raise ValueError("Prompt overrides must contain 1–50000 characters")
    return value
