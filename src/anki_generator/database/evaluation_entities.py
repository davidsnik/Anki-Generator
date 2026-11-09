"""Versioned benchmark references and immutable experiment/review evidence."""

from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .entities import Base, Timestamps, new_id, now


class EvaluationDataset(Timestamps, Base):
    __tablename__ = "evaluation_datasets"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(default=1)
    provenance: Mapped[str] = mapped_column(default="unreviewed")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_manifest: Mapped[list[Any]] = mapped_column(JSON, default=list)


class EvaluationExperiment(Timestamps, Base):
    __tablename__ = "evaluation_experiments"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    reference_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    variants: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cases: Mapped[list[Any]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    blind: Mapped[bool] = mapped_column(default=True)
    random_seed: Mapped[str] = mapped_column(default=new_id)


class EvaluationJudgment(Base):
    __tablename__ = "evaluation_judgments"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_experiments.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[str] = mapped_column(index=True)
    label: Mapped[str]
    origin: Mapped[str] = mapped_column(default="human")
    reviewer: Mapped[str]
    independent: Mapped[bool] = mapped_column(default=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reference_concept_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(default=now)


class EvaluationAnnotation(Base):
    __tablename__ = "evaluation_annotations"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str]
    label: Mapped[str]
    source: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected: Mapped[str] = mapped_column(default="")
    actual: Mapped[str] = mapped_column(default="")
    rationale: Mapped[str] = mapped_column(default="")
    origin: Mapped[str] = mapped_column(default="human")
    created_at: Mapped[str] = mapped_column(default=now)
