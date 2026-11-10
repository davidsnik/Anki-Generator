"""Transparent developer metrics; no model score is academic ground truth."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .annotations import (
    DIMENSIONS,
    AnnotationBundle,
    BenchmarkAnnotation,
    latest_annotations,
    reference_inventory,
    result_cases,
    validate_bundle,
)

ORIGINS = ("deterministic", "model", "human", "synthetic")


def proportion(numerator: int, denominator: int) -> dict[str, Any]:
    """A descriptive Wilson interval, conditional on the observed sample only.

    Cards/reviewer judgments can be dependent and samples need not be random. The
    interval is not a population generalization or an inter-rater agreement test.
    """
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise ValueError("A proportion requires 0 <= numerator <= denominator")
    interval = None
    if denominator:
        z = 1.959963984540054
        value = numerator / denominator
        scale = 1 + z * z / denominator
        center = (value + z * z / (2 * denominator)) / scale
        half = (
            z
            * math.sqrt(value * (1 - value) / denominator + z * z / (4 * denominator * denominator))
            / scale
        )
        interval = [max(0.0, center - half), min(1.0, center + half)]
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "wilson_95": interval,
    }


def _judgment_summary(items: list[BenchmarkAnnotation], total_cases: int) -> dict[str, Any]:
    decisions = Counter(item.decision for item in items)
    errors = Counter(error.category for item in items for error in item.errors)
    dimensions = {}
    for dimension in DIMENSIONS:
        observed = [
            item.dimensions[dimension]
            for item in items
            if item.dimensions.get(dimension) is not None
        ]
        dimensions[dimension] = proportion(sum(value is True for value in observed), len(observed))
    observed_times = [
        item.active_review_seconds for item in items if item.active_review_seconds is not None
    ]
    cases = {(item.target_type, item.target_id) for item in items}
    return {
        "judgment_count": len(items),
        "reviewed_case_count": len(cases),
        "case_count": total_cases,
        "unreviewed_case_count": total_cases - len(cases),
        "decision_distribution": dict(decisions),
        "acceptance_without_edits": proportion(decisions["accepted"], len(items)),
        "requires_editing": proportion(decisions["needs_edit"], len(items)),
        "rejection": proportion(decisions["rejected"], len(items)),
        "dimensions": dimensions,
        "error_categories": dict(errors),
        "severity": dict(Counter(error.severity for item in items for error in item.errors)),
        "observed_active_review_seconds": sum(observed_times) if observed_times else None,
        "judgments_with_observed_time": len(observed_times),
        "time_measurement": "Explicit reviewer-recorded active seconds; no inferred or "
        "model-estimated time.",
    }


def _edit_distance(left: list[str] | str, right: list[str] | str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, character in enumerate(left, 1):
        current = [row]
        for column, other in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (character != other),
                )
            )
        previous = current
    return previous[-1]


def transcription_error(actual: str, reference: str, *, max_characters: int = 5000) -> dict:
    """Exact codepoint Levenshtein; retain mathematical symbols and case.

    Whitespace/LaTeX variants are not normalized into mathematical equivalence.
    Empty reference and oversized comparisons remain unmeasured. Error rates can
    exceed one because inserted content is an error too.
    """
    if max(len(actual), len(reference)) > max_characters:
        return {"status": "not_measured", "reason": "transcription_length_limit"}
    if not reference:
        return {"status": "not_measured", "reason": "empty_reference"}
    reference_words = reference.split()
    character_edits = _edit_distance(actual, reference)
    word_edits = _edit_distance(actual.split(), reference_words)
    return {
        "status": "measured",
        "character_error_rate": {
            "value": character_edits / len(reference),
            "edit_count": character_edits,
            "reference_characters": len(reference),
        },
        "word_error_rate": {
            "value": word_edits / len(reference_words) if reference_words else None,
            "edit_count": word_edits,
            "reference_words": len(reference_words),
        },
        "method": "Exact Unicode codepoint/whitespace-word Levenshtein; no mathematical "
        "equivalence claim.",
    }


def _fidelity(result: dict, annotations: list[BenchmarkAnnotation]) -> dict:
    cases = {str(case["id"]): case for case in result.get("fidelity", [])}
    groups = {}
    for origin in ORIGINS:
        observations = []
        for annotation in annotations:
            if annotation.target_type != "fidelity" or annotation.origin != origin:
                continue
            if annotation.reference_transcription is None:
                continue
            case = cases[annotation.target_id]
            metric = transcription_error(
                case.get("transcription", ""), annotation.reference_transcription
            )
            observations.append(
                {
                    "case_id": annotation.target_id,
                    "annotation_id": annotation.id,
                    "independent_source": annotation.independent_source,
                    **metric,
                }
            )
        measured = [item for item in observations if item["status"] == "measured"]
        character_edits = sum(item["character_error_rate"]["edit_count"] for item in measured)
        character_count = sum(
            item["character_error_rate"]["reference_characters"] for item in measured
        )
        word_edits = sum(item["word_error_rate"]["edit_count"] for item in measured)
        word_count = sum(item["word_error_rate"]["reference_words"] for item in measured)
        groups[origin] = {
            "reference_judgments": len(observations),
            "measured_judgments": len(measured),
            "character_error_rate": {
                "value": character_edits / character_count if character_count else None,
                "edit_count": character_edits,
                "reference_characters": character_count,
            },
            "word_error_rate": {
                "value": word_edits / word_count if word_count else None,
                "edit_count": word_edits,
                "reference_words": word_count,
            },
            "cases": observations,
        }
    return {"case_count": len(cases), "by_reference_origin": groups}


def retrieval_metrics(
    case: dict,
    annotation: BenchmarkAnnotation,
    *,
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict:
    """Ranked unique hits and explicit labels; unjudged hits never become negatives.

    Recall refers to the declared relevant set. It is labeled partial when the
    reviewer has not declared the relevance universe complete. Precision over all
    returned hits is only measurable when those hits are all explicitly judged.
    """
    if (
        not ks
        or any(not isinstance(k, int) or isinstance(k, bool) or k < 1 for k in ks)
        or len(set(ks)) != len(ks)
    ):
        raise ValueError("Retrieval k values must be distinct positive integers")
    ranked = list(dict.fromkeys(str(item["id"]) for item in case.get("hits", [])))
    labels = {item.id: item.relevant for item in annotation.relevance}
    relevant = {key for key, value in labels.items() if value}
    at_k = {}
    for k in sorted(ks):
        hits = ranked[:k]
        judged = [key for key in hits if key in labels]
        found = len(set(hits) & relevant)
        at_k[str(k)] = {
            "returned": len(hits),
            "judged_returned": len(judged),
            "unjudged_returned": len(hits) - len(judged),
            "relevant_returned": found,
            "precision": proportion(found, len(hits))
            if len(judged) == len(hits)
            else {"value": None, "numerator": found, "denominator": len(hits), "wilson_95": None},
            "judged_precision": proportion(found, len(judged)),
            "recall_of_declared_relevant": proportion(found, len(relevant)),
            "recall_universe": "complete" if annotation.relevance_universe_complete else "partial",
            "missing_declared_relevant": sorted(relevant - set(hits)),
        }
    return {
        "case_id": str(case["id"]),
        "annotation_id": annotation.id,
        "origin": annotation.origin,
        "independent_source": annotation.independent_source,
        "declared_relevant_count": len(relevant),
        "relevance_universe_complete": annotation.relevance_universe_complete,
        "duplicate_hit_count": len(case.get("hits", [])) - len(ranked),
        "at_k": at_k,
        "precision_denominator": "Unique returned hits, up to k; fewer than k results are "
        "reported explicitly.",
    }


def _retrieval(result: dict, annotations: list[BenchmarkAnnotation], ks: tuple[int, ...]) -> dict:
    cases = {str(case["id"]): case for case in result.get("retrieval", [])}
    groups = {}
    for origin in ORIGINS:
        observations = [
            retrieval_metrics(cases[item.target_id], item, ks=ks)
            for item in annotations
            if item.target_type == "retrieval" and item.origin == origin and item.relevance
        ]
        summary = {}
        for k in sorted(ks):
            rows = [item["at_k"][str(k)] for item in observations]
            complete = [row for row in rows if row["precision"]["value"] is not None]
            recall = [
                row
                for row in rows
                if row["recall_universe"] == "complete"
                and row["recall_of_declared_relevant"]["value"] is not None
            ]
            summary[str(k)] = {
                "query_judgments": len(rows),
                "fully_judged_returned_queries": len(complete),
                "complete_relevance_queries": len(recall),
                "macro_precision": sum(row["precision"]["value"] for row in complete)
                / len(complete)
                if complete
                else None,
                "macro_recall": sum(row["recall_of_declared_relevant"]["value"] for row in recall)
                / len(recall)
                if recall
                else None,
                "micro_precision": proportion(
                    sum(row["relevant_returned"] for row in complete),
                    sum(row["returned"] for row in complete),
                ),
                "micro_recall": proportion(
                    sum(row["recall_of_declared_relevant"]["numerator"] for row in recall),
                    sum(row["recall_of_declared_relevant"]["denominator"] for row in recall),
                ),
                "unjudged_returned": sum(row["unjudged_returned"] for row in rows),
            }
        groups[origin] = {"judgments": len(observations), "at_k": summary, "cases": observations}
    return {"case_count": len(cases), "by_label_origin": groups}


def summarize_benchmark(
    result: dict[str, Any],
    annotations: AnnotationBundle | None = None,
    *,
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[str, Any]:
    if annotations is not None:
        validate_bundle(annotations, result)
    cases = result_cases(result)
    judgments = latest_annotations(annotations)
    by_origin = {}
    for origin in ORIGINS:
        group = [item for item in judgments if item.origin == origin]
        by_origin[origin] = {
            "all_cases": _judgment_summary(group, len(cases)),
            "by_target_type": {
                kind: _judgment_summary(
                    [item for item in group if item.target_type == kind],
                    sum(key[0] == kind for key in cases),
                )
                for kind in ("card", "concept", "fidelity", "retrieval")
            },
            "independent_source": _judgment_summary(
                [item for item in group if item.independent_source], len(cases)
            ),
        }
    by_course = {}
    for course in result.get("courses", []):
        course_id = str(course["id"])
        keys = {
            key
            for key, case in cases.items()
            if str(case.get("workload_id", case.get("course_id"))) == course_id
        }
        by_course[course_id] = {
            origin: _judgment_summary(
                [
                    item
                    for item in judgments
                    if item.origin == origin and (item.target_type, item.target_id) in keys
                ],
                len(keys),
            )
            for origin in ORIGINS
        }
    return {
        "schema_version": "1",
        "run_id": result["run_id"],
        "dataset_id": result["dataset_id"],
        "case_counts": dict(Counter(key[0] for key in cases)),
        "annotation_events": len(annotations.annotations) if annotations else 0,
        "completed_current_judgments": len(judgments),
        "observed_human_effort": _human_effort(annotations),
        "by_origin": by_origin,
        "by_course": by_course,
        "document_fidelity": _fidelity(result, judgments),
        "retrieval": _retrieval(result, judgments, ks),
        "coverage": _coverage(result, judgments),
        "measurements": result.get("measurements", {}),
        "workload_measurements": workload_measurements(result),
        "limitations": [
            "Human, model, deterministic and synthetic observations have separate denominators.",
            "Independent source agreement does not establish mathematical correctness; "
            "model agreement is not proof.",
            "Pending/unreviewed cases never count as accepted. Multiple reviewers "
            "contribute separate judgments.",
            "Wilson intervals describe observed binary samples; dependent cards/reviews and "
            "nonrandom sampling limit generalization.",
            "Human timing is observed only when explicitly recorded by a human reviewer; "
            "unavailable timing remains null.",
            "Transcription edit rates compare notation literally and do not establish "
            "mathematical equivalence.",
        ],
    }


def workload_measurements(result: dict[str, Any]) -> dict[str, Any]:
    """Keep full production counters and cold/repeat snapshots, with compact source totals."""
    workloads = {}
    for course in result.get("courses", []):
        sources = course.get("sources", [])

        def observed_sum(field: str, observed_sources=sources):
            values = [
                source[field]
                for source in observed_sources
                if isinstance(source.get(field), (int, float))
            ]
            return sum(values) if values else None

        workloads[str(course["id"])] = {
            "status": course.get("status"),
            "source_ids": course.get("source_ids", [source.get("source_id") for source in sources]),
            "source_count": len(sources),
            "failed_sources": sum(source.get("status") == "failed" for source in sources),
            "extracted_pages": observed_sum("extracted_pages"),
            "native_characters": observed_sum("native_characters"),
            "regions": observed_sum("regions"),
            "render_pixels": observed_sum("render_pixels"),
            "measurements": course.get("measurements", {}),
            "production_metrics": course.get("metrics", {}),
            "usage": course.get("usage", {}),
            "repetitions": course.get("repetitions", []),
            "sources": sources,
        }
    return workloads


def _human_effort(bundle: AnnotationBundle | None) -> dict:
    events = (
        [
            item
            for item in bundle.annotations
            if item.origin == "human" and item.decision != "pending"
        ]
        if bundle
        else []
    )
    timed = [
        item.active_review_seconds for item in events if item.active_review_seconds is not None
    ]
    return {
        "review_events": len(events),
        "distinct_cases_reviewed": len({(item.target_type, item.target_id) for item in events}),
        "timed_events": len(timed),
        "active_seconds": sum(timed) if timed else None,
        "performed_actions": dict(Counter(action for item in events for action in item.actions)),
        "scope": "All declared completed human annotation events, including superseded "
        "history; active seconds are per-event observations.",
        "limitations": "No observed annotations means no observed human effort. Needs-edit "
        "judgments do not imply an edit was performed.",
    }


def _coverage(result: dict, annotations: list[BenchmarkAnnotation]) -> dict:
    inventory = reference_inventory(result)
    if inventory is None:
        return {
            "status": "not_measured",
            "reason": "No independent reference inventory was supplied.",
            "by_mapping_origin": {},
        }
    targets = {target.id: target for target in inventory.concepts}
    groups = {}
    for origin in ORIGINS:
        group = [
            item for item in annotations if item.origin == origin and item.target_type == "card"
        ]
        accepted = {
            identifier
            for item in group
            if item.decision == "accepted"
            for identifier in item.reference_concept_ids
            if identifier in targets
        }
        needs_edit = {
            identifier
            for item in group
            if item.decision == "needs_edit"
            for identifier in item.reference_concept_ids
            if identifier in targets
        }
        observed = [item for item in group if item.reference_concept_ids]

        def observed_proportion(numerator, denominator, assessed=bool(observed)):
            measured = proportion(numerator, denominator)
            if not assessed:
                measured.update(value=None, wilson_95=None)
            return measured

        groups[origin] = {
            "mapping_judgments": len(observed),
            "accepted_target_coverage": observed_proportion(len(accepted), len(targets)),
            "accepted_target_importance_fraction": (
                sum(targets[key].importance for key in accepted)
                / sum(target.importance for target in targets.values())
            )
            if observed
            else None,
            "targets_mapped_to_cards_requiring_edits": sorted(needs_edit),
            "missing_accepted_targets": sorted(targets.keys() - accepted),
            "by_kind": {
                kind: observed_proportion(
                    sum(key in accepted for key, target in targets.items() if target.kind == kind),
                    sum(target.kind == kind for target in targets.values()),
                )
                for kind in sorted({target.kind for target in targets.values()})
            },
            "targets_with_assumptions": sum(
                bool(target.assumptions) for target in targets.values()
            ),
            "targets_with_competencies": sum(
                bool(target.competencies) for target in targets.values()
            ),
        }
    return {
        "status": "measured_against_declared_targets"
        if any(value["mapping_judgments"] for value in groups.values())
        else "not_measured",
        "inventory_id": inventory.id,
        "reference_origin": inventory.origin,
        "reference_model": inventory.model,
        "reference_method": inventory.method,
        "independent_source": inventory.independent_source,
        "reference_universe_complete": inventory.complete,
        "reference_target_count": len(targets),
        "by_mapping_origin": groups,
        "limitations": "Coverage is an observed mapping fraction of declared targets, not a claim "
        "that all unreviewed cards were assessed. Mapping a theorem does not "
        "establish that every assumption was correctly recalled. "
        "Model reference targets remain provisional.",
    }
