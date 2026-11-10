"""Export a private, offline source-grounded review package without a research GUI."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from .annotations import (
    DIMENSIONS,
    AnnotationBundle,
    BenchmarkAnnotation,
    SourceReference,
    append_annotations,
    case_sha256,
    load_annotations,
    reference_inventory,
    reference_inventory_hash,
    result_cases,
)

__all__ = ["append_annotations", "export_review_package", "load_annotations"]


def _source_refs(case: dict) -> list[SourceReference]:
    candidates = list(case.get("sources", []))
    if {"source_id", "document_sha256", "page_number"} <= case.keys():
        candidates.append(case)
    refs = []
    seen = set()
    for source in candidates:
        if not {"source_id", "document_sha256", "page_number"} <= source.keys():
            continue
        values = {key: source[key] for key in SourceReference.model_fields if key in source}
        ref = SourceReference.model_validate(values)
        identity = ref.model_dump_json()
        if identity not in seen:
            refs.append(ref)
            seen.add(identity)
    return refs


def _code(value: Any) -> str:
    """Fence untrusted source text; embedded Markdown/HTML never becomes instructions."""
    text = str(value)
    longest = max(
        (len(part) for part in text.split("\n") if part and set(part) == {"`"}), default=0
    )
    fence = "`" * max(3, longest + 1)
    # Any occurrence could close a fence after leading whitespace.
    while fence in text:
        fence += "`"
    return f"{fence}text\n{text}\n{fence}"


def _artifact_link(path: str, label: str) -> str:
    if any(character in path for character in ("\x00", "\n", "\r")) or "://" in path:
        return _code(path)
    # Encode local path punctuation rather than interpreting imported Markdown/HTML.
    return f"[{label}](<{quote(path, safe='/._-')}>)"


def _retrieval_context(value: Any) -> Any:
    """Expose judging material while withholding model identities, scores and verdicts."""
    if not isinstance(value, dict):
        return value
    fields = (
        "id",
        "kind",
        "text",
        "title",
        "question",
        "answer",
        "explanation",
        "description",
        "statement",
        "assumptions",
        "competencies",
        "sources",
        "image_path",
    )
    visible = {key: value[key] for key in fields if key in value}
    saved_object = value.get("object")
    if isinstance(saved_object, dict):
        content = {key: saved_object[key] for key in fields if key in saved_object}
        metadata = saved_object.get("metadata")
        if isinstance(metadata, dict):
            for key in ("assumptions", "competencies"):
                if key in metadata and key not in content:
                    content[key] = metadata[key]
        visible["object"] = content
    return visible


def export_review_package(
    result: dict[str, Any], destination: Path, *, blind: bool = True
) -> dict[str, Any]:
    """Create new Markdown + pending JSON; no judgment is manufactured by export.

    Blind review hides the run configuration and pipeline verdicts, but source
    evidence remains visible. Run IDs are opaque and retained for import binding.
    Source paths refer to private local artifacts; this package is private too.
    """
    cases = list(result_cases(result).items())
    if blind:
        seed = int(hashlib.sha256(result["dataset_sha256"].encode()).hexdigest()[:16], 16)
        random.Random(seed).shuffle(cases)
    annotations = []
    source_manifest = {source["id"]: source for source in result.get("source_manifest", [])}
    sections = [
        "# Offline benchmark review",
        "This package contains private course data. Keep it outside version control.",
        f"Run: `{result['run_id']}`. Dataset SHA-256: `{result['dataset_sha256']}`.",
        "## Review instructions",
        "Inspect the original source image/page independently before declaring source agreement. "
        "Source agreement alone cannot establish that a student's solution or arbitrary "
        "proof is correct.",
        "Edit annotations.json. Leave undecided cases pending. For an actual human "
        "judgment, enter your "
        "reviewer name, set human_attested=true, select "
        "accepted/needs_edit/rejected/unresolved, and fill only "
        "observed dimensions. Unknown values stay null. Record actual active seconds only "
        "if timed reliably. "
        "A declaration records responsibility, not authenticated expertise.",
        "For fidelity cases enter a reference_transcription only after inspecting the "
        "original. For retrieval "
        "cases enter explicit relevance labels; declare relevance_universe_complete only if "
        "all relevant "
        "items have been identified. For coverage, map only source-grounded reference_concept_ids.",
        "Use origin=model plus the actual model identifier for model judgments. "
        "Model-produced annotations "
        "remain provisional. Mark independent_source=true only for a separate inspection of "
        "the cited original "
        "source. Add error categories and rationale rather than only replacing wording.",
        "Imports are append-only. To revise a previously imported judgment, assign a new "
        "annotation ID and "
        "set supersedes to the earlier ID; preserve both entries. Never edit frozen "
        "benchmark results.",
        "No live API call is needed to review or import these files.",
    ]
    if not blind:
        sections.extend(
            [
                "## Configuration (unblinded)",
                _code(json.dumps(result.get("configuration", {}), indent=2)),
            ]
        )
    inventory = reference_inventory(result)
    if inventory is not None:
        sections.extend(
            [
                "## Independent reference inventory",
                "These declared targets are evaluation references, not generation inputs. "
                "Model-produced references remain provisional and are not human validation.",
                _code(inventory.model_dump_json(indent=2)),
            ]
        )
    for index, ((kind, identifier), case) in enumerate(cases, 1):
        refs = _source_refs(case)
        annotation = BenchmarkAnnotation(
            id=str(uuid4()),
            target_type=kind,
            target_id=identifier,
            target_sha256=case_sha256(case),
            dimensions={name: None for name in DIMENSIONS},
            source_refs=refs,
        )
        annotations.append(annotation)
        sections.extend(
            [
                f"## Case {index}: {kind}",
                f"Target: `{identifier}`. Annotation: `{annotation.id}`.",
            ]
        )
        if kind == "card":
            sections.extend(
                [
                    "Question",
                    _code(case.get("question", "")),
                    "Answer",
                    _code(case.get("answer", "")),
                ]
            )
            if case.get("explanation"):
                sections.extend(["Explanation", _code(case["explanation"])])
        elif kind == "concept":
            for key in ("label", "title", "statement", "assumptions", "competencies"):
                if case.get(key):
                    sections.extend([key.replace("_", " ").capitalize(), _code(case[key])])
        elif kind == "fidelity":
            sections.extend(["Extracted transcription", _code(case.get("transcription", ""))])
            if not blind:
                sections.extend(["Extraction method", _code(case.get("method", "unknown"))])
            if case.get("image_path"):
                sections.extend(
                    [
                        "Original rendered page/region",
                        _artifact_link(str(case["image_path"]), "Open recorded original image"),
                    ]
                )
            regions = case.get("regions", [])
            if regions:
                sections.append(
                    "All rendered regions are listed below. The first image can cover only one "
                    "bounded tile of a long page; inspect every relevant tile and its "
                    "original coordinates."
                )
                for region_index, region in enumerate(regions, 1):
                    sections.append(
                        _code(
                            json.dumps(
                                {
                                    key: region[key]
                                    for key in (
                                        "id",
                                        "bbox",
                                        "coordinate_system",
                                        "pixel_width",
                                        "pixel_height",
                                        "image_path",
                                        "warnings",
                                    )
                                    if key in region
                                },
                                ensure_ascii=False,
                                indent=2,
                            )
                        )
                    )
                    if region.get("image_path"):
                        sections.append(
                            _artifact_link(
                                str(region["image_path"]), f"Open original region {region_index}"
                            )
                        )
        else:
            sections.extend(
                [
                    "Retrieval query",
                    _code(_retrieval_context(case.get("query", ""))),
                    "Object context scope",
                    _code(
                        case.get(
                            "object_context_scope",
                            "Saved artifact context; inspect original evidence independently.",
                        )
                    ),
                    "Ranked evidence candidates",
                ]
            )
            for rank, hit in enumerate(case.get("hits", []), 1):
                # Candidate content is needed to judge relevance. Scores and model IDs bias review.
                visible = _retrieval_context(hit)
                sections.extend(
                    [f"Rank {rank}", _code(json.dumps(visible, ensure_ascii=False, indent=2))]
                )
        sections.append("Original source references")
        sections.append(
            _code(
                json.dumps(
                    [ref.model_dump(exclude_none=True) for ref in refs],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        )
        if not refs:
            sections.append(
                "No original location was recorded. Supporting evidence remains unresolved."
            )
        for ref in refs:
            source = source_manifest.get(ref.source_id)
            if source is not None:
                sections.append(
                    _code(
                        json.dumps(
                            {
                                key: source[key]
                                for key in (
                                    "id",
                                    "relative_path",
                                    "sha256",
                                    "course_id",
                                    "source_type",
                                )
                                if key in source
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                )
    bundle = AnnotationBundle(
        run_id=result["run_id"],
        dataset_id=result["dataset_id"],
        dataset_sha256=result["dataset_sha256"],
        reference_inventory_sha256=reference_inventory_hash(result),
        annotations=annotations,
    )
    # Validate/render everything before creating the directory. Existing packages are immutable.
    payload = bundle.model_dump_json(indent=2) + "\n"
    markdown = "\n\n".join(sections) + "\n"
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    annotation_path = destination / "annotations.json"
    review_path = destination / "review.md"
    annotation_path.write_text(payload, encoding="utf-8")
    review_path.write_text(markdown, encoding="utf-8")
    annotation_path.chmod(0o600)
    review_path.chmod(0o600)
    return {
        "annotations": str(annotation_path),
        "review": str(review_path),
        "case_count": len(cases),
        "blind": blind,
    }
