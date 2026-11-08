"""HTTP contracts, persistence, local extraction, and local-application boundaries."""

from __future__ import annotations

import io
import json
import sqlite3
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from anki_generator.database.entities import ApplicationSetting, Card, Document, Run
from anki_generator.services import storage


def zip_bytes(members: list[tuple[str | ZipInfo, bytes]]) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return stream.getvalue()


def upload(api_client: TestClient, course: dict, name: str, data: bytes, **form):
    return api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", (name, data, "application/octet-stream"))],
        data=form,
    )


def test_bootstrap_exposes_session_and_useful_diagnostics_without_secrets(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/bootstrap")
    assert response.status_code == 200
    result = response.json()
    assert len(result["csrf_token"]) >= 32
    assert result["courses"] == result["recent_runs"] == []
    assert not result["key_status"]["configured"]
    assert result["diagnostics"]["database"] == "SQLite / Alembic"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_write_requires_valid_session_token(api_client: TestClient) -> None:
    for token in ("", "forged-token"):
        response = api_client.post(
            "/api/courses", json={"name": "Unsafe"}, headers={"X-CSRF-Token": token}
        )
        assert response.status_code == 403
    assert api_client.get("/api/courses").json() == []


def test_non_ascii_session_token_is_rejected_without_server_exception(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/courses", json={"name": "Unsafe"}, headers=[(b"x-csrf-token", b"\xff")]
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.invalid"},
        {"Host": "attacker.invalid"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_host_origin_and_fetch_site_prevent_cross_site_access(
    api_client: TestClient, headers: dict
) -> None:
    response = api_client.get("/api/bootstrap", headers=headers)
    assert response.status_code == 403
    assert "csrf_token" not in response.text


def test_same_origin_and_explicit_dev_origin_work(api_client: TestClient) -> None:
    for origin in ("http://testserver", "http://localhost:5173", "http://127.0.0.1:5173"):
        response = api_client.post(
            "/api/courses", json={"name": "Allowed"}, headers={"Origin": origin}
        )
        assert response.status_code == 201, response.text


def test_invalid_and_oversized_content_length_are_rejected_before_body(
    api_client: TestClient,
) -> None:
    for length, expected in [("invalid", 400), (str(523 * 1024 * 1024), 413)]:
        response = api_client.post(
            "/api/courses", json={"name": "Too large"}, headers={"Content-Length": length}
        )
        assert response.status_code == expected


def test_course_crud_archive_persists_and_cascades_documents(
    api_client: TestClient,
    course: dict,
    source_document: dict,
) -> None:
    identifier = course["id"]
    updated = api_client.patch(
        f"/api/courses/{identifier}",
        json={
            "name": "Real analysis",
            "description": "Exam preparation",
            "language": "Dutch",
            "archived": True,
            "criteria": {"coverage": "focused", "methods_emphasis": 2},
        },
    )
    assert updated.status_code == 200, updated.text
    result = api_client.get(f"/api/courses/{identifier}").json()
    assert result["name"] == "Real analysis" and result["archived"]
    assert result["language"] == "Dutch" and result["criteria"]["methods_emphasis"] == 2
    assert result["stats"]["documents"] == 1
    assert (
        api_client.patch(f"/api/courses/{identifier}", json={"archived": False}).status_code == 200
    )
    assert api_client.delete(f"/api/courses/{identifier}").json() == {"deleted": True}
    assert api_client.get(f"/api/documents/{source_document['id']}/source").status_code == 404
    assert api_client.get("/api/courses").json() == []


@pytest.mark.parametrize("payload", [{"name": " "}, {"name": "Course", "unknown": True}])
def test_invalid_course_inputs_fail(api_client: TestClient, payload: dict) -> None:
    assert api_client.post("/api/courses", json=payload).status_code in {400, 422}


def test_batch_upload_preserves_paths_roles_and_originals(
    api_client: TestClient, course: dict
) -> None:
    result = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[
            ("files", ("first.txt", b"A theorem", "text/plain")),
            ("files", ("second.md", b"# An exercise", "text/markdown")),
        ],
        data={
            "paths": json.dumps(["lectures/first.txt", "tutorial/second.md"]),
            "category": "exercises",
            "authority": "student",
        },
    )
    assert result.status_code == 201, result.text
    documents = result.json()["documents"]
    assert [d["relative_path"] for d in documents] == ["lectures/first.txt", "tutorial/second.md"]
    assert all(d["category"] == "exercises" and d["authority"] == "student" for d in documents)
    assert all("storage_path" not in d for d in documents)
    assert api_client.get(documents[0]["source_url"]).content == b"A theorem"


def test_zip_upload_preserves_nested_supported_entries_and_reports_skips(
    api_client: TestClient, course: dict
) -> None:
    archive = zip_bytes(
        [
            ("lecture/notes.md", b"A definition"),
            ("work/exercise.tex", b"x=1"),
            ("readme.exe", b"unsupported"),
        ]
    )
    response = upload(api_client, course, "materials.zip", archive, category="reference")
    assert response.status_code == 201, response.text
    assert {d["relative_path"] for d in response.json()["documents"]} == {
        "lecture/notes.md",
        "work/exercise.tex",
    }
    assert any("readme.exe" in w for w in response.json()["warnings"])


@pytest.mark.parametrize(
    "name", ["../escape.txt", "/absolute.txt", "C:/escape.txt", "a\\escape.txt"]
)
def test_upload_and_zip_traversal_are_rejected(
    api_client: TestClient, course: dict, name: str
) -> None:
    response = upload(api_client, course, "safe.txt", b"source", paths=json.dumps([name]))
    assert response.status_code == 400
    archive = zip_bytes([(name, b"source")])
    assert upload(api_client, course, "bad.zip", archive).status_code == 400
    assert api_client.get(f"/api/courses/{course['id']}/documents").json() == []


def test_zip_symlink_and_duplicate_paths_are_rejected(api_client: TestClient, course: dict) -> None:
    link = ZipInfo("link.txt")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    assert (
        upload(api_client, course, "links.zip", zip_bytes([(link, b"../../target")])).status_code
        == 400
    )
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = zip_bytes([("same.txt", b"first"), ("same.txt", b"second")])
    assert upload(api_client, course, "duplicate.zip", duplicate).status_code == 400


def test_upload_limits_and_path_metadata_are_validated(
    api_client: TestClient,
    course: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("anki_generator.api.documents.MAX_UPLOAD_BYTES", 10)
    assert upload(api_client, course, "large.txt", b"x" * 11).status_code == 400
    assert upload(api_client, course, "safe.txt", b"source", paths="{}").status_code == 400
    assert upload(api_client, course, "safe.txt", b"source", paths="not-json").status_code == 400
    assert upload(api_client, course, "safe.exe", b"source").status_code == 400
    assert (
        upload(api_client, course, "safe.txt", b"source", authority="untrusted-value").status_code
        == 400
    )
    assert (
        upload(api_client, course, "safe.txt", b"source", category="not-a-category").status_code
        == 422
    )


def test_zip_expansion_and_member_limits_are_enforced(
    api_client: TestClient,
    course: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 10)
    assert (
        upload(api_client, course, "large.zip", zip_bytes([("large.txt", b"x" * 11)])).status_code
        == 400
    )
    monkeypatch.setattr(storage, "MAX_ZIP_MEMBERS", 1)
    archive = zip_bytes([("first.txt", b"one"), ("second.txt", b"two")])
    assert upload(api_client, course, "many.zip", archive).status_code == 400


def test_repeated_upload_is_idempotent_and_conflicting_content_does_not_replace_original(
    api_client: TestClient,
    course: dict,
    source_document: dict,
) -> None:
    original = api_client.get(source_document["source_url"]).content
    repeated = upload(api_client, course, "lecture.txt", original)
    assert repeated.status_code == 201
    assert repeated.json()["documents"][0]["id"] == source_document["id"]
    assert repeated.json()["warnings"]
    conflict = upload(api_client, course, "lecture.txt", b"different revision")
    assert conflict.status_code == 400
    assert api_client.get(source_document["source_url"]).content == original
    assert len(api_client.get(f"/api/courses/{course['id']}/documents").json()) == 1


def test_document_roles_authority_links_rename_and_reprocess(
    api_client: TestClient,
    course: dict,
    source_document: dict,
) -> None:
    solution = upload(
        api_client, course, "solution.txt", b"Worked reasoning", category="solutions"
    ).json()["documents"][0]
    response = api_client.patch(
        f"/api/documents/{source_document['id']}",
        json={
            "filename": "exercise.txt",
            "category": "exercises",
            "authority": "official",
            "linked_document_id": solution["id"],
            "reprocess": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["linked_document_id"] == solution["id"]
    assert response.json()["status"] == "imported"
    assert response.json()["relative_path"] == "lecture.txt"
    for payload in (
        {"filename": "../unsafe.txt"},
        {"filename": "changed.pdf"},
        {"linked_document_id": source_document["id"]},
    ):
        assert (
            api_client.patch(f"/api/documents/{source_document['id']}", json=payload).status_code
            == 400
        )
    other = api_client.post("/api/courses", json={"name": "Other"}).json()
    other_doc = upload(api_client, other, "other.txt", b"Source").json()["documents"][0]
    assert (
        api_client.patch(
            f"/api/documents/{source_document['id']}", json={"linked_document_id": other_doc["id"]}
        ).status_code
        == 400
    )
    assert (
        api_client.patch(
            f"/api/documents/{source_document['id']}", json={"linked_document_id": None}
        ).json()["linked_document_id"]
        is None
    )


def test_local_extraction_run_persists_real_pages_and_source_pngs(
    api_client: TestClient,
    extracted_source: dict,
) -> None:
    page = extracted_source["pages"][0]
    assert "function is continuous" in page["text"]
    assert page["page_number"] == 1
    response = api_client.get(page["regions"][0]["image_url"])
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (page["regions"][0]["pixel_width"], page["regions"][0]["pixel_height"])
    assert extracted_source["run"]["stages"]
    identifier = extracted_source["document"]["id"]
    assert api_client.get(f"/api/documents/{identifier}/regions/unknown").status_code == 404


def test_original_html_like_text_is_served_as_inert_plain_text(
    api_client: TestClient, course: dict
) -> None:
    document = upload(api_client, course, "unsafe.md", b"<script>alert(1)</script>").json()[
        "documents"
    ][0]
    response = api_client.get(document["source_url"])
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_manual_card_edit_revision_and_review_history_are_durable(
    api_client: TestClient,
    course: dict,
    extracted_source: dict,
) -> None:
    source = {
        "document_id": extracted_source["document"]["id"],
        "page_number": 1,
        "region_id": extracted_source["pages"][0]["regions"][0]["id"],
        "quote": "f(x) = x squared",
    }
    created = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "What is f?",
            "answer": "The square function",
            "tags": ["definition"],
            "sources": [source],
        },
    )
    assert created.status_code == 201, created.text
    card = created.json()
    assert card["review_status"] == "pending" and card["revision_number"] == 1
    assert card["sources"][0]["document_name"] == "lecture.txt"
    assert (
        api_client.post(
            f"/api/cards/{card['id']}/review", json={"decision": "approved"}
        ).status_code
        == 400
    )
    approved = api_client.post(
        f"/api/cards/{card['id']}/review",
        json={
            "decision": "approved",
            "reason": "Checked the source and assumptions by hand.",
        },
    )
    assert approved.status_code == 200
    edited = api_client.patch(
        f"/api/cards/{card['id']}",
        json={
            "question": "On what domain is the square function continuous?",
            "answer": "All real numbers.",
            "expected_revision": 1,
        },
    )
    assert edited.status_code == 200, edited.text
    current = edited.json()
    assert current["revision_number"] == 2 and current["review_status"] == "pending"
    assert current["verification_status"] == "unverified" and current["issues"]
    assert current["note_guid"] == card["note_guid"]
    assert current["review_history"][0]["revision_number"] == 1
    revisions = api_client.get(f"/api/cards/{card['id']}/revisions").json()
    assert [r["revision_number"] for r in revisions] == [2, 1]
    assert revisions[1]["snapshot"]["question"] == "What is f?"
    conflict = api_client.patch(
        f"/api/cards/{card['id']}", json={"answer": "stale", "expected_revision": 1}
    )
    assert conflict.status_code == 400
    archived = api_client.patch(f"/api/cards/{card['id']}", json={"archived": True}).json()
    assert archived["revision_number"] == 2
    assert api_client.get(f"/api/cards/{card['id']}").json()["archived"] is True
    assert api_client.get(f"/api/courses/{course['id']}").json()["stats"]["cards"] == 0


def test_failed_verification_cannot_be_overridden_by_human_approval(
    api_client: TestClient, course: dict
) -> None:
    card = api_client.post(
        f"/api/courses/{course['id']}/cards", json={"question": "Q", "answer": "A"}
    ).json()
    with api_client.app.state.runtime.sessions.begin() as session:
        session.get(Card, card["id"]).verification_status = "failed"
    response = api_client.post(
        f"/api/cards/{card['id']}/review", json={"decision": "approved", "reason": "Force it"}
    )
    assert response.status_code == 400
    assert api_client.get(f"/api/cards/{card['id']}").json()["review_status"] == "pending"


def test_manual_source_references_reject_missing_pages_regions_and_other_courses(
    api_client: TestClient,
    course: dict,
    extracted_source: dict,
) -> None:
    identifier = extracted_source["document"]["id"]
    route = f"/api/courses/{course['id']}/cards"
    for reference in (
        {"document_id": identifier, "page_number": 99},
        {"document_id": identifier, "page_number": 1, "region_id": "fabricated"},
    ):
        response = api_client.post(
            route, json={"question": "Q", "answer": "A", "sources": [reference]}
        )
        assert response.status_code == 400
    response = api_client.post(
        route,
        json={
            "question": "Q",
            "answer": "A",
            "image_refs": [
                {"document_id": identifier, "page_number": 1},
            ],
        },
    )
    assert response.status_code == 400
    other = api_client.post("/api/courses", json={"name": "Other"}).json()
    response = api_client.post(
        f"/api/courses/{other['id']}/cards",
        json={
            "question": "Q",
            "answer": "A",
            "sources": [{"document_id": identifier, "page_number": 1}],
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize("bbox", [[-1, 0, 10, 10], [0, 0, 100000, 10], [10, 10, 1, 1]])
def test_source_boxes_must_be_within_page_and_ordered(
    api_client: TestClient,
    course: dict,
    extracted_source: dict,
    bbox: list,
) -> None:
    response = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "Q",
            "answer": "A",
            "sources": [
                {
                    "document_id": extracted_source["document"]["id"],
                    "page_number": 1,
                    "bbox": bbox,
                }
            ],
        },
    )
    assert response.status_code in {400, 422}


def test_settings_validate_known_fields_and_preserve_partial_nested_changes(
    api_client: TestClient,
) -> None:
    saved = api_client.patch(
        "/api/settings",
        json={
            "theme": "dark",
            "models": {"generation": "test-model"},
            "criteria": {"methods_emphasis": 2},
        },
    )
    assert saved.status_code == 200
    values = api_client.get("/api/settings").json()
    assert values["models"]["generation"] == "test-model"
    assert values["models"]["factual"]
    assert values["criteria"]["coverage"] == "comprehensive"
    assert values["theme"] == "dark"
    for payload in (
        {"api_key": "must-never-be-settings"},
        {"unexpected": True},
        {"max_revisions": 100},
        {"models": {"generation": "bad model"}},
        {"criteria": {"card_types": []}},
    ):
        assert api_client.patch("/api/settings", json=payload).status_code in {400, 422}
    assert api_client.get("/api/settings").json()["theme"] == "dark"


def test_session_api_key_never_enters_responses_database_or_backup(api_client: TestClient) -> None:
    secret = "sk-test-private-value-only-in-memory"
    response = api_client.put("/api/settings/key", json={"api_key": secret, "persist": True})
    assert response.status_code == 200
    assert response.json()["configured"] and response.json()["storage"] == "session"
    assert not response.json()["persistent_available"]
    assert secret not in response.text
    assert secret not in api_client.get("/api/bootstrap").text
    assert secret not in api_client.get("/api/settings").text
    rt = api_client.app.state.runtime
    with rt.sessions() as session:
        assert all(
            secret not in json.dumps(setting.value)
            for setting in session.scalars(select(ApplicationSetting))
        )
    archive = ZipFile(io.BytesIO(api_client.post("/api/backup").content))
    assert all(secret.encode() not in archive.read(name) for name in archive.namelist())
    assert api_client.delete("/api/settings/key").json()["configured"] is False
    assert rt.secrets.get() is None


def test_invalid_keys_are_rejected_without_becoming_configured(api_client: TestClient) -> None:
    for value in ("", "contains space", "  "):
        assert api_client.put("/api/settings/key", json={"api_key": value}).status_code in {
            400,
            422,
        }
    assert not api_client.get("/api/settings").json()["key_status"]["configured"]


def test_run_consent_keys_controls_and_active_input_guards(
    api_client: TestClient,
    course: dict,
    source_document: dict,
) -> None:
    route = f"/api/courses/{course['id']}/runs"
    assert api_client.post(route, json={"mode": "generate"}).status_code == 400
    assert api_client.post(route, json={"mode": "generate", "consent": True}).status_code == 400
    run = api_client.post(route, json={"mode": "extract"}).json()
    assert run["status"] == "queued"
    assert run["inputs"][0]["category"] == "lecture"
    assert api_client.post(route, json={"mode": "extract"}).status_code == 400
    assert api_client.delete(f"/api/documents/{source_document['id']}").status_code == 400
    assert (
        api_client.patch(
            f"/api/courses/{course['id']}", json={"criteria": {"coverage": "focused"}}
        ).status_code
        == 400
    )
    assert api_client.post(f"/api/runs/{run['id']}/pause").json()["status"] == "paused"
    assert api_client.post(f"/api/runs/{run['id']}/resume").json()["status"] == "queued"
    assert api_client.post(f"/api/runs/{run['id']}/retry").status_code == 400
    assert api_client.post(f"/api/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert api_client.post(f"/api/runs/{run['id']}/resume").status_code == 400
    assert api_client.post(f"/api/runs/{run['id']}/unknown").status_code == 404
    assert api_client.get(f"/api/courses/{course['id']}/runs").json()[0]["status"] == "cancelled"


def test_run_state_persists_in_sqlite_and_retry_requeues_failed_run(
    api_client: TestClient,
    course: dict,
    source_document: dict,
) -> None:
    run = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"}).json()
    with api_client.app.state.runtime.sessions.begin() as session:
        persisted = session.get(Run, run["id"])
        persisted.status, persisted.error = "failed", "A recoverable test failure"
    retried = api_client.post(f"/api/runs/{run['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued" and retried.json()["error"] is None


def test_backup_contains_consistent_database_originals_and_migration_version(
    api_client: TestClient,
    course: dict,
    source_document: dict,
    tmp_path: Path,
) -> None:
    response = api_client.post("/api/backup")
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert "application.sqlite3" in archive.namelist()
        assert any(name.startswith("originals/") for name in archive.namelist())
        assert not any(name.endswith(("-wal", "-shm")) for name in archive.namelist())
        database = tmp_path / "restored.sqlite3"
        database.write_bytes(archive.read("application.sqlite3"))
    with sqlite3.connect(database) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            restored.execute("SELECT name FROM courses WHERE id=?", (course["id"],)).fetchone()[0]
            == "Analysis"
        )
        assert restored.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert restored.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001"


def test_stored_path_tampering_cannot_read_outside_application(
    api_client: TestClient,
    source_document: dict,
    tmp_path: Path,
) -> None:
    private = tmp_path / "outside.txt"
    private.write_text("private sentinel")
    with api_client.app.state.runtime.sessions.begin() as session:
        session.get(Document, source_document["id"]).storage_path = "../outside.txt"
    response = api_client.get(source_document["source_url"])
    assert response.status_code == 400
    assert "private sentinel" not in response.text


def test_secure_keyring_persistence_replacement_and_removal_never_echo_keys(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring

    from anki_generator.services.settings import SecretStore

    class SecureBackend:
        priority = 1
        value = None

        def get_password(self, service, username):
            return self.value

        def set_password(self, service, username, value):
            self.value = value

        def delete_password(self, service, username):
            self.value = None

    SecureBackend.__module__ = "keyring.backends.SecretService"
    backend = SecureBackend()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    rt = api_client.app.state.runtime
    rt.secrets = SecretStore()
    private = "sk-test-fake-secure-keyring-value"
    response = api_client.put("/api/settings/key", json={"api_key": private, "persist": True})
    assert response.status_code == 200
    assert response.json()["storage"] == "keyring" and response.json()["persistent_available"]
    assert private not in response.text and private not in api_client.get("/api/bootstrap").text
    assert backend.value == private
    session_key = "sk-test-replaced-with-session-only"
    response = api_client.put("/api/settings/key", json={"api_key": session_key, "persist": False})
    assert response.json()["storage"] == "session"
    assert backend.value is None and rt.secrets.get() == session_key
    assert api_client.delete("/api/settings/key").json()["configured"] is False
    assert rt.secrets.get() is None and backend.value is None


def test_unknown_settings_cannot_echo_accidentally_submitted_secret(api_client: TestClient) -> None:
    secret = "sk-accidentally-sent-to-settings-not-key-endpoint"
    response = api_client.patch("/api/settings", json={"api_key": secret})
    assert response.status_code in {400, 422}
    assert secret not in response.text


def test_deleting_source_invalidates_dependent_card_and_blocks_reapproval_and_export(
    api_client: TestClient,
    course: dict,
    extracted_source: dict,
) -> None:
    source = {"document_id": extracted_source["document"]["id"], "page_number": 1}
    card = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "What is the source function?",
            "answer": "The square function.",
            "sources": [source],
        },
    ).json()
    api_client.post(
        f"/api/cards/{card['id']}/review",
        json={"decision": "approved", "reason": "Checked original."},
    )
    assert api_client.delete(f"/api/documents/{source['document_id']}").status_code == 200
    invalid = api_client.get(f"/api/cards/{card['id']}").json()
    assert invalid["verification_status"] == "failed" and invalid["review_status"] == "pending"
    assert any("source" in str(issue).lower() for issue in invalid["issues"])
    assert (
        api_client.post(
            f"/api/cards/{card['id']}/review",
            json={
                "decision": "approved",
                "reason": "Try overriding missing evidence.",
            },
        ).status_code
        == 400
    )
    assert (
        api_client.post(
            f"/api/courses/{course['id']}/exports",
            json={
                "format": "apkg",
                "card_ids": [card["id"]],
            },
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "Application/JSON",
        "application/vendor+json",
        None,
    ],
)
def test_streamed_json_body_is_bounded_without_content_length(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    content_type: str | None,
) -> None:
    monkeypatch.setattr("anki_generator.api.security.MAX_JSON_BYTES", 64)
    chunks = iter([b'{"name":"', b"x" * 100, b'"}'])
    request = api_client.build_request(
        "POST",
        "/api/courses",
        content=chunks,
        headers={"Content-Type": content_type} if content_type else {},
    )
    assert "Content-Length" not in request.headers
    response = api_client.send(request)
    assert response.status_code == 413, response.text
    assert api_client.get("/api/courses").json() == []


def test_streamed_multipart_upload_is_bounded_before_parsing_or_storage(
    api_client: TestClient,
    course: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("anki_generator.api.security.MAX_REQUEST_BYTES", 256)
    body = (
        b'--test-boundary\r\nContent-Disposition: form-data; name="files"; filename="large.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\n" + b"x" * 1000 + b"\r\n--test-boundary--\r\n"
    )
    request = api_client.build_request(
        "POST",
        f"/api/courses/{course['id']}/documents",
        content=iter([body[:100], body[100:]]),
        headers={"Content-Type": "multipart/form-data; boundary=test-boundary"},
    )
    assert "Content-Length" not in request.headers
    response = api_client.send(request)
    assert response.status_code == 413, response.text
    assert api_client.get(f"/api/courses/{course['id']}/documents").json() == []
    assert not list((api_client.app.state.runtime.data_root / "originals").glob("*"))


def test_reprocess_forces_local_extraction_but_unchanged_runs_reuse_artifact(
    api_client: TestClient,
    course: dict,
    extracted_source: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from anki_generator.ingestion import extraction

    calls = []
    original = extraction.extract_document_safely

    def observed(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(extraction, "extract_document_safely", observed)

    def extract_again():
        response = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"})
        assert response.status_code == 202
        api_client.app.state.runtime.runner.run_now(response.json()["id"])
        run = api_client.get(f"/api/runs/{response.json()['id']}").json()
        assert run["status"] == "completed", run.get("error")

    extract_again()
    assert not calls
    identifier = extracted_source["document"]["id"]
    assert (
        api_client.patch(f"/api/documents/{identifier}", json={"reprocess": True}).status_code
        == 200
    )
    extract_again()
    assert len(calls) == 1


def test_global_generation_defaults_are_copied_into_new_courses_and_explicit_choices_win(
    api_client: TestClient,
) -> None:
    saved = api_client.patch(
        "/api/settings",
        json={
            "criteria": {
                "coverage": "focused",
                "methods_emphasis": 2.5,
                "include_diagrams": False,
                "instructions": "Prioritize reusable exercise strategies.",
            }
        },
    )
    assert saved.status_code == 200
    inherited = api_client.post("/api/courses", json={"name": "Inherited defaults"}).json()
    assert inherited["criteria"]["coverage"] == "focused"
    assert inherited["criteria"]["methods_emphasis"] == 2.5
    assert inherited["criteria"]["include_diagrams"] is False
    explicit = api_client.post(
        "/api/courses",
        json={
            "name": "Explicit preferences",
            "criteria": {
                "coverage": "comprehensive",
                "methods_emphasis": 0.5,
            },
        },
    ).json()
    assert explicit["criteria"]["coverage"] == "comprehensive"
    assert explicit["criteria"]["methods_emphasis"] == 0.5
    assert explicit["criteria"]["include_diagrams"] is True
    api_client.patch("/api/settings", json={"criteria": {"methods_emphasis": 1}})
    # A later global preference change does not overwrite a course's saved choices.
    assert (
        api_client.get(f"/api/courses/{inherited['id']}").json()["criteria"]["methods_emphasis"]
        == 2.5
    )


def test_deleting_document_removes_private_original_and_rendered_previews(
    api_client: TestClient,
    extracted_source: dict,
) -> None:
    rt = api_client.app.state.runtime
    identifier = extracted_source["document"]["id"]
    with rt.sessions() as session:
        document = session.get(Document, identifier)
        original_path = rt.data_root / document.storage_path
        artifact_directory = rt.data_root / document.extraction["artifact_dir"]
    image_url = extracted_source["pages"][0]["regions"][0]["image_url"]
    assert original_path.is_file() and artifact_directory.is_dir()
    assert any(artifact_directory.rglob("*.png"))
    response = api_client.delete(f"/api/documents/{identifier}")
    assert response.status_code == 200
    assert not original_path.exists()
    assert not (rt.data_root / "artifacts" / identifier).exists()
    assert api_client.get(image_url).status_code == 404
    assert api_client.get(extracted_source["document"]["source_url"]).status_code == 404


def test_shared_original_is_retained_until_last_course_document_is_removed(
    api_client: TestClient,
    course: dict,
    source_document: dict,
) -> None:
    content = api_client.get(source_document["source_url"]).content
    other = api_client.post("/api/courses", json={"name": "Shared source course"}).json()
    shared = upload(api_client, other, "shared-lecture.txt", content).json()["documents"][0]
    rt = api_client.app.state.runtime
    with rt.sessions() as session:
        first = session.get(Document, source_document["id"])
        second = session.get(Document, shared["id"])
        assert first.storage_path == second.storage_path
        original_path = rt.data_root / first.storage_path
    assert api_client.delete(f"/api/courses/{course['id']}").status_code == 200
    assert original_path.is_file()
    assert api_client.get(shared["source_url"]).content == content
    assert api_client.delete(f"/api/documents/{shared['id']}").status_code == 200
    assert not original_path.exists()
    assert api_client.get(f"/api/courses/{other['id']}").json()["stats"]["documents"] == 0


def test_multiple_archives_share_one_total_document_limit(
    api_client: TestClient, course: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from anki_generator.api import documents

    monkeypatch.setattr(documents, "MAX_BATCH_DOCUMENTS", 2)
    response = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[
            ("files", ("first.zip", zip_bytes([("a.txt", b"a"), ("b.txt", b"b")]))),
            ("files", ("second.zip", zip_bytes([("c.txt", b"c")]))),
        ],
    )
    assert response.status_code == 400
    assert "batch limit" in response.json()["detail"]
    assert api_client.get(f"/api/courses/{course['id']}/documents").json() == []


def test_queued_run_submission_and_reads_include_pending_plan_without_fake_progress(
    api_client: TestClient, course: dict, source_document: dict
) -> None:
    from anki_generator.database.entities import Stage

    response = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"})
    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "queued"
    assert run["stages"] == [
        {
            "run_id": run["id"],
            "name": "extraction",
            "status": "pending",
            "message": "Waiting for earlier work.",
        }
    ]
    assert api_client.get(f"/api/runs/{run['id']}").json()["stages"] == run["stages"]
    assert api_client.get(f"/api/courses/{course['id']}/runs").json()[0]["stages"] == run["stages"]
    with api_client.app.state.runtime.sessions() as session:
        assert list(session.scalars(select(Stage).where(Stage.run_id == run["id"]))) == []
