"""Private dataset safety and real offline developer-worker integration."""

import hashlib
import json
import signal
import stat
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from anki_generator.benchmark.contracts import BenchmarkConfig
from anki_generator.benchmark.inventory import inventory_zip, write_new_json
from anki_generator.benchmark.runner import run_benchmark, wait_for_worker
from anki_generator.benchmark.worker import portable_case
from anki_generator.cli import app


def archive_at(path, entries):
    with ZipFile(path, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return path


def local_dataset(tmp_path):
    archive = archive_at(
        tmp_path / "source.zip", [("Study/courses/Probability/lecture.txt", "P(A)=1/2.\n")]
    )
    return inventory_zip(archive, extract_to=tmp_path / "sources")


def configuration(manifest, **changes):
    return BenchmarkConfig.model_validate(
        {
            "name": "Offline integration",
            "workloads": [
                {
                    "id": "small",
                    "name": "Probability",
                    "samples": [
                        {
                            "source_id": manifest.sources[0].id,
                            "rationale": "Synthetic worker regression, no academic-quality claim",
                        }
                    ],
                }
            ],
            **changes,
        }
    )


@pytest.mark.parametrize("name", ["../escape.pdf", "/absolute.pdf", "C:/drive.pdf", "a\\b.pdf"])
def test_private_archive_rejects_unsafe_paths_before_extracting(tmp_path, name):
    archive = archive_at(tmp_path / "bad.zip", [("safe.pdf", b"safe"), (name, b"bad")])
    with pytest.raises(ValueError, match="path|traversal"):
        inventory_zip(archive, extract_to=tmp_path / "sources")
    assert not (tmp_path / "sources").exists()
    assert not list(tmp_path.glob(".dataset-*"))


def test_archive_link_duplicates_and_expansion_bounds(tmp_path):
    link = ZipInfo("linked.pdf")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = archive_at(tmp_path / "link.zip", [(link, "/private/file")])
    with pytest.raises(ValueError, match="links"):
        inventory_zip(archive)
    with pytest.warns(UserWarning, match="Duplicate"):
        archive = archive_at(tmp_path / "duplicate.zip", [("x.pdf", b"a"), ("x.pdf", b"b")])
    with pytest.raises(ValueError, match="duplicate"):
        inventory_zip(archive)
    archive = archive_at(tmp_path / "large.zip", [("x.pdf", b"abc")])
    with pytest.raises(ValueError, match="expansion"):
        inventory_zip(archive, max_expanded_bytes=2)


def test_deterministic_content_manifest_preserves_originals_and_unknown_roles(tmp_path):
    entries = [("Study/courses/Test/misc.pdf", b"pdf"), ("Study/courses/Test/code.py", b"x=1")]
    first = archive_at(tmp_path / "a.zip", entries)
    second = archive_at(tmp_path / "b.zip", list(reversed(entries)))
    original = first.read_bytes()
    a = inventory_zip(first, extract_to=tmp_path / "sources")
    b = inventory_zip(second)
    assert a.dataset_sha256 == b.dataset_sha256
    assert [source.id for source in a.sources] == [source.id for source in b.sources]
    assert first.read_bytes() == original
    assert all(not source.role_candidates for source in a.sources)
    assert {source.source_type: source.supported for source in a.sources} == {
        "py": False,
        "pdf": True,
    }
    for source in a.sources:
        data = (Path(a.source_root) / source.relative_path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == source.sha256
    with pytest.raises(ValueError, match="new"):
        inventory_zip(first, extract_to=tmp_path / "sources")


def test_exercise_relationship_hints_remain_explicitly_unconfirmed(tmp_path):
    archive = archive_at(
        tmp_path / "roles.zip",
        [
            ("Study/courses/Math/Linear Algebra Exercises 1.pdf", b"a"),
            ("Study/courses/Math/Linear Algebra Solutions 1.pdf", b"b"),
            ("Study/courses/Other/Linear Algebra Solutions 1.pdf", b"c"),
            ("Study/courses/Math/Exam Questions and Solutions.pdf", b"d"),
            ("Study/courses/Math/Exercises.pdf", b"e"),
        ],
    )
    manifest = inventory_zip(archive)
    assert len(manifest.relationships) == 2
    assert {item["status"] for item in manifest.relationships} == {"unconfirmed"}
    by_id = {source.id: source for source in manifest.sources}
    pair = next(item for item in manifest.relationships if len(item["source_ids"]) == 2)
    assert len({by_id[value].course_id for value in pair["source_ids"]}) == 1


def test_cli_schema_errors_do_not_print_untrusted_input_values(tmp_path):
    manifest = local_dataset(tmp_path)
    manifest_path = write_new_json(tmp_path / "manifest.json", manifest.model_dump(mode="json"))
    config = configuration(manifest).model_dump(mode="json")
    config["pipeline"]["accidental_secret"] = "sk-private-marker-never-print"
    config_path = write_new_json(tmp_path / "config.json", config)
    response = CliRunner().invoke(
        app, ["benchmark", "run", str(manifest_path), "--config", str(config_path)]
    )
    assert response.exit_code == 1
    assert "input values withheld" in response.output
    assert "sk-private-marker" not in response.output


def test_configs_reject_reference_leakage_and_paid_execution_requires_both_flags(tmp_path):
    manifest = local_dataset(tmp_path)
    with pytest.raises(ValidationError):
        configuration(manifest, reference_cards=[{"answer": "gold"}])
    with pytest.raises(ValidationError):
        configuration(manifest, max_api_requests=0)
    with pytest.raises(ValidationError, match="local_pipeline"):
        configuration(manifest, repetitions=2)
    config = configuration(manifest, execution="live_pipeline")
    for flags in ({}, {"live": True}, {"consent": True}):
        with pytest.raises(ValueError, match="both"):
            run_benchmark(manifest, config, tmp_path / "runs", **flags)
    assert not (tmp_path / "runs").exists()


def test_real_offline_worker_handles_relative_output_and_retains_two_runs(tmp_path, monkeypatch):
    manifest = local_dataset(tmp_path)
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    outputs = []
    for _ in range(2):
        result_path = run_benchmark(
            manifest, configuration(manifest), Path("runs"), implementation_root=root
        )
        result = json.loads(result_path.read_text())
        assert result["courses"][0]["status"] == "completed"
        assert result["fidelity"][0]["transcription"] == "P(A)=1/2.\n"
        assert result["courses"][0]["measurements"]["api_requests"] == 0
        assert result["evidence"]["human_validation"] == "pending"
        assert result["cards"] == []
        assert Path(result["fidelity"][0]["image_path"]).exists()
        snapshot = Path(result["reproducibility"]["executed_snapshot"])
        assert Path(result["courses"][0]["implementation_path"]).is_relative_to(snapshot)
        assert (result_path.parent / "harness" / "worker.py").exists()
        assert (snapshot / "src" / "anki_generator" / "ingestion" / "extraction.py").is_file()
        outputs.append(result_path)
    assert outputs[0] != outputs[1]
    assert all(path.exists() for path in outputs)
    assert not list(tmp_path.glob("**/application.sqlite"))


def test_changed_source_is_failure_not_silent_new_baseline(tmp_path):
    manifest = local_dataset(tmp_path)
    source = manifest.sources[0]
    (Path(manifest.source_root) / source.relative_path).write_text("changed")
    result_path = run_benchmark(
        manifest,
        configuration(manifest),
        tmp_path / "runs",
        implementation_root=Path(__file__).resolve().parents[1],
    )
    result = json.loads(result_path.read_text())
    assert result["courses"][0]["status"] == "failed"
    assert result["fidelity"] == []
    assert result["evidence"]["execution"] == "local_only"


def test_durable_offline_pipeline_reuses_real_extraction_without_credentials(tmp_path):
    manifest = local_dataset(tmp_path)
    result_path = run_benchmark(
        manifest,
        configuration(manifest, execution="local_pipeline", repetitions=2),
        tmp_path / "runs",
        implementation_root=Path(__file__).resolve().parents[1],
    )
    result = json.loads(result_path.read_text())
    course = result["courses"][0]
    assert course["status"] == "completed", course
    assert len(course["repetitions"]) == 2
    assert result["fidelity"][0]["transcription"] == "P(A)=1/2.\n"
    assert all(not repetition["usage"].get("api_calls") for repetition in course["repetitions"])
    assert result["cards"] == []


def test_cli_help_is_developer_only_and_json_results_do_not_overwrite(tmp_path):
    response = CliRunner().invoke(app, ["benchmark", "--help"])
    assert response.exit_code == 0
    assert "review-export" in response.stdout
    assert "inventory" in response.stdout
    path = write_new_json(tmp_path / "result.json", {"human_judgments": None})
    with pytest.raises(FileExistsError):
        write_new_json(path, {"human_judgments": "invented"})
    assert json.loads(path.read_text())["human_judgments"] is None


def test_existing_portable_reference_examples_validate_without_becoming_ground_truth():
    fixture = Path(__file__).resolve().parents[1] / "fixtures/evaluation/synthetic-probability.json"
    response = CliRunner().invoke(app, ["benchmark", "reference-validate", str(fixture)])
    assert response.exit_code == 0
    assert "synthetic" in response.stdout
    assert "does not establish academic truth" in response.stdout


def test_portable_case_pairs_declared_targets_without_database_ids():
    source = {"id": "source-a", "sha256": "a" * 64}
    cases = [
        portable_case(
            {
                "id": f"card-{i}",
                "question": "Q",
                "answer": answer,
                "sources": [{"document_id": f"doc-{i}", "page_number": 1}],
            },
            {f"doc-{i}": source},
            identity="explicit-target",
            kind="card",
        )
        for i, answer in enumerate(["first", "revised"])
    ]
    assert cases[0]["id"] == cases[1]["id"]
    assert cases[0]["production_id"] != cases[1]["production_id"]
    assert cases[0]["sources"][0]["source_id"] == "source-a"
    assert cases[0]["sources"][0]["document_sha256"] == "a" * 64
    assert "not human equivalence" in cases[0]["pairing_basis"]
    unmatched = portable_case(
        {"id": "unknown", "question": "Q", "sources": [{"document_id": "absent"}]},
        {},
        identity=None,
        kind="card",
    )
    assert unmatched["sources"] == []
    assert unmatched["unresolved_source_references"] == 1


def test_interruption_reaps_only_the_owned_worker_group(monkeypatch):
    class Worker:
        pid = 1234567
        returncode = None
        calls = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            self.returncode = -15
            return self.returncode

    signals = []
    worker = Worker()

    def signal_owned_group(group_id, signum):
        if signum == 0:
            if worker.returncode is not None:
                raise ProcessLookupError
        else:
            signals.append((group_id, signum))

    monkeypatch.setattr("anki_generator.benchmark.runner.os.killpg", signal_owned_group)
    with pytest.raises(KeyboardInterrupt):
        wait_for_worker(worker, 10)
    assert signals == [(worker.pid, signal.SIGTERM)]
    assert worker.returncode == -15
