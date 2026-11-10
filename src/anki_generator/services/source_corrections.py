"""Human source revisions override automatic readings without rewriting originals."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from anki_generator.database.entities import Card, Concept, Document
from anki_generator.database.source_entities import SelectedSourceRegion, SourceCorrection
from anki_generator.services.records import record_dict
from anki_generator.services.storage import safe_storage_path


def correction_history(
    session: Session, document_id: str, page_number: int | None = None
) -> list[dict]:
    query = select(SourceCorrection).where(SourceCorrection.document_id == document_id)
    if page_number is not None:
        query = query.where(SourceCorrection.page_number == page_number)
    return [
        record_dict(row)
        for row in session.scalars(
            query.order_by(SourceCorrection.created_at, SourceCorrection.revision_number)
        )
    ]


def snapshot_source_state(session: Session, document: Document) -> dict[str, Any]:
    corrections = correction_history(session, document.id)
    regions = [
        record_dict(row)
        for row in session.scalars(
            select(SelectedSourceRegion)
            .where(SelectedSourceRegion.document_id == document.id)
            .order_by(SelectedSourceRegion.id)
        )
    ]
    data = {"corrections": corrections, "regions": regions}
    return {
        "source_revision": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
        "correction_count": len(corrections),
        "selected_region_ids": [r["id"] for r in regions],
    }


def resolve_source_region(
    session: Session,
    document_id: str,
    page_number: int,
    region_id: str,
    regions: list[dict] | None = None,
) -> dict | None:
    region = next((item for item in regions or [] if item["id"] == region_id), None)
    if region is not None:
        return region
    selected = session.get(SelectedSourceRegion, region_id)
    if selected and selected.document_id == document_id and selected.page_number == page_number:
        return selected_region_dict(selected)
    return None


def selected_region_dict(region: SelectedSourceRegion) -> dict:
    return {
        **record_dict(region),
        "storage_path": region.image_path,
        "image_path": f"images/selected/{region.id}.png",
        "needs_vision": True,
        "status": "needs_review",
        "is_original_visual": True,
        "warnings": [],
        "image_url": f"/api/documents/{region.document_id}/regions/{region.id}",
    }


def _overlaps(a: list | tuple, b: list | tuple) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def apply_corrections(
    session: Session,
    document_id: str,
    extraction: dict,
    *,
    replace_human: bool = False,
    data_root: Path | None = None,
) -> dict:
    """Return effective evidence, retaining original text and every automatic reading.

    A verified page correction is authoritative for the whole transcription. A
    regional correction replaces intersecting text blocks and that region's model
    interpretation. Draft corrections remain explicitly uncertain. ``replace_human``
    bypasses effective overrides for an explicitly confirmed automatic retry only;
    it never deletes historical human revisions.
    """
    result = copy.deepcopy(extraction)
    pages = {p["page_number"]: p for p in result.get("pages", [])}
    source_hash = result.get("source_sha256")
    for selected in session.scalars(
        select(SelectedSourceRegion).where(
            SelectedSourceRegion.document_id == document_id,
            SelectedSourceRegion.source_sha256 == source_hash,
        )
    ):
        if selected.page_number not in pages:
            continue
        region = selected_region_dict(selected)
        page = pages[selected.page_number]
        if not any(item["id"] == region["id"] for item in page["regions"]):
            page["regions"].append(region)
        if data_root and result.get("artifact_dir"):
            original = safe_storage_path(data_root, selected.image_path)
            target = safe_storage_path(
                data_root, f"{result['artifact_dir']}/{region['image_path']}"
            )
            if original.is_file() and not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)
    latest: dict[str, dict] = {}
    history = correction_history(session, document_id)
    for correction in history:
        if correction["source_sha256"] == source_hash:
            latest[correction["scope_key"]] = correction
    for number, page in pages.items():
        page["original_text"] = page.get("original_text", page.get("text", ""))
        page["original_visual_interpretations"] = copy.deepcopy(
            page.get("visual_interpretations", [])
        )
        page["corrections"] = [c for c in history if c["page_number"] == number]
        page["human_verified"] = False
        page["correction_revision"] = latest.get(f"page:{number}", {}).get("revision_number", 0)
        for region in page["regions"]:
            region["correction_revision"] = latest.get(f"region:{region['id']}", {}).get(
                "revision_number", 0
            )
        relevant = [
            c
            for c in latest.values()
            if c["page_number"] == number and c.get("origin", "human") == "human"
        ]
        automatic = [
            c
            for c in latest.values()
            if c["page_number"] == number and c.get("origin") == "automatic_override"
        ]
        for replacement in automatic:
            if replacement["region_id"] is None:
                page["text"] = replacement["text"]
                page["blocks"] = [
                    {
                        "text": replacement["text"],
                        "bbox": [0, 0, page["width"], page["height"]],
                        "kind": "text",
                    }
                ]
            else:
                region = next(
                    (r for r in page["regions"] if r["id"] == replacement["region_id"]), None
                )
                if region:
                    page["blocks"] = [
                        b
                        for b in page.get("blocks", [])
                        if not _overlaps(b["bbox"], region["bbox"])
                    ] + [{"text": replacement["text"], "bbox": region["bbox"], "kind": "text"}]
                    page["text"] = "\n".join(
                        b["text"] for b in page["blocks"] if b["kind"] == "text"
                    )
            page["source_transcription_status"] = "model_interpreted"
        whole = latest.get(f"page:{number}")
        if whole and whole.get("origin", "human") != "human":
            whole = None
        if replace_human:
            page["effective_text"] = page.get("text", "")
            continue
        for correction in relevant:
            if correction["region_id"] is None:
                continue
            region = next((r for r in page["regions"] if r["id"] == correction["region_id"]), None)
            if not region:
                continue
            # Replace contradictory automatic text in the corrected spatial area.
            page["blocks"] = [
                b for b in page.get("blocks", []) if not _overlaps(b["bbox"], region["bbox"])
            ] + [{"text": correction["text"], "bbox": region["bbox"], "kind": "text"}]
            page["text"] = "\n".join(b["text"] for b in page["blocks"] if b["kind"] == "text")
            page["visual_interpretations"] = [
                v for v in page.get("visual_interpretations", []) if v["region_id"] != region["id"]
            ] + [
                {
                    "region_id": region["id"],
                    "transcription": correction["text"],
                    "description": "Human source correction",
                    "uncertain": not correction["verified"],
                    "uncertainties": []
                    if correction["verified"]
                    else ["Human correction is a draft"],
                    "equations": [],
                    "origin": "human",
                    "correction_id": correction["id"],
                    "source_transcription_status": "human_verified"
                    if correction["verified"]
                    else "unresolved",
                }
            ]
            region["human_verified"] = correction["verified"]
            region["needs_vision"] = not correction["verified"]
            region["status"] = "complete" if correction["verified"] else "needs_review"
        if whole:
            page["text"] = whole["text"]
            page["blocks"] = [
                {
                    "text": whole["text"],
                    "bbox": [0, 0, page["width"], page["height"]],
                    "kind": "text",
                }
            ]
            page["human_verified"] = whole["verified"]
            page["correction_revision"] = whole["revision_number"]
            page["source_transcription_status"] = (
                "human_verified" if whole["verified"] else "unresolved"
            )
            # Whole-page human transcription supersedes automatic interpretations,
            # including interpretations of omitted/misread mathematical symbols.
            page["visual_interpretations"] = [
                {
                    "region_id": r["id"],
                    "transcription": whole["text"],
                    "description": "Human page correction",
                    "uncertain": not whole["verified"],
                    "uncertainties": [] if whole["verified"] else ["Draft correction"],
                    "equations": [],
                    "origin": "human",
                    "correction_id": whole["id"],
                }
                for r in page["regions"]
            ]
            for region in page["regions"]:
                region["human_verified"] = whole["verified"]
                region["needs_vision"] = not whole["verified"]
        if relevant:
            page["needs_vision"] = any(r.get("needs_vision") for r in page["regions"])
            if not page["needs_vision"] and page.get("status") != "partial":
                page["status"] = "complete"
        automatic_text = "\n\n".join(
            item.get("transcription", "")
            for item in page.get("visual_interpretations", [])
            if item.get("origin") != "human" and item.get("transcription")
        )
        page["automatic_transcription"] = automatic_text
        page["effective_text"] = (
            page.get("text", "")
            if relevant or automatic
            else automatic_text or page.get("text", "")
        )
    result["source_transcription_status"] = (
        "human_verified"
        if pages and all(p.get("human_verified") for p in pages.values())
        else "mixed"
        if any(c.get("origin", "human") == "human" for c in latest.values())
        else "automatic_unverified"
    )
    incomplete = (
        result.get("status") in {"partial", "failed"}
        or len(pages) < result.get("total_pages", len(pages))
        or bool(result.get("unmapped_office_math"))
    )
    if incomplete:
        # Verified text on available pages cannot establish coverage of omitted
        # pages/equations. Also withdraw any stale cached "complete" overlay.
        result["effective_status"] = "failed" if result.get("status") == "failed" else "partial"
    elif pages and all(p.get("status") == "complete" for p in pages.values()):
        result["effective_status"] = "complete"
    result["correction_ids"] = [c["id"] for c in latest.values()]
    return result


def invalidate_corrected_evidence(session: Session, document_id: str, page_number: int) -> None:
    document = session.get(Document, document_id)
    for card in session.scalars(select(Card).where(Card.course_id == document.course_id)):
        if any(
            r.get("document_id") == document_id and r.get("page_number") == page_number
            for r in [*card.sources, *card.image_refs]
        ):
            card.verification_status = "needs_review"
            card.review_status = "pending"
            card.issues = [
                *card.issues,
                "Source transcription changed; reverify against the human correction.",
            ]
    for concept in session.scalars(select(Concept).where(Concept.course_id == document.course_id)):
        if any(
            r.get("document_id") == document_id and r.get("page_number") == page_number
            for r in concept.sources
        ):
            concept.coverage_status = "unresolved"


def adopt_automatic_replacement(
    session: Session,
    document_id: str,
    page_number: int,
    region_id: str | None,
    transcription: str,
    run_id: str,
) -> None:
    """Commit a confirmed replacement as history, never erase a human revision.

    The caller invokes this only after a successful selected vision task from a
    run with replace_human=True. The run's own source snapshot advances atomically
    with this deliberate source change, so interrupted work can resume safely.
    """
    from anki_generator.database.entities import Run

    run = session.get(Run, run_id)
    if run is None or not run.request.get("replace_human"):
        raise ValueError("Automatic replacement requires explicit run confirmation")
    document = session.get(Document, document_id)
    scope = f"region:{region_id}" if region_id else f"page:{page_number}"
    previous = session.scalar(
        select(SourceCorrection)
        .where(SourceCorrection.document_id == document_id, SourceCorrection.scope_key == scope)
        .order_by(SourceCorrection.revision_number.desc())
        .limit(1)
    )
    if not previous or previous.origin == "automatic_override":
        return
    session.add(
        SourceCorrection(
            document_id=document_id,
            page_number=page_number,
            region_id=region_id,
            scope_key=scope,
            source_sha256=document.sha256,
            revision_number=previous.revision_number + 1,
            text=transcription,
            verified=False,
            origin="automatic_override",
            reason=f"Explicit automatic replacement in run {run_id}; human history retained.",
            supersedes_id=previous.id,
        )
    )
    session.flush()
    snapshot = snapshot_source_state(session, document)
    run.inputs = [
        {**item, **snapshot} if item.get("document_id", item.get("id")) == document_id else item
        for item in run.inputs
    ]
