from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from typing import List, Literal, Optional
from datetime import datetime, timezone, timedelta, date as date_type
from decimal import Decimal
import os

from app.database.database import get_db
from app.core.deps import get_current_user, require_permission
from app.auth.models import User
from app.time_tracking.models import TimeEntry, TimeCheckPair, OvertimeThresholdHistory
from app.time_tracking.schemas import (
    TimeEntryResponse,
    ClockStatusResponse,
    WeeklyStatsResponse,
    DayEntryResponse,
    CheckPairResponse,
    OvertimeThresholdResponse,
    AllAttendanceResponse,
    OvertimeThresholdUpdate,
)

router = APIRouter()

DEFAULT_THRESHOLD = 8.0  # fallback if no threshold row exists
# How far back/forward the week/day/month pickers may page. ~10 years back is
# far more history than anyone browses; unbounded values used to overflow
# timedelta (500) or spin the month loop for a very long time.
MAX_PERIOD_OFFSET = 520


def _period_offset():
    # A fresh Query per parameter: FastAPI binds a Query object's name to the
    # first parameter that uses it, so sharing one silently renames the others.
    return Query(0, ge=-MAX_PERIOD_OFFSET, le=MAX_PERIOD_OFFSET)

# ── Time zone handling ──────────────────────────────────────────────────────────
# Two distinct concerns, kept separate:
#   • Timestamps are STORED in UTC. The frontend appends 'Z' to every timestamp
#     and converts UTC → the viewer's local zone for display, so storing anything
#     other than UTC double-shifts the clock. Use _utc_now() for stored instants.
#   • Work "days" roll over at LOCAL midnight, so day identity (which date a
#     session belongs to, when the day ends) is computed in local time. Sri Lanka
#     is a fixed UTC+5:30 (no DST); override with APP_TZ_OFFSET_MINUTES elsewhere.
_APP_TZ_OFFSET = timedelta(minutes=int(os.getenv("APP_TZ_OFFSET_MINUTES", "330")))


def _utc_now() -> datetime:
    """Current UTC instant (naive) — how every timestamp is STORED and read back."""
    return datetime.utcnow()


def _local_now() -> datetime:
    """Current LOCAL wall-clock time (naive) — for date arithmetic only, never stored."""
    return datetime.utcnow() + _APP_TZ_OFFSET


def _local_today() -> date_type:
    """Current LOCAL calendar date — work days roll over at LOCAL midnight."""
    return (datetime.utcnow() + _APP_TZ_OFFSET).date()


def _local_midnight_utc(day: date_type) -> datetime:
    """UTC instant of the START of local day `day` (its 00:00 local)."""
    return datetime.combine(day, datetime.min.time()) - _APP_TZ_OFFSET


def _local_day_end_utc(day: date_type) -> datetime:
    """UTC instant of the END of local day `day` (its 23:59:59.999999 local)."""
    return datetime.combine(day, datetime.max.time()) - _APP_TZ_OFFSET


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _get_threshold_for_date(db: Session, target_date: date_type) -> float:
    """Returns the overtime threshold (hours) effective on the given date."""
    row = (
        db.query(OvertimeThresholdHistory)
        .filter(OvertimeThresholdHistory.effective_date <= target_date)
        .order_by(OvertimeThresholdHistory.effective_date.desc())
        .first()
    )
    return float(row.threshold_hours) if row else DEFAULT_THRESHOLD


def _get_current_threshold(db: Session) -> float:
    """Returns the most recently set threshold (for display / future use)."""
    row = (
        db.query(OvertimeThresholdHistory)
        .order_by(OvertimeThresholdHistory.effective_date.desc())
        .first()
    )
    return float(row.threshold_hours) if row else DEFAULT_THRESHOLD


def _today_entry(db: Session, user_id: int) -> Optional[TimeEntry]:
    """Returns today's TimeEntry for this user (if any)."""
    today = _local_today()
    return (
        db.query(TimeEntry)
        .filter(
            TimeEntry.user_id == user_id,
            TimeEntry.date == today,
            TimeEntry.status.in_(["active", "paused"]),
        )
        .first()
    )


def _open_pair(db: Session, user_id: int) -> Optional[TimeCheckPair]:
    """Returns the currently open (no check_out) pair for this user."""
    return (
        db.query(TimeCheckPair)
        .filter(
            TimeCheckPair.user_id == user_id,
            TimeCheckPair.check_out.is_(None),
        )
        .first()
    )


def _accumulated_seconds(db: Session, user_id: int, target_date: date_type) -> int:
    """Sum of seconds from all COMPLETED pairs for the given day."""
    pairs = (
        db.query(TimeCheckPair)
        .filter(
            TimeCheckPair.user_id == user_id,
            TimeCheckPair.date == target_date,
            TimeCheckPair.check_out.isnot(None),
        )
        .all()
    )
    return sum(p.seconds or 0 for p in pairs)


def _close_pair(pair: TimeCheckPair, now: datetime) -> None:
    """Close an open pair by setting check_out and computing seconds."""
    pair.check_out = now
    pair.seconds = int((now - pair.check_in).total_seconds())


def _finalize_day(db: Session, entry: TimeEntry, now: datetime) -> None:
    """Finalize a day: compute total_hours, overtime, set status=completed."""
    today = entry.date or now.date()

    # Close any still-open pair
    open_pair = _open_pair(db, entry.user_id)
    if open_pair and open_pair.date == today:
        _close_pair(open_pair, now)
        db.flush()

    total_secs = _accumulated_seconds(db, entry.user_id, today)
    total_hours = round(total_secs / 3600, 4)

    threshold = _get_threshold_for_date(db, today)
    overtime = round(max(0.0, total_hours - threshold), 4)

    entry.end_time = now
    entry.total_seconds = total_secs
    entry.total_hours = total_hours
    entry.overtime = overtime
    entry.applied_threshold = Decimal(str(threshold))
    entry.status = "completed"


def _finalize_stale_day(db: Session, entry: TimeEntry) -> None:
    """Auto-finalize a PAST day's session that was never ended.

    Unlike ``_finalize_day`` (which closes at ``now``), the work here is capped
    at the entry's OWN day's midnight. An employee who forgot to click "End Work"
    gets that day's real sessions saved as a completed record — instead of the
    session being discarded (the old 1-second close) or appearing to run for many
    hours across the following days.
    """
    day = entry.date or (entry.start_time.date() if entry.start_time else None)
    if day is None:
        return

    # Local midnight of that day, expressed as the UTC instant we store.
    cutoff = _local_day_end_utc(day)

    # Close the still-open pair for that day at the day's end. Guard against a
    # check_in after the cutoff (would otherwise yield negative seconds).
    open_pair = (
        db.query(TimeCheckPair)
        .filter(
            TimeCheckPair.user_id == entry.user_id,
            TimeCheckPair.date == day,
            TimeCheckPair.check_out.is_(None),
        )
        .first()
    )
    if open_pair:
        end_at = cutoff if cutoff > open_pair.check_in else open_pair.check_in
        _close_pair(open_pair, end_at)
        db.flush()

    total_secs = _accumulated_seconds(db, entry.user_id, day)
    total_hours = round(total_secs / 3600, 4)
    threshold = _get_threshold_for_date(db, day)

    entry.end_time = cutoff
    entry.total_seconds = total_secs
    entry.total_hours = total_hours
    entry.overtime = round(max(0.0, total_hours - threshold), 4)
    entry.applied_threshold = Decimal(str(threshold))
    entry.status = "completed"


def _format_hm(hours: Optional[float]) -> str:
    """Format decimal hours as 'Xh Ym' (e.g. 6.5 -> '6h 30m')."""
    total_min = int(round((hours or 0.0) * 60))
    return f"{total_min // 60}h {total_min % 60}m"


def _day_label(day) -> str:
    """Human date label like 'Sat, Aug 15' (no zero-padded day)."""
    return f"{day.strftime('%a, %b')} {day.day}"


def _notify_rollover(db: Session, user_id: int, ended: list, started_date) -> None:
    """Notify the user about the midnight rollover.

    When work continued across midnight (a new day was auto-started), a SINGLE
    notification is sent about the new day, with a short note that the previous
    day was ended at midnight — that one message covers both halves.

    When only an auto-end happened (no continuation — e.g. a multi-day gap or a
    day left paused), a single plain note is sent so the closed day isn't a
    silent surprise.

    Best-effort only: notification problems must never break the rollover.
    ``notify_user`` already never raises, and the import is guarded too.
    """
    try:
        from app.notifications.service import notify_user
    except Exception:
        return

    link = "/dashboard/time-tracking"

    if started_date is not None:
        # ended[-1] is the day that crossed midnight (yesterday).
        note = ""
        if ended:
            note = f" (your previous day, {_day_label(ended[-1][1])}, was ended and saved at midnight)"
        notify_user(
            db, user_id,
            f"A new work session for {_day_label(started_date)} started "
            f"automatically at 12:00 AM{note}. You can pause, resume, or end it "
            f"anytime.",
            category="attendance", type="info", link=link,
            entity_type="time_entry", entity_id=f"autostart-{started_date.isoformat()}",
        )
        return

    # No continuation — just let them know the open day was closed.
    for entry_id, day, hours in ended:
        notify_user(
            db, user_id,
            f"Your work day for {_day_label(day)} was automatically ended and "
            f"saved at midnight ({_format_hm(hours)}) because it was left open.",
            category="attendance", type="info", link=link,
            entity_type="time_entry", entity_id=str(entry_id),
        )


def _auto_finalize_stale_days(db: Session, user_id: int) -> bool:
    """Close unfinished prior days at local midnight, and continue an active
    session into today if it crossed midnight.

    Called whenever the user reads or starts a session (so the rollover happens
    lazily on the first request after midnight, but is always recorded AT
    midnight):

    - Every unfinished prior day (active/paused) is closed at ITS OWN local
      midnight and marked completed, preserving that day's sessions.
    - If the user was still actively working when the clock passed into today
      (the most recent unfinished day is *yesterday* and was 'active'), a new
      session is auto-started for today from 00:00 so tracking continues without
      a gap — the new day's timer then reads "time since midnight".
    - The user is notified of the auto-end (and auto-start, if any).

    The continuation is deliberately limited to a single-night crossover
    (yesterday → today). A gap of two or more days is treated as "forgot to end",
    so the old day is just closed and the user starts today's session manually —
    the system never fabricates full 24h days for periods of absence.

    Returns True if anything changed, so read handlers know to commit.
    """
    today = _local_today()
    # SELECT ... FOR UPDATE serialises the requests the dashboard fires together
    # on mount (/current, /history, /weekly-stats). The first to run locks and
    # finalises these rows; the others then re-evaluate the filter, see them as
    # 'completed', and get an empty result — so a day is never rolled over, or
    # notified, twice.
    stale = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.user_id == user_id,
            TimeEntry.status.in_(["active", "paused"]),
            TimeEntry.date < today,
        )
        .order_by(TimeEntry.date.asc())
        .with_for_update()
        .all()
    )
    if not stale:
        return False

    latest = stale[-1]
    # Continue only a genuine single-night crossover: the latest unfinished day
    # is yesterday AND the user was actively working (open pair) at midnight.
    continue_active = (
        latest.status == "active"
        and latest.date == today - timedelta(days=1)
    )
    carry_employee_id = latest.employee_id

    ended = []
    for entry in stale:
        _finalize_stale_day(db, entry)
        ended.append((entry.id, entry.date, float(entry.total_hours or 0.0)))
    db.flush()

    started_date = None
    if continue_active:
        already_today = (
            db.query(TimeEntry)
            .filter(TimeEntry.user_id == user_id, TimeEntry.date == today)
            .first()
        )
        if not already_today:
            midnight = _local_midnight_utc(today)  # UTC instant of local 00:00 today
            new_entry = TimeEntry(
                user_id=user_id,
                employee_id=carry_employee_id,
                start_time=midnight,
                date=today,
                status="active",
            )
            db.add(new_entry)
            db.flush()
            db.add(TimeCheckPair(user_id=user_id, date=today, check_in=midnight))
            db.flush()
            started_date = today

    _notify_rollover(db, user_id, ended, started_date)
    return True


def _week_dates(offset: int = 0):
    """LOCAL Monday and Sunday calendar dates for the given week offset (0=current)."""
    today = _local_today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    return monday, monday + timedelta(days=6)


def _week_bounds(offset: int = 0):
    """Local Monday 00:00 → local Sunday 23:59:59.999999, as UTC instants.

    Returned in UTC because history/weekly filter on start_time (a UTC instant),
    but the week itself follows LOCAL midnight like work days do — a session
    started Monday 01:00 local (Sunday evening UTC) belongs to the new week.
    """
    monday, sunday = _week_dates(offset)
    return _local_midnight_utc(monday), _local_day_end_utc(sunday)


def _pairs_for_date(db: Session, user_id: int, target_date: date_type) -> List[dict]:
    """Returns serialized check pairs for a given date."""
    pairs = (
        db.query(TimeCheckPair)
        .filter(
            TimeCheckPair.user_id == user_id,
            TimeCheckPair.date == target_date,
        )
        .order_by(TimeCheckPair.check_in.asc())
        .all()
    )
    return [
        {
            "id": p.id,
            "check_in": p.check_in,
            "check_out": p.check_out,
            "seconds": p.seconds,
        }
        for p in pairs
    ]


def _day_entry_response(db: Session, entry: TimeEntry) -> dict:
    """Build a DayEntryResponse dict from a TimeEntry."""
    entry_date = entry.date or (entry.start_time.date() if entry.start_time else None)
    date_str = entry_date.isoformat() if entry_date else None

    # For active/paused entries, compute live total from completed pairs
    if entry.status in ("active", "paused") and entry_date:
        completed_secs = _accumulated_seconds(db, entry.user_id, entry_date)
        total_hours = round(completed_secs / 3600, 4) if completed_secs else 0.0
        # For active (currently ticking), the frontend will add the live delta
    else:
        total_hours = float(entry.total_hours) if entry.total_hours is not None else None

    overtime_val = float(entry.overtime) if entry.overtime is not None else None

    pairs = _pairs_for_date(db, entry.user_id, entry_date) if entry_date else []

    return {
        "date": date_str,
        "total_hours": total_hours,
        "overtime": overtime_val,
        "status": entry.status,
        "pairs": pairs,
    }


def _to_legacy_response(entry: TimeEntry) -> dict:
    """Map DB model → legacy TimeEntryResponse dict (backward compat)."""
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "employee_id": entry.employee_id,
        "clock_in": entry.start_time,
        "clock_out": entry.end_time,
        "total_hours": float(entry.total_hours) if entry.total_hours is not None else None,
        "overtime": float(entry.overtime) if entry.overtime is not None else None,
        "status": entry.status,
        "work_date": entry.date.isoformat() if entry.date else None,
    }


# ── POST /start — Start Work ─────────────────────────────────────────────────────
@router.post("/start", response_model=ClockStatusResponse)
def clock_in(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Start a new work session.
    Creates or reuses today's TimeEntry and opens a new check pair.
    Returns 400 if user already has an active/paused session today.
    """
    now = _utc_now()          # stored timestamp (UTC)
    today = _local_today()    # which local day this belongs to

    # First roll over any unfinished prior day: if the user was still actively
    # working when the clock passed local midnight, that day is closed at its own
    # midnight AND today's session is auto-started from 00:00. So this click may
    # find that today's session is already running. Commit here so the rollover
    # and its notifications persist even if the "already clocked in" path returns.
    if _auto_finalize_stale_days(db, current_user.id):
        db.commit()

    # Re-check AFTER the rollover — the continuation above may already have
    # started today's session.
    existing = _today_entry(db, current_user.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already clocked in today. Use pause/resume or end your current session first."
        )

    # One clock-in cycle per day: once the day has been ended (status
    # 'completed'), Start must be refused rather than opening a second day-entry.
    # Pause/resume is the way to take breaks within the single start…end cycle.
    completed_today = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.user_id == current_user.id,
            TimeEntry.date == today,
            TimeEntry.status == "completed",
        )
        .first()
    )
    if completed_today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already clocked in today. Your work day has already ended."
        )

    # Create day-level entry
    entry = TimeEntry(
        user_id=current_user.id,
        employee_id=current_user.employee_id,
        start_time=now,
        date=today,
        status="active",
    )
    db.add(entry)
    db.flush()

    # Create first check pair
    pair = TimeCheckPair(
        user_id=current_user.id,
        date=today,
        check_in=now,
    )
    db.add(pair)
    db.commit()
    db.refresh(entry)

    return {
        "active": True,
        "paused": False,
        "clock_in": now,
        "elapsed_seconds": 0,
        "entry_id": entry.id,
    }


# ── POST /pause — Pause Work ─────────────────────────────────────────────────────
@router.post("/pause", response_model=ClockStatusResponse)
def pause_work(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Pause the current work session.
    Closes the open check pair and sets day status to 'paused'.
    Timer should freeze on the frontend.
    """
    entry = _today_entry(db, current_user.id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session found. Start work first."
        )

    if entry.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not currently active (already paused or completed)."
        )

    pair = _open_pair(db, current_user.id)
    if not pair:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No open check pair found to pause."
        )

    now = _utc_now()
    _close_pair(pair, now)
    entry.status = "paused"
    db.commit()

    accumulated = _accumulated_seconds(db, current_user.id, entry.date or _local_today())
    return {
        "active": True,
        "paused": True,
        "clock_in": None,
        "elapsed_seconds": accumulated,
        "entry_id": entry.id,
    }


# ── POST /resume — Resume Work ───────────────────────────────────────────────────
@router.post("/resume", response_model=ClockStatusResponse)
def resume_work(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resume work after a pause.
    Opens a new check pair and sets day status back to 'active'.
    """
    entry = _today_entry(db, current_user.id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session found. Start work first."
        )

    if entry.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not paused. Cannot resume."
        )

    now = _utc_now()          # stored timestamp (UTC)
    today = _local_today()    # local day this segment belongs to

    pair = TimeCheckPair(
        user_id=current_user.id,
        date=today,
        check_in=now,
    )
    db.add(pair)

    entry.status = "active"
    db.commit()

    accumulated = _accumulated_seconds(db, current_user.id, today)
    return {
        "active": True,
        "paused": False,
        "clock_in": now,
        "elapsed_seconds": accumulated,
        "entry_id": entry.id,
    }


# ── POST /end — End Work ─────────────────────────────────────────────────────────
@router.post("/end", response_model=DayEntryResponse)
def clock_out(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    End the current work session.
    Closes any open pair, finalizes the day (computes total + overtime),
    and sets status='completed'.
    """
    entry = _today_entry(db, current_user.id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session found."
        )

    now = _utc_now()
    _finalize_day(db, entry, now)
    db.commit()
    db.refresh(entry)

    return _day_entry_response(db, entry)


# ── GET /current — Active session (source of truth for timer) ─────────────────────
@router.get("/current", response_model=ClockStatusResponse)
def get_current_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the current session state:
    - active=False → not clocked in
    - active=True, paused=False → working (clock_in = open pair's check-in)
    - active=True, paused=True → paused (clock_in = None, elapsed_seconds = accumulated)
    Frontend always calls this on mount — NEVER use localStorage as source of truth.
    """
    # Self-heal: close out any day the user forgot to end before today, so the
    # timer never reports a session that has been ticking across midnight.
    if _auto_finalize_stale_days(db, current_user.id):
        db.commit()

    entry = _today_entry(db, current_user.id)
    if not entry:
        completed_today = (
            db.query(TimeEntry)
            .filter(
                TimeEntry.user_id == current_user.id,
                TimeEntry.date == _local_today(),
                TimeEntry.status == "completed",
            )
            .first()
        )
        return {"active": False, "paused": False, "completed": bool(completed_today), "elapsed_seconds": 0}

    today = entry.date or _local_today()
    accumulated = _accumulated_seconds(db, current_user.id, today)

    if entry.status == "paused":
        return {
            "active": True,
            "paused": True,
            "clock_in": None,
            "elapsed_seconds": accumulated,
            "entry_id": entry.id,
        }

    # status == "active" → there should be an open pair
    pair = _open_pair(db, current_user.id)
    return {
        "active": True,
        "paused": False,
        "clock_in": pair.check_in if pair else entry.start_time,
        "elapsed_seconds": accumulated,
        "entry_id": entry.id,
    }


# ── GET /history — Day-grouped entries (filterable by week) ───────────────────────
@router.get("/history", response_model=List[DayEntryResponse])
def get_history(
    week: int = _period_offset(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns day-grouped entries for the logged-in user, ordered newest first.
    Each day is a single row with nested check-in/check-out pairs.
    """
    if _auto_finalize_stale_days(db, current_user.id):
        db.commit()

    monday, sunday = _week_bounds(week)
    entries = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.user_id == current_user.id,
            TimeEntry.start_time >= monday,
            TimeEntry.start_time <= sunday,
        )
        .order_by(TimeEntry.start_time.desc())
        .all()
    )

    # Group by date — there should already be one entry per day,
    # but handle legacy duplicates by merging
    day_map: dict = {}
    for e in entries:
        d = (e.date or e.start_time.date()).isoformat()
        if d not in day_map:
            day_map[d] = e
        # If duplicate date entries exist (legacy), keep the one with higher total
        # This shouldn't happen going forward

    return [_day_entry_response(db, entry) for entry in day_map.values()]


# ── GET /weekly-stats — Summary for the stats cards ──────────────────────────────
@router.get("/weekly-stats", response_model=WeeklyStatsResponse)
def get_weekly_stats(
    week: int = _period_offset(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Aggregated weekly stats: total_hours, regular_hours, overtime_hours.
    Now uses per-day totals and the configurable overtime threshold.
    """
    if _auto_finalize_stale_days(db, current_user.id):
        db.commit()

    monday, sunday = _week_bounds(week)
    all_entries = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.user_id == current_user.id,
            TimeEntry.start_time >= monday,
            TimeEntry.start_time <= sunday,
        )
        .order_by(TimeEntry.start_time.desc())
        .all()
    )

    # Group by date
    day_map: dict = {}
    for e in all_entries:
        d = (e.date or e.start_time.date()).isoformat()
        if d not in day_map:
            day_map[d] = e

    day_entries = list(day_map.values())
    completed = [e for e in day_entries if e.status == "completed" and e.total_hours is not None]

    total = round(sum(float(e.total_hours) for e in completed), 2)
    ot_sum = round(sum(float(e.overtime or 0) for e in completed), 2)
    regular = round(max(0.0, total - ot_sum), 2)

    # Include in-progress entries in total for display
    for e in day_entries:
        if e.status in ("active", "paused") and e.date:
            live_secs = _accumulated_seconds(db, current_user.id, e.date)
            if e.status == "active":
                pair = _open_pair(db, current_user.id)
                if pair:
                    live_secs += int((_utc_now() - pair.check_in).total_seconds())
            live_hours = round(live_secs / 3600, 2)
            total = round(total + live_hours, 2)
            threshold = _get_threshold_for_date(db, e.date)
            live_ot = round(max(0.0, live_hours - threshold), 2)
            ot_sum = round(ot_sum + live_ot, 2)
            regular = round(max(0.0, total - ot_sum), 2)

    current_threshold = _get_current_threshold(db)

    # Build day-grouped response
    day_responses = [_day_entry_response(db, entry) for entry in day_entries]

    week_start, week_end = _week_dates(week)
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_hours": total,
        "regular_hours": regular,
        "overtime_hours": ot_sum,
        "overtime_threshold": current_threshold,
        "entries": day_responses,
    }


# ── GET /overtime-threshold — Current effective threshold ─────────────────────────
@router.get("/overtime-threshold", response_model=OvertimeThresholdResponse)
def get_overtime_threshold(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the currently effective overtime threshold."""
    row = (
        db.query(OvertimeThresholdHistory)
        .order_by(OvertimeThresholdHistory.effective_date.desc())
        .first()
    )
    if row:
        return {
            "threshold_hours": float(row.threshold_hours),
            "effective_date": row.effective_date.isoformat(),
        }
    return {
        "threshold_hours": DEFAULT_THRESHOLD,
        "effective_date": "2000-01-01",
    }


# ── PUT /overtime-threshold — Update threshold (permission-gated) ─────────────────
@router.put(
    "/overtime-threshold",
    response_model=OvertimeThresholdResponse,
    dependencies=[Depends(require_permission("time_tracking:edit_overtime_threshold"))],
)
def update_overtime_threshold(
    payload: OvertimeThresholdUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update the overtime threshold. Creates a new history row with
    effective_date = today. Only affects future/today's overtime calculations.
    Past finalized days remain unchanged.
    """
    new_threshold = payload.threshold_hours

    today = _local_today()
    row = OvertimeThresholdHistory(
        threshold_hours=Decimal(str(round(new_threshold, 2))),
        effective_date=today,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()

    return {
        "threshold_hours": float(row.threshold_hours),
        "effective_date": row.effective_date.isoformat(),
    }


# ── Backward-compat aliases ───────────────────────────────────────────────────────

@router.get("/status", response_model=ClockStatusResponse)
def status_compat(db=Depends(get_db), current_user=Depends(get_current_user)):
    return get_current_session(db, current_user)

@router.post("/clock-in", response_model=ClockStatusResponse)
def clock_in_compat(db=Depends(get_db), current_user=Depends(get_current_user)):
    return clock_in(db, current_user)

@router.post("/clock-out", response_model=DayEntryResponse)
def clock_out_compat(db=Depends(get_db), current_user=Depends(get_current_user)):
    return clock_out(db, current_user)

@router.get("/all-attendance", response_model=AllAttendanceResponse, dependencies=[Depends(require_permission("attendance:view_others"))])
def get_all_attendance(
    period: Literal["day", "week", "month"] = "week",
    offset: int = _period_offset(),
    db: Session = Depends(get_db)
):
    """
    Returns attendance records for all active users based on the specified period (day/week/month)
    and offset (0 = current, -1 = previous, etc.).
    Requires 'attendance:view_others' permission.
    """
    now = _local_now()  # period is matched against the local `date` column

    if period == "day":
        target_date = (now + timedelta(days=offset)).date()
        start_date = datetime(target_date.year, target_date.month, target_date.day)
        end_date = start_date + timedelta(days=1, microseconds=-1)
    elif period == "month":
        # Simplified month arithmetic (good enough for typical offsets)
        years, month_index = divmod(now.month - 1 + offset, 12)
        target_year, target_month = now.year + years, month_index + 1
        start_date = datetime(target_year, target_month, 1)
        # Next month start minus 1 microsecond
        next_month = target_month + 1 if target_month < 12 else 1
        next_year = target_year if target_month < 12 else target_year + 1
        end_date = datetime(next_year, next_month, 1) - timedelta(microseconds=1)
    else:  # week
        # Local dates, not the UTC instants from _week_bounds(): the filter below
        # is on the local `date` column.
        monday, sunday = _week_dates(offset)
        start_date = datetime.combine(monday, datetime.min.time())
        end_date = datetime.combine(sunday, datetime.max.time())
        
    start_date_only = start_date.date()
    end_date_only = end_date.date()

    # Source the roster from real EMPLOYEE records (not raw users). This excludes
    # non-employee accounts such as super admins, and lets us read the AUTHORITATIVE
    # department (employees.department_id → departments.name) and role
    # (users.roles → role_name) instead of the stale/backward-compat
    # users.department and users.role scalar columns.
    from app.employees.models import Employee
    employees = (
        db.query(Employee)
        .options(
            joinedload(Employee.department_rel),
            joinedload(Employee.user).joinedload(User.roles),
        )
        .filter(Employee.is_deleted == False)
        .all()
    )

    # Query time entries in the range, grouped by the owning user
    entries = db.query(TimeEntry).filter(
        TimeEntry.date >= start_date_only,
        TimeEntry.date <= end_date_only,
    ).all()
    entries_by_user: dict = {}
    for e in entries:
        entries_by_user.setdefault(e.user_id, []).append(e)

    items = []
    for emp in employees:
        user = emp.user
        # Skip employees with no linked login, or whose account is inactive/deleted
        if not user or not user.is_active or user.is_deleted:
            continue

        user_entries = entries_by_user.get(user.id, [])
        total_hours = 0.0
        overtime = 0.0
        for e in user_entries:
            # Live total for in-progress days (mirrors _day_entry_response)
            if e.status in ("active", "paused") and e.date:
                completed_secs = _accumulated_seconds(db, e.user_id, e.date)
                e_hours = round(completed_secs / 3600, 4) if completed_secs else 0.0
            else:
                e_hours = float(e.total_hours) if e.total_hours is not None else 0.0

            total_hours += e_hours
            overtime += float(e.overtime) if e.overtime is not None else 0.0

        # Authoritative role: first role assigned via the RBAC join table; only
        # fall back to the legacy scalar when no role is linked.
        role_name = user.roles[0].role_name if user.roles else (user.role or None)
        # Authoritative department: from the employee's department FK.
        dept_name = emp.department_rel.name if emp.department_rel else None

        items.append({
            "user_id": user.id,
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "employee_id": emp.employee_id,
            "department": dept_name,
            "role": role_name,
            "total_hours": round(total_hours, 4),
            "overtime": round(overtime, 4),
        })

    return {
        "period": period,
        "start_date": start_date_only.isoformat(),
        "end_date": end_date_only.isoformat(),
        "items": items,
    }


@router.get("/entries", response_model=List[DayEntryResponse])
def entries_compat(db=Depends(get_db), current_user=Depends(get_current_user)):
    return get_history(0, db, current_user)
