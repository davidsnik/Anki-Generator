"""Manifest publication must preserve results and never expose partial JSON."""

import os
from pathlib import Path

import pytest

from anki_generator.models import DiscoveryManifest
from anki_generator.output import validate_output_directory, write_manifest


@pytest.mark.parametrize("relationship", ["same", "ancestor"])
def test_output_cannot_equal_or_contain_source(tmp_path: Path, relationship: str) -> None:
    course = tmp_path / "course"
    course.mkdir()
    output = course if relationship == "same" else tmp_path
    with pytest.raises(ValueError, match="equal or contain"):
        validate_output_directory(course, output)


@pytest.mark.parametrize("kind", ["file", "symlink", "broken_symlink"])
def test_invalid_output_kind_is_rejected(tmp_path: Path, kind: str) -> None:
    course = tmp_path / "course"
    course.mkdir()
    output = tmp_path / "result"
    if kind == "file":
        output.write_bytes(b"existing")
    else:
        output.symlink_to(tmp_path / ("course" if kind == "symlink" else "missing"))
    with pytest.raises(ValueError):
        validate_output_directory(course, output)


def test_serializes_versioned_valid_json_and_marks_output(tmp_path: Path) -> None:
    output = tmp_path / "new/nested"
    manifest = DiscoveryManifest()
    result = write_manifest(manifest, output)
    assert result == output / "manifest.json"
    assert DiscoveryManifest.model_validate_json(result.read_bytes()) == manifest
    assert (output / ".anki-generator-output").is_file()
    assert not list(output.glob(".manifest-*"))


def test_existing_result_requires_explicit_overwrite(tmp_path: Path) -> None:
    result = write_manifest(DiscoveryManifest(), tmp_path)
    original = result.read_bytes()
    changed = DiscoveryManifest(skipped_unsupported=1)
    with pytest.raises(FileExistsError, match="overwrite"):
        write_manifest(changed, tmp_path)
    assert result.read_bytes() == original
    write_manifest(changed, tmp_path, overwrite=True)
    assert DiscoveryManifest.model_validate_json(result.read_bytes()) == changed


@pytest.mark.parametrize("name", ["manifest.json", ".anki-generator-output"])
def test_output_does_not_follow_symlink_files(tmp_path: Path, name: str) -> None:
    external = tmp_path / "private.txt"
    external.write_bytes(b"private")
    output = tmp_path / "output"
    output.mkdir()
    (output / name).symlink_to(external)
    with pytest.raises(ValueError, match="symlink|regular file"):
        write_manifest(DiscoveryManifest(), output, overwrite=True)
    assert external.read_bytes() == b"private"


def test_publication_race_does_not_clobber_new_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = os.link
    destination = tmp_path / "manifest.json"

    def competing_write(source: Path, target: Path) -> None:
        destination.write_bytes(b"a different process published first")
        link(source, target)

    monkeypatch.setattr(os, "link", competing_write)
    with pytest.raises(FileExistsError):
        write_manifest(DiscoveryManifest(), tmp_path)
    assert destination.read_bytes() == b"a different process published first"
    assert not list(tmp_path.glob(".manifest-*"))


def test_failed_overwrite_preserves_previous_result_and_cleans_tempfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = write_manifest(DiscoveryManifest(), tmp_path)
    previous = destination.read_bytes()

    def fail_replace(source: Path, target: Path) -> None:
        raise PermissionError("simulated write failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        write_manifest(DiscoveryManifest(skipped_symlinks=1), tmp_path, overwrite=True)
    assert destination.read_bytes() == previous
    assert not list(tmp_path.glob(".manifest-*"))
