"""Immutable local Markdown reports and paired comparisons, outside the GUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .annotations import AnnotationBundle, case_sha256, latest_annotations, result_cases
from .metrics import ORIGINS, summarize_benchmark
from .review import _code, _source_refs


def _display(value: Any) -> str:
    if value is None:
        return "Not measured"
    if isinstance(value, float):
        return f"{value:.5g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _rate(value: dict) -> str:
    if value["value"] is None:
        return f"Not measured (0/{value['denominator']})"
    interval = value.get("wilson_95")
    suffix = f"; 95% Wilson {interval[0]:.1%}–{interval[1]:.1%}" if interval else ""
    return f"{value['numerator']}/{value['denominator']} ({value['value']:.1%}{suffix})"


def _safe_configuration(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if any(
                marker in str(key).lower()
                for marker in ("api_key", "authorization", "password", "secret", "access_token")
            )
            else _safe_configuration(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_configuration(item) for item in value]
    return value


def _join_sections(sections: list[str]) -> str:
    output = ""
    for section in sections:
        separator = "\n" if output.rstrip().endswith("|") and section.startswith("|") else "\n\n"
        output += (separator if output else "") + section
    return output + "\n"


def _performance_sections(workloads: dict[str, Any], *, prefix: str = "") -> list[str]:
    sections = [
        f"### {prefix}Isolated workloads",
        "CPU/RSS columns refer to the isolated workload parent and its waited children. "
        "Peaks are separate observations, not additive memory consumption.",
        "| Workload | Status | Sources / failed | Pages | Regions | Native chars | Wall s | "
        "Parent CPU s | Child CPU s | Parent peak bytes | Child peak bytes |\n"
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for identifier, workload in workloads.items():
        values = workload["measurements"]
        sections.append(
            f"| {_display(identifier)} | {_display(workload['status'])} | "
            f"{workload['source_count']}/{workload['failed_sources']} | "
            + " | ".join(
                _display(value)
                for value in [
                    workload["extracted_pages"],
                    workload["regions"],
                    workload["native_characters"],
                    values.get("wall_seconds"),
                    values.get("parent_cpu_seconds"),
                    values.get("child_cpu_seconds"),
                    values.get("parent_peak_rss_bytes"),
                    values.get("child_peak_rss_bytes"),
                ]
            )
            + " |"
        )
    sections.extend(
        [
            f"### {prefix}Cold and repeated pipeline runs",
            "Empty API usage remains unmeasured unless explicitly recorded as zero. "
            "A same-workspace repeat is not a separate cold sample.",
            "| Workload | Repetition | Cache state | Status | Wall s | Logical API calls | "
            "Cached responses | Input tokens | Output tokens | Estimated USD | Unpriced calls |\n"
            "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for identifier, workload in workloads.items():
        for repetition in workload["repetitions"]:
            usage = repetition.get("usage", {})
            sections.append(
                f"| {_display(identifier)} | {_display(repetition.get('index'))} | "
                + " | ".join(
                    _display(value)
                    for value in [
                        repetition.get("cache_state"),
                        repetition.get("status"),
                        repetition.get("wall_seconds"),
                        usage.get("api_calls"),
                        usage.get("cached_calls"),
                        usage.get("input_tokens"),
                        usage.get("output_tokens"),
                        usage.get("estimated_cost_usd"),
                        usage.get("unpriced_calls"),
                    ]
                )
                + " |"
            )
    sections.extend(
        [
            f"### {prefix}Production stage spans and caches",
            "Inclusive stage/operation spans overlap. Their sums are not course runtime. "
            "The initiating-thread CPU excludes other threads and parser/converter processes.",
            "| Workload | Repetition | Stage | Operation | Count | Failed | Wall sum s | "
            "Thread CPU sum s | Stage cache hits | Stage cache misses |\n"
            "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for identifier, workload in workloads.items():
        attempts = workload["repetitions"] or [{"metrics": workload["production_metrics"]}]
        for repetition in attempts:
            measurement = repetition.get("metrics", {}).get("developer_measurements", {})
            for stage, operations in measurement.get("spans", {}).items():
                counts = measurement.get("counts", {}).get(stage, {})
                for operation, values in operations.items():
                    sections.append(
                        f"| {_display(identifier)} | {_display(repetition.get('index'))} | "
                        f"{_display(stage)} | {_display(operation)} | "
                        + " | ".join(
                            _display(value)
                            for value in [
                                values.get("count"),
                                values.get("failed"),
                                values.get("wall_seconds_sum"),
                                values.get("initiating_thread_cpu_seconds_sum"),
                                counts.get("cache_hits"),
                                counts.get("cache_misses"),
                            ]
                        )
                        + " |"
                    )
    return sections


def render_report(result: dict[str, Any], annotations: AnnotationBundle | None = None) -> str:
    metrics = summarize_benchmark(result, annotations)
    evidence = result.get("evidence", {})
    sections = [
        "# Developer benchmark report",
        "Private local evaluation artifact. Model agreement, source agreement and human "
        "validation are distinct.",
        f"Run: `{result['run_id']}`. Dataset: `{result['dataset_id']}`. "
        f"SHA-256: `{result['dataset_sha256']}`.",
        f"Execution: **{_display(evidence.get('execution', 'not_recorded'))}**. "
        "Local extraction and controlled simulations do not measure live model quality, "
        "latency or API cost.",
        "## Workloads",
        "| Course ID | Cards | Concepts | Fidelity cases | Retrieval queries |\n"
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for course in result.get("courses", []):
        identifier = str(course["id"])
        counts = [
            sum(
                str(item.get("workload_id", item.get("course_id"))) == identifier
                for item in result.get(key, [])
            )
            for key in ("cards", "concepts", "fidelity", "retrieval")
        ]
        sections.append(f"| {_display(identifier)} | " + " | ".join(map(str, counts)) + " |")
    sections.extend(
        [
            "## Evidence and quality",
            "Rates use completed latest judgments, separated by origin; unreviewed cases "
            "remain pending. "
            "Distinct reviewers count separately. Intervals are descriptive for the "
            "observed sample and do not "
            "correct selection bias or dependence between cards/reviewers.",
            "| Origin | Reviewed cards / all cards | Accepted unchanged | Requires editing | "
            "Rejected | Observed active seconds |\n"
            "| --- | ---: | --- | --- | --- | ---: |",
        ]
    )
    for origin in ORIGINS:
        summary = metrics["by_origin"][origin]["by_target_type"]["card"]
        sections.append(
            f"| {origin} | {summary['reviewed_case_count']}/{summary['case_count']} | "
            f"{_rate(summary['acceptance_without_edits'])} | "
            f"{_rate(summary['requires_editing'])} | {_rate(summary['rejection'])} | "
            f"{_display(summary['observed_active_review_seconds'])} |"
        )
    for origin in ORIGINS:
        summary = metrics["by_origin"][origin]
        card = summary["by_target_type"]["card"]
        sections.extend(
            [
                f"### {origin.capitalize()} observations",
                f"Completed judgments: {summary['all_cases']['judgment_count']}. "
                "Independently source-grounded judgments: "
                f"{summary['independent_source']['judgment_count']}. "
                "Independence is a declared separate inspection of original evidence; it "
                "does not change the judgment's origin.",
                "| Card dimension | Observed true / assessed |\n| --- | --- |",
            ]
        )
        for name, rate in card["dimensions"].items():
            if rate["denominator"]:
                sections.append(f"| {name.replace('_', ' ')} | {_rate(rate)} |")
        if not any(rate["denominator"] for rate in card["dimensions"].values()):
            sections.append("| All quality dimensions | Not measured |")
        sections.extend(
            [
                "Error categories",
                _code(json.dumps(summary["all_cases"]["error_categories"], indent=2)),
            ]
        )
    sections.extend(
        [
            "## Document fidelity",
            "Literal Unicode/word edit rates require an independently entered reference "
            "transcription. "
            "Equivalent LaTeX spellings can differ, and a low edit rate does not establish "
            "mathematical correctness.",
            "| Reference origin | Measured / reference judgments | "
            "Character errors / reference characters | Word errors / reference words |\n"
            "| --- | ---: | --- | --- |",
        ]
    )
    for origin, data in metrics["document_fidelity"]["by_reference_origin"].items():
        char, word = data["character_error_rate"], data["word_error_rate"]
        sections.append(
            f"| {origin} | {data['measured_judgments']}/{data['reference_judgments']} | "
            f"{char['edit_count']}/{char['reference_characters']} ({_display(char['value'])}) | "
            f"{word['edit_count']}/{word['reference_words']} ({_display(word['value'])}) |"
        )
    sections.extend(
        [
            "## Retrieval",
            "Relevance comes from explicit annotations, never similarity or model "
            "confidence. Precision uses unique "
            "returned results; incomplete hit judgments remain unmeasured. Recall is "
            "aggregated only for declared "
            "complete relevant sets. Partial-set observations remain available in metrics.json.",
            "| Label origin | k | Query judgments | Fully judged queries | "
            "Complete relevant sets | Macro precision | Macro recall | Unjudged returned |\n"
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for origin, data in metrics["retrieval"]["by_label_origin"].items():
        for k, values in data["at_k"].items():
            sections.append(
                f"| {origin} | {k} | {values['query_judgments']} | "
                f"{values['fully_judged_returned_queries']} | "
                f"{values['complete_relevance_queries']} | {_display(values['macro_precision'])} | "
                f"{_display(values['macro_recall'])} | {values['unjudged_returned']} |"
            )
    sections.extend(
        [
            "## Coverage against independent reference targets",
            "The reference inventory is attached only for evaluation. Generated concepts alone "
            "do not supply an independent coverage denominator. Mapping judgments and reference "
            "origins remain separate.",
            _code(json.dumps(metrics["coverage"], ensure_ascii=False, indent=2)),
            "## Performance measurements",
            "Measurements retain their declared scope. Process RSS includes Python/native "
            "allocations in the observed "
            "process; stage response durations can overlap and must not be summed as course "
            "wall time. Unknown pricing "
            "must remain unpriced. Human effort is not estimated from card length.",
            _code(json.dumps(metrics["measurements"], ensure_ascii=False, indent=2)),
            *_performance_sections(metrics["workload_measurements"]),
            "### Observed human effort",
            _code(json.dumps(metrics["observed_human_effort"], ensure_ascii=False, indent=2)),
            "## Configuration and reproducibility",
            _code(
                json.dumps(
                    _safe_configuration(result.get("configuration", {})),
                    ensure_ascii=False,
                    indent=2,
                )
            ),
            _code(
                json.dumps(
                    _safe_configuration(result.get("reproducibility", {})),
                    ensure_ascii=False,
                    indent=2,
                )
            ),
            "## Limitations",
        ]
    )
    sections.extend(
        "- " + item for item in [*metrics["limitations"], *evidence.get("limitations", [])]
    )
    return _join_sections(sections)


def write_report(
    result: dict[str, Any], destination: Path, *, annotations: AnnotationBundle | None = None
) -> Path:
    rendered = render_report(result, annotations)
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(rendered)
    destination.chmod(0o600)
    return destination


def _source_identity(case: dict) -> str:
    return case_sha256(
        {
            "sources": sorted(
                (ref.model_dump(exclude_none=True) for ref in _source_refs(case)),
                key=lambda ref: json.dumps(ref, sort_keys=True),
            )
        }
    )


def compare_results(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_annotations: AnnotationBundle | None = None,
    candidate_annotations: AnnotationBundle | None = None,
) -> dict[str, Any]:
    """Descriptive paired observations; reject unpaired datasets/execution modes."""
    for field in ("dataset_id", "dataset_sha256"):
        if baseline.get(field) != candidate.get(field):
            raise ValueError(f"Cannot compare different {field}; use the same frozen dataset")
    if _workload_selection(baseline) != _workload_selection(candidate):
        raise ValueError(
            "Cannot pair different workloads, source/page selections or development/held-out splits"
        )
    if baseline.get("reference_inventory") != candidate.get("reference_inventory"):
        raise ValueError(
            "Paired reports require the same independently versioned reference inventory"
        )
    if baseline.get("evidence", {}).get("execution") != candidate.get("evidence", {}).get(
        "execution"
    ):
        raise ValueError("Cannot compare different execution evidence modes as paired measurements")
    left_metrics = summarize_benchmark(baseline, baseline_annotations)
    right_metrics = summarize_benchmark(candidate, candidate_annotations)
    left, right = result_cases(baseline), result_cases(candidate)
    shared = {
        key
        for key in left.keys() & right.keys()
        if left[key].get("pairing_eligible") is not False
        and right[key].get("pairing_eligible") is not False
    }
    changed_sources = sorted(
        key for key in shared if _source_identity(left[key]) != _source_identity(right[key])
    )
    if changed_sources:
        raise ValueError(
            "Paired cases have changed original source references; freeze matching inputs"
        )
    pairable = {key for key in shared if _source_refs(left[key])}
    paired = sorted(pairable)
    comparisons = {}
    left_judgments = latest_annotations(baseline_annotations)
    right_judgments = latest_annotations(candidate_annotations)
    for origin in ORIGINS:
        # Pair the same case and reviewer, with the same evaluating model if applicable.
        def judgments_by_key(items, selected_origin=origin):
            groups = {}
            for item in items:
                key = (item.target_type, item.target_id, item.reviewer, item.model)
                if (
                    item.origin == selected_origin
                    and (item.target_type, item.target_id) in pairable
                ):
                    if key in groups:
                        raise ValueError(
                            "Conflicting current judgments require explicit supersession "
                            "before comparison"
                        )
                    groups[key] = item
            return groups

        before = judgments_by_key(left_judgments)
        after = judgments_by_key(right_judgments)
        common = before.keys() & after.keys()
        deltas = [
            int(after[key].decision == "accepted") - int(before[key].decision == "accepted")
            for key in common
        ]
        dimensions = {}
        for dimension in left_metrics["by_origin"][origin]["all_cases"]["dimensions"]:
            observed = [
                key
                for key in common
                if before[key].dimensions.get(dimension) is not None
                and after[key].dimensions.get(dimension) is not None
            ]
            changes = [
                int(after[key].dimensions[dimension]) - int(before[key].dimensions[dimension])
                for key in observed
            ]
            dimensions[dimension] = {
                "paired_judgments": len(changes),
                "mean_delta": sum(changes) / len(changes) if changes else None,
            }
        comparisons[origin] = {
            "paired_judgments": len(deltas),
            "acceptance_delta": sum(deltas) / len(deltas) if deltas else None,
            "dimensions": dimensions,
        }
    return {
        "schema_version": "1",
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "dataset_id": baseline["dataset_id"],
        "dataset_sha256": baseline["dataset_sha256"],
        "paired_cases": [{"type": key[0], "id": key[1]} for key in paired],
        "cases_without_source_evidence": [
            {"type": key[0], "id": key[1]} for key in sorted(shared - pairable)
        ],
        "unpaired_baseline_cases": [
            {"type": key[0], "id": key[1]} for key in sorted(left.keys() - pairable)
        ],
        "unpaired_candidate_cases": [
            {"type": key[0], "id": key[1]} for key in sorted(right.keys() - pairable)
        ],
        "quality_by_origin": comparisons,
        "baseline_metrics": left_metrics,
        "candidate_metrics": right_metrics,
        "configuration_changed": baseline.get("configuration") != candidate.get("configuration"),
        "limitations": [
            "Only identical case IDs and original source references are paired; "
            "configuration differences are retained.",
            "Quality deltas require the same origin, case and reviewer in both runs; "
            "missing observations remain null.",
            "Descriptive differences do not establish statistical significance or broad "
            "academic correctness.",
        ],
    }


def write_comparison(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    destination: Path,
    *,
    baseline_annotations: AnnotationBundle | None = None,
    candidate_annotations: AnnotationBundle | None = None,
) -> Path:
    comparison = compare_results(
        baseline,
        candidate,
        baseline_annotations=baseline_annotations,
        candidate_annotations=candidate_annotations,
    )
    sections = [
        "# Paired developer benchmark comparison",
        f"Baseline: `{baseline['run_id']}`. Candidate: `{candidate['run_id']}`. "
        f"Dataset SHA-256: `{baseline['dataset_sha256']}`.",
        f"Paired cases: {len(comparison['paired_cases'])}. "
        f"Unpaired baseline: {len(comparison['unpaired_baseline_cases'])}. "
        f"Unpaired candidate: {len(comparison['unpaired_candidate_cases'])}.",
        "## Quality observations",
        "| Origin | Paired judgments | Acceptance delta |\n| --- | ---: | ---: |",
    ]
    for origin, data in comparison["quality_by_origin"].items():
        sections.append(
            f"| {origin} | {data['paired_judgments']} | {_display(data['acceptance_delta'])} |"
        )
    sections.extend(
        [
            "## Performance measurements",
            "Baseline",
            _code(json.dumps(baseline.get("measurements", {}), indent=2)),
            "Candidate",
            _code(json.dumps(candidate.get("measurements", {}), indent=2)),
            *_performance_sections(
                comparison["baseline_metrics"]["workload_measurements"], prefix="Baseline: "
            ),
            *_performance_sections(
                comparison["candidate_metrics"]["workload_measurements"], prefix="Candidate: "
            ),
            "## Fidelity and retrieval",
            "Reference annotations remain separated by origin. No reference means no "
            "correctness measurement.",
            "Baseline",
            _code(
                json.dumps(
                    {
                        key: comparison["baseline_metrics"][key]
                        for key in ("document_fidelity", "retrieval", "coverage")
                    },
                    indent=2,
                )
            ),
            "Candidate",
            _code(
                json.dumps(
                    {
                        key: comparison["candidate_metrics"][key]
                        for key in ("document_fidelity", "retrieval", "coverage")
                    },
                    indent=2,
                )
            ),
            "## Configurations",
            "Baseline",
            _code(json.dumps(_safe_configuration(baseline.get("configuration", {})), indent=2)),
            "Candidate",
            _code(json.dumps(_safe_configuration(candidate.get("configuration", {})), indent=2)),
            "## Limitations",
            *["- " + item for item in comparison["limitations"]],
        ]
    )
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(_join_sections(sections))
    destination.chmod(0o600)
    return destination


def _workload_selection(result: dict[str, Any]) -> list:
    workloads = result.get("configuration", {}).get("workloads", [])
    return sorted(
        [
            (
                workload["id"],
                sorted(
                    [
                        (
                            sample["source_id"],
                            tuple(sample.get("page_numbers") or []),
                            sample.get("page_numbers") is None,
                            sample.get("split", "development"),
                        )
                        for sample in workload.get("samples", [])
                    ]
                ),
            )
            for workload in workloads
        ]
    )
