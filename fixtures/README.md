# Synthetic fixtures

`example-course/` contains original, synthetic introductory probability material:

- `01-lecture.md`: conditional probability, independence, and Bernoulli expectation.
- `02-exercises.txt`: fair-die and Bernoulli exercises with worked solutions.
- `03-summary.tex`: a small, valid LaTeX document containing the main formulas.

These files can be redistributed with this repository. They contain no private
course material. They are plain Markdown, text, and LaTeX sources; there are no
placeholder PDFs or claims of PDF extraction coverage.

From the repository root:

```sh
uv run --locked anki-generator inspect fixtures/example-course --output outputs/example
```

Use `--overwrite` to intentionally replace a previously generated manifest. The
current CLI inventories these files without interpreting their contents.
Automated discovery tests use temporary directories to exercise other file types
and error cases. Future extraction fixtures must use genuine format-valid files
and include reviewed expected results and provenance.
