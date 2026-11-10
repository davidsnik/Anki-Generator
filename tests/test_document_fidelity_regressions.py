"""Real-format regressions derived from private-source inspection, without private bytes."""

import pymupdf
import pytest
from pydantic import ValidationError

from anki_generator.ingestion.contracts import ExtractionMeasurements, ExtractionResult
from anki_generator.ingestion.extraction import extract_document, extract_document_safely
from anki_generator.ingestion.pdf_extract import tile_rectangles
from anki_generator.processing.contracts import VisualInterpretation
from anki_generator.processing.extraction_stages import ExtractionStages


def test_unknown_pdf_font_control_character_preserves_raw_reading_and_requires_review(tmp_path):
    """An unmapped Type3 glyph resembles the real math-font control-code failure."""
    source = tmp_path / "unmapped-math-font.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=200)
        page.insert_text((20, 50), "The function is continuous under the stated assumptions.")
        glyph = document.get_new_xref()
        document.update_object(glyph, "<<>>")
        document.update_stream(glyph, b"500 0 d0 0 0 m 100 500 l 200 0 l S")
        font = document.get_new_xref()
        document.update_object(
            font,
            "<< /Type /Font /Subtype /Type3 /FontBBox [0 0 500 500] "
            "/FontMatrix [.001 0 0 .001 0 0] /Encoding << /Type /Encoding "
            "/Differences [18 /UnknownMathGlyph] >> /FirstChar 18 /LastChar 18 "
            f"/Widths [500] /CharProcs << /UnknownMathGlyph {glyph} 0 R >> "
            "/Resources << >> >>",
        )
        resource = int(document.xref_get_key(page.xref, "Resources")[1].split()[0])
        document.xref_set_key(
            resource,
            "Font",
            f"<< /helv {page.get_fonts()[0][0]} 0 R /control {font} 0 R >>",
        )
        stream = page.get_contents()[0]
        document.update_stream(
            stream,
            document.xref_stream(stream) + b" BT /control 12 Tf 1 0 0 1 70 100 Tm <12> Tj ET",
        )
        document.save(source)
    original = source.read_bytes()
    result = extract_document(source, tmp_path / "extracted")
    assert "\x12" in result.pages[0].text  # Never guess which symbol the glyph means.
    assert any("Suspicious characters" in warning for warning in result.pages[0].warnings)
    assert result.needs_vision and result.status == "needs_review"
    assert all(region.needs_vision for region in result.pages[0].regions)
    assert source.read_bytes() == original


def test_wide_pdf_interpretation_hints_exclude_nonintersecting_columns(tmp_path):
    source = tmp_path / "wide-two-column.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=2000, height=300)
        page.insert_text((30, 80), "LEFT assumption: x > 0 and denominator nonzero.")
        page.insert_text((1450, 80), "RIGHT different theorem: x < 0.")
        document.save(source)
    extraction = extract_document(source, tmp_path / "extracted")

    class CapturedBeforePersistence(Exception):
        pass

    class Probe(ExtractionStages):
        def _stage(self, *args, **kwargs):
            pass

        def _parallel(self, tasks, function):
            for task in tasks:
                function(task)
            raise CapturedBeforePersistence

        def _call(self, stage, key, payload, schema, **kwargs):
            self.payloads.append(payload)
            return VisualInterpretation(
                transcription="", description="", uncertain=True, uncertainties=[], equations=[]
            )

    probe = Probe()
    probe.documents = [
        {
            "id": "synthetic-wide-pdf",
            "filename": source.name,
            "category": "notes",
            "authority": "supporting",
            "extraction": {"artifact_dir": "extracted", **extraction.model_dump(mode="json")},
        }
    ]
    probe.request = {}
    probe.root = tmp_path
    probe.mode = "generate"
    probe.options = type("Options", (), {"input_token_budget": 60_000})()
    probe.payloads = []
    with pytest.raises(CapturedBeforePersistence):
        probe._interpret()
    assert len(probe.payloads) > 1
    left = probe.payloads[0]
    right = probe.payloads[-1]
    assert left["bbox"][2] < 1450
    assert "LEFT assumption" in left["machine_text"]
    assert "RIGHT different theorem" not in left["machine_text"]
    assert "RIGHT different theorem" in right["machine_text"]
    assert "LEFT assumption" not in right["machine_text"]


def test_line_localization_preserves_existing_block_based_tile_geometry(tmp_path):
    from anki_generator.ingestion.contracts import ExtractionOptions

    source = tmp_path / "long-paragraph.pdf"
    options = ExtractionOptions(max_region_dimension=1000, overlap_points=20)
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=1500)
        page.insert_text((20, 450), "First assumption.\nSecond assumption.\nThird assumption.")
        original_blocks = page.get_text(
            "blocks", flags=pymupdf.TEXTFLAGS_BLOCKS & ~pymupdf.TEXT_PRESERVE_IMAGES, sort=True
        )
        expected = tile_rectangles(
            page.rect.width,
            page.rect.height,
            options.render_dpi / 72,
            options,
            [tuple(block[:4]) for block in original_blocks],
        )
        document.save(source)
    result = extract_document(source, tmp_path / "out", options=options)
    assert [region.bbox for region in result.pages[0].regions] == expected
    assert len([block for block in result.pages[0].blocks if block.kind == "text"]) == 3


@pytest.mark.parametrize("version", ["1", "2", "3"])
def test_extraction_artifacts_retain_readability_across_fidelity_versions(version):
    artifact = ExtractionResult(source_sha256="0" * 64, source_type="pdf")
    assert (
        ExtractionResult.model_validate(
            {**artifact.model_dump(), "extractor_version": version}
        ).extractor_version
        == version
    )
    assert artifact.measurements is None


def test_actual_parser_worker_reports_numeric_cpu_rss_and_pdf_render_scope(tmp_path):
    source = tmp_path / "measure.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((20, 40), "The original source stays local.")
        document.save(source)
    direct = extract_document(source, tmp_path / "direct")
    isolated = extract_document_safely(source, tmp_path / "isolated")
    assert direct.measurements.worker_wall_seconds is None  # Caller is not a parser child.
    metrics = isolated.measurements
    assert metrics.worker_wall_seconds > 0 and metrics.worker_cpu_seconds > 0
    assert metrics.pdf_render_seconds > 0
    assert metrics.pdf_render_seconds <= metrics.worker_wall_seconds
    assert metrics.pdf_regions_rendered == sum(len(page.regions) for page in isolated.pages)
    assert metrics.worker_peak_rss_bytes is None or metrics.worker_peak_rss_bytes > 0
    with pytest.raises(ValidationError):
        ExtractionMeasurements(pdf_render_seconds=float("inf"))


def test_cached_extraction_does_not_replay_worker_costs(api_client, course):
    from pathlib import Path

    from anki_generator.services.measurements import PipelineMeasurements

    source = Path(__file__).resolve().parents[1] / "fixtures" / "ingestion" / "digital.pdf"
    uploaded = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", ("synthetic.pdf", source.read_bytes(), "application/pdf"))],
    )
    assert uploaded.status_code == 201
    runner = api_client.app.state.runtime.runner
    runner.profiler_factory = lambda run_id: PipelineMeasurements()
    measured = []
    for _ in range(2):
        submitted = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"})
        assert submitted.status_code == 202
        runner.run_now(submitted.json()["id"])
        completed = api_client.get(f"/api/runs/{submitted.json()['id']}").json()
        assert completed["status"] == "completed", completed.get("error")
        measured.append(completed["metrics"]["developer_measurements"])
    fresh, cached = measured
    assert fresh["counts"]["extraction"]["cache_misses"] == 1
    assert fresh["subprocesses"]["extraction"]["reports"] == 1
    assert cached["counts"]["extraction"]["cache_hits"] == 1
    assert "extraction" not in cached["subprocesses"]


def test_regional_math_correction_keeps_unaffected_assumption_line(api_client, course, tmp_path):
    source = tmp_path / "nearby-assumption.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=200)
        page.insert_text((20, 50), "Assume x > 0.\nThen f(x) = x.", fontsize=11)
        document.save(source)
    uploaded = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", (source.name, source.read_bytes(), "application/pdf"))],
    )
    assert uploaded.status_code == 201
    identifier = uploaded.json()["documents"][0]["id"]
    submitted = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"})
    api_client.app.state.runtime.runner.run_now(submitted.json()["id"])
    selected = api_client.post(
        f"/api/documents/{identifier}/regions",
        json={"page_number": 1, "bbox": [15, 54, 300, 75], "dpi": 144},
    )
    assert selected.status_code == 201, selected.text
    corrected = api_client.post(
        f"/api/documents/{identifier}/pages/1/corrections",
        json={
            "region_id": selected.json()["id"],
            "text": "Then f(x) = 1/x.",
            "verified": True,
            "reason": "Synthetic regional transcription correction; retain the nearby domain.",
        },
    )
    assert corrected.status_code == 201, corrected.text
    page = api_client.get(f"/api/documents/{identifier}/interpretation").json()["pages"][0]
    assert "Assume x > 0." in page["effective_text"]
    assert "Then f(x) = 1/x." in page["effective_text"]
    assert "Then f(x) = x." not in page["effective_text"]
    assert "Then f(x) = x." in page["original_text"]


def test_correcting_available_page_does_not_hide_missing_pdf_pages(api_client, course, tmp_path):
    from anki_generator.database.entities import Document
    from anki_generator.services.source_corrections import apply_corrections

    source = tmp_path / "two-pages.pdf"
    with pymupdf.open() as document:
        for _ in range(2):
            document.new_page().insert_text(
                (20, 40),
                "An ordinary readable page with enough original source text for extraction.",
            )
        document.save(source)
    uploaded = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[("files", (source.name, source.read_bytes(), "application/pdf"))],
    )
    identifier = uploaded.json()["documents"][0]["id"]
    settings = api_client.patch("/api/settings", json={"extraction": {"max_pages": 1}})
    assert settings.status_code == 200, settings.text
    submitted = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"})
    api_client.app.state.runtime.runner.run_now(submitted.json()["id"])
    route = f"/api/documents/{identifier}/interpretation"

    def effective():
        with api_client.app.state.runtime.sessions() as session:
            return apply_corrections(
                session, identifier, session.get(Document, identifier).extraction
            )

    inspected = effective()
    assert inspected["status"] == inspected["effective_status"] == "partial"
    assert inspected["total_pages"] == 2 and len(inspected["pages"]) == 1
    correction = api_client.post(
        f"/api/documents/{identifier}/pages/1/corrections",
        json={
            "text": "Human correction of the available first page only.",
            "verified": True,
            "reason": "The absent second page has not been reviewed.",
        },
    )
    assert correction.status_code == 201, correction.text
    corrected = effective()
    assert corrected["pages"][0]["human_verified"]
    assert corrected["pages"][0]["text"] == correction.json()["text"]
    assert corrected["effective_status"] == "partial"
    assert api_client.get(route).json()["pages"][0]["human_verified"]
    listed = api_client.get(f"/api/courses/{course['id']}/documents").json()
    assert (
        next(document for document in listed if document["id"] == identifier)["status"] == "partial"
    )
    history = api_client.get(f"/api/documents/{identifier}/pages/1/corrections").json()
    assert len(history) == 1 and history[0]["revision_number"] == 1


def test_unmapped_office_equation_withdraws_stale_complete_overlay(api_client, extracted_source):
    from anki_generator.database.entities import Document
    from anki_generator.services.source_corrections import apply_corrections

    identifier = extracted_source["document"]["id"]
    with api_client.app.state.runtime.sessions() as session:
        document = session.get(Document, identifier)
        original = document.extraction
        stale = {
            **original,
            "status": "needs_review",
            "effective_status": "complete",
            "unmapped_office_math": [
                {"source_slide_number": 2, "transcription": r"\(\frac{1}{x}\)"}
            ],
        }
        effective = apply_corrections(session, identifier, stale)
        assert effective["effective_status"] == "partial"
        assert effective["pages"][0]["text"] == original["pages"][0]["text"]
        assert document.extraction == original  # Overlay never rewrites original extraction.
