# Synthetic fixtures

All fixtures are original synthetic material, safe to track and free of private
university documents.

- example-course/: introductory probability Markdown, exercises/solutions and LaTeX
  for the preserved discovery CLI.
- ingestion/: genuine digital/scanned/very tall PDFs, raster diagram and DOCX/PPTX
  used to test extraction, original geometry and explicit Office limitations.
- e2e/: a genuine Euclidean-geometry PDF with a labelled right triangle, exercise
  sheet and worked solutions for the complete controlled-provider browser workflow.

Rebuild generated fixtures with the application environment:

    uv run python fixtures/create_ingestion_fixtures.py
    uv run python fixtures/create_e2e_fixtures.py

Extraction fixtures have reviewed expected assertions in tests/test_extraction.py.
The geometry identity assumes a right triangle, with positive leg lengths a,b and
hypotenuse c. For legs3,4 the hypotenuse is5. These fixtures establish deterministic
integration behavior, not a broad independently human-reviewed model-quality corpus.
Future evaluation fixtures should record target annotations, source regions,
reviewer decisions and held-out splits; see the [roadmap](../docs/roadmap.md).
