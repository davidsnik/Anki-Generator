"""Concurrent task queue metadata, ownership and persisted event history."""

import sqlalchemy as sa
from alembic import op

revision = "0006_concurrent_tasks"
down_revision = "0005_source_override_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive ALTERs preserve references from verification rows. Rebuilding runs
    # under SQLite foreign_keys=ON could apply ON DELETE actions to those rows.
    for column in [
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submission_key", sa.String(), nullable=True),
        sa.Column("active_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("resumed_at", sa.String(), nullable=True),
        sa.Column("recovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_at", sa.String(), nullable=True),
    ]:
        op.add_column("runs", column)
    op.execute("UPDATE runs SET queued_at=created_at")
    op.create_index("ix_verifications_run_card", "verifications", ["run_id", "card_id"])
    op.create_index(
        "uq_runs_course_submission", "runs", ["course_id", "submission_key"], unique=True
    )
    op.create_index(
        "ix_runs_schedule", "runs", ["status", sa.text("priority DESC"), "created_at", "id"]
    )
    op.create_index(
        "uq_runs_executing_course",
        "runs",
        ["course_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('running','pausing','cancelling')"),
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_job_events_run_created", "job_events", ["run_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_table("job_events")
    op.drop_index("ix_verifications_run_card", table_name="verifications")
    op.drop_index("uq_runs_executing_course", table_name="runs")
    op.drop_index("ix_runs_schedule", table_name="runs")
    op.drop_index("uq_runs_course_submission", table_name="runs")
    for name in [
        "priority",
        "submission_key",
        "active_seconds",
        "resumed_at",
        "recovery_count",
        "queued_at",
    ]:
        op.drop_column("runs", name)
