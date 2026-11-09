"""Bounded independent rendering of selected original-coordinate rectangles."""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import tempfile
from pathlib import Path

from anki_generator.ingestion.contracts import ExtractionOptions
from anki_generator.ingestion.extraction import ExtractionError


def _render_worker(
    path: str, output: str, page_number: int, bbox: list[float], dpi: int, settings: dict
) -> None:
    try:
        options = ExtractionOptions.model_validate(settings)
        if os.name == "posix":
            import resource

            memory = options.worker_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_CPU, (options.worker_cpu_seconds,) * 2)
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        source = Path(path)
        if source.suffix.lower() == ".pdf":
            import pymupdf

            with pymupdf.open(source) as document:
                if not 1 <= page_number <= len(document):
                    raise ExtractionError("Source page does not exist")
                page = document[page_number - 1]
                page.set_rotation(0)
                if pymupdf.Rect(bbox) not in page.rect:
                    raise ExtractionError("Selected rectangle lies outside the original page")
                scale = dpi / 72
                width = math.ceil((bbox[2] - bbox[0]) * scale) + 2
                height = math.ceil((bbox[3] - bbox[1]) * scale) + 2
                if width * height > options.max_region_pixels or max(width, height) > 8192:
                    raise ExtractionError(
                        "Crop exceeds the pixel budget; select less area or lower DPI"
                    )
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    clip=pymupdf.Rect(bbox),
                    alpha=False,
                    colorspace=pymupdf.csRGB,
                )
                pixmap.save(Path(output) / "crop.png")
                dimensions = [pixmap.width, pixmap.height]
        elif source.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            import warnings

            from PIL import Image

            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source, formats=["PNG", "JPEG"]) as image:
                    if image.width * image.height > options.max_image_pixels:
                        raise ExtractionError("Original image exceeds the decoded-pixel limit")
                    if page_number != 1 or not (
                        0 <= bbox[0] < bbox[2] <= image.width
                        and 0 <= bbox[1] < bbox[3] <= image.height
                    ):
                        raise ExtractionError("Selected rectangle lies outside the original image")
                    # Raster source coordinates are pixels; avoid inventing details
                    # by upscaling the already fixed-resolution original.
                    if (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > options.max_region_pixels:
                        raise ExtractionError("Crop exceeds the pixel budget")
                    crop = image.crop(tuple(round(v) for v in bbox)).convert("RGB")
                    if min(crop.size) < 1:
                        raise ExtractionError("Selected image rectangle is smaller than one pixel")
                    crop.save(Path(output) / "crop.png")
                    dimensions = list(crop.size)
        else:
            raise ExtractionError(
                "Original-coordinate selection supports PDFs, PNG and JPEG sources"
            )
        (Path(output) / "result.json").write_text(json.dumps({"dimensions": dimensions}))
    except BaseException as error:
        (Path(output) / "error.json").write_text(json.dumps({"error": str(error)}))


def render_region_safely(
    path: Path,
    destination: Path,
    *,
    page_number: int,
    bbox: list[float],
    dpi: int = 144,
    options: ExtractionOptions | None = None,
    expected_sha256: str | None = None,
) -> tuple[int, int]:
    options = options or ExtractionOptions()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > options.max_file_bytes:
        raise ExtractionError("Selected source is unavailable or exceeds the file limit")
    if (
        len(bbox) != 4
        or not all(math.isfinite(v) for v in bbox)
        or not (0 <= bbox[0] < bbox[2] and 0 <= bbox[1] < bbox[3])
    ):
        raise ExtractionError("Selection requires finite ordered original coordinates")
    if not 72 <= dpi <= 300 or page_number < 1:
        raise ExtractionError("Invalid source page or rendering DPI")
    if expected_sha256:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
                raise ExtractionError("Original source hash changed; reimport a stable original")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".region-", dir=destination.parent) as temporary:
        process = multiprocessing.get_context("spawn").Process(
            target=_render_worker,
            args=(str(path), temporary, page_number, bbox, dpi, options.model_dump()),
        )
        process.start()
        process.join(options.worker_timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
            raise ExtractionError("Selected-region renderer timed out")
        root = Path(temporary)
        if (root / "error.json").exists():
            raise ExtractionError(json.loads((root / "error.json").read_text())["error"])
        if process.exitcode != 0 or not (root / "crop.png").is_file():
            raise ExtractionError("Region renderer stopped; damaged source or resource limit")
        dimensions = json.loads((root / "result.json").read_text())["dimensions"]
        (root / "crop.png").replace(destination)
        return tuple(dimensions)
