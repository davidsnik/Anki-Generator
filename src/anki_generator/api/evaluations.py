"""Portable references, isolated paired runs, blind review and auditable reports."""

import copy
import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import delete, select

from anki_generator.api.courses import ensure_idle
from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Course, Run, new_id
from anki_generator.database.evaluation_entities import (
    EvaluationAnnotation,
    EvaluationDataset,
    EvaluationExperiment,
    EvaluationJudgment,
)
from anki_generator.domain import InputModel, RunInput
from anki_generator.evaluation.contracts import (
    AnnotationInput,
    DatasetInput,
    ExperimentInput,
    JudgmentInput,
    ReferenceCard,
)
from anki_generator.evaluation.service import (
    blind_cases,
    clone_course,
    refresh_experiment,
    source_manifest,
)
from anki_generator.services.records import record_dict, require

router = APIRouter(prefix="/api/evaluations")


def dataset_view(session: Any, dataset: EvaluationDataset) -> dict[str, Any]:
    result = {**record_dict(dataset), **dataset.data, "version": dataset.version}
    result["annotations"] = [
        *dataset.data.get("annotations", []),
        *[
            record_dict(item)
            for item in session.scalars(
                select(EvaluationAnnotation)
                .where(EvaluationAnnotation.dataset_id == dataset.id)
                .order_by(EvaluationAnnotation.created_at)
            )
        ],
    ]
    result["source_manifest"] = dataset.source_manifest
    return result


@router.get("/datasets")
def list_datasets(request: Request) -> list[dict]:
    with runtime(request).sessions() as session:
        return [
            dataset_view(session, item)
            for item in session.scalars(
                select(EvaluationDataset).order_by(EvaluationDataset.updated_at.desc())
            )
        ]


@router.post("/datasets", status_code=201)
def create_dataset(request: Request, values: DatasetInput) -> dict:
    with runtime(request).sessions.begin() as session:
        manifest = [item for item in values.sources if "sha256" in item and "relative_path" in item]
        if values.course_id:
            require(session, Course, values.course_id)
            manifest = source_manifest(session, values.course_id)
        dataset = EvaluationDataset(
            name=values.name.strip(),
            description=values.description,
            provenance=values.provenance,
            course_id=values.course_id,
            version=values.version,
            data=values.model_dump(),
            source_manifest=manifest,
        )
        if not dataset.name:
            raise ValueError("Enter a benchmark name")
        session.add(dataset)
        session.flush()
        return dataset_view(session, dataset)


@router.post("/datasets/import", status_code=201)
def import_dataset(request: Request, values: DatasetInput) -> dict:
    # Portable references can be imported before their source course exists.
    with runtime(request).sessions() as session:
        if values.course_id and session.get(Course, values.course_id) is None:
            values = values.model_copy(update={"course_id": None})
    return create_dataset(request, values)


@router.get("/datasets/{dataset_id}")
def get_dataset(request: Request, dataset_id: str) -> dict:
    with runtime(request).sessions() as session:
        return dataset_view(session, require(session, EvaluationDataset, dataset_id))


@router.patch("/datasets/{dataset_id}")
def update_dataset(
    request: Request, dataset_id: str, changes: Annotated[dict[str, Any], Body()]
) -> dict:
    with runtime(request).sessions.begin() as session:
        dataset = require(session, EvaluationDataset, dataset_id)
        changes = dict(changes)
        expected = changes.pop("expected_version", None)
        if expected is not None and expected != dataset.version:
            raise ValueError("Benchmark changed since opening; reload before saving")
        values = DatasetInput.model_validate({**dataset.data, **changes})
        if values.course_id:
            require(session, Course, values.course_id)
        dataset.version += 1
        dataset.name, dataset.description, dataset.provenance = (
            values.name,
            values.description,
            values.provenance,
        )
        dataset.course_id = values.course_id
        dataset.data = {**values.model_dump(), "version": dataset.version}
        dataset.source_manifest = (
            source_manifest(session, values.course_id) if values.course_id else []
        )
        return dataset_view(session, dataset)


@router.delete("/datasets/{dataset_id}")
def delete_dataset(request: Request, dataset_id: str) -> dict:
    with runtime(request).sessions.begin() as session:
        require(session, EvaluationDataset, dataset_id)
        session.execute(delete(EvaluationDataset).where(EvaluationDataset.id == dataset_id))
    return {"deleted": True}


@router.get("/datasets/{dataset_id}/export")
def export_dataset(request: Request, dataset_id: str) -> Response:
    with runtime(request).sessions() as session:
        result = dataset_view(session, require(session, EvaluationDataset, dataset_id))
        payload = {key: result[key] for key in DatasetInput.model_fields if key in result}
        payload["sources"] = result["source_manifest"] or payload.get("sources", [])
    return Response(
        json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="evaluation-dataset.json"'},
    )


@router.post("/datasets/{dataset_id}/annotations", status_code=201)
def add_annotation(request: Request, dataset_id: str, values: AnnotationInput) -> dict:
    with runtime(request).sessions.begin() as session:
        dataset = require(session, EvaluationDataset, dataset_id)
        annotation = EvaluationAnnotation(dataset_id=dataset.id, **values.model_dump())
        session.add(annotation)
        session.flush()
        dataset.version += 1
        return record_dict(annotation)


@router.post("/datasets/{dataset_id}/experiments", status_code=202)
def create_experiment(request: Request, dataset_id: str, values: ExperimentInput) -> dict:
    from anki_generator.services.run_submission import submit_run

    rt = runtime(request)
    with rt.sessions() as session:
        dataset = require(session, EvaluationDataset, dataset_id)
        reference = copy.deepcopy(dataset_view(session, dataset))
        course_id = values.course_id or dataset.course_id
        if not course_id:
            raise ValueError("Choose the source course for this experiment")
        require(session, Course, course_id)
        ensure_idle(session, course_id)
        manifest = source_manifest(session, course_id)
        expected = {json.dumps(item, sort_keys=True) for item in dataset.source_manifest}
        actual = {json.dumps(item, sort_keys=True) for item in manifest}
        if expected and expected != actual:
            raise ValueError(
                "Sources, roles, links, corrections or crops changed; update the reference dataset "
                "version before comparing"
            )
        reference["source_manifest"] = manifest
        for variant in values.variants:
            if variant.run_id:
                run = require(session, Run, variant.run_id)
                if run.course_id != course_id:
                    raise ValueError("Existing runs must belong to the selected source course")
                if run.status != "completed":
                    raise ValueError("Capture only completed existing runs")
                if variant.config:
                    raise ValueError("Configuration overrides require executing a new variant")
                from anki_generator.database.entities import Document
                from anki_generator.services.source_corrections import snapshot_source_state

                current = {
                    item.id: item
                    for item in session.scalars(
                        select(Document).where(Document.course_id == course_id)
                    )
                }
                if {
                    item.get("document_id", item.get("id")) for item in run.inputs
                } != current.keys():
                    raise ValueError("The captured run used a different source set")
                for item in run.inputs:
                    source = current[item.get("document_id", item.get("id"))]
                    actual_source = {
                        key: getattr(source, key)
                        for key in ("sha256", "category", "authority", "linked_document_id")
                    }
                    actual_source.update(snapshot_source_state(session, source))
                    if any(
                        actual_source[key] != value
                        for key, value in item.items()
                        if key in actual_source
                    ):
                        raise ValueError(
                            "Captured run sources changed; use a matching reference version "
                            "and processing run"
                        )
                    if "source_revision" not in item and (
                        actual_source["correction_count"] or actual_source["selected_region_ids"]
                    ):
                        raise ValueError(
                            "Legacy run predates these human corrections; "
                            "execute a fresh comparison run"
                        )
    if any(not variant.run_id for variant in values.variants):
        if not values.consent or not rt.secrets.get():
            raise ValueError(
                "Configure a key and confirm external processing to execute evaluation variants"
            )
    variants, cloned_ids = [], []
    try:
        for variant in values.variants:
            if variant.run_id:
                run_id = variant.run_id
            else:
                clone_id = clone_course(rt, course_id, variant.name)
                cloned_ids.append(clone_id)
                run = submit_run(
                    rt, clone_id, RunInput(consent=True), variant.config, enqueue=False
                )
                run_id = run["id"]
            variants.append(
                {
                    "id": new_id(),
                    "name": variant.name,
                    "run_id": run_id,
                    "requested_config": variant.config,
                    "status": "queued",
                    "execution": "captured" if variant.run_id else "configured_pipeline",
                    "provider_transport": rt.provider_kind,
                    "snapshot_kind": "current_course_at_capture"
                    if variant.run_id
                    else "isolated_pipeline_output",
                }
            )
        with rt.sessions.begin() as session:
            if source_manifest(session, course_id) != manifest:
                raise ValueError(
                    "Course sources changed while preparing variants; "
                    "retry against a single frozen version"
                )
            experiment = EvaluationExperiment(
                dataset_id=dataset_id,
                name=values.name,
                reference_snapshot=reference,
                variants=variants,
                blind=values.blind,
            )
            session.add(experiment)
            session.flush()
            identifier = experiment.id
        for variant in variants:
            if variant["execution"] != "captured":
                rt.runner.enqueue(variant["run_id"])
        return refresh_experiment(rt, identifier)
    except Exception:
        # Clones contain no user-created records; preserve the source course.
        from anki_generator.database.entities import Document
        from anki_generator.services.cleanup import remove_owned_directory

        with rt.sessions.begin() as session:
            for clone_id in cloned_ids:
                document_ids = list(
                    session.scalars(select(Document.id).where(Document.course_id == clone_id))
                )
                session.execute(delete(Course).where(Course.id == clone_id))
                for document_id in document_ids:
                    remove_owned_directory(rt.data_root, f"artifacts/{document_id}")
        raise


@router.get("/experiments")
def list_experiments(request: Request) -> list[dict]:
    rt = runtime(request)
    with rt.sessions() as session:
        ids = list(
            session.scalars(
                select(EvaluationExperiment.id)
                .order_by(EvaluationExperiment.created_at.desc())
                .limit(200)
            )
        )
    return [experiment_summary(refresh_experiment(rt, identifier)) for identifier in ids]


def experiment_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in result.items() if key not in {"cases", "judgments"}},
        "case_count": len(result["cases"]),
        "judgment_count": len(result["judgments"]),
    }


@router.get("/experiments/{experiment_id}")
def get_experiment(request: Request, experiment_id: str) -> dict:
    return experiment_summary(refresh_experiment(runtime(request), experiment_id))


@router.get("/experiments/{experiment_id}/cases")
def get_cases(
    request: Request,
    experiment_id: str,
    blind: bool = True,
    offset: int | None = Query(default=None, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> Any:
    experiment = refresh_experiment(runtime(request), experiment_id)
    cases = blind_cases(experiment, blind)
    if offset is None:
        return cases
    selected = cases[offset : offset + limit]
    for case in selected:
        case["judgments"] = [
            item for item in experiment["judgments"] if item["case_id"] == case["case_id"]
        ][-20:]
    return {
        "items": selected,
        "total": len(cases),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(selected) < len(cases),
    }


@router.get("/experiments/{experiment_id}/judgments")
def get_judgments(
    request: Request,
    experiment_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    from sqlalchemy import func

    with runtime(request).sessions() as session:
        require(session, EvaluationExperiment, experiment_id)
        query = select(EvaluationJudgment).where(EvaluationJudgment.experiment_id == experiment_id)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        items = session.scalars(
            query.order_by(EvaluationJudgment.created_at.desc(), EvaluationJudgment.id)
            .offset(offset)
            .limit(limit)
        )
        return {
            "items": [record_dict(item) for item in items],
            "total": total,
            "offset": offset,
            "limit": limit,
        }


@router.get("/experiments/{experiment_id}/report")
def export_report(request: Request, experiment_id: str) -> Response:
    return Response(
        json.dumps(refresh_experiment(runtime(request), experiment_id), indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="evaluation-report.json"'},
    )


@router.post("/experiments/{experiment_id}/judgments", status_code=201)
def record_judgment(request: Request, experiment_id: str, values: JudgmentInput) -> dict:
    with runtime(request).sessions.begin() as session:
        experiment = require(session, EvaluationExperiment, experiment_id)
        if values.case_id not in {case["case_id"] for case in experiment.cases}:
            raise ValueError("Select a card snapshot belonging to this experiment")
        known = {item["id"] for item in experiment.reference_snapshot.get("reference_concepts", [])}
        if set(values.reference_concept_ids) - known:
            raise ValueError("Judgments must map to this experiment's frozen reference concepts")
        judgment = EvaluationJudgment(experiment_id=experiment.id, **values.model_dump())
        session.add(judgment)
        session.flush()
        return record_dict(judgment)


class PromoteInput(InputModel):
    case_ids: list[str] = Field(min_length=1, max_length=500)
    reviewer: str | None = None
    confirm: bool = False


@router.post("/experiments/{experiment_id}/promote")
def promote_reviewed_examples(request: Request, experiment_id: str, values: PromoteInput) -> dict:
    if not values.confirm:
        raise ValueError(
            "Confirm promotion of these human-reviewed examples into the reference dataset"
        )
    with runtime(request).sessions.begin() as session:
        experiment = require(session, EvaluationExperiment, experiment_id)
        dataset = require(session, EvaluationDataset, experiment.dataset_id)
        cases = {case["case_id"]: case for case in experiment.cases}
        if len(set(values.case_ids)) != len(values.case_ids) or set(values.case_ids) - cases.keys():
            raise ValueError("Select distinct case snapshots from this experiment")
        references = {item["id"]: item for item in dataset.data.get("reference_cards", [])}
        known = {item["id"] for item in dataset.data.get("reference_concepts", [])}
        for identifier in values.case_ids:
            query = select(EvaluationJudgment).where(
                EvaluationJudgment.experiment_id == experiment_id,
                EvaluationJudgment.case_id == identifier,
                EvaluationJudgment.origin == "human",
            )
            if values.reviewer:
                query = query.where(EvaluationJudgment.reviewer == values.reviewer)
            judgments = list(
                session.scalars(
                    query.order_by(EvaluationJudgment.created_at.desc(), EvaluationJudgment.id)
                )
            )
            by_reviewer = {}
            for judgment in judgments:
                by_reviewer.setdefault(judgment.reviewer, judgment)
            if not by_reviewer:
                raise ValueError(
                    "Only actual human-reviewed cases can be promoted; "
                    "synthetic/model labels stay separate"
                )
            if len({item.label for item in by_reviewer.values()}) > 1:
                raise ValueError(
                    "Reviewers disagree; select a reviewer or resolve "
                    "the reference judgment explicitly"
                )
            judgment = next(iter(by_reviewer.values()))
            if set(judgment.reference_concept_ids) - known:
                raise ValueError(
                    "Reference concepts changed; reconcile the benchmark mapping before promotion"
                )
            card = cases[identifier]["card"]
            references[identifier] = ReferenceCard(
                id=identifier,
                question=card["question"],
                answer=card["answer"],
                concept_ids=judgment.reference_concept_ids,
                expected_label=judgment.label,
                label_origin="human",
                dimensions=judgment.dimensions,
                rationale=judgment.rationale,
                sources=card.get("sources", []),
                reviewer=judgment.reviewer,
                independent=judgment.independent,
            ).model_dump()
        dataset.version += 1
        dataset.data = {
            **dataset.data,
            "reference_cards": list(references.values()),
            "version": dataset.version,
        }
        return dataset_view(session, dataset)
