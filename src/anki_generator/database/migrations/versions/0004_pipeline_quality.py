"""Semantic retrieval, independent source coverage and identity audit history.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003_source_fidelity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_vectors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_id", sa.String(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "course_id", "object_type", "object_id", "text_hash", "model", "dimensions"
        ),
    )
    op.create_index("ix_semantic_vectors_course_id", "semantic_vectors", ["course_id"])
    op.create_table(
        "identity_aliases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("semantic_key", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("course_id", "entity_type", "semantic_key"),
    )
    op.create_index("ix_identity_aliases_course_id", "identity_aliases", ["course_id"])
    op.create_index("ix_identity_aliases_entity_id", "identity_aliases", ["entity_id"])
    op.create_table(
        "identity_proposals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("candidate_key", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("candidate_payload", sa.JSON(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("selected_id", sa.String()),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("resolved_at", sa.String()),
        sa.UniqueConstraint("run_id", "entity_type", "candidate_key"),
    )
    for name in ("course_id", "candidate_id", "state"):
        op.create_index(f"ix_identity_proposals_{name}", "identity_proposals", [name])
    op.create_table(
        "source_coverage_targets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("parent_key", sa.String()),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("statement", sa.String(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("mapped_concept_ids", sa.JSON(), nullable=False),
        sa.Column("covered_card_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("run_id", "target_key"),
    )
    for name in ("course_id", "run_id", "status"):
        op.create_index(f"ix_source_coverage_targets_{name}", "source_coverage_targets", [name])
    op.create_table(
        "export_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "export_id",
            sa.String(),
            sa.ForeignKey("exports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("note_guid", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("export_id", "card_id"),
    )
    op.create_index("ix_export_snapshots_export_id", "export_snapshots", ["export_id"])


def downgrade() -> None:
    for name in (
        "export_snapshots",
        "source_coverage_targets",
        "identity_proposals",
        "identity_aliases",
        "semantic_vectors",
    ):
        op.drop_table(name)
