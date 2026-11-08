"""Public HTTP workflow with genuine sources and an explicit test-only provider."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path
from zipfile import ZipFile

import pymupdf
from fastapi.testclient import TestClient
from support.controlled_provider import ControlledProvider


class CourseFixtureProvider(ControlledProvider):
    """Produce two independently reviewed targets and retain original diagram media."""

    def structured(self, stage, payload, schema, *, model, images=None, settings=None):
        result = super().structured(
            stage, payload, schema, model=model, images=images, settings=settings
        )
        if stage == "generation":
            result.data.cards[0].media = payload["available_media"][:1]
            cloze = result.data.cards[0].model_copy(deep=True)
            cloze.identity_key = "pythagoras:hypotenuse"
            cloze.card_type = "cloze"
            cloze.question = (
                r"For a right triangle, \(a^2+b^2=c^2\), where \(c\) is the {{c1::hypotenuse}}."
            )
            cloze.answer = "The side opposite the right angle."
            result.data.cards.append(cloze)
        return result


def lecture_pdf() -> bytes:
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((45, 65), "Euclidean geometry", fontsize=22)
        page.insert_text((45, 115), "For a right triangle, a^2 + b^2 = c^2.", fontsize=15)
        page.insert_text((45, 145), "The right-angle assumption is necessary.", fontsize=14)
        page.insert_text(
            (45, 175), "Here c is the hypotenuse, opposite the right angle.", fontsize=14
        )
        page.draw_polyline(
            [(100, 450), (100, 220), (450, 450), (100, 450)], color=(0.3, 0.2, 0.8), width=2
        )
        page.draw_rect((100, 430, 120, 450), color=(0, 0, 0))
        page.insert_text((65, 340), "a", fontsize=20)
        page.insert_text((270, 485), "b", fontsize=20)
        page.insert_text((290, 300), "c", fontsize=20)
        return document.tobytes(garbage=4, deflate=True, no_new_id=True)


def package_notes(content: bytes, database_path: Path) -> tuple[dict[str, tuple], dict]:
    with ZipFile(io.BytesIO(content)) as package:
        assert package.testzip() is None
        media = json.loads(package.read("media"))
        assert media
        assert all(package.read(index).startswith(b"\x89PNG") for index in media)
        database_path.write_bytes(package.read("collection.anki2"))
    with sqlite3.connect(database_path) as database:
        assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        notes = {row[0]: row[1:] for row in database.execute("SELECT guid,mid,flds FROM notes")}
    return notes, media


def test_complete_http_course_to_source_linked_reviewed_anki_workflow(
    api_client: TestClient,
    tmp_path: Path,
) -> None:
    provider = CourseFixtureProvider()
    rt = api_client.app.state.runtime
    rt.runner.provider_factory = lambda key, config: provider
    response = api_client.put(
        "/api/settings/key", json={"api_key": "test-provider-key-is-never-sent"}
    )
    assert response.status_code == 200
    course_response = api_client.post(
        "/api/courses", json={"name": "Geometry", "deck_name": "University::Geometry"}
    )
    assert course_response.status_code == 201
    course = course_response.json()
    raw_pdf = lecture_pdf()
    sources = [
        ("01-lecture.pdf", raw_pdf, "lecture", "application/pdf"),
        (
            "02-exercises.txt",
            b"For a right triangle, a^2 + b^2 = c^2.\n"
            b"Exercise: identify the hypotenuse and find a missing side.\n",
            "exercises",
            "text/plain",
        ),
        (
            "03-solutions.md",
            b"For a right triangle, a^2 + b^2 = c^2.\n"
            b"Locate the right angle, identify c, and apply the identity.\n",
            "solutions",
            "text/markdown",
        ),
    ]
    imported = []
    for filename, content, role, mime in sources:
        response = api_client.post(
            f"/api/courses/{course['id']}/documents",
            files=[
                ("files", (filename, content, mime)),
            ],
            data={"category": role, "authority": "official"},
        )
        assert response.status_code == 201, response.text
        imported.append(response.json()["documents"][0])
    linked = api_client.patch(
        f"/api/documents/{imported[2]['id']}", json={"linked_document_id": imported[1]["id"]}
    )
    assert linked.status_code == 200
    response = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"mode": "generate", "consent": True}
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert response.json()["status"] == "queued"
    assert response.json()["inputs"][2]["linked_document_id"] == imported[1]["id"]
    rt.runner.run_now(run_id)
    run = api_client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "completed", run.get("error")
    assert run["metrics"]["coverage_complete"] and run["metrics"]["concepts_covered"] == 1
    assert run["progress"]["documents"] == 3
    assert run["usage"]["api_calls"] == sum(provider.calls.values())
    assert provider.calls["interpretation"] >= 1
    assert {payload["role"] for stage, payload in provider.payloads if stage == "knowledge"} == {
        "lecture",
        "exercises",
        "solutions",
    }
    assert {"factual", "pedagogical", "mathematical", "coverage"} <= set(provider.calls)
    concepts = api_client.get(f"/api/courses/{course['id']}/concepts").json()
    assert len(concepts) == 1 and concepts[0]["sources"]
    assert concepts[0]["exercise_analysis"][0]["techniques"] == ["Identify hypotenuse"]
    cards = api_client.get(f"/api/courses/{course['id']}/cards").json()
    assert len(cards) == 2 and {card["card_type"] for card in cards} == {"basic", "cloze"}
    assert all(
        card["verification_status"] == "verified" and card["review_status"] == "pending"
        for card in cards
    )
    assert all(card["sources"] and card["image_refs"] for card in cards)
    for card in cards:
        detail = api_client.get(f"/api/cards/{card['id']}").json()
        assert {check["stage"] for check in detail["verifications"]} >= {
            "factual",
            "pedagogical",
            "mathematical",
        }
        assert api_client.get(card["sources"][0]["source_url"]).status_code == 200
        assert (
            api_client.get(card["image_refs"][0]["image_url"]).headers["content-type"]
            == "image/png"
        )
        approved = api_client.post(f"/api/cards/{card['id']}/review", json={"decision": "approved"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["review_history"][0]["decision"] == "approved"
    source = api_client.get(imported[0]["source_url"]).content
    assert hashlib.sha256(source).digest() == hashlib.sha256(raw_pdf).digest()
    packages = []
    for index in range(2):
        exported = api_client.post(f"/api/courses/{course['id']}/exports", json={"format": "apkg"})
        assert exported.status_code == 201, exported.text
        assert exported.json()["card_count"] == 2
        downloaded = api_client.get(exported.json()["download_url"])
        packages.append(package_notes(downloaded.content, tmp_path / f"export-{index}.sqlite3"))
    assert set(packages[0][0]) == set(packages[1][0]) == {card["note_guid"] for card in cards}
    assert len(packages[0][0]) == 2
    assert len(api_client.get(f"/api/courses/{course['id']}/exports").json()) == 2
    assert api_client.get(f"/api/courses/{course['id']}").json()["stats"]["verified"] == 2
    with ZipFile(io.BytesIO(api_client.post("/api/backup").content)) as backup:
        paths = set(backup.namelist())
        assert "application.sqlite3" in paths
        for checkpoint in run["checkpoints"].values():
            if not isinstance(checkpoint, str):
                continue  # Transactional card-final checkpoints are inline state.
            assert checkpoint in paths, f"Backup omitted resumable artifact {checkpoint}"
        assert all(b"test-provider-key-is-never-sent" not in backup.read(name) for name in paths)

    # Deletion removes this course's private copies and durable processing files.
    original_paths = list((rt.data_root / "originals").iterdir())
    artifact_directories = [rt.data_root / "artifacts" / doc["id"] for doc in imported]
    export_paths = list((rt.data_root / "exports").glob("*.apkg"))
    cache_directory = rt.data_root / "cache" / "llm" / course["id"]
    assert original_paths and all(path.is_file() for path in original_paths)
    assert all(path.is_dir() for path in artifact_directories)
    assert len(export_paths) == 2 and cache_directory.is_dir()
    run_directory = rt.data_root / "runs" / run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_directory / "auxiliary-checkpoint.json").write_text("{}")
    unrelated = rt.data_root / "unrelated-user-file.txt"
    unrelated.write_text("Keep this file")
    deleted = api_client.delete(f"/api/courses/{course['id']}")
    assert deleted.status_code == 200, deleted.text
    assert not any(
        path.exists() for path in [*original_paths, *artifact_directories, *export_paths]
    )
    assert not cache_directory.exists() and not run_directory.exists()
    assert unrelated.read_text() == "Keep this file"
    assert api_client.get(f"/api/courses/{course['id']}").status_code == 404
    assert api_client.get(f"/api/runs/{run_id}").status_code == 404
    assert all(api_client.get(f"/api/cards/{card['id']}").status_code == 404 for card in cards)
