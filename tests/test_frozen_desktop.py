"""Opt-in integration checks against a copied, real PyInstaller executable.

ANKI_TEST_FROZEN_BACKEND must identify a bundle outside the source checkout.
Normal tests never build packages or contact a live model provider.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import signal
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from support.desktop_provider_server import TEST_KEY, ControlledResponsesServer

ROOT = Path(__file__).resolve().parents[1]


def wait_for(operation, predicate, *, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = operation()
        if predicate(last):
            return last
        time.sleep(0.05)
    raise AssertionError(f"Packaged operation timed out; last result: {last}")


class FrozenBackend:
    def __init__(self, executable, directory, *, provider=None, data=None):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.data = data or directory / "data"
        self.token = secrets.token_urlsafe(32)
        self.ready = directory / "ready.json"
        self.origin = None
        self.client = None
        self.csrf = None
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "OPENAI_API_KEY"}
        }
        environment.update(
            {
                "PATH": "/usr/bin:/bin",
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                "ANKI_GENERATOR_DESKTOP_TOKEN": self.token,
            }
        )
        if provider:
            environment.update(
                {"OPENAI_BASE_URL": f"{provider.origin}/v1/", "OPENAI_API_KEY": TEST_KEY}
            )
        self.process = subprocess.Popen(
            [
                str(executable),
                "--data-directory",
                str(self.data),
                "--state-directory",
                str(directory / "state"),
                "--startup-file",
                str(self.ready),
                "--parent-pid",
                str(os.getpid()),
            ],
            cwd=directory,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def startup(self):
        def read():
            if self.ready.is_file():
                return json.loads(self.ready.read_text())
            assert self.process.poll() is None, "Frozen backend exited before readiness"
            return None

        info = wait_for(read, bool)
        assert info["status"] == "ready", info
        assert info["host"] == "127.0.0.1" and info["pid"] == self.process.pid
        assert self.ready.stat().st_mode & 0o777 == 0o600
        assert self.token not in self.ready.read_text()
        self.origin = info["origin"]
        self.client = httpx.Client(
            base_url=self.origin,
            headers={"X-Desktop-Token": self.token},
            timeout=90,
            trust_env=False,
        )
        assert self.client.get("/api/health").json()["status"] == "ok"
        self.csrf = self.client.get("/api/bootstrap").json()["csrf_token"]
        self.client.headers["X-CSRF-Token"] = self.csrf
        return self

    def json(self, method, route, **kwargs):
        response = self.client.request(method, route, **kwargs)
        assert response.is_success, (route, response.status_code, response.text)
        return response.json()

    def run(self, course, mode="extract"):
        return self.json(
            "POST", f"/api/courses/{course['id']}/runs", json={"mode": mode, "consent": True}
        )

    def result(self, run):
        result = wait_for(
            lambda: self.json("GET", f"/api/runs/{run['id']}"),
            lambda value: value["status"] in {"completed", "failed", "cancelled", "paused"},
            timeout=120,
        )
        assert result["status"] == "completed", result.get("error")
        return result

    def course(self, name):
        return self.json("POST", "/api/courses", json={"name": name})

    def upload(self, course, path):
        response = self.json(
            "POST",
            f"/api/courses/{course['id']}/documents",
            files={"files": (path.name, path.read_bytes())},
        )
        return response["documents"][0]

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()  # Parent first; parsers must finish and checkpoint.
            assert self.process.wait(timeout=30) in {0, -signal.SIGTERM}
        if self.client:
            self.client.close()

    def cleanup(self):
        if self.client:
            self.client.close()
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=5)


@pytest.fixture
def frozen_factory(tmp_path):
    value = os.environ.get("ANKI_TEST_FROZEN_BACKEND")
    if not value:
        pytest.skip("Set ANKI_TEST_FROZEN_BACKEND to test an actual copied frozen bundle")
    executable = Path(value).resolve()
    assert executable.is_file() and not executable.is_relative_to(ROOT)
    processes = []

    def launch(*, provider=None, data=None):
        backend = FrozenBackend(
            executable, tmp_path / f"launch-{len(processes)}", provider=provider, data=data
        )
        processes.append(backend)
        return backend

    try:
        yield launch
    finally:
        for backend in processes:
            backend.cleanup()


def test_frozen_formats_authentication_resources_and_persistence(frozen_factory):
    backend = frozen_factory().startup()
    for route in ("/", "/api/health", "/api/bootstrap", "/api/courses"):
        assert httpx.get(f"{backend.origin}{route}", trust_env=False).status_code == 401
    assert backend.client.get("/").status_code == 200
    assert backend.client.get("/tasks").status_code == 200
    bootstrap = backend.json("GET", "/api/bootstrap")
    assert bootstrap["diagnostics"]["schema_version"] == "0006_concurrent_tasks"
    assert not bootstrap["key_status"]["configured"]
    course = backend.course("Frozen local formats")
    sources = [
        ROOT / "fixtures/e2e/01-lecture.pdf",
        ROOT / "fixtures/ingestion/sample.docx",
        ROOT / "fixtures/ingestion/sample.pptx",
    ]
    images = sorted((ROOT / "fixtures/ingestion").glob("*.png"))
    assert images
    documents = [backend.upload(course, path) for path in [*sources, images[0]]]
    result = backend.result(backend.run(course))
    assert result["progress"]["documents"] == 4
    for document in documents:
        pages = backend.json("GET", f"/api/documents/{document['id']}/pages")
        assert pages and pages[0]["regions"], document["filename"]
        image = backend.client.get(pages[0]["regions"][0]["image_url"])
        assert image.is_success and image.content.startswith(b"\x89PNG")
    card = backend.json(
        "POST",
        f"/api/courses/{course['id']}/cards",
        json={"question": "What is the derivative of \\(x^2\\)?", "answer": "\\(2x\\)"},
    )
    backend.json(
        "POST",
        f"/api/cards/{card['id']}/review",
        json={"decision": "approved", "reason": "Synthetic manual example checked by test author"},
    )
    exported = backend.json("POST", f"/api/courses/{course['id']}/exports", json={"format": "apkg"})
    package = backend.client.get(f"/api/exports/{exported['id']}/download")
    with ZipFile(io.BytesIO(package.content)) as archive:
        assert "collection.anki2" in archive.namelist()
    backup = backend.client.post("/api/backup").content
    backend.stop()
    reopened = frozen_factory(data=backend.data).startup()
    assert reopened.origin != backend.origin
    assert reopened.json("GET", "/api/courses")[0]["id"] == course["id"]
    assert reopened.json("GET", f"/api/cards/{card['id']}")["note_guid"] == card["note_guid"]
    assert len(reopened.json("GET", f"/api/courses/{course['id']}/documents")) == 4
    reopened.stop()
    restored = frozen_factory().startup()
    staged = restored.json(
        "POST", "/api/backup/validate", files={"file": ("legacy-workspace.zip", backup)}
    )
    restored.json(
        "POST",
        "/api/backup/restore",
        json={"token": staged["token"], "mode": "clean", "confirm": True},
    )
    assert restored.json("GET", f"/api/cards/{card['id']}")["note_guid"] == card["note_guid"]
    assert len(restored.json("GET", f"/api/courses/{course['id']}/documents")) == 4
    restored.stop()


def test_frozen_concurrent_sdk_jobs_symbolic_workers_and_anki(frozen_factory, tmp_path):
    with ControlledResponsesServer() as provider:
        backend = frozen_factory(provider=provider).startup()
        courses = [backend.course(f"Packaged synthetic course {index}") for index in range(3)]
        source = tmp_path / "lecture.txt"
        source.write_text(
            "For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is required."
        )
        documents = [backend.upload(course, source) for course in courses]
        with provider.lock:
            provider.gates = {document["id"]: threading.Event() for document in documents}
        try:
            runs = [backend.run(course, "generate") for course in courses]
            wait_for(lambda: provider.snapshot()["waiting"], lambda value: len(value) == 2)
            assert backend.json("GET", f"/api/runs/{runs[2]['id']}")["status"] == "queued"
            assert backend.json("GET", "/api/tasks/summary")["counts"]["running"] == 2
            provider.gates[documents[0]["id"]].set()
            backend.result(runs[0])
            wait_for(
                lambda: provider.snapshot()["waiting"],
                lambda value: sorted(value) == sorted([documents[1]["id"], documents[2]["id"]]),
            )
            cards = backend.json("GET", f"/api/courses/{courses[0]['id']}/cards")
            assert len(cards) == 1 and cards[0]["verification_status"] == "verified"
            detailed = backend.json("GET", f"/api/cards/{cards[0]['id']}")
            assert "calculation_verified" in json.dumps(detailed["verifications"])
            backend.json(
                "POST", f"/api/cards/{cards[0]['id']}/review", json={"decision": "approved"}
            )
            exported = backend.json(
                "POST", f"/api/courses/{courses[0]['id']}/exports", json={"format": "apkg"}
            )
            assert backend.client.get(f"/api/exports/{exported['id']}/download").content.startswith(
                b"PK"
            )
            for document in documents[1:]:
                provider.gates[document["id"]].set()
            for run in runs[1:]:
                backend.result(run)
            for course, document in zip(courses, documents, strict=True):
                cards = backend.json("GET", f"/api/courses/{course['id']}/cards")
                assert len(cards) == 1
                assert {ref["document_id"] for ref in cards[0]["sources"]} == {document["id"]}
            diagnostic_zip = backend.client.post("/api/desktop/diagnostics/export").content
            with ZipFile(io.BytesIO(diagnostic_zip)) as archive:
                contents = b"\n".join(archive.read(name) for name in archive.namelist())
                assert TEST_KEY.encode() not in contents and backend.token.encode() not in contents
                assert str(backend.data).encode() not in contents
            backend.stop()
        finally:
            for gate in provider.gates.values():
                gate.set()


def test_frozen_active_shutdown_checkpoints_and_crash_recovery(frozen_factory, tmp_path):
    with ControlledResponsesServer() as provider:
        backend = frozen_factory(provider=provider).startup()
        course = backend.course("Frozen recoverable course")
        source = tmp_path / "lecture.txt"
        source.write_text("For a right triangle, a^2 + b^2 = c^2.")
        document = backend.upload(course, source)
        provider.gates[document["id"]] = threading.Event()
        try:
            run = backend.run(course, "generate")
            wait_for(lambda: provider.snapshot()["waiting"], bool)
            backend.process.terminate()
            time.sleep(0.25)
            assert backend.process.poll() is None, "In-flight work must drain before normal exit"
            provider.gates[document["id"]].set()
            assert backend.process.wait(timeout=30) in {0, -signal.SIGTERM}
            with sqlite3.connect(backend.data / "application.sqlite3") as database:
                status, checkpoints = database.execute(
                    "SELECT status, checkpoints FROM runs WHERE id=?", (run["id"],)
                ).fetchone()
            assert status == "paused"
            assert any(key.startswith("knowledge:") for key in json.loads(checkpoints))
            restarted = frozen_factory(provider=provider, data=backend.data).startup()
            assert restarted.json("GET", f"/api/runs/{run['id']}")["status"] == "paused"
            knowledge_calls = provider.snapshot()["calls"]["knowledge"]
            restarted.json("POST", f"/api/runs/{run['id']}/resume")
            restarted.result(run)
            assert provider.snapshot()["calls"]["knowledge"] == knowledge_calls
            restarted.stop()
        finally:
            provider.gates[document["id"]].set()


def test_frozen_corrupt_database_and_second_owner_fail_safely(frozen_factory, tmp_path):
    backend = frozen_factory().startup()
    second = frozen_factory(data=backend.data)
    wait_for(lambda: second.process.poll(), lambda value: value is not None)
    assert second.process.returncode != 0
    assert json.loads(second.ready.read_text())["status"] == "error"
    assert backend.client.get("/api/health").is_success
    backend.stop()
    damaged = tmp_path / "damaged"
    damaged.mkdir()
    (damaged / "application.sqlite3").write_bytes(b"Synthetic corrupt database, not user data")
    failed = frozen_factory(data=damaged)
    wait_for(lambda: failed.process.poll(), lambda value: value is not None)
    assert failed.process.returncode != 0
    assert json.loads(failed.ready.read_text())["code"] == "database"
    assert (damaged / "application.sqlite3").read_bytes().startswith(b"Synthetic corrupt")


def test_frozen_unexpected_kill_recovers_without_claiming_unsaved_response(
    frozen_factory, tmp_path
):
    with ControlledResponsesServer() as provider:
        backend = frozen_factory(provider=provider).startup()
        course = backend.course("Frozen unexpected shutdown")
        source = tmp_path / "lecture.txt"
        source.write_text("For a right triangle, a^2 + b^2 = c^2.")
        document = backend.upload(course, source)
        provider.gates[document["id"]] = threading.Event()
        try:
            run = backend.run(course, "generate")
            wait_for(lambda: provider.snapshot()["waiting"], bool)
            backend.process.kill()
            assert backend.process.wait(timeout=10) == -signal.SIGKILL
            provider.gates[document["id"]].set()
            with sqlite3.connect(backend.data / "application.sqlite3") as database:
                assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            restarted = frozen_factory(provider=provider, data=backend.data).startup()
            recovered = restarted.json("GET", f"/api/runs/{run['id']}")
            assert recovered["status"] == "paused" and recovered["recovery_count"] == 1
            restarted.json("POST", f"/api/runs/{run['id']}/resume")
            restarted.result(run)
            # This call had no saved response at the crash, so repeating it is
            # required. Previously checkpointed extraction is retained.
            assert provider.snapshot()["calls"]["knowledge"] == 2
            restarted.stop()
        finally:
            provider.gates[document["id"]].set()
