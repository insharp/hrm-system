"""
core/app_time.py — UTC storage vs. the organisation's local wall clock.

Instants (event times, clock-ins) are STORED as naive UTC. Anything a person
reads — "tomorrow at 3:00 PM", which calendar day something falls on — is in
the organisation's local zone: Sri Lanka, fixed UTC+5:30 with no DST. Override
with APP_TZ_OFFSET_MINUTES (the same variable time tracking uses).
"""
import os
from datetime import date, datetime, time, timedelta, timezone

APP_TZ_OFFSET = timedelta(minutes=int(os.getenv("APP_TZ_OFFSET_MINUTES", "330")))


def utc_now() -> datetime:
    """Current instant as naive UTC — how timestamps are stored."""
    return datetime.utcnow()


def to_utc_naive(value: datetime) -> datetime:
    """Normalise an incoming datetime to naive UTC.

    Offset-aware values are converted. Naive values are ambiguous; they are
    treated as LOCAL wall-clock time (what a person typed into a form).
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value - APP_TZ_OFFSET


def to_local(value: datetime) -> datetime:
    """Stored naive-UTC instant → local wall-clock time, for display."""
    return value + APP_TZ_OFFSET


def local_today() -> date:
    return (datetime.utcnow() + APP_TZ_OFFSET).date()


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """UTC instants of the start and end of local calendar day `day`."""
    start = datetime.combine(day, time.min) - APP_TZ_OFFSET
    end = datetime.combine(day, time.max) - APP_TZ_OFFSET
    return start, end
