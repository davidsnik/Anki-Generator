"""Frozen source identities never become unchecked filesystem destinations."""

import copy
import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from anki_generator.benchmark.annotations import (
    AnnotationBundle,
    append_annotations,
    load_annotations,
    reference_inventory_hash,
    validate_bundle,
)
from anki_generator.benchmark.contracts import DatasetSource
from anki_generator.benchmark.review import export_review_package
from anki_generator.benchmark.runner import implementation_metadata, wait_for_worker
from anki_generator.benchmark.worker import (
    _source_destination,
    distinct_output_cases,
    portable_card_case,
)


def source_values(identifier: str) -> dict:
    return {
        "id": identifier,
        "relative_path": "Synthetic/courses/Algebra/lecture.txt",
        "sha256": "a" * 64,
        "size_bytes": 3,
        "source_type": "txt",
        "supported": True,
        "course_id": "algebra",
        "course_name": "Algebra",
    }


@pytest.mark.parametrize("identifier", ["../../outside", "/tmp/outside", ".", "", "f" * 25])
def test_source_manifest_rejects_path_shaped_or_invalid_identities(identifier):
    with pytest.raises(ValidationError):
        DatasetSource.model_validate(source_values(identifier))


@pytest.mark.parametrize("identifier", ["../../outside", "/tmp/outside", "a/b", "", "f" * 25])
def test_direct_worker_request_cannot_escape_private_output(tmp_path, identifier):
    output = tmp_path / "experiment"
    output.mkdir()
    with pytest.raises(ValueError, match="Source identity"):
        _source_destination(output, identifier)
    assert list(output.iterdir()) == []
    assert not (tmp_path / "outside").exists()


def test_worker_rejects_existing_symlink_and_preserves_its_target(tmp_path):
    output = tmp_path / "experiment"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("unchanged")
    (output / ("a" * 24)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        _source_destination(output, "a" * 24)
    assert sentinel.read_text() == "unchanged"
    assert list(outside.iterdir()) == [sentinel]


def test_valid_generated_source_id_creates_new_private_output_and_never_overwrites(tmp_path):
    source = DatasetSource.model_validate(source_values("a" * 24))
    output = tmp_path / "experiment"
    output.mkdir()
    destination = _source_destination(output, source.id)
    assert destination == output / source.id
    assert destination.stat().st_mode & 0o777 == 0o700
    sentinel = destination / "previous.json"
    sentinel.write_text("preserve")
    with pytest.raises(FileExistsError):
        _source_destination(output, source.id)
    assert sentinel.read_text() == "preserve"


def test_environment_metadata_records_reproduction_fields_without_host_or_environment(tmp_path):
    package = tmp_path / "src" / "anki_generator"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# synthetic implementation")
    (tmp_path / "uv.lock").write_text("synthetic lock")
    environment = implementation_metadata(tmp_path)["environment"]
    assert environment["platform"] and environment["machine"]
    assert environment["logical_cpu_count"] is None or environment["logical_cpu_count"] > 0
    assert set(environment["dependency_versions"]) == {
        "PyMuPDF",
        "pydantic",
        "SQLAlchemy",
        "openai",
        "numpy",
    }
    assert (
        environment["lockfile_sha256"]["uv.lock"] == hashlib.sha256(b"synthetic lock").hexdigest()
    )
    assert set(environment) == {
        "platform",
        "machine",
        "logical_cpu_count",
        "dependency_versions",
        "lockfile_sha256",
    }


def test_card_pairing_respects_portable_concept_scope_and_not_database_ids():
    source = {"id": "a" * 24, "sha256": "b" * 64}

    def exported(production_concept, portable_concept, production_document):
        return portable_card_case(
            {
                "id": f"card-{production_concept}",
                "concept_id": production_concept,
                "question": "State the definition.",
                "answer": "Definition.",
                "sources": [{"document_id": production_document, "page_number": 1}],
            },
            {production_document: source},
            identity="definition",
            concept_targets={production_concept: portable_concept},
        )

    first = exported("database-concept-1", "portable-concept-a", "document-1")
    repeated = exported("fresh-database-concept", "portable-concept-a", "new-document")
    different = exported("database-concept-2", "portable-concept-b", "document-1")
    assert first["id"] == repeated["id"]
    assert first["id"] != different["id"]
    assert first["production_id"] != repeated["production_id"]
    assert first["concept_target_id"] == "portable-concept-a"


def test_ambiguous_output_targets_remain_distinct_but_cannot_pair():
    case = {"id": "same-target", "question": "First", "pairing_eligible": True}
    outputs = distinct_output_cases([case, {**case, "question": "Second"}])
    assert len({item["id"] for item in outputs}) == 2
    assert all(item["pairing_eligible"] is False for item in outputs)
    assert all(item["ambiguous_target_id"] == "same-target" for item in outputs)
    assert all("Multiple outputs" in item["unpairable_reason"] for item in outputs)
    assert case["id"] == "same-target"  # Inputs and existing frozen artifacts stay unchanged.


def test_card_with_unresolved_concept_never_falls_back_to_declared_global_identity():
    exported = portable_card_case(
        {"id": "production-card", "concept_id": "missing", "question": "Q", "sources": []},
        {},
        identity="definition",
        concept_targets={},
    )
    assert exported["pairing_eligible"] is False
    assert "missing or ambiguous" in exported["unpairable_reason"]


def reference_result():
    source = {"source_id": "a" * 24, "document_sha256": "b" * 64, "page_number": 1}
    return {
        "run_id": "synthetic-run",
        "dataset_id": "synthetic-dataset",
        "dataset_sha256": "c" * 64,
        "cards": [{"id": "synthetic-card", "question": "Q", "answer": "A", "sources": [source]}],
        "reference_inventory": {
            "dataset_id": "synthetic-dataset",
            "dataset_sha256": "c" * 64,
            "origin": "synthetic",
            "method": "Authored test fixture, no empirical quality claim",
            "concepts": [{"id": "target-a", "label": "Target", "source_refs": [source]}],
        },
    }


def mapped_bundle(result, tmp_path):
    export_review_package(result, tmp_path / "review")
    pending = load_annotations(tmp_path / "review" / "annotations.json", result)
    values = pending.model_dump()
    values["annotations"][0].update(
        origin="synthetic",
        method="Synthetic mapping test, not human academic validation",
        decision="accepted",
        reference_concept_ids=["target-a"],
    )
    return AnnotationBundle.model_validate(values)


def test_coverage_annotations_require_exact_reference_inventory_hash(tmp_path):
    result = reference_result()
    labels = mapped_bundle(result, tmp_path)
    assert labels.reference_inventory_sha256 == reference_inventory_hash(result)
    validate_bundle(labels, result)
    with pytest.raises(ValueError, match="frozen reference inventory hash"):
        validate_bundle(labels.model_copy(update={"reference_inventory_sha256": None}), result)


@pytest.mark.parametrize("field,value", [("label", "Changed target"), ("assumptions", ["x > 0"])])
def test_reference_changes_cannot_reinterpret_earlier_coverage_labels(tmp_path, field, value):
    result = reference_result()
    labels = mapped_bundle(result, tmp_path)
    changed = copy.deepcopy(result)
    changed["reference_inventory"]["concepts"][0][field] = value
    with pytest.raises(ValueError, match="reference inventory hash changed"):
        validate_bundle(labels, changed)


def test_legacy_pending_labels_without_mappings_remain_valid(tmp_path):
    result = reference_result()
    export_review_package(result, tmp_path / "review")
    pending = load_annotations(tmp_path / "review" / "annotations.json", result)
    legacy = pending.model_copy(update={"reference_inventory_sha256": None})
    assert validate_bundle(legacy, result) is legacy
    assert reference_inventory_hash(result) == reference_inventory_hash(copy.deepcopy(result))


def test_append_preserves_reference_binding_for_new_unmapped_judgments(tmp_path):
    result = reference_result()
    existing = mapped_bundle(result, tmp_path)
    values = existing.model_dump()
    values["reference_inventory_sha256"] = None
    values["annotations"][0].update(
        id="new-pending-case", decision="pending", reference_concept_ids=[]
    )
    incoming = AnnotationBundle.model_validate(values)
    output = append_annotations(result, incoming, tmp_path / "labels-v2.json", existing=existing)
    saved = load_annotations(output, result)
    assert saved.reference_inventory_sha256 == existing.reference_inventory_sha256
    assert len(saved.annotations) == 2
    invalid = existing.model_copy(update={"reference_inventory_sha256": None})
    with pytest.raises(ValueError, match="frozen reference inventory hash"):
        append_annotations(result, invalid, tmp_path / "invalid.json", existing=existing)


@pytest.mark.skipif(sys.platform != "linux", reason="Process-group regression observes Linux /proc")
@pytest.mark.parametrize("leader_exits", [False, True])
def test_worker_cleanup_terminates_descendant_even_when_leader_exits(monkeypatch, leader_exits):
    monkeypatch.setattr("anki_generator.benchmark.runner._WORKER_TERMINATION_GRACE_SECONDS", 0.05)
    child_code = (
        "import os, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print(os.getpid(), flush=True); time.sleep(60)"
    )
    leader_code = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1]]); "
        + ("time.sleep(0.1)" if leader_exits else "time.sleep(60)")
    )
    process = subprocess.Popen(
        [sys.executable, "-c", leader_code, child_code],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        assert process.stdout is not None
        child_pid = int(process.stdout.readline())
        completed = wait_for_worker(process, timeout=1 if leader_exits else 0.1)
        assert completed is leader_exits
        assert process.returncode is not None
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = Path(f"/proc/{child_pid}/stat")
            if not status.exists() or status.read_text().split()[2] == "Z":
                break
            time.sleep(0.01)
        else:
            pytest.fail("Owned descendant continued running after benchmark cleanup")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
