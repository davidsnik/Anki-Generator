"""OOXML text, table and raster capture without running Office or document code."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from pptx import Presentation

from anki_generator.ingestion.contracts import ExtractionOptions, ExtractionResult, NativeOfficeMath
from anki_generator.ingestion.extraction import (
    ExtractionError,
    _extract_image,
    render_text_previews,
    validate_office_archive,
)
from anki_generator.ingestion.office_math import MATH, paragraph_text, transcribe_math


def _supplement_powerpoint_math(path: Path, result: ExtractionResult) -> ExtractionResult:
    """Keep original slide equations even when an Office converter omits them.

    Binding is established only for one converted page per original slide. Native
    equations have no invented PDF rectangle and never become visually verified.
    """
    presentation = Presentation(path)
    slide_math = []
    warnings: set[str] = set()
    for number, slide in enumerate(presentation.slides, start=1):
        slide_math.append(
            [
                NativeOfficeMath(
                    source_slide_number=number,
                    transcription=transcribe_math(element, warnings),
                )
                for element in slide._element.iter(f"{{{MATH}}}oMath")
            ]
        )
    all_equations = [equation for equations in slide_math for equation in equations]
    if not all_equations:
        return result
    note = (
        "Original PowerPoint OMML equations are retained as an unverified native supplement; "
        "conversion may omit equations. Inspect the original slide; "
        "no PDF equation box is inferred."
    )
    if result.total_pages != len(slide_math) or len(result.pages) != len(slide_math):
        mismatch = (
            "PowerPoint slide count and converted page count differ; native equations "
            "cannot be assigned to converted pages and remain unresolved."
        )
        return result.model_copy(
            update={
                "unmapped_office_math": all_equations,
                "status": "partial",
                "pages": [
                    page.model_copy(
                        update={"status": "partial", "warnings": [*page.warnings, mismatch]}
                    )
                    for page in result.pages
                ],
                "warnings": [
                    *result.warnings,
                    note,
                    mismatch,
                    *sorted(warnings),
                ],
            }
        )
    pages = []
    for page, equations in zip(result.pages, slide_math, strict=True):
        if not equations:
            pages.append(page)
            continue
        text = (
            page.text
            + "\n\n[Unverified original-slide OMML supplement]\n"
            + "\n".join(equation.transcription for equation in equations)
        )
        pages.append(
            page.model_copy(
                update={
                    "text": text,
                    "native_office_math": equations,
                    "status": "partial" if page.status == "partial" else "needs_review",
                    "warnings": [*page.warnings, note, *sorted(warnings)],
                }
            )
        )
    return result.model_copy(
        update={
            "pages": pages,
            "status": "partial" if result.status == "partial" else "needs_review",
            "warnings": [*result.warnings, note, *sorted(warnings)],
        }
    )


def _docx_text(path: Path, warnings: set[str] | None = None) -> str:
    document = Document(path)
    warnings = warnings if warnings is not None else set()
    sections = []

    def body_text(container) -> list[str]:
        values = []
        for element in container.iter_inner_content():
            if hasattr(element, "text"):
                values.append(paragraph_text(element._p, warnings))
            else:
                values.extend(
                    "\t".join("\n".join(body_text(cell)) for cell in row.cells)
                    for row in element.rows
                )
        return values

    # iter_inner_content preserves ordering of body paragraphs and tables.
    sections.extend(body_text(document))
    try:
        settings = document.part.part_related_by(RELATIONSHIP_TYPE.SETTINGS).settings
        even_pages = settings.odd_and_even_pages_header_footer
    except KeyError:
        even_pages = False
    definitions = {}
    captured_parts = set()
    for section in document.sections:
        variants = (
            ("header", section.header, True),
            ("footer", section.footer, True),
            ("first_header", section.first_page_header, section.different_first_page_header_footer),
            ("first_footer", section.first_page_footer, section.different_first_page_header_footer),
            ("even_header", section.even_page_header, even_pages),
            ("even_footer", section.even_page_footer, even_pages),
        )
        for name, proxy, active in variants:
            # Accessing content on a missing definition creates a new Word part
            # (and opens a template). Read only existing parts, tracking inherited
            # variants even when a preceding section did not display that variant.
            if not proxy.is_linked_to_previous:
                definitions[name] = proxy
            definition = definitions.get(name)
            if not active or definition is None:
                continue
            part = definition.part.partname
            if part not in captured_parts:
                sections.extend(body_text(definition))
                captured_parts.add(part)
    return "\n".join(sections)


def _pptx_text(path: Path, warnings: set[str] | None = None) -> str:
    presentation = Presentation(path)
    warnings = warnings if warnings is not None else set()
    sections = []

    def text_frame_text(frame) -> str:
        return "\n".join(paragraph_text(p._p, warnings) for p in frame.paragraphs)

    def shape_text(shape) -> list[str]:
        values = []
        if shape.has_text_frame:
            values.append(text_frame_text(shape.text_frame))
        if shape.has_table:
            values.extend(
                "\t".join(text_frame_text(cell.text_frame) for cell in row.cells)
                for row in shape.table.rows
            )
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
                sections.append(f"Speaker notes: {text_frame_text(notes)}")
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
            if suffix == "pptx":
                result = _supplement_powerpoint_math(path, result)
            if (
                sum(len(page.text) for page in result.pages)
                + sum(len(equation.transcription) for equation in result.unmapped_office_math)
                > options.max_text_characters
            ):
                raise ExtractionError("Office document exceeds the text-character limit")
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
    math_warnings: set[str] = set()
    text = _docx_text(path, math_warnings) if suffix == "docx" else _pptx_text(path, math_warnings)
    if len(text) > options.max_text_characters:
        raise ExtractionError("Office document exceeds the text-character limit")
    pages = render_text_previews(text, output_dir, media_dir, options)
    pages = [
        page.model_copy(
            update={
                "warnings": [*page.warnings, warning, *sorted(math_warnings)],
                "status": "needs_review",
            }
        )
        for page in pages
    ]
    warnings = [warning, engine_warning, *sorted(math_warnings)]
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
