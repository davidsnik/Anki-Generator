"""Versioned semantic retrieval, source coverage, and identity reconciliation state."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anki_generator.database.entities import Base, new_id, now


class SemanticVector(Base):
    __tablename__ = "semantic_vectors"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "object_type", "object_id", "text_hash", "model", "dimensions"
        ),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    object_type: Mapped[str]
    object_id: Mapped[str]
    text_hash: Mapped[str]
    model: Mapped[str]
    dimensions: Mapped[int]
    vector: Mapped[list[float]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class IdentityAlias(Base):
    __tablename__ = "identity_aliases"
    __table_args__ = (UniqueConstraint("course_id", "entity_type", "semantic_key"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str]
    semantic_key: Mapped[str]
    entity_id: Mapped[str] = mapped_column(index=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(default="generated")
    created_at: Mapped[str] = mapped_column(default=now)


class IdentityProposal(Base):
    __tablename__ = "identity_proposals"
    __table_args__ = (UniqueConstraint("run_id", "entity_type", "candidate_key"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    entity_type: Mapped[str]
    candidate_key: Mapped[str]
    candidate_id: Mapped[str] = mapped_column(index=True)
    candidate_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    candidates: Mapped[list[Any]] = mapped_column(JSON, default=list)
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(default="pending", index=True)
    selected_id: Mapped[str | None] = mapped_column(default=None)
    reason: Mapped[str] = mapped_column(default="")
    rationale: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(default=now)
    resolved_at: Mapped[str | None] = mapped_column(default=None)


class SourceCoverageTarget(Base):
    __tablename__ = "source_coverage_targets"
    __table_args__ = (UniqueConstraint("run_id", "target_key"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    target_key: Mapped[str]
    parent_key: Mapped[str | None] = mapped_column(default=None)
    kind: Mapped[str]
    title: Mapped[str]
    statement: Mapped[str]
    importance: Mapped[float] = mapped_column(default=0.5)
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    mapped_concept_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    covered_card_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="uncovered", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(default=now)


class ExportSnapshot(Base):
    __tablename__ = "export_snapshots"
    __table_args__ = (UniqueConstraint("export_id", "card_id"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    export_id: Mapped[str] = mapped_column(ForeignKey("exports.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[str]
    note_guid: Mapped[str]
    revision_number: Mapped[int]
    content_hash: Mapped[str]
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)
