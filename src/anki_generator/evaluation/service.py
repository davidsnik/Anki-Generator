"""Freeze paired experiments and collect real pipeline results without fake providers."""

import copy
import hashlib
import json
import random
import shutil
import threading
from typing import Any

from sqlalchemy import select, text

from anki_generator.database.entities import (
    Card,
    Concept,
    Course,
    Document,
    Page,
    Run,
    Verification,
    new_id,
)
from anki_generator.database.evaluation_entities import (
    EvaluationExperiment,
    EvaluationJudgment,
)
from anki_generator.domain import CardInput
from anki_generator.services.records import card_view, record_dict, require
from anki_generator.services.storage import safe_storage_path

from .metrics import summarize

_snapshot_lock = threading.RLock()


def source_manifest(session: Any, course_id: str) -> list[dict[str, Any]]:
    from anki_generator.database.source_entities import SelectedSourceRegion, SourceCorrection
    from anki_generator.services.source_corrections import snapshot_source_state

    result = []
    for document in session.scalars(
        select(Document).where(Document.course_id == course_id).order_by(Document.relative_path)
    ):
        corrections = [
            record_dict(item)
            for item in session.scalars(
                select(SourceCorrection)
                .where(SourceCorrection.document_id == document.id)
                .order_by(SourceCorrection.created_at, SourceCorrection.id)
            )
        ]
        crops = [
            record_dict(item)
            for item in session.scalars(
                select(SelectedSourceRegion)
                .where(SelectedSourceRegion.document_id == document.id)
                .order_by(SelectedSourceRegion.id)
            )
        ]
        result.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "relative_path": document.relative_path,
                "sha256": document.sha256,
                "category": document.category,
                "authority": document.authority,
                "linked_document_id": document.linked_document_id,
                "source_revision": snapshot_source_state(session, document)["source_revision"],
                "correction_hash": hashlib.sha256(
                    json.dumps(corrections, sort_keys=True).encode()
                ).hexdigest(),
                "selected_regions": [item["id"] for item in crops],
            }
        )
    return result


def clone_course(rt: Any, course_id: str, variant_name: str) -> str:
    allocated: list[str] = []
    try:
        return _clone_course(rt, course_id, allocated)
    except Exception:
        from anki_generator.services.cleanup import remove_owned_directory

        for identifier in allocated:
            remove_owned_directory(rt.data_root, f"artifacts/{identifier}")
        raise


def _clone_course(rt: Any, course_id: str, allocated: list[str]) -> str:
    """Isolate variants, including annotations; immutable originals may share blobs."""
    from anki_generator.database.source_entities import SelectedSourceRegion, SourceCorrection

    with rt.sessions.begin() as session:
        original = require(session, Course, course_id)
        clone = Course(
            name=original.name,
            description=original.description,
            deck_name=original.deck_name,
            language=original.language,
            criteria=copy.deepcopy(original.criteria),
            archived=True,
        )
        session.add(clone)
        session.flush()
        documents = list(session.scalars(select(Document).where(Document.course_id == course_id)))
        ids = {document.id: new_id() for document in documents}
        allocated.extend(ids.values())
        for document in documents:
            fields = record_dict(document)
            fields.update(
                id=ids[document.id],
                course_id=clone.id,
                linked_document_id=ids.get(document.linked_document_id),
            )
            fields = copy.deepcopy(fields)
            artifact = fields["extraction"].get("artifact_dir")
            if artifact:
                source = safe_storage_path(rt.data_root, artifact)
                target = rt.data_root / "artifacts" / ids[document.id] / "evaluation-source"
                if not source.is_dir():
                    raise ValueError(
                        "Source extraction artifacts are missing; re-extract the document "
                        "before starting an isolated comparison"
                    )
                if source.is_dir():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source, target, dirs_exist_ok=True)
                    fields["extraction"]["artifact_dir"] = target.relative_to(
                        rt.data_root
                    ).as_posix()
                    extraction_file = target / "extraction.json"
                    if extraction_file.is_file():
                        cached = json.loads(extraction_file.read_text(encoding="utf-8"))
                        cached["artifact_dir"] = fields["extraction"]["artifact_dir"]
                        extraction_file.write_text(json.dumps(cached), encoding="utf-8")
            session.add(Document(**fields))
            session.flush()
            for page in session.scalars(select(Page).where(Page.document_id == document.id)):
                page_fields = copy.deepcopy(record_dict(page))
                page_fields.update(id=new_id(), document_id=ids[document.id])
                session.add(Page(**page_fields))
            region_ids = {}
            for region in session.scalars(
                select(SelectedSourceRegion).where(SelectedSourceRegion.document_id == document.id)
            ):
                values = copy.deepcopy(record_dict(region))
                region_ids[region.id] = new_id()
                source = safe_storage_path(rt.data_root, region.image_path)
                target = (
                    rt.data_root
                    / "artifacts"
                    / ids[document.id]
                    / "selected"
                    / f"{region_ids[region.id]}.png"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                values.update(
                    id=region_ids[region.id],
                    document_id=ids[document.id],
                    image_path=target.relative_to(rt.data_root).as_posix(),
                )
                session.add(SelectedSourceRegion(**values))
            corrections = list(
                session.scalars(
                    select(SourceCorrection)
                    .where(SourceCorrection.document_id == document.id)
                    .order_by(SourceCorrection.created_at)
                )
            )
            correction_ids = {item.id: new_id() for item in corrections}
            for correction in corrections:
                values = copy.deepcopy(record_dict(correction))
                values.update(
                    id=correction_ids[correction.id],
                    document_id=ids[document.id],
                    region_id=region_ids.get(correction.region_id, correction.region_id),
                    supersedes_id=correction_ids.get(correction.supersedes_id),
                )
                if values["region_id"]:
                    values["scope_key"] = f"region:{values['region_id']}"
                session.add(SourceCorrection(**values))
        return clone.id


def card_case(
    session: Any, card: Card, variant_id: str, reference: dict[str, Any]
) -> dict[str, Any]:
    content = record_dict(card)
    valid_schema = True
    try:
        CardInput.model_validate({key: content[key] for key in CardInput.model_fields})
    except ValueError:
        valid_schema = False
    sources_valid = bool(card.sources)
    for source in card.sources:
        document = session.get(Document, source.get("document_id"))
        page = session.scalar(
            select(Page).where(
                Page.document_id == source.get("document_id"),
                Page.page_number == source.get("page_number"),
            )
        )
        if not document or not page or document.course_id != card.course_id:
            sources_valid = False
    concept = session.get(Concept, card.concept_id) if card.concept_id else None
    mapped = [
        item["id"]
        for item in reference.get("reference_concepts", [])
        if concept and item["label"].strip().casefold() == concept.title.strip().casefold()
    ]
    checks = [
        record_dict(item)
        for item in session.scalars(
            select(Verification).where(
                Verification.card_id == card.id,
                Verification.revision_number == card.revision_number,
            )
        )
    ]
    return {
        "case_id": new_id(),
        "variant_id": variant_id,
        "card": card_view(session, card),
        "reference_concept_ids": mapped,
        "checks": checks,
        "automatic": {"schema_valid": valid_schema, "source_locations_valid": sources_valid},
        "topic": concept.title if concept else "Unassigned",
    }


def refresh_experiment(rt: Any, experiment_id: str) -> dict[str, Any]:
    with _snapshot_lock:
        return _refresh_experiment(rt, experiment_id)


def capture_completed_run(sessions: Any, run_id: str) -> None:
    """Publish completion and immutable evaluation output in one transaction.

    All experiment refreshes acquire the snapshot lock before starting their DB
    transaction. Acquiring it before the completion write preserves that order.
    Other API connections continue seeing `running` until both changes commit.
    """
    with _snapshot_lock, sessions.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        run = require(session, Run, run_id)
        from anki_generator.orchestration.job_states import settle_completion

        if settle_completion(session, run) != "completed":
            return
        session.flush()
        ids = [
            item.id
            for item in session.execute(
                select(EvaluationExperiment.id, EvaluationExperiment.variants)
            )
            if any(variant["run_id"] == run_id for variant in item.variants)
        ]
        for identifier in ids:
            _refresh_in_session(session, identifier)


def _refresh_experiment(rt: Any, experiment_id: str) -> dict[str, Any]:
    with rt.sessions.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        return _refresh_in_session(session, experiment_id)


def _refresh_in_session(session: Any, experiment_id: str) -> dict[str, Any]:
    """Completed variants are frozen once inside the caller's transaction."""
    experiment = require(session, EvaluationExperiment, experiment_id)
    variants = copy.deepcopy(experiment.variants)
    cases = list(experiment.cases)
    for variant in variants:
        run = session.get(Run, variant["run_id"])
        if run is None:
            variant.update(status="missing", error="Source processing run was removed")
            continue
        variant.update(
            status=run.status,
            usage=run.usage,
            run_metrics=run.metrics,
            error=run.error,
            effective_config=run.config,
            source_versions=run.inputs,
        )
        if run.status == "completed" and not variant.get("snapshotted"):
            for card in session.scalars(
                select(Card)
                .where(Card.course_id == run.course_id, ~Card.archived)
                .order_by(Card.id)
            ):
                cases.append(card_case(session, card, variant["id"], experiment.reference_snapshot))
            variant["snapshotted"] = True
    experiment.variants = variants
    experiment.cases = cases
    statuses = {variant["status"] for variant in variants}
    experiment.status = (
        "completed"
        if statuses == {"completed"}
        else (
            "failed" if statuses <= {"completed", "failed", "cancelled", "missing"} else "running"
        )
    )
    judgments = [
        record_dict(item)
        for item in session.scalars(
            select(EvaluationJudgment)
            .where(EvaluationJudgment.experiment_id == experiment.id)
            .order_by(EvaluationJudgment.created_at, EvaluationJudgment.id)
        )
    ]
    experiment.metrics = summarize(cases, judgments, experiment.reference_snapshot, variants)
    return {**record_dict(experiment), "judgments": judgments}


def blind_cases(experiment: dict[str, Any], blind: bool = True) -> list[dict[str, Any]]:
    cases = copy.deepcopy(experiment["cases"])
    random.Random(experiment["random_seed"]).shuffle(cases)
    if blind:
        for case in cases:
            case.pop("variant_id", None)
            # Model/prompt/run metadata are hidden during review, including GUIDs
            # whose values could otherwise link to the comparison results.
            case.pop("checks", None)
            case["card"] = {
                key: value
                for key, value in case["card"].items()
                if key
                in {
                    "question",
                    "answer",
                    "explanation",
                    "card_type",
                    "kind",
                    "tags",
                    "sources",
                    "image_refs",
                }
            }
    return cases
