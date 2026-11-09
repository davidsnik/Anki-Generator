"""Bounded local extraction; no content is executed or sent to a provider.

PDF preparation is intentionally separate from vision interpretation. A successful
text parse never certifies a diagram or handwritten page as understood.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shutil
import tempfile
from pathlib import Path
from time import monotonic
from zipfile import BadZipFile, ZipFile

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from anki_generator.ingestion.contracts import (
    ExtractedPage,
    ExtractionOptions,
    ExtractionResult,
    SourceRegion,
    TextBlock,
)

__all__ = [
    "ExtractedPage",
    "ExtractionError",
    "ExtractionOptions",
    "ExtractionResult",
    "SourceRegion",
    "TextBlock",
    "extract_document",
    "extract_document_safely",
]


class ExtractionError(ValueError):
    """An unsupported, corrupt, or resource-limited source could not be extracted."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def extract_document(
    path: Path,
    output_dir: Path,
    *,
    options: ExtractionOptions | None = None,
    page_numbers: list[int] | None = None,
) -> ExtractionResult:
    """Extract trusted local files directly; use the safe wrapper for uploads.

    Generated PNG paths are relative to ``output_dir``. Originals are never saved
    or modified. Partial extraction is represented explicitly in the result.
    """
    options = options or ExtractionOptions()
    path, output_dir = Path(path), Path(output_dir)
    if path.is_symlink() or not path.is_file():
        raise ExtractionError("The source must be a regular file, not a symlink")
    size = path.stat().st_size
    if size > options.max_file_bytes:
        raise ExtractionError(f"File exceeds the {options.max_file_bytes}-byte limit")
    if not size:
        raise ExtractionError("The document is empty")
    suffix = path.suffix.lower().removeprefix(".")
    if suffix not in {"pdf", "png", "jpg", "jpeg", "txt", "md", "tex", "docx", "pptx"}:
        raise ExtractionError(f"Unsupported document format: {suffix or '(no extension)'}")
    if page_numbers is not None and suffix != "pdf":
        if page_numbers != [1] or suffix not in {"png", "jpg", "jpeg"}:
            raise ExtractionError(
                "Targeted native page extraction requires PDF; Office pages use their rendered PDF"
            )
    digest = _sha256(path)
    if output_dir.is_symlink():
        raise ExtractionError("The extraction output cannot be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = output_dir / "images" / digest[:20]
    if any(parent.is_symlink() for parent in [output_dir / "images", media_dir]):
        raise ExtractionError("The image output cannot contain symlinks")
    media_dir.mkdir(parents=True, exist_ok=True)
    try:
        if suffix == "pdf":
            from anki_generator.ingestion.pdf_extract import extract_pdf

            result = extract_pdf(
                path, output_dir, media_dir, digest, options, page_numbers=page_numbers
            )
        elif suffix in {"png", "jpg", "jpeg"}:
            result = _extract_image(path, output_dir, media_dir, digest, options)
        elif suffix in {"docx", "pptx"}:
            from anki_generator.ingestion.office_extract import extract_office

            result = extract_office(path, output_dir, media_dir, digest, options)
        else:
            try:
                text = path.read_bytes().decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ExtractionError(
                    "Text must use UTF-8 encoding; convert it and retry"
                ) from error
            if "\x00" in text:
                raise ExtractionError("Text contains binary NUL bytes")
            if len(text) > options.max_text_characters:
                raise ExtractionError("Text exceeds the configured character limit")
            pages = render_text_previews(text, output_dir, media_dir, options)
            result = ExtractionResult(
                source_sha256=digest,
                source_type=suffix,
                pages=pages,
                total_pages=len(pages),
            )
    except ExtractionError:
        raise
    except (OSError, ValueError, RuntimeError, BadZipFile) as error:
        raise ExtractionError(f"Cannot read {suffix.upper()} document: {error}") from error
    if _sha256(path) != digest:
        raise ExtractionError("Source changed during extraction; import a stable copy and retry")
    return result


def _extract_image(
    path: Path, output_dir: Path, media_dir: Path, digest: str, options: ExtractionOptions
) -> ExtractionResult:
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path, formats=["PNG", "JPEG"]) as candidate:
                expected = "PNG" if path.suffix.lower() == ".png" else "JPEG"
                if candidate.format != expected:
                    raise ExtractionError(
                        "Image contents do not match the declared filename format"
                    )
                width, height = candidate.size
                if width * height > options.max_image_pixels:
                    raise ExtractionError("Image exceeds the configured decoded-pixel limit")
                candidate.verify()
            with Image.open(path, formats=["PNG", "JPEG"]) as candidate:
                # EXIF orientation is intentionally not applied: coordinates remain
                # relative to the original raster; the viewer uses the same PNG.
                candidate.load()
                image = candidate.convert("RGB")
    except (
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as e:
        raise ExtractionError("Image is invalid or exceeds safe decompression limits") from e
    from anki_generator.ingestion.pdf_extract import tile_rectangles

    scale = 1.0
    boxes = tile_rectangles(width, height, scale, options, [])
    if len(boxes) > options.max_regions:
        raise ExtractionError("Image requires more than the configured region limit")
    pixels = 0
    regions = []
    for index, box in enumerate(boxes):
        tile = image.crop(tuple(round(v) for v in box))
        pixels += tile.width * tile.height
        if pixels > options.max_total_render_pixels:
            raise ExtractionError("Image exceeds the total rendering-pixel budget")
        target = media_dir / f"page-0001-region-{index + 1:04d}.png"
        tile.save(target, format="PNG")
        regions.append(
            SourceRegion(
                id=f"p1-r{index + 1}",
                page_number=1,
                bbox=box,
                image_path=target.relative_to(output_dir).as_posix(),
                pixel_width=tile.width,
                pixel_height=tile.height,
                needs_vision=True,
                status="needs_review",
                warnings=["Raster content requires multimodal interpretation"],
            )
        )
    page = ExtractedPage(
        page_number=1,
        width=width,
        height=height,
        regions=regions,
        coordinate_system="image-pixels",
        needs_vision=True,
        status="needs_review",
        warnings=["No OCR interpretation has been performed locally"],
    )
    return ExtractionResult(
        source_sha256=digest,
        source_type=path.suffix.lower()[1:],
        pages=[page],
        total_pages=1,
        status="needs_review",
        needs_vision=True,
    )


def render_text_previews(
    text: str,
    output_dir: Path,
    media_dir: Path,
    options: ExtractionOptions,
    *,
    start_page: int = 1,
) -> list[ExtractedPage]:
    """Retain all original text plus clearly marked convenience previews.

    Synthetic pagination is never represented as original document geometry. Raw
    LaTeX is displayed literally, without running TeX or following includes.
    """
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 17)
    except OSError:
        font = ImageFont.load_default(size=17)
    # Store exact source slices separately from visual wrapping. Concatenating
    # page text recreates the input byte-for-byte after UTF-8 decoding.
    lines = [
        line[index : index + 88]
        for line in text.splitlines(keepends=True)
        for index in range(0, len(line), 88)
    ] or [""]
    chunks = [lines[index : index + 48] for index in range(0, len(lines), 48)]
    if len(chunks) > options.max_pages or len(chunks) > options.max_regions:
        raise ExtractionError("Text exceeds the configured logical-page or region limit")
    if len(chunks) * 1000 * 1320 > options.max_total_render_pixels:
        raise ExtractionError("Text previews exceed the configured rendering-pixel budget")
    pages = []
    for offset, chunk in enumerate(chunks):
        number = start_page + offset
        image = Image.new("RGB", (1000, 1320), "white")
        draw = ImageDraw.Draw(image)
        draw.text((42, 25), "Text preview - synthetic layout", fill="#646b77", font=font)
        draw.multiline_text(
            (42, 70),
            "\n".join(line.rstrip("\r\n") for line in chunk),
            fill="#152037",
            font=font,
            spacing=7,
        )
        target = media_dir / f"text-page-{number:04d}.png"
        image.save(target, format="PNG")
        page_text = "".join(chunk)
        bbox = (0.0, 0.0, 1000.0, 1320.0)
        pages.append(
            ExtractedPage(
                page_number=number,
                width=1000,
                height=1320,
                text=page_text,
                blocks=[TextBlock(bbox=bbox, text=page_text)],
                coordinate_system="synthetic-preview-pixels",
                regions=[
                    SourceRegion(
                        id=f"p{number}-preview",
                        page_number=number,
                        bbox=bbox,
                        image_path=target.relative_to(output_dir).as_posix(),
                        pixel_width=1000,
                        pixel_height=1320,
                        is_original_visual=False,
                    )
                ],
                warnings=[
                    "Synthetic preview; page numbers and coordinates are not original pagination"
                ],
            )
        )
    return pages


def validate_office_archive(path: Path, options: ExtractionOptions) -> None:
    """Preflight OOXML containers before third-party parsers decompress them."""
    with ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > options.max_office_members:
            raise ExtractionError("Office archive has too many members")
        names = [member.filename for member in members]
        if len(set(names)) != len(names):
            raise ExtractionError("Office archive contains duplicate member names")
        total = 0
        for member in members:
            from pathlib import PurePosixPath

            pure = PurePosixPath(member.filename)
            if pure.is_absolute() or ".." in pure.parts or "\\" in member.filename:
                raise ExtractionError("Office archive contains an unsafe member path")
            if member.flag_bits & 1:
                raise ExtractionError("Encrypted Office archives are unsupported")
            total += member.file_size
            if total > options.max_office_expanded_bytes:
                raise ExtractionError("Office archive exceeds the expanded-byte limit")
            if member.file_size > max(member.compress_size, 1) * options.max_archive_ratio:
                raise ExtractionError("Office archive has an unsafe compression ratio")
            if member.filename.lower().endswith((".xml", ".rels")):
                # OOXML does not need DTDs/entities. Reject declarations before
                # any downstream XML parser can expand them or read external URIs.
                xml = archive.read(member).replace(b"\x00", b"").upper()
                if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                    raise ExtractionError("Office XML contains forbidden DTD/entity declarations")
        required = "word/document.xml" if path.suffix.lower() == ".docx" else "ppt/presentation.xml"
        if required not in archive.namelist():
            raise ExtractionError("Office archive does not contain the expected document structure")


def _extraction_worker(
    path: str, output: str, options_data: dict, page_numbers: list[int] | None = None
) -> None:
    """Spawn target; a native-parser crash cannot crash the API/job process."""
    options = ExtractionOptions.model_validate(options_data)
    try:
        if os.name == "posix":
            import resource

            memory = options.worker_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_CPU, (options.worker_cpu_seconds,) * 2)
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        result = extract_document(
            Path(path), Path(output), options=options, page_numbers=page_numbers
        )
        (Path(output) / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
    except BaseException as error:
        # These diagnostics stay local and intentionally omit tracebacks/source text.
        (Path(output) / "error.json").write_text(
            json.dumps({"error": f"{type(error).__name__}: {error}"}), encoding="utf-8"
        )


def extract_document_safely(
    path: Path,
    output_dir: Path,
    *,
    options: ExtractionOptions | None = None,
    page_numbers: list[int] | None = None,
) -> ExtractionResult:
    """Run parsers in an isolated, bounded subprocess and publish complete artifacts.

    The caller owns the output directory. POSIX adds address-space/CPU limits;
    every platform has a wall timeout and all formats retain their logical limits.
    """
    options = options or ExtractionOptions()
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExtractionError("The source must be a regular file, not a symlink")
    if path.stat().st_size > options.max_file_bytes:
        raise ExtractionError(f"File exceeds the {options.max_file_bytes}-byte limit")
    output_dir = Path(output_dir)
    if output_dir.is_symlink():
        raise ExtractionError("Extraction output cannot be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".extraction-", dir=output_dir) as temp:
        process = multiprocessing.get_context("spawn").Process(
            target=_extraction_worker,
            args=(str(path.absolute()), temp, options.model_dump(), page_numbers),
        )
        process.start()
        deadline = monotonic() + options.worker_timeout_seconds
        while process.is_alive() and monotonic() < deadline:
            process.join(timeout=min(0.1, max(deadline - monotonic(), 0)))
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            raise ExtractionError("Document parser timed out; reduce the source or adjust limits")
        process.join()
        root = Path(temp)
        if (root / "error.json").exists():
            error = json.loads((root / "error.json").read_text(encoding="utf-8"))["error"]
            raise ExtractionError(error)
        if process.exitcode != 0 or not (root / "result.json").is_file():
            raise ExtractionError(
                f"Document parser stopped (exit {process.exitcode}); resource limit or damaged file"
            )
        result = ExtractionResult.model_validate_json((root / "result.json").read_text())
        if result.rendered_source_path:
            from pathlib import PurePosixPath

            relative = PurePosixPath(result.rendered_source_path)
            if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
                raise ExtractionError("Unsafe converted-source output path")
            rendered_source = root / relative
            rendered_destination = output_dir / relative
            rendered_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(rendered_source, rendered_destination)
        for page in result.pages:
            for region in page.regions:
                source, destination = root / region.image_path, output_dir / region.image_path
                if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
                    raise ExtractionError("Unsafe symlink in image output")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".png.pending")
                try:
                    shutil.copyfile(source, temporary)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
        return result
