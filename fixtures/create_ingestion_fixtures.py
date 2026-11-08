"""Rebuild small original synthetic documents used by offline extraction tests.

Run from the repository root: uv run python fixtures/create_ingestion_fixtures.py
These contain no private university material. The scan is a raster simulation,
not a claim of having tested genuine student handwriting recognition.
"""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pymupdf
from docx import Document
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches

ROOT = Path(__file__).parent / "ingestion"


def save(document: pymupdf.Document, name: str) -> None:
    document.set_metadata({"title": name, "author": "Anki Generator synthetic fixtures"})
    document.save(ROOT / name, garbage=4, deflate=True, no_new_id=True)
    document.close()


def normalize_office(path: Path) -> None:
    """Remove ZIP timestamps so rebuilding fixtures produces identical bytes."""
    source = BytesIO(path.read_bytes())
    output = BytesIO()
    with ZipFile(source) as archive, ZipFile(output, "w", ZIP_DEFLATED) as normalized:
        for member in sorted(archive.namelist()):
            info = ZipInfo(member, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            normalized.writestr(info, archive.read(member))
    path.write_bytes(output.getvalue())


def build() -> None:
    ROOT.mkdir(exist_ok=True)
    image = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.line((70, 430, 720, 430), fill="black", width=3)
    draw.line((80, 440, 80, 50), fill="black", width=3)
    draw.line([(80 + x, 430 - int(x * x / 1200)) for x in range(600)], fill="#4f46e5", width=4)
    draw.text((140, 40), "Synthetic diagram: f(x) = x^2", fill="black", font_size=26)
    image.save(ROOT / "diagram.png")
    image.save(ROOT / "diagram.jpg", quality=90)

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((48, 60), "Continuity on a compact interval", fontsize=20)
    page.insert_textbox(
        (48, 100, 548, 190),
        "Definition. A real function f is continuous at a when, for every epsilon > 0, "
        "there exists delta > 0 such that |x-a| < delta implies |f(x)-f(a)| < epsilon.",
        fontsize=13,
    )
    page.insert_textbox(
        (48, 215, 548, 300),
        "Theorem. If f is continuous on the closed bounded interval [a,b], "
        "then f attains both a maximum and a minimum. Both endpoints are included.",
        fontsize=13,
    )
    page.insert_image(pymupdf.Rect(48, 340, 548, 653), filename=str(ROOT / "diagram.png"))
    page.draw_rect((48, 690, 548, 750), color=(0.3, 0.3, 0.3))
    page.insert_text((65, 720), "Exercise: Why does f(x)=x on (0,1) have no maximum?", fontsize=12)
    save(document, "digital.pdf")

    document = pymupdf.open()
    page = document.new_page(width=600, height=12000)
    for index in range(12):
        y = 50 + index * 980
        page.insert_text((40, y), f"Long note section {index + 1}", fontsize=20)
        page.insert_text(
            (40, y + 45), "Assume f is continuous on the closed interval [a,b].", fontsize=13
        )
        page.insert_text((40, y + 75), "For all epsilon > 0 there exists delta > 0.", fontsize=13)
        page.draw_rect((40, y + 130, 560, y + 360), color=(0.2, 0.3, 0.8))
        page.insert_text((55, y + 175), f"Equation {index + 1}: f(x) = x^2", fontsize=18)
    save(document, "tall-notes.pdf")

    scan = Image.new("RGB", (1000, 1400), "#fcfbf7")
    draw = ImageDraw.Draw(scan)
    draw.text((80, 90), "RASTER LECTURE NOTE", fill="#162038", font_size=42)
    draw.text((80, 190), "P(A|B) = P(A and B) / P(B)", fill="#162038", font_size=36)
    draw.text((80, 275), "Assumption: P(B) > 0", fill="#162038", font_size=36)
    draw.ellipse((100, 430, 650, 950), outline="#4f46e5", width=5)
    draw.ellipse((350, 430, 900, 950), outline="#db2777", width=5)
    draw.text((240, 620), "A", fill="#162038", font_size=48)
    draw.text((720, 620), "B", fill="#162038", font_size=48)
    scan.save(ROOT / "scan.png")
    document = pymupdf.open()
    page = document.new_page(width=600, height=840)
    page.insert_image(page.rect, filename=str(ROOT / "scan.png"))
    save(document, "scanned.pdf")

    document = Document()
    document.add_heading("Probability lecture", 0)
    document.add_paragraph(
        "For events A and B with P(B)>0, conditional probability is "
        "P(A|B)=P(A intersection B)/P(B)."
    )
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Concept"
    table.cell(0, 1).text = "Assumption"
    table.cell(1, 0).text = "Conditional probability"
    table.cell(1, 1).text = "P(B)>0"
    document.add_picture(str(ROOT / "diagram.png"))
    document.core_properties.created = datetime(2000, 1, 1, tzinfo=UTC)
    document.core_properties.modified = datetime(2000, 1, 1, tzinfo=UTC)
    document.save(ROOT / "sample.docx")
    normalize_office(ROOT / "sample.docx")

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Conditional probability"
    slide.placeholders[1].text = "P(A|B)=P(A intersection B)/P(B)\nAssume P(B)>0."
    slide.shapes.add_picture(str(ROOT / "diagram.png"), Inches(5), Inches(2), width=Inches(4))
    presentation.core_properties.created = datetime(2000, 1, 1, tzinfo=UTC)
    presentation.core_properties.modified = datetime(2000, 1, 1, tzinfo=UTC)
    presentation.save(ROOT / "sample.pptx")
    normalize_office(ROOT / "sample.pptx")


if __name__ == "__main__":
    build()
