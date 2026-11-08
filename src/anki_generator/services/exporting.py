"""Review-gated, stable-identity exports without touching a live Anki collection."""

import csv
import hashlib
import html
import io
import json
import re
import shutil
import tempfile
from pathlib import Path

import genanki
from sqlalchemy import select
from sqlalchemy.orm import Session

from anki_generator.database.entities import Card, Course, Document, ExportRecord, Page, new_id
from anki_generator.domain import ExportInput
from anki_generator.services.records import card_view, require
from anki_generator.services.storage import safe_storage_path

CSS = """
.card {font-family:Arial,sans-serif;font-size:21px;text-align:left;color:#252336;
background:#faf9ff;padding:28px;line-height:1.6;max-width:850px;margin:auto;}
.answer {font-weight:500;} .extra {font-size:17px;color:#686177;margin-top:22px;}
.source {font-size:12px;color:#847d94;margin-top:28px;white-space:pre-wrap;}
img {max-width:100%;height:auto;border-radius:8px;margin:16px 0;}
.cloze {font-weight:bold;color:#7155d9;} .nightMode .card {color:#eeeaf8;background:#211e2c;}
"""
BASIC_MODEL = genanki.Model(
    2026110801,
    "Anki Generator Basic v1",
    fields=[
        {"name": name}
        for name in ("Front", "Back", "Explanation", "Sources", "Concept", "Identity")
    ],
    templates=[
        {
            "name": "Recall",
            "qfmt": "{{Front}}",
            "afmt": (
                '{{FrontSide}}<hr id="answer"><div class="answer">{{Back}}</div>'
                '<div class="extra">{{Explanation}}</div><div class="source">{{Sources}}</div>'
            ),
        }
    ],
    css=CSS,
)
CLOZE_MODEL = genanki.Model(
    2026110802,
    "Anki Generator Cloze v1",
    model_type=genanki.Model.CLOZE,
    fields=[
        {"name": name} for name in ("Text", "Back", "Explanation", "Sources", "Concept", "Identity")
    ],
    templates=[
        {
            "name": "Cloze",
            "qfmt": "{{cloze:Text}}",
            "afmt": (
                '{{cloze:Text}}<hr id="answer"><div class="answer">{{Back}}</div>'
                '<div class="extra">{{Explanation}}</div><div class="source">{{Sources}}</div>'
            ),
        }
    ],
    css=CSS,
)


def render_text(value: str) -> str:
    """Escape all user/model HTML; retain MathJax and Anki cloze syntax."""
    value = re.sub(r"\$\$(.+?)\$\$", lambda match: r"\[" + match[1] + r"\]", value, flags=re.S)
    value = re.sub(r"(?<![\\$])\$([^\n$]+)\$", lambda match: r"\(" + match[1] + r"\)", value)
    return html.escape(value, quote=False).replace("\n", "<br>")


def selected_cards(session: Session, course_id: str, card_ids: list[str] | None) -> list[Card]:
    cards = list(session.scalars(select(Card).where(Card.course_id == course_id, ~Card.archived)))
    if card_ids is not None:
        if not card_ids:
            raise ValueError("Select at least one card")
        available = {card.id for card in cards}
        if set(card_ids) - available:
            raise ValueError(
                "An export selection contains missing cards or cards from another course"
            )
        cards = [card for card in cards if card.id in card_ids]
    return sorted(cards, key=lambda card: (card.created_at, card.id))


def create_export(
    session: Session, data_root: Path, course_id: str, values: ExportInput
) -> ExportRecord:
    course: Course = require(session, Course, course_id)
    cards = selected_cards(session, course_id, values.card_ids)
    if values.format == "apkg":
        # An explicit selection never bypasses approval or a failed quality gate.
        eligible = [
            card
            for card in cards
            if card.review_status == "approved"
            and card.verification_status not in {"failed", "rejected", "duplicate"}
        ]
        if values.card_ids is not None and len(eligible) != len(cards):
            raise ValueError(
                "Only human-approved cards without failed verification can export to Anki"
            )
        cards = eligible
    if not cards:
        raise ValueError("No eligible cards. Review and approve cards before exporting to Anki.")
    export_id = new_id()
    relative = f"exports/{export_id}.{values.format}"
    destination = safe_storage_path(data_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    deck_name = values.deck_name or course.deck_name
    with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
        staging_path = Path(staging)
        temporary = staging_path / f"deck.{values.format}"
        if values.format == "apkg":
            _write_anki(session, data_root, course, cards, deck_name, temporary, staging_path)
        else:
            payloads = [card_view(session, card, detail=True) for card in cards]
            if values.format == "json":
                temporary.write_text(
                    json.dumps(
                        {
                            "schema_version": "1",
                            "course": course.name,
                            "deck_name": deck_name,
                            "cards": payloads,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            else:
                stream = io.StringIO()
                fields = [
                    "id",
                    "note_guid",
                    "card_type",
                    "question",
                    "answer",
                    "explanation",
                    "tags",
                    "sources",
                    "concept_id",
                    "review_status",
                    "verification_status",
                ]
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for item in payloads:
                    row = {field: item.get(field) for field in fields}
                    row["tags"] = json.dumps(row["tags"], ensure_ascii=False)
                    row["sources"] = json.dumps(row["sources"], ensure_ascii=False)
                    # CSV files are often opened in a spreadsheet. Escape formula triggers.
                    writer.writerow(
                        {
                            key: "'" + value
                            if isinstance(value, str)
                            and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                            else value
                            for key, value in row.items()
                        }
                    )
                temporary.write_text(stream.getvalue(), encoding="utf-8")
        temporary.replace(destination)
    result = ExportRecord(
        id=export_id,
        course_id=course.id,
        format=values.format,
        deck_name=deck_name,
        card_ids=[card.id for card in cards],
        card_count=len(cards),
        storage_path=relative,
        sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
    )
    session.add(result)
    session.flush()
    return result


def _write_anki(
    session: Session,
    data_root: Path,
    course: Course,
    cards: list[Card],
    deck_name: str,
    destination: Path,
    staging: Path,
) -> None:
    deck_id = (
        int.from_bytes(hashlib.sha256(course.id.encode()).digest()[:4]) & 0x3FFFFFFF
    ) | 0x40000000
    deck = genanki.Deck(deck_id, deck_name)
    media: dict[str, Path] = {}
    for card in cards:
        if any(
            "\x1f" in text or "\x00" in text
            for text in (
                card.question,
                card.answer,
                card.explanation,
                card.concept_id or "",
                card.id,
            )
        ):
            raise ValueError("Card text contains an unsafe Anki field separator or NUL character")
        for source in card.sources:
            document = session.get(Document, source.get("document_id"))
            if document is None or document.course_id != course.id:
                raise ValueError(
                    "A card's supporting source is missing; update its evidence before export"
                )
        if card.card_type == "cloze" and not re.search(r"{{c[1-9]\d*::.+?}}", card.question, re.S):
            raise ValueError(
                f"Cloze card {card.id} has no valid deletion (e.g. {{{{c1::answer}}}})"
            )
        if card.card_type == "basic" and not card.answer.strip():
            raise ValueError(f"Basic card {card.id} has an empty answer")
        images = []
        for reference in card.image_refs:
            document = require(session, Document, reference["document_id"])
            if document.course_id != course.id:
                raise ValueError("Image evidence belongs to another course")
            page = session.scalar(
                select(Page).where(
                    Page.document_id == document.id, Page.page_number == reference["page_number"]
                )
            )
            region = (
                next(
                    (item for item in page.regions if item["id"] == reference.get("region_id")),
                    None,
                )
                if page
                else None
            )
            if region is None:
                raise ValueError("A referenced image region is missing; reprocess the source")
            artifact_dir = document.extraction.get("artifact_dir", "")
            image = safe_storage_path(data_root, f"{artifact_dir}/{region['image_path']}")
            if not image.is_file():
                raise ValueError("A referenced source image is missing from local storage")
            name = "image_" + hashlib.sha256(image.read_bytes()).hexdigest() + image.suffix.lower()
            if name not in media:
                target = staging / name
                shutil.copyfile(image, target)
                media[name] = target
            images.append(f'<img src="{name}">')
        sources = "\n".join(
            f"{source.get('document_name', source['document_id'])} · page {source['page_number']}"
            + (f" · {source['section']}" if source.get("section") else "")
            for source in card.sources
        )
        fields = [
            render_text(card.question) + "".join(images),
            render_text(card.answer),
            render_text(card.explanation),
            render_text(sources),
            render_text(card.concept_id or "manual"),
            render_text(card.id),
        ]
        tags = [re.sub(r"[^\w:-]", "_", tag) for tag in card.tags if tag.strip()]
        note = genanki.Note(
            model=CLOZE_MODEL if card.card_type == "cloze" else BASIC_MODEL,
            fields=fields,
            tags=tags,
            guid=card.note_guid,
        )
        deck.add_note(note)
    package = genanki.Package(deck)
    package.media_files = [str(path) for path in media.values()]
    package.write_to_file(str(destination))
