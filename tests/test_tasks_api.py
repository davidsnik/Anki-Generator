"""Atomic submissions, bounded task history and persistent queue controls."""

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from anki_generator.database.entities import Run
from anki_generator.database.task_entities import JobEvent


def test_simultaneous_settings_saves_cannot_leave_live_limits_behind_database(
    api_client, monkeypatch
):
    rt = api_client.app.state.runtime
    entered, release = threading.Event(), threading.Event()
    waiting = threading.Event()
    actual_lock = threading.Lock()

    class ObservedLock:
        def __enter__(self):
            if actual_lock.locked():
                waiting.set()
            actual_lock.acquire()

        def __exit__(self, *args):
            actual_lock.release()

    monkeypatch.setattr(rt, "settings_lock", ObservedLock())
    real_configure = rt.runner.resources.configure
    calls = []

    def delayed_configure(options):
        calls.append(options.api_concurrency)
        if options.api_concurrency == 1:
            entered.set()
            assert release.wait(timeout=5)
        return real_configure(options)

    monkeypatch.setattr(rt.runner.resources, "configure", delayed_configure)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            api_client.patch, "/api/settings", json={"tasks": {"api_concurrency": 1}}
        )
        try:
            assert entered.wait(timeout=3)
            second = pool.submit(
                api_client.patch, "/api/settings", json={"tasks": {"api_concurrency": 3}}
            )
            assert waiting.wait(timeout=3)
            assert api_client.get("/api/health").status_code == 200
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
        assert second.result(timeout=5).status_code == 200
    assert calls == [1, 3]
    assert api_client.get("/api/settings").json()["tasks"]["api_concurrency"] == 3
    assert rt.runner.resources.snapshot()["api_concurrency"] == 3


def test_simultaneous_submission_keys_are_idempotent(api_client, course, source_document):
    barrier = threading.Barrier(2)
    payload = {"mode": "extract", "idempotency_key": "same-launch-1234"}

    def submit():
        barrier.wait(timeout=5)
        return api_client.post(f"/api/courses/{course['id']}/runs", json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(), range(2)))
    assert [item.status_code for item in responses] == [202, 202]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with api_client.app.state.runtime.sessions() as session:
        assert len(list(session.scalars(select(Run)))) == 1
    changed = api_client.post(
        f"/api/courses/{course['id']}/runs", json={**payload, "instruction": "Different request"}
    )
    assert changed.status_code == 400


def test_simultaneous_different_submissions_cannot_duplicate_course_jobs(
    api_client, course, source_document
):
    barrier = threading.Barrier(2)

    def submit(number):
        barrier.wait(timeout=5)
        return api_client.post(
            f"/api/courses/{course['id']}/runs",
            json={"mode": "extract", "idempotency_key": f"intent-{number}-123"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert sorted(item.status_code for item in responses) == [202, 400]


def test_task_pages_are_bounded_and_filters_events_priority_persist(api_client, course):
    rt = api_client.app.state.runtime
    with rt.sessions.begin() as session:
        for index in range(250):
            session.add(
                Run(
                    course_id=course["id"],
                    mode="extract",
                    status="queued" if index < 3 else "completed",
                    created_at=f"2026-10-{index % 28 + 1:02d}T12:00:00+00:00",
                    config={"large_snapshot": "x" * 20000},
                    metrics={"unbounded_details": "x" * 20000},
                )
            )
    page = api_client.get("/api/tasks?limit=24&sort=oldest")
    assert page.status_code == 200, page.text
    data = page.json()
    assert data["total"] == 250 and len(data["items"]) == 24
    assert len(page.content) < 50000
    assert all(
        "config" not in item and "unbounded_details" not in item["metrics"]
        for item in data["items"]
    )
    other = api_client.get("/api/tasks?limit=24&offset=24&sort=oldest").json()
    assert not {item["id"] for item in data["items"]} & {item["id"] for item in other["items"]}
    queued = api_client.get("/api/tasks?status=queued&mode=extract").json()
    assert queued["total"] == 3
    last = max(queued["items"], key=lambda item: item["queue_position"])
    prioritized = api_client.post(f"/api/tasks/{last['id']}/priority", json={"priority": 10})
    assert prioritized.status_code == 200, prioritized.text
    assert prioritized.json()["queue_position"] == 1
    detail = api_client.get(f"/api/tasks/{last['id']}").json()
    assert detail["config"]["large_snapshot"] and detail["allowed_actions"] == ["pause", "cancel"]
    assert detail["events"]["items"][0]["kind"] == "priority"
    with rt.sessions.begin() as session:
        assert session.get(Run, last["id"]).priority == 10
        for index in range(40):
            session.add(JobEvent(run_id=last["id"], kind="test", message=f"Event {index}"))
    events = api_client.get(f"/api/tasks/{last['id']}/events?limit=10&offset=10").json()
    assert events["total"] == 41 and len(events["items"]) == 10
    summary = api_client.get("/api/tasks/summary").json()
    assert summary["counts"]["queued"] == 3 and summary["counts"]["completed"] == 247
    assert summary["limits"]["max_concurrent_jobs"] == 2
    assert api_client.get("/api/tasks?limit=101").status_code == 422
    assert api_client.get("/api/tasks?status=imaginary").status_code == 400
    assert api_client.get("/api/tasks?q=%25").json()["total"] == 0
    assert api_client.get("/api/tasks?date_from=2027-01-01T00:00:00Z").json()["total"] == 0
    assert (
        api_client.get(
            "/api/tasks?date_from=2027-01-01T00:00:00Z&date_to=2026-01-01T00:00:00Z"
        ).status_code
        == 400
    )


def test_course_preferences_change_only_future_job_snapshots(api_client, course, source_document):
    first = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"}).json()
    changed = api_client.patch(
        f"/api/courses/{course['id']}",
        json={
            "name": "Next name",
            "language": "Dutch",
            "criteria": {"answer_detail": "detailed"},
        },
    )
    assert changed.status_code == 200, changed.text
    before = api_client.get(f"/api/runs/{first['id']}").json()
    assert before["config"]["course_snapshot"]["name"] == course["name"]
    assert before["config"]["language"] == "English"
    assert before["config"]["criteria"]["answer_detail"] == "concise"
    assert api_client.post(f"/api/runs/{first['id']}/cancel").status_code == 200
    second = api_client.post(f"/api/courses/{course['id']}/runs", json={"mode": "extract"}).json()
    assert second["config"]["course_snapshot"]["name"] == "Next name"
    assert second["config"]["language"] == "Dutch"
    assert second["config"]["criteria"]["answer_detail"] == "detailed"
