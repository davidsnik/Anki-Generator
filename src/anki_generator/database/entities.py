"""Persistent entities; JSON columns retain versioned evidence and stage artifacts."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Timestamps:
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now, onupdate=now)


class Course(Timestamps, Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    deck_name: Mapped[str]
    language: Mapped[str] = mapped_column(default="English")
    archived: Mapped[bool] = mapped_column(default=False)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Document(Timestamps, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("course_id", "relative_path"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str]
    relative_path: Mapped[str]
    category: Mapped[str] = mapped_column(default="lecture")
    authority: Mapped[str] = mapped_column(default="unknown")
    linked_document_id: Mapped[str | None] = mapped_column(default=None)
    sha256: Mapped[str]
    size_bytes: Mapped[int]
    mime_type: Mapped[str]
    storage_path: Mapped[str]
    status: Mapped[str] = mapped_column(default="imported")
    extraction_key: Mapped[str] = mapped_column(default="")
    extraction: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int]
    width: Mapped[float]
    height: Mapped[float]
    text: Mapped[str] = mapped_column(default="")
    blocks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    regions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    needs_vision: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default="complete")


class Concept(Timestamps, Base):
    __tablename__ = "concepts"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    kind: Mapped[str] = mapped_column(default="concept")
    parent_id: Mapped[str | None] = mapped_column(default=None)
    importance: Mapped[float] = mapped_column(default=0.5)
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    relationships: Mapped[list[Any]] = mapped_column(JSON, default=list)
    exercise_analysis: Mapped[list[Any]] = mapped_column(JSON, default=list)
    excluded: Mapped[bool] = mapped_column(default=False)
    coverage_status: Mapped[str] = mapped_column(default="uncovered")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Card(Timestamps, Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"))
    card_type: Mapped[str] = mapped_column(default="basic")
    kind: Mapped[str] = mapped_column(default="conceptual")
    question: Mapped[str]
    answer: Mapped[str] = mapped_column(default="")
    explanation: Mapped[str] = mapped_column(default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    image_refs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    verification_status: Mapped[str] = mapped_column(default="unverified")
    review_status: Mapped[str] = mapped_column(default="pending")
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    manually_edited: Mapped[bool] = mapped_column(default=False)
    revision_number: Mapped[int] = mapped_column(default=1)
    note_guid: Mapped[str] = mapped_column(default=new_id, unique=True)
    archived: Mapped[bool] = mapped_column(default=False)


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("card_id", "revision_number"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int]
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    origin: Mapped[str] = mapped_column(default="generated")
    instruction: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(default=now)


class Verification(Base):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    revision_number: Mapped[int]
    stage: Mapped[str]
    verdict: Mapped[str]
    score: Mapped[float | None] = mapped_column(default=None)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(default="")
    prompt_version: Mapped[str] = mapped_column(default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(default=now)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    revision_number: Mapped[int]
    decision: Mapped[str]
    reason: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(default=now)


class Run(Timestamps, Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(default="generate")
    status: Mapped[str] = mapped_column(default="queued")
    current_stage: Mapped[str] = mapped_column(default="queued")
    error: Mapped[str | None] = mapped_column(default=None)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inputs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    checkpoints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pause_requested: Mapped[bool] = mapped_column(default=False)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[str | None] = mapped_column(default=None)
    finished_at: Mapped[str | None] = mapped_column(default=None)
    priority: Mapped[int] = mapped_column(default=0)
    submission_key: Mapped[str | None] = mapped_column(default=None)
    active_seconds: Mapped[float] = mapped_column(default=0)
    resumed_at: Mapped[str | None] = mapped_column(default=None)
    recovery_count: Mapped[int] = mapped_column(default=0)
    queued_at: Mapped[str | None] = mapped_column(default=now)


class Stage(Base):
    __tablename__ = "stages"
    __table_args__ = (UniqueConstraint("run_id", "name"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    completed: Mapped[int] = mapped_column(default=0)
    total: Mapped[int] = mapped_column(default=0)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(default=None)
    started_at: Mapped[str | None] = mapped_column(default=None)
    finished_at: Mapped[str | None] = mapped_column(default=None)


class ExportRecord(Base):
    __tablename__ = "exports"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    format: Mapped[str]
    deck_name: Mapped[str]
    card_ids: Mapped[list[str]] = mapped_column(JSON)
    card_count: Mapped[int]
    storage_path: Mapped[str]
    sha256: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)


class ApplicationSetting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)


Index("ix_cards_course_updated_id", Card.course_id, Card.updated_at, Card.id)
Index(
    "ix_cards_course_review_quality", Card.course_id, Card.review_status, Card.verification_status
)
Index("ix_runs_schedule", Run.status, Run.priority.desc(), Run.created_at, Run.id)
Index("ix_verifications_run_card", Verification.run_id, Verification.card_id)
Index("uq_runs_course_submission", Run.course_id, Run.submission_key, unique=True)
Index(
    "uq_runs_executing_course",
    Run.course_id,
    unique=True,
    sqlite_where=Run.status.in_(["running", "pausing", "cancelling"]),
)
