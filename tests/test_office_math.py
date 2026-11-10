"""Authentic synthetic OMML in Word/PowerPoint; no private course fixtures."""

from pathlib import Path

import pymupdf
import pytest
from docx import Document
from lxml import etree
from pptx import Presentation
from pptx.util import Inches

from anki_generator.ingestion.contracts import ExtractionOptions
from anki_generator.ingestion.extraction import extract_document
from anki_generator.ingestion.office_math import MATH, transcribe_math


def node(name: str, *children, text=None, value=None):
    element = etree.Element(f"{{{MATH}}}{name}")
    element.extend(children)
    element.text = text
    if value is not None:
        element.set(f"{{{MATH}}}val", value)
    return element


def run(text: str):
    return node("r", node("t", text=text))


def fraction():
    return node("oMath", node("f", node("num", run("1")), node("den", run("x"))))


def native(path: Path, output: Path):
    return extract_document(path, output, options=ExtractionOptions(office_rendering="native"))


def test_docx_keeps_inline_math_order_in_body_table_and_header(tmp_path):
    source = tmp_path / "equations.docx"
    document = Document()
    paragraph = document.add_paragraph("Before ")
    paragraph._p.append(fraction())
    paragraph.add_run(" after.")
    document.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]._p.append(fraction())
    document.sections[0].header.paragraphs[0]._p.append(fraction())
    document.save(source)
    before = source.read_bytes()
    result = native(source, tmp_path / "out")
    text = "\n".join(page.text for page in result.pages)
    assert r"Before \(\frac{1}{x}\) after." in text
    assert text.count(r"\frac{1}{x}") == 3
    assert result.status == "needs_review"  # Recovery is not mathematical verification.
    assert any("OMML" in warning for warning in result.warnings)
    assert source.read_bytes() == before


def test_pptx_math_wrapper_preserves_equation_between_text_runs(tmp_path):
    source = tmp_path / "equations.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    paragraph = slide.shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(2)
    ).text_frame.paragraphs[0]
    paragraph.text = "Before "
    wrapper = etree.Element("{http://schemas.microsoft.com/office/drawing/2010/main}m")
    wrapper.append(fraction())
    paragraph._p.append(wrapper)
    paragraph.add_run().text = " after."
    presentation.save(source)
    result = native(source, tmp_path / "out")
    assert r"Before \(\frac{1}{x}\) after." in result.pages[0].text
    assert any("OMML" in warning for warning in result.warnings)
    assert result.status == "needs_review"


@pytest.mark.parametrize("converted_pages", [1, 2])
def test_auto_powerpoint_retains_native_equation_when_converter_drops_it(
    tmp_path, monkeypatch, converted_pages
):
    source = tmp_path / "equation-conversion.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    paragraph = slide.shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(2)
    ).text_frame.paragraphs[0]
    paragraph.text = "Original equation: "
    wrapper = etree.Element("{http://schemas.microsoft.com/office/drawing/2010/main}m")
    wrapper.append(fraction())
    paragraph._p.append(wrapper)
    presentation.save(source)

    def converted_without_equation(path, destination, options):
        with pymupdf.open() as document:
            for _ in range(converted_pages):
                document.new_page().insert_text((20, 40), "Original equation: ")
            document.save(destination)
        return True, "Controlled Office conversion omits the original OMML equation"

    monkeypatch.setattr(
        "anki_generator.ingestion.office_engine.render_office_pdf", converted_without_equation
    )
    result = extract_document(source, tmp_path / "converted")
    assert any("conversion may omit equations" in warning for warning in result.warnings)
    assert result.rendered_source_path
    if converted_pages == 1:
        page = result.pages[0]
        assert r"\frac{1}{x}" in page.text
        assert page.native_office_math[0].source_slide_number == 1
        assert page.native_office_math[0].verification_status == "unverified"
        assert "bbox" not in page.native_office_math[0].model_dump()
        assert not result.unmapped_office_math
    else:
        assert result.status == "partial"
        assert result.unmapped_office_math[0].source_slide_number == 1
        assert r"\frac{1}{x}" in result.unmapped_office_math[0].transcription
        assert all(not page.native_office_math for page in result.pages)
        assert all(r"\frac{1}{x}" not in page.text for page in result.pages)


def test_nested_fraction_scripts_radical_and_matrix_dimensions_remain_explicit():
    expression = node(
        "oMath",
        node(
            "f",
            node(
                "num",
                node("sSubSup", node("e", run("x")), node("sub", run("i")), node("sup", run("2"))),
            ),
            node("den", node("rad", node("deg", run("3")), node("e", run("y")))),
        ),
        node(
            "m",
            node("mr", node("e", run("1")), node("e", run("2"))),
            node("mr", node("e", run("3")), node("e", run("4"))),
        ),
    )
    warnings = set()
    text = transcribe_math(expression, warnings)
    assert r"\frac{{x}_{i}^{2}}{\sqrt[3]{y}}" in text
    assert r"\begin{matrix}1 & 2 \\ 3 & 4\end{matrix}" in text
    assert not any("Unresolved" in warning for warning in warnings)


@pytest.mark.parametrize(
    "expression,reason",
    [
        (node("oMath", node("acc", node("e", run("x")))), "unsupported acc"),
        (node("oMath", node("f", node("num", run("1")))), "missing or repeated den"),
        (
            node(
                "oMath",
                node(
                    "f",
                    node("fPr", node("type", value="noBar")),
                    node("num", run("n")),
                    node("den", run("k")),
                ),
            ),
            "nonstandard fraction layout",
        ),
        (
            node(
                "oMath",
                node(
                    "m",
                    node("mr", node("e", run("1"))),
                    node("mr", node("e", run("2")), node("e", run("3"))),
                ),
            ),
            "inconsistent matrix dimensions",
        ),
    ],
)
def test_unsupported_or_incomplete_math_never_becomes_plausible_plain_equation(expression, reason):
    warnings = set()
    text = transcribe_math(expression, warnings)
    assert text.startswith("[Unresolved Office mathematics")
    assert reason in text
    assert any(reason in warning for warning in warnings)


def test_untrusted_math_text_is_literal_and_complexity_is_bounded():
    warnings = set()
    text = transcribe_math(node("oMath", run(r"\input{secret}")), warnings)
    assert r"\backslash input\{secret\}" in text
    assert r"\input{" not in text
    commented = node("oMath", run("x"), etree.Comment("nonvisible metadata"))
    assert transcribe_math(commented, warnings) == r"\(x\)"
    nested = run("x")
    for _ in range(70):
        nested = node("e", nested)
    text = transcribe_math(node("oMath", nested), warnings)
    assert "complexity limit" in text
