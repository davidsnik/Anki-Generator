"""Real SQLite/archive round trips, overwrite recovery and hostile-input rejection."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from anki_generator.api.app import create_app
from anki_generator.services.backups import durable_json, recover_interrupted_restore


@pytest.mark.parametrize("field", ["document", "export", "artifact"])
def test_backup_rejects_references_into_other_owned_namespaces(
    api_client, course, source_document, tmp_path, field
):
    import sqlite3

    from anki_generator.database.entities import Document, ExportRecord

    rt = api_client.app.state.runtime
    with rt.sessions.begin() as session:
        if field == "document":
            session.get(Document, source_document["id"]).storage_path = "application.sqlite3"
        elif field == "artifact":
            session.get(Document, source_document["id"]).extraction = {
                "artifact_dir": "originals/incorrect"
            }
        else:
            session.add(
                ExportRecord(
                    course_id=course["id"],
                    format="json",
                    deck_name="Unsafe",
                    card_ids=[],
                    card_count=0,
                    storage_path="application.sqlite3",
                    sha256="0" * 64,
                )
            )
    snapshot = tmp_path / "forged.sqlite3"
    with sqlite3.connect(rt.data_root / "application.sqlite3") as source:
        with sqlite3.connect(snapshot) as target:
            source.backup(target)
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.write(snapshot, "application.sqlite3")
    response = api_client.post(
        "/api/backup/validate", files={"file": ("forged.zip", content.getvalue())}
    )
    assert response.status_code == 400, response.text
    assert "namespace" in response.json()["detail"]
    assert api_client.get("/api/health").status_code == 200


def validate(client, archive):
    response = client.post(
        "/api/backup/validate", files={"file": ("backup.zip", archive, "application/zip")}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_backup_restore_preserves_sources_corrections_revisions_labels_and_guids(
    api_client, course, extracted_source, tmp_path
):
    document = extracted_source["document"]
    corrected = api_client.post(
        f"/api/documents/{document['id']}/corrections",
        json={
            "page_number": 1,
            "text": "For all real x, the function x squared is continuous.",
            "verified": True,
            "reason": "Synthetic fixture test of a human input path",
        },
    )
    assert corrected.status_code == 201, corrected.text
    card = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "Q \\(x^2\\)",
            "answer": "A",
            "sources": [{"document_id": document["id"], "page_number": 1, "quote": "continuous"}],
        },
    ).json()
    api_client.patch(
        f"/api/cards/{card['id']}",
        json={
            "explanation": "Preserved explanation",
            "tags": ["backup-test"],
            "expected_revision": 1,
        },
    )
    api_client.post(
        f"/api/cards/{card['id']}/review",
        json={"decision": "approved", "reason": "Controlled backup test rationale"},
    )
    dataset = api_client.post(
        "/api/evaluations/datasets",
        json={
            "name": "Synthetic benchmark",
            "provenance": "synthetic",
            "course_id": course["id"],
            "reference_concepts": [{"id": "continuity", "label": "Continuity"}],
        },
    ).json()
    secret = "sk-synthetic-restore-test-never-a-real-provider-key"
    api_client.app.state.runtime.secrets.set(secret)
    archive = api_client.post("/api/backup")
    assert archive.status_code == 200, archive.text
    with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
        assert "backup-manifest.json" in package.namelist()
        assert not any(secret.encode() in package.read(name) for name in package.namelist())
    with TestClient(create_app(tmp_path / "restored", start_worker=False)) as restored:
        restored.headers["X-CSRF-Token"] = restored.get("/api/bootstrap").json()["csrf_token"]
        checked = validate(restored, archive.content)
        assert checked["summary"]["cards"] == 1
        assert checked["version_compatible"] and checked["summary"]["includes_originals"]
        assert (
            restored.post(
                "/api/backup/restore", json={"token": checked["token"], "confirm": False}
            ).status_code
            == 400
        )
        result = restored.post(
            "/api/backup/restore",
            json={"token": checked["token"], "confirm": True, "mode": "clean"},
        )
        assert result.status_code == 200, result.text
        recovered = restored.get(f"/api/cards/{card['id']}").json()
        assert recovered["note_guid"] == card["note_guid"]
        assert recovered["revision_number"] == 2 and recovered["review_status"] == "approved"
        assert recovered["tags"] == ["backup-test"]
        assert len(restored.get(f"/api/cards/{card['id']}/revisions").json()) == 2
        interpretation = restored.get(f"/api/documents/{document['id']}/interpretation").json()
        assert interpretation["corrections"][0]["text"] == corrected.json()["text"]
        assert (
            restored.get(f"/api/documents/{document['id']}/source").content
            == api_client.get(f"/api/documents/{document['id']}/source").content
        )
        assert (
            restored.get(f"/api/evaluations/datasets/{dataset['id']}").json()["reference_concepts"][
                0
            ]["id"]
            == "continuity"
        )
        assert not restored.get("/api/bootstrap").json()["key_status"]["configured"]


def test_replacement_requires_confirmation_and_produces_downloadable_recovery(api_client, course):
    archive = api_client.post("/api/backup").content
    checked = validate(api_client, archive)
    api_client.patch(
        f"/api/courses/{course['id']}", json={"name": "Current unsaved-in-backup name"}
    )
    assert (
        api_client.post(
            "/api/backup/restore",
            json={"token": checked["token"], "confirm": True, "mode": "clean"},
        ).status_code
        == 400
    )
    result = api_client.post(
        "/api/backup/restore", json={"token": checked["token"], "confirm": True, "mode": "replace"}
    )
    assert result.status_code == 200, result.text
    assert api_client.get(f"/api/courses/{course['id']}").json()["name"] == course["name"]
    recovery = api_client.get(result.json()["recovery_backup"])
    assert recovery.status_code == 200
    recovered_validation = validate(api_client, recovery.content)
    assert recovered_validation["summary"]["courses"] == 1


@pytest.mark.parametrize(
    "name", ["../outside.txt", "/absolute", "originals/../../outside.txt", ".env"]
)
def test_restore_rejects_traversal_and_unowned_files_without_changing_live_data(
    api_client, course, name
):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, "untrusted")
    response = api_client.post(
        "/api/backup/validate", files={"file": ("bad.zip", stream.getvalue())}
    )
    assert response.status_code == 400
    assert api_client.get(f"/api/courses/{course['id']}").json()["name"] == course["name"]


def test_restore_rejects_manifest_tampering(api_client, course):
    original = api_client.post("/api/backup").content
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(changed, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "backup-manifest.json":
                manifest = json.loads(content)
                manifest["files"]["application.sqlite3"]["sha256"] = "0" * 64
                content = json.dumps(manifest).encode()
            target.writestr(name, content)
    response = api_client.post(
        "/api/backup/validate", files={"file": ("tampered.zip", changed.getvalue())}
    )
    assert response.status_code == 400 and "checksum" in response.text


def test_interrupted_swap_rolls_back_before_application_opens_database(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    previous, staging = root / ".restore-previous-example", root / ".restore-staging-example"
    previous.mkdir()
    staging.mkdir()
    (previous / "application.sqlite3").write_bytes(b"old persistent identity database")
    (root / "application.sqlite3").write_bytes(b"new partially installed database")
    (root / "artifacts").mkdir()
    durable_json(
        root / ".restore-journal.json",
        {
            "phase": "swapping",
            "previous": previous.name,
            "staging": staging.name,
            "existing": ["application.sqlite3"],
            "incoming": ["application.sqlite3", "artifacts"],
        },
    )
    recover_interrupted_restore(root)
    assert (root / "application.sqlite3").read_bytes() == b"old persistent identity database"
    assert not (root / "artifacts").exists() and not previous.exists() and not staging.exists()


def test_failed_swap_recovers_current_workspace_and_service_remains_usable(
    api_client, course, monkeypatch
):
    from anki_generator.services import backups

    archive = api_client.post("/api/backup").content
    checked = validate(api_client, archive)
    api_client.patch(f"/api/courses/{course['id']}", json={"name": "Keep this current workspace"})
    real_open = backups.open_database
    calls = 0

    def fail_first(root, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("Synthetic failure after files move")
        return real_open(root, **kwargs)

    monkeypatch.setattr(backups, "open_database", fail_first)
    response = api_client.post(
        "/api/backup/restore", json={"token": checked["token"], "confirm": True, "mode": "replace"}
    )
    assert response.status_code == 500
    assert (
        api_client.get(f"/api/courses/{course['id']}").json()["name"]
        == "Keep this current workspace"
    )
    assert api_client.get("/api/health").status_code == 200


def test_committed_restore_cleanup_failure_keeps_new_state_and_live_worker(
    api_client, course, monkeypatch
):
    from anki_generator.services import backups

    rt = api_client.app.state.runtime
    original = api_client.post("/api/backup")
    checked = api_client.post(
        "/api/backup/validate", files={"file": ("backup.zip", original.content)}
    )
    assert checked.status_code == 200, checked.text
    api_client.patch(f"/api/courses/{course['id']}", json={"name": "Later state"})
    original_recovery = backups.recover_interrupted_restore

    def fail_cleanup(root):
        journal = json.loads((root / ".restore-journal.json").read_text())
        if journal["phase"] == "committed":
            raise OSError("Synthetic post-commit cleanup failure")
        return original_recovery(root)

    monkeypatch.setattr(backups, "recover_interrupted_restore", fail_cleanup)
    rt.runner.start()
    try:
        response = api_client.post(
            "/api/backup/restore",
            json={"token": checked.json()["token"], "confirm": True, "mode": "replace"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["cleanup_pending"] is True
        assert api_client.get(f"/api/courses/{course['id']}").json()["name"] == course["name"]
        assert rt.runner._thread and rt.runner._thread.is_alive()
        assert (rt.data_root / ".restore-journal.json").is_file()
    finally:
        rt.runner.stop()
        original_recovery(rt.data_root)
