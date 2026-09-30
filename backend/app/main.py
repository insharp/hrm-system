import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import logging

from app.database.database import engine, SessionLocal
from app.database.base import Base

logger = logging.getLogger(__name__)

# ── Import all models ──
import app.roles.models             # noqa: F401
import app.auth.models              # noqa: F401
import app.departments.models       # noqa: F401
import app.employees.models         # noqa: F401
import app.time_tracking.models     # noqa: F401
import app.messages.models          # noqa: F401
import app.announcements.models     # noqa: F401
import app.events.models            # noqa: F401
import app.notifications.models     # noqa: F401
import app.calendar_holidays.models # noqa: F401
import app.dashboard.models         # noqa: F401

# ── Document models ────────────────────────────────────────────────────────────
from app.documents.models.model import EmployeeDocument              # noqa: F401
from app.documents.models.template_model import DocumentTemplate     # noqa: F401
from app.documents.models.document_type_model import DocumentType    # noqa: F401
from app.documents.models.audit_log_model import DocumentAuditLog    # noqa: F401
from app.documents.models.request_model import DocumentRequest       # noqa: F401

# ── Routers ────────────────────────────────────────────────────────────────────
from app.auth.router          import router as auth_router
from app.roles.router         import router as roles_router
from app.employees.router     import router as employee_router
from app.leave.router         import router as leave_router
from app.reports.router       import router as reports_router
import app.leave.models             # noqa: F401 — register leave tables for create_all
from app.departments.router   import router as departments_router
from app.designations.router  import router as designations_router
from app.dashboard.router     import router as dashboard_router
from app.messages.router      import router as messages_router
from app.announcements.router import router as announcements_router
from app.events.router        import router as events_router
from app.calendar_holidays.router import router as holidays_router
from app.notifications.router import router as notifications_router
from app.time_tracking.router import router as time_tracking_router

# ── Document routers ───────────────────────────────────────────────────────────
from app.documents.routers.router               import router as documents_router
from app.documents.routers.approval_router      import router as approval_router
from app.documents.routers.request_router       import router as request_router
from app.documents.routers.hr_request_router    import router as hr_request_router
from app.documents.routers.template_router      import router as template_router
from app.documents.routers.document_type_router import router as document_type_router
from app.documents.routers.promotion_router     import router as promotion_letter_router
from app.documents.routers.employee_docs_router import router as employee_docs_router

# ── Recruitment routers (from recruitment branch) ──────────────────────────────
try:
    from app.recruitment.router        import router as recruitment_router
    from app.recruitment.public_router import router as public_router
    _recruitment_available = True
except ImportError:
    _recruitment_available = False
    recruitment_router = None
    public_router = None
    logger.warning("Recruitment module not found — skipping.")

# NOTE: the inbound email poller is no longer a hand-rolled sleep loop here. It
# runs as an APScheduler job (`poll_email_inbox` in app/core/scheduler.py) so it
# has a job registry, max_instances=1, and the same lifecycle as the other
# scheduled jobs. Trigger one cycle on demand via POST /hr-document-requests/poll-inbox.


async def holiday_reminder_loop():
    """
    Background loop that checks once per hour for tomorrow's holidays and
    notifies all active users.

    Dedupes against the notifications table, not process memory: an in-memory
    guard is reset by every restart, which would re-send the reminder each time.
    """
    from app.core.scheduler import advisory_lock
    await asyncio.sleep(30)  # Delay startup to let DB initialize
    while True:
        try:
            # One worker per cycle sends the reminders (advisory lock); the
            # notifications-table dedupe is a second guard, but the lock avoids
            # N workers racing to send in the first place.
            with advisory_lock("holiday_reminder") as got_lock:
                if got_lock:
                    from datetime import date, timedelta
                    from app.calendar_holidays.models import Holiday
                    from app.auth.models import User
                    from app.notifications.service import notify_users, already_notified_today

                    tomorrow = (date.today() + timedelta(days=1)).isoformat()

                    db = SessionLocal()
                    try:
                        holidays = db.query(Holiday).filter(Holiday.date == tomorrow).all()
                        if holidays:
                            # Get all active user IDs
                            active_user_ids = [
                                uid for (uid,) in
                                db.query(User.id).filter(User.is_active == True).all()
                            ]
                            if active_user_ids:
                                sent = 0
                                for holiday in holidays:
                                    if already_notified_today(db, "holiday_reminder", holiday.id):
                                        continue
                                    notify_users(
                                        db,
                                        active_user_ids,
                                        f"\U0001f4c5 Tomorrow is {holiday.name}",
                                        category="holiday",
                                        type="info",
                                        link="/dashboard#widget-calendar",
                                        entity_type="holiday_reminder",
                                        entity_id=str(holiday.id),
                                    )
                                    sent += 1
                                if sent:
                                    db.commit()
                                    logger.info("[Holiday Reminder] Sent %s holiday reminder(s) to %s users.", sent, len(active_user_ids))
                    finally:
                        db.close()
        except Exception as e:
            logger.error("[Holiday Reminder] Loop Error: %s", e)
        await asyncio.sleep(3600)  # Check every hour

async def daily_digest_loop():
    """
    Once-a-day background pass for time-based notifications.

    Covers what nobody triggers by hand: tomorrow's events, today's birthdays
    and work anniversaries, and the retention purge.

    Runs hourly. Each job dedupes against the notifications table rather than
    process memory, so restarts (uvicorn --reload fires one on every code save)
    cannot re-send the same reminder.
    """
    from app.core.scheduler import advisory_lock
    await asyncio.sleep(45)  # let the DB settle, and stagger off the holiday loop
    while True:
        try:
            # One worker per cycle runs events/celebrations/purge (advisory lock).
            with advisory_lock("daily_digest") as got_lock:
                if got_lock:
                    from datetime import date

                    today = date.today()
                    db = SessionLocal()
                    try:
                        _notify_tomorrows_events(db, today)
                        _notify_celebrations(db, today)

                        from app.notifications.service import purge_expired_notifications
                        purged = purge_expired_notifications(db)
                        if purged:
                            logger.info("[Notifications] Retention purge removed %s old notification(s).", purged)
                    finally:
                        db.close()
        except Exception as e:
            logger.error("[Daily Digest] Loop Error: %s", e)
        await asyncio.sleep(3600)


def _active_user_ids(db) -> list:
    from app.auth.models import User
    return [uid for (uid,) in db.query(User.id).filter(User.is_active == True).all()]


def _notify_tomorrows_events(db, today) -> None:
    """Remind everyone about events happening tomorrow, at most once per event per day."""
    try:
        from datetime import datetime, timedelta, time as dt_time
        from app.events.models import Event
        from app.notifications.service import notify_users, already_notified_today

        tomorrow = today + timedelta(days=1)
        events = (
            db.query(Event)
            .filter(
                Event.event_date >= datetime.combine(tomorrow, dt_time.min),
                Event.event_date <= datetime.combine(tomorrow, dt_time.max),
            )
            .all()
        )
        if not events:
            return

        user_ids = _active_user_ids(db)
        if not user_ids:
            return

        sent = 0
        for ev in events:
            # The table is the guard, not process memory — this loop re-runs on
            # every restart and must not re-send the same reminder.
            if already_notified_today(db, "event_reminder", ev.id):
                continue
            when = ev.event_date.strftime("%I:%M %p").lstrip("0")
            location = f" at {ev.location}" if ev.location else ""
            notify_users(
                db,
                user_ids,
                f"Reminder: {ev.title} is tomorrow at {when}{location}",
                category="events",
                type="info",
                link="/dashboard#widget-upcoming_events",
                entity_type="event_reminder",
                entity_id=str(ev.id),
            )
            sent += 1
        if sent:
            db.commit()
            print(f"[Event Reminder] Sent {sent} event reminder(s) to {len(user_ids)} users.")
    except Exception as e:
        print(f"[Event Reminder] Error: {e}")
        db.rollback()


def _notify_celebrations(db, today) -> None:
    """Announce today's birthdays and work anniversaries to the team."""
    try:
        from sqlalchemy import extract
        from app.employees.models import Employee
        from app.notifications.service import notify_users, already_notified_today

        user_ids = _active_user_ids(db)
        if not user_ids:
            return

        active_employees = db.query(Employee).filter(
            (Employee.is_deleted == False) | (Employee.is_deleted.is_(None))
        )

        # ── Birthdays ────────────────────────────────────────────────
        birthdays = active_employees.filter(
            Employee.date_of_birth.isnot(None),
            extract("month", Employee.date_of_birth) == today.month,
            extract("day", Employee.date_of_birth) == today.day,
        ).all()

        for emp in birthdays:
            if already_notified_today(db, "birthday", emp.id):
                continue
            name = f"{emp.first_name} {emp.last_name}"
            notify_users(
                db,
                user_ids,
                f"\U0001f389 Today is {name}'s birthday",
                category="celebration",
                type="info",
                link="/dashboard/employees",
                entity_type="birthday",
                entity_id=str(emp.id),
                # Don't tell someone it's their own birthday.
                exclude_user_id=emp.user_id,
            )

        # ── Work anniversaries ───────────────────────────────────────
        anniversaries = active_employees.filter(
            Employee.joined_date.isnot(None),
            extract("month", Employee.joined_date) == today.month,
            extract("day", Employee.joined_date) == today.day,
        ).all()

        for emp in anniversaries:
            years = today.year - emp.joined_date.year
            if years < 1:
                continue  # their start date, not an anniversary
            if already_notified_today(db, "work_anniversary", emp.id):
                continue
            name = f"{emp.first_name} {emp.last_name}"
            label = "1 year" if years == 1 else f"{years} years"
            notify_users(
                db,
                user_ids,
                f"\U0001f38a {name} completes {label} at the company today",
                category="celebration",
                type="info",
                link="/dashboard/employees",
                entity_type="work_anniversary",
                entity_id=str(emp.id),
                exclude_user_id=emp.user_id,
            )

        if birthdays or anniversaries:
            db.commit()
            print(f"[Celebrations] Sent {len(birthdays)} birthday(s), {len(anniversaries)} anniversary(ies).")
    except Exception as e:
        print(f"[Celebrations] Error: {e}")
        db.rollback()


# ── Seed helpers ───────────────────────────────────────────────────────────────
from app.roles.seed       import seed_roles
from app.departments.seed import seed_departments


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema ownership: Alembic is authoritative. create_all() is a dev-only
    # convenience so contributors can spin up without running migrations. In
    # production set ENVIRONMENT=production and run `alembic upgrade head` — the
    # two schema sources must not both manage the DB, or they drift.
    if os.getenv("ENVIRONMENT", "development").strip().lower() == "production":
        logger.info("[Startup] ENVIRONMENT=production — skipping create_all(); Alembic migrations are authoritative.")
    else:
        Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        try:
            seed_departments(db)
        except Exception as e:
            print(f"[WARNING] seed_departments skipped: {e}")
        try:
            seed_roles(db)
        except Exception as e:
            print(f"[WARNING] seed_roles skipped (DB migration may be needed): {e}")
        try:
            # Seed default overtime threshold (8h) if none exists
            from app.time_tracking.models import OvertimeThresholdHistory
            from datetime import date as date_type
            from decimal import Decimal
            existing_threshold = db.query(OvertimeThresholdHistory).first()
            if not existing_threshold:
                default_threshold = OvertimeThresholdHistory(
                    threshold_hours=Decimal("8.00"),
                    effective_date=date_type(2000, 1, 1),
                    created_by_user_id=None,
                )
                db.add(default_threshold)
                db.commit()
                print("[Seed] Default overtime threshold (8h) created.")
        except Exception as e:
            print(f"[WARNING] seed_overtime_threshold skipped: {e}")
        try:
            from app.calendar_holidays.router import seed_holidays
            seed_holidays()
        except Exception as e:
            print(f"[WARNING] seed_holidays skipped: {e}")
        try:
            from app.leave.seed import seed_leave_types
            seed_leave_types(db)
        except Exception as e:
            print(f"[WARNING] seed_leave_types skipped: {e}")
        try:
            from app.documents.services.document_type_service import seed_request_document_types
            seed_request_document_types(db)
        except Exception as e:
            print(f"[WARNING] seed_request_document_types skipped: {e}")
    finally:
        db.close()

    holiday_task = asyncio.create_task(holiday_reminder_loop())
    print("[Holiday Reminder] Background holiday reminder loop started (checks every hour).")
    digest_task = asyncio.create_task(daily_digest_loop())
    print("[Daily Digest] Event reminders, celebrations and retention purge started (checks every hour).")

    # APScheduler runs the nightly designation-expiry check; it is independent of
    # the asyncio loops above, so a failure to start must not take them down.
    from app.core.scheduler import start_scheduler, shutdown_scheduler
    try:
        start_scheduler()
    except Exception as e:
        print(f"[Scheduler] Failed to start APScheduler: {e}")

    yield

    holiday_task.cancel()
    digest_task.cancel()

    try:
        shutdown_scheduler()
    except Exception as e:
        print(f"[Scheduler] Failed to shutdown APScheduler: {e}")
    try:
        await holiday_task
    except asyncio.CancelledError:
        pass
    try:
        await digest_task
    except asyncio.CancelledError:
        pass
    print("[Holiday Reminder] Background holiday reminder loop stopped.")
    print("[Daily Digest] Background daily digest loop stopped.")


app = FastAPI(
    title="HRM System API",
    version="2.0.0",
    description="Role-based HRM System — permissions managed via /roles/",
    lifespan=lifespan,
    redirect_slashes=False,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API routers ───────────────────────────────────────────────────────
app.include_router(auth_router,          prefix="/auth",          tags=["Authentication"])
app.include_router(roles_router,         prefix="/roles",         tags=["Roles & Permissions"])
app.include_router(employee_router,      prefix="/employees",     tags=["Employees"])
app.include_router(leave_router,         tags=["Leave"])  # router defines its own /leave prefix
app.include_router(reports_router,       tags=["Reports"])
app.include_router(departments_router,   prefix="/departments",   tags=["Departments"])
app.include_router(designations_router,  prefix="/designations",  tags=["Designations"])
app.include_router(dashboard_router,     prefix="/dashboard",     tags=["Dashboard"])
app.include_router(messages_router,      prefix="/messages",      tags=["Messages"])
app.include_router(announcements_router, prefix="/announcements", tags=["Announcements"])
app.include_router(events_router,        prefix="/events",        tags=["Events"])
app.include_router(holidays_router,      prefix="/holidays",      tags=["Holidays"])
app.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
app.include_router(time_tracking_router, prefix="/time-tracking", tags=["Time Tracking"])

if recruitment_router is not None and public_router is not None:
    app.include_router(recruitment_router)
    app.include_router(public_router)

# ── Document routers ───────────────────────────────────────────────────────────
app.include_router(documents_router,        tags=["Employee Documents"])
app.include_router(approval_router,         tags=["Document Approval"])
app.include_router(request_router,          tags=["Document Requests"])
app.include_router(hr_request_router,       tags=["HR Document Requests"])
app.include_router(template_router,         tags=["Document Templates"])
app.include_router(document_type_router,    tags=["Document Types"])
app.include_router(promotion_letter_router, tags=["Promotion Letters"])
app.include_router(employee_docs_router,    tags=["Employee Documents Browser"])

# ── Static file uploads (Local Only) ───────────────────────────────────────────
from app.core.config import STORAGE_BACKEND


class SecureStaticFiles(StaticFiles):
    """StaticFiles that never lets an upload execute as active content.

    Upload validation already rejects HTML/SVG/executables, but this is a cheap
    second layer: `nosniff` stops the browser MIME-sniffing a file into HTML,
    and the sandbox CSP neutralizes scripts if such a file is ever navigated to
    directly. Both are inert for images loaded via <img>, so avatars still show.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


if STORAGE_BACKEND != "s3":
    os.makedirs("uploads/profiles", exist_ok=True)
    os.makedirs("uploads/documents", exist_ok=True)
    os.makedirs("uploads/templates", exist_ok=True)
    os.makedirs("uploads/generated_documents", exist_ok=True)
    app.mount("/uploads", SecureStaticFiles(directory="uploads"), name="uploads")

# ── Root ───────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "HRM System API v2.0 — Role-based permissions active"}
