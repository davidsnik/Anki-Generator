# Local document extraction

`anki_generator.ingestion.extraction.extract_document_safely` prepares uploaded
material locally in a spawned subprocess. On POSIX the worker has CPU,
address-space, and core-dump limits; all platforms have a wall-clock timeout.
`extract_document` exposes the same deterministic parser directly for trusted
inputs and tests. Neither function invokes a language model, executes LaTeX,
follows document instructions, or modifies the source.

The API returns `ExtractionResult`, schema/extractor version `1`, with the original
SHA-256 hash, actual PDF page count (logical page count for other formats), parsed
pages, visual regions, warnings, and an explicit status. Limits cover input bytes,
page and region counts, text characters, decoded raster pixels, tile dimensions,
total rendered pixels, and expanded Office archive bytes/members/ratios. The safe
wrapper stages results and publishes PNG evidence only after successful worker
completion. Native parser failure and timeout become actionable `ExtractionError`s.
Partial PDF extraction retains finished visual evidence and text while reporting
unprocessed content. It must never be interpreted as full course coverage.

| Input | Implemented behavior | Fidelity and review requirements |
| --- | --- | --- |
| PDF | PyMuPDF text blocks, image/drawing bounds, dimensions, original page rotation, bounded overlapping PNG tiles | Low text, raster content, vector graphics, suspicious symbols, and mathematical notation request vision review. Extracted text is not a semantic verification. Password-protected or invalid files are rejected. |
| PNG / JPEG | Pillow format verification and decoded-pixel checks; full-resolution bounded PNG tiles | Raster interpretation remains pending until an explicit multimodal stage or human review. No local OCR is claimed. Coordinates use original decoded raster pixels. EXIF orientation is not applied. |
| UTF-8 TXT / Markdown / LaTeX | Exact source text split into bounded logical pages; convenience PNG previews | Markdown and LaTeX are source text. No HTML, TeX engine, includes, or shell escapes are executed. Preview pagination and geometry are synthetic. |
| DOCX | Body paragraphs/tables in document order, header/footer text, embedded PNG/JPEG images | Original pagination, equation objects, charts, and vector layout are not rendered. Synthetic previews and unresolved warnings make this limitation visible; consult or convert the original to PDF for faithful visual analysis. |
| PPTX | Slide text, tables, grouped text, speaker notes, embedded PNG/JPEG images | Native slide drawings/charts/equations are not rendered. Slide labels are retained in text; preview page numbers are logical, not the original slide number. Convert to PDF for faithful full-slide visual analysis. |

The upload service handles ZIP import separately, with path and expansion checks;
ZIP files are not accepted as single documents by the extraction API. OOXML ZIP
containers are preflighted before parsing, and unsupported embedded graphic
formats remain explicitly unresolved in the original file.

## Coordinates and visual evidence

PDF page numbers are 1-based. Bounding boxes are `(x0, y0, x1, y1)` in unrotated
original page points, measured from the top-left of the crop box. Rendering removes
rotation in memory, so the PNG and source coordinates agree; the original rotation
is recorded without saving changes. Both vertical and horizontal segmentation
retain the requested resolution. Nearby whitespace boundaries are preferred when
text/graphic bounds make that possible; overlaps retain context when a diagram
cannot fit in one region. A very tall page is never first rendered as one large
bitmap and then shrunk.

Region PNG paths are safe POSIX paths relative to the extraction output directory.
Each region records its exact source box and rendered dimensions. Original PDF
and raster regions have `is_original_visual=true`. Text and Office convenience
previews have `is_original_visual=false` and
`coordinate_system=synthetic-preview-pixels`; their coordinates must not be
presented as original source layout. Embedded Office raster images are separate
logical image pages with original pixels and explicit placement warnings.

Vision transcriptions belong to the model pipeline, separately from deterministic
extraction. Keep the original tiles, uncertainty, failed regions, and disagreements
alongside those interpretations. A model's plausible transcription is not proof
that a strict inequality, quantifier, or theorem assumption was read correctly.

## Offline fixtures and verification

`fixtures/create_ingestion_fixtures.py` rebuilds genuine PDFs, PNG/JPEG files, DOCX,
and PPTX documents under `fixtures/ingestion`. They are original synthetic course
content, including a real text PDF with a diagram and equation, a 12,000-point-tall
PDF, and a raster-only PDF. The raster note simulates a scan; it is not a benchmark
of genuine handwriting recognition. Digital and scanned PDFs were rendered with
Poppler for visual inspection. Tests verify coordinate coverage, overlap,
resolution, corruption/encryption rejection, data preservation, Office/archive
limits, subprocess failure/timeouts, and explicit incomplete extraction.
