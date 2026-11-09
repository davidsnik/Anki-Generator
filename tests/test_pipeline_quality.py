"""New source/identity/concurrency boundaries; external inference is controlled."""
# ruff: noqa: F811 -- pytest intentionally reuses the imported shared fixture.

import json
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_pipeline_jobs import setup_course  # noqa: F401

from anki_generator.database.entities import Card, Concept, Revision, Run
from anki_generator.database.pipeline_entities import (
    IdentityAlias,
    IdentityProposal,
    SourceCoverageTarget,
)
from anki_generator.domain import ExportInput
from anki_generator.llm.provider import OpenAIProvider, ProviderError
from anki_generator.services.context_budget import (
    ContextBudgetError,
    bounded_batches,
    ensure_request_budget,
)
from anki_generator.services.export_preview import export_preview
from anki_generator.services.exporting import create_export
from anki_generator.services.identity_resolution import IdentityResolution, resolve_identity
from anki_generator.services.semantic import SemanticIndex


def test_independent_source_audit_recovers_initial_omission_and_checks_it(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    original = provider.structured
    seen = []

    def structured(stage, payload, schema, **kwargs):
        result = original(stage, payload, schema, **kwargs)
        if stage == "source_audit":
            assert "inventory" not in payload and "cards" not in payload
            target = result.data.targets[0]
            target.dimension = "assumption"
            target.concept.kind = "assumption"
            target.concept.key = "right-angle-assumption"
            target.concept.title = "Necessary right-angle assumption"
            target.concept.statement = "The right-angle assumption is necessary."
            target.concept.sources[0].quote = "The right-angle assumption is necessary."
        if stage == "target_coverage":
            seen.append(payload["targets"][0])
            # A theorem-recall card is not an assumption-recall competency.
            for assessment in result.data.assessments:
                assessment.status = "uncovered"
                assessment.card_ids = []
                assessment.missing_aspects = ["Explicitly recall the necessary assumption"]
        return result

    provider.structured = structured
    run_id = new_run()
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert run.metrics["source_coverage"]["recovered_initial_omissions"] == 1
        assert not run.metrics["coverage_complete"]
        target = session.scalar(select(SourceCoverageTarget))
        assert target.kind == "assumption" and target.status == "uncovered"
        assert target.mapped_concept_ids
        assert session.get(Concept, target.mapped_concept_ids[0]).kind == "assumption"
    assert seen


def test_parallel_real_pipeline_calls_are_bounded_and_artifacts_durable(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    lock = threading.Lock()
    active = maximum = 0
    original = provider.structured

    def structured(stage, payload, schema, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.025)
        try:
            return original(stage, payload, schema, **kwargs)
        finally:
            with lock:
                active -= 1

    provider.structured = structured
    run_id = new_run()
    with sessions.begin() as session:
        run = session.get(Run, run_id)
        run.config = {**run.config, "processing": {"concurrency": 4, "api_concurrency": 2}}
    runner.run_now(run_id)
    with sessions() as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", run.error
        assert 1 < maximum <= 2
        assert all(
            (runner.data_root / path).is_file()
            for key, path in run.checkpoints.items()
            if key.startswith("knowledge:")
        )
        assert run.usage["api_calls"] == sum(provider.calls.values())


def test_structured_call_artifacts_respect_context_budget(setup_course):
    sessions, runner, _, new_run, _ = setup_course
    identifier = new_run()
    runner.run_now(identifier)
    with sessions() as session:
        run = session.get(Run, identifier)
        assert run.status == "completed", run.error
        checked = 0
        for key, path in run.checkpoints.items():
            if key.startswith(("card-final:", "task-card:", "extraction:", "embeddings:")):
                continue
            artifact = json.loads((runner.data_root / path).read_text())
            assert artifact["context_budget"]["input_token_upper_bound"] <= 24000
            assert artifact["prompt_version"]
            checked += 1
        assert checked > 0


def test_context_refuses_irreducible_claim_without_truncation():
    with pytest.raises(ContextBudgetError, match="No source statement"):
        ensure_request_budget({"assumptions": ["∀x " * 2000]}, "prompt", {}, budget=1000)
    with pytest.raises(ContextBudgetError, match="One evidence"):
        bounded_batches([{"claim": "x" * 2000}], max_bytes=100, max_items=5)
    assert bounded_batches(["a" * 40] * 5, max_bytes=90, max_items=5) == [
        ["a" * 40] * 2,
        ["a" * 40] * 2,
        ["a" * 40],
    ]


def test_actual_embeddings_sdk_contract_and_invalid_response():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ],
            model="text-embedding-3-small",
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 12, "total_tokens": 12}),
        )

    provider = OpenAIProvider(
        "isolated", client=SimpleNamespace(embeddings=SimpleNamespace(create=create))
    )
    response = provider.embed(
        ["State the premise", "Recall the hypothesis"], model="text-embedding-3-small", dimensions=2
    )
    assert response.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert calls[0] == {
        "input": ["State the premise", "Recall the hypothesis"],
        "model": "text-embedding-3-small",
        "dimensions": 2,
        "encoding_format": "float",
    }
    assert response.usage["input_tokens"] == 12
    provider.client.embeddings.create = lambda **kwargs: SimpleNamespace(data=[], usage=None)
    with pytest.raises(ProviderError):
        provider.embed(["source"], model="text-embedding-3-small", dimensions=2)


def test_semantic_retrieval_candidates_still_need_equivalence_review():
    # Authored vectors exercise retrieval mechanics only, not live embedding quality.
    index = SemanticIndex(
        {
            "recall": [1.0, 0.0, 0.0],
            "paraphrase": [0.99, 0.01, 0.0],
            "assumption": [0.85, 0.5, 0.0],
            "procedure": [0.0, 0.0, 1.0],
        }
    )
    retrieved = index.search([1.0, 0.0, 0.0], limit=3, exclude={"recall"})
    assert [identifier for identifier, _ in retrieved][:2] == ["paraphrase", "assumption"]
    assert index.search([1.0, 0.0, 0.0], limit=2, allowed={"procedure"}) == [("procedure", 0.0)]


def test_high_confidence_semantic_rewording_keeps_concept_identity(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    first = new_run()
    runner.run_now(first)
    with sessions() as session:
        concept = session.scalar(select(Concept))
        original_id = concept.id
    original = provider.structured

    def structured(stage, payload, schema, **kwargs):
        result = original(stage, payload, schema, **kwargs)
        if stage == "knowledge":
            result.data.concepts[0].key = "right-triangle-relation"
            result.data.concepts[0].title = "Right triangle squared-side relation"
        if stage == "identity":
            result.data.relation = "same"
            result.data.existing_id = payload["retrieved_items"][0]["id"]
        return result

    provider.structured = structured
    second = new_run()
    with sessions.begin() as session:
        run = session.get(Run, second)
        run.config = {
            **run.config,
            "prompt_overrides": {"knowledge": "Reword while preserving meaning."},
        }
    runner.run_now(second)
    with sessions() as session:
        run = session.get(Run, second)
        assert run.status == "completed", run.error
        alias = session.scalar(
            select(IdentityAlias).where(IdentityAlias.semantic_key == "right-triangle-relation")
        )
        assert alias.entity_id == original_id
        assert len(list(session.scalars(select(Concept)))) == 1


def test_ambiguous_identity_blocks_anki_and_human_match_preserves_guid_history(setup_course):
    sessions, runner, _, new_run, course_id = setup_course
    runner.run_now(new_run())
    with sessions.begin() as session:
        old = session.scalar(select(Card))
        old.review_status = "approved"
        old_guid, old_id = old.note_guid, old.id
        candidate = Card(
            course_id=course_id,
            question="Rephrased target",
            answer=old.answer,
            concept_id=old.concept_id,
            sources=old.sources,
            verification_status="verified",
            review_status="approved",
        )
        session.add(candidate)
        session.flush()
        proposal = IdentityProposal(
            course_id=course_id,
            entity_type="card",
            candidate_key="renamed",
            candidate_id=candidate.id,
            reason="Two possible target matches",
            candidates=[{"id": old.id}],
            candidate_payload={},
        )
        session.add(proposal)
        session.flush()
        proposal_id, candidate_id = proposal.id, candidate.id
        preview = export_preview(session, course_id, limit=1)
        assert preview["export_blocked"] and preview["counts"]["uncertain"] == 1
        with pytest.raises(ValueError, match="ambiguous"):
            create_export(session, runner.data_root, course_id, ExportInput())
        with pytest.raises(ValueError, match="Confirm replacement"):
            resolve_identity(
                session,
                proposal_id,
                IdentityResolution(decision="match", existing_id=old.id, rationale="Same target"),
            )
    with sessions.begin() as session:
        resolve_identity(
            session,
            proposal_id,
            IdentityResolution(
                decision="match",
                existing_id=old_id,
                rationale="Reviewed original sources and exact learning target",
                replace_reviewed=True,
            ),
        )
    with sessions() as session:
        old = session.get(Card, old_id)
        assert old.note_guid == old_guid and old.question == "Rephrased target"
        assert old.revision_number == 2 and old.review_status == "pending"
        assert session.get(Card, candidate_id).archived
        assert len(list(session.scalars(select(Revision).where(Revision.card_id == old_id)))) == 2
        assert not export_preview(session, course_id)["export_blocked"]


def test_export_preview_uses_content_hash_guid_and_pagination(setup_course):
    sessions, runner, _, new_run, course_id = setup_course
    runner.run_now(new_run())
    with sessions.begin() as session:
        card = session.scalar(select(Card))
        card.review_status = "approved"
        record = create_export(session, runner.data_root, course_id, ExportInput(format="json"))
        assert export_preview(session, course_id)["counts"]["matching"] == 1
        card.answer += " Clarification."
        assert export_preview(session, course_id)["counts"]["modified"] == 1
        card.archived = True
        preview = export_preview(session, course_id, offset=0, limit=1)
        assert preview["counts"]["missing"] == 1
        assert preview["baseline_export_id"] == record.id


def test_worker_waiting_for_maintenance_lock_stops_and_restarts(setup_course):
    sessions, runner, _, new_run, _ = setup_course
    identifier = new_run(mode="extract")
    entered = threading.Event()

    class ObservedGate:
        def __init__(self):
            self.lock = threading.Lock()

        def acquire(self, *args, **kwargs):
            if threading.current_thread().name == "anki-job-scheduler" and self.lock.locked():
                entered.set()
            return self.lock.acquire(*args, **kwargs)

        def release(self):
            self.lock.release()

    runner._run_lock = ObservedGate()
    runner._run_lock.acquire()
    try:
        runner.start()
        assert entered.wait(3)
        started = time.monotonic()
        runner.stop()
        assert time.monotonic() - started < 2
        assert runner._thread is None
        with sessions() as session:
            assert session.get(Run, identifier).status == "queued"
    finally:
        runner._run_lock.release()
    runner.start()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with sessions() as session:
            if session.get(Run, identifier).status == "completed":
                break
        time.sleep(0.02)
    else:
        pytest.fail("Restarted worker did not process the persisted queue")
    runner.stop()


def test_stop_rejects_unconfirmed_thread_termination(setup_course):
    _, runner, _, _, _ = setup_course

    class StillAlive:
        def join(self, timeout):
            assert 0 < timeout <= 5

        def is_alive(self):
            return True

    runner._thread = StillAlive()
    with pytest.raises(ValueError, match="Storage was not released"):
        runner.stop()
    runner._thread = None


def test_concept_merge_preserves_secondary_mappings_and_revision_identity(setup_course):
    sessions, runner, _, new_run, course_id = setup_course
    runner.run_now(new_run())
    with sessions.begin() as session:
        card = session.scalar(select(Card))
        primary = card.concept_id
        old = Concept(course_id=course_id, title="Existing secondary target")
        candidate = Concept(course_id=course_id, title="Renamed secondary target")
        session.add_all([old, candidate])
        session.flush()
        revision = session.scalar(select(Revision).where(Revision.card_id == card.id))
        revision.snapshot = {**revision.snapshot, "concept_ids": [primary, candidate.id]}
        identity = revision.snapshot["identity_key"]
        guid = card.note_guid
        proposal = IdentityProposal(
            course_id=course_id,
            entity_type="concept",
            candidate_key="renamed-secondary",
            candidate_id=candidate.id,
        )
        session.add(proposal)
        session.flush()
        resolve_identity(
            session,
            proposal.id,
            IdentityResolution(
                decision="merge", existing_id=old.id, rationale="Same secondary competency"
            ),
        )
        latest = session.scalar(
            select(Revision).where(Revision.card_id == card.id, Revision.revision_number == 2)
        )
        assert card.concept_id == primary and card.note_guid == guid
        assert latest.snapshot["concept_ids"] == [primary, old.id]
        assert latest.snapshot["identity_key"] == identity
        assert card.verification_status == "needs_review"


def test_source_audit_keeps_distinct_statements_with_same_generic_model_key(setup_course):
    sessions, runner, provider, new_run, _ = setup_course
    original = provider.structured

    def structured(stage, payload, schema, **kwargs):
        result = original(stage, payload, schema, **kwargs)
        if stage == "source_audit":
            target = result.data.targets[0]
            target.concept.key = "generic-theorem"
            if payload["role"] == "exercises":
                target.concept.title = "Necessary hypothesis"
                target.concept.statement = "The right-angle assumption is necessary."
                target.concept.sources[0].quote = target.concept.statement
                target.competency = "Recall the required hypothesis"
        return result

    provider.structured = structured
    identifier = new_run()
    runner.run_now(identifier)
    with sessions() as session:
        run = session.get(Run, identifier)
        assert run.status == "completed", run.error
        targets = list(
            session.scalars(
                select(SourceCoverageTarget).where(SourceCoverageTarget.run_id == identifier)
            )
        )
        assert len(targets) == 2
        assert {target.statement for target in targets} == {
            "For a right triangle, a^2 + b^2 = c^2.",
            "The right-angle assumption is necessary.",
        }
        assert len({target.target_key for target in targets}) == 2
        assert len({target.mapped_concept_ids[0] for target in targets}) == 2


def test_targeted_knowledge_retry_reads_nested_visual_region_provenance():
    from types import SimpleNamespace

    from anki_generator.processing.pipeline import CoursePipeline

    pipeline = SimpleNamespace(
        request={
            "retry_stage": "knowledge",
            "document_ids": ["doc"],
            "page_numbers": [2],
            "region_ids": ["chosen"],
        }
    )
    payload = {
        "document_id": "doc",
        "page_number": 2,
        "visual_interpretations": [{"region_id": "chosen", "transcription": "A source target"}],
    }
    assert CoursePipeline._force_unit(pipeline, "knowledge", payload)
    payload["visual_interpretations"][0]["region_id"] = "unrelated"
    assert not CoursePipeline._force_unit(pipeline, "knowledge", payload)


def test_targeted_generation_retry_does_not_force_unrelated_concept_sources():
    from types import SimpleNamespace

    from anki_generator.processing.pipeline import CoursePipeline

    pipeline = SimpleNamespace(request={"retry_stage": "generation", "document_ids": ["selected"]})
    assert CoursePipeline._force_unit(
        pipeline,
        "generation",
        {"concepts": [{"sources": [{"document_id": "selected", "page_number": 1}]}]},
    )
    assert not CoursePipeline._force_unit(
        pipeline,
        "generation",
        {"concepts": [{"sources": [{"document_id": "unrelated", "page_number": 1}]}]},
    )
