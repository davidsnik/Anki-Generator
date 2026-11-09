"""Restore preflight, worker handoff and open-engine rollback regressions."""

from __future__ import annotations

import io
import json
import sqlite3
import threading
import zipfile

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, select, text

from anki_generator.api.app import create_app
from anki_generator.database.connection import migration_config, open_database
from anki_generator.database.entities import (
    Card,
    Course,
    Document,
    Page,
    ReviewDecision,
    Revision,
    Run,
    new_id,
    now,
)
from anki_generator.services import backups
from anki_generator.services.instance_lock import InstanceLock
from anki_generator.services.storage import store_bytes


class ObservedLock:
    """Keep the real lock semantics while exposing the worker's blocked attempt."""

    def __init__(self):
        self.lock = threading.Lock()
        self.waiting_worker = threading.Event()

    def acquire(self, *args, **kwargs):
        if threading.current_thread().name.startswith("anki-job-") and self.lock.locked():
            self.waiting_worker.set()
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


def staged_backup(client):
    archive = client.post("/api/backup")
    assert archive.status_code == 200, archive.text
    validation = client.post(
        "/api/backup/validate", files={"file": ("backup.zip", archive.content, "application/zip")}
    )
    assert validation.status_code == 200, validation.text
    return validation.json()["token"]


def test_restore_restarts_worker_that_had_read_a_now_paused_run(api_client, course, monkeypatch):
    """A queued-ID read may precede pause even though maintenance sees no active jobs."""
    rt = api_client.app.state.runtime
    with rt.sessions.begin() as session:
        run = Run(course_id=course["id"], mode="extract", status="queued")
        session.add(run)
        session.flush()
        run_id = run.id
    observed_lock = ObservedLock()
    monkeypatch.setattr(rt.runner, "_run_lock", observed_lock)
    read_queued = threading.Event()
    release_queued = threading.Event()
    original_claim = rt.runner._claim

    def delayed_run_now(identifier):
        read_queued.set()
        assert release_queued.wait(timeout=15)
        return original_claim(identifier)

    monkeypatch.setattr(rt.runner, "_claim", delayed_run_now)
    rt.runner.start()
    try:
        assert read_queued.wait(timeout=3)
        rt.runner.pause(run_id)
        token = staged_backup(api_client)
        original_stop = rt.runner.stop

        def release_then_stop():
            release_queued.set()
            assert observed_lock.waiting_worker.wait(timeout=3)
            return original_stop()

        monkeypatch.setattr(rt.runner, "stop", release_then_stop)
        response = api_client.post(
            "/api/backup/restore", json={"token": token, "confirm": True, "mode": "replace"}
        )
        assert response.status_code == 200, response.text
        assert rt.runner._thread is not None and rt.runner._thread.is_alive()
        assert not rt.runner._stop.is_set()
        assert api_client.get("/api/health").status_code == 200
    finally:
        release_queued.set()
        rt.runner.stop()


def test_failure_after_new_database_opens_disposes_it_before_rollback(
    api_client, course, monkeypatch
):
    token = staged_backup(api_client)
    api_client.patch(f"/api/courses/{course['id']}", json={"name": "Current state survives"})
    real_open = backups.open_database
    real_journal = backups.durable_json
    real_recover = backups.recover_interrupted_restore
    state = {"opened": False, "disposed": False, "disposed_before_rollback": None}

    def tracked_open(root, **kwargs):
        sessions = real_open(root, **kwargs)
        if not state["opened"]:
            state["opened"] = True
            engine = sessions.kw["bind"]
            real_dispose = engine.dispose

            def tracked_dispose(*args, **kwargs):
                state["disposed"] = True
                return real_dispose(*args, **kwargs)

            monkeypatch.setattr(engine, "dispose", tracked_dispose)
        return sessions

    def fail_commit(path, data):
        if data["phase"] == "committed":
            raise OSError("Synthetic committed-journal write failure")
        return real_journal(path, data)

    def observe_rollback(root):
        if state["opened"] and state["disposed_before_rollback"] is None:
            state["disposed_before_rollback"] = state["disposed"]
        return real_recover(root)

    monkeypatch.setattr(backups, "open_database", tracked_open)
    monkeypatch.setattr(backups, "durable_json", fail_commit)
    monkeypatch.setattr(backups, "recover_interrupted_restore", observe_rollback)
    response = api_client.post(
        "/api/backup/restore", json={"token": token, "confirm": True, "mode": "replace"}
    )
    assert response.status_code == 500, response.text
    assert state["disposed_before_rollback"] is True
    assert api_client.get(f"/api/courses/{course['id']}").json()["name"] == "Current state survives"


@pytest.mark.parametrize("damage", ["missing_table", "missing_column"])
def test_head_stamped_backup_with_incomplete_schema_is_rejected_before_restore(
    api_client, course, tmp_path, damage
):
    original = api_client.post("/api/backup")
    assert original.status_code == 200
    extracted = tmp_path / "damaged-backup"
    extracted.mkdir()
    with zipfile.ZipFile(io.BytesIO(original.content)) as archive:
        # Generated application archive only; no untrusted test input is extracted here.
        archive.extractall(extracted)
    connection = sqlite3.connect(extracted / "application.sqlite3")
    try:
        if damage == "missing_table":
            connection.execute("DROP TABLE source_corrections")
        else:
            connection.execute("ALTER TABLE cards RENAME COLUMN question TO missing_question")
        connection.commit()
    finally:
        connection.close()
    damaged = io.BytesIO()
    with zipfile.ZipFile(damaged, "w") as archive:
        for path in extracted.rglob("*"):
            if path.is_file() and path.name != "backup-manifest.json":
                archive.write(path, path.relative_to(extracted).as_posix())
    response = api_client.post(
        "/api/backup/validate", files={"file": ("incomplete.zip", damaged.getvalue())}
    )
    assert response.status_code == 400, response.text
    assert api_client.get(f"/api/courses/{course['id']}").json()["name"] == course["name"]


def test_backup_refuses_top_level_managed_symlink(api_client, tmp_path):
    rt = api_client.app.state.runtime
    outside = tmp_path / "outside-private-data"
    outside.mkdir()
    marker = b"Outside the application; must never enter its backup"
    (outside / "unrelated-secret.txt").write_bytes(marker)
    (rt.data_root / "artifacts").symlink_to(outside, target_is_directory=True)
    response = api_client.post("/api/backup")
    assert response.status_code == 400, response.text if response.status_code != 200 else ""
    assert marker not in response.content


def test_backup_missing_extracted_region_media_is_rejected(api_client, extracted_source):
    rt = api_client.app.state.runtime
    document_id = extracted_source["document"]["id"]
    with rt.sessions() as session:
        document = session.get(Document, document_id)
        region = document.extraction["pages"][0]["regions"][0]
        omitted = f"{document.extraction['artifact_dir']}/{region['image_path']}"
    original = api_client.post("/api/backup")
    assert original.status_code == 200, original.text
    changed = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original.content)) as source,
        zipfile.ZipFile(changed, "w") as destination,
    ):
        assert omitted in source.namelist()
        for name in source.namelist():
            if name == omitted:
                continue
            content = source.read(name)
            if name == "backup-manifest.json":
                manifest = json.loads(content)
                del manifest["files"][omitted]
                content = json.dumps(manifest).encode()
            destination.writestr(name, content)
    response = api_client.post(
        "/api/backup/validate", files={"file": ("missing-media.zip", changed.getvalue())}
    )
    assert response.status_code == 400, response.text
    assert api_client.get(f"/api/documents/{document_id}/regions/{region['id']}").status_code == 200


def test_second_instance_cannot_recover_before_obtaining_process_ownership(api_client, monkeypatch):
    rt = api_client.app.state.runtime
    owner = InstanceLock(rt.data_root)
    owner.acquire()
    entered_recovery = []
    real_recovery = backups.recover_interrupted_restore

    def observe_recovery(root):
        entered_recovery.append(root)
        return real_recovery(root)

    monkeypatch.setattr(backups, "recover_interrupted_restore", observe_recovery)
    try:
        with pytest.raises(RuntimeError, match="Another application instance"):
            with TestClient(create_app(rt.data_root, start_worker=True)):
                pass
        assert entered_recovery == []
    finally:
        owner.release()


def test_legacy_0001_backup_migrates_preserving_human_history_and_pauses_queued_job(
    api_client, tmp_path
):
    legacy_root = tmp_path / "legacy-0001"
    sessions = open_database(legacy_root, migrate=False)
    engine = sessions.kw["bind"]
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
    source = b"Synthetic legacy source: every polynomial is continuous on the real numbers."
    storage_path, source_hash = store_bytes(legacy_root, source, ".txt")
    with sessions.begin() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        assert not session.scalar(
            text("SELECT 1 FROM sqlite_master WHERE name='source_corrections'")
        )
        course = Course(name="Legacy analysis", deck_name="Legacy::Analysis")
        session.add(course)
        session.flush()
        document = Document(
            course_id=course.id,
            filename="legacy.txt",
            relative_path="legacy.txt",
            sha256=source_hash,
            size_bytes=len(source),
            mime_type="text/plain",
            storage_path=storage_path,
            status="complete",
        )
        session.add(document)
        session.flush()
        session.add(
            Page(
                document_id=document.id,
                page_number=1,
                width=612,
                height=792,
                text=source.decode(),
            )
        )
        reference = {"document_id": document.id, "page_number": 1, "quote": "continuous"}
        card = Card(
            course_id=course.id,
            question="Where is a real polynomial continuous?",
            answer="At every real number.",
            explanation="A preserved human explanation.",
            sources=[reference],
            tags=["legacy", "human-edited"],
            revision_number=2,
            manually_edited=True,
            review_status="approved",
        )
        session.add(card)
        session.flush()
        for number, question in [
            (1, "Where is a polynomial continuous?"),
            (2, card.question),
        ]:
            session.add(
                Revision(
                    card_id=card.id,
                    revision_number=number,
                    origin="human" if number == 2 else "manual_create",
                    instruction="Synthetic legacy human-edit history",
                    snapshot={
                        "id": card.id,
                        "question": question,
                        "answer": card.answer,
                        "note_guid": card.note_guid,
                        "sources": card.sources,
                    },
                )
            )
        rationale = "Synthetic legacy approval path; not a real human quality rating."
        session.add(
            ReviewDecision(
                card_id=card.id,
                revision_number=2,
                decision="approved",
                reason=rationale,
            )
        )
        # Reflect the genuinely old table: today's Run includes later columns.
        legacy_runs = Table("runs", MetaData(), autoload_with=session.get_bind())
        legacy_run_id = new_id()
        session.execute(
            legacy_runs.insert().values(
                id=legacy_run_id,
                course_id=course.id,
                mode="generate",
                status="queued",
                current_stage="queued",
                config={"consent": True},
                inputs=[],
                checkpoints={},
                metrics={},
                warnings=[],
                progress={},
                usage={},
                request={},
                pause_requested=False,
                cancel_requested=False,
                created_at=now(),
                updated_at=now(),
            )
        )
        course_id, document_id, card_id, guid, run_id = (
            course.id,
            document.id,
            card.id,
            card.note_guid,
            legacy_run_id,
        )
    engine.dispose()
    snapshot = tmp_path / "legacy-snapshot.sqlite3"
    source_connection = sqlite3.connect(legacy_root / "application.sqlite3")
    target_connection = sqlite3.connect(snapshot)
    try:
        source_connection.backup(target_connection)
    finally:
        source_connection.close()
        target_connection.close()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.write(snapshot, "application.sqlite3")
        package.write(legacy_root / storage_path, storage_path)
    checked = api_client.post(
        "/api/backup/validate", files={"file": ("legacy-0001.zip", archive.getvalue())}
    )
    assert checked.status_code == 200, checked.text
    validation = checked.json()
    assert validation["summary"]["schema_version"] == "0001"
    assert validation["version_compatible"]
    assert any("Legacy backup" in warning for warning in validation["warnings"])
    restored = api_client.post(
        "/api/backup/restore",
        json={"token": validation["token"], "confirm": True, "mode": "clean"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["jobs_paused"]
    recovered = api_client.get(f"/api/cards/{card_id}").json()
    assert recovered["note_guid"] == guid
    assert recovered["revision_number"] == 2 and recovered["manually_edited"]
    assert recovered["review_status"] == "approved"
    assert recovered["explanation"] == "A preserved human explanation."
    assert recovered["tags"] == ["legacy", "human-edited"]
    revisions = api_client.get(f"/api/cards/{card_id}/revisions").json()
    assert len(revisions) == 2
    assert {revision["snapshot"]["question"] for revision in revisions} == {
        "Where is a polynomial continuous?",
        "Where is a real polynomial continuous?",
    }
    assert api_client.get(f"/api/documents/{document_id}/source").content == source
    assert api_client.get(f"/api/courses/{course_id}").json()["name"] == "Legacy analysis"
    rt = api_client.app.state.runtime
    with rt.sessions() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == (
            ScriptDirectory.from_config(migration_config()).get_current_head()
        )
        decision = session.scalar(select(ReviewDecision).where(ReviewDecision.card_id == card_id))
        assert decision.reason == rationale and decision.revision_number == 2
        paused = session.get(Run, run_id)
        assert paused.status == "paused"
        assert not paused.pause_requested and not paused.cancel_requested
        assert "explicitly resume" in paused.error
        assert session.scalar(text("SELECT COUNT(*) FROM source_corrections")) == 0
        assert session.scalar(text("SELECT COUNT(*) FROM evaluation_datasets")) == 0
