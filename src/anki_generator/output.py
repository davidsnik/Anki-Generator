"""Publish complete manifests atomically, preserving existing results by default."""

import os
import tempfile
from pathlib import Path

from anki_generator.ingestion.discovery import OUTPUT_MARKER
from anki_generator.models import DiscoveryManifest

MANIFEST_FILENAME = "manifest.json"


def validate_output_directory(
    course_directory: Path, output_directory: Path, *, overwrite: bool = False
) -> Path:
    """Validate before discovery so an invalid output never causes a long scan."""
    if output_directory.is_symlink():
        raise ValueError("Output directory must not be a symlink")
    try:
        output = output_directory.resolve()
        course = course_directory.resolve(strict=True)
    except RuntimeError as exc:
        raise ValueError(f"Cannot resolve source/output path: {exc}") from exc
    if course.is_relative_to(output):
        raise ValueError("Output directory must not equal or contain the course directory")
    if output.exists() and not output.is_dir():
        raise ValueError("Output path is not a directory")
    _check_destination(output, overwrite=overwrite)
    return output


def _check_destination(output: Path, *, overwrite: bool) -> None:
    destination = output / MANIFEST_FILENAME
    if destination.is_symlink():
        raise ValueError("Manifest path must not be a symlink")
    if destination.exists():
        if not destination.is_file():
            raise ValueError("Manifest path is not a regular file")
        if not overwrite:
            raise FileExistsError(f"{destination} already exists; use --overwrite to replace it")
    marker = output / OUTPUT_MARKER
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise ValueError("Output marker must be a regular file")


def write_manifest(
    manifest: DiscoveryManifest, output_directory: Path, *, overwrite: bool = False
) -> Path:
    """Use a sibling temporary file, then link exclusively or explicitly replace.

    The marker lets later runs recognize generated directories at arbitrary names.
    A failed publication may leave an empty marked directory, but no partial manifest.
    """
    payload = manifest.model_dump_json(indent=2) + "\n"
    if output_directory.is_symlink():
        raise ValueError("Output directory must not be a symlink")
    _check_destination(output_directory, overwrite=overwrite)
    output_directory.mkdir(parents=True, exist_ok=True)
    marker = output_directory / OUTPUT_MARKER
    try:
        with marker.open("x", encoding="utf-8") as stream:
            stream.write("anki-generator output directory\n")
    except FileExistsError:
        _check_destination(output_directory, overwrite=overwrite)
    destination = output_directory / MANIFEST_FILENAME
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_directory, prefix=".manifest-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, destination)
        else:
            # Hard-link creation is atomic and refuses an existing destination.
            os.link(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
