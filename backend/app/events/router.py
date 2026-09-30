from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta

from app.database.database import get_db
from app.core.deps import get_current_user, require_permission
from app.auth.models import User
from app.events.models import Event, UserCalendarEvent
from app.events.schemas import EventCreate, EventUpdate, EventResponse, EventWithStatus
from app.core.app_time import to_local, local_today

router = APIRouter()

EVENT_LINK = "/dashboard#widget-upcoming_events"


def _format_event_date(event_date: datetime) -> str:
    """
    Render an event date relative to today so reminders read naturally.

    Includes its own preposition ("today at …" vs "on Jul 28, 2026") so callers
    can drop it straight into a sentence without producing "on today at …".
    `event_date` is stored UTC; people read local time.
    """
    event_date = to_local(event_date)
    today = local_today()
    d = event_date.date()
    if d == today:
        return f"today at {event_date.strftime('%I:%M %p').lstrip('0')}"
    if d == today + timedelta(days=1):
        return f"tomorrow at {event_date.strftime('%I:%M %p').lstrip('0')}"
    return f"on {event_date.strftime('%b %d, %Y')}"


def _format_cancellation(title: str, event_date: datetime) -> str:
    """
    Word a cancellation around the event's own name and day.

    An event cancelled on the day it falls reads "is not held today"; anything
    further out reads as a plain cancellation with its date.
    """
    event_date = to_local(event_date)
    today = local_today()
    d = event_date.date()
    if d == today:
        return f"{title} is not held today"
    if d == today + timedelta(days=1):
        return f"{title} scheduled for tomorrow has been cancelled"
    return f"{title} scheduled for {event_date.strftime('%b %d, %Y')} has been cancelled"


def _notify_all_users(
    db: Session,
    message: str,
    *,
    actor_id: int,
    event_id: int,
    type: str = "info",
) -> None:
    """
    Fan an event message out to every active user except the actor.

    Never raises — an event change must not fail because notifying failed.
    """
    try:
        from app.notifications.service import notify_users

        user_ids = [
            uid for (uid,) in db.query(User.id).filter(User.is_active == True).all()
        ]
        if user_ids:
            notify_users(
                db,
                user_ids,
                message,
                category="events",
                type=type,
                link=EVENT_LINK,
                entity_type="event",
                entity_id=str(event_id),
                exclude_user_id=actor_id,
            )
            db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Events] Notification failed: {e}")
        db.rollback()


# ── GET upcoming events only (future dates) ─────────────────────────────────────
@router.get("", response_model=List[EventWithStatus])
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns future events only. Past events are automatically excluded."""
    now = datetime.utcnow()
    events = (
        db.query(Event)
        .filter(Event.event_date >= now)
        .order_by(Event.event_date.asc())
        .all()
    )
    
    # Check which events are saved by the current user
    saved_event_ids = set(
        db.query(UserCalendarEvent.event_id)
        .filter(UserCalendarEvent.user_id == current_user.id)
        .all()
    )
    saved_event_ids = {id[0] for id in saved_event_ids}

    return [
        EventWithStatus(
            id=ev.id,
            title=ev.title,
            description=ev.description,
            event_date=ev.event_date,
            location=ev.location,
            created_by=ev.created_by,
            created_at=ev.created_at,
            is_saved=(ev.id in saved_event_ids)
        ) for ev in events
    ]


# ── GET all events including past — used by Calendar widget ────────────────────
@router.get("/all", response_model=List[EventResponse])
def list_all_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns all events (past + future). Used by CalendarWidget."""
    return db.query(Event).order_by(Event.event_date.asc()).all()


@router.get("/my-calendar", response_model=List[EventResponse])
def list_my_calendar_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns events explicitly saved by the user to their calendar."""
    return (
        db.query(Event)
        .join(UserCalendarEvent, Event.id == UserCalendarEvent.event_id)
        .filter(UserCalendarEvent.user_id == current_user.id)
        .order_by(Event.event_date.asc())
        .all()
    )


@router.post("/{event_id}/save", status_code=status.HTTP_201_CREATED)
def save_event_to_calendar(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.query(Event.id).filter(Event.id == event_id).first():
        raise HTTPException(status_code=404, detail="Event not found")

    # Check if already saved
    existing = db.query(UserCalendarEvent).filter(
        UserCalendarEvent.user_id == current_user.id,
        UserCalendarEvent.event_id == event_id
    ).first()
    if existing:
        return {"message": "Already saved"}
    
    save = UserCalendarEvent(user_id=current_user.id, event_id=event_id)
    db.add(save)
    db.commit()
    return {"message": "Saved to calendar"}


@router.delete("/{event_id}/save", status_code=status.HTTP_204_NO_CONTENT)
def remove_event_from_calendar(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    save = db.query(UserCalendarEvent).filter(
        UserCalendarEvent.user_id == current_user.id,
        UserCalendarEvent.event_id == event_id
    ).first()
    if save:
        db.delete(save)
        db.commit()
    return


# ── POST — requires widget.upcoming_events.manage ──────────────────────────────
@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    data: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("widget.upcoming_events.manage")),
):
    # Reject past-dated events on creation. Otherwise the event saves but is
    # hidden from the "upcoming" list (which filters event_date >= now) — a
    # confusing saved-and-invisible state (BUG-22 / TC-EVT-008). Compared to the
    # minute, not the day: an event earlier today is just as invisible.
    if data.event_date < datetime.utcnow() - timedelta(minutes=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event date cannot be in the past.",
        )

    event = Event(
        title=data.title,
        description=data.description,
        event_date=data.event_date,
        location=data.location,
        created_by=current_user.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    _notify_all_users(
        db,
        f"New upcoming event: {event.title} {_format_event_date(event.event_date)}",
        actor_id=current_user.id,
        event_id=event.id,
    )

    return event


# ── PUT — requires widget.upcoming_events.manage ───────────────────────────────
@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    data: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("widget.upcoming_events.manage")),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    was_upcoming = ev.event_date >= datetime.utcnow()

    changes = data.model_dump(exclude_unset=True)
    # Moving an event INTO the past has the same saved-but-invisible problem as
    # creating one there. Editing other fields of a past event stays allowed.
    if "event_date" in changes and changes["event_date"] != ev.event_date             and changes["event_date"] < datetime.utcnow() - timedelta(minutes=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event date cannot be in the past.",
        )

    for field, value in changes.items():
        setattr(ev, field, value)
    db.commit()
    db.refresh(ev)

    # Only announce edits to events that people can still attend — editing a
    # past event is a records fix, not news.
    if was_upcoming or ev.event_date >= datetime.utcnow():
        _notify_all_users(
            db,
            f"Event updated: {ev.title} is now {_format_event_date(ev.event_date)}",
            actor_id=current_user.id,
            event_id=ev.id,
            type="warning",
        )

    return ev


# ── DELETE — requires widget.upcoming_events.manage ───────────────────────────
@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("widget.upcoming_events.manage")),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    # Capture what we need for the message before the row goes away.
    title = ev.title
    event_date = ev.event_date
    was_upcoming = event_date >= datetime.utcnow()

    db.delete(ev)
    db.commit()

    # Cancellations are named after the event itself — people recognise
    # "Annual General Meeting is cancelled", not "an upcoming event".
    if was_upcoming:
        _notify_all_users(
            db,
            _format_cancellation(title, event_date),
            actor_id=current_user.id,
            event_id=event_id,
            type="warning",
        )
