"""Optional real isolated LibreOffice integration, separate from native fallback."""

import shutil
from pathlib import Path

import pytest

from anki_generator.ingestion.contracts import ExtractionOptions
from anki_generator.ingestion.extraction import extract_document, extract_document_safely
from anki_generator.ingestion.office_engine import render_office_pdf

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion"


def test_unavailable_office_isolation_keeps_native_content_and_explicit_limitation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("anki_generator.ingestion.office_engine.shutil.which", lambda name: None)
    result = extract_document(FIXTURES / "sample.docx", tmp_path)
    assert result.status == "needs_review"
    assert "P(B)>0" in result.pages[0].text
    assert result.rendered_source_path is None
    assert any("bubblewrap" in warning for warning in result.warnings)
    assert any(not region.is_original_visual for page in result.pages for region in page.regions)


@pytest.mark.parametrize("extension", ["docx", "pptx"])
def test_real_office_engine_renders_native_layout_and_publishes_pdf(tmp_path, extension):
    if not shutil.which("libreoffice") or not shutil.which("bwrap"):
        pytest.skip("Optional LibreOffice/bubblewrap unavailable")
    options = ExtractionOptions(office_rendering="auto")
    converted, diagnostic = render_office_pdf(
        FIXTURES / f"sample.{extension}", tmp_path / "probe.pdf", options
    )
    if not converted:
        pytest.skip(diagnostic)
    result = extract_document_safely(
        FIXTURES / f"sample.{extension}", tmp_path / "extracted", options=options
    )
    assert result.rendering_engine and "network disabled" in result.rendering_engine
    assert result.rendered_source_path
    assert (tmp_path / "extracted" / result.rendered_source_path).read_bytes().startswith(b"%PDF-")
    assert result.source_type == extension
    assert all(page.coordinate_system == "pdf-points" for page in result.pages)
    assert all(region.is_original_visual for page in result.pages for region in page.regions)
    assert "Conditional probability" in " ".join(page.text for page in result.pages)
    assert any("conversion fidelity" in warning for warning in result.warnings)
