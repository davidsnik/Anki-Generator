"""Content-free PDF dataset profiling in bounded, local-only parser subprocesses."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from anki_generator.benchmark.contracts import DatasetManifest, DatasetSource
from anki_generator.services.storage import safe_storage_path

PROFILE_VERSION = "1"
LIMITS = {
    "wall_seconds_per_pdf": 30,
    "cpu_seconds_per_pdf": 25,
    "address_space_bytes_per_pdf": 1024 * 1024 * 1024,
    "max_file_bytes": 200 * 1024 * 1024,
    "max_geometry_pages": 10_000,
    "max_native_characters_per_sampled_page": 5_000_000,
}


def _profile_pdf(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Runs only in the owned child; never return native source text or filenames."""
    limits_applied = False
    if os.name == "posix":
        import resource

        memory = LIMITS["address_space_bytes_per_pdf"]
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (LIMITS["cpu_seconds_per_pdf"],) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        limits_applied = True
    if path.is_symlink() or not path.is_file():
        return {"status": "failed", "error_kind": "source_not_regular"}
    if path.stat().st_size > LIMITS["max_file_bytes"]:
        return {"status": "failed", "error_kind": "file_byte_limit"}
    with path.open("rb") as stream:
        actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual_hash != expected_sha256:
        return {"status": "failed", "error_kind": "source_hash_mismatch"}

    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    with pymupdf.open(path) as document:
        if not document.is_pdf or document.needs_pass or not document.page_count:
            return {"status": "failed", "error_kind": "invalid_empty_or_encrypted_pdf"}
        total_pages = document.page_count
        geometry = []
        for index in range(min(total_pages, LIMITS["max_geometry_pages"])):
            page = document[index]
            width, height = page.rect.width, page.rect.height
            if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                return {"status": "failed", "error_kind": "invalid_page_dimensions"}
            geometry.append(
                {
                    "page_number": index + 1,
                    "width": round(width, 3),
                    "height": round(height, 3),
                    "rotation": page.rotation,
                }
            )
        sample_indices = sorted({0, total_pages // 2, total_pages - 1})
        sampled = []
        for index in sample_indices:
            page = document[index]
            text = page.get_text("text")
            if len(text) > LIMITS["max_native_characters_per_sampled_page"]:
                return {"status": "failed", "error_kind": "sampled_page_text_limit"}
            flags = pymupdf.TEXTFLAGS_BLOCKS & ~pymupdf.TEXT_PRESERVE_IMAGES
            sampled.append(
                {
                    "page_number": index + 1,
                    "native_text_characters": len(text),
                    "native_control_characters": sum(
                        (ord(character) < 32 and character not in "\n\t\r") or character == "\x7f"
                        for character in text
                    ),
                    "replacement_characters": text.count("\ufffd"),
                    "image_count": len(page.get_images()),
                    "drawing_count": len(page.get_drawings()),
                    "text_block_count": sum(
                        block[6] == 0 for block in page.get_text("blocks", flags=flags)
                    ),
                }
            )
        strata = []
        if any(page["height"] > 1600 for page in geometry):
            strata.append("long_pdf_page")
        if any(page["width"] > 799 for page in geometry):
            strata.append("wide_pdf_page")
        nonempty = sum(page["native_text_characters"] > 0 for page in sampled)
        strata.append(
            "sampled_no_native_text"
            if nonempty == 0
            else "sampled_native_text"
            if nonempty == len(sampled)
            else "sampled_mixed_native_text"
        )
        for field, label in (
            ("native_control_characters", "sampled_native_control_codes"),
            ("image_count", "sampled_raster_evidence"),
            ("drawing_count", "sampled_vector_evidence"),
        ):
            if any(page[field] for page in sampled):
                strata.append(label)
        return {
            "status": "complete" if len(geometry) == total_pages else "partial",
            "pages": total_pages,
            "geometry_all_pages": geometry,
            "geometry_complete": len(geometry) == total_pages,
            "sampled_content_pages": sampled,
            "all_content_pages_sampled": len(sampled) == total_pages,
            "repaired": document.is_repaired,
            "posix_cpu_memory_limits_applied": limits_applied,
            "strata": strata,
        }


def _source_profile(source: DatasetSource, root: Path) -> dict[str, Any]:
    identity = {
        "id": source.id,
        "sha256": source.sha256,
        "course_id": source.course_id,
        "size_bytes": source.size_bytes,
        "source_type": source.source_type,
    }
    if source.source_type.casefold() != "pdf":
        return {**identity, "status": "not_profiled", "reason": "not_pdf"}
    try:
        path = safe_storage_path(root, source.relative_path)
    except ValueError:
        return {**identity, "status": "failed", "error_kind": "unsafe_source_path"}
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
        return {**identity, "status": "failed", "error_kind": "source_symlink"}
    if not path.is_file():
        return {**identity, "status": "failed", "error_kind": "source_missing"}
    started = time.perf_counter()
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", __name__, "--worker", str(path), source.sha256],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=LIMITS["wall_seconds_per_pdf"],
            env=environment,
            check=False,
        )
        data = (
            json.loads(completed.stdout)
            if completed.returncode == 0
            else {
                "status": "failed",
                "error_kind": "worker_exit",
                "exit_code": completed.returncode,
            }
        )
    except subprocess.TimeoutExpired:
        data = {"status": "failed", "error_kind": "worker_timeout"}
    except (OSError, ValueError):
        data = {"status": "failed", "error_kind": "worker_start_or_protocol"}
    return {**identity, "seconds": time.perf_counter() - started, **data}


def profile_dataset(manifest: DatasetManifest, *, workers: int = 2) -> dict[str, Any]:
    """Observe PDF structure with deterministic sample positions and explicit coverage.

    Missing native text is not a handwriting diagnosis. All outputs are metadata;
    profiling never renders/transcribes pages, invokes a provider, or launches a GUI.
    The caller publishes the returned report without overwriting prior artifacts.
    """
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("Profile workers must be an integer from 1 to 8")
    if manifest.source_root is None:
        raise ValueError("Profiling requires extracted local originals in source_root")
    original_root = Path(manifest.source_root)
    if original_root.is_symlink() or not original_root.is_dir():
        raise ValueError("Profile source_root must be a regular directory, not a symlink")
    root = original_root.resolve()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(lambda source: _source_profile(source, root), manifest.sources))
    return {
        "schema_version": PROFILE_VERSION,
        "dataset_id": manifest.dataset_id,
        "dataset_sha256": manifest.dataset_sha256,
        "created_at": datetime.now(UTC).isoformat(),
        "profiler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "pymupdf_version": version("PyMuPDF"),
        "application_version": version("anki-generator"),
        "configuration": {"workers": workers, **LIMITS},
        "method": (
            "Verify each original hash in an isolated parser child. Read all page dimensions "
            "within the page budget; sample native text/control/image/drawing counters on "
            "first, middle and last pages. No source text, vision interpretation or provider calls."
        ),
        "limitations": [
            "Native-text absence does not establish handwriting or unreadability.",
            "Content counters describe only the stated sampled pages, not all document content.",
            "Non-PDF inputs are not profiled; extraction benchmarks assess other formats.",
            "Per-child CPU/address limits require POSIX; wall timeout applies on all platforms.",
        ],
        "cases": rows,
    }


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit("Use the developer benchmark profile CLI")
    try:
        observation = _profile_pdf(Path(sys.argv[2]), sys.argv[3])
    except Exception:
        observation = {"status": "failed", "error_kind": "pdf_parser_error"}
    print(json.dumps(observation, allow_nan=False))
