"""PDF text/geometry capture and original-coordinate, bounded visual tiles."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pymupdf

from anki_generator.ingestion.contracts import (
    BoundingBox,
    ExtractedPage,
    ExtractionOptions,
    ExtractionResult,
    SourceRegion,
    TextBlock,
)
from anki_generator.ingestion.extraction import ExtractionError


def _segments(
    length: float,
    span: float,
    overlap: float,
    forbidden: list[tuple[float, float]],
    limit: int,
) -> list[tuple[float, float]]:
    if not math.isfinite(length) or length <= 0:
        raise ExtractionError("Page dimensions are invalid")
    overlap = min(overlap, span / 4)
    start = 0.0
    segments = []
    while start < length:
        end = min(start + span, length)
        if end < length:
            # Prefer a nearby whitespace boundary. Large diagrams that cannot fit
            # remain overlapping tiles and are explicitly reported to vision.
            candidates = [end]
            candidates.extend(lo - 3 for lo, _ in forbidden if end - span / 5 < lo - 3 < end)
            candidates.extend(hi + 3 for _, hi in forbidden if end - span / 5 < hi + 3 < end)
            clear = [v for v in candidates if not any(lo < v < hi for lo, hi in forbidden)]
            if clear:
                end = max(clear)
        segments.append((start, end))
        if len(segments) > limit:
            raise ExtractionError("Page requires more than the configured region limit")
        if end >= length:
            break
        start = max(start + span / 2, end - overlap)
    return segments


def tile_rectangles(
    width: float,
    height: float,
    scale: float,
    options: ExtractionOptions,
    structures: list[BoundingBox],
) -> list[BoundingBox]:
    """Cover the page with bounded overlapping tiles, without global shrinking."""
    # Reserve 2 pixels per axis for MuPDF integer bounding-box rounding.
    pixels = min(options.max_region_dimension, math.sqrt(options.max_region_pixels)) - 2
    span = pixels / scale
    xs = _segments(
        width,
        span,
        options.overlap_points,
        [(box[0], box[2]) for box in structures],
        options.max_regions,
    )
    ys = _segments(
        height,
        span,
        options.overlap_points,
        [(box[1], box[3]) for box in structures],
        options.max_regions,
    )
    if len(xs) * len(ys) > options.max_regions:
        raise ExtractionError("Page requires more than the configured region limit")
    return [(x0, y0, x1, y1) for y0, y1 in ys for x0, x1 in xs]


def _bbox(raw: tuple | list | pymupdf.Rect, bounds: pymupdf.Rect) -> BoundingBox | None:
    rect = pymupdf.Rect(raw) & bounds
    if rect.is_empty or not all(math.isfinite(v) for v in rect):
        return None
    return tuple(float(v) for v in rect)  # type: ignore[return-value]


def extract_pdf(
    path: Path, output_dir: Path, media_dir: Path, digest: str, options: ExtractionOptions
) -> ExtractionResult:
    pages = []
    warnings = []
    partial = False
    consumed_pixels, consumed_regions = 0, 0
    with pymupdf.open(path) as document:
        if not document.is_pdf:
            raise ExtractionError("File extension is PDF but its contents are not a PDF")
        if document.needs_pass:
            raise ExtractionError("PDF is password-protected; import a decrypted copy")
        if not document.page_count:
            raise ExtractionError("PDF has no pages")
        total_pages = document.page_count
        if document.is_repaired:
            warnings.append("PDF required structural repair; inspect original evidence carefully")
        if total_pages > options.max_pages:
            warnings.append(f"Only {options.max_pages} of {total_pages} pages fit the page limit")
            partial = True
        for index in range(min(total_pages, options.max_pages)):
            page_warnings = []
            blocks: list[TextBlock] = []
            regions: list[SourceRegion] = []
            text = ""
            page_number = index + 1
            page = document.load_page(index)
            rotation = page.rotation
            # Extraction coordinates are unrotated. Rendering the in-memory page
            # unrotated keeps tile coordinates exact; originals are never saved.
            page.set_rotation(0)
            bounds = page.rect
            width, height = bounds.width, bounds.height
            if width <= 0 or height <= 0 or not all(math.isfinite(v) for v in (width, height)):
                raise ExtractionError(f"PDF page {page_number} has invalid dimensions")
            try:
                flags = pymupdf.TEXTFLAGS_BLOCKS & ~pymupdf.TEXT_PRESERVE_IMAGES
                for raw in page.get_text("blocks", flags=flags, sort=True):
                    if raw[6] == 0 and (box := _bbox(raw[:4], bounds)):
                        blocks.append(TextBlock(bbox=box, text=raw[4], kind="text"))
                text = "\n".join(block.text for block in blocks)
                if len(text) > options.max_text_characters:
                    raise ExtractionError("PDF page exceeds the text-character limit")
                images = page.get_image_info()
                for image in images:
                    if box := _bbox(image["bbox"], bounds):
                        blocks.append(TextBlock(bbox=box, text="", kind="image"))
                drawings = page.get_drawings()
                for drawing in drawings:
                    rect = pymupdf.Rect(drawing["rect"])
                    # Include zero-width/height strokes in segmentation geometry.
                    rect = rect + (-0.5, -0.5, 0.5, 0.5)
                    if box := _bbox(rect, bounds):
                        blocks.append(TextBlock(bbox=box, text="", kind="drawing"))
                if len(text.strip()) < 40:
                    page_warnings.append(
                        "Little machine-readable text; scan or handwriting may be present"
                    )
                if images:
                    page_warnings.append(
                        "Raster images may contain information absent from text extraction"
                    )
                if drawings:
                    page_warnings.append(
                        "Vector graphics or diagrams require visual interpretation"
                    )
                if re.search(r"[=<>≤≥∑∫∀∃√∞α-ωΑ-Ω]|\b(?:theorem|lemma|equation)\b", text, re.I):
                    page_warnings.append(
                        "Mathematical notation must be compared with original visual evidence"
                    )
                if "\ufffd" in text or "\x00" in text or text.count("\u00b7") > 5:
                    page_warnings.append(
                        "Suspicious characters suggest uncertain text transcription"
                    )
                structures = [block.bbox for block in blocks]
                scale = options.render_dpi / 72
                boxes = tile_rectangles(width, height, scale, options, structures)
                if len(boxes) > 1:
                    page_warnings.append(
                        f"Page rendered as {len(boxes)} overlapping regions in original coordinates"
                    )
                needs_vision = bool(
                    page_warnings
                    and any(
                        word in warning
                        for warning in page_warnings
                        for word in ("text;", "Raster", "Vector", "Mathematical", "Suspicious")
                    )
                )
                page_partial = False
                for region_index, box in enumerate(boxes):
                    projected_pixels = math.ceil((box[2] - box[0]) * scale + 1) * math.ceil(
                        (box[3] - box[1]) * scale + 1
                    )
                    if consumed_regions >= options.max_regions:
                        raise ExtractionError("Document exceeds the configured region limit")
                    if consumed_pixels + projected_pixels > options.max_total_render_pixels:
                        raise ExtractionError("Document exceeds the total rendering-pixel budget")
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale),
                        clip=pymupdf.Rect(box),
                        alpha=False,
                        colorspace=pymupdf.csRGB,
                    )
                    if pixmap.width * pixmap.height > options.max_region_pixels:
                        raise ExtractionError("Rendered region exceeds the configured pixel limit")
                    consumed_regions += 1
                    consumed_pixels += pixmap.width * pixmap.height
                    target = media_dir / f"page-{page_number:04d}-region-{region_index + 1:04d}.png"
                    pixmap.save(target)
                    regions.append(
                        SourceRegion(
                            id=f"p{page_number}-r{region_index + 1}",
                            page_number=page_number,
                            bbox=box,
                            image_path=target.relative_to(output_dir).as_posix(),
                            pixel_width=pixmap.width,
                            pixel_height=pixmap.height,
                            needs_vision=needs_vision,
                            status="needs_review" if needs_vision else "complete",
                            warnings=page_warnings if needs_vision else [],
                        )
                    )
                    del pixmap
            except (RuntimeError, ValueError, OSError) as error:
                # Retain extracted text and every completed visual region. Omitted
                # regions/pages remain explicit, and a partially rendered page is
                # never treated as complete source coverage.
                page_warnings.append(f"Page {page_number} incompletely extracted: {error}")
                page_partial = True
                needs_vision = True
                partial = True
            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    width=width,
                    height=height,
                    text=text,
                    blocks=blocks,
                    regions=regions,
                    warnings=page_warnings,
                    coordinate_system="pdf-points",
                    original_rotation=rotation,
                    needs_vision=needs_vision,
                    status="partial"
                    if page_partial
                    else "needs_review"
                    if needs_vision
                    else "complete",
                )
            )
            if page_partial:
                warnings.append(f"Unprocessed or uncertain content remains from page {page_number}")
                # A per-document resource budget cannot recover on later pages.
                if "limit" in page_warnings[-1] or "budget" in page_warnings[-1]:
                    break
    needs_vision = any(page.needs_vision for page in pages)
    return ExtractionResult(
        source_sha256=digest,
        source_type="pdf",
        pages=pages,
        total_pages=total_pages,
        warnings=warnings,
        needs_vision=needs_vision,
        status="partial" if partial else "needs_review" if needs_vision else "complete",
    )
