"""Versioned developer dataset/configuration contracts, separate from generation inputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anki_generator.ingestion.contracts import ExtractionOptions
from anki_generator.processing.state import digest
from anki_generator.services.settings import ApplicationSettings
from anki_generator.services.storage import safe_relative


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetSource(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    relative_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    source_type: str
    supported: bool
    course_id: str
    course_name: str
    role_candidates: list[str] = Field(default_factory=list)
    classification_basis: str = "filename hints only; unconfirmed"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def safe_path(self):
        safe_relative(self.relative_path)
        return self


class DatasetManifest(Contract):
    schema_version: Literal["1"] = "1"
    dataset_id: str
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: str
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_bytes: int = Field(ge=0)
    source_root: str | None = None
    sources: list[DatasetSource]
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_sources(self):
        ids = [source.id for source in self.sources]
        paths = [source.relative_path for source in self.sources]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("Dataset source identities and paths must be unique")
        signature = digest(
            [
                source.model_dump(exclude={"metadata"})
                for source in sorted(self.sources, key=lambda item: item.relative_path)
            ]
        )
        if signature != self.dataset_sha256:
            raise ValueError("Dataset hash does not match its frozen source manifest")
        return self


class Sample(Contract):
    source_id: str
    page_numbers: list[int] | None = None
    split: Literal["development", "held_out"] = "development"
    stratum: str = "ordinary"
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_pages(self):
        if self.page_numbers is not None and (
            not self.page_numbers
            or self.page_numbers != sorted(set(self.page_numbers))
            or min(self.page_numbers) < 1
        ):
            raise ValueError("Page selections must be ordered, unique positive integers")
        return self


class Workload(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str
    samples: list[Sample] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sources(self):
        ids = [sample.source_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("Select a source once per workload, with all required pages")
        return self


class BenchmarkConfig(Contract):
    schema_version: Literal["1"] = "1"
    name: str = Field(min_length=1, max_length=200)
    workloads: list[Workload] = Field(min_length=1)
    extraction: ExtractionOptions = Field(default_factory=ExtractionOptions)
    pipeline: ApplicationSettings = Field(default_factory=ApplicationSettings)
    execution: Literal["local_extract", "local_pipeline", "live_pipeline"] = "local_extract"
    repetitions: int = Field(default=1, ge=1, le=5)
    max_api_requests: int = Field(default=100, ge=1, le=10000)
    max_elapsed_seconds: int = Field(default=3600, ge=1, le=86400)
    notes: str = ""

    @model_validator(mode="after")
    def unique_workloads(self):
        if self.execution == "local_extract" and self.repetitions != 1:
            raise ValueError("Use local_pipeline for repeated cold/warm extraction measurements")
        ids = [workload.id for workload in self.workloads]
        if len(ids) != len(set(ids)):
            raise ValueError("Workload IDs must be unique")
        return self
