"""Auditable role/authority and repeated-competency importance signals."""

import math
from typing import Any


def importance_from_sources(
    model_estimate: float,
    sources: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    exercises: list[dict[str, Any]],
    influence: dict[str, float],
) -> tuple[float, dict[str, Any]]:
    by_id = {doc["id"]: doc for doc in documents}
    document_ids = sorted({ref["document_id"] for ref in sources if ref["document_id"] in by_id})
    signals = []
    for document_id in document_ids:
        doc = by_id[document_id]
        role = doc["category"]
        authority = doc.get("authority", "unknown")
        weight = influence.get(
            role,
            {
                "lecture": 1,
                "personal_notes": 0.7,
                "exercises": 1.2,
                "solutions": 1,
                "reference": 0.8,
            }.get(role, 0.8),
        )
        if role == "solutions":
            weight *= 1.1 if authority == "official" else 0.65 if authority == "student" else 0.8
        if role == "reference" and any(
            word in doc["filename"].casefold() for word in ("syllabus", "objective", "curriculum")
        ):
            weight *= 1.3
        signals.append(
            {
                "document_id": document_id,
                "role": role,
                "authority": authority,
                "weight": round(weight, 4),
            }
        )
    # Distinct source-linked exercise strategies, not arbitrary model frequency or
    # repeated copies of the same numerical exercise, contribute to recurrence.
    signatures = {
        (
            e.get("reusable_strategy", "").casefold(),
            tuple(sorted((r["document_id"], r["page_number"]) for r in e.get("sources", []))),
        )
        for e in exercises
        if e.get("reusable_strategy")
    }
    average = sum(item["weight"] for item in signals) / max(len(signals), 1)
    recurrence = min(0.18, math.log1p(len(signatures)) * 0.08)
    score = min(1, max(0, model_estimate * (0.65 + min(average, 2) * 0.35) + recurrence))
    return round(score, 4), {
        "model_estimate": model_estimate,
        "source_signals": signals,
        "distinct_exercise_patterns": len(signatures),
        "recurrence_bonus": round(recurrence, 4),
        "meaning": "Prioritization evidence, not factual confidence or correctness.",
    }
