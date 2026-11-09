"""Application-wide scheduler and request budgets, distinct from stage workers."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class TaskOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    max_concurrent_jobs: int = Field(default=2, ge=1, le=8)
    api_concurrency: int = Field(default=4, ge=1, le=16)
    per_model_concurrency: dict[str, StrictInt] = Field(default_factory=dict, max_length=100)
    local_concurrency: int = Field(default=2, ge=1, le=4)
    per_job_api_concurrency: int = Field(default=2, ge=1, le=16)

    @field_validator("per_model_concurrency")
    @classmethod
    def bounded_models(cls, value: dict[str, int]) -> dict[str, int]:
        if any(
            not model.strip()
            or len(model) > 200
            or any(character.isspace() for character in model)
            or not 1 <= limit <= 16
            for model, limit in value.items()
        ):
            raise ValueError("Per-model limits require model identifiers and limits from 1 to 16")
        return value
