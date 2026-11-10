"""Reproducible, opt-in experiments using isolated production-service workers."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from anki_generator.benchmark.contracts import BenchmarkConfig, DatasetManifest
from anki_generator.benchmark.inventory import write_new_json
from anki_generator.processing.state import digest

_WORKER_TERMINATION_GRACE_SECONDS = 1.0


def _worker_group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for_worker(process: subprocess.Popen, timeout: float) -> bool:
    """Reap a worker created with start_new_session=True, including its descendants.

    A leader exiting does not establish that its parser children exited. Retain
    the newly owned process-group ID and bound cleanup independently of the leader.
    """
    group_id = process.pid
    completed = True
    try:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            completed = False
    finally:
        if _worker_group_exists(group_id):
            try:
                os.killpg(group_id, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + _WORKER_TERMINATION_GRACE_SECONDS
            while _worker_group_exists(group_id) and time.monotonic() < deadline:
                remaining = min(0.05, max(0, deadline - time.monotonic()))
                if process.poll() is None:
                    try:
                        process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        pass
                else:
                    time.sleep(remaining)
            if _worker_group_exists(group_id):
                try:
                    os.killpg(group_id, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        process.wait()
    return completed


def implementation_metadata(root: Path) -> dict:
    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None

    package = root / "src" / "anki_generator"
    fingerprint = digest(
        {
            path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".txt", ".mako"}
        }
    )
    revision = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    snapshot = root / ".benchmark-revision.json"
    declared = json.loads(snapshot.read_text()) if snapshot.is_file() else {}

    def dependency_version(name: str) -> str | None:
        try:
            return version(name)
        except PackageNotFoundError:
            return None

    return {
        "git_revision": revision or declared.get("git_revision"),
        "git_dirty": bool(status) if status is not None else None,
        "snapshot_provenance": declared,
        "source_tree_sha256": fingerprint,
        "prompt_hashes": {
            path.name: digest(path.read_text())
            for path in sorted((package / "prompts").glob("*.txt"))
        },
        "python_version": sys.version.split()[0],
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "dependency_versions": {
                name: dependency_version(name)
                for name in ("PyMuPDF", "pydantic", "SQLAlchemy", "openai", "numpy")
            },
            "lockfile_sha256": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ("uv.lock",)
                if (root / name).is_file()
            },
        },
        "implementation_root": str(root),
        "model_nondeterminism": "Live outputs may vary; no seed guarantee is asserted",
        "benchmark_harness_hashes": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(__file__).parent.glob("*.py"))
        },
    }


def snapshot_implementation(root: Path, destination: Path) -> None:
    """Retain the exact production source used by this run, including dirty edits."""
    package = root / "src" / "anki_generator"
    destination.mkdir(mode=0o700)
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".txt", ".mako"}:
            target = destination / "src" / "anki_generator" / path.relative_to(package)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(0o600)
    for name in ("pyproject.toml", "uv.lock"):
        path = root / name
        if path.is_file():
            shutil.copyfile(path, destination / name)


def run_benchmark(
    manifest: DatasetManifest,
    config: BenchmarkConfig,
    output_root: Path,
    *,
    implementation_root: Path | None = None,
    live: bool = False,
    consent: bool = False,
) -> Path:
    """Save new run artifacts; evaluation references never enter generation requests."""
    if config.execution == "live_pipeline" and not (live and consent):
        raise ValueError("Live model execution requires both --live and --consent")
    if not manifest.source_root:
        raise ValueError("Inventory with --extract-to before running a dataset")
    source_root = Path(manifest.source_root).resolve(strict=True)
    implementation_root = (implementation_root or Path.cwd()).resolve(strict=True)
    if not (implementation_root / "src" / "anki_generator").is_dir():
        raise ValueError("Implementation root must contain src/anki_generator")
    available = {source.id: source for source in manifest.sources}
    for workload in config.workloads:
        for sample in workload.samples:
            if sample.source_id not in available:
                raise ValueError("A workload refers to a source absent from the frozen dataset")
            source = available[sample.source_id]
            if not source.supported:
                raise ValueError("Selected source format is inventoried but unsupported")
            path = source_root / source.relative_path
            if path.is_symlink() or not path.resolve().is_relative_to(source_root):
                raise ValueError("Selected source escapes the dataset or is a symlink")
        if config.execution != "local_extract" and any(
            sample.page_numbers is not None for sample in workload.samples
        ):
            raise ValueError(
                "Durable pipeline workloads currently require complete source files; "
                "page selections are supported by local fidelity runs"
            )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
    directory = output_root / run_id
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    write_new_json(directory / "dataset.json", manifest.model_dump(mode="json"))
    write_new_json(directory / "configuration.json", config.model_dump(mode="json"))
    metadata = implementation_metadata(implementation_root)
    implementation_snapshot = directory.resolve() / "implementation"
    snapshot_implementation(implementation_root, implementation_snapshot)
    snapshot_metadata = implementation_metadata(implementation_snapshot)
    if snapshot_metadata["source_tree_sha256"] != metadata["source_tree_sha256"]:
        raise ValueError("Implementation changed during snapshot; saved attempt is retained")
    metadata["executed_snapshot"] = str(implementation_snapshot)
    write_new_json(directory / "implementation.json", metadata)
    harness_root = directory.resolve() / "harness"
    harness_root.mkdir(mode=0o700)
    for path in Path(str(files("anki_generator.benchmark"))).glob("*.py"):
        shutil.copyfile(path, harness_root / path.name)
    worker = harness_root / "worker.py"
    courses, cards, concepts, fidelity, retrieval = [], [], [], [], []
    started = time.perf_counter()
    for workload in config.workloads:
        work_root = directory / workload.id
        work_root.mkdir(mode=0o700)
        sources = []
        for sample in workload.samples:
            source = available[sample.source_id]
            sources.append(
                {
                    **source.model_dump(mode="json", exclude={"metadata"}),
                    "path": str(source_root / source.relative_path),
                    "page_numbers": sample.page_numbers,
                    "split": sample.split,
                    "stratum": sample.stratum,
                    "sampling_rationale": sample.rationale,
                }
            )
        request = {
            "schema_version": "1",
            "name": workload.name,
            "implementation_root": str(implementation_snapshot),
            "sources": sources,
            "execution": config.execution,
            "extraction": config.extraction.model_dump(mode="json"),
            "pipeline": config.pipeline.model_dump(mode="json"),
            "max_api_requests": config.max_api_requests,
            "max_elapsed_seconds": config.max_elapsed_seconds,
            "repetitions": config.repetitions,
            "live": live,
            "consent": consent,
        }
        request_path = write_new_json(work_root / "request.json", request)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(implementation_root / "src")
        environment["PYTHONUNBUFFERED"] = "1"
        environment.pop("ELECTRON_RUN_AS_NODE", None)
        if config.execution != "live_pipeline":
            environment.pop("OPENAI_API_KEY", None)
            environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        with (work_root / "worker.log").open("x") as log:
            process = subprocess.Popen(
                [sys.executable, str(worker), str(request_path.resolve())],
                cwd=work_root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            completed = wait_for_worker(process, config.max_elapsed_seconds + 240)
        result_path = work_root / "worker-result.json"
        result = (
            json.loads(result_path.read_text())
            if result_path.exists()
            else {
                "status": "failed",
                "error_kind": "worker_exit" if completed else "worker_timeout",
                "exit_code": process.returncode,
            }
        )
        courses.append(
            {
                "id": workload.id,
                "name": workload.name,
                "source_ids": [sample.source_id for sample in workload.samples],
                **{
                    key: value
                    for key, value in result.items()
                    if key not in {"cards", "concepts", "fidelity", "retrieval"}
                },
            }
        )
        for key, target in (
            ("cards", cards),
            ("concepts", concepts),
            ("fidelity", fidelity),
            ("retrieval", retrieval),
        ):
            target.extend({**case, "workload_id": workload.id} for case in result.get(key, []))
    for collection in (cards, concepts, fidelity, retrieval):
        for case in collection:
            case["source_case_id"] = case["id"]
            case["id"] = f"{case['workload_id']}:{case['id']}"
    result = {
        "schema_version": "1",
        "run_id": run_id,
        "dataset_id": manifest.dataset_id,
        "dataset_sha256": manifest.dataset_sha256,
        "created_at": datetime.now(UTC).isoformat(),
        "configuration": config.model_dump(mode="json"),
        "reproducibility": metadata,
        "source_manifest": [source.model_dump(mode="json") for source in manifest.sources],
        "courses": courses,
        "cards": cards,
        "concepts": concepts,
        "fidelity": fidelity,
        "retrieval": retrieval,
        "measurements": {"wall_seconds": time.perf_counter() - started},
        "evidence": {
            "execution": "openai" if config.execution == "live_pipeline" else "local_only",
            "human_validation": "pending",
            "limitations": [
                "Source agreement is not mathematical correctness.",
                "Local extraction does not run vision interpretation or generate cards.",
                "No model or human score is inferred from structural success.",
                "Memory peaks belong to isolated workloads; they are not cumulative across runs.",
            ],
        },
    }
    return write_new_json(directory / "result.json", result)
