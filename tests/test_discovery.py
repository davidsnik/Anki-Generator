"""Local document discovery and filesystem boundary behavior."""

import hashlib
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

from anki_generator.config import DiscoverySettings
from anki_generator.ingestion import discovery
from anki_generator.ingestion.discovery import DiscoveryError, discover_documents


def write_file(root: Path, relative_path: str, content: bytes = b"course material") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_discovers_supported_files_with_sorted_relative_paths_and_metadata(
    tmp_path: Path,
) -> None:
    expected = {
        "z-slides.PDF": b"%PDF-1.7\x00\xff",
        "Week 1/概率.tex": b"\\section{Probability}\n",
        "a-notes.md": b"# Notes\n",
        "figures/diagram.PNG": bytes(range(256)),
    }
    for relative_path, content in expected.items():
        write_file(tmp_path, relative_path, content)
    write_file(tmp_path, "ignored.zip")

    manifest = discover_documents(tmp_path)

    assert [record.relative_path for record in manifest.documents] == sorted(expected)
    assert manifest.skipped_unsupported == 1
    assert manifest.skipped_symlinks == 0
    for record in manifest.documents:
        content = expected[record.relative_path]
        assert record.file_type == Path(record.relative_path).suffix[1:].lower()
        assert record.size_bytes == len(content)
        assert record.sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize(
    "extension",
    ["pdf", "tex", "md", "txt", "png", "jpg", "jpeg", "tif", "tiff", "webp", "pptx", "docx"],
)
def test_default_supported_extensions_are_discovered(tmp_path: Path, extension: str) -> None:
    write_file(tmp_path, f"material.{extension}")

    manifest = discover_documents(tmp_path)

    assert [record.file_type for record in manifest.documents] == [extension]


def test_unchanged_tree_produces_identical_manifest_json(tmp_path: Path) -> None:
    write_file(tmp_path, "b.txt", b"b")
    write_file(tmp_path, "nested/a.pdf", b"a")

    first = discover_documents(tmp_path)
    second = discover_documents(tmp_path)

    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.parametrize("content", [b"", b"chunk" * 250_001])
def test_hashes_empty_and_multichunk_files(tmp_path: Path, content: bytes) -> None:
    write_file(tmp_path, "lecture.pdf", content)

    record = discover_documents(tmp_path).documents[0]

    assert record.size_bytes == len(content)
    assert record.sha256 == hashlib.sha256(content).hexdigest()


def test_empty_directory_produces_valid_empty_manifest(tmp_path: Path) -> None:
    manifest = discover_documents(tmp_path)

    assert manifest.documents == ()
    assert manifest.skipped_unsupported == 0
    assert manifest.skipped_symlinks == 0
    assert manifest.excluded_directories == ()


def test_unsupported_regular_files_are_counted(tmp_path: Path) -> None:
    write_file(tmp_path, "archive.zip")
    write_file(tmp_path, "nested/README")
    write_file(tmp_path, "config.json")

    manifest = discover_documents(tmp_path)

    assert manifest.documents == ()
    assert manifest.skipped_unsupported == 3


@pytest.mark.parametrize("input_kind", ["missing", "file"])
def test_invalid_input_directory_fails(tmp_path: Path, input_kind: str) -> None:
    course = tmp_path / "course"
    if input_kind == "file":
        course.write_text("not a directory")

    with pytest.raises(DiscoveryError):
        discover_documents(course)


def test_all_nested_symlinks_are_skipped(tmp_path: Path) -> None:
    course = tmp_path / "course"
    course.mkdir()
    internal_file = write_file(course, "original.txt", b"internal")
    internal_directory = course / "notes"
    internal_directory.mkdir()
    write_file(internal_directory, "lecture.pdf")
    external_file = write_file(tmp_path, "private.pdf", b"outside")
    external_directory = tmp_path / "outside"
    external_directory.mkdir()
    write_file(external_directory, "private.txt")
    (course / "internal-link.txt").symlink_to(internal_file)
    (course / "external-link.pdf").symlink_to(external_file)
    (course / "internal-directory").symlink_to(internal_directory, target_is_directory=True)
    (course / "external-directory").symlink_to(external_directory, target_is_directory=True)
    (course / "broken.pdf").symlink_to(tmp_path / "missing.pdf")

    manifest = discover_documents(course)

    assert [record.relative_path for record in manifest.documents] == [
        "notes/lecture.pdf",
        "original.txt",
    ]
    assert manifest.skipped_symlinks == 5
    assert manifest.skipped_unsupported == 0


def test_explicitly_supplied_symlink_root_is_resolved(tmp_path: Path) -> None:
    course = tmp_path / "course"
    course.mkdir()
    write_file(course, "lecture.pdf")
    alias = tmp_path / "course-alias"
    alias.symlink_to(course, target_is_directory=True)

    manifest = discover_documents(alias)

    assert [record.relative_path for record in manifest.documents] == ["lecture.pdf"]


def test_symlink_loop_as_input_fails_gracefully(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to(loop)

    with pytest.raises(DiscoveryError):
        discover_documents(loop)


def test_nested_output_directory_is_excluded(tmp_path: Path) -> None:
    write_file(tmp_path, "lecture.pdf")
    write_file(tmp_path, "generated/custom/previous-deck.txt")
    output = tmp_path / "generated/custom"

    manifest = discover_documents(tmp_path, output_directory=output)

    assert [record.relative_path for record in manifest.documents] == ["lecture.pdf"]
    assert manifest.excluded_directories == ("generated/custom",)
    assert manifest.skipped_unsupported == 0


def test_external_output_path_does_not_change_discovery(tmp_path: Path) -> None:
    course = tmp_path / "course"
    course.mkdir()
    write_file(course, "lecture.pdf")

    manifest = discover_documents(course, output_directory=tmp_path / "elsewhere")

    assert [record.relative_path for record in manifest.documents] == ["lecture.pdf"]
    assert manifest.excluded_directories == ()


@pytest.mark.parametrize(
    "excluded_name", [".git", ".venv", "__pycache__", "output", "outputs", "runs"]
)
def test_default_generated_and_tool_directories_are_excluded(
    tmp_path: Path, excluded_name: str
) -> None:
    write_file(tmp_path, "lecture.pdf")
    write_file(tmp_path, f"{excluded_name}/old-result.txt")

    manifest = discover_documents(tmp_path)

    assert [record.relative_path for record in manifest.documents] == ["lecture.pdf"]
    assert manifest.excluded_directories == (excluded_name,)


def test_marked_prior_output_is_excluded_at_any_depth(tmp_path: Path) -> None:
    write_file(tmp_path, "lecture.pdf")
    write_file(tmp_path, "previous/session/.anki-generator-output", b"")
    write_file(tmp_path, "previous/session/old-result.pdf")

    manifest = discover_documents(tmp_path)

    assert [record.relative_path for record in manifest.documents] == ["lecture.pdf"]
    assert manifest.excluded_directories == ("previous/session",)


def test_excluded_directory_paths_are_sorted(tmp_path: Path) -> None:
    write_file(tmp_path, "z/output/old.pdf")
    write_file(tmp_path, "a/runs/old.pdf")

    manifest = discover_documents(tmp_path)

    assert manifest.excluded_directories == ("a/runs", "z/output")


def test_custom_settings_control_extensions_and_exclusions(tmp_path: Path) -> None:
    write_file(tmp_path, "keep.csv")
    write_file(tmp_path, "lecture.pdf")
    write_file(tmp_path, "private/hidden.csv")
    settings = DiscoverySettings(
        supported_extensions=(".csv",), excluded_directory_names=("private",)
    )

    manifest = discover_documents(tmp_path, settings=settings)

    assert [record.relative_path for record in manifest.documents] == ["keep.csv"]
    assert manifest.skipped_unsupported == 1
    assert manifest.excluded_directories == ("private",)


def test_directory_read_error_fails_instead_of_returning_partial_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_file(tmp_path, "lecture.pdf")
    inaccessible = tmp_path / "restricted"
    inaccessible.mkdir()
    original_scandir = os.scandir

    def deny_restricted_directory(
        path: Path,
    ) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        if Path(path) == inaccessible:
            raise PermissionError("directory access denied")
        return original_scandir(path)

    monkeypatch.setattr(discovery.os, "scandir", deny_restricted_directory)

    with pytest.raises(DiscoveryError, match="directory access denied"):
        discover_documents(tmp_path)


def test_file_read_error_fails_instead_of_returning_partial_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unreadable = write_file(tmp_path, "restricted.pdf")
    original_open = os.open

    def deny_restricted_file(path: Path, flags: int, mode: int = 0o777) -> int:
        if Path(path) == unreadable:
            raise PermissionError("file access denied")
        return original_open(path, flags, mode)

    monkeypatch.setattr(discovery.os, "open", deny_restricted_file)

    with pytest.raises(DiscoveryError, match="file access denied"):
        discover_documents(tmp_path)


def test_file_changed_during_hashing_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_file(tmp_path, "changing.txt", b"original")
    original_fstat = os.fstat
    has_changed = False

    def change_after_first_stat(descriptor: int) -> os.stat_result:
        nonlocal has_changed
        result = original_fstat(descriptor)
        if not has_changed:
            has_changed = True
            source.write_bytes(b"new contents with a different length")
        return result

    monkeypatch.setattr(discovery.os, "fstat", change_after_first_stat)

    with pytest.raises(DiscoveryError, match="changed while hashing"):
        discover_documents(tmp_path)
