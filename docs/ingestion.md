# Local document extraction

`anki_generator.ingestion.extraction.extract_document_safely` prepares uploaded
material locally in a spawned subprocess. On POSIX the worker has CPU,
address-space, and core-dump limits; all platforms have a wall-clock timeout.
`extract_document` exposes the same deterministic parser directly for trusted
inputs and tests. Neither function invokes a language model, executes LaTeX,
follows document instructions, or modifies the source.

The API returns `ExtractionResult`, schema version `1`, extractor version `2` (version-1 results remain readable), with the original
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
| DOCX | When available, isolated LibreOffice renders native layout to PDF; otherwise paragraphs/tables in document order, header/footer text, embedded PNG/JPEG images | Converted pages retain visual evidence and require conversion-fidelity review. Native fallback explicitly flags missing pagination, equation objects, charts and vector layout. |
| PPTX | When available, isolated LibreOffice renders full slides to PDF; otherwise slide text, tables, grouped text, speaker notes and embedded raster images | Converted slides retain graphics and layout. Native fallback remains explicitly limited; synthetic preview page numbers are logical, not original slide numbers. |

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

## Human corrections and selected evidence

The document workbench reads original extraction separately from effective evidence.
Page or region transcription corrections are append-only `SourceCorrection` records,
with source hash, revision, reason, verification decision and origin. A verified
correction requires a rationale. Changing a verified correction requires explicit
replacement confirmation and supports expected-revision conflict detection. The
original source bytes and extraction artifact are never rewritten by corrections.

Human page corrections replace the effective page transcription; regional
corrections replace intersecting automatic text blocks and that region's automatic
interpretation. Draft corrections remain uncertain. Subsequent automatic processing
preserves human corrections by default. An explicitly confirmed successful automatic
replacement appends an `automatic_override` history record, preserving the previous
human review rather than pretending the new model output was human-verified. A
whole-page human transcription must be replaced as a whole page or edited directly;
its arbitrary prose cannot safely be spliced from an unrelated regional reading.

Source edits invalidate dependent card verification/review and concept coverage.
Runs snapshot correction/crop revisions; a paused run cannot silently resume using
changed source evidence. Effective corrected text and original visual evidence are
both supplied to later reasoning. Source transcription verification, bounded
mathematical calculation, model judgment and human claim review remain separate.

`POST /api/documents/{id}/regions` saves an original-coordinate rectangle at a chosen
72–300 DPI, within the configured pixel budget. PDF pages, original PNG/JPEG images,
and successfully rendered Office pages support selection. Raster sources retain
original pixel resolution, with selection edges rounded to pixels. Native Office
fallback and synthetic text previews cannot claim original document geometry.
Crops use isolated resource-limited workers, keep source hashes/coordinates, survive
automatic re-extraction, and may be associated with cards or concepts. Associating
card media creates an auditable human revision and invalidates prior checks.

The synthetic `misread-math.pdf` fixture contains a visible correct plus sign and a
deliberately wrong invisible OCR minus sign. The controlled-provider workflow test
checks that a stored human correction reaches knowledge extraction, original
evidence shown to reviewers, and resulting cards while preserving the original
bytes and incorrect machine reading. This is a synthetic wiring regression, not a
claim of expert-reviewed course accuracy.

The workbench's zoom/pan and image resizing affect presentation only: coordinates
are obtained by mapping the pointer fraction within the displayed tile back through
that tile's original bbox. Tall pages therefore do not require a full-page bitmap.
Selected page/region interpretation retries require ordinary visible external
consent; local extraction and cropping send nothing to a provider.

## Optional Office rendering engine

`office_rendering=auto` attempts LibreOffice only through bubblewrap with network,
user, PID and IPC namespaces, a minimal read-only runtime filesystem, a single
read-only input, private output/profile directories, and macro security level 3.
The headless `svp` backend needs no desktop display. No unrestricted engine fallback
is launched. Missing software, unavailable user namespaces, timeout or conversion
failure falls back to native parsing with visible fidelity warnings. Set
`office_rendering=native` to choose native extraction explicitly.

LibreOffice and bubblewrap are optional system packages, not Python dependencies.
Their presence does not guarantee that the operating system permits the sandbox.
In this environment LibreOffice 26.2.7.3 successfully rendered genuine synthetic
DOCX and PPTX fixtures through the isolated engine; resulting PDF pages were rendered
with Poppler and visually inspected. Conversion can substitute fonts or interpret
Office constructs differently, so preserved page images and warnings remain
necessary. These tests do not establish accuracy on private university documents.
