"""Versioned benchmark references, experiments and append-only judgments."""

import sqlalchemy as sa
from alembic import op

revision = "0002_evaluation"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), sa.ForeignKey("courses.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.String(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("source_manifest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "evaluation_experiments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(),
            sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reference_snapshot", sa.JSON(), nullable=False),
        sa.Column("variants", sa.JSON(), nullable=False),
        sa.Column("cases", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("blind", sa.Boolean(), nullable=False),
        sa.Column("random_seed", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_evaluation_experiments_dataset_id", "evaluation_experiments", ["dataset_id"]
    )
    op.create_table(
        "evaluation_judgments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(),
            sa.ForeignKey("evaluation_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("reference_concept_ids", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_evaluation_judgments_experiment_id", "evaluation_judgments", ["experiment_id"]
    )
    op.create_index("ix_evaluation_judgments_case_id", "evaluation_judgments", ["case_id"])
    op.create_table(
        "evaluation_annotations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(),
            sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("expected", sa.String(), nullable=False),
        sa.Column("actual", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_evaluation_annotations_dataset_id", "evaluation_annotations", ["dataset_id"]
    )
    op.create_index("ix_cards_course_updated_id", "cards", ["course_id", "updated_at", "id"])
    op.create_index(
        "ix_cards_course_review_quality",
        "cards",
        ["course_id", "review_status", "verification_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_cards_course_review_quality", table_name="cards")
    op.drop_index("ix_cards_course_updated_id", table_name="cards")
    for table in (
        "evaluation_annotations",
        "evaluation_judgments",
        "evaluation_experiments",
        "evaluation_datasets",
    ):
        op.drop_table(table)
