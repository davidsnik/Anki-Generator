"""Preserve explicit automatic replacement as a separate source history origin."""

import sqlalchemy as sa
from alembic import op

revision = "0005_source_override_origin"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_corrections",
        sa.Column("origin", sa.String(), nullable=False, server_default="human"),
    )


def downgrade() -> None:
    op.drop_column("source_corrections", "origin")
