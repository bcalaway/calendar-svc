"""load_run: each load from mkt-data's near-raw rows

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "load_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=8), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint("outcome IN ('ok', 'error')", name="ck_load_run_outcome"),
    )


def downgrade() -> None:
    op.drop_table("load_run")
