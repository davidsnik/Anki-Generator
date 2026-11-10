"""Private dataset sampling profiles record observations, never semantic diagnoses."""

import json
from zipfile import ZipFile

import pymupdf
import pytest

from anki_generator.benchmark.inventory import inventory_zip
from anki_generator.benchmark.profile import profile_dataset


def dataset(tmp_path):
    archive = tmp_path / "sources.zip"
    with pymupdf.open() as digital, pymupdf.open() as visual:
        for index in range(3):
            digital.new_page(width=300, height=400 + index * 100).insert_text(
                (20, 40), "Private source text should never enter the profile report."
            )
        visual.new_page(width=900, height=1800).draw_rect(pymupdf.Rect(10, 10, 40, 40))
        with ZipFile(archive, "w") as zipped:
            zipped.writestr("Study/courses/A/notes/digital.pdf", digital.tobytes())
            zipped.writestr("Study/courses/B/notes/visual.pdf", visual.tobytes())
            zipped.writestr("Study/courses/B/source.py", b"raise RuntimeError('never execute')")
    return inventory_zip(archive, extract_to=tmp_path / "originals")


def test_real_pdf_profile_covers_geometry_and_explicit_sample_denominators(tmp_path):
    manifest = dataset(tmp_path)
    result = profile_dataset(manifest, workers=2)
    assert result["dataset_sha256"] == manifest.dataset_sha256
    assert result["configuration"]["wall_seconds_per_pdf"] == 30
    digital, visual = [row for row in result["cases"] if row["source_type"] == "pdf"]
    assert digital["status"] == visual["status"] == "complete"
    assert digital["pages"] == len(digital["geometry_all_pages"]) == 3
    assert [page["page_number"] for page in digital["sampled_content_pages"]] == [1, 2, 3]
    assert digital["all_content_pages_sampled"]
    assert all(page["native_text_characters"] > 0 for page in digital["sampled_content_pages"])
    assert visual["sampled_content_pages"][0]["drawing_count"] == 1
    assert "long_pdf_page" in visual["strata"] and "wide_pdf_page" in visual["strata"]
    assert "sampled_no_native_text" in visual["strata"]
    assert (
        next(row for row in result["cases"] if row["source_type"] == "py")["status"]
        == "not_profiled"
    )
    serialized = json.dumps(result)
    assert "Private source text" not in serialized
    assert "handwritten" not in serialized  # Observation never silently becomes this diagnosis.


def test_changed_original_fails_hash_binding_and_other_sources_still_profile(tmp_path):
    manifest = dataset(tmp_path)
    original = tmp_path / "originals" / manifest.sources[0].relative_path
    original.write_bytes(b"changed bytes")
    report = profile_dataset(manifest, workers=1)
    assert report["cases"][0]["error_kind"] == "source_hash_mismatch"
    assert any(row["status"] == "complete" for row in report["cases"])


@pytest.mark.parametrize("workers", [0, 9, True])
def test_profile_worker_budget_validation(tmp_path, workers):
    with pytest.raises(ValueError, match="workers"):
        profile_dataset(dataset(tmp_path), workers=workers)
