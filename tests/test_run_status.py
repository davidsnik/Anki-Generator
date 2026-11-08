"""Pending plans are presentation data; persisted checkpoints remain authoritative."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from anki_generator.database.entities import Base, Course, Run, Stage
from anki_generator.services.records import record_dict, run_view


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'status.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        course = Course(name="Status fixture", deck_name="Status")
        session.add(course)
        session.flush()
        yield session, course.id
    engine.dispose()


def create_run(session, course_id, *, mode="generate", status="queued", **values):
    run = Run(course_id=course_id, mode=mode, status=status, **values)
    session.add(run)
    session.flush()
    return run


@pytest.mark.parametrize("mode", ["generate", "topic", "revise", "extract"])
def test_queued_run_exposes_mode_specific_pending_plan_without_writing_rows(session, mode):
    db, course_id = session
    run = create_run(db, course_id, mode=mode)
    stages = run_view(db, run)["stages"]
    names = [stage["name"] for stage in stages]
    assert names[0] == "extraction"
    assert all(stage["status"] == "pending" for stage in stages)
    assert all("total" not in stage and "completed" not in stage for stage in stages)
    assert db.scalar(select(func.count()).select_from(Stage)) == 0
    if mode == "extract":
        assert names == ["extraction"]
    else:
        assert names[-2:] == ["deduplication", "coverage"]
        assert "mathematical" in names and "symbolic" not in names
        assert {"interpretation", "factual", "pedagogical"} <= set(names)
        if mode == "revise":
            assert names[2] == "revision"
            assert not {"knowledge", "consolidation", "generation"} & set(names)
        else:
            assert names[2:5] == ["knowledge", "consolidation", "generation"]
            assert (
                "Only for actionable defects"
                in next(s for s in stages if s["name"] == "revision")["message"]
            )


def test_running_view_preserves_completed_current_checkpoint_counts_errors_and_pending_work(
    session,
):
    db, course_id = session
    run = create_run(db, course_id, status="running", current_stage="knowledge")
    extraction = Stage(
        run_id=run.id,
        name="extraction",
        status="completed",
        completed=3,
        total=3,
        started_at="2026-11-08T10:00:00",
        finished_at="2026-11-08T10:01:00",
    )
    knowledge = Stage(
        run_id=run.id,
        name="knowledge",
        status="running",
        completed=7,
        total=11,
        artifacts={"section-7": "cache/exact.json"},
        error="Recorded diagnostic",
    )
    db.add_all([extraction, knowledge])
    db.flush()
    stages = {stage["name"]: stage for stage in run_view(db, run)["stages"]}
    assert stages["extraction"] == record_dict(extraction)
    assert stages["knowledge"] == record_dict(knowledge)
    assert stages["generation"]["status"] == stages["coverage"]["status"] == "pending"
    assert stages["interpretation"]["status"] == "skipped"
    assert "total" not in stages["generation"]
    assert db.scalar(select(func.count()).select_from(Stage)) == 2


@pytest.mark.parametrize(
    "status,expected",
    [
        ("completed", "skipped"),
        ("cancelled", "not_run"),
        ("failed", "pending"),
        ("paused", "pending"),
    ],
)
def test_unencountered_conditional_stages_match_terminal_or_recoverable_state(
    session, status, expected
):
    db, course_id = session
    run = create_run(db, course_id, status=status)
    stage = Stage(run_id=run.id, name="extraction", status="completed", completed=2, total=2)
    db.add(stage)
    db.flush()
    view = run_view(db, run)
    by_name = {item["name"]: item for item in view["stages"]}
    assert by_name["extraction"] == record_dict(stage)
    assert by_name["interpretation"]["status"] == expected
    assert "Only when" in by_name["interpretation"]["message"]
    assert by_name["mathematical"]["status"] == by_name["revision"]["status"] == expected
    assert "total" not in by_name["mathematical"]
    if status == "completed":
        assert not any(item["status"] == "pending" for item in view["stages"])
    if status == "failed":
        assert "retry" in by_name["coverage"]["message"]


def test_recorded_conditional_and_unknown_stages_are_never_dropped_or_relabelled(session):
    db, course_id = session
    run = create_run(db, course_id, status="completed")
    mathematical = Stage(
        run_id=run.id, name="mathematical", status="completed", completed=4, total=4
    )
    extension = Stage(
        run_id=run.id,
        name="future_audit",
        status="failed",
        completed=1,
        total=3,
        error="An explicit failure stays visible.",
    )
    db.add_all([mathematical, extension])
    db.flush()
    by_name = {item["name"]: item for item in run_view(db, run)["stages"]}
    assert by_name["mathematical"] == record_dict(mathematical)
    assert by_name["future_audit"] == record_dict(extension)
