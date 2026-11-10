"""Offline judgments bound to frozen benchmark cases, never generation inputs.

Origins describe who or what made a judgment. Independence describes whether the
original source was inspected through a separate path; it never promotes a model
judgment to human ground truth. Declarations cannot authenticate reviewer expertise.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from anki_generator.domain import InputModel

Origin = Literal["human", "model", "deterministic", "synthetic"]
TargetType = Literal["card", "concept", "fidelity", "retrieval"]
Decision = Literal["pending", "accepted", "needs_edit", "rejected", "unresolved"]

DIMENSIONS = (
    "factual_correct",
    "mathematical_correct",
    "assumptions_complete",
    "theorem_correct",
    "source_interpretation_correct",
    "clear",
    "unambiguous",
    "atomic",
    "useful",
    "concise",
    "spaced_repetition_suitable",
    "transferable",
    "notation_correct",
    "source_reference_correct",
    "evidence_supports_claim",
    "nonredundant",
    "coverage_complete",
)

ERROR_CATEGORIES = (
    "factual_error",
    "mathematical_error",
    "unsupported_claim",
    "missing_assumption",
    "incorrect_theorem",
    "misleading_simplification",
    "source_interpretation",
    "unclear_question",
    "ambiguous_answer",
    "non_atomic",
    "not_useful",
    "verbose_answer",
    "unsuitable_for_spaced_repetition",
    "weak_transfer",
    "missing_concept",
    "missing_technique",
    "exercise_competency_gap",
    "redundant",
    "trivial_overrepresentation",
    "notation",
    "source_reference",
    "layout",
    "equation",
    "chart",
    "diagram",
    "table",
    "other",
)


class SourceReference(InputModel):
    source_id: str = Field(min_length=1, max_length=300)
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_number: int = Field(ge=1)
    region_id: str | None = Field(default=None, max_length=300)
    bbox: tuple[float, float, float, float] | None = None

    @field_validator("bbox")
    @classmethod
    def ordered_box(cls, value):
        if value is not None and (
            not all(math.isfinite(number) for number in value)
            or value[0] < 0
            or value[1] < 0
            or value[2] <= value[0]
            or value[3] <= value[1]
        ):
            raise ValueError("Source coordinates must form a finite positive-area box")
        return value


class ErrorAnnotation(InputModel):
    category: str = Field(min_length=1, max_length=100)
    severity: Literal["minor", "major", "critical"] = "major"
    rationale: str = Field(min_length=1, max_length=20000)
    expected: str | None = Field(default=None, max_length=100000)
    actual: str | None = Field(default=None, max_length=100000)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in ERROR_CATEGORIES:
            raise ValueError("Unknown error category; use other and explain in rationale")
        return value


class RelevanceLabel(InputModel):
    id: str = Field(min_length=1, max_length=300)
    relevant: bool


class ReferenceTarget(InputModel):
    """An independently authored expected learning target, separate from generated concepts."""

    id: str = Field(min_length=1, max_length=300)
    label: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="concept", min_length=1, max_length=100)
    importance: float = Field(default=1, gt=0, le=3)
    assumptions: list[str] = Field(default_factory=list, max_length=1000)
    competencies: list[str] = Field(default_factory=list, max_length=1000)
    source_refs: list[SourceReference] = Field(min_length=1, max_length=1000)


class ReferenceInventory(InputModel):
    schema_version: Literal["1"] = "1"
    id: str = Field(default="reference-v1", min_length=1, max_length=300)
    dataset_id: str = Field(min_length=1, max_length=300)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin: Origin
    reviewer: str = Field(default="", max_length=300)
    model: str | None = Field(default=None, max_length=300)
    method: str = Field(default="", max_length=2000)
    human_attested: bool = False
    independent_source: bool = False
    complete: bool = False
    concepts: list[ReferenceTarget] = Field(min_length=1, max_length=100000)

    @model_validator(mode="after")
    def declared_provenance(self):
        if self.origin == "human" and (not self.reviewer.strip() or not self.human_attested):
            raise ValueError(
                "Human reference targets require a reviewer and explicit human attestation"
            )
        if self.origin == "model" and not ((self.model or "").strip() or self.method.strip()):
            raise ValueError("Identify the model or explicitly describe its unavailable identity")
        if self.origin in {"deterministic", "synthetic"} and not self.method.strip():
            raise ValueError("Identify the method producing these reference targets")
        if self.origin != "human" and self.human_attested:
            raise ValueError("Model and synthetic targets cannot claim human validation")
        if len({item.id for item in self.concepts}) != len(self.concepts):
            raise ValueError("Reference target IDs must be unique")
        return self


class BenchmarkAnnotation(InputModel):
    id: str = Field(min_length=1, max_length=300)
    target_type: TargetType
    target_id: str = Field(min_length=1, max_length=300)
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin: Origin = "human"
    decision: Decision = "pending"
    reviewer: str = Field(default="", max_length=300)
    model: str | None = Field(default=None, max_length=300)
    method: str = Field(default="", max_length=2000)
    independent_source: bool = False
    human_attested: bool = False
    dimensions: dict[str, bool | None] = Field(default_factory=dict)
    errors: list[ErrorAnnotation] = Field(default_factory=list, max_length=1000)
    source_refs: list[SourceReference] = Field(default_factory=list, max_length=1000)
    reference_concept_ids: list[str] = Field(default_factory=list, max_length=10000)
    reference_transcription: str | None = Field(default=None, max_length=100000)
    relevance: list[RelevanceLabel] = Field(default_factory=list, max_length=100000)
    relevance_universe_complete: bool = False
    active_review_seconds: float | None = Field(default=None, ge=0, le=604800)
    actions: list[Literal["edited", "regeneration_requested"]] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=30000)
    created_at: str = Field(default="", max_length=100)
    supersedes: str | None = Field(default=None, max_length=300)

    @field_validator("dimensions")
    @classmethod
    def known_dimensions(cls, value):
        if set(value) - set(DIMENSIONS):
            raise ValueError("Unknown quality dimension")
        return value

    @model_validator(mode="after")
    def truthful_declarations(self):
        completed = self.decision != "pending"
        if (
            completed
            and self.origin == "human"
            and (not self.reviewer.strip() or not self.human_attested)
        ):
            raise ValueError("Completed human judgments require a reviewer and human attestation")
        if (
            completed
            and self.origin == "model"
            and not ((self.model or "").strip() or self.method.strip())
        ):
            raise ValueError(
                "Identify the actual model or explicitly describe unavailable identity"
            )
        if completed and self.origin in {"deterministic", "synthetic"} and not self.method.strip():
            raise ValueError("Identify the deterministic method or synthetic fixture")
        if self.origin != "human" and (
            self.human_attested or self.active_review_seconds is not None or self.actions
        ):
            raise ValueError("Only actual human judgments can declare human attestation or time")
        if self.active_review_seconds is not None and not math.isfinite(self.active_review_seconds):
            raise ValueError("Human review time must be finite")
        if self.decision == "pending" and (
            any(value is not None for value in self.dimensions.values())
            or self.errors
            or self.relevance
            or self.reference_transcription is not None
            or self.active_review_seconds is not None
            or self.actions
        ):
            raise ValueError("Pending annotations cannot contain completed judgments")
        if self.independent_source and not self.source_refs:
            raise ValueError(
                "Independent source judgments require inspected original source references"
            )
        if self.target_type != "retrieval" and (self.relevance or self.relevance_universe_complete):
            raise ValueError("Relevance labels belong to retrieval cases")
        if self.target_type != "fidelity" and self.reference_transcription is not None:
            raise ValueError("Reference transcriptions belong to fidelity cases")
        labels = [item.id for item in self.relevance]
        if len(set(labels)) != len(labels):
            raise ValueError("Retrieval relevance IDs must be unique")
        if len(set(self.reference_concept_ids)) != len(self.reference_concept_ids):
            raise ValueError("Reference concept IDs must be unique")
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("Review actions must be distinct within each observed event")
        if self.decision == "accepted" and "edited" in self.actions:
            raise ValueError("Accepted unchanged cannot simultaneously record a performed edit")
        if self.supersedes == self.id:
            raise ValueError("An annotation cannot supersede itself")
        return self


class AnnotationBundle(InputModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(min_length=1, max_length=300)
    dataset_id: str = Field(min_length=1, max_length=300)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_inventory_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    annotations: list[BenchmarkAnnotation] = Field(default_factory=list, max_length=100000)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [item.id for item in self.annotations]
        if len(ids) != len(set(ids)):
            raise ValueError("Annotation IDs must be unique; preserve history using supersedes")
        return self


def case_sha256(case: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            case, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def result_cases(result: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    cases = {}
    for kind, collection in (
        ("card", "cards"),
        ("concept", "concepts"),
        ("fidelity", "fidelity"),
        ("retrieval", "retrieval"),
    ):
        for case in result.get(collection, []):
            key = (kind, str(case["id"]))
            if key in cases:
                raise ValueError("Benchmark case IDs must be unique within each case type")
            cases[key] = case
    return cases


def validate_bundle(bundle: AnnotationBundle, result: dict[str, Any]) -> AnnotationBundle:
    for field in ("run_id", "dataset_id", "dataset_sha256"):
        if getattr(bundle, field) != result.get(field):
            raise ValueError(f"Annotation {field} does not match the frozen benchmark result")
    cases = result_cases(result)
    by_id = {item.id: item for item in bundle.annotations}
    inventory = reference_inventory(result)
    inventory_hash = (
        case_sha256(inventory.model_dump(mode="json")) if inventory is not None else None
    )
    if bundle.reference_inventory_sha256 is not None:
        if bundle.reference_inventory_sha256 != inventory_hash:
            raise ValueError(
                "Annotation reference inventory hash changed; export a new review package"
            )
    elif any(item.reference_concept_ids for item in bundle.annotations):
        raise ValueError("Coverage mappings require a frozen reference inventory hash")
    target_ids = {target.id for target in inventory.concepts} if inventory else set()
    known_sources = _source_identities(result)
    for item in bundle.annotations:
        case = cases.get((item.target_type, item.target_id))
        if case is None:
            raise ValueError("Annotation target does not exist in the frozen benchmark result")
        if case_sha256(case) != item.target_sha256:
            raise ValueError("Annotation target content changed; export a new review package")
        if any(
            (ref.source_id, ref.document_sha256) not in known_sources for ref in item.source_refs
        ):
            raise ValueError(
                "Annotation source hash or identity is absent from the frozen benchmark"
            )
        if set(item.reference_concept_ids) - target_ids:
            raise ValueError("Coverage mappings require explicit independent reference targets")
        if item.supersedes:
            previous = by_id.get(item.supersedes)
            if previous is None:
                raise ValueError("Superseded annotation is missing from append-only history")
            if (
                previous.target_type,
                previous.target_id,
                previous.origin,
                previous.reviewer,
                previous.model,
            ) != (item.target_type, item.target_id, item.origin, item.reviewer, item.model):
                raise ValueError(
                    "An annotation can supersede only the same target, origin and reviewer"
                )
            visited = {item.id}
            while previous is not None:
                if previous.id in visited:
                    raise ValueError("Annotation supersession history cannot contain cycles")
                visited.add(previous.id)
                previous = by_id.get(previous.supersedes) if previous.supersedes else None
    current_keys = set()
    for item in latest_annotations(bundle):
        key = (item.target_type, item.target_id, item.origin, item.reviewer, item.model)
        if key in current_keys:
            raise ValueError("Repeated current judgments require explicit supersession")
        current_keys.add(key)
    return bundle


def load_annotations(path: Path, result: dict[str, Any]) -> AnnotationBundle:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Annotation file exceeds the 64 MiB developer-artifact limit")
    return validate_bundle(
        AnnotationBundle.model_validate_json(path.read_text(encoding="utf-8")), result
    )


def latest_annotations(bundle: AnnotationBundle | None) -> list[BenchmarkAnnotation]:
    """Only explicit supersession replaces history; conflicting reviewers stay distinct."""
    if bundle is None:
        return []
    superseded = {item.supersedes for item in bundle.annotations if item.supersedes}
    return [
        item
        for item in bundle.annotations
        if item.id not in superseded and item.decision != "pending"
    ]


def append_annotations(
    result: dict[str, Any],
    incoming: AnnotationBundle,
    destination: Path,
    *,
    existing: AnnotationBundle | None = None,
) -> Path:
    """Write a new artifact preserving every prior event; never mutate an old file."""
    if existing is not None:
        validate_bundle(existing, result)
    if any(item.reference_concept_ids for item in incoming.annotations) and (
        incoming.reference_inventory_sha256 is None
    ):
        raise ValueError("Coverage mappings require a frozen reference inventory hash")
    if (
        existing is not None
        and incoming.reference_inventory_sha256 is not None
        and existing.reference_inventory_sha256 is not None
        and incoming.reference_inventory_sha256 != existing.reference_inventory_sha256
    ):
        raise ValueError("Cannot merge annotations from different reference inventory hashes")
    entries = {item.id: item for item in existing.annotations} if existing else {}
    for item in incoming.annotations:
        if item.id in entries and entries[item.id] != item:
            raise ValueError("Cannot overwrite an annotation; use a new ID and supersedes")
        entries[item.id] = item
    combined = AnnotationBundle.model_validate(
        {
            **incoming.model_dump(),
            "reference_inventory_sha256": incoming.reference_inventory_sha256
            or (existing.reference_inventory_sha256 if existing is not None else None),
            "annotations": list(entries.values()),
        }
    )
    validate_bundle(combined, result)
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(combined.model_dump_json(indent=2) + "\n")
    destination.chmod(0o600)
    return destination


def reference_inventory(result: dict[str, Any]) -> ReferenceInventory | None:
    """Validate a report-only reference inventory, never an input to generation."""
    payload = result.get("reference_inventory")
    if payload is None:
        return None
    inventory = ReferenceInventory.model_validate(payload)
    for field in ("dataset_id", "dataset_sha256"):
        if getattr(inventory, field) != result.get(field):
            raise ValueError(f"Reference inventory {field} differs from the frozen dataset")
    sources = _source_identities(result)
    for concept in inventory.concepts:
        if any((ref.source_id, ref.document_sha256) not in sources for ref in concept.source_refs):
            raise ValueError("Reference target source is absent from the frozen benchmark")
    return inventory


def reference_inventory_hash(result: dict[str, Any]) -> str | None:
    """Hash validated reference meaning, independent of JSON whitespace/default omission."""
    inventory = reference_inventory(result)
    return case_sha256(inventory.model_dump(mode="json")) if inventory is not None else None


def _source_identities(result: dict[str, Any]) -> set[tuple[str, str]]:
    sources = {
        (ref.source_id, ref.document_sha256)
        for case in result_cases(result).values()
        for ref in _case_sources(case)
    }
    sources.update(
        (source["id"], source["sha256"])
        for source in result.get("source_manifest", [])
        if source.get("id") and source.get("sha256")
    )
    return sources


def _case_sources(case: dict[str, Any]) -> list[SourceReference]:
    """Only the portable source fields are interpreted, not imported document text."""
    candidates = list(case.get("sources", []))
    if {"source_id", "document_sha256", "page_number"} <= case.keys():
        candidates.append(case)
    refs = []
    for source in candidates:
        if {"source_id", "document_sha256", "page_number"} <= source.keys():
            refs.append(
                SourceReference.model_validate(
                    {key: source[key] for key in SourceReference.model_fields if key in source}
                )
            )
    return refs
