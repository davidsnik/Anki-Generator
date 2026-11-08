"""Inspect genuine Anki packages, persistent note identities, and backup formats."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from anki_generator.database.entities import Card
from anki_generator.services.exporting import BASIC_MODEL, CLOZE_MODEL, render_text


@pytest.fixture
def export_cards(api_client: TestClient, course: dict, extracted_source: dict) -> list[dict]:
    reference = {
        "document_id": extracted_source["document"]["id"],
        "page_number": 1,
        "region_id": extracted_source["pages"][0]["regions"][0]["id"],
        "section": "Definition",
        "quote": "f(x) = x squared",
    }
    payloads = [
        {
            "card_type": "basic",
            "question": "What is $f(x)$? <script>unsafe()</script>",
            "answer": r"\(f(x)=x^2\)",
            "explanation": "The square function.",
            "tags": ["Analysis::Functions", "two words", "math"],
            "sources": [reference],
            "image_refs": [reference],
        },
        {
            "card_type": "cloze",
            "question": r"The square function is {{c1::continuous}} on \(\mathbb R\).",
            "answer": "Every real point.",
            "tags": ["Analysis::Functions"],
            "sources": [reference],
            "image_refs": [reference],
        },
    ]
    cards = []
    for payload in payloads:
        response = api_client.post(f"/api/courses/{course['id']}/cards", json=payload)
        assert response.status_code == 201, response.text
        card = response.json()
        reviewed = api_client.post(
            f"/api/cards/{card['id']}/review",
            json={
                "decision": "approved",
                "reason": "Human checked the source, notation and educational target.",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        cards.append(reviewed.json())
    return cards


def export_download(api_client: TestClient, course: dict, **options) -> tuple[dict, bytes]:
    response = api_client.post(f"/api/courses/{course['id']}/exports", json=options)
    assert response.status_code == 201, response.text
    record = response.json()
    downloaded = api_client.get(record["download_url"])
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == record["sha256"]
    return record, downloaded.content


def inspect_package(
    content: bytes, directory: Path
) -> tuple[list[dict], dict, dict, dict[str, bytes]]:
    directory.mkdir(parents=True, exist_ok=True)
    with ZipFile(io.BytesIO(content)) as archive:
        assert {"collection.anki2", "media"} <= set(archive.namelist())
        assert archive.testzip() is None
        database = directory / "collection.anki2"
        database.write_bytes(archive.read("collection.anki2"))
        media_map = json.loads(archive.read("media"))
        media = {name: archive.read(index) for index, name in media_map.items()}
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        notes = [dict(row) for row in connection.execute("SELECT * FROM notes ORDER BY guid")]
        col = connection.execute("SELECT models,decks FROM col").fetchone()
        models, decks = json.loads(col[0]), json.loads(col[1])
        for note in notes:
            note["fields"] = note["flds"].split("\x1f")
            note["cards"] = [
                dict(row)
                for row in connection.execute("SELECT * FROM cards WHERE nid=?", (note["id"],))
            ]
    return notes, models, decks, media


def test_real_apkg_contains_basic_cloze_math_media_templates_tags_and_sources(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
    tmp_path: Path,
) -> None:
    record, content = export_download(
        api_client, course, format="apkg", deck_name="University::Source-backed Analysis"
    )
    assert record["card_count"] == 2
    assert set(record["card_ids"]) == {card["id"] for card in export_cards}
    assert "storage_path" not in record
    notes, models, decks, media = inspect_package(content, tmp_path / "package")
    assert len(notes) == 2
    assert {note["guid"] for note in notes} == {card["note_guid"] for card in export_cards}
    assert {note["mid"] for note in notes} == {BASIC_MODEL.model_id, CLOZE_MODEL.model_id}
    assert any(deck["name"] == "University::Source-backed Analysis" for deck in decks.values())
    assert len(media) == 1  # Shared source image is packaged once.
    assert next(iter(media.values())).startswith(b"\x89PNG\r\n\x1a\n")
    for note in notes:
        assert len(note["fields"]) == 6
        assert "lecture.txt" in note["fields"][3] and "page 1" in note["fields"][3]
        assert "Definition" in note["fields"][3]
        assert '<img src="image_' in note["fields"][0]
        assert "Analysis::Functions" in note["tags"]
        assert note["cards"]
        assert all(card["did"] != 1 for card in note["cards"])
        model = models[str(note["mid"])]
        assert model["css"] and len(model["flds"]) == 6
        assert "Explanation" in model["tmpls"][0]["afmt"]
    basic = next(note for note in notes if note["mid"] == BASIC_MODEL.model_id)
    cloze = next(note for note in notes if note["mid"] == CLOZE_MODEL.model_id)
    assert r"\(f(x)\)" in basic["fields"][0]
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in basic["fields"][0]
    assert "<script>" not in basic["fields"][0]
    assert "two_words" in basic["tags"]
    assert "{{c1::continuous}}" in cloze["fields"][0]
    assert models[str(CLOZE_MODEL.model_id)]["type"] == 1
    assert "{{cloze:Text}}" in models[str(CLOZE_MODEL.model_id)]["tmpls"][0]["qfmt"]


def test_repeated_export_and_wording_edit_keep_note_guids_and_models(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
    tmp_path: Path,
) -> None:
    first_record, first_content = export_download(api_client, course, format="apkg")
    second_record, second_content = export_download(api_client, course, format="apkg")
    first, first_models, first_decks, _ = inspect_package(first_content, tmp_path / "first")
    second, second_models, second_decks, _ = inspect_package(second_content, tmp_path / "second")
    assert first_record["id"] != second_record["id"]
    assert {n["guid"] for n in first} == {n["guid"] for n in second}
    assert set(first_models) == set(second_models)
    assert set(first_decks) == set(second_decks)
    basic = export_cards[0]
    changed = api_client.patch(
        f"/api/cards/{basic['id']}", json={"question": "State the square function precisely."}
    )
    assert changed.status_code == 200
    assert changed.json()["note_guid"] == basic["note_guid"]
    assert changed.json()["review_status"] == "pending"
    api_client.post(
        f"/api/cards/{basic['id']}/review",
        json={
            "decision": "approved",
            "reason": "Rechecked this wording revision against the source.",
        },
    )
    _, third_content = export_download(api_client, course, format="apkg")
    third, third_models, _, _ = inspect_package(third_content, tmp_path / "third")
    assert {n["guid"] for n in first} == {n["guid"] for n in third}
    updated = next(n for n in third if n["guid"] == basic["note_guid"])
    assert "State the square function precisely." in updated["fields"][0]
    assert third_models[str(updated["mid"])]["flds"] == first_models[str(updated["mid"])]["flds"]
    history = api_client.get(f"/api/courses/{course['id']}/exports").json()
    assert len(history) == 3
    assert all(item["card_count"] == 2 for item in history)


def test_apkg_defaults_exclude_pending_and_rejected_and_explicit_selection_cannot_bypass_gate(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
) -> None:
    pending = api_client.post(
        f"/api/courses/{course['id']}/cards", json={"question": "Pending?", "answer": "Yes"}
    ).json()
    rejected = api_client.post(
        f"/api/courses/{course['id']}/cards", json={"question": "Rejected?", "answer": "Yes"}
    ).json()
    api_client.post(
        f"/api/cards/{rejected['id']}/review", json={"decision": "rejected", "reason": "Ambiguous"}
    )
    record, _ = export_download(api_client, course, format="apkg")
    assert set(record["card_ids"]) == {card["id"] for card in export_cards}
    for identifiers in (
        [pending["id"]],
        [rejected["id"]],
        [export_cards[0]["id"], pending["id"]],
        [],
    ):
        response = api_client.post(
            f"/api/courses/{course['id']}/exports", json={"format": "apkg", "card_ids": identifiers}
        )
        assert response.status_code == 400


def test_failed_verification_cannot_export_even_if_old_record_is_human_approved(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
) -> None:
    card = export_cards[0]
    with api_client.app.state.runtime.sessions.begin() as session:
        session.get(Card, card["id"]).verification_status = "failed"
    response = api_client.post(
        f"/api/courses/{course['id']}/exports", json={"format": "apkg", "card_ids": [card["id"]]}
    )
    assert response.status_code == 400


def test_other_course_selection_and_archived_cards_are_rejected(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
) -> None:
    other = api_client.post("/api/courses", json={"name": "Unrelated"}).json()
    card = api_client.post(
        f"/api/courses/{other['id']}/cards", json={"question": "Other", "answer": "A"}
    ).json()
    route = f"/api/courses/{course['id']}/exports"
    assert api_client.post(route, json={"card_ids": [card["id"]]}).status_code == 400
    api_client.patch(f"/api/cards/{export_cards[0]['id']}", json={"archived": True})
    assert api_client.post(route, json={"card_ids": [export_cards[0]["id"]]}).status_code == 400
    record, _ = export_download(api_client, course, format="apkg")
    assert record["card_ids"] == [export_cards[1]["id"]]


@pytest.mark.parametrize(
    "card_type,question,answer",
    [
        ("cloze", "No deletion exists", "Answer"),
        ("basic", "Question?", ""),
    ],
)
def test_invalid_basic_and_cloze_are_rejected_before_publishing_package(
    api_client: TestClient,
    course: dict,
    card_type: str,
    question: str,
    answer: str,
) -> None:
    card = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "card_type": card_type,
            "question": question,
            "answer": answer,
        },
    ).json()
    api_client.post(
        f"/api/cards/{card['id']}/review", json={"decision": "approved", "reason": "Review attempt"}
    )
    response = api_client.post(f"/api/courses/{course['id']}/exports", json={"format": "apkg"})
    assert response.status_code == 400
    assert api_client.get(f"/api/courses/{course['id']}/exports").json() == []
    assert not list((api_client.app.state.runtime.data_root / "exports").glob("*.apkg"))


def test_json_backup_retains_pending_cards_sources_revisions_and_review_history(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
) -> None:
    pending = api_client.post(
        f"/api/courses/{course['id']}/cards", json={"question": "Pending?", "answer": "Yes"}
    ).json()
    record, content = export_download(api_client, course, format="json")
    backup = json.loads(content)
    assert backup["schema_version"] == "1"
    assert record["card_count"] == 3
    assert {card["id"] for card in backup["cards"]} == {
        card["id"] for card in [*export_cards, pending]
    }
    assert (
        next(card for card in backup["cards"] if card["id"] == pending["id"])["review_status"]
        == "pending"
    )
    approved = next(card for card in backup["cards"] if card["id"] == export_cards[0]["id"])
    assert approved["review_history"] and approved["sources"] and approved["note_guid"]


def test_csv_backup_quotes_formula_triggers_and_serializes_evidence(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
) -> None:
    api_client.patch(
        f"/api/cards/{export_cards[0]['id']}",
        json={"question": '=HYPERLINK("unsafe")', "answer": "+1"},
    )
    record, content = export_download(api_client, course, format="csv")
    assert record["card_count"] == 2
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    row = next(row for row in rows if row["id"] == export_cards[0]["id"])
    assert row["question"].startswith("'=") and row["answer"] == "'+1"
    assert json.loads(row["sources"])[0]["document_name"] == "lecture.txt"
    assert "math" in json.loads(row["tags"])


def test_missing_media_prevents_export_and_does_not_record_success(
    api_client: TestClient,
    course: dict,
    export_cards: list[dict],
    extracted_source: dict,
) -> None:
    rt = api_client.app.state.runtime
    image_path = extracted_source["pages"][0]["regions"][0]["image_path"]
    for path in (rt.data_root / "artifacts").rglob(Path(image_path).name):
        path.unlink()
    response = api_client.post(f"/api/courses/{course['id']}/exports", json={"format": "apkg"})
    assert response.status_code == 400
    assert "missing" in response.json()["detail"].lower()
    assert api_client.get(f"/api/courses/{course['id']}/exports").json() == []


def test_exported_html_is_escaped_and_math_delimiters_are_anki_compatible() -> None:
    rendered = render_text('<img onerror="alert(1)"> $x<y$\n$$x^2+y^2=z^2$$')
    assert "<img" not in rendered and "&lt;img" in rendered
    assert r"\(x&lt;y\)" in rendered
    assert r"\[x^2+y^2=z^2\]" in rendered
    assert "<br>" in rendered


@pytest.mark.parametrize("prefix", ["\t=", "\r=", " \t=", "@", "+", "-"])
def test_csv_neutralizes_formula_triggers_after_leading_whitespace(
    api_client: TestClient,
    course: dict,
    prefix: str,
) -> None:
    card = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": prefix + "SUM(1,2)",
            "answer": "3",
        },
    )
    assert card.status_code == 201
    _, content = export_download(api_client, course, format="csv")
    row = next(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    assert row["question"].startswith("'"), "Spreadsheet formula trigger was not neutralized"


@pytest.mark.parametrize("control", ["\x1f", "\x00"])
def test_anki_export_rejects_field_separator_and_nul_controls(
    api_client: TestClient,
    course: dict,
    control: str,
) -> None:
    response = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "Question" + control + "injected field",
            "answer": "Answer",
        },
    )
    if response.status_code in {400, 422}:
        return  # Rejecting unsafe controls at input is also an effective boundary.
    assert response.status_code == 201
    card = response.json()
    approved = api_client.post(
        f"/api/cards/{card['id']}/review",
        json={
            "decision": "approved",
            "reason": "Attempted approval cannot bypass package structure safety.",
        },
    )
    assert approved.status_code == 200
    export = api_client.post(f"/api/courses/{course['id']}/exports", json={"format": "apkg"})
    assert export.status_code == 400
    assert api_client.get(f"/api/courses/{course['id']}/exports").json() == []
