"""One validated submission path for the GUI and isolated paired experiments."""

from importlib.resources import files
from typing import Any

from sqlalchemy import select, text

from anki_generator.api.courses import ensure_idle
from anki_generator.database.entities import Card, Concept, Course, Document, Run
from anki_generator.domain import RunInput
from anki_generator.processing.state import digest
from anki_generator.services.model_discovery import preflight_run
from anki_generator.services.records import require, run_view
from anki_generator.services.settings import ApplicationSettings, get_settings
from anki_generator.services.task_events import add_event


def submit_run(
    rt: Any,
    course_id: str,
    values: RunInput | dict[str, Any],
    config_overrides: dict[str, Any] | None = None,
    *,
    enqueue: bool = True,
) -> dict[str, Any]:
    values = values if isinstance(values, RunInput) else RunInput.model_validate(values)
    fingerprint = digest({"request": values.model_dump(), "overrides": config_overrides or {}})
    if values.idempotency_key:
        with rt.sessions() as session:
            previous = session.scalar(
                select(Run).where(
                    Run.course_id == course_id, Run.submission_key == values.idempotency_key
                )
            )
            if previous:
                if previous.config.get("submission_fingerprint") != fingerprint:
                    raise ValueError("This submission key already belongs to a different request")
                return {**run_view(session, previous), "submission_reused": True}
    if values.mode != "extract":
        if not values.consent:
            raise ValueError(
                "Confirm that selected course excerpts, source images and semantic "
                "representations may be sent to OpenAI"
            )
        if not rt.secrets.get():
            raise ValueError("Configure an OpenAI API key in Settings before starting analysis")
    settings = get_settings(rt.sessions).model_dump()
    overrides = config_overrides or {}
    allowed = {
        "models",
        "criteria",
        "extraction",
        "processing",
        "prompt_overrides",
        "reasoning_effort",
        "max_revisions",
        "role_influence",
    }
    if set(overrides) - allowed:
        raise ValueError("Run overrides contain an unsupported setting")
    for name, value in overrides.items():
        settings[name] = {**settings[name], **value} if isinstance(value, dict) else value
    effective_settings = ApplicationSettings.model_validate(settings).model_dump()
    with rt.sessions() as session:
        require(session, Course, course_id)
        # This preliminary check must stay read-only: ensure_idle acquires the
        # SQLite writer and belongs after BEGIN IMMEDIATE plus the idempotency
        # recheck below. Otherwise a simultaneous repeat can be rejected before
        # it gets a chance to reuse the first durable submission.
        if not session.scalar(select(Document.id).where(Document.course_id == course_id).limit(1)):
            raise ValueError("Import course documents before starting processing")
    # Check access/capabilities before acquiring SQLite's writer or creating a
    # durable job. This metadata-only request sends no course material.
    preflight_run(rt, effective_settings, values.mode)
    with rt.sessions.begin() as session:
        # Serialize only the short submission transaction, including the check.
        # Network calls and extraction never occur while this writer is held.
        session.execute(text("BEGIN IMMEDIATE"))
        if values.idempotency_key:
            previous = session.scalar(
                select(Run).where(
                    Run.course_id == course_id, Run.submission_key == values.idempotency_key
                )
            )
            if previous:
                if previous.config.get("submission_fingerprint") != fingerprint:
                    raise ValueError("This submission key already belongs to a different request")
                return {**run_view(session, previous), "submission_reused": True}
        course = require(session, Course, course_id)
        ensure_idle(session, course_id)
        settings["criteria"] = course.criteria or settings["criteria"]
        if "criteria" in overrides:
            settings["criteria"] = {**settings["criteria"], **overrides["criteria"]}
        effective = ApplicationSettings.model_validate(settings).model_dump()
        effective["language"] = course.language
        effective["course_snapshot"] = {
            "name": course.name,
            "description": course.description,
            "language": course.language,
            "deck_name": course.deck_name,
        }
        effective["submission_fingerprint"] = fingerprint
        effective["prompt_hashes"] = {
            item.name.removesuffix(".txt"): digest(
                (
                    files("anki_generator.prompts").joinpath("generic.txt").read_text()
                    + "\n"
                    + effective["prompt_overrides"][item.name.removesuffix(".txt")]
                )
                if item.name.removesuffix(".txt") in effective["prompt_overrides"]
                else item.read_text()
            )
            for item in files("anki_generator.prompts").iterdir()
            if item.name.endswith(".txt")
        }
        documents = list(session.scalars(select(Document).where(Document.course_id == course_id)))
        selected_ids = getattr(values, "document_ids", None)
        if selected_ids is not None:
            if not selected_ids or set(selected_ids) - {document.id for document in documents}:
                raise ValueError("Select existing documents from this course")
        if not documents:
            raise ValueError("Import course documents before starting processing")
        if values.mode == "revise":
            if not values.card_id:
                raise ValueError("Select a card to regenerate")
            card = require(session, Card, values.card_id)
            if card.course_id != course_id:
                raise ValueError("Card belongs to another course")
            if (
                values.expected_revision is not None
                and card.revision_number != values.expected_revision
            ):
                raise ValueError(
                    "This card changed since it was selected. Reload before regeneration"
                )
            if (
                card.manually_edited or card.review_status in {"approved", "rejected"}
            ) and not values.overwrite_manual:
                raise ValueError("Confirm replacement of this human-edited or reviewed card")
        if values.topic_id and require(session, Concept, values.topic_id).course_id != course_id:
            raise ValueError("Topic belongs to another course")
        from anki_generator.services.source_corrections import snapshot_source_state

        run = Run(
            course_id=course_id,
            mode=values.mode,
            status="queued" if enqueue else "prepared",
            config=effective,
            inputs=[
                {
                    "document_id": doc.id,
                    "sha256": doc.sha256,
                    "category": doc.category,
                    "authority": doc.authority,
                    "linked_document_id": doc.linked_document_id,
                    **snapshot_source_state(session, doc),
                }
                for doc in documents
            ],
            request=values.model_dump(),
            submission_key=values.idempotency_key,
            progress={"task_counter_version": 1},
        )
        session.add(run)
        session.flush()
        add_event(
            session,
            run.id,
            "submission",
            "Task queued" if enqueue else "Task prepared",
            details={"status": run.status, "mode": run.mode},
        )
        result = run_view(session, run)
        identifier = run.id
    if enqueue:
        rt.runner.enqueue(identifier)
    return result


def retry_stage(rt: Any, run_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """A new immutable attempt reuses valid inputs and forces only selected units."""
    from anki_generator.services.source_corrections import snapshot_source_state

    allowed = {"stage", "consent", "document_ids", "page_numbers", "region_ids", "replace_human"}
    if set(values) - allowed or not values.get("stage"):
        raise ValueError("Choose a processing stage and valid source selection")
    with rt.sessions() as session:
        previous = require(session, Run, run_id)
        if previous.status not in {"failed", "completed", "cancelled", "paused"}:
            raise ValueError("Wait for this run to stop before retrying a stage")
        for item in previous.inputs:
            document = require(session, Document, item.get("document_id", item.get("id")))
            actual = {
                **{
                    key: getattr(document, key)
                    for key in ("sha256", "category", "authority", "linked_document_id")
                },
                **snapshot_source_state(session, document),
            }
            if any(actual.get(key) != value for key, value in item.items() if key in actual):
                raise ValueError(
                    "Sources changed after this run. Start a new run using current evidence"
                )
        if previous.mode != "extract" and values.get("consent") is not True:
            raise ValueError("Confirm external processing consent for this new stage attempt")
        request = {**previous.request, **values, "retry_stage": values["stage"]}
        request["idempotency_key"] = None
        request["mode"] = (
            "extract"
            if values["stage"] == "extraction" and previous.mode == "extract"
            else previous.mode
        )
        options = {
            key: previous.config[key]
            for key in (
                "models",
                "criteria",
                "extraction",
                "processing",
                "prompt_overrides",
                "reasoning_effort",
                "max_revisions",
                "role_influence",
            )
            if key in previous.config
        }
        course_id, checkpoints = previous.course_id, dict(previous.checkpoints)
        course_snapshot = previous.config.get("course_snapshot")
        language = previous.config.get("language")
    result = submit_run(rt, course_id, request, options, enqueue=False)
    order = [
        "extraction",
        "interpretation",
        "knowledge",
        "consolidation",
        "source_audit",
        "source_matching",
        "embeddings",
        "generation",
        "factual",
        "pedagogical",
        "mathematical",
        "revision",
        "identity",
        "deduplication",
        "coverage",
        "target_coverage",
    ]
    before = set(order[: order.index(values["stage"])])
    with rt.sessions.begin() as session:
        run = session.get(Run, result["id"])
        run.checkpoints = {
            key: path for key, path in checkpoints.items() if key.split(":", 1)[0] in before
        }
        run.request = {**run.request, "retry_of": run_id}
        if course_snapshot:
            run.config = {**run.config, "course_snapshot": course_snapshot, "language": language}
    rt.runner.enqueue(result["id"])
    with rt.sessions() as session:
        return run_view(session, session.get(Run, result["id"]))
