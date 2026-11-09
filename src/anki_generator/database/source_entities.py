"""Persistent human source revisions and original-coordinate selected evidence."""

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from anki_generator.database.entities import Base, new_id, now


class SourceCorrection(Base):
    __tablename__ = "source_corrections"
    __table_args__ = (UniqueConstraint("document_id", "scope_key", "revision_number"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int]
    region_id: Mapped[str | None] = mapped_column(default=None)
    scope_key: Mapped[str]
    source_sha256: Mapped[str]
    revision_number: Mapped[int]
    text: Mapped[str]
    verified: Mapped[bool] = mapped_column(default=False)
    origin: Mapped[str] = mapped_column(default="human")
    reason: Mapped[str] = mapped_column(default="")
    supersedes_id: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[str] = mapped_column(default=now)


class SelectedSourceRegion(Base):
    __tablename__ = "selected_source_regions"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    source_sha256: Mapped[str]
    page_number: Mapped[int]
    bbox: Mapped[list[float]] = mapped_column(JSON)
    image_path: Mapped[str]
    pixel_width: Mapped[int]
    pixel_height: Mapped[int]
    dpi: Mapped[int]
    label: Mapped[str] = mapped_column(default="")
    coordinate_system: Mapped[str] = mapped_column(default="pdf-points")
    created_at: Mapped[str] = mapped_column(default=now)
