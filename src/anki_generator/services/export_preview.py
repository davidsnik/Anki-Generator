"""Paginated changes against an immutable previous export, using stable note GUIDs."""

from collections import Counter

from sqlalchemy import select

from anki_generator.database.entities import Course, ExportRecord, Revision, Run
from anki_generator.database.pipeline_entities import ExportSnapshot
from anki_generator.processing.state import digest
from anki_generator.services.exporting import selected_cards
from anki_generator.services.identity import unresolved_for_cards
from anki_generator.services.records import require


def card_snapshot(card):
    return {
        key: getattr(card, key)
        for key in (
            "id",
            "note_guid",
            "revision_number",
            "concept_id",
            "card_type",
            "kind",
            "question",
            "answer",
            "explanation",
            "tags",
            "sources",
            "image_refs",
        )
    }


def content_hash(card):
    data = card_snapshot(card)
    return digest(
        {
            key: value
            for key, value in data.items()
            if key not in {"id", "note_guid", "revision_number"}
        }
    )


def export_preview(session, course_id, card_ids=None, *, offset=0, limit=25):
    require(session, Course, course_id)
    cards = selected_cards(session, course_id, card_ids)
    baseline = session.scalar(
        select(ExportRecord)
        .where(ExportRecord.course_id == course_id)
        .order_by(ExportRecord.created_at.desc())
        .limit(1)
    )
    snapshots = (
        list(session.scalars(select(ExportSnapshot).where(ExportSnapshot.export_id == baseline.id)))
        if baseline
        else []
    )
    prior = {row.note_guid: row for row in snapshots}
    current = {card.note_guid for card in cards}
    proposals = unresolved_for_cards(session, cards)
    affected = {p.candidate_id for p in proposals if p.entity_type == "card"}
    concepts = {p.candidate_id for p in proposals if p.entity_type == "concept"}
    guid_counts = Counter(card.note_guid for card in cards)
    groups = {
        name: [] for name in ("new", "matching", "modified", "uncertain", "missing", "duplicates")
    }
    for card in cards:
        item = {
            "id": card.id,
            "note_guid": card.note_guid,
            "question": card.question,
            "revision_number": card.revision_number,
            "verification_status": card.verification_status,
            "review_status": card.review_status,
        }
        revision = session.scalar(
            select(Revision).where(
                Revision.card_id == card.id, Revision.revision_number == card.revision_number
            )
        )
        mapped = set(revision.snapshot.get("concept_ids", [])) if revision else set()
        mapped.update([card.concept_id] if card.concept_id else [])
        if card.id in affected or mapped & concepts:
            related = [
                p.id for p in proposals if p.candidate_id == card.id or p.candidate_id in mapped
            ]
            groups["uncertain"].append(
                {**item, "proposal_id": related[0] if related else None, "proposal_ids": related}
            )
        elif card.verification_status == "duplicate" or guid_counts[card.note_guid] > 1:
            groups["duplicates"].append(item)
        elif card.note_guid not in prior:
            groups["new"].append(item)
        elif content_hash(card) == prior[card.note_guid].content_hash:
            groups["matching"].append(item)
        else:
            groups["modified"].append(item)
    groups["missing"] = [
        {
            "id": row.card_id,
            "note_guid": row.note_guid,
            "question": row.snapshot.get("question", ""),
            "revision_number": row.revision_number,
        }
        for row in snapshots
        if row.note_guid not in current
    ]
    last_run = session.scalar(
        select(Run.id).where(Run.course_id == course_id).order_by(Run.created_at.desc()).limit(1)
    )
    counts = {name: len(items) for name, items in groups.items()}
    return {
        "course_id": course_id,
        "baseline_export_id": baseline.id if baseline else None,
        "last_run_id": last_run,
        "counts": counts,
        **{name: items[offset : offset + limit] for name, items in groups.items()},
        "preview_offset": offset,
        "preview_limit": limit,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "has_more": any(count > offset + limit for count in counts.values()),
        },
        "has_more": any(count > offset + limit for count in counts.values()),
        "export_blocked": bool(proposals),
        "identity_proposals": len(proposals),
        "limitations": [
            "The previous export predates immutable snapshots; changes cannot be reconstructed."
        ]
        if baseline and not snapshots
        else [],
    }
