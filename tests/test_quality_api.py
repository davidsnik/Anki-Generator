"""HTTP contracts for granular retries and paginated source/identity review."""

from sqlalchemy import select
from support.controlled_provider import ControlledProvider

from anki_generator.database.entities import Card, Run
from anki_generator.database.pipeline_entities import IdentityProposal


def _generate(api_client, course):
    rt = api_client.app.state.runtime
    provider = ControlledProvider()
    rt.runner.provider_factory = lambda key, config: provider
    rt.secrets.set("controlled-test-key")
    api_client.post(
        f"/api/courses/{course['id']}/documents",
        files=[
            (
                "files",
                (
                    "lecture.txt",
                    b"For a right triangle, a^2 + b^2 = c^2.\n"
                    b"The right-angle assumption is necessary.\n",
                    "text/plain",
                ),
            )
        ],
    )
    response = api_client.post(f"/api/courses/{course['id']}/runs", json={"consent": True})
    assert response.status_code == 202, response.text
    identifier = response.json()["id"]
    rt.runner.run_now(identifier)
    run = api_client.get(f"/api/runs/{identifier}").json()
    assert run["status"] == "completed", run["error"]
    return rt, provider, run


def test_selected_stage_retry_reuses_unrelated_calls_and_checks_consent(api_client, course):
    rt, provider, first = _generate(api_client, course)
    counts = provider.calls.copy()
    denied = api_client.post(f"/api/runs/{first['id']}/retry-stage", json={"stage": "factual"})
    assert denied.status_code == 400
    retry = api_client.post(
        f"/api/runs/{first['id']}/retry-stage", json={"stage": "factual", "consent": True}
    )
    assert retry.status_code == 202, retry.text
    rt.runner.run_now(retry.json()["id"])
    completed = api_client.get(f"/api/runs/{retry.json()['id']}").json()
    assert completed["status"] == "completed", completed["error"]
    assert completed["request"]["retry_of"] == first["id"]
    assert provider.calls["factual"] == counts["factual"] + 1
    for stage in (
        "knowledge",
        "consolidation",
        "source_audit",
        "generation",
        "pedagogical",
        "mathematical",
    ):
        assert provider.calls[stage] == counts[stage], stage
    with rt.sessions() as session:
        assert len(list(session.scalars(select(Card)))) == 1


def test_coverage_filters_and_export_identity_api(api_client, course):
    rt, _, run = _generate(api_client, course)
    report = api_client.get(
        f"/api/courses/{course['id']}/coverage-targets?kind=theorem&status=covered&limit=1"
    ).json()
    assert report["total"] == 1 and len(report["items"]) == 1
    assert report["summary"]["by_kind"] == {"theorem": 1}
    concept_id = report["items"][0]["mapped_concept_ids"][0]
    assert (
        api_client.get(
            f"/api/courses/{course['id']}/coverage-targets?topic_id={concept_id}"
        ).json()["total"]
        == 1
    )
    preview = api_client.get(f"/api/courses/{course['id']}/export-preview?limit=1").json()
    assert preview["counts"]["new"] == 1 and preview["pagination"]["limit"] == 1
    with rt.sessions.begin() as session:
        card = session.scalar(select(Card))
        proposal = IdentityProposal(
            course_id=course["id"],
            run_id=run["id"],
            entity_type="card",
            candidate_key="possible-split",
            candidate_id=card.id,
            reason="Potential split",
        )
        session.add(proposal)
        session.flush()
        identifier = proposal.id
    pending = api_client.get(f"/api/courses/{course['id']}/identity-proposals?limit=1").json()
    assert pending["total"] == 1
    resolved = api_client.post(
        f"/api/identity-proposals/{identifier}/resolve",
        json={"decision": "new", "rationale": "Reviewed as an independent target"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["state"] == "new"
    assert api_client.get(f"/api/courses/{course['id']}/identity-proposals").json()["total"] == 0


def test_paired_prepared_run_never_queues_before_explicit_enqueue(
    api_client, course, source_document
):
    from anki_generator.services.run_submission import submit_run

    rt = api_client.app.state.runtime
    rt.secrets.set("controlled-test-key")
    run = submit_run(
        rt,
        course["id"],
        {"consent": True},
        {"processing": {"concurrency": 3}, "prompt_overrides": {"knowledge": "Variant prompt."}},
        enqueue=False,
    )
    with rt.sessions() as session:
        saved = session.get(Run, run["id"])
        assert saved.status == "prepared"
        assert saved.config["processing"]["concurrency"] == 3
        assert saved.config["prompt_hashes"]["knowledge"]
    rt.runner.run_now(run["id"])
    assert api_client.get(f"/api/runs/{run['id']}").json()["status"] == "prepared"


def test_queued_revision_refuses_newer_edit(api_client, course):
    rt, provider, _ = _generate(api_client, course)
    with rt.sessions() as session:
        card = session.scalar(select(Card))
        identifier = card.id
        revision = card.revision_number
    response = api_client.post(
        f"/api/courses/{course['id']}/runs",
        json={
            "mode": "revise",
            "card_id": identifier,
            "expected_revision": revision,
            "consent": True,
            "instruction": "Clarify the assumption",
        },
    )
    assert response.status_code == 202
    with rt.sessions.begin() as session:
        card = session.get(Card, identifier)
        card.question = "Newer user wording"
        card.revision_number += 1
        card.manually_edited = True
    rt.runner.run_now(response.json()["id"])
    failed = api_client.get(f"/api/runs/{response.json()['id']}").json()
    assert failed["status"] == "failed" and "newer edit was preserved" in failed["error"]
    with rt.sessions() as session:
        assert session.get(Card, identifier).question == "Newer user wording"
    assert provider.calls["revision"] == 0
