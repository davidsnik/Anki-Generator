"""Deterministic reference validation against preserved source evidence."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .contracts import EvidenceReference


def normalize_quote(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class EvidenceIndex:
    def __init__(self, documents: list[dict[str, Any]], data_root: Path):
        self.documents = {document["id"]: document for document in documents}
        self.data_root = data_root
        self.pages = {
            (document["id"], page["page_number"]): page
            for document in documents
            for page in document.get("extraction", {}).get("pages", [])
        }

    def enrich(self, refs: list[EvidenceReference]) -> list[EvidenceReference]:
        """Add only spatial metadata established by actual blocks/regions."""
        enriched = []
        for ref in refs:
            page = self.pages.get((ref.document_id, ref.page_number), {})
            updates: dict[str, Any] = {}
            matching_regions = [
                region for region in page.get("regions", []) if region["id"] == ref.region_id
            ]
            if not ref.bbox:
                blocks = [
                    block
                    for block in page.get("blocks", [])
                    if normalize_quote(ref.quote)
                    and normalize_quote(ref.quote) in normalize_quote(block.get("text", ""))
                ]
                if matching_regions:
                    updates["bbox"] = matching_regions[0]["bbox"]
                elif blocks:
                    updates["bbox"] = [
                        min(b["bbox"][0] for b in blocks),
                        min(b["bbox"][1] for b in blocks),
                        max(b["bbox"][2] for b in blocks),
                        max(b["bbox"][3] for b in blocks),
                    ]
            enriched.append(ref.model_copy(update=updates))
        return enriched

    def validate(self, refs: list[EvidenceReference]) -> list[str]:
        errors = []
        if not refs:
            return ["No supporting source evidence was supplied."]
        for ref in refs:
            page = self.pages.get((ref.document_id, ref.page_number))
            if page is None:
                errors.append("A reference names a missing source document or page.")
                continue
            region = next((r for r in page.get("regions", []) if r["id"] == ref.region_id), None)
            if ref.region_id and region is None:
                errors.append("A source reference names a region that does not exist.")
            if ref.bbox:
                x0, y0, x1, y1 = ref.bbox
                if (
                    not all(math.isfinite(v) for v in ref.bbox)
                    or x0 < 0
                    or y0 < 0
                    or x1 > page["width"] + 0.1
                    or y1 > page["height"] + 0.1
                ):
                    errors.append("A source reference bounding box lies outside its page.")
            if ref.bbox:
                matching_blocks = [
                    b
                    for b in page.get("blocks", [])
                    if normalize_quote(ref.quote)
                    and normalize_quote(ref.quote) in normalize_quote(b.get("text", ""))
                ]
                spatial_candidates = [b["bbox"] for b in matching_blocks]
                if region is not None:
                    spatial_candidates.append(region["bbox"])
                if ref.bbox == [0, 0, page["width"], page["height"]]:
                    spatial_candidates.append(ref.bbox)
                if spatial_candidates:
                    x0, y0, x1, y1 = ref.bbox
                    if not any(
                        x1 >= box[0] and x0 <= box[2] and y1 >= box[1] and y0 <= box[3]
                        for box in spatial_candidates
                    ):
                        errors.append(
                            "The source box does not overlap its supporting block or region."
                        )
                else:
                    errors.append("The source box cannot be established from preserved extraction.")
            text = page.get("text", "")
            visual = page.get("visual_interpretations", [])
            if ref.region_id:
                visual = [item for item in visual if item["region_id"] == ref.region_id]
            elif ref.bbox:
                x0, y0, x1, y1 = ref.bbox
                relevant_region_ids = {
                    item["id"]
                    for item in page.get("regions", [])
                    if x1 >= item["bbox"][0]
                    and x0 <= item["bbox"][2]
                    and y1 >= item["bbox"][1]
                    and y0 <= item["bbox"][3]
                }
                visual = [item for item in visual if item["region_id"] in relevant_region_ids]
            if (ref.region_id or page.get("needs_vision")) and any(
                item.get("uncertain", True) for item in visual
            ):
                errors.append("The referenced original visual region has unresolved uncertainty.")
            quote = normalize_quote(ref.quote)
            text_support = bool(quote) and quote in normalize_quote(text)
            visual_support = [
                v
                for v in visual
                if quote
                and quote
                in normalize_quote(v.get("transcription", "") + " " + v.get("description", ""))
            ]
            if not quote or not (text_support or visual_support):
                errors.append("A supporting quotation is absent from preserved source evidence.")
            elif not text_support and all(v.get("uncertain", True) for v in visual_support):
                errors.append(
                    "Supporting visual transcription is uncertain and requires human review."
                )
            if page.get("status") in {"failed", "partial"}:
                errors.append("Supporting page extraction is incomplete; inspect the original.")
        return list(dict.fromkeys(errors))

    def sources(self, refs: list[EvidenceReference]) -> list[dict[str, Any]]:
        """Return exact bounded excerpts from originals, never generating summaries.

        Character ranges preserve the location within the complete stored text;
        every supplied quote on a page receives its own surrounding context.
        """
        result = []
        grouped: dict[tuple[str, int], list[EvidenceReference]] = {}
        for ref in refs:
            grouped.setdefault((ref.document_id, ref.page_number), []).append(ref)
        for (document_id, page_number), page_refs in grouped.items():
            page = self.pages.get((document_id, page_number))
            if not page:
                continue
            doc = self.documents[document_id]
            text = page.get("text", "")
            ranges = []
            for ref in page_refs:
                if not normalize_quote(ref.quote):
                    continue
                pattern = r"\s+".join(re.escape(part) for part in ref.quote.split())
                match = re.search(pattern, text)
                if match:
                    ranges.append(
                        (max(match.start() - 1200, 0), min(match.end() + 1200, len(text)))
                    )
            if not ranges and text:
                ranges = [(0, min(len(text), 2400))]
            merged: list[list[int]] = []
            for lower, upper in sorted(ranges):
                if merged and lower <= merged[-1][1]:
                    merged[-1][1] = max(upper, merged[-1][1])
                else:
                    merged.append([lower, upper])
            visual = [
                item
                for item in page.get("visual_interpretations", [])
                if any(
                    ref.region_id == item["region_id"]
                    or (
                        normalize_quote(ref.quote)
                        and normalize_quote(ref.quote)
                        in normalize_quote(
                            item.get("transcription", "") + " " + item.get("description", "")
                        )
                    )
                    for ref in page_refs
                )
            ]
            result.append(
                {
                    "document_id": document_id,
                    "filename": doc["filename"],
                    "role": doc["category"],
                    "authority": doc.get("authority", "unknown"),
                    "page_number": page_number,
                    "text": "\n[...source excerpt boundary...]\n".join(
                        text[a:b] for a, b in merged
                    ),
                    "source_character_ranges": merged,
                    "total_page_characters": len(text),
                    "visual_interpretations": visual,
                    "warnings": page.get("warnings", []),
                }
            )
        return result

    def image_paths(self, refs: list[EvidenceReference], *, limit: int = 12) -> list[Path]:
        result: list[Path] = []
        for ref in refs:
            page = self.pages.get((ref.document_id, ref.page_number), {})
            doc = self.documents.get(ref.document_id, {})
            for region in page.get("regions", []):
                if ref.region_id and region["id"] != ref.region_id:
                    continue
                if not ref.region_id and ref.bbox:
                    x0, y0, x1, y1 = ref.bbox
                    rx0, ry0, rx1, ry1 = region["bbox"]
                    if x1 <= rx0 or x0 >= rx1 or y1 <= ry0 or y0 >= ry1:
                        continue
                if not region.get("is_original_visual", True):
                    continue
                path = (
                    self.data_root
                    / (
                        region.get("storage_path")
                        or f"{doc['extraction']['artifact_dir']}/{region['image_path']}"
                    )
                ).resolve()
                if (
                    path.is_relative_to(self.data_root.resolve())
                    and path.is_file()
                    and path not in result
                ):
                    result.append(path)
        return result[:limit]

    def media(self, ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        media = []
        errors = []
        for media_id in ids:
            found = False
            for (doc_id, number), page in self.pages.items():
                for region in page.get("regions", []):
                    if media_id == f"{doc_id}:{region['id']}":
                        media.append(
                            {
                                "document_id": doc_id,
                                "page_number": number,
                                "region_id": region["id"],
                                "bbox": region["bbox"],
                            }
                        )
                        found = True
            if not found:
                errors.append("A card requests an image not present in its source material.")
        return media, errors
