"""SQLAlchemy models: the golden calendars (mkt-data's docs/phase-2.md, Part A).

Built from mkt-data's near-raw calendar rows (each source as it states
itself) by applying each calendar's sources in precedence order
(app/calendars/golden.py), and always rebuildable from them.

- `calendar`: FED, SIFMA-US, NYSE (integer ID plus short readable name).
- `calendar_year`: the years the calendar covers, credited to the
  highest-precedence source that covers each.
- `calendar_day`: closed and early-close weekdays, with history: a date that
  changes or disappears gets `valid_to` and a new row, never an overwrite.
  The current view is `valid_to IS NULL`. `source` is the mkt-data source
  that holds the date (precedence works from it); `capture_id` is mkt-data's
  raw capture it came from, for lineage.

Every change here needs a matching Alembic migration (`tests/test_migrations.py`
checks).
"""

from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Calendar(Base):
    __tablename__ = "calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20), unique=True)
    description: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(40))


class CalendarYear(Base):
    __tablename__ = "calendar_year"

    calendar_id: Mapped[int] = mapped_column(Integer, ForeignKey("calendar.id"), primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    capture_id: Mapped[int] = mapped_column(Integer)  # mkt-data's capture, not a local key
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CalendarDay(Base):
    __tablename__ = "calendar_day"
    __table_args__ = (
        CheckConstraint("status IN ('closed', 'early_close')", name="ck_calendar_day_status"),
        CheckConstraint("(status = 'early_close') = (close_time IS NOT NULL)", name="ck_calendar_day_close_time"),
        Index(
            "uq_calendar_day_current",
            "calendar_id",
            "day",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calendar_id: Mapped[int] = mapped_column(Integer, ForeignKey("calendar.id"))
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12))
    close_time: Mapped[time | None] = mapped_column(Time)
    holiday: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(40))
    capture_id: Mapped[int] = mapped_column(Integer)  # mkt-data's capture, not a local key
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
