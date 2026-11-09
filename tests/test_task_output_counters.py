"""Task counters record distinct outputs, survive retry and stay historical."""

from support.controlled_provider import ControlledProvider


def prepare(api_client, course):
    rt = api_client.app.state.runtime
    provider = ControlledProvider()
    rt.runner.provider_factory = lambda key, config: provider
    rt.secrets.set("controlled-test-key")
    imported = api_client.post(
        f"/api/courses/{course['id']}/documents",
        files={
            "files": (
                "triangle.txt",
                b"For a right triangle, a^2 + b^2 = c^2.\nThe right-angle assumption is necessary.",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    return rt, provider


def execute(api_client, course, rt, key):
    submitted = api_client.post(
        f"/api/courses/{course['id']}/runs", json={"consent": True, "idempotency_key": key}
    )
    assert submitted.status_code == 202, submitted.text
    rt.runner.run_now(submitted.json()["id"])
    return api_client.get(f"/api/tasks/{submitted.json()['id']}").json()


def test_output_counters_distinguish_generation_reuse_and_later_course_changes(api_client, course):
    rt, _ = prepare(api_client, course)
    first = execute(api_client, course, rt, "first-run-12345")
    assert first["status"] == "completed", first.get("error")
    stats = first["statistics"]
    assert stats["concepts_extracted"] == 1
    assert stats["cards_generated"] == stats["cards_new"] == stats["cards_verified"] == 1
    assert stats["cards_reused"] == 0
    extra = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={"question": "A manual addition", "answer": "An unrelated answer"},
    )
    assert extra.status_code == 201, extra.text
    second = execute(api_client, course, rt, "second-run-12345")
    assert second["status"] == "completed", second.get("error")
    assert second["statistics"]["cards_generated"] == 0
    assert second["statistics"]["cards_reused"] == 1
    assert second["statistics"]["cards_verified"] == 1
    after = api_client.get(f"/api/tasks/{first['id']}").json()["statistics"]
    assert after["cards_generated"] == after["cards_verified"] == 1
    assert after["cards_current"] == 2
    page = api_client.get("/api/tasks").json()
    assert next(item for item in page["items"] if item["id"] == first["id"])["statistics"] == {
        key: value for key, value in after.items() if key != "cards_checked_this_run"
    }


def test_retry_does_not_double_count_outputs_and_stage_retry_creates_new_intent(api_client, course):
    rt, provider = prepare(api_client, course)
    provider.fail_stage, provider.fail_once = "factual", True
    first = execute(api_client, course, rt, "retry-run-123456")
    assert first["status"] == "failed"
    assert first["statistics"]["cards_generated"] == first["statistics"]["cards_new"] == 1
    retry = api_client.post(f"/api/runs/{first['id']}/retry")
    assert retry.status_code == 200, retry.text
    rt.runner.run_now(first["id"])
    recovered = api_client.get(f"/api/tasks/{first['id']}").json()
    assert recovered["status"] == "completed", recovered.get("error")
    assert recovered["statistics"]["cards_generated"] == recovered["statistics"]["cards_new"] == 1
    assert recovered["statistics"]["cards_verified"] == 1
    stage_retry = api_client.post(
        f"/api/runs/{first['id']}/retry-stage", json={"stage": "factual", "consent": True}
    )
    assert stage_retry.status_code == 202, stage_retry.text
    assert stage_retry.json()["id"] != first["id"]
