"""Actual ranking traces bind only objects and evidence that were retained."""

from anki_generator.benchmark.worker import portable_retrieval_cases


def event(query="query", run="run"):
    return {
        "id": "raw-trace",
        "stage": "deduplication",
        "query": {"id": query, "kind": "card"},
        "candidate_kind": "card",
        "production_run_id": run,
        "hits": [{"id": "candidate", "score": 0.75, "rank": 1}],
        "judgment_status": "pending",
    }


def bound(identifier="stable-query"):
    return {
        "id": identifier,
        "question": "Synthetic retained target",
        "sources": [{"source_id": "a" * 24, "document_sha256": "b" * 64, "page_number": 2}],
        "pairing_eligible": True,
    }


def test_portable_rankings_use_bound_query_and_repetition_not_random_database_ids():
    before = portable_retrieval_cases(
        [event(), event()],
        {("card", "query"): bound(), ("card", "candidate"): bound("stable-hit")},
        {"run": 0},
    )
    after = portable_retrieval_cases(
        [event("new-query", "new-run"), event("new-query", "new-run")],
        {("card", "new-query"): bound(), ("card", "candidate"): bound("stable-hit")},
        {"new-run": 0},
    )
    assert [case["id"] for case in before] == [case["id"] for case in after]
    assert before[0]["id"] != before[1]["id"]
    assert before[0]["hits"][0]["id"] == "stable-hit"
    assert before[0]["hits"][0]["score"] == 0.75
    assert before[0]["pairing_eligible"]
    assert before[0]["judgment_status"] == "pending"
    assert "relevance" not in before[0]["hits"][0]


def test_opaque_query_context_remains_unresolved_and_cannot_pair():
    result = portable_retrieval_cases([event()], {}, {"run": 0})[0]
    assert result["query"]["object"] is None
    assert result["sources"] == []
    assert not result["pairing_eligible"]
    assert result["hits"][0]["source_binding_status"] == "unresolved"
    assert "pending" in result["relevance_status"]


def test_source_targets_resolve_against_the_observed_production_run():
    trace = event()
    trace["query"] = {"kind": "source_target", "id": "same-target-key"}
    objects = {
        ("source_target", "same-target-key", "run"): bound("actual-run-target"),
        ("source_target", "same-target-key", "other-run"): bound("different-run-target"),
    }
    result = portable_retrieval_cases([trace], objects, {"run": 1})[0]
    assert result["query"]["object"]["id"] == "actual-run-target"
    assert result["repetition"] == 1
