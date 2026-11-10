"""Native Word inspection must never create definitions or depend on creation templates."""

from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from docx.enum.section import WD_SECTION
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.parts.hdrftr import FooterPart, HeaderPart
from docx.parts.settings import SettingsPart
from docx.shared import Inches
from lxml import etree

from anki_generator.ingestion.contracts import ExtractionOptions
from anki_generator.ingestion.extraction import extract_document


def forbid_creation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Reading an original must never create a Word part from a template")

    monkeypatch.setattr(HeaderPart, "new", forbidden)
    monkeypatch.setattr(FooterPart, "new", forbidden)
    monkeypatch.setattr(SettingsPart, "default", forbidden)


def native_text(source, output):
    result = extract_document(source, output, options=ExtractionOptions(office_rendering="native"))
    return "\n".join(page.text for page in result.pages)


@pytest.mark.parametrize("settings_missing", [False, True])
def test_missing_word_headers_footers_and_settings_require_no_creation_templates(
    tmp_path, monkeypatch, settings_missing
):
    source = tmp_path / "no-header-footer.docx"
    document = Document()
    document.add_paragraph("The source contains this original body text only.")
    document.save(source)
    if settings_missing:
        staged = tmp_path / "without-settings.docx"
        with ZipFile(source) as original, ZipFile(staged, "w", ZIP_DEFLATED) as output:
            for info in original.infolist():
                if info.filename == "word/settings.xml":
                    continue
                content = original.read(info)
                if info.filename == "word/_rels/document.xml.rels":
                    xml = etree.fromstring(content)
                    for relation in list(xml):
                        if relation.get("Type") == RELATIONSHIP_TYPE.SETTINGS:
                            xml.remove(relation)
                    content = etree.tostring(xml)
                if info.filename == "[Content_Types].xml":
                    xml = etree.fromstring(content)
                    for part in list(xml):
                        if part.get("PartName") == "/word/settings.xml":
                            xml.remove(part)
                    content = etree.tostring(xml)
                output.writestr(info, content)
        staged.replace(source)
    original_bytes = source.read_bytes()
    forbid_creation(monkeypatch)
    assert "original body text only" in native_text(source, tmp_path / "out")
    assert source.read_bytes() == original_bytes


def test_existing_and_inherited_active_header_variants_keep_tables_and_math(tmp_path, monkeypatch):
    source = tmp_path / "existing-header-definitions.docx"
    document = Document()
    document.add_paragraph("Original body.")
    document.settings.odd_and_even_pages_header_footer = True
    first = document.sections[0]
    for name, text in (
        ("header", "Normal header"),
        ("footer", "Normal footer"),
        ("first_page_header", "Inherited first header"),
        ("first_page_footer", "Inherited first footer"),
        ("even_page_header", "Even header"),
        ("even_page_footer", "Even footer"),
    ):
        getattr(first, name).paragraphs[0].text = text
    first.header.add_table(rows=1, cols=1, width=Inches(3)).cell(0, 0).text = "Header table"
    first.footer.add_table(rows=1, cols=1, width=Inches(3)).cell(0, 0).text = "Footer table"
    math = etree.fromstring(
        b'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        b"<m:f><m:num><m:r><m:t>1</m:t></m:r></m:num>"
        b"<m:den><m:r><m:t>x</m:t></m:r></m:den></m:f></m:oMath>"
    )
    first.header.paragraphs[0]._p.append(math)
    # A stored first-page variant can be inactive in its originating section and
    # become active through inheritance in a later section.
    first.different_first_page_header_footer = False
    second = document.add_section(WD_SECTION.NEW_PAGE)
    second.different_first_page_header_footer = True
    assert second.header.is_linked_to_previous
    assert second.first_page_header.is_linked_to_previous
    assert second.even_page_header.is_linked_to_previous
    document.save(source)
    original_bytes = source.read_bytes()
    forbid_creation(monkeypatch)
    text = native_text(source, tmp_path / "out")
    for expected in (
        "Normal header",
        "Normal footer",
        "Inherited first header",
        "Inherited first footer",
        "Even header",
        "Even footer",
        "Header table",
        "Footer table",
    ):
        assert text.count(expected) == 1
    assert r"\frac{1}{x}" in text
    assert source.read_bytes() == original_bytes


def test_stored_inactive_first_and_even_page_headers_are_not_generation_text(tmp_path, monkeypatch):
    source = tmp_path / "inactive-header-definitions.docx"
    document = Document()
    document.add_paragraph("Original active body.")
    section = document.sections[0]
    section.first_page_header.paragraphs[0].text = "INACTIVE_FIRST_HEADER"
    section.first_page_footer.paragraphs[0].text = "INACTIVE_FIRST_FOOTER"
    section.even_page_header.paragraphs[0].text = "INACTIVE_EVEN_HEADER"
    section.even_page_footer.paragraphs[0].text = "INACTIVE_EVEN_FOOTER"
    document.save(source)
    forbid_creation(monkeypatch)
    text = native_text(source, tmp_path / "out")
    assert "Original active body" in text
    assert "INACTIVE_" not in text
