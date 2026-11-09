"""Real local ingestion and durable processing; all external calls controlled."""

from __future__ import annotations

import hashlib
import threading

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from support.controlled_provider import ControlledProvider

from anki_generator.database.entities import (
    Base,
    Card,
    Concept,
    Course,
    Document,
    Revision,
    Run,
    Stage,
    Verification,
)
from anki_generator.orchestration.runner import DurableRunner


@pytest.fixture
def setup_course(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'course.sqlite'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as session:
        course = Course(name="Euclidean geometry", deck_name="Geometry", criteria={})
        session.add(course)
        session.flush()
        for filename, role in [
            ("lecture.txt", "lecture"),
            ("exercises.txt", "exercises"),
            ("solution.txt", "solutions"),
        ]:
            path = tmp_path / "originals" / filename
            path.parent.mkdir(exist_ok=True)
            path.write_text(
                "For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is necessary.\n"
            )
            data = path.read_bytes()
            session.add(
                Document(
                    course_id=course.id,
                    filename=filename,
                    relative_path=filename,
                    category=role,
                    authority="official",
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    mime_type="text/plain",
                    storage_path=path.relative_to(tmp_path).as_posix(),
                )
            )
        session.commit()
        course_id = course.id
    provider = ControlledProvider()
    runner = DurableRunner(
        sessions, tmp_path, lambda: "test-key-never-sent", lambda key, config: provider
    )

    def new_run(**kwargs):
        with sessions() as session:
            run = Run(
                course_id=course_id,
                config={
                    "max_revisions": 1,
                    "coverage_rounds": 0,
                    "processing": {"concurrency": 1, "api_concurrency": 1},
                },
                request={"consent": True},
                **kwargs,
            )
            session.add(run)
            session.commit()
            return run.id

    yield sessions, runner, provider, new_run, course_id
    runner.stop()
    engine.dispose()


def test_full_role_aware_pipeline_persists_evidence_and_independent_reviews(setup_course):
    sessions, runner, provider, new_run, course_id = setup_course
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert run.metrics["coverage_complete"]
        assert run.metrics["concepts_covered"] == 1
        assert run.usage["api_calls"] == sum(provider.calls.values())
        assert run.usage["total_tokens"] == 30 * run.usage["api_calls"]
        assert run.checkpoints
        concept = session.scalar(select(Concept))
        assert concept.sources
        assert concept.exercise_analysis[0]["techniques"] == ["Identify hypotenuse"]
        card = session.scalar(select(Card))
        assert card.verification_status == "verified"
        assert card.review_status == "pending"
        assert card.sources[0]["page_number"] == 1
        reviews = list(session.scalars(select(Verification).where(Verification.card_id == card.id)))
        assert {r.stage for r in reviews} == {"factual", "pedagogical", "mathematical"}
        assert all(r.evidence[0]["text"] for r in reviews)
        assert session.scalar(select(Revision)).snapshot["concept_ids"] == [concept.id]
        assert len(run.inputs) == 3
    assert {payload["role"] for stage, payload in provider.payloads if stage == "knowledge"} == {
        "lecture",
        "exercises",
        "solutions",
    }
    for stage, payload in provider.payloads:
        if stage in {"factual", "mathematical"}:
            assert payload["original_evidence"][0]["text"]


def test_bad_math_is_revised_and_rechecked_with_history(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    provider.bad_first_card = True
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
        card = session.scalar(select(Card))
        assert card.verification_status == "verified"
        assert card.revision_number == 2
        stages = list(session.scalars(select(Stage).where(Stage.run_id == run_id)))
        assert next(stage for stage in stages if stage.name == "revision").status == "completed"
        assert not any(stage.status == "running" for stage in stages)
        revisions = list(session.scalars(select(Revision).order_by(Revision.revision_number)))
        assert "a^2 - b^2" in revisions[0].snapshot["answer"]
        assert "a^2 + b^2" in revisions[1].snapshot["answer"]
        assert (
            provider.calls["factual"]
            == provider.calls["pedagogical"]
            == provider.calls["mathematical"]
            == 2
        )


def test_missing_evidence_blocks_model_pass(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    provider.missing_evidence = True
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
        card = session.scalar(select(Card))
        assert card.verification_status == "needs_review"
        assert any("absent" in issue["message"] for issue in card.issues)
        assert session.get(Run, run_id).metrics["coverage_gaps"]


def test_failed_stage_retry_reuses_prior_model_checkpoints(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    provider.fail_stage = "pedagogical"
    provider.fail_once = True
    run_id = new_run()
    runner.run_now(run_id)
    calls = provider.calls.copy()
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "failed"
        assert "timeout" in run.error
        assert run.checkpoints
    runner.retry(run_id)
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
        assert len(list(session.scalars(select(Card)))) == 1
        assert len(list(session.scalars(select(Revision)))) == 1
    assert provider.calls["knowledge"] == calls["knowledge"]
    assert provider.calls["consolidation"] == calls["consolidation"]
    assert provider.calls["generation"] == calls["generation"]
    assert provider.calls["factual"] == calls["factual"]
    assert provider.calls["pedagogical"] == calls["pedagogical"] + 1


def test_pause_after_call_is_durable_and_resume_reuses_response(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    run_id = new_run()

    def pause(stage, payload):
        if stage == "knowledge":
            provider.on_call = None
            runner.pause(run_id)

    provider.on_call = pause
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "paused"
        assert any(key.startswith("knowledge:") for key in run.checkpoints)
    runner.resume(run_id)
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
    assert provider.calls["knowledge"] == 3


def test_cancellation_keeps_partial_artifacts_and_stops_new_calls(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    run_id = new_run()

    def cancel(stage, payload):
        if stage == "knowledge":
            runner.cancel(run_id)

    provider.on_call = cancel
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "cancelled"
        assert run.checkpoints
    assert provider.calls == {"knowledge": 1}
    with pytest.raises(ValueError, match="current state"):
        runner.resume(run_id)


def test_restart_marks_live_job_paused_and_preserves_stage(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    run_id = new_run()
    with sessions() as session:
        run = session.get(Run, run_id)
        run.status = "running"
        session.add(Stage(run_id=run_id, name="generation", status="running", completed=3, total=8))
        session.commit()
    runner.start()
    runner.stop()
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "paused"
        assert "interrupted" in run.error
        stage = session.scalar(select(Stage))
        assert stage.status == "paused" and stage.completed == 3


def test_no_external_calls_without_explicit_consent(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    run_id = new_run()
    with sessions() as session:
        session.get(Run, run_id).request = {"consent": False}
        session.commit()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "failed"
        assert "Confirm" in run.error
    assert not provider.calls


def test_extraction_only_does_not_need_key_or_consent(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    runner.key_getter = lambda: None
    run_id = new_run(mode="extract")
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed"
        assert all(d.extraction["pages"] for d in session.scalars(select(Document)))
    assert not provider.calls


def test_reviewed_and_manually_edited_cards_survive_regeneration(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    runner.run_now(new_run())
    with sessions() as session:
        card = session.scalar(select(Card))
        card.question = "My carefully edited question"
        card.manually_edited = True
        card.review_status = "approved"
        guid = card.note_guid
        session.commit()
    runner.run_now(new_run())
    with sessions() as session:
        card = session.scalar(select(Card))
        assert card.question == "My carefully edited question"
        assert card.review_status == "approved"
        assert card.note_guid == guid
        assert len(list(session.scalars(select(Card)))) == 1


def test_worker_processes_persisted_queue(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    run_id = new_run()
    finished = threading.Event()
    original = runner.run_now

    def execute(run):
        original(run)
        finished.set()

    runner.run_now = execute
    runner.start()
    assert finished.wait(10)
    runner.stop()
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error


def test_api_style_document_input_snapshot_executes_and_is_guarded(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    run_id = new_run(mode="extract")
    with sessions() as session:
        run = session.get(Run, run_id)
        run.inputs = [
            {
                "document_id": doc.id,
                "sha256": doc.sha256,
                "category": doc.category,
                "authority": doc.authority,
                "linked_document_id": doc.linked_document_id,
            }
            for doc in session.scalars(select(Document))
        ]
        session.commit()
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
    stale_id = new_run()
    with sessions() as session:
        run = session.get(Run, stale_id)
        doc = session.scalar(select(Document))
        run.inputs = [
            {
                "document_id": d.id,
                "sha256": d.sha256,
                "category": d.category,
                "authority": d.authority,
                "linked_document_id": d.linked_document_id,
            }
            for d in session.scalars(select(Document))
        ]
        doc.category = "personal_notes"
        session.commit()
    runner.run_now(stale_id)
    with sessions() as session:
        run = session.get(Run, stale_id)
        assert run.status == "failed" and "source changed" in run.error
    assert not provider.calls


def test_uncertain_visual_transcription_stays_flagged(setup_course, tmp_path):
    from PIL import Image, ImageDraw

    sessions, runner, provider, new_run, course_id = setup_course
    path = tmp_path / "originals" / "triangle.png"
    image = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(image).polygon([(30, 30), (30, 270), (350, 270)], outline="black", width=3)
    image.save(path)
    data = path.read_bytes()
    with sessions() as session:
        session.execute(delete(Document))
        session.add(
            Document(
                course_id=course_id,
                filename="triangle.png",
                relative_path="triangle.png",
                category="lecture",
                authority="official",
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                mime_type="image/png",
                storage_path="originals/triangle.png",
            )
        )
        session.commit()
    provider.uncertain_visual = True
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert provider.calls["interpretation"] == 1
        interpretation = session.scalar(
            select(Stage).where(Stage.run_id == run_id, Stage.name == "interpretation")
        )
        assert interpretation.status == "completed"
        assert not any(
            stage.status == "running"
            for stage in session.scalars(select(Stage).where(Stage.run_id == run_id))
        )
        assert session.scalar(select(Document)).extraction["vision_status"] == "uncertain"
        assert session.scalar(select(Card)).verification_status == "needs_review"
        assert not run.metrics["coverage_complete"]


def test_conflicting_source_claims_cannot_be_promoted_by_reviewer_agreement(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    provider.conflicting_concepts = True
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert session.scalar(select(Concept)).metadata_json["uncertain"]
        assert session.scalar(select(Card)).verification_status == "needs_review"
        assert not run.metrics["coverage_complete"]


@pytest.mark.parametrize("duplicate", [True, False])
def test_semantic_duplicate_decisions_preserve_useful_distinctions(setup_course, duplicate):
    sessions, runner, provider, new_run, _ = setup_course
    provider.extra_card = True
    provider.duplicate = duplicate
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
        cards = list(session.scalars(select(Card)))
        assert len(cards) == 2
        expected = {"verified", "duplicate"} if duplicate else {"verified"}
        assert {card.verification_status for card in cards} == expected
        comparison = session.scalar(
            select(Verification).where(Verification.stage == "deduplication")
        )
        assert comparison.verdict == ("duplicate" if duplicate else "pass")
        assert bool(comparison.details["redundant_with"]) == duplicate
    assert provider.calls["deduplication"] == 1


def test_coverage_audit_fills_explicit_mapping_gap_even_if_model_reports_no_gaps(setup_course):
    from anki_generator.llm import ModelResult

    sessions, runner, provider, new_run, _ = setup_course
    original = provider.structured
    right_angle_attempts = 0

    def structured(stage, payload, schema, **kwargs):
        nonlocal right_angle_attempts
        response = original(stage, payload, schema, **kwargs)
        data = response.data.model_dump(mode="json")
        if stage == "consolidation":
            extra = {
                **data["concepts"][0],
                "key": "right-angle",
                "title": "Right-angle assumption",
                "kind": "assumption",
                "statement": "The theorem requires a right triangle.",
            }
            data["concepts"].append(extra)
        if stage == "generation" and payload["concepts"][0]["key"] == "right-angle":
            right_angle_attempts += 1
            if right_angle_attempts == 1:
                data["cards"] = []
            else:
                data["cards"][0].update(
                    {
                        "identity_key": "right-angle:applicability",
                        "concept_keys": ["right-angle"],
                        "category": "assumption",
                        "question": "For which triangles is the Pythagorean identity valid?",
                        "answer": "Right triangles.",
                    }
                )
        return ModelResult(
            schema.model_validate(data), response.usage, response.model, response.response_id
        )

    provider.structured = structured
    run_id = new_run()
    with sessions() as session:
        run = session.get(Run, run_id)
        run.config = {**run.config, "coverage_rounds": 1}
        session.commit()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert run.metrics["coverage_complete"]
        assert run.metrics["concepts_covered"] == 2
        assert len(list(session.scalars(select(Card)))) == 2
    assert right_angle_attempts == 2 and provider.calls["coverage"] == 2


def test_partial_document_failure_stays_visible_without_losing_other_sources(
    setup_course, tmp_path
):
    sessions, runner, provider, new_run, course_id = setup_course
    path = tmp_path / "originals" / "broken.pdf"
    path.write_bytes(b"not a readable PDF")
    with sessions() as session:
        session.add(
            Document(
                course_id=course_id,
                filename="broken.pdf",
                relative_path="broken.pdf",
                category="lecture",
                authority="official",
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                size_bytes=path.stat().st_size,
                mime_type="application/pdf",
                storage_path="originals/broken.pdf",
            )
        )
        session.commit()
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert run.metrics["unresolved_sources"] == 1
        assert not run.metrics["coverage_complete"]
        broken = session.scalar(select(Document).where(Document.filename == "broken.pdf"))
        assert broken.status == "failed" and broken.warnings
        assert session.scalar(select(Card)).verification_status == "verified"


def test_card_criteria_change_reuses_unchanged_local_extraction_and_document_understanding(
    setup_course, monkeypatch
):
    sessions, runner, provider, new_run, _ = setup_course
    runner.run_now(new_run())
    prior_knowledge_calls = provider.calls["knowledge"]

    def unexpected_extraction(*args, **kwargs):
        raise AssertionError("Unchanged documents must reuse local extraction artifacts")

    monkeypatch.setattr(
        "anki_generator.ingestion.extraction.extract_document_safely", unexpected_extraction
    )
    run_id = new_run()
    with sessions() as session:
        run = session.get(Run, run_id)
        run.config = {
            **run.config,
            "criteria": {"answer_detail": "detailed", "include_explanations": False},
        }
        session.commit()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert run.usage["cached_calls"] >= 3
        assert session.scalar(select(Card)).explanation == ""
    assert provider.calls["knowledge"] == prior_knowledge_calls


def test_explicit_reprocess_reruns_only_selected_extraction(setup_course, monkeypatch):
    from anki_generator.ingestion.extraction import extract_document_safely

    sessions, runner, provider, new_run, _ = setup_course
    runner.run_now(new_run(mode="extract"))
    with sessions() as session:
        doc = session.scalar(select(Document))
        selected_id = doc.id
        doc.extraction_key = ""
        doc.status = "imported"
        doc.extraction = {**doc.extraction, "force_reprocess": True}
        session.commit()
    processed = []

    def extract(path, output, **kwargs):
        processed.append(path.name)
        return extract_document_safely(path, output, **kwargs)

    monkeypatch.setattr("anki_generator.ingestion.extraction.extract_document_safely", extract)
    run_id = new_run(mode="extract")
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
        doc = session.get(Document, selected_id)
        assert doc.extraction_key and not doc.extraction.get("force_reprocess")
        assert processed == [doc.filename]


def test_unchanged_generation_reuses_cards_without_new_generation_or_revision_calls(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    runner.run_now(new_run())
    prior = provider.calls.copy()
    with sessions() as session:
        card = session.scalar(select(Card))
        stable = card.id, card.note_guid, card.revision_number, card.question
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        assert session.get(Run, run_id).status == "completed", session.get(Run, run_id).error
        card = session.scalar(select(Card))
        assert (card.id, card.note_guid, card.revision_number, card.question) == stable
        assert len(list(session.scalars(select(Revision)))) == 1
    for stage in ["knowledge", "generation", "factual", "pedagogical", "mathematical", "revision"]:
        assert provider.calls[stage] == prior[stage]


def test_requested_revision_completes_its_persisted_stage_and_rechecks_the_card(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    runner.run_now(new_run())
    with sessions() as session:
        card_id = session.scalar(select(Card.id))
    run_id = new_run(mode="revise")
    with sessions() as session:
        run = session.get(Run, run_id)
        run.request = {**run.request, "card_id": card_id, "instruction": "Clarify the assumptions."}
        session.commit()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        stages = {
            stage.name: stage
            for stage in session.scalars(select(Stage).where(Stage.run_id == run_id))
        }
        assert stages["revision"].status == "completed"
        assert stages["revision"].completed == stages["revision"].total == 1
        assert not any(stage.status == "running" for stage in stages.values())
        assert {"factual", "pedagogical", "mathematical", "coverage"} <= set(stages)
        assert not {"knowledge", "consolidation", "generation"} & set(stages)
