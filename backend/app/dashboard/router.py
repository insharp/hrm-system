from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.database.database import get_db
from app.core.deps import get_current_user, get_user_permissions
from app.auth.models import User
from app.dashboard.schemas import DashboardLayoutResponse, DashboardLayoutUpdate
from app.dashboard.service import get_layout, save_layout

router = APIRouter()

# ── Permission → widget key mapping ────────────────────────────────────────────
# A user sees a widget if they hold the corresponding view permission.
# Super Admins receive ALL permissions via get_user_permissions() in core/deps.py,
# so they automatically get every widget — no role name needed here.
PERMISSION_WIDGET_MAP: Dict[str, str] = {
    "widget.time_tracking.view":              "time_tracking",
    "widget.leave_balance.view":              "leave_balance",
    "widget.notifications.view":              "notifications",
    "widget.attendance.view":                 "weekly_hours",
    "widget.calendar.view":                   "calendar",
    "widget.approval_summary.view_approvals": "approval_summary",
    "widget.approval_summary.view_requests":  "approval_summary",
    "widget.announcements.view":              "announcements",
    "widget.upcoming_events.view":            "upcoming_events",
}

DEFAULT_LAYOUT = [
    {"i": "time_tracking",    "x": 0, "y": 0, "w": 4, "h": 3},
    {"i": "leave_balance",    "x": 4, "y": 0, "w": 4, "h": 3},
    {"i": "notifications",    "x": 8, "y": 0, "w": 4, "h": 3},
    {"i": "weekly_hours",     "x": 0, "y": 3, "w": 4, "h": 3},
    {"i": "calendar",         "x": 4, "y": 3, "w": 4, "h": 3},
    {"i": "approval_summary", "x": 8, "y": 3, "w": 4, "h": 3},
    {"i": "announcements",    "x": 0, "y": 6, "w": 4, "h": 3},
    {"i": "upcoming_events",  "x": 4, "y": 6, "w": 4, "h": 3},
]


def _allowed_widgets_from_permissions(permissions: List[str]) -> List[str]:
    """Return deduplicated widget keys the user can see, derived purely from permissions."""
    seen: set = set()
    result: List[str] = []
    for perm in permissions:
        widget_key = PERMISSION_WIDGET_MAP.get(perm)
        if widget_key and widget_key not in seen:
            seen.add(widget_key)
            result.append(widget_key)
    return result


# ── GET layout ─────────────────────────────────────────────────────────────────
@router.get("/layout", response_model=DashboardLayoutResponse)
def get_dashboard_layout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permissions = get_user_permissions(current_user, db)
    allowed = _allowed_widgets_from_permissions(permissions)
    saved = get_layout(db, current_user.id)

    if saved:
        filtered = [w for w in saved if w.get("i") in allowed]
    else:
        filtered = [w for w in DEFAULT_LAYOUT if w["i"] in allowed]

    return {"widgets": filtered, "role": current_user.role, "allowed_widgets": allowed}


# ── POST / save layout ─────────────────────────────────────────────────────────
@router.post("/layout", response_model=DashboardLayoutResponse)
def update_dashboard_layout(
    data: DashboardLayoutUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permissions = get_user_permissions(current_user, db)
    allowed = _allowed_widgets_from_permissions(permissions)
    # Only persist widgets the user is actually allowed to have
    safe_widgets = [w.model_dump() for w in data.widgets if w.i in allowed]
    saved = save_layout(db, current_user.id, safe_widgets)
    return {"widgets": saved, "role": current_user.role, "allowed_widgets": allowed}