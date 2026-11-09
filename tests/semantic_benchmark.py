"""Optional real embedding + independent LLM benchmark with synthetic references.

uv run python tests/semantic_benchmark.py --live --consent --output /tmp/semantic.json
Reads OPENAI_API_KEY in memory. Never runs an external request without both flags.
The reference cases are author-created examples, not human evaluation evidence.
"""

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

from anki_generator.llm.provider import DEFAULT_MODEL, OpenAIProvider
from anki_generator.processing.contracts import DuplicateDecision
from anki_generator.services.semantic import SemanticIndex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (args.live and args.consent):
        parser.error(
            "This benchmark requires explicit --live --consent; "
            "offline mechanics are covered by pytest"
        )
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        parser.error("Configure OPENAI_API_KEY for this process; it is never saved")
    provider = OpenAIProvider(key)
    fixture = json.loads(Path("fixtures/semantic/cases.json").read_text())
    cases = fixture["cases"]
    texts = [
        text
        for case in cases
        for text in (
            case["left"] + "\n" + case["left_answer"],
            case["right"] + "\n" + case["right_answer"],
        )
    ]
    started = perf_counter()
    embedded = provider.embed(texts, model="text-embedding-3-small", dimensions=512)
    rows = []
    for index, case in enumerate(cases):
        vectors = {"left": embedded.vectors[index * 2], "right": embedded.vectors[index * 2 + 1]}
        score = SemanticIndex(vectors).search(vectors["left"], limit=1, exclude={"left"})[0][1]
        result = provider.structured(
            "deduplication",
            {
                "candidate": {
                    "id": "left",
                    "question": case["left"],
                    "answer": case["left_answer"],
                },
                "retrieved_cards": [
                    {"id": "right", "question": case["right"], "answer": case["right_answer"]}
                ],
                "retrieval": "real_neural_embedding_candidate_not_equivalence",
            },
            DuplicateDecision,
            model=DEFAULT_MODEL,
        )
        rows.append(
            {
                "id": case["id"],
                "category": case["category"],
                "cosine": score,
                "reference_duplicate": case["duplicate"],
                "model_decision": result.data.model_dump(),
                "reference_agreement": result.data.duplicate == case["duplicate"],
                "usage": result.usage,
            }
        )
    args.output.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "label_origin": fixture["label_origin"],
                "embedding_model": embedded.model,
                "decision_model": DEFAULT_MODEL,
                "embedding_usage": embedded.usage,
                "elapsed_seconds": perf_counter() - started,
                "cases": rows,
                "agreement": {
                    "numerator": sum(row["reference_agreement"] for row in rows),
                    "denominator": len(rows),
                },
                "limitations": [
                    "Small synthetic reference set; no independent human labels.",
                    "Candidate cosine is not a correctness or equivalence probability.",
                ],
            },
            indent=2,
        )
    )
    print(args.output)


if __name__ == "__main__":
    main()
