"""Developer evaluation preserves missing labels, provenance and frozen input boundaries."""

import copy
import json

import pytest

from anki_generator.benchmark.annotations import (
    AnnotationBundle,
    BenchmarkAnnotation,
    ReferenceInventory,
    append_annotations,
    case_sha256,
    load_annotations,
    reference_inventory_hash,
    validate_bundle,
)
from anki_generator.benchmark.metrics import (
    proportion,
    retrieval_metrics,
    summarize_benchmark,
    transcription_error,
)
from anki_generator.benchmark.reports import compare_results, write_comparison, write_report
from anki_generator.benchmark.review import export_review_package


@pytest.fixture
def benchmark_result():
    source = {"source_id": "source-a", "document_sha256": "a" * 64, "page_number": 2}
    return {
        "schema_version": "1",
        "run_id": "baseline",
        "dataset_id": "synthetic-course",
        "dataset_sha256": "b" * 64,
        "configuration": {"models": {"generation": "explicit-model"}},
        "reproducibility": {"git_revision": "revision", "prompt_versions": {"generation": "hash"}},
        "courses": [{"id": "course-a"}],
        "cards": [
            {
                "id": "card-a",
                "course_id": "course-a",
                "question": "When?",
                "answer": "x < y",
                "sources": [source],
            },
            {
                "id": "card-b",
                "course_id": "course-a",
                "question": "Why?",
                "answer": "Reason",
                "sources": [source],
            },
        ],
        "concepts": [
            {"id": "concept-a", "course_id": "course-a", "title": "Order", "sources": [source]}
        ],
        "fidelity": [
            {
                "id": "fidelity-a",
                "course_id": "course-a",
                **source,
                "method": "native",
                "transcription": "x < y",
                "image_path": "/tmp/synthetic.png",
            }
        ],
        "retrieval": [
            {
                "id": "query-a",
                "course_id": "course-a",
                "query": "Order assumptions",
                "sources": [source],
                "hits": [
                    {"id": "evidence-b", "score": 0.9},
                    {"id": "evidence-a", "score": 0.8},
                    {"id": "evidence-a", "score": 0.7},
                ],
            }
        ],
        "measurements": {"wall_seconds": 1.5, "estimated_cost_usd": None},
        "evidence": {"execution": "local_only", "limitations": ["No live calls"]},
    }


def annotation(result, *, kind="card", index=0, **changes):
    collection = {
        "card": "cards",
        "concept": "concepts",
        "fidelity": "fidelity",
        "retrieval": "retrieval",
    }[kind]
    case = result[collection][index]
    return BenchmarkAnnotation.model_validate(
        {
            "id": f"annotation-{kind}-{index}",
            "target_type": kind,
            "target_id": case["id"],
            "target_sha256": case_sha256(case),
            "origin": "human",
            "reviewer": "Actual named reviewer",
            "human_attested": True,
            "decision": "accepted",
            "source_refs": case.get("sources", [])
            or [{key: case[key] for key in ("source_id", "document_sha256", "page_number")}],
            **changes,
        }
    )


def bundle(result, *items):
    return AnnotationBundle(
        run_id=result["run_id"],
        dataset_id=result["dataset_id"],
        dataset_sha256=result["dataset_sha256"],
        reference_inventory_sha256=reference_inventory_hash(result),
        annotations=list(items),
    )


def test_pending_review_export_is_blind_bound_and_never_human_truth(benchmark_result, tmp_path):
    result = benchmark_result
    result["cards"][0]["question"] = "```\n<script>alert('private')</script>\n```"
    paths = export_review_package(result, tmp_path / "review")
    pending = load_annotations(tmp_path / "review/annotations.json", result)
    assert paths["case_count"] == 5
    assert all(
        item.decision == "pending" and not item.human_attested for item in pending.annotations
    )
    markdown = (tmp_path / "review/review.md").read_text()
    assert "explicit-model" not in markdown
    assert "0.9" not in markdown
    assert "````text\n```\n<script>" in markdown
    summary = summarize_benchmark(result, pending)
    assert (
        summary["by_origin"]["human"]["by_target_type"]["card"]["acceptance_without_edits"]["value"]
        is None
    )
    assert summary["observed_human_effort"]["active_seconds"] is None
    with pytest.raises(FileExistsError):
        export_review_package(result, tmp_path / "review")


def test_offline_review_lists_every_long_page_region_with_original_coordinates(
    benchmark_result, tmp_path
):
    result = benchmark_result
    result["fidelity"][0]["regions"] = [
        {
            "id": f"tile-{index}",
            "bbox": [0, index * 100, 200, (index + 1) * 100],
            "image_path": f"/tmp/private notes/tile-{index}.png",
            "pixel_width": 400,
            "pixel_height": 200,
        }
        for index in range(3)
    ]
    result["source_manifest"] = [
        {"id": "source-a", "sha256": "a" * 64, "relative_path": "course/long-page.pdf"}
    ]
    export_review_package(result, tmp_path / "long-review")
    text = (tmp_path / "long-review/review.md").read_text()
    for index in range(3):
        assert f"tile-{index}.png" in text
        assert (
            f"[Open original region {index + 1}](</tmp/private%20notes/tile-{index}.png>)" in text
        )
    assert "course/long-page.pdf" in text
    assert '"bbox": [' in text


@pytest.mark.parametrize(
    "changes",
    [
        {"human_attested": False},
        {"reviewer": " "},
        {
            "origin": "model",
            "model": "model-id",
            "human_attested": False,
            "active_review_seconds": 10,
        },
        {"origin": "model", "model": "model-id", "human_attested": True},
        {"decision": "pending", "dimensions": {"factual_correct": True}},
        {"dimensions": {"invented_accuracy": True}},
        {"independent_source": True, "source_refs": []},
        {"active_review_seconds": float("nan")},
        {"actions": ["edited"]},
    ],
)
def test_judgments_reject_fabricated_or_contradictory_declarations(benchmark_result, changes):
    with pytest.raises(ValueError):
        annotation(benchmark_result, **changes)


@pytest.mark.parametrize("mutation", ["run", "dataset", "content", "source", "unknown_target"])
def test_import_rejects_changed_or_forged_frozen_boundary(benchmark_result, mutation):
    result = benchmark_result
    values = bundle(result, annotation(result)).model_dump()
    if mutation == "run":
        values["run_id"] = "other"
    if mutation == "dataset":
        values["dataset_sha256"] = "d" * 64
    if mutation == "content":
        result["cards"][0]["answer"] = "Changed answer"
    if mutation == "source":
        values["annotations"][0]["source_refs"][0]["document_sha256"] = "e" * 64
    if mutation == "unknown_target":
        values["annotations"][0]["target_id"] = "missing"
    with pytest.raises(ValueError):
        validate_bundle(AnnotationBundle.model_validate(values), result)


def test_append_only_annotation_revisions_preserve_observed_effort(benchmark_result, tmp_path):
    result = benchmark_result
    original = annotation(
        result, decision="needs_edit", active_review_seconds=11, actions=["edited"]
    )
    previous = bundle(result, original)
    path = append_annotations(result, previous, tmp_path / "first.json")
    first_bytes = path.read_bytes()
    edited = original.model_copy(update={"rationale": "Overwriting previous judgment"})
    with pytest.raises(ValueError, match="overwrite"):
        append_annotations(result, bundle(result, edited), tmp_path / "bad.json", existing=previous)
    revised = annotation(result, id="revised", supersedes=original.id, active_review_seconds=5)
    destination = append_annotations(
        result, bundle(result, revised), tmp_path / "second.json", existing=previous
    )
    current = load_annotations(destination, result)
    assert len(current.annotations) == 2
    assert path.read_bytes() == first_bytes
    metrics = summarize_benchmark(result, current)
    assert metrics["by_origin"]["human"]["all_cases"]["judgment_count"] == 1
    assert metrics["observed_human_effort"]["active_seconds"] == 16
    assert metrics["observed_human_effort"]["performed_actions"] == {"edited": 1}
    with pytest.raises(FileExistsError):
        append_annotations(result, current, destination)


def test_supersession_cannot_hide_other_reviewers_or_loop(benchmark_result):
    result = benchmark_result
    first = annotation(result)
    second = annotation(result, id="second", reviewer="Another reviewer", supersedes=first.id)
    with pytest.raises(ValueError, match="same target"):
        validate_bundle(bundle(result, first, second), result)
    cyclic = first.model_copy(update={"supersedes": "second"})
    second = first.model_copy(update={"id": "second", "supersedes": first.id})
    with pytest.raises(ValueError, match="cycles"):
        validate_bundle(bundle(result, cyclic, second), result)


def test_quality_denominators_separate_model_human_and_unknown(benchmark_result):
    result = benchmark_result
    human = annotation(
        result,
        dimensions={"factual_correct": False, "mathematical_correct": None},
        decision="rejected",
    )
    model = annotation(
        result,
        id="model",
        origin="model",
        model="actual-model",
        human_attested=False,
        reviewer="",
        dimensions={"factual_correct": True},
        independent_source=True,
    )
    metrics = summarize_benchmark(result, bundle(result, human, model))
    assert metrics["by_origin"]["human"]["by_target_type"]["card"]["unreviewed_case_count"] == 1
    assert metrics["by_origin"]["human"]["all_cases"]["acceptance_without_edits"]["value"] == 0
    assert metrics["by_origin"]["model"]["all_cases"]["acceptance_without_edits"]["value"] == 1
    assert (
        metrics["by_origin"]["human"]["all_cases"]["dimensions"]["mathematical_correct"]["value"]
        is None
    )
    assert metrics["by_origin"]["model"]["independent_source"]["judgment_count"] == 1
    assert metrics["by_origin"]["synthetic"]["all_cases"]["judgment_count"] == 0


def test_literal_transcription_metrics_catch_math_sign_and_empty_boundaries():
    metric = transcription_error("x < y", "x ≤ y")
    assert metric["character_error_rate"]["edit_count"] == 1
    assert metric["character_error_rate"]["value"] == 0.2
    assert metric["word_error_rate"]["value"] == pytest.approx(1 / 3)
    assert transcription_error("anything", "")["status"] == "not_measured"
    assert (
        transcription_error("long", "reference", max_characters=3)["reason"]
        == "transcription_length_limit"
    )
    assert transcription_error("abc", "x")["character_error_rate"]["value"] == 3


def test_fidelity_requires_reference_and_preserves_origin(benchmark_result):
    result = benchmark_result
    empty = summarize_benchmark(result)["document_fidelity"]
    assert empty["by_reference_origin"]["human"]["character_error_rate"]["value"] is None
    reference = annotation(
        result,
        kind="fidelity",
        reference_transcription="x ≤ y",
        origin="model",
        human_attested=False,
        reviewer="",
        method="Independent agent image inspection; exact model identifier unavailable",
        independent_source=True,
    )
    measured = summarize_benchmark(result, bundle(result, reference))["document_fidelity"]
    assert measured["by_reference_origin"]["model"]["character_error_rate"]["value"] == 0.2
    assert measured["by_reference_origin"]["human"]["measured_judgments"] == 0


def test_retrieval_does_not_promote_unjudged_hits_to_relevant_or_irrelevant(benchmark_result):
    result = benchmark_result
    labels = annotation(
        result,
        kind="retrieval",
        relevance=[{"id": "evidence-a", "relevant": True}, {"id": "evidence-c", "relevant": True}],
    )
    metric = retrieval_metrics(result["retrieval"][0], labels, ks=(1, 2, 5))
    assert metric["duplicate_hit_count"] == 1
    at_two = metric["at_k"]["2"]
    assert at_two["precision"]["value"] is None
    assert at_two["unjudged_returned"] == 1
    assert at_two["judged_precision"]["value"] == 1
    assert at_two["recall_of_declared_relevant"]["value"] == 0.5
    assert at_two["recall_universe"] == "partial"
    summary = summarize_benchmark(result, bundle(result, labels))["retrieval"]["by_label_origin"][
        "human"
    ]["at_k"]["3"]
    assert summary["macro_recall"] is None
    assert summary["macro_precision"] is None


def test_complete_retrieval_labels_compute_macro_micro_and_fewer_than_k(benchmark_result):
    result = benchmark_result
    labels = annotation(
        result,
        kind="retrieval",
        relevance=[
            {"id": "evidence-a", "relevant": True},
            {"id": "evidence-b", "relevant": False},
            {"id": "evidence-c", "relevant": True},
        ],
        relevance_universe_complete=True,
    )
    summary = summarize_benchmark(result, bundle(result, labels))["retrieval"]["by_label_origin"][
        "human"
    ]["at_k"]["5"]
    assert summary["macro_precision"] == 0.5
    assert summary["macro_recall"] == 0.5
    assert summary["micro_precision"]["denominator"] == 2
    assert summary["complete_relevance_queries"] == 1


def test_wilson_intervals_and_missing_denominators_are_explicit():
    assert proportion(0, 0)["wilson_95"] is None
    interval = proportion(5, 10)["wilson_95"]
    assert interval == pytest.approx([0.236593, 0.763407], abs=1e-6)
    assert proportion(0, 1)["wilson_95"][1] > 0
    with pytest.raises(ValueError):
        proportion(2, 1)


def add_references(result):
    source = result["cards"][0]["sources"][0]
    result["reference_inventory"] = ReferenceInventory(
        dataset_id=result["dataset_id"],
        dataset_sha256=result["dataset_sha256"],
        origin="model",
        method="Independent original-page inspection; exact model identity unavailable",
        independent_source=True,
        concepts=[
            {
                "id": "ref-theorem",
                "label": "Order theorem",
                "kind": "theorem",
                "importance": 2,
                "assumptions": ["real scalars"],
                "source_refs": [source],
            },
            {
                "id": "ref-method",
                "label": "Order method",
                "kind": "method",
                "competencies": ["choose a bound"],
                "source_refs": [source],
            },
        ],
    ).model_dump()


def test_coverage_requires_independent_targets_not_generated_inventory(benchmark_result):
    result = benchmark_result
    assert summarize_benchmark(result)["coverage"]["status"] == "not_measured"
    add_references(result)
    pending = summarize_benchmark(result)["coverage"]
    assert pending["status"] == "not_measured"
    assert pending["by_mapping_origin"]["human"]["accepted_target_coverage"]["value"] is None
    judgment = annotation(result, reference_concept_ids=["ref-theorem"])
    coverage = summarize_benchmark(result, bundle(result, judgment))["coverage"]
    assert coverage["reference_origin"] == "model"
    assert coverage["reference_universe_complete"] is False
    assert coverage["by_mapping_origin"]["human"]["accepted_target_coverage"]["value"] == 0.5
    assert coverage["by_mapping_origin"]["human"][
        "accepted_target_importance_fraction"
    ] == pytest.approx(2 / 3)
    assert coverage["by_mapping_origin"]["human"]["missing_accepted_targets"] == ["ref-method"]
    assert coverage["by_mapping_origin"]["model"]["accepted_target_coverage"]["numerator"] == 0


def test_reference_inventory_cannot_claim_human_or_forged_source(benchmark_result):
    result = benchmark_result
    add_references(result)
    result["reference_inventory"]["origin"] = "human"
    with pytest.raises(ValueError, match="attestation"):
        summarize_benchmark(result)
    add_references(result)
    result["reference_inventory"]["concepts"][0]["source_refs"][0]["document_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="source"):
        summarize_benchmark(result)


def test_comparison_pairs_cases_and_reviewers_without_invented_quality(benchmark_result, tmp_path):
    left = benchmark_result
    right = copy.deepcopy(left)
    right["run_id"] = "candidate"
    right["cards"][0]["answer"] = "x ≤ y"
    empty = compare_results(left, right)
    assert len(empty["paired_cases"]) == 5
    assert empty["quality_by_origin"]["human"]["acceptance_delta"] is None
    before = annotation(left, decision="rejected", dimensions={"mathematical_correct": False})
    after = annotation(right, dimensions={"mathematical_correct": True})
    measured = compare_results(
        left,
        right,
        baseline_annotations=bundle(left, before),
        candidate_annotations=bundle(right, after),
    )
    assert measured["quality_by_origin"]["human"]["acceptance_delta"] == 1
    assert measured["quality_by_origin"]["model"]["acceptance_delta"] is None
    different_reviewer = after.model_copy(update={"reviewer": "Different reviewer"})
    not_paired = compare_results(
        left,
        right,
        baseline_annotations=bundle(left, before),
        candidate_annotations=bundle(right, different_reviewer),
    )
    assert not_paired["quality_by_origin"]["human"]["paired_judgments"] == 0
    destination = write_comparison(left, right, tmp_path / "comparison.md")
    assert "Not measured" in destination.read_text()


@pytest.mark.parametrize("mutation", ["dataset", "execution", "source"])
def test_comparison_rejects_incomparable_source_or_execution(benchmark_result, mutation):
    candidate = copy.deepcopy(benchmark_result)
    candidate["run_id"] = "candidate"
    if mutation == "dataset":
        candidate["dataset_sha256"] = "d" * 64
    if mutation == "execution":
        candidate["evidence"]["execution"] = "openai"
    if mutation == "source":
        candidate["cards"][0]["sources"][0]["page_number"] = 3
    with pytest.raises(ValueError):
        compare_results(benchmark_result, candidate)


def test_report_preserves_missing_measurements_redacts_secrets_and_is_immutable(
    benchmark_result, tmp_path
):
    result = benchmark_result
    result["configuration"]["api_key"] = "do-not-include"
    report = write_report(result, tmp_path / "report.md")
    text = report.read_text()
    assert "do-not-include" not in text
    assert "[redacted]" in text
    assert "Not measured" in text
    assert "local_only" in text
    assert "explicit-model" in text
    with pytest.raises(FileExistsError):
        write_report(result, report)


def test_annotation_json_roundtrip_preserves_history_and_rejects_duplicate_ids(
    benchmark_result, tmp_path
):
    result = benchmark_result
    values = bundle(result, annotation(result)).model_dump()
    path = tmp_path / "human.json"
    path.write_text(json.dumps(values))
    assert load_annotations(path, result).annotations[0].human_attested
    values["annotations"].append(values["annotations"][0])
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="unique"):
        load_annotations(path, result)


def test_workload_identity_and_full_performance_snapshots_survive_reporting(
    benchmark_result, tmp_path
):
    result = benchmark_result
    result["courses"] = [
        {
            "id": "selected-workload",
            "status": "completed",
            "source_ids": ["source-a"],
            "sources": [
                {
                    "source_id": "source-a",
                    "status": "partial",
                    "extracted_pages": 2,
                    "regions": 4,
                    "native_characters": 300,
                    "render_pixels": 12000,
                }
            ],
            "measurements": {
                "wall_seconds": 7.5,
                "parent_cpu_seconds": 2.5,
                "parent_peak_rss_bytes": 500000,
            },
            "repetitions": [
                {
                    "index": 0,
                    "cache_state": "cold",
                    "status": "completed",
                    "wall_seconds": 5,
                    "usage": {"api_calls": 0, "cached_calls": 2},
                    "metrics": {
                        "developer_measurements": {
                            "spans": {
                                "extraction": {
                                    "stage": {
                                        "count": 1,
                                        "failed": 0,
                                        "wall_seconds_sum": 4,
                                        "initiating_thread_cpu_seconds_sum": 0.1,
                                    }
                                }
                            },
                            "counts": {"extraction": {"cache_misses": 1}},
                            "subprocesses": {"extraction": {"worker_peak_rss_bytes_max": 200000}},
                        }
                    },
                }
            ],
        }
    ]
    for collection in ("cards", "concepts", "fidelity", "retrieval"):
        for case in result[collection]:
            case["workload_id"] = "selected-workload"
    labels = bundle(result, annotation(result))
    metrics = summarize_benchmark(result, labels)
    assert metrics["by_course"]["selected-workload"]["human"]["reviewed_case_count"] == 1
    workload = metrics["workload_measurements"]["selected-workload"]
    assert workload["native_characters"] == 300
    assert (
        workload["repetitions"][0]["metrics"]["developer_measurements"]["subprocesses"][
            "extraction"
        ]["worker_peak_rss_bytes_max"]
        == 200000
    )
    report = write_report(result, tmp_path / "workload.md", annotations=labels).read_text()
    assert "| selected-workload | 2 | 1 | 1 | 1 |" in report
    assert "| selected-workload | completed | 1/0 | 2 | 4 | 300 | 7.5 |" in report
    assert "| selected-workload | 0 | cold | completed | 5 | 0 | 2 |" in report
    assert "| selected-workload | 0 | extraction | stage | 1 | 0 | 4 | 0.1 |" in report
    assert "Generated concepts alone do not supply an independent coverage denominator" in report
    assert "|\n\n|" not in report


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "different-source"),
        ("page_numbers", [2, 3]),
        ("split", "held_out"),
    ],
)
def test_pairing_rejects_different_workload_sampling_but_allows_model_settings(
    benchmark_result, field, value
):
    baseline = benchmark_result
    baseline["configuration"]["workloads"] = [
        {
            "id": "sample",
            "samples": [{"source_id": "source-a", "page_numbers": [2], "split": "development"}],
        }
    ]
    candidate = copy.deepcopy(baseline)
    candidate["run_id"] = "candidate"
    candidate["configuration"]["models"]["generation"] = "different-model"
    assert compare_results(baseline, candidate)["configuration_changed"]
    candidate["configuration"]["workloads"][0]["samples"][0][field] = value
    with pytest.raises(ValueError, match="source/page selections"):
        compare_results(baseline, candidate)


def test_explicitly_unpairable_outputs_never_create_quality_deltas(benchmark_result):
    baseline = benchmark_result
    candidate = copy.deepcopy(baseline)
    candidate["run_id"] = "candidate"
    candidate["cards"][0]["pairing_eligible"] = False
    compared = compare_results(baseline, candidate)
    assert {"type": "card", "id": "card-a"} not in compared["paired_cases"]
    assert {"type": "card", "id": "card-a"} in compared["unpaired_baseline_cases"]
    assert {"type": "card", "id": "card-a"} in compared["unpaired_candidate_cases"]
