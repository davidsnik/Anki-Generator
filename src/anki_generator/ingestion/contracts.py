"""Versioned, local-only document extraction and visual-evidence contracts."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExtractionStatus = Literal["complete", "needs_review", "partial", "failed"]
BoundingBox = tuple[float, float, float, float]


class ExtractionOptions(BaseModel):
    """Practical per-document limits; rendering never allocates a whole tall page."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    worker_timeout_seconds: float = Field(default=120, gt=0, le=3600)
    worker_memory_mb: int = Field(default=1024, ge=128)
    worker_cpu_seconds: int = Field(default=60, ge=1)
    office_rendering: Literal["auto", "native"] = "auto"
    office_timeout_seconds: int = Field(default=45, ge=1, le=120)
    max_file_bytes: int = Field(default=200 * 1024 * 1024, ge=1)
    max_pages: int = Field(default=2000, ge=1, le=10000)
    max_image_pixels: int = Field(default=40_000_000, ge=1)
    render_dpi: int = Field(default=144, ge=72, le=300)
    max_region_dimension: int = Field(default=1600, ge=256, le=4096)
    max_region_pixels: int = Field(default=4_000_000, ge=65536)
    max_total_render_pixels: int = Field(default=256_000_000, ge=65536)
    max_regions: int = Field(default=4096, ge=1)
    overlap_points: float = Field(default=36, ge=0, le=200)
    max_office_expanded_bytes: int = Field(default=256 * 1024 * 1024, ge=1)
    max_office_members: int = Field(default=4096, ge=1)
    max_archive_ratio: int = Field(default=1000, ge=1)
    max_text_characters: int = Field(default=5_000_000, ge=1)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TextBlock(_Contract):
    bbox: BoundingBox
    text: str
    kind: Literal["text", "image", "drawing"] = "text"

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value: BoundingBox) -> BoundingBox:
        if not all(math.isfinite(item) for item in value):
            raise ValueError("Bounding-box coordinates must be finite")
        if value[2] < value[0] or value[3] < value[1]:
            raise ValueError("Bounding-box coordinates must be ordered")
        return value


class SourceRegion(_Contract):
    id: str
    page_number: int = Field(ge=1)
    bbox: BoundingBox
    image_path: str
    pixel_width: int = Field(ge=1)
    pixel_height: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)
    needs_vision: bool = False
    status: ExtractionStatus = "complete"
    is_original_visual: bool = True

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value: BoundingBox) -> BoundingBox:
        return TextBlock.valid_bbox(value)

    @field_validator("image_path")
    @classmethod
    def relative_image_path(cls, value: str) -> str:
        from pathlib import PurePosixPath

        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value or not path.parts:
            raise ValueError("Region image paths must be safe relative POSIX paths")
        return value


class NativeOfficeMath(_Contract):
    source_slide_number: int = Field(ge=1)
    transcription: str = Field(max_length=110_000)
    origin: Literal["native_omml"] = "native_omml"
    verification_status: Literal["unverified"] = "unverified"


class ExtractedPage(_Contract):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)
    text: str = ""
    blocks: list[TextBlock] = Field(default_factory=list)
    regions: list[SourceRegion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    needs_vision: bool = False
    status: ExtractionStatus = "complete"
    coordinate_system: Literal["pdf-points", "image-pixels", "synthetic-preview-pixels"]
    original_rotation: int = 0
    native_office_math: list[NativeOfficeMath] = Field(default_factory=list)

    @model_validator(mode="after")
    def regions_match_page(self) -> ExtractedPage:
        if any(region.page_number != self.page_number for region in self.regions):
            raise ValueError("Region page numbers must match their page")
        return self


class ExtractionMeasurements(_Contract):
    """Numeric observations only; absent fields were not measured.

    Worker CPU/RSS describe the parser process, excluding external conversion
    children. Peak RSS is the worker lifetime high-water mark, never a job total.
    """

    worker_wall_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    worker_cpu_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    worker_peak_rss_bytes: int | None = Field(default=None, ge=0)
    pdf_render_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    pdf_regions_rendered: int | None = Field(default=None, ge=0)


class ExtractionResult(_Contract):
    schema_version: Literal["1"] = "1"
    extractor_version: Literal["1", "2", "3"] = "3"
    rendered_source_path: str | None = None
    rendering_engine: str | None = None
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: str
    pages: list[ExtractedPage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: ExtractionStatus = "complete"
    needs_vision: bool = False
    total_pages: int = Field(default=0, ge=0)
    measurements: ExtractionMeasurements | None = None
    unmapped_office_math: list[NativeOfficeMath] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_page_numbers(self) -> ExtractionResult:
        numbers = [page.page_number for page in self.pages]
        if numbers != sorted(set(numbers)):
            raise ValueError("Page numbers must be ordered and unique")
        return self
