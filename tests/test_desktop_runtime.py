"""Actual loopback launch, process lifecycle and independent persistent paths."""

import json
import os
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from anki_generator.desktop.logs import LifecycleLog, safe_events
from anki_generator.desktop.main import main, write_startup
from anki_generator.desktop.paths import resolve_paths

ROOT = Path(__file__).resolve().parents[1]


def test_xdg_paths_are_private_and_ignore_relative_environment_values(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_STATE_HOME", "relative-is-ignored")
    paths = resolve_paths()
    assert paths.data == tmp_path / "xdg-data/anki-generator"
    assert paths.state == tmp_path / "home/.local/state/anki-generator"
    assert (
        stat.S_IMODE(paths.data.stat().st_mode) == stat.S_IMODE(paths.state.stat().st_mode) == 0o700
    )
    assert resolve_paths(tmp_path / "override", tmp_path / "state").data == tmp_path / "override"


def test_startup_metadata_is_atomic_private_and_never_contains_environment_token(tmp_path):
    path = tmp_path / "ready.json"
    path.write_text("stale metadata")
    write_startup(path, {"status": "ready", "pid": 123, "port": 456})
    assert json.loads(path.read_text()) == {"status": "ready", "pid": 123, "port": 456}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_missing_launch_secret_fails_before_creating_database(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANKI_GENERATOR_DESKTOP_TOKEN", raising=False)
    ready = tmp_path / "ready.json"
    assert main(["--startup-file", str(ready), "--data-directory", str(tmp_path / "data")]) == 2
    assert json.loads(ready.read_text())["code"] == "configuration"
    assert not (tmp_path / "data/application.sqlite3").exists()
    assert "configuration" in capsys.readouterr().err


def test_runtime_factory_error_is_curated_and_does_not_leak_secret(tmp_path, monkeypatch, capsys):
    secret = "sk-secret-not-for-diagnostics-" + "a" * 32
    monkeypatch.setenv("ANKI_GENERATOR_DESKTOP_TOKEN", secret)

    def broken(*args, **kwargs):
        assert "ANKI_GENERATOR_DESKTOP_TOKEN" not in os.environ
        raise RuntimeError(secret)

    ready = tmp_path / "ready.json"
    assert (
        main(
            [
                "--startup-file",
                str(ready),
                "--data-directory",
                str(tmp_path / "data"),
                "--state-directory",
                str(tmp_path / "state"),
            ],
            create_app_factory=broken,
        )
        == 1
    )
    assert json.loads(ready.read_text())["status"] == "error"
    assert secret not in ready.read_text() + capsys.readouterr().err
    assert secret not in (tmp_path / "state/logs/backend.log").read_text()


def test_frozen_runtime_refuses_missing_frontend_before_publishing_readiness(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("anki_generator.desktop.main")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "bundle/desktop/main.py"))
    monkeypatch.setenv("ANKI_GENERATOR_DESKTOP_TOKEN", "a" * 64)
    ready = tmp_path / "ready.json"
    result = main(
        [
            "--startup-file",
            str(ready),
            "--data-directory",
            str(tmp_path / "data"),
            "--state-directory",
            str(tmp_path / "state"),
        ]
    )
    assert result == 1
    assert json.loads(ready.read_text())["code"] == "resources"
    assert not (tmp_path / "data/application.sqlite3").exists()


def test_uvicorn_diagnostic_filter_never_formats_exception_secrets():
    import logging

    from anki_generator.desktop.logs import SafeServerFilter

    private = "sk-private-not-for-logs"
    try:
        raise RuntimeError(private)
    except RuntimeError:
        record = logging.LogRecord(
            "uvicorn.error", logging.ERROR, "", 0, private, (), sys.exc_info()
        )
    assert SafeServerFilter().filter(record)
    assert private not in logging.Formatter().format(record)


def test_readiness_publication_failure_stops_server_instead_of_leaving_an_orphan(
    tmp_path, monkeypatch
):
    import importlib
    import io
    import threading
    from types import SimpleNamespace

    module = importlib.import_module("anki_generator.desktop.main")
    monkeypatch.setattr(
        module.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(b'{"status":"ok"}')),
    )

    def unwritable(*args, **kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr(module, "write_startup", unwritable)
    server = SimpleNamespace(started=True, should_exit=False)
    events = []
    module._ready(
        server,
        "http://127.0.0.1:1234",
        "a" * 64,
        tmp_path / "ready.json",
        "1.0",
        threading.Event(),
        SimpleNamespace(event=lambda *args, **kwargs: events.append(args[0])),
    )
    assert server.should_exit and events == ["readiness_failed"]


def test_runner_stop_timeout_keeps_ownership_until_worker_finishes(tmp_path):
    import threading

    from anki_generator.database.connection import open_database
    from anki_generator.orchestration.runner import DurableRunner

    sessions = open_database(tmp_path)
    runner = DurableRunner(sessions, tmp_path, lambda: None)
    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=True)
    runner._active["test-owned-worker"] = worker
    worker.start()
    try:
        with pytest.raises(ValueError, match="still finishing"):
            runner.stop(timeout=0.01)
        assert worker.is_alive() and runner.scheduler_snapshot()["stopping"]
        release.set()
        runner.stop(timeout=1)
        assert not worker.is_alive()
    finally:
        release.set()
        worker.join(timeout=1)
        sessions.kw["bind"].dispose()


def test_rotating_lifecycle_logs_remain_bounded_and_private(tmp_path, monkeypatch):
    from anki_generator.desktop import logs

    monkeypatch.setattr(logs, "MAX_LOG_BYTES", 250)
    log = LifecycleLog(tmp_path)
    for _ in range(40):
        log.event("ready")
    log.close()
    files = list((tmp_path / "logs").iterdir())
    assert len(files) <= 4
    assert all(
        path.stat().st_size <= 250 and stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files
    )
    assert safe_events(tmp_path)


@contextmanager
def backend(tmp_path: Path, *, data: Path | None = None, parent_pid: int | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ready = tmp_path / "ready.json"
    token = secrets.token_hex(32)
    environment = {
        **os.environ,
        "ANKI_GENERATOR_DESKTOP_TOKEN": token,
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    environment.pop("OPENAI_API_KEY", None)
    args = [
        sys.executable,
        "-m",
        "anki_generator.desktop",
        "--startup-file",
        str(ready),
        "--data-directory",
        str(data or tmp_path / "data"),
        "--state-directory",
        str(tmp_path / "state"),
    ]
    if parent_pid:
        args.extend(["--parent-pid", str(parent_pid)])
    process = subprocess.Popen(
        args, cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), process.communicate(timeout=3)
        metadata = json.loads(ready.read_text())
        yield process, metadata, token
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.communicate(timeout=3)


def test_actual_subprocess_dynamic_socket_readiness_restart_and_local_extraction(tmp_path):
    data = tmp_path / "persistent"
    with backend(tmp_path / "launch-one", data=data) as (process, ready, token):
        assert ready["status"] == "ready" and ready["pid"] == process.pid
        assert ready["host"] == "127.0.0.1" and ready["port"] > 0
        assert token not in json.dumps(ready)
        with socket.socket() as contender:
            with pytest.raises(OSError):
                contender.bind(("127.0.0.1", ready["port"]))
        with httpx.Client(base_url=ready["origin"], trust_env=False) as client:
            assert client.get("/api/health").status_code == 401
            client.headers["X-Desktop-Token"] = token
            client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf_token"]
            course = client.post("/api/courses", json={"name": "Persistent outside cwd"}).json()
            document = client.post(
                f"/api/courses/{course['id']}/documents",
                files=[
                    (
                        "files",
                        (
                            "source.txt",
                            b"A continuous function on a compact interval attains its maximum.",
                        ),
                    )
                ],
            ).json()["documents"][0]
            run = client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"}).json()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = client.get(f"/api/runs/{run['id']}").json()
                if result["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            assert result["status"] == "completed", result
            assert "compact interval" in client.get(f"/api/documents/{document['id']}/pages").text
    with backend(tmp_path / "launch-two", data=data) as (_, ready, token):
        with httpx.Client(
            base_url=ready["origin"], headers={"X-Desktop-Token": token}, trust_env=False
        ) as client:
            assert client.get("/api/courses").json()[0]["id"] == course["id"]
            assert client.get(document["source_url"]).status_code == 200
    assert not (tmp_path / "launch-one/application.sqlite3").exists()


def test_actual_second_backend_cannot_open_owned_data_directory(tmp_path):
    data = tmp_path / "shared"
    with backend(tmp_path / "first", data=data) as (_, first, _):
        assert first["status"] == "ready"
        with backend(tmp_path / "second", data=data) as (process, second, token):
            assert second["status"] == "error"
            assert token not in json.dumps(second)
            process.wait(timeout=5)
            assert process.returncode != 0


def test_parent_exit_requests_graceful_backend_shutdown(tmp_path):
    ready = tmp_path / "ready.json"
    args = [
        sys.executable,
        "-m",
        "anki_generator.desktop",
        "--startup-file",
        str(ready),
        "--data-directory",
        str(tmp_path / "data"),
        "--state-directory",
        str(tmp_path / "state"),
    ]
    script = (
        "import os, subprocess, sys, time; "
        "subprocess.Popen(sys.argv[1:] + ['--parent-pid', str(os.getpid())]); time.sleep(60)"
    )
    environment = {
        **os.environ,
        "ANKI_GENERATOR_DESKTOP_TOKEN": secrets.token_hex(32),
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    environment.pop("OPENAI_API_KEY", None)
    parent = subprocess.Popen([sys.executable, "-c", script, *args], env=environment, cwd=tmp_path)
    try:
        deadline = time.monotonic() + 25
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert json.loads(ready.read_text())["status"] == "ready"
        parent.terminate()
        parent.wait(timeout=3)
        while time.monotonic() < deadline:
            if any(event["event"] == "stopped" for event in safe_events(tmp_path / "state")):
                break
            time.sleep(0.05)
        assert any(event["event"] == "parent_exited" for event in safe_events(tmp_path / "state"))
        assert any(event["event"] == "stopped" for event in safe_events(tmp_path / "state"))
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        if ready.exists():
            try:
                os.kill(json.loads(ready.read_text())["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
