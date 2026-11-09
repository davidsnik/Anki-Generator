"""OOXML text, table and raster capture without running Office or document code."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from docx import Document
from pptx import Presentation

from anki_generator.ingestion.contracts import ExtractionOptions, ExtractionResult
from anki_generator.ingestion.extraction import (
    ExtractionError,
    _extract_image,
    render_text_previews,
    validate_office_archive,
)


def _docx_text(path: Path) -> str:
    document = Document(path)
    sections = []
    # iter_inner_content preserves ordering of body paragraphs and tables.
    for element in document.iter_inner_content():
        if hasattr(element, "text"):
            sections.append(element.text)
        else:
            sections.extend("\t".join(cell.text for cell in row.cells) for row in element.rows)
    for section in document.sections:
        sections.extend(p.text for p in section.header.paragraphs if p.text)
        sections.extend(p.text for p in section.footer.paragraphs if p.text)
    return "\n".join(sections)


def _pptx_text(path: Path) -> str:
    presentation = Presentation(path)
    sections = []

    def shape_text(shape) -> list[str]:
        values = []
        if shape.has_text_frame:
            values.append(shape.text_frame.text)
        if shape.has_table:
            values.extend("\t".join(cell.text for cell in row.cells) for row in shape.table.rows)
        if hasattr(shape, "shapes"):
            for child in shape.shapes:
                values.extend(shape_text(child))
        return values

    for index, slide in enumerate(presentation.slides):
        sections.append(f"Slide {index + 1}")
        for shape in slide.shapes:
            sections.extend(shape_text(shape))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes and notes.text.strip():
                sections.append(f"Speaker notes: {notes.text}")
    return "\n".join(sections)


def extract_office(
    path: Path, output_dir: Path, media_dir: Path, digest: str, options: ExtractionOptions
) -> ExtractionResult:
    validate_office_archive(path, options)
    suffix = path.suffix.lower()[1:]
    engine_warning = "Native Office rendering disabled by settings"
    if options.office_rendering == "auto":
        from anki_generator.ingestion.office_engine import render_office_pdf
        from anki_generator.ingestion.pdf_extract import extract_pdf

        rendered = media_dir / "office-rendered.pdf"
        converted, engine_warning = render_office_pdf(path, rendered, options)
        if converted:
            result = extract_pdf(rendered, output_dir, media_dir, digest, options)
            return result.model_copy(
                update={
                    "source_type": suffix,
                    "rendered_source_path": rendered.relative_to(output_dir).as_posix(),
                    "rendering_engine": engine_warning,
                    "warnings": [
                        *result.warnings,
                        "Office pages rendered by LibreOffice; "
                        "inspect font substitutions and conversion fidelity",
                    ],
                }
            )
    warning = (
        "Office text and tables parsed locally; original pagination, equations, charts, "
        "and drawing layout require review in the original file. Preview geometry is synthetic."
    )
    text = _docx_text(path) if suffix == "docx" else _pptx_text(path)
    if len(text) > options.max_text_characters:
        raise ExtractionError("Office document exceeds the text-character limit")
    pages = render_text_previews(text, output_dir, media_dir, options)
    pages = [
        page.model_copy(
            update={
                "warnings": [*page.warnings, warning],
                "status": "needs_review",
            }
        )
        for page in pages
    ]
    warnings = [warning, engine_warning]
    consumed_pixels = sum(r.pixel_width * r.pixel_height for p in pages for r in p.regions)
    consumed_regions = sum(len(page.regions) for page in pages)
    partial = False
    prefix = "word/media/" if suffix == "docx" else "ppt/media/"
    with ZipFile(path) as archive:
        media_members = sorted(member for member in archive.namelist() if member.startswith(prefix))
        for index, member in enumerate(media_members):
            extension = Path(member).suffix.lower()
            if extension not in {".png", ".jpg", ".jpeg"}:
                warnings.append(
                    f"Embedded {extension or 'unknown'} graphic remains in original Office file"
                )
                continue
            if len(pages) >= options.max_pages:
                warnings.append("Embedded image processing stopped at the logical-page limit")
                return ExtractionResult(
                    source_sha256=digest,
                    source_type=suffix,
                    pages=pages,
                    warnings=warnings,
                    status="partial",
                    needs_vision=True,
                    total_pages=len(pages),
                )
            remaining_pixels = options.max_total_render_pixels - consumed_pixels
            remaining_regions = options.max_regions - consumed_regions
            if remaining_pixels < 65536 or remaining_regions < 1:
                warnings.append("Embedded image processing stopped at the visual-evidence budget")
                partial = True
                break
            remaining_options = options.model_copy(
                update={
                    "max_total_render_pixels": remaining_pixels,
                    "max_regions": remaining_regions,
                }
            )
            embedded_dir = media_dir / f"embedded-{index + 1:04d}"
            embedded_dir.mkdir(exist_ok=True)
            image_path = embedded_dir / f"original{extension}"
            image_path.write_bytes(archive.read(member))
            try:
                extracted = _extract_image(
                    image_path, output_dir, embedded_dir, digest, remaining_options
                )
                consumed_pixels += sum(
                    r.pixel_width * r.pixel_height for p in extracted.pages for r in p.regions
                )
                consumed_regions += sum(len(page.regions) for page in extracted.pages)
                page_number = len(pages) + 1
                image_page = extracted.pages[0]
                regions = [
                    region.model_copy(
                        update={
                            "id": f"p{page_number}-r{n + 1}",
                            "page_number": page_number,
                        }
                    )
                    for n, region in enumerate(image_page.regions)
                ]
                pages.append(
                    image_page.model_copy(
                        update={
                            "page_number": page_number,
                            "regions": regions,
                            "warnings": [
                                *image_page.warnings,
                                "Original embedded raster; logical image page; "
                                "original Office placement unavailable",
                            ],
                        }
                    )
                )
            except ExtractionError as error:
                warnings.append(f"Embedded raster could not be extracted: {error}")
                partial = True
            # The source image is already preserved in immutable original OOXML;
            # only sanitized RGB visual-evidence PNGs need publication.
            image_path.unlink(missing_ok=True)
    pixel_count = sum(r.pixel_width * r.pixel_height for p in pages for r in p.regions)
    region_count = sum(len(page.regions) for page in pages)
    if pixel_count > options.max_total_render_pixels or region_count > options.max_regions:
        raise ExtractionError("Office document exceeds the total visual-evidence resource budget")
    return ExtractionResult(
        source_sha256=digest,
        source_type=suffix,
        pages=pages,
        total_pages=len(pages),
        warnings=warnings,
        status="partial" if partial else "needs_review",
        needs_vision=any(p.needs_vision for p in pages),
    )
