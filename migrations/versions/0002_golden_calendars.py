"""golden calendars: calendar, calendar_year, calendar_day

Replaces the template's example `items` table (mkt-data's docs/phase-2.md,
Part A step 3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("items")
    op.create_table(
        "calendar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=20), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("timezone", sa.String(length=40), nullable=False),
    )
    op.create_table(
        "calendar_year",
        sa.Column("calendar_id", sa.Integer(), sa.ForeignKey("calendar.id"), primary_key=True),
        sa.Column("year", sa.SmallInteger(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("capture_id", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "calendar_day",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("calendar_id", sa.Integer(), sa.ForeignKey("calendar.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column("holiday", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("capture_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('closed', 'early_close')", name="ck_calendar_day_status"),
        sa.CheckConstraint("(status = 'early_close') = (close_time IS NOT NULL)", name="ck_calendar_day_close_time"),
    )
    op.create_index(
        "uq_calendar_day_current",
        "calendar_day",
        ["calendar_id", "day"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
        sqlite_where=sa.text("valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_calendar_day_current", table_name="calendar_day")
    op.drop_table("calendar_day")
    op.drop_table("calendar_year")
    op.drop_table("calendar")
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
