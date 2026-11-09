"""Real-format, offline ingestion checks; no OCR/model responses are substituted."""

from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pymupdf
import pytest
from PIL import Image
from pydantic import ValidationError

from anki_generator.ingestion.extraction import (
    ExtractionError,
    ExtractionOptions,
    ExtractionResult,
    SourceRegion,
    TextBlock,
    extract_document,
    extract_document_safely,
)
from anki_generator.ingestion.pdf_extract import tile_rectangles

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"


def test_pdf_preserves_text_geometry_graphics_hash_and_original(tmp_path: Path) -> None:
    source = FIXTURES / "digital.pdf"
    before = source.read_bytes()
    result = extract_document(source, tmp_path)
    assert result.source_sha256 == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before
    assert result.schema_version == "1"
    assert result.total_pages == 1
    page = result.pages[0]
    assert page.page_number == 1
    assert page.width == 595 and page.height == 842
    assert page.coordinate_system == "pdf-points"
    assert "every epsilon > 0" in page.text
    assert "closed bounded interval" in page.text
    assert {block.kind for block in page.blocks} == {"text", "image", "drawing"}
    assert result.status == "needs_review" and result.needs_vision
    assert any("Mathematical" in warning for warning in page.warnings)
    for region in page.regions:
        assert region.needs_vision and region.is_original_visual
        assert region.page_number == page.page_number
        assert 0 <= region.bbox[0] < region.bbox[2] <= page.width
        assert 0 <= region.bbox[1] < region.bbox[3] <= page.height
        with Image.open(tmp_path / region.image_path) as image:
            assert image.format == "PNG"
            assert image.size == (region.pixel_width, region.pixel_height)
    assert ExtractionResult.model_validate_json(result.model_dump_json()) == result


def test_tall_pages_preserve_coordinates_overlap_readability_and_full_coverage(
    tmp_path: Path,
) -> None:
    options = ExtractionOptions(max_region_dimension=1000, max_region_pixels=1_000_000)
    result = extract_document(FIXTURES / "tall-notes.pdf", tmp_path, options=options)
    page = result.pages[0]
    assert page.height == 12000
    assert "Long note section 12" in page.text
    assert len(page.regions) > 20
    assert page.regions[0].bbox[1] == 0
    assert page.regions[-1].bbox[3] == page.height
    vertical_spans = sorted({(region.bbox[1], region.bbox[3]) for region in page.regions})
    for previous, current in zip(vertical_spans, vertical_spans[1:], strict=False):
        assert current[0] < previous[1]
        assert current[1] > previous[1]
    for region in page.regions:
        assert max(region.pixel_width, region.pixel_height) <= 1000
        assert region.pixel_width * region.pixel_height <= options.max_region_pixels
        assert abs(region.pixel_height / (region.bbox[3] - region.bbox[1]) - 2) < 0.02
    assert not any(region.pixel_height > 1000 for region in page.regions)


def test_segmentation_prefers_whitespace_before_equation() -> None:
    options = ExtractionOptions(max_region_dimension=1000, overlap_points=20)
    boxes = tile_rectangles(300, 1500, 2, options, [(0, 470, 300, 530)])
    assert boxes[0][3] < 470
    assert boxes[1][1] < boxes[0][3]
    assert boxes[-1][3] == 1500


def test_scanned_pdf_is_not_silently_considered_text_complete(tmp_path: Path) -> None:
    result = extract_document(FIXTURES / "scanned.pdf", tmp_path)
    assert not result.pages[0].text
    assert result.needs_vision and result.status == "needs_review"
    assert all(region.needs_vision for region in result.pages[0].regions)
    assert any("Little machine-readable" in text for text in result.pages[0].warnings)


def test_rotated_pdf_uses_unrotated_rendering_coordinates(tmp_path: Path) -> None:
    source = tmp_path / "rotated.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=500)
    page.insert_text((25, 50), "Original coordinate test")
    page.set_rotation(90)
    document.save(source)
    document.close()
    result = extract_document(source, tmp_path / "out")
    page = result.pages[0]
    assert (page.width, page.height, page.original_rotation) == (300, 500, 90)
    assert page.regions[0].bbox == (0, 0, 300, 500)
    assert page.regions[0].pixel_width == 600
    assert page.regions[0].pixel_height == 1000
    with pymupdf.open(source) as original:
        assert original[0].rotation == 90


@pytest.mark.parametrize("filename", ["diagram.png", "diagram.jpg"])
def test_real_images_are_validated_and_preserved_as_png(filename: str, tmp_path: Path) -> None:
    result = extract_document(FIXTURES / filename, tmp_path)
    page = result.pages[0]
    assert (page.width, page.height) == (800, 500)
    assert page.coordinate_system == "image-pixels"
    assert page.regions[0].bbox == (0, 0, 800, 500)
    assert result.needs_vision
    with Image.open(tmp_path / page.regions[0].image_path) as image:
        assert image.format == "PNG"
        assert image.getpixel((400, 430)) != (255, 255, 255)


def test_very_wide_image_is_tiled_without_global_downsampling(tmp_path: Path) -> None:
    source = tmp_path / "wide.png"
    Image.new("RGB", (5000, 500), "white").save(source)
    result = extract_document(source, tmp_path / "out")
    regions = result.pages[0].regions
    assert len(regions) > 3
    assert regions[0].bbox[0] == 0
    assert regions[-1].bbox[2] == 5000
    assert regions[0].pixel_width == regions[0].bbox[2]


@pytest.mark.parametrize("suffix", ["txt", "md", "tex"])
def test_text_preserves_original_notation_without_executing_tex(
    suffix: str, tmp_path: Path
) -> None:
    source = tmp_path / f"input.{suffix}"
    text = "\\forall x, \\exists \\delta > 0.\n\\input{/etc/passwd}\n" * 90
    source.write_text(text, encoding="utf-8")
    result = extract_document(source, tmp_path / "out")
    assert "".join(page.text for page in result.pages) == text
    assert all(page.coordinate_system == "synthetic-preview-pixels" for page in result.pages)
    assert not any(region.is_original_visual for page in result.pages for region in page.regions)
    assert result.status == "complete"


@pytest.mark.parametrize("suffix", ["docx", "pptx"])
def test_actual_office_formats_extract_text_and_original_embedded_rasters(
    suffix: str,
    tmp_path: Path,
) -> None:
    result = extract_document(
        FIXTURES / f"sample.{suffix}",
        tmp_path,
        options=ExtractionOptions(office_rendering="native"),
    )
    assert "P(B)>0" in "\n".join(page.text for page in result.pages)
    assert result.status == "needs_review"
    assert any("pagination" in warning for warning in result.warnings)
    assert any(region.is_original_visual for page in result.pages for region in page.regions)
    assert any(not region.is_original_visual for page in result.pages for region in page.regions)
    assert all(
        (tmp_path / region.image_path).exists() for p in result.pages for region in p.regions
    )
    if suffix == "docx":
        assert "Concept\tAssumption" in result.pages[0].text
    else:
        assert "Slide 1" in result.pages[0].text


@pytest.mark.parametrize("name", ["invalid.pdf", "invalid.docx", "invalid.pptx", "invalid.png"])
def test_corrupt_documents_fail_with_actionable_error(name: str, tmp_path: Path) -> None:
    source = tmp_path / name
    source.write_bytes(b"these are not actual document bytes")
    with pytest.raises(ExtractionError):
        extract_document(source, tmp_path / "out")


def test_password_protected_pdf_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    with pymupdf.open(FIXTURES / "digital.pdf") as document:
        document.save(source, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    with pytest.raises(ExtractionError, match="password-protected"):
        extract_document(source, tmp_path / "out")


@pytest.mark.parametrize(
    "name,content",
    [
        ("empty.txt", b""),
        ("binary.txt", b"\x00test"),
        ("bad.txt", b"\xff"),
        ("script.py", b"print('unsafe')"),
    ],
)
def test_invalid_empty_binary_and_unsupported_sources_are_rejected(
    name: str,
    content: bytes,
    tmp_path: Path,
) -> None:
    source = tmp_path / name
    source.write_bytes(content)
    with pytest.raises(ExtractionError):
        extract_document(source, tmp_path / "out")


def test_size_limit_applies_before_parsing(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="byte limit"):
        extract_document(
            FIXTURES / "digital.pdf", tmp_path, options=ExtractionOptions(max_file_bytes=10)
        )


def test_pixel_limit_rejects_image_before_decoding(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="decoded-pixel"):
        extract_document(
            FIXTURES / "diagram.png", tmp_path, options=ExtractionOptions(max_image_pixels=10)
        )


def test_render_budget_preserves_partial_evidence_and_reports_unprocessed_page(
    tmp_path: Path,
) -> None:
    result = extract_document(
        FIXTURES / "tall-notes.pdf",
        tmp_path,
        options=ExtractionOptions(max_total_render_pixels=2_000_000),
    )
    assert result.status == "partial"
    assert result.pages[0].status == "partial"
    assert result.pages[0].text
    assert any("budget" in warning for warning in result.pages[0].warnings)
    assert result.warnings


def test_pdf_page_limit_is_explicit_and_keeps_actual_page_count(tmp_path: Path) -> None:
    source = tmp_path / "two-pages.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.new_page()
        document.save(source)
    result = extract_document(source, tmp_path / "out", options=ExtractionOptions(max_pages=1))
    assert result.total_pages == 2
    assert len(result.pages) == 1
    assert result.status == "partial"
    assert any("Only 1 of 2" in warning for warning in result.warnings)


def test_office_archive_expansion_and_unsafe_names_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bomb.docx"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * 5000)
    with pytest.raises(ExtractionError, match="expanded-byte"):
        extract_document(
            source, tmp_path / "out", options=ExtractionOptions(max_office_expanded_bytes=100)
        )
    with ZipFile(source, "w") as archive:
        archive.writestr("../escape", "invalid")
        archive.writestr("word/document.xml", "invalid")
    with pytest.raises(ExtractionError, match="unsafe member path"):
        extract_document(source, tmp_path / "out")


def test_source_and_image_output_symlinks_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "link.pdf"
    source.symlink_to(FIXTURES / "digital.pdf")
    with pytest.raises(ExtractionError, match="symlink"):
        extract_document(source, tmp_path / "out")
    with pytest.raises(ExtractionError, match="symlink"):
        extract_document_safely(source, tmp_path / "safe-out")
    output = tmp_path / "out"
    output.mkdir(exist_ok=True)
    (output / "images").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ExtractionError, match="symlink"):
        extract_document(FIXTURES / "digital.pdf", output)


def test_safe_subprocess_extracts_and_publishes_real_images(tmp_path: Path) -> None:
    result = extract_document_safely(FIXTURES / "digital.pdf", tmp_path)
    assert "Continuity" in result.pages[0].text
    assert all((tmp_path / r.image_path).exists() for page in result.pages for r in page.regions)
    assert not list(tmp_path.glob(".extraction-*"))


def test_safe_subprocess_reports_parser_failure_and_timeout(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a PDF")
    with pytest.raises(ExtractionError, match="PDF"):
        extract_document_safely(invalid, tmp_path / "invalid-output")
    with pytest.raises(ExtractionError, match="timed out"):
        extract_document_safely(
            FIXTURES / "digital.pdf",
            tmp_path / "timeout-output",
            options=ExtractionOptions(worker_timeout_seconds=0.001),
        )
    assert not list((tmp_path / "timeout-output").glob(".extraction-*"))


def test_contracts_reject_unsafe_paths_and_nonfinite_boxes() -> None:
    with pytest.raises(ValidationError):
        TextBlock(bbox=(0, 0, float("inf"), 1), text="bad")
    with pytest.raises(ValidationError):
        SourceRegion(
            id="r",
            page_number=1,
            bbox=(0, 0, 1, 1),
            image_path="../secret",
            pixel_width=1,
            pixel_height=1,
        )


def test_image_declared_format_must_match_actual_bytes(tmp_path: Path) -> None:
    source = tmp_path / "disguised.png"
    source.write_bytes((FIXTURES / "diagram.jpg").read_bytes())
    with pytest.raises(ExtractionError, match="declared filename"):
        extract_document(source, tmp_path / "out")


def test_office_xml_entities_are_rejected_before_xml_parser(tmp_path: Path) -> None:
    source = tmp_path / "entities.docx"
    with ZipFile(source, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<!DOCTYPE root [<!ENTITY read SYSTEM "file:///etc/passwd">]><root>&read;</root>'
            ).encode("utf-16"),
        )
    with pytest.raises(ExtractionError, match="DTD/entity"):
        extract_document(source, tmp_path / "out")


def test_office_compression_ratio_and_member_limits(tmp_path: Path) -> None:
    source = tmp_path / "ratio.docx"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * 10000)
        archive.writestr("second.xml", "test")
    with pytest.raises(ExtractionError, match="compression ratio"):
        extract_document(source, tmp_path / "out", options=ExtractionOptions(max_archive_ratio=2))
    with pytest.raises(ExtractionError, match="too many members"):
        extract_document(source, tmp_path / "out", options=ExtractionOptions(max_office_members=1))


def test_text_character_limit_is_applied(tmp_path: Path) -> None:
    source = tmp_path / "large.txt"
    source.write_text("a" * 200)
    with pytest.raises(ExtractionError, match="character limit"):
        extract_document(
            source, tmp_path / "out", options=ExtractionOptions(max_text_characters=100)
        )


def test_pdf_region_limit_reports_partial_with_retained_original_text(tmp_path: Path) -> None:
    result = extract_document(
        FIXTURES / "tall-notes.pdf", tmp_path, options=ExtractionOptions(max_regions=1)
    )
    assert result.status == "partial"
    assert "Long note section 12" in result.pages[0].text
    assert any("region limit" in warning for warning in result.pages[0].warnings)
