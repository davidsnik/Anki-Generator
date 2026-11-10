"""Blind ranking review includes source-grounded context without internal verdicts."""

from anki_generator.benchmark.review import export_review_package


def test_captured_retrieval_review_shows_objects_but_hides_scores_and_model_verdicts(tmp_path):
    source = {"source_id": "a" * 24, "document_sha256": "b" * 64, "page_number": 1}
    result = {
        "run_id": "synthetic-review",
        "dataset_id": "synthetic-dataset",
        "dataset_sha256": "c" * 64,
        "retrieval": [
            {
                "id": "query-1",
                "sources": [source],
                "query": {
                    "id": "query-card",
                    "kind": "card",
                    "object": {
                        "question": "Which assumption is needed?",
                        "answer": "Positive x.",
                        "sources": [source],
                        "verification_status": "INTERNAL_VERDICT",
                        "verifications": [{"model": "hidden-evaluator-model", "score": 0.98765}],
                    },
                },
                "hits": [
                    {
                        "id": "candidate-1",
                        "score": 0.98765,
                        "object": {
                            "title": "Candidate target",
                            "description": "A relevant statement.",
                            "metadata": {"assumptions": ["x > 0"], "model": "hidden-model"},
                            "sources": [source],
                            "review_status": "INTERNAL_REVIEW_VERDICT",
                        },
                    },
                ],
                "object_context_scope": "Final saved object state, not query-time wording.",
            },
        ],
    }
    exported = export_review_package(result, tmp_path / "review", blind=True)
    text = (tmp_path / "review" / "review.md").read_text()
    assert exported["case_count"] == 1
    for visible in (
        "Which assumption is needed?",
        "Candidate target",
        "A relevant statement.",
        "x > 0",
        "Final saved object state, not query-time wording.",
    ):
        assert visible in text
    for hidden in (
        "INTERNAL_VERDICT",
        "INTERNAL_REVIEW_VERDICT",
        "hidden-model",
        "hidden-evaluator-model",
        "0.98765",
    ):
        assert hidden not in text
