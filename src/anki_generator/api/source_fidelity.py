"""Auditable transcription corrections, selected original evidence and targeted retry."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from anki_generator.api.courses import ensure_idle
from anki_generator.api.runtime import runtime
from anki_generator.database.entities import Document, Page, new_id
from anki_generator.database.source_entities import SelectedSourceRegion, SourceCorrection
from anki_generator.domain import InputModel, RunInput
from anki_generator.ingestion.regions import render_region_safely
from anki_generator.services.records import record_dict, require
from anki_generator.services.settings import get_settings
from anki_generator.services.source_corrections import (
    apply_corrections,
    correction_history,
    invalidate_corrected_evidence,
    resolve_source_region,
    selected_region_dict,
    snapshot_source_state,
)
from anki_generator.services.storage import safe_storage_path

router = APIRouter(prefix="/api")


class CorrectionInput(InputModel):
    text: str = Field(max_length=500_000)
    verified: bool = False
    reason: str = Field(default="", max_length=10_000)
    region_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    replace_verified: bool = False


class DocumentCorrectionInput(CorrectionInput):
    page_number: int = Field(ge=1)


class RegionInput(InputModel):
    page_number: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    dpi: int = Field(default=144, ge=72, le=300)
    label: str = Field(default="", max_length=300)


class ReprocessInput(InputModel):
    page_numbers: list[int] | None = Field(default=None, max_length=2000)
    region_ids: list[str] | None = Field(default=None, max_length=4096)
    mode: Literal["extract", "interpret"] = "interpret"
    consent: bool = False
    replace_human: bool = False


@router.get("/documents/{document_id}/interpretation")
def get_interpretation(request: Request, document_id: str) -> dict:
    rt = runtime(request)
    with rt.sessions() as session:
        document = require(session, Document, document_id)
        effective = apply_corrections(session, document_id, document.extraction)
        pages = effective.get("pages", [])
        for page in pages:
            for region in page["regions"]:
                region["image_url"] = f"/api/documents/{document_id}/regions/{region['id']}"
        return {
            "document_id": document_id,
            "source_sha256": document.sha256,
            "pages": pages,
            "corrections": correction_history(session, document_id),
            **snapshot_source_state(session, document),
        }


@router.get("/documents/{document_id}/pages/{page_number}/corrections")
def get_corrections(request: Request, document_id: str, page_number: int) -> list[dict]:
    with runtime(request).sessions() as session:
        require(session, Document, document_id)
        return correction_history(session, document_id, page_number)


@router.post("/documents/{document_id}/pages/{page_number}/corrections", status_code=201)
def save_correction(
    request: Request, document_id: str, page_number: int, values: CorrectionInput
) -> dict:
    rt = runtime(request)
    try:
        with rt.sessions.begin() as session:
            document = require(session, Document, document_id)
            ensure_idle(session, document.course_id)
            page = session.scalar(
                select(Page).where(Page.document_id == document_id, Page.page_number == page_number)
            )
            if page is None:
                raise ValueError("Extract this source page before correcting its transcription")
            if (
                values.region_id
                and resolve_source_region(
                    session, document_id, page_number, values.region_id, page.regions
                )
                is None
            ):
                raise ValueError("Selected source region does not exist on this page")
            if values.region_id:
                whole = session.scalar(
                    select(SourceCorrection.id)
                    .where(
                        SourceCorrection.document_id == document_id,
                        SourceCorrection.scope_key == f"page:{page_number}",
                    )
                    .limit(1)
                )
                if whole:
                    raise ValueError(
                        "Edit the whole-page transcription; "
                        "corrected prose cannot be safely spliced by region"
                    )
            scope = f"region:{values.region_id}" if values.region_id else f"page:{page_number}"
            previous = session.scalar(
                select(SourceCorrection)
                .where(
                    SourceCorrection.document_id == document_id, SourceCorrection.scope_key == scope
                )
                .order_by(SourceCorrection.revision_number.desc())
                .limit(1)
            )
            revision = previous.revision_number if previous else 0
            if values.expected_revision is not None and values.expected_revision != revision:
                raise ValueError("Transcription changed since opening; reload before saving")
            if previous and previous.verified and not values.replace_verified:
                raise ValueError("Confirm replacement of the human-verified transcription")
            if values.verified and not values.reason.strip():
                raise ValueError("Record why the source transcription was independently checked")
            correction = SourceCorrection(
                document_id=document_id,
                page_number=page_number,
                region_id=values.region_id,
                scope_key=scope,
                source_sha256=document.sha256,
                revision_number=revision + 1,
                text=values.text,
                verified=values.verified,
                reason=values.reason,
                supersedes_id=previous.id if previous else None,
            )
            session.add(correction)
            invalidate_corrected_evidence(session, document_id, page_number)
            session.flush()
            return record_dict(correction)
    except IntegrityError as error:
        raise ValueError(
            "Another correction was saved concurrently; reload before saving"
        ) from error


@router.post("/documents/{document_id}/corrections", status_code=201)
def save_document_correction(
    request: Request, document_id: str, values: DocumentCorrectionInput
) -> dict:
    return save_correction(
        request,
        document_id,
        values.page_number,
        CorrectionInput.model_validate(values.model_dump(exclude={"page_number"})),
    )


@router.get("/documents/{document_id}/regions")
def list_regions(request: Request, document_id: str) -> list[dict]:
    with runtime(request).sessions() as session:
        require(session, Document, document_id)
        return [
            selected_region_dict(region)
            for region in session.scalars(
                select(SelectedSourceRegion)
                .where(SelectedSourceRegion.document_id == document_id)
                .order_by(SelectedSourceRegion.created_at)
            )
        ]


@router.post("/documents/{document_id}/regions", status_code=201)
def create_region(request: Request, document_id: str, values: RegionInput) -> dict:
    rt = runtime(request)
    with rt.sessions() as session:
        document = require(session, Document, document_id)
        ensure_idle(session, document.course_id)
        page = session.scalar(
            select(Page).where(
                Page.document_id == document_id, Page.page_number == values.page_number
            )
        )
        if page is None:
            raise ValueError("Extract the original source before selecting evidence")
        source_path = safe_storage_path(rt.data_root, document.storage_path)
        rendered_source = document.extraction.get("rendered_source_path")
        if rendered_source:
            source_path = safe_storage_path(
                rt.data_root, f"{document.extraction['artifact_dir']}/{rendered_source}"
            )
        identifier = new_id()
        relative = f"artifacts/{document_id}/selected/{identifier}.png"
        sha, course_id = document.sha256, document.course_id
    destination = safe_storage_path(rt.data_root, relative)
    options = get_settings(rt.sessions).extraction
    with rt.runner.resources.local(f"crop:{document_id}"):
        dimensions = render_region_safely(
            source_path,
            destination,
            page_number=values.page_number,
            bbox=values.bbox,
            dpi=values.dpi,
            options=options,
            expected_sha256=None if rendered_source else sha,
        )
    try:
        with rt.sessions.begin() as session:
            ensure_idle(session, course_id)
            current = require(session, Document, document_id)
            if current.sha256 != sha:
                raise ValueError(
                    "The source changed while the region was rendered; select it again"
                )
            region = SelectedSourceRegion(
                id=identifier,
                document_id=document_id,
                source_sha256=sha,
                page_number=values.page_number,
                bbox=values.bbox,
                image_path=relative,
                pixel_width=dimensions[0],
                pixel_height=dimensions[1],
                dpi=values.dpi,
                label=values.label,
                coordinate_system="pdf-points"
                if source_path.suffix.lower() == ".pdf"
                else "image-pixels",
            )
            session.add(region)
            session.flush()
            return selected_region_dict(region)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


@router.post("/documents/{document_id}/reprocess", status_code=202)
def reprocess_source(request: Request, document_id: str, values: ReprocessInput) -> dict:
    from anki_generator.services.run_submission import submit_run

    rt = runtime(request)
    with rt.sessions() as session:
        document = require(session, Document, document_id)
        course_id = document.course_id
        if values.replace_human and values.region_ids:
            effective = apply_corrections(session, document_id, document.extraction)
            pages = [
                page
                for page in effective.get("pages", [])
                if any(region["id"] in values.region_ids for region in page["regions"])
            ]
            if any(page.get("human_verified") for page in pages):
                raise ValueError(
                    "Replace the whole human-verified page, or edit its transcription directly"
                )
    return submit_run(
        rt,
        course_id,
        RunInput(
            document_ids=[document_id],
            page_numbers=values.page_numbers,
            region_ids=values.region_ids,
            replace_human=values.replace_human,
            mode=values.mode,
            consent=values.consent,
        ),
    )


class AssociationInput(InputModel):
    card_id: str | None = None
    concept_id: str | None = None
    expected_revision: int | None = None


@router.post("/documents/{document_id}/regions/{region_id}/associate")
def associate_region(
    request: Request, document_id: str, region_id: str, values: AssociationInput
) -> dict:
    from anki_generator.database.entities import Card, Concept
    from anki_generator.domain import CardPatch
    from anki_generator.services.records import card_view, edit_card

    rt = runtime(request)
    with rt.sessions.begin() as session:
        document = require(session, Document, document_id)
        ensure_idle(session, document.course_id)
        selected = require(session, SelectedSourceRegion, region_id)
        if selected.document_id != document_id:
            raise ValueError("Selected evidence belongs to another source")
        if not values.card_id and not values.concept_id:
            raise ValueError("Select a card or concept to associate with this evidence")
        reference = {
            "document_id": document_id,
            "page_number": selected.page_number,
            "region_id": region_id,
            "bbox": selected.bbox,
            "quote": "",
            "section": selected.label,
        }
        result = {}
        if values.card_id:
            card = require(session, Card, values.card_id)
            if card.course_id != document.course_id:
                raise ValueError("Card and selected evidence must belong to the same course")
            images = [*card.image_refs]
            if not any(r.get("region_id") == region_id for r in images):
                images.append(reference)
            # Public source views may contain read-only URLs; persisted references
            # are validated by the ordinary human-edit path.
            clean = [
                {
                    k: v
                    for k, v in r.items()
                    if k
                    in {
                        "document_id",
                        "document_name",
                        "page_number",
                        "region_id",
                        "bbox",
                        "quote",
                        "section",
                    }
                }
                for r in images
            ]
            edit_card(
                session,
                card,
                CardPatch(image_refs=clean, expected_revision=values.expected_revision),
            )
            session.flush()
            result["card"] = card_view(session, card, detail=True)
        if values.concept_id:
            concept = require(session, Concept, values.concept_id)
            if concept.course_id != document.course_id:
                raise ValueError("Concept and selected evidence must belong to the same course")
            concept.sources = [*concept.sources, reference]
            concept.coverage_status = "unresolved"
            result["concept"] = record_dict(concept)
        return result
