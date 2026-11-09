"""Transparent denominators; model agreement is never counted as human truth."""

from collections import Counter, defaultdict
from typing import Any


def rate(numerator: int | float, denominator: int) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def latest_judgments(judgments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = {}
    for judgment in judgments:
        latest[(judgment["case_id"], judgment["reviewer"], judgment["origin"])] = judgment
    return list(latest.values())


def summarize(
    cases: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    reference: dict[str, Any],
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    """Separate automatic structure, model outcomes, and declared review origins.

    Reference coverage uses explicit mappings. Automatic exact-title mappings are
    an inspection aid; human mappings have separate denominators and never inherit
    the generating model's own confidence.
    """
    judgments = latest_judgments(judgments)
    known = {item["id"]: item for item in reference.get("reference_concepts", [])}
    result: dict[str, Any] = {
        "variants": [],
        "comparisons": [],
        "reference_provenance": reference.get("provenance", "unreviewed"),
        "reference_version": reference.get("version", 1),
        "limitations": [
            "Human/reference provenance is explicitly declared by the local reviewer.",
            "Automated structural checks and model judgments do not establish factual truth.",
            "Unreviewed cases are excluded from human-quality rates, not counted as correct.",
            "Review burden is a word-count heuristic, not a scheduling measurement.",
        ],
    }
    paired: dict[str, dict[str, list[int]]] = {}
    for variant in variants:
        selected = [case for case in cases if case["variant_id"] == variant["id"]]
        ids = {case["case_id"] for case in selected}
        reviews = [judgment for judgment in judgments if judgment["case_id"] in ids]
        mapped = {
            key
            for case in selected
            for key in case.get("reference_concept_ids", [])
            if key in known
        }
        automatic = {
            "card_count": len(selected),
            "schema_validity": rate(
                sum(bool(c.get("automatic", {}).get("schema_valid")) for c in selected),
                len(selected),
            ),
            "source_location_validity": rate(
                sum(bool(c.get("automatic", {}).get("source_locations_valid")) for c in selected),
                len(selected),
            ),
            "exact_title_reference_coverage": rate(len(mapped), len(known)),
            "missing_reference_concepts": [
                item for key, item in known.items() if key not in mapped
            ],
            "estimated_review_seconds": round(
                sum(max(10, len(c["card"].get("answer", "").split()) * 0.8) for c in selected), 1
            ),
        }
        model = dict(Counter(c["card"].get("verification_status", "unverified") for c in selected))
        model_dimensions = defaultdict(Counter)
        failure_categories = Counter()
        for case in selected:
            for check in case.get("checks", []):
                model_dimensions[check["stage"]][check["verdict"]] += 1
                for issue in check.get("issues", []):
                    if isinstance(issue, dict):
                        failure_categories["model:" + issue.get("category", "unspecified")] += 1
        reference_decisions = {}
        for origin in ("human", "synthetic", "model"):
            expected = {
                (item["question"].strip(), item["answer"].strip()): item
                for item in reference.get("reference_cards", [])
                if item.get("label_origin") == origin
            }
            matched = [
                case
                for case in selected
                if (
                    case["card"].get("question", "").strip(),
                    case["card"].get("answer", "").strip(),
                )
                in expected
            ]
            agree = sum(
                (case["card"].get("verification_status") == "verified")
                == (
                    expected[(case["card"]["question"].strip(), case["card"]["answer"].strip())][
                        "expected_label"
                    ]
                    == "correct_useful"
                )
                for case in matched
            )
            reference_decisions[origin] = rate(agree, len(matched))
        origins = {}
        topics = defaultdict(lambda: Counter())
        per_target = defaultdict(list)
        for origin in ("human", "synthetic", "model"):
            group = [item for item in reviews if item["origin"] == origin]
            dimensions = {}
            for dimension in (
                "factual_correct",
                "mathematical_correct",
                "assumptions_complete",
                "atomic",
                "source_correct",
                "useful",
                "unambiguous",
            ):
                observed = [
                    item["dimensions"][dimension]
                    for item in group
                    if item.get("dimensions", {}).get(dimension) is not None
                ]
                dimensions[dimension] = rate(
                    sum(value is True for value in observed), len(observed)
                )
            covered = {
                key
                for item in group
                if item["label"] in {"correct_useful", "needs_improvement"}
                for key in item.get("reference_concept_ids", [])
                if key in known
            }
            reviewed_cases = {item["case_id"] for item in group}
            origins[origin] = {
                "judgments": len(group),
                "reviewed_cases": len(reviewed_cases),
                "review_progress": rate(len(reviewed_cases), len(selected)),
                "acceptance": rate(
                    sum(item["label"] == "correct_useful" for item in group), len(group)
                ),
                "distribution": dict(Counter(item["label"] for item in group)),
                "dimensions": dimensions,
                "reference_concept_coverage": rate(len(covered), len(known)),
                "missing_reference_concepts": [
                    item for key, item in known.items() if key not in covered
                ],
                "independent_judgments": sum(bool(item.get("independent")) for item in group),
            }
            if origin == "human":
                for item in group:
                    for key in item.get("reference_concept_ids", []):
                        if key in known:
                            per_target[key].append(int(item["label"] == "correct_useful"))
                            topics[known[key].get("topic") or "Unassigned"][item["label"]] += 1
        paired[variant["id"]] = dict(per_target)
        failures = [item for item in reviews if item["label"] != "correct_useful"]
        failure_categories.update(item["origin"] + ":" + item["label"] for item in failures)
        result["variants"].append(
            {
                "id": variant["id"],
                "name": variant["name"],
                "automatic": automatic,
                "model_judgments": model,
                "model_dimensions": {key: dict(value) for key, value in model_dimensions.items()},
                "failure_categories": dict(failure_categories),
                "reference_decision_agreement": reference_decisions,
                "reviews": origins,
                "topic_weaknesses": {key: dict(value) for key, value in topics.items()},
                "failed_case_ids": list(dict.fromkeys(item["case_id"] for item in failures)),
                "usage": variant.get("usage", {}),
                "status": variant.get("status", "pending"),
            }
        )
    if variants:
        baseline = variants[0]
        for variant in variants[1:]:
            left, right = paired[baseline["id"]], paired[variant["id"]]
            shared = sorted(left.keys() & right.keys())
            deltas = [
                sum(right[key]) / len(right[key]) - sum(left[key]) / len(left[key])
                for key in shared
            ]
            delta = sum(deltas) / len(deltas) if deltas else None
            result["comparisons"].append(
                {
                    "baseline": baseline["id"],
                    "candidate": variant["id"],
                    "paired_reference_concepts": shared,
                    "paired_target_acceptance_delta": delta,
                    "conclusion": "incomplete"
                    if delta is None
                    else ("improved" if delta > 0 else "degraded" if delta < 0 else "unchanged"),
                    "method": "Mean acceptance difference across the same explicitly human-mapped "
                    "reference concepts; no significance claim.",
                }
            )
    return result
