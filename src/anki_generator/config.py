"""Validate only configuration used by current deterministic discovery."""

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


class DiscoverySettings(BaseModel):
    """Filename recognition is independent of future parser support."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    supported_extensions: tuple[str, ...] = (
        ".pdf",
        ".tex",
        ".md",
        ".txt",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".webp",
        ".pptx",
        ".docx",
    )
    excluded_directory_names: tuple[str, ...] = (
        ".git",
        ".venv",
        "__pycache__",
        "output",
        "outputs",
        "runs",
    )

    @field_validator("supported_extensions")
    @classmethod
    def valid_extensions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or any(re.fullmatch(r"\.[a-z0-9]+", item) is None for item in values):
            raise ValueError("supported_extensions must contain lowercase suffixes such as '.pdf'")
        if len(values) != len(set(values)):
            raise ValueError("supported_extensions must be unique")
        return values

    @field_validator("excluded_directory_names")
    @classmethod
    def valid_directory_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not name or name in {".", ".."} or "/" in name or "\\" in name for name in values):
            raise ValueError("excluded_directory_names must be simple directory names")
        if len(values) != len(set(values)):
            raise ValueError("excluded_directory_names must be unique")
        return values


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    discovery: DiscoverySettings = DiscoverySettings()


def load_settings(path: Path | None = None) -> Settings:
    """Read an explicitly selected TOML file; defaults work outside the repo."""
    if path is None:
        return Settings()
    with path.open("rb") as stream:
        return Settings.model_validate(tomllib.load(stream))
