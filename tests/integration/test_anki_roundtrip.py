"""Actual Anki Python/Rust imports into disposable collections, never user profiles.

Install: uv sync --extra anki-integration
Run: uv run --extra anki-integration pytest tests/integration/test_anki_roundtrip.py
No network, AnkiWeb, GUI profile, real API key or existing Anki collection is used.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import re
import time
from pathlib import Path

import pytest

pytest.importorskip(
    "anki", reason="Install the optional anki-integration extra for real collection tests"
)
from anki.collection import Collection, ImportAnkiPackageOptions, ImportAnkiPackageRequest
from anki.import_export_pb2 import (
    IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS as ALWAYS,
)
from anki.import_export_pb2 import (
    IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_IF_NEWER as IF_NEWER,
)
from anki.import_export_pb2 import (
    IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_NEVER as NEVER,
)
from anki.scheduler.v3 import CardAnswer

pytestmark = pytest.mark.anki_integration


@pytest.fixture
def disposable_collection(tmp_path):
    profile = tmp_path / "disposable-anki-profile"
    profile.mkdir()
    collection_path = profile / "collection.anki2"
    assert collection_path.resolve().is_relative_to(tmp_path.resolve())
    collection = Collection(str(collection_path))
    try:
        yield collection
    finally:
        collection.close()


@pytest.fixture
def frozen_export_clock(monkeypatch):
    clock = [int(time.time())]
    # genanki uses whole-second note modification times. Keep the wall second
    # fixed to exercise the real importer's equal-modification-time boundary.
    monkeypatch.setattr("genanki.package.time.time", lambda: clock[0])
    return clock


@pytest.fixture
def notes_for_import(api_client, course, extracted_source):
    reference = {
        "document_id": extracted_source["document"]["id"],
        "page_number": 1,
        "region_id": extracted_source["pages"][0]["regions"][0]["id"],
    }
    result = []
    for payload in [
        {
            "card_type": "basic",
            "question": r"What is \(f(x)\)?",
            "answer": r"\(f(x)=x^2\)",
            "explanation": "The square function",
            "tags": ["initial", "analysis"],
            "sources": [reference],
            "image_refs": [reference],
        },
        {
            "card_type": "cloze",
            "question": r"The square function is {{c1::continuous}} on \(\mathbb R\).",
            "answer": "At every real point",
            "explanation": "A polynomial is continuous.",
            "tags": ["cloze"],
            "sources": [reference],
            "image_refs": [reference],
        },
    ]:
        response = api_client.post(f"/api/courses/{course['id']}/cards", json=payload)
        assert response.status_code == 201, response.text
        card = response.json()
        approve(api_client, card["id"])
        result.append(card)
    return result


def approve(client, card_id):
    response = client.post(
        f"/api/cards/{card_id}/review",
        json={
            "decision": "approved",
            "reason": "Synthetic Anki integration fixture; not a real human quality rating.",
        },
    )
    assert response.status_code == 200, response.text


def export_package(client, course, tmp_path):
    exported = client.post(f"/api/courses/{course['id']}/exports", json={"format": "apkg"})
    assert exported.status_code == 201, exported.text
    record = exported.json()
    response = client.get(record["download_url"])
    assert response.status_code == 200
    path = tmp_path / f"package-{record['id']}.apkg"
    path.write_bytes(response.content)
    return path


def import_package(collection, path, condition=IF_NEWER, *, with_scheduling=False):
    return collection.import_anki_package(
        ImportAnkiPackageRequest(
            package_path=str(path),
            options=ImportAnkiPackageOptions(
                update_notes=condition,
                update_notetypes=IF_NEWER,
                merge_notetypes=False,
                with_scheduling=with_scheduling,
                with_deck_configs=False,
            ),
        )
    )


def note_by_guid(collection, guid):
    note_id = collection.db.scalar("SELECT id FROM notes WHERE guid=?", guid)
    assert note_id is not None, "Expected stable GUID was not imported"
    return collection.get_note(note_id)


def card_ids(collection, guid):
    note = note_by_guid(collection, guid)
    return collection.db.list("SELECT id FROM cards WHERE nid=? ORDER BY id", note.id)


def test_import_into_empty_real_collection_includes_basic_cloze_math_and_media(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
):
    collection = disposable_collection
    assert collection.note_count() == collection.card_count() == 0
    package = export_package(api_client, course, tmp_path)
    result = import_package(collection, package)
    assert len(result.log.new) == 2
    assert collection.note_count() == collection.card_count() == 2
    assert tuple(int(part) for part in importlib.metadata.version("anki").split(".")) == (26, 9, 4)
    for card in notes_for_import:
        note = note_by_guid(collection, card["note_guid"])
        assert note["Identity"] == card["id"]
        assert "lecture.txt" in note["Sources"]
        front = note["Text"] if card["card_type"] == "cloze" else note["Front"]
        assert r"\(" in front
        if card["card_type"] == "cloze":
            assert "{{c1::continuous}}" in front
        media = re.findall(r'<img src="([^"]+)"', front)
        assert media
        for filename in media:
            path = Path(collection.media.dir()) / filename
            assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            assert hashlib.sha256(path.read_bytes()).hexdigest() in filename
    assert len(list(Path(collection.media.dir()).glob("*.png"))) == 1


def test_importing_same_package_twice_keeps_note_and_card_ids_without_duplicates(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
):
    collection = disposable_collection
    package = export_package(api_client, course, tmp_path)
    import_package(collection, package)
    before = {
        card["note_guid"]: (
            note_by_guid(collection, card["note_guid"]).id,
            card_ids(collection, card["note_guid"]),
        )
        for card in notes_for_import
    }
    repeated = import_package(collection, package)
    assert not repeated.log.new
    assert collection.note_count() == collection.card_count() == 2
    after = {
        card["note_guid"]: (
            note_by_guid(collection, card["note_guid"]).id,
            card_ids(collection, card["note_guid"]),
        )
        for card in notes_for_import
    }
    assert before == after


def test_same_second_application_edit_reimports_with_if_newer_and_keeps_identity(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
    frozen_export_clock,
):
    collection = disposable_collection
    card = notes_for_import[0]
    import_package(collection, export_package(api_client, course, tmp_path))
    original = note_by_guid(collection, card["note_guid"])
    identifier, ids, previous_mtime = (
        original.id,
        card_ids(collection, card["note_guid"]),
        original.mod,
    )
    changed = api_client.patch(
        f"/api/cards/{card['id']}", json={"question": "An exact revised question?"}
    )
    assert changed.status_code == 200
    approve(api_client, card["id"])
    result = import_package(collection, export_package(api_client, course, tmp_path))
    updated = note_by_guid(collection, card["note_guid"])
    assert updated["Front"].startswith("An exact revised question?")
    assert updated.id == identifier and card_ids(collection, card["note_guid"]) == ids
    assert updated.mod > previous_mtime
    assert len(result.log.updated) >= 1 and collection.note_count() == 2


def test_new_application_cards_are_added_without_replacing_existing_notes(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
):
    collection = disposable_collection
    import_package(collection, export_package(api_client, course, tmp_path))
    previous_ids = {note_by_guid(collection, card["note_guid"]).id for card in notes_for_import}
    added = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "What is a closed interval?",
            "answer": "An interval containing both endpoints.",
        },
    ).json()
    approve(api_client, added["id"])
    imported = import_package(collection, export_package(api_client, course, tmp_path))
    assert len(imported.log.new) == 1
    assert collection.note_count() == collection.card_count() == 3
    assert {
        note_by_guid(collection, card["note_guid"]).id for card in notes_for_import
    } == previous_ids
    assert note_by_guid(collection, added["note_guid"])["Back"] == added["answer"]


def test_omitting_archived_application_card_does_not_delete_anki_note_or_card(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
):
    collection = disposable_collection
    import_package(collection, export_package(api_client, course, tmp_path))
    archived = notes_for_import[0]
    old_ids = card_ids(collection, archived["note_guid"])
    response = api_client.patch(f"/api/cards/{archived['id']}", json={"archived": True})
    assert response.status_code == 200
    import_package(collection, export_package(api_client, course, tmp_path))
    assert collection.note_count() == collection.card_count() == 2
    assert card_ids(collection, archived["note_guid"]) == old_ids


@pytest.mark.parametrize(
    "condition,preserves_manual", [(IF_NEWER, True), (NEVER, True), (ALWAYS, False)]
)
def test_manual_anki_edits_follow_explicit_import_update_policy(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
    frozen_export_clock,
    condition,
    preserves_manual,
):
    collection = disposable_collection
    card = notes_for_import[0]
    frozen_export_clock[0] -= 60  # Ensure imported note is older than the genuine local Anki edit.
    import_package(collection, export_package(api_client, course, tmp_path))
    note = note_by_guid(collection, card["note_guid"])
    note["Front"] = "Manual edit made inside disposable Anki"
    collection.update_note(note)
    # Re-export unchanged app content a minute later: this must not pretend that
    # the unchanged app note itself changed under the default IfNewer policy.
    frozen_export_clock[0] += 120
    import_package(collection, export_package(api_client, course, tmp_path), condition)
    current = note_by_guid(collection, card["note_guid"])
    if preserves_manual:
        assert current["Front"] == "Manual edit made inside disposable Anki"
    else:
        assert current["Front"].startswith(card["question"])
    assert collection.note_count() == 2


@pytest.mark.parametrize("with_scheduling", [False, True])
def test_real_scheduler_review_history_and_scheduling_survive_package_updates(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
    with_scheduling,
):
    collection = disposable_collection
    import_package(collection, export_package(api_client, course, tmp_path))
    imported_deck_id = collection.db.scalar("SELECT did FROM cards LIMIT 1")
    collection.decks.set_current(imported_deck_id)
    queued = collection.sched.get_queued_cards(fetch_limit=1).cards[0]
    card = collection.get_card(queued.card.id)
    card.start_timer()
    answer = collection.sched.build_answer(card=card, states=queued.states, rating=CardAnswer.EASY)
    collection.sched.answer_card(answer)
    reviewed = collection.get_card(card.id)
    schedule_fields = (
        "id",
        "nid",
        "did",
        "queue",
        "type",
        "due",
        "ivl",
        "factor",
        "reps",
        "lapses",
        "left",
    )
    before = {field: getattr(reviewed, field) for field in schedule_fields}
    history = collection.db.all("SELECT * FROM revlog WHERE cid=? ORDER BY id", card.id)
    assert history and reviewed.reps == 1
    reviewed_guid = collection.get_note(reviewed.nid).guid
    app_card = next(item for item in notes_for_import if item["note_guid"] == reviewed_guid)
    api_client.patch(
        f"/api/cards/{app_card['id']}",
        json={"explanation": "A revised explanation, with learning history retained."},
    )
    approve(api_client, app_card["id"])
    import_package(
        collection,
        export_package(api_client, course, tmp_path),
        ALWAYS,
        with_scheduling=with_scheduling,
    )
    after = collection.get_card(card.id)
    assert (
        collection.get_note(after.nid)["Explanation"]
        == "A revised explanation, with learning history retained."
    )
    assert {field: getattr(after, field) for field in schedule_fields} == before
    assert collection.db.all("SELECT * FROM revlog WHERE cid=? ORDER BY id", card.id) == history


def test_tags_explanations_math_and_media_update_under_explicit_always_policy(
    api_client,
    course,
    notes_for_import,
    disposable_collection,
    tmp_path,
):
    collection = disposable_collection
    card = notes_for_import[0]
    import_package(collection, export_package(api_client, course, tmp_path))
    note = note_by_guid(collection, card["note_guid"])
    media_before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(collection.media.dir()).glob("*.png")
    }
    api_client.patch(
        f"/api/cards/{card['id']}",
        json={
            "tags": ["revised_tag"],
            "explanation": r"The derivative is \(f'(x)=2x\).",
            "answer": r"\[f(x)=x^2\]",
        },
    )
    approve(api_client, card["id"])
    import_package(collection, export_package(api_client, course, tmp_path), ALWAYS)
    updated = note_by_guid(collection, card["note_guid"])
    assert updated.id == note.id and set(updated.tags) == {"revised_tag"}
    assert updated["Explanation"] == r"The derivative is \(f'(x)=2x\)."
    assert updated["Back"] == r"\[f(x)=x^2\]"
    assert {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(collection.media.dir()).glob("*.png")
    } == media_before
