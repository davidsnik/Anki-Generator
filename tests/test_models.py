"""Validation tests for the published discovery manifest contract."""

import hashlib

import pytest
from pydantic import ValidationError

from anki_generator.models import DiscoveryManifest, DocumentRecord


def document(relative_path: str = "lecture.pdf", **changes: object) -> DocumentRecord:
    values: dict[str, object] = {
        "relative_path": relative_path,
        "file_type": "pdf",
        "size_bytes": 7,
        "sha256": hashlib.sha256(b"lecture").hexdigest(),
    }
    values.update(changes)
    return DocumentRecord.model_validate(values)


def test_manifest_json_round_trip_preserves_version_and_records() -> None:
    manifest = DiscoveryManifest(documents=(document(),))

    restored = DiscoveryManifest.model_validate_json(manifest.model_dump_json())

    assert restored == manifest
    assert restored.schema_version == "1"
    assert restored.hash_algorithm == "sha256"
    assert restored.documents[0].relative_path == "lecture.pdf"


@pytest.mark.parametrize(
    "relative_path",
    [
        "",
        "/lecture.pdf",
        "../lecture.pdf",
        "notes/../lecture.pdf",
        "./lecture.pdf",
        "notes//lecture.pdf",
        "notes\\lecture.pdf",
        "C:/lecture.pdf",
    ],
)
def test_document_rejects_unsafe_or_noncanonical_paths(relative_path: str) -> None:
    with pytest.raises(ValidationError):
        document(relative_path)


def test_document_accepts_nested_unicode_and_space_in_path() -> None:
    record = document("Week 1/概率 lecture.pdf")

    assert record.relative_path == "Week 1/概率 lecture.pdf"


@pytest.mark.parametrize("sha256", ["", "0" * 63, "0" * 65, "G" * 64, "A" * 64])
def test_document_rejects_invalid_sha256(sha256: str) -> None:
    with pytest.raises(ValidationError):
        document(sha256=sha256)


def test_document_rejects_negative_size() -> None:
    with pytest.raises(ValidationError):
        document(size_bytes=-1)


def test_document_rejects_boolean_size() -> None:
    with pytest.raises(ValidationError):
        document(size_bytes=True)


@pytest.mark.parametrize("file_type", ["", ".pdf", "PDF", "pd/f"])
def test_document_rejects_invalid_file_type(file_type: str) -> None:
    with pytest.raises(ValidationError):
        document(file_type=file_type)


def test_document_rejects_type_that_disagrees_with_path_suffix() -> None:
    with pytest.raises(ValidationError):
        document(file_type="txt")


@pytest.mark.parametrize(
    "documents",
    [(document("b.pdf"), document("a.pdf")), (document(), document())],
)
def test_manifest_rejects_unsorted_or_duplicate_document_paths(
    documents: tuple[DocumentRecord, ...],
) -> None:
    with pytest.raises(ValidationError):
        DiscoveryManifest(documents=documents)


@pytest.mark.parametrize("field", ["skipped_unsupported", "skipped_symlinks"])
def test_manifest_rejects_negative_counts(field: str) -> None:
    with pytest.raises(ValidationError):
        DiscoveryManifest.model_validate({"documents": [], field: -1})


@pytest.mark.parametrize("changes", [{"schema_version": "2"}, {"hash_algorithm": "md5"}])
def test_manifest_rejects_unknown_format_or_hash_algorithm(
    changes: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        DiscoveryManifest.model_validate({"documents": [], **changes})


@pytest.mark.parametrize(
    "paths",
    [("z", "a"), ("a", "a"), ("../outside",), ("/absolute",)],
)
def test_manifest_rejects_invalid_excluded_directories(paths: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        DiscoveryManifest(documents=(), excluded_directories=paths)


def test_manifest_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DiscoveryManifest.model_validate({"documents": [], "parsed": True})
