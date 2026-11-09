"""Input edits and job submissions share one short SQLite writer boundary."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select

from anki_generator.api.courses import ensure_idle
from anki_generator.database.entities import Course, Document, Run
from anki_generator.database.source_entities import SourceCorrection
from anki_generator.services import run_submission
from anki_generator.services.source_corrections import snapshot_source_state


def _correction(document):
    return SourceCorrection(
        document_id=document.id,
        page_number=1,
        scope_key="page:1",
        source_sha256=document.sha256,
        revision_number=1,
        text="The corrected function is continuous on the real line.",
        verified=True,
        reason="Checked against the original source",
    )


def test_guarded_edit_commits_before_waiting_submission_snapshots_sources(
    api_client, course, source_document
):
    rt = api_client.app.state.runtime
    engine = rt.sessions.kw["bind"]
    attempting, acquired = threading.Event(), threading.Event()

    def before_execute(connection, cursor, statement, parameters, context, executemany):
        if (
            threading.current_thread().name.startswith("submitting")
            and statement == "BEGIN IMMEDIATE"
        ):
            attempting.set()

    def after_execute(connection, cursor, statement, parameters, context, executemany):
        if (
            threading.current_thread().name.startswith("submitting")
            and statement == "BEGIN IMMEDIATE"
        ):
            acquired.set()

    event.listen(engine, "before_cursor_execute", before_execute)
    event.listen(engine, "after_cursor_execute", after_execute)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="submitting") as pool:
            with rt.sessions.begin() as session:
                document = session.get(Document, source_document["id"])
                timestamp = session.get(Course, course["id"]).updated_at
                ensure_idle(session, course["id"])
                submission = pool.submit(
                    run_submission.submit_run, rt, course["id"], {"mode": "extract"}
                )
                assert attempting.wait(timeout=5)
                # The submitter reached its physical BEGIN, but cannot obtain a
                # writer until this guarded edit has committed its correction.
                assert not acquired.wait(timeout=0.2)
                session.add(_correction(document))
            result = submission.result(timeout=5)
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)
        event.remove(engine, "after_cursor_execute", after_execute)

    assert acquired.is_set() and result["status"] == "queued"
    with rt.sessions() as session:
        document = session.get(Document, source_document["id"])
        snapshot = snapshot_source_state(session, document)
        submitted = session.get(Run, result["id"]).inputs[0]
        assert snapshot["correction_count"] == 1
        assert all(submitted[key] == value for key, value in snapshot.items())
        assert session.get(Course, course["id"]).updated_at == timestamp


def test_waiting_edit_rechecks_active_job_after_submission_commits(
    api_client, course, source_document, monkeypatch
):
    rt = api_client.app.state.runtime
    engine = rt.sessions.kw["bind"]
    checked, release, attempting, acquired = (threading.Event() for _ in range(4))
    real_ensure_idle = run_submission.ensure_idle

    def hold_submission_writer(session, course_id):
        real_ensure_idle(session, course_id)
        checked.set()
        assert release.wait(timeout=5)

    def before_execute(connection, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("editing") and statement.startswith(
            "UPDATE courses SET id = id"
        ):
            attempting.set()

    def after_execute(connection, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("editing") and statement.startswith(
            "UPDATE courses SET id = id"
        ):
            acquired.set()

    def edit():
        with rt.sessions.begin() as session:
            document = session.get(Document, source_document["id"])
            ensure_idle(session, course["id"])
            session.add(_correction(document))

    monkeypatch.setattr(run_submission, "ensure_idle", hold_submission_writer)
    event.listen(engine, "before_cursor_execute", before_execute)
    event.listen(engine, "after_cursor_execute", after_execute)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="submitting") as submit_pool,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="editing") as edit_pool,
        ):
            submission = submit_pool.submit(
                run_submission.submit_run, rt, course["id"], {"mode": "extract"}
            )
            try:
                assert checked.wait(timeout=5)
                mutation = edit_pool.submit(edit)
                assert attempting.wait(timeout=5)
                assert not acquired.wait(timeout=0.2)
            finally:
                release.set()
            result = submission.result(timeout=5)
            with pytest.raises(ValueError, match="Pause or cancel"):
                mutation.result(timeout=5)
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)
        event.remove(engine, "after_cursor_execute", after_execute)

    assert acquired.is_set() and result["status"] == "queued"
    with rt.sessions() as session:
        assert list(session.scalars(select(SourceCorrection))) == []
        assert session.get(Run, result["id"]).inputs[0]["correction_count"] == 0
