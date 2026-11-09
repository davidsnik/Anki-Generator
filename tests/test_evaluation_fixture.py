"""The portable example binds actual synthetic sources without invented human labels."""

import hashlib
import json
from pathlib import Path

from anki_generator.evaluation.contracts import DatasetInput


def test_synthetic_benchmark_keeps_provenance_defects_and_source_hashes():
    root = Path(__file__).resolve().parents[1]
    path = root / "fixtures/evaluation/synthetic-probability.json"
    benchmark = DatasetInput.model_validate(json.loads(path.read_text()))
    assert benchmark.provenance == "synthetic"
    assert {card.expected_label for card in benchmark.reference_cards} == {
        "correct_useful",
        "needs_improvement",
        "incorrect",
        "ambiguous",
        "redundant",
        "not_worth_memorizing",
    }
    assert all(
        card.label_origin == "synthetic" and not card.independent
        for card in benchmark.reference_cards
    )
    assert {item["kind"] for item in benchmark.annotations} == {
        "missing_concept",
        "interpretation_error",
    }
    assert any(item.assumptions for item in benchmark.reference_concepts)
    assert any(item.competencies for item in benchmark.reference_concepts)
    for source in benchmark.sources:
        assert (
            hashlib.sha256((root / source["relative_path"]).read_bytes()).hexdigest()
            == source["sha256"]
        )
