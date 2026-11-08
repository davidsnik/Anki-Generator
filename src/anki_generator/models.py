"""Versioned contracts for discovery, without claims about extracted content."""

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


def validate_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value == "."
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or PureWindowsPath(value).drive
        or path.as_posix() != value
    ):
        raise ValueError("expected a normalized relative POSIX path without traversal")
    return value


class DocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    file_type: str = Field(pattern=r"^[a-z0-9]+$")
    size_bytes: NonNegativeInt
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return validate_relative_path(value)

    @model_validator(mode="after")
    def suffix_matches_type(self) -> Self:
        if PurePosixPath(self.relative_path).suffix.lower() != f".{self.file_type}":
            raise ValueError("file_type must match the filename suffix")
        return self


class DiscoveryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    hash_algorithm: Literal["sha256"] = "sha256"
    documents: tuple[DocumentRecord, ...] = ()
    skipped_unsupported: NonNegativeInt = 0
    skipped_symlinks: NonNegativeInt = 0
    excluded_directories: tuple[str, ...] = ()

    @field_validator("excluded_directories")
    @classmethod
    def valid_exclusions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_relative_path(value)
        if list(values) != sorted(set(values)):
            raise ValueError("excluded_directories must be sorted and unique")
        return values

    @model_validator(mode="after")
    def ordered_unique_documents(self) -> Self:
        paths = [document.relative_path for document in self.documents]
        if paths != sorted(set(paths)):
            raise ValueError("documents must have sorted, unique relative paths")
        return self
