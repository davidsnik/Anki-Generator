"""Persistent structured task events, without source payloads or credentials."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from anki_generator.database.entities import Base, new_id, now


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    created_at: Mapped[str] = mapped_column(default=now)
    kind: Mapped[str]
    level: Mapped[str] = mapped_column(default="info")
    message: Mapped[str]
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


Index("ix_job_events_run_created", JobEvent.run_id, JobEvent.created_at, JobEvent.id)
