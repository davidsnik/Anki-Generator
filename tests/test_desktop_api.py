"""Desktop authentication, safe diagnostics and explicit browser-data migration."""

import io
import json
from pathlib import Path
from zipfile import ZipFile

import keyring
import pytest
from fastapi.testclient import TestClient

from anki_generator.api.app import create_app
from anki_generator.desktop.logs import LifecycleLog

TOKEN = "private-desktop-session-" + "a" * 40


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    from keyring.backends.null import Keyring

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(keyring, "get_keyring", Keyring)


def desktop_client(tmp_path: Path, **kwargs) -> TestClient:
    app = create_app(
        tmp_path / "data",
        start_worker=False,
        desktop_token=TOKEN,
        desktop_state_directory=tmp_path / "state",
        **kwargs,
    )
    return TestClient(app, headers={"X-Desktop-Token": TOKEN})


def test_desktop_token_protects_all_requests_and_static_files(tmp_path: Path):
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>Bundled desktop</html>")
    (frontend / "assets/app.js").write_text("const bundled=true;")
    with desktop_client(tmp_path, frontend_directory=frontend) as client:
        for endpoint in ("/", "/assets/app.js", "/api/health", "/api/bootstrap", "/openapi.json"):
            assert client.get(endpoint, headers={"X-Desktop-Token": ""}).status_code == 401
            assert client.get(endpoint, headers={"X-Desktop-Token": "forged"}).status_code == 401
            assert client.get(endpoint, headers=[(b"x-desktop-token", b"\xff")]).status_code == 401
            assert client.get(endpoint).status_code == 200
        bootstrap = client.get("/api/bootstrap")
        assert TOKEN not in bootstrap.text
        assert client.post("/api/courses", json={"name": "CSRF still required"}).status_code == 403
        client.headers["X-CSRF-Token"] = bootstrap.json()["csrf_token"]
        assert client.post("/api/courses", json={"name": "Desktop"}).status_code == 201
        assert (
            client.get("/api/bootstrap", headers={"Origin": "https://remote.invalid"}).status_code
            == 403
        )
        assert (
            client.get("/api/bootstrap", headers={"Origin": "http://localhost:5173"}).status_code
            == 200
        )


def test_desktop_routes_absent_in_browser_mode(api_client: TestClient):
    assert api_client.get("/api/health").status_code == 200
    assert api_client.get("/api/desktop/diagnostics").status_code == 404


@pytest.mark.parametrize("token", ["", "short", "a" * 300, "a" * 40 + "\n", "\u00e9" * 40])
def test_invalid_desktop_token_cannot_enable_unauthenticated_mode(tmp_path: Path, token: str):
    with pytest.raises(ValueError, match="Desktop authentication"):
        create_app(tmp_path, desktop_token=token, start_worker=False)
    assert not (tmp_path / "application.sqlite3").exists()


def test_diagnostics_are_bounded_allowlisted_and_exclude_secrets_private_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    private = "sk-private-api-key-and-source-sentinel"
    state = tmp_path / "state"
    log = LifecycleLog(state)
    log.event("ready")
    log.close()
    with (state / "logs/backend.log").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "event": "ready",
                    "pid": 123,
                    "secret": private,
                }
            )
            + "\n"
        )
        stream.write(private + "\n")
    with desktop_client(tmp_path) as client:
        client.app.state.runtime.secrets.set(private)
        client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf_token"]
        client.post("/api/courses", json={"name": private})
        report = client.get("/api/desktop/diagnostics").json()
        assert report["schema_version"]
        assert report["data_directory"] == str(tmp_path / "data")
        assert report["logs"]["events"][0]["event"] == "ready"
        assert private not in json.dumps(report)
        shutdown = client.get("/api/desktop/shutdown-status").json()
        assert shutdown["active_jobs"] == shutdown["queued_jobs"] == shutdown["paused_jobs"] == 0
        assert shutdown["checkpoint_shutdown_timeout_seconds"] == 210
        exported = client.post("/api/desktop/diagnostics/export")
        assert exported.status_code == 200
        with ZipFile(io.BytesIO(exported.content)) as archive:
            assert set(archive.namelist()) == {"diagnostics.json", "README.txt"}
            payload = archive.read("diagnostics.json").decode()
            assert private not in payload and TOKEN not in payload
            assert str(tmp_path) not in payload
            assert "data_directory" not in payload


def test_explicit_browser_backup_import_preserves_courses_documents_and_originals(
    api_client: TestClient, course: dict, source_document: dict, tmp_path: Path
):
    browser_root = api_client.app.state.runtime.data_root
    original_bytes = api_client.get(source_document["source_url"]).content
    backup = api_client.post("/api/backup")
    assert backup.status_code == 200
    with desktop_client(tmp_path / "desktop") as client:
        client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf_token"]
        validation = client.post(
            "/api/backup/validate", files={"file": ("browser.zip", backup.content)}
        )
        assert validation.status_code == 200, validation.text
        restored = client.post(
            "/api/backup/restore",
            json={"token": validation.json()["token"], "mode": "clean", "confirm": True},
        )
        assert restored.status_code == 200, restored.text
        assert client.get("/api/courses").json()[0]["id"] == course["id"]
        assert client.get(source_document["source_url"]).content == original_bytes
    assert browser_root.is_dir()
    assert api_client.get(source_document["source_url"]).content == original_bytes


def test_desktop_shutdown_waits_for_inflight_request_then_saves_paused_checkpoint(tmp_path):
    import threading
    import time

    from sqlalchemy import select
    from support.controlled_provider import ControlledProvider

    from anki_generator.database.entities import Run

    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    failures = []

    class BlockedProvider(ControlledProvider):
        def structured(self, stage, payload, schema, **kwargs):
            if stage == "knowledge":
                entered.set()
                assert release.wait(15), "Test barrier was not released"
            return super().structured(stage, payload, schema, **kwargs)

    provider = BlockedProvider()
    app = create_app(
        tmp_path / "data",
        desktop_token=TOKEN,
        desktop_state_directory=tmp_path / "state",
        desktop_shutdown_timeout=0.02,
        provider_factory=lambda key, config: provider,
    )
    client = TestClient(app, headers={"X-Desktop-Token": TOKEN})
    client.__enter__()
    rt = app.state.runtime
    try:
        client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf_token"]
        client.put("/api/settings/key", json={"api_key": "controlled-offline-key"})
        course = client.post("/api/courses", json={"name": "Checkpoint on quit"}).json()
        client.post(
            f"/api/courses/{course['id']}/documents",
            files=[
                (
                    "files",
                    (
                        "lecture.txt",
                        b"For a right triangle, a^2 + b^2 = c^2. "
                        b"The right-angle assumption is necessary.",
                    ),
                )
            ],
        )
        submitted = client.post(f"/api/courses/{course['id']}/runs", json={"consent": True})
        assert submitted.status_code == 202, submitted.text
        identifier = submitted.json()["id"]
        assert entered.wait(10)

        def close():
            try:
                client.__exit__(None, None, None)
            except BaseException as error:
                failures.append(error)
            finally:
                closed.set()

        closing = threading.Thread(target=close)
        closing.start()
        deadline = time.monotonic() + 5
        while not rt.runner.scheduler_snapshot()["stopping"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not closed.wait(0.12), "In-flight operation was abandoned after short grace period"
        with rt.sessions() as session:
            assert session.get(Run, identifier).status in {"running", "pausing"}
        release.set()
        assert closed.wait(10)
        closing.join(timeout=1)
        assert not failures
        # Reopening the engine checks durable state after the lifespan disposed it.
        with rt.sessions() as session:
            assert session.scalar(select(Run.status).where(Run.id == identifier)) == "paused"
        rt.sessions.kw["bind"].dispose()
    finally:
        release.set()
        if not closed.is_set():
            client.__exit__(None, None, None)
