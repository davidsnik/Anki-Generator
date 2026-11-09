"""Human correction precedence, original-coordinate selection and targeted recovery."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from anki_generator.database.entities import Document
from anki_generator.services.source_corrections import apply_corrections

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"


def extract(api_client, course_id, **extra):
    response = api_client.post(f"/api/courses/{course_id}/runs", json={"mode": "extract", **extra})
    assert response.status_code == 202, response.text
    api_client.app.state.runtime.runner.run_now(response.json()["id"])
    run = api_client.get(f"/api/runs/{response.json()['id']}").json()
    assert run["status"] == "completed", run.get("error")
    return run


def test_human_correction_history_preserves_original_and_requires_explicit_verified_replacement(
    api_client,
    extracted_source,
):
    document = extracted_source["document"]
    identifier = document["id"]
    original = api_client.get(document["source_url"]).content
    route = f"/api/documents/{identifier}/pages/1/corrections"
    created = api_client.post(
        route,
        json={
            "text": r"For every x>0, \(f(x)\geq0\).",
            "verified": True,
            "reason": "Synthetic human correction regression",
            "expected_revision": 0,
        },
    )
    assert created.status_code == 201, created.text
    first = created.json()
    inspected = api_client.get(f"/api/documents/{identifier}/interpretation").json()
    page = inspected["pages"][0]
    assert page["original_text"].encode() == original
    assert page["text"] == page["effective_text"] == first["text"]
    assert page["human_verified"] and page["correction_revision"] == 1
    assert (
        api_client.post(
            route, json={"text": "automatic replacement", "verified": False}
        ).status_code
        == 400
    )
    replaced = api_client.post(
        route,
        json={
            "text": "Corrected revision two",
            "verified": True,
            "reason": "Synthetic second review",
            "replace_verified": True,
            "expected_revision": 1,
        },
    )
    assert replaced.status_code == 201
    assert replaced.json()["supersedes_id"] == first["id"]
    assert [c["revision_number"] for c in api_client.get(route).json()] == [1, 2]
    assert api_client.get(document["source_url"]).content == original
    rt = api_client.app.state.runtime
    with rt.sessions() as session:
        saved = session.get(Document, identifier)
        assert saved.extraction["pages"][0]["text"].encode() == original
        effective = apply_corrections(session, identifier, saved.extraction)
        assert effective["pages"][0]["text"] == "Corrected revision two"
        assert (
            apply_corrections(session, identifier, saved.extraction, replace_human=True)["pages"][
                0
            ]["text"].encode()
            == original
        )


def test_correcting_source_invalidates_prior_card_checks_without_changing_note_guid(
    api_client,
    course,
    extracted_source,
):
    document_id = extracted_source["document"]["id"]
    card = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "Q",
            "answer": "A",
            "sources": [{"document_id": document_id, "page_number": 1}],
        },
    ).json()
    api_client.post(
        f"/api/cards/{card['id']}/review",
        json={"decision": "approved", "reason": "Synthetic approval"},
    )
    response = api_client.post(
        f"/api/documents/{document_id}/pages/1/corrections",
        json={
            "text": "A corrected source",
            "verified": False,
        },
    )
    assert response.status_code == 201
    current = api_client.get(f"/api/cards/{card['id']}").json()
    assert (
        current["verification_status"] == "needs_review" and current["review_status"] == "pending"
    )
    assert current["note_guid"] == card["note_guid"]
    assert "transcription changed" in " ".join(map(str, current["issues"]))


def test_high_resolution_pdf_selection_persists_after_reextraction_and_can_associate_card(
    api_client,
    course,
):
    pdf = (FIXTURES / "digital.pdf").read_bytes()
    response = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", ("lecture.pdf", pdf, "application/pdf"))],
    )
    document = response.json()["documents"][0]
    identifier = document["id"]
    extract(api_client, course["id"])
    selected = api_client.post(
        f"/api/documents/{identifier}/regions",
        json={
            "page_number": 1,
            "bbox": [48, 215, 548, 300],
            "dpi": 200,
            "label": "Theorem assumptions",
        },
    )
    assert selected.status_code == 201, selected.text
    region = selected.json()
    assert region["bbox"] == [48, 215, 548, 300]
    assert region["coordinate_system"] == "pdf-points"
    assert abs(region["pixel_width"] - 500 * 200 / 72) < 2
    image = api_client.get(region["image_url"])
    assert image.status_code == 200
    with Image.open(io.BytesIO(image.content)) as png:
        assert png.size == (region["pixel_width"], region["pixel_height"])
    card = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={"question": "State the assumptions", "answer": "Continuity on [a,b]."},
    ).json()
    associated = api_client.post(
        f"/api/documents/{identifier}/regions/{region['id']}/associate",
        json={
            "card_id": card["id"],
            "expected_revision": 1,
        },
    )
    assert associated.status_code == 200, associated.text
    assert associated.json()["card"]["image_refs"][0]["region_id"] == region["id"]
    assert associated.json()["card"]["revision_number"] == 2
    api_client.patch(f"/api/documents/{identifier}", json={"reprocess": True})
    extract(api_client, course["id"])
    assert api_client.get(region["image_url"]).content == image.content
    inspected = api_client.get(f"/api/documents/{identifier}/interpretation").json()
    assert any(r["id"] == region["id"] for r in inspected["pages"][0]["regions"])
    # Recreated Page rows must not break persistent selected-region evidence.
    changed = api_client.patch(
        f"/api/cards/{card['id']}",
        json={
            "image_refs": [
                {
                    "document_id": identifier,
                    "page_number": 1,
                    "region_id": region["id"],
                }
            ]
        },
    )
    assert changed.status_code == 200, changed.text
    assert (
        hashlib.sha256(api_client.get(document["source_url"]).content).digest()
        == hashlib.sha256(pdf).digest()
    )


@pytest.mark.parametrize("bbox", [[-1, 0, 10, 10], [0, 0, 100000, 200000], [5, 5, 1, 1]])
def test_invalid_original_coordinate_selection_is_rejected(api_client, course, bbox):
    response = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", ("image.png", (FIXTURES / "diagram.png").read_bytes(), "image/png"))],
    )
    identifier = response.json()["documents"][0]["id"]
    extract(api_client, course["id"])
    assert (
        api_client.post(
            f"/api/documents/{identifier}/regions", json={"page_number": 1, "bbox": bbox}
        ).status_code
        == 400
    )


def test_regional_correction_overrides_conflicting_automatic_region_interpretation(
    api_client,
    extracted_source,
):
    identifier = extracted_source["document"]["id"]
    region_id = extracted_source["pages"][0]["regions"][0]["id"]
    response = api_client.post(
        f"/api/documents/{identifier}/pages/1/corrections",
        json={
            "region_id": region_id,
            "text": "x > 0, not x >= 0",
            "verified": True,
            "reason": "Synthetic strict-inequality transcription correction",
        },
    )
    assert response.status_code == 201
    rt = api_client.app.state.runtime
    with rt.sessions() as session:
        raw = session.get(Document, identifier).extraction
        raw["pages"][0]["visual_interpretations"] = [
            {
                "region_id": region_id,
                "transcription": "x >= 0",
                "description": "Automatic draft",
                "uncertain": False,
            }
        ]
        effective = apply_corrections(session, identifier, raw)
    interpretations = effective["pages"][0]["visual_interpretations"]
    assert len(interpretations) == 1 and interpretations[0]["origin"] == "human"
    assert interpretations[0]["transcription"] == "x > 0, not x >= 0"
    assert not interpretations[0]["uncertain"]


def test_selected_pdf_page_extraction_keeps_original_number_and_skips_other_pages(
    tmp_path, monkeypatch
):
    import pymupdf

    from anki_generator.ingestion.extraction import extract_document

    source = tmp_path / "pages.pdf"
    with pymupdf.open() as document:
        for number in range(1, 4):
            page = document.new_page(width=300, height=400)
            page.insert_text((30, 60), f"Original page {number}: exact source coordinates")
        document.save(source)
    visited = []
    original = pymupdf.Document.load_page

    def observed(document, index):
        visited.append(index)
        return original(document, index)

    monkeypatch.setattr(pymupdf.Document, "load_page", observed)
    result = extract_document(source, tmp_path / "out", page_numbers=[2])
    assert visited == [1]
    assert result.total_pages == 3 and [p.page_number for p in result.pages] == [2]
    assert "Original page 2" in result.pages[0].text
    assert all(region.page_number == 2 for region in result.pages[0].regions)
    assert result.status == "partial" and any("selected pages" in w for w in result.warnings)


def test_verified_human_math_correction_propagates_into_actual_pipeline_evidence(
    api_client, course
):
    from support.controlled_provider import ControlledProvider

    provider = ControlledProvider()
    api_client.app.state.runtime.runner.provider_factory = lambda key, config: provider
    uploaded = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[
            (
                "files",
                (
                    "misread-math.pdf",
                    (FIXTURES / "misread-math.pdf").read_bytes(),
                    "application/pdf",
                ),
            )
        ],
    )
    document = uploaded.json()["documents"][0]
    identifier = document["id"]
    extract(api_client, course["id"])
    original = api_client.get(f"/api/documents/{identifier}/interpretation").json()["pages"][0]
    assert "a^2 - b^2" in original["original_text"]
    corrected = "For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is necessary."
    response = api_client.post(
        f"/api/documents/{identifier}/pages/1/corrections",
        json={
            "text": corrected,
            "verified": True,
            "reason": "Synthetic benchmark: corrected the deliberately wrong invisible OCR sign.",
        },
    )
    assert response.status_code == 201, response.text
    api_client.put("/api/settings/key", json={"api_key": "test-source-correction-provider"})
    started = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"mode": "generate", "consent": True}
    )
    assert started.status_code == 202, started.text
    api_client.app.state.runtime.runner.run_now(started.json()["id"])
    completed = api_client.get(f"/api/runs/{started.json()['id']}").json()
    assert completed["status"] == "completed", completed.get("error")
    assert provider.calls["interpretation"] == 0  # Human page transcription is preserved.
    knowledge = [payload for stage, payload in provider.payloads if stage == "knowledge"]
    assert knowledge and any("a^2 + b^2" in payload["text"] for payload in knowledge)
    assert all("a^2 - b^2" not in payload["text"] for payload in knowledge)
    cards = api_client.get(f"/api/courses/{course['id']}/cards").json()
    assert cards and all(card["sources"] for card in cards)
    assert all("a^2 + b^2" in card["answer"] for card in cards)
    for stage, payload in provider.payloads:
        if stage in {"factual", "mathematical"}:
            assert "a^2 + b^2" in payload["original_evidence"][0]["text"]
            assert "a^2 - b^2" not in payload["original_evidence"][0]["text"]
    final = api_client.get(f"/api/documents/{identifier}/interpretation").json()["pages"][0]
    assert final["human_verified"] and final["effective_text"] == corrected
    assert "a^2 - b^2" in final["original_text"]


def test_confirmed_automatic_replacement_keeps_human_history_and_adopts_new_reading(
    api_client,
    course,
    extracted_source,
):
    from support.controlled_provider import ControlledProvider

    provider = ControlledProvider()
    rt = api_client.app.state.runtime
    rt.runner.provider_factory = lambda key, config: provider
    identifier = extracted_source["document"]["id"]
    route = f"/api/documents/{identifier}/pages/1/corrections"
    human = api_client.post(
        route,
        json={
            "text": "Preserved human reading",
            "verified": True,
            "reason": "Synthetic human history test",
        },
    ).json()
    api_client.put("/api/settings/key", json={"api_key": "test-confirmed-replacement"})
    response = api_client.post(
        f"/api/documents/{identifier}/reprocess",
        json={
            "page_numbers": [1],
            "mode": "interpret",
            "consent": True,
            "replace_human": True,
        },
    )
    assert response.status_code == 202, response.text
    rt.runner.run_now(response.json()["id"])
    completed = api_client.get(f"/api/runs/{response.json()['id']}").json()
    assert completed["status"] == "completed", completed.get("error")
    history = api_client.get(route).json()
    assert history[0]["id"] == human["id"] and history[0]["verified"] is True
    assert history[-1]["origin"] == "automatic_override" and history[-1]["verified"] is False
    assert history[-1]["supersedes_id"] == human["id"]
    inspected = api_client.get(f"/api/documents/{identifier}/interpretation").json()["pages"][0]
    assert not inspected["human_verified"]
    assert "a^2 + b^2" in inspected["effective_text"]
    assert "Preserved human reading" not in inspected["effective_text"]
    assert inspected["correction_revision"] == 2


def test_paused_run_refuses_changed_human_evidence_before_any_provider_call(
    api_client, course, extracted_source
):
    from support.controlled_provider import ControlledProvider

    provider = ControlledProvider()
    rt = api_client.app.state.runtime
    rt.runner.provider_factory = lambda key, config: provider
    api_client.put("/api/settings/key", json={"api_key": "test-source-snapshot"})
    submitted = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"mode": "generate", "consent": True}
    ).json()
    assert api_client.post(f"/api/runs/{submitted['id']}/pause").status_code == 200
    identifier = extracted_source["document"]["id"]
    correction = api_client.post(
        f"/api/documents/{identifier}/pages/1/corrections",
        json={
            "text": "A newly corrected source",
            "verified": True,
            "reason": "Synthetic version-change test",
        },
    )
    assert correction.status_code == 201
    assert api_client.post(f"/api/runs/{submitted['id']}/resume").status_code == 200
    rt.runner.run_now(submitted["id"])
    failed = api_client.get(f"/api/runs/{submitted['id']}").json()
    assert failed["status"] == "failed"
    assert "correction" in failed["error"].lower() or "source" in failed["error"].lower()
    assert not provider.calls


def test_targeted_interpretation_keeps_human_verified_page_without_replace_confirmation(
    api_client,
    course,
    extracted_source,
):
    from support.controlled_provider import ControlledProvider

    provider = ControlledProvider()
    rt = api_client.app.state.runtime
    rt.runner.provider_factory = lambda key, config: provider
    identifier = extracted_source["document"]["id"]
    api_client.post(
        f"/api/documents/{identifier}/pages/1/corrections",
        json={
            "text": "Keep the human reading",
            "verified": True,
            "reason": "Synthetic preservation check",
        },
    )
    api_client.put("/api/settings/key", json={"api_key": "test-preserve-human"})
    submitted = api_client.post(
        f"/api/documents/{identifier}/reprocess",
        json={
            "mode": "interpret",
            "page_numbers": [1],
            "consent": True,
        },
    )
    assert submitted.status_code == 202
    rt.runner.run_now(submitted.json()["id"])
    completed = api_client.get(f"/api/runs/{submitted.json()['id']}").json()
    assert completed["status"] == "completed", completed.get("error")
    assert provider.calls["interpretation"] == 0
    page = api_client.get(f"/api/documents/{identifier}/interpretation").json()["pages"][0]
    assert page["human_verified"] and page["effective_text"] == "Keep the human reading"
