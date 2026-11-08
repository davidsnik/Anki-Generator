"""Rebuild the original synthetic geometry course used in browser integration tests."""

from pathlib import Path

import pymupdf


def build() -> None:
    root = Path(__file__).parent / "e2e"
    root.mkdir(exist_ok=True)
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((45, 65), "Euclidean geometry", fontsize=22)
        page.insert_text((45, 115), "For a right triangle, a^2 + b^2 = c^2.", fontsize=15)
        page.insert_text((45, 145), "The right-angle assumption is necessary.", fontsize=14)
        page.insert_text(
            (45, 175), "Here c is the hypotenuse, opposite the right angle.", fontsize=14
        )
        page.draw_polyline(
            [(100, 450), (100, 220), (450, 450), (100, 450)], color=(0.3, 0.2, 0.8), width=2
        )
        page.draw_rect((100, 430, 120, 450), color=(0, 0, 0))
        for position, label in [((65, 340), "a"), ((270, 485), "b"), ((290, 300), "c")]:
            page.insert_text(position, label, fontsize=20)
        (root / "01-lecture.pdf").write_bytes(
            document.tobytes(garbage=4, deflate=True, no_new_id=True)
        )
    (root / "02-exercises.txt").write_text(
        "For a right triangle, a^2 + b^2 = c^2.\n"
        "Exercise 1: With legs 3 and 4, find the hypotenuse.\n"
        "Exercise 2: Why can the identity not be applied to an arbitrary triangle?\n"
    )
    (root / "03-solutions.md").write_text(
        "# Worked solutions\nFor a right triangle, a^2 + b^2 = c^2.\n"
        "1. The hypotenuse is sqrt(3^2+4^2)=5. Check that 3 and 4 are the legs.\n"
        "2. A right angle is necessary; general triangles require the cosine rule.\n"
    )


if __name__ == "__main__":
    build()
