"""Reference truth and controlled labels must never masquerade as human evidence."""

import copy

import pytest

from anki_generator.evaluation.contracts import DatasetInput
from anki_generator.evaluation.metrics import summarize


def test_metrics_keep_unreviewed_human_synthetic_and_model_denominators_separate():
    cases = [
        {
            "case_id": "a",
            "variant_id": "v",
            "card": {"answer": "a short answer", "verification_status": "verified"},
            "reference_concept_ids": ["theorem"],
            "automatic": {"schema_valid": True, "source_locations_valid": True},
        },
        {
            "case_id": "b",
            "variant_id": "v",
            "card": {"answer": "incorrect answer", "verification_status": "verified"},
            "reference_concept_ids": [],
            "automatic": {"schema_valid": True, "source_locations_valid": False},
        },
    ]
    reference = {
        "provenance": "synthetic",
        "reference_concepts": [
            {"id": "theorem", "label": "Theorem"},
            {"id": "assumption", "label": "Assumption"},
        ],
    }
    empty = summarize(cases, [], reference, [{"id": "v", "name": "Original"}])["variants"][0]
    assert empty["reviews"]["human"]["acceptance"]["value"] is None
    assert empty["reviews"]["human"]["review_progress"]["denominator"] == 2
    judgments = [
        {
            "case_id": "a",
            "reviewer": "Synthetic fixture",
            "origin": "synthetic",
            "label": "correct_useful",
            "dimensions": {"factual_correct": True},
            "reference_concept_ids": ["theorem"],
        },
        {
            "case_id": "b",
            "reviewer": "Actual reviewer",
            "origin": "human",
            "label": "incorrect",
            "dimensions": {"factual_correct": False},
            "reference_concept_ids": [],
        },
    ]
    result = summarize(cases, judgments, reference, [{"id": "v", "name": "Original"}])["variants"][
        0
    ]
    assert result["model_judgments"] == {"verified": 2}
    assert result["reviews"]["human"]["acceptance"]["value"] == 0
    assert result["reviews"]["synthetic"]["acceptance"]["value"] == 1
    assert result["reviews"]["human"]["dimensions"]["factual_correct"]["denominator"] == 1
    assert result["automatic"]["exact_title_reference_coverage"]["value"] == 0.5
    assert result["automatic"]["source_location_validity"]["value"] == 0.5


def test_paired_comparison_requires_same_explicitly_reviewed_reference_targets():
    cases = [{"case_id": name, "variant_id": name, "card": {"answer": "x"}} for name in ["a", "b"]]
    variants = [{"id": "a", "name": "Baseline"}, {"id": "b", "name": "Candidate"}]
    reference = {"reference_concepts": [{"id": "x", "label": "X"}]}
    assert summarize(cases, [], reference, variants)["comparisons"][0]["conclusion"] == "incomplete"
    judgments = [
        {
            "case_id": "a",
            "reviewer": "Reviewer",
            "origin": "human",
            "label": "incorrect",
            "dimensions": {},
            "reference_concept_ids": ["x"],
        },
        {
            "case_id": "b",
            "reviewer": "Reviewer",
            "origin": "human",
            "label": "correct_useful",
            "dimensions": {},
            "reference_concept_ids": ["x"],
        },
    ]
    comparison = summarize(cases, judgments, reference, variants)["comparisons"][0]
    assert comparison["paired_target_acceptance_delta"] == 1
    assert comparison["paired_reference_concepts"] == ["x"]
    assert comparison["conclusion"] == "improved"


def test_dataset_rejects_fabricated_or_inconsistent_reference_declarations():
    with pytest.raises(ValueError, match="reviewer"):
        DatasetInput(name="Not actually reviewed", provenance="human_reference")
    with pytest.raises(ValueError, match="existing reference"):
        DatasetInput(
            name="Broken",
            reference_cards=[{"id": "a", "question": "Q", "concept_ids": ["missing"]}],
        )


def test_dataset_roundtrip_blind_cases_and_append_only_judgments(
    api_client, course, extracted_source
):
    created = api_client.post(
        "/api/evaluations/datasets",
        json={
            "name": "Synthetic right triangle",
            "course_id": course["id"],
            "provenance": "synthetic",
            "reference_concepts": [
                {"id": "continuity", "label": "Continuity", "assumptions": ["real domain"]}
            ],
        },
    )
    assert created.status_code == 201, created.text
    dataset = created.json()
    exported = api_client.get(f"/api/evaluations/datasets/{dataset['id']}/export")
    imported = api_client.post("/api/evaluations/datasets/import", json=exported.json())
    assert imported.status_code == 201
    assert imported.json()["reference_concepts"] == dataset["reference_concepts"]
    # A completed extraction run can be explicitly captured for structural review.
    card = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={"question": "What is continuity?", "answer": "A local limiting property."},
    ).json()
    result = api_client.post(
        f"/api/evaluations/datasets/{dataset['id']}/experiments",
        json={
            "name": "Recorded local state",
            "variants": [{"name": "Captured", "run_id": extracted_source["run"]["id"]}],
        },
    )
    assert result.status_code == 202, result.text
    experiment = result.json()
    assert experiment["status"] == "completed"
    cases = api_client.get(
        f"/api/evaluations/experiments/{experiment['id']}/cases?blind=true"
    ).json()
    assert len(cases) == 1 and "variant_id" not in cases[0]
    assert "id" not in cases[0]["card"] and "checks" not in cases[0]
    payload = {
        "case_id": cases[0]["case_id"],
        "label": "needs_improvement",
        "origin": "synthetic",
        "reviewer": "Controlled fixture",
        "reference_concept_ids": ["continuity"],
        "dimensions": {"factual_correct": True, "atomic": False},
    }
    assert (
        api_client.post(
            f"/api/evaluations/experiments/{experiment['id']}/judgments", json=payload
        ).status_code
        == 201
    )
    payload["label"] = "correct_useful"
    assert (
        api_client.post(
            f"/api/evaluations/experiments/{experiment['id']}/judgments", json=payload
        ).status_code
        == 201
    )
    report = api_client.get(f"/api/evaluations/experiments/{experiment['id']}/report").json()
    assert len(report["judgments"]) == 2
    assert report["metrics"]["variants"][0]["reviews"]["synthetic"]["judgments"] == 1
    assert report["metrics"]["variants"][0]["reviews"]["human"]["acceptance"]["value"] is None
    # Immutable cases survive subsequent user editing; dataset edits create a new version.
    before = copy.deepcopy(report["cases"])
    api_client.patch(f"/api/cards/{card['id']}", json={"question": "Changed later"})
    api_client.patch(f"/api/evaluations/datasets/{dataset['id']}", json={"reference_concepts": []})
    after = api_client.get(f"/api/evaluations/experiments/{experiment['id']}/report").json()
    assert after["cases"] == before
    assert after["reference_snapshot"]["reference_concepts"]


@pytest.fixture
def executed_pair(api_client, course):
    """Controlled human-input fixtures verify provenance, not live accuracy."""
    from pathlib import Path

    from sqlalchemy import select
    from support.controlled_provider import ControlledProvider

    from anki_generator.database.entities import Document, Run
    from anki_generator.database.evaluation_entities import EvaluationExperiment
    from anki_generator.database.source_entities import SelectedSourceRegion, SourceCorrection
    from anki_generator.services.settings import get_settings

    rt = api_client.app.state.runtime
    rt.provider_kind = "injected_test_provider"
    providers = {}

    class VariantProvider(ControlledProvider):
        def __init__(self, detail):
            super().__init__()
            self.detail = detail

        def structured(self, stage, payload, schema, **kwargs):
            result = super().structured(stage, payload, schema, **kwargs)
            if stage == "generation":
                if self.detail == "detailed":
                    result.data.cards[0].answer += " The triangle must have a right angle."
                if payload.get("available_media"):
                    result.data.cards[0].media = [payload["available_media"][-1]]
            return result

    def factory(key, config):
        provider = VariantProvider(config["criteria"]["answer_detail"])
        providers[provider.detail] = provider
        return provider

    rt.runner.provider_factory = factory
    rt.secrets.set("controlled-offline-key")
    settings = get_settings(rt.sessions).model_dump()
    original = (Path(__file__).parents[1] / "fixtures/e2e/01-lecture.pdf").read_bytes()
    response = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", ("lecture.pdf", original, "application/pdf"))],
        data={"category": "lecture", "authority": "official"},
    )
    assert response.status_code == 201, response.text
    document = response.json()["documents"][0]
    extraction = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"mode": "extract"}
    ).json()
    rt.runner.run_now(extraction["id"])
    response = api_client.post(
        f"/api/documents/{document['id']}/regions",
        json={"page_number": 1, "bbox": [80, 210, 470, 500], "dpi": 150},
    )
    assert response.status_code == 201, response.text
    crop = response.json()
    crop_bytes = api_client.get(crop["image_url"]).content
    corrected = "For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is necessary."
    response = api_client.post(
        f"/api/documents/{document['id']}/pages/1/corrections",
        json={"text": corrected, "verified": True, "reason": "Simulated expert-input fixture"},
    )
    assert response.status_code == 201, response.text
    dataset = api_client.post(
        "/api/evaluations/datasets",
        json={
            "name": "Executed synthetic paired comparison",
            "course_id": course["id"],
            "provenance": "synthetic",
            "reference_concepts": [{"id": "pythagoras", "label": "Pythagorean theorem"}],
        },
    ).json()
    response = api_client.post(
        f"/api/evaluations/datasets/{dataset['id']}/experiments",
        json={
            "name": "Executed comparison",
            "consent": True,
            "variants": [
                {
                    "name": "Baseline",
                    "config": {
                        "criteria": {"answer_detail": "concise"},
                        "processing": {"concurrency": 1},
                        "prompt_overrides": {
                            "knowledge": "Preserve source assumptions. Version A."
                        },
                    },
                },
                {
                    "name": "Candidate",
                    "config": {
                        "criteria": {"answer_detail": "detailed"},
                        "processing": {"concurrency": 2},
                        "prompt_overrides": {
                            "knowledge": "Preserve source assumptions. Version B."
                        },
                    },
                },
            ],
        },
    )
    assert response.status_code == 202, response.text
    experiment = response.json()
    identifiers = [variant["run_id"] for variant in experiment["variants"]]
    with rt.sessions() as session:
        runs = [session.get(Run, identifier) for identifier in identifiers]
        assert all(run.status == "queued" for run in runs)
        assert len({run.course_id for run in runs}) == 2
        assert course["id"] not in {run.course_id for run in runs}
        assert (
            runs[0].config["prompt_hashes"]["knowledge"]
            != runs[1].config["prompt_hashes"]["knowledge"]
        )
        assert {run.config["criteria"]["answer_detail"] for run in runs} == {"concise", "detailed"}
        for run in runs:
            clone = session.scalar(select(Document).where(Document.course_id == run.course_id))
            copied = session.scalar(
                select(SourceCorrection).where(SourceCorrection.document_id == clone.id)
            )
            selected = session.scalar(
                select(SelectedSourceRegion).where(SelectedSourceRegion.document_id == clone.id)
            )
            assert clone.sha256 == document["sha256"]
            assert copied.text == corrected and copied.verified
            assert selected.id != crop["id"] and selected.bbox == crop["bbox"]
            assert (rt.data_root / selected.image_path).read_bytes() == crop_bytes
            assert run.inputs[0]["selected_region_ids"] == [selected.id]
    # An edit to the original after preparation must not enter either clone.
    assert (
        api_client.post(
            f"/api/documents/{document['id']}/pages/1/corrections",
            json={
                "text": "Later original-course correction",
                "verified": True,
                "replace_verified": True,
                "expected_revision": 1,
                "reason": "Simulated later checked correction",
            },
        ).status_code
        == 201
    )
    for identifier in identifiers:
        rt.runner.run_now(identifier)
        with rt.sessions() as session:
            run = session.get(Run, identifier)
            assert run.status == "completed", run.error
            clone = session.scalar(select(Document).where(Document.course_id == run.course_id))
            assert clone.extraction["artifact_dir"].startswith(f"artifacts/{clone.id}/")
            assert (
                session.scalar(
                    select(SourceCorrection).where(SourceCorrection.document_id == clone.id)
                ).text
                == corrected
            )
            # DB read proves capture happened inside the completion hook, before GET.
            captured = session.get(EvaluationExperiment, experiment["id"])
            variant = next(item for item in captured.variants if item["run_id"] == identifier)
            assert variant.get("snapshotted")
            assert any(case["variant_id"] == variant["id"] for case in captured.cases)
    assert get_settings(rt.sessions).model_dump() == settings
    for provider in providers.values():
        assert provider.calls["generation"] and provider.calls["source_audit"]
        assert provider.calls["interpretation"] == 0
        assert any(
            corrected in payload.get("text", "")
            for stage, payload in provider.payloads
            if stage == "knowledge"
        )
    return rt, dataset, experiment


def test_executed_pair_isolates_sources_overrides_and_auto_captures_snapshots(
    api_client, course, executed_pair
):
    from sqlalchemy import select

    from anki_generator.database.entities import Card

    rt, dataset, experiment = executed_pair
    report = api_client.get(f"/api/evaluations/experiments/{experiment['id']}/report").json()
    assert report["status"] == "completed" and len(report["cases"]) == 2
    assert all(variant["execution"] == "configured_pipeline" for variant in report["variants"])
    assert all(
        variant["provider_transport"] == "injected_test_provider" for variant in report["variants"]
    )
    assert all(case["card"]["image_refs"] for case in report["cases"])
    assert len({case["card"]["answer"] for case in report["cases"]}) == 2
    before = copy.deepcopy(report["cases"])
    with rt.sessions() as session:
        card_id = session.scalar(select(Card.id).where(Card.course_id != course["id"]))
    assert (
        api_client.patch(
            f"/api/cards/{card_id}", json={"question": "Edited after capture"}
        ).status_code
        == 200
    )
    after = api_client.get(f"/api/evaluations/experiments/{experiment['id']}/report").json()
    assert after["cases"] == before
    assert after["reference_snapshot"]["version"] == dataset["version"]


def test_promotion_preserves_origin_and_rejects_synthetic_labels(api_client, executed_pair):
    _, dataset, experiment = executed_pair
    cases = api_client.get(
        f"/api/evaluations/experiments/{experiment['id']}/cases?blind=false"
    ).json()
    identifier = cases[0]["case_id"]
    judgment = {
        "case_id": identifier,
        "label": "correct_useful",
        "origin": "synthetic",
        "reviewer": "Controlled fixture",
        "reference_concept_ids": ["pythagoras"],
        "rationale": "Workflow fixture, not expert acceptance evidence",
    }
    assert (
        api_client.post(
            f"/api/evaluations/experiments/{experiment['id']}/judgments", json=judgment
        ).status_code
        == 201
    )
    denied = api_client.post(
        f"/api/evaluations/experiments/{experiment['id']}/promote",
        json={"case_ids": [identifier], "confirm": True},
    )
    assert denied.status_code == 400 and "actual human-reviewed" in denied.json()["detail"]
    # Exercise explicit human-input provenance. This simulated input is not a real expert study.
    judgment.update(origin="human", reviewer="Simulated human-input test", independent=True)
    assert (
        api_client.post(
            f"/api/evaluations/experiments/{experiment['id']}/judgments", json=judgment
        ).status_code
        == 201
    )
    response = api_client.post(
        f"/api/evaluations/experiments/{experiment['id']}/promote",
        json={"case_ids": [identifier], "confirm": True, "reviewer": judgment["reviewer"]},
    )
    assert response.status_code == 200, response.text
    current = api_client.get(f"/api/evaluations/datasets/{dataset['id']}").json()
    assert current["version"] > dataset["version"]
    reference = next(item for item in current["reference_cards"] if item["id"] == identifier)
    assert reference["label_origin"] == "human" and reference["independent"]
    assert reference["reviewer"] == judgment["reviewer"] and reference["sources"]
    report = api_client.get(f"/api/evaluations/experiments/{experiment['id']}/report").json()
    assert report["reference_snapshot"]["version"] == dataset["version"]
    assert len(report["judgments"]) == 2


@pytest.mark.parametrize("change", ["category", "authority", "correction"])
def test_experiment_refuses_changed_reference_source_state(
    api_client, course, extracted_source, change
):
    document_id = extracted_source["document"]["id"]
    dataset = api_client.post(
        "/api/evaluations/datasets",
        json={
            "name": "Frozen synthetic sources",
            "course_id": course["id"],
            "provenance": "synthetic",
        },
    ).json()
    if change == "correction":
        response = api_client.post(
            f"/api/documents/{document_id}/pages/1/corrections",
            json={"text": "A new unreviewed transcription", "verified": False},
        )
        assert response.status_code == 201
    else:
        response = api_client.patch(
            f"/api/documents/{document_id}",
            json={change: "exercises" if change == "category" else "student"},
        )
        assert response.status_code == 200
    response = api_client.post(
        f"/api/evaluations/datasets/{dataset['id']}/experiments",
        json={"name": "Stale references", "consent": True, "variants": [{"name": "Attempt"}]},
    )
    assert response.status_code == 400
    assert "changed" in response.json()["detail"]


def test_experiment_refuses_new_crop_after_reference_version(api_client, course):
    from pathlib import Path

    rt = api_client.app.state.runtime
    response = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[
            (
                "files",
                (
                    "lecture.pdf",
                    (Path(__file__).parents[1] / "fixtures/e2e/01-lecture.pdf").read_bytes(),
                    "application/pdf",
                ),
            )
        ],
    )
    identifier = response.json()["documents"][0]["id"]
    run = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"}).json()
    rt.runner.run_now(run["id"])
    dataset = api_client.post(
        "/api/evaluations/datasets",
        json={
            "name": "Frozen region choices",
            "course_id": course["id"],
            "provenance": "synthetic",
        },
    ).json()
    selected = api_client.post(
        f"/api/documents/{identifier}/regions",
        json={"page_number": 1, "bbox": [80, 210, 470, 500], "dpi": 150},
    )
    assert selected.status_code == 201, selected.text
    response = api_client.post(
        f"/api/evaluations/datasets/{dataset['id']}/experiments",
        json={
            "name": "Changed selected evidence",
            "consent": True,
            "variants": [{"name": "Attempt"}],
        },
    )
    assert response.status_code == 400
    assert "changed" in response.json()["detail"]


def _queued_evaluation(api_client, course):
    from support.controlled_provider import ControlledProvider

    rt = api_client.app.state.runtime
    rt.provider_kind = "injected_test_provider"
    provider = ControlledProvider()
    rt.runner.provider_factory = lambda key, config: provider
    rt.secrets.set("isolated-offline-provider-key")
    response = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[
            ("files", ("lecture.txt", b"For a right triangle, a^2 + b^2 = c^2.\n", "text/plain"))
        ],
    )
    assert response.status_code == 201
    dataset = api_client.post(
        "/api/evaluations/datasets",
        json={
            "name": "Completion transaction fixture",
            "course_id": course["id"],
            "provenance": "synthetic",
        },
    ).json()
    response = api_client.post(
        f"/api/evaluations/datasets/{dataset['id']}/experiments",
        json={
            "name": "Completion boundary",
            "consent": True,
            "variants": [{"name": "Actual pipeline"}],
        },
    )
    assert response.status_code == 202, response.text
    experiment = response.json()
    return rt, experiment, experiment["variants"][0]["run_id"]


def test_capture_failure_never_publishes_completed_without_frozen_cases(
    api_client, course, monkeypatch
):
    from anki_generator.database.entities import Run
    from anki_generator.database.evaluation_entities import EvaluationExperiment
    from anki_generator.evaluation import service

    rt, experiment, identifier = _queued_evaluation(api_client, course)
    refresh = service._refresh_in_session

    def fail_capture(session, experiment_id):
        assert session.get(Run, identifier).status == "completed"
        raise ValueError("Injected evaluation capture failure")

    monkeypatch.setattr(service, "_refresh_in_session", fail_capture)
    rt.runner.run_now(identifier)
    with rt.sessions() as session:
        run = session.get(Run, identifier)
        frozen = session.get(EvaluationExperiment, experiment["id"])
        assert run.status == "failed" and "capture failure" in run.error
        assert frozen.cases == []
        assert not frozen.variants[0].get("snapshotted")
    monkeypatch.setattr(service, "_refresh_in_session", refresh)
    rt.runner.retry(identifier)
    rt.runner.run_now(identifier)
    with rt.sessions() as session:
        assert session.get(Run, identifier).status == "completed"
        frozen = session.get(EvaluationExperiment, experiment["id"])
        assert frozen.variants[0]["snapshotted"] and len(frozen.cases) == 1


def test_capture_blocks_edit_until_completion_and_keeps_pre_edit_snapshot(
    api_client, course, monkeypatch
):
    import threading

    from sqlalchemy import select

    from anki_generator.database.entities import Card, Run
    from anki_generator.evaluation import service

    rt, experiment, identifier = _queued_evaluation(api_client, course)
    entered, release = threading.Event(), threading.Event()
    original = service.card_case

    def blocked_capture(*args):
        entered.set()
        assert release.wait(5), "The test did not release the completion boundary"
        return original(*args)

    monkeypatch.setattr(service, "card_case", blocked_capture)
    worker = threading.Thread(target=rt.runner.run_now, args=(identifier,))
    worker.start()
    try:
        assert entered.wait(5)
        with rt.sessions() as session:
            run = session.get(Run, identifier)
            assert run.status == "running"
            card = session.scalar(select(Card).where(Card.course_id == run.course_id))
            card_id, initial = card.id, card.question
        denied = api_client.patch(
            f"/api/cards/{card_id}", json={"question": "Concurrent newer edit"}
        )
        assert denied.status_code == 400
        assert "active processing run" in denied.json()["detail"]
    finally:
        release.set()
        worker.join(8)
    assert not worker.is_alive()
    assert api_client.get(f"/api/runs/{identifier}").json()["status"] == "completed"
    assert (
        api_client.patch(
            f"/api/cards/{card_id}", json={"question": "Concurrent newer edit"}
        ).status_code
        == 200
    )
    report = api_client.get(f"/api/evaluations/experiments/{experiment['id']}/report").json()
    assert report["cases"][0]["card"]["question"] == initial
    assert api_client.get(f"/api/cards/{card_id}").json()["question"] == "Concurrent newer edit"
