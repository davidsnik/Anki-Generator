"""Persist human transcription history and selected original visual evidence.

Revision ID: 0003_source_fidelity
Revises: 0002_evaluation
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_source_fidelity"
down_revision = "0002_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_corrections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.String(), nullable=True),
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("source_sha256", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("supersedes_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("document_id", "scope_key", "revision_number"),
    )
    op.create_index("ix_source_corrections_document_id", "source_corrections", ["document_id"])
    op.create_table(
        "selected_source_regions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_sha256", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("image_path", sa.String(), nullable=False),
        sa.Column("pixel_width", sa.Integer(), nullable=False),
        sa.Column("pixel_height", sa.Integer(), nullable=False),
        sa.Column("dpi", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("coordinate_system", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_selected_source_regions_document_id", "selected_source_regions", ["document_id"]
    )


def downgrade() -> None:
    op.drop_table("selected_source_regions")
    op.drop_table("source_corrections")
