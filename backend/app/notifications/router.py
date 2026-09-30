from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List, Optional
from datetime import datetime
import os
import hmac

from app.database.database import get_db
from app.core.deps import get_current_user
from app.auth.models import User
from app.notifications.models import Notification
from app.notifications.schemas import (
    NotificationCreate,
    NotificationResponse,
    NotificationBulkAction,
    NotificationCounts,
)

router = APIRouter()


def _owned(db: Session, user_id: int, ids: List[int]) -> List[Notification]:
    """
    Fetch the caller's own notifications by id.

    Scoping the query to user_id is what stops a caller from acting on someone
    else's notifications by guessing ids; unknown/foreign ids are silently
    dropped rather than raising, so a partially-stale client selection still
    applies to the rows it legitimately owns.
    """
    if not ids:
        return []
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.id.in_(ids))
        .all()
    )


def _targets_for_bulk(db: Session, user_id: int, ids: List[int]) -> List[Notification]:
    """
    Resolve the caller's own notifications for a bulk action, distinguishing
    the two "nothing to do" cases so the response is never misleading:

    - Empty id list → return [] so the endpoint is a clean no-op (200,
      ``updated: 0``) instead of a noisy 422 (TC-NOT-014).
    - Non-empty list but the caller owns none of the ids → 404. The ids are
      foreign, non-existent, or already purged; a blanket 200 would look like
      success the caller never earned (TC-NOT-013 cross-user read, TC-NOT-026
      restore-after-purge).
    - Otherwise → the owned rows. Foreign ids inside a mixed selection are still
      silently dropped so a partially-stale client selection keeps working.
    """
    if not ids:
        return []
    items = _owned(db, user_id, ids)
    if not items:
        raise HTTPException(status_code=404, detail="Notification(s) not found")
    return items


# ── GET my notifications ───────────────────────────────────────────────────────
@router.get("/", response_model=List[NotificationResponse])
def list_notifications(
    folder: str = Query("inbox", pattern="^(inbox|archived|trash|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the caller's notifications for one folder, newest first.

    Folders are mutually exclusive: trash wins over archived, so an archived
    item that is then deleted appears only in trash.
    """
    q = db.query(Notification).filter(Notification.user_id == current_user.id)

    if folder == "inbox":
        q = q.filter(Notification.is_deleted == False, Notification.is_archived == False)
    elif folder == "archived":
        q = q.filter(Notification.is_deleted == False, Notification.is_archived == True)
    elif folder == "trash":
        q = q.filter(Notification.is_deleted == True)
    # folder == "all" → no folder filter

    return q.order_by(Notification.created_at.desc()).all()


# ── GET recent notifications ──────────────────────────────────────────────────
@router.get("/recent", response_model=List[NotificationResponse])
def get_recent(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns 5 most recent inbox notifications for dashboard widget"""
    return (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_deleted == False,
            Notification.is_archived == False,
        )
        .order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )


# ── GET unread count ──────────────────────────────────────────────────────────
@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Unread count for the bell badge.

    Archived and trashed items never count toward the badge — the user has
    already dealt with them.
    """
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
            Notification.is_deleted == False,
            Notification.is_archived == False,
        )
        .count()
    )
    return {"count": count}


# ── GET per-folder counts ─────────────────────────────────────────────────────
@router.get("/counts", response_model=NotificationCounts)
def get_counts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Counts for each folder tab, computed in a single pass over the user's rows."""
    in_inbox = (Notification.is_deleted == False) & (Notification.is_archived == False)

    row = (
        db.query(
            func.coalesce(func.sum(case((in_inbox, 1), else_=0)), 0).label("inbox"),
            func.coalesce(
                func.sum(case((in_inbox & (Notification.is_read == False), 1), else_=0)), 0
            ).label("unread"),
            func.coalesce(
                func.sum(case(
                    ((Notification.is_deleted == False) & (Notification.is_archived == True), 1),
                    else_=0,
                )), 0
            ).label("archived"),
            func.coalesce(
                func.sum(case((Notification.is_deleted == True, 1), else_=0)), 0
            ).label("trash"),
        )
        .filter(Notification.user_id == current_user.id)
        .one()
    )
    return NotificationCounts(
        inbox=row.inbox or 0,
        unread=row.unread or 0,
        archived=row.archived or 0,
        trash=row.trash or 0,
    )


# ── PUT mark single notification as read ──────────────────────────────────────
@router.put("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


# ── PUT mark ALL notifications as read ────────────────────────────────────────
@router.put("/read-all", status_code=status.HTTP_200_OK)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Scoped to the inbox — "mark all read" should not resurrect or alter
    # anything the user already archived or deleted.
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
        Notification.is_deleted == False,
        Notification.is_archived == False,
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}


# ── Bulk inbox actions ────────────────────────────────────────────────────────
# Declared before "/{notification_id}/..." so the literal "bulk" segment always
# wins the route match.

@router.post("/bulk/read", status_code=status.HTTP_200_OK)
def bulk_mark_read(
    data: NotificationBulkAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark the selected notifications as read."""
    items = _targets_for_bulk(db, current_user.id, data.ids)
    for n in items:
        n.is_read = True
    db.commit()
    return {"updated": len(items)}


@router.post("/bulk/unread", status_code=status.HTTP_200_OK)
def bulk_mark_unread(
    data: NotificationBulkAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark the selected notifications as unread."""
    items = _targets_for_bulk(db, current_user.id, data.ids)
    for n in items:
        n.is_read = False
    db.commit()
    return {"updated": len(items)}


@router.post("/bulk/archive", status_code=status.HTTP_200_OK)
def bulk_archive(
    data: NotificationBulkAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Move the selected notifications to Archived.

    Archiving also marks them read: an archived item is one the user has
    consciously filed away, so leaving it bolded in the badge would be wrong.
    """
    items = _targets_for_bulk(db, current_user.id, data.ids)
    now = datetime.utcnow()
    for n in items:
        n.is_archived = True
        n.archived_at = now
        n.is_read = True
    db.commit()
    return {"updated": len(items)}


@router.post("/bulk/unarchive", status_code=status.HTTP_200_OK)
def bulk_unarchive(
    data: NotificationBulkAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move the selected notifications from Archived back to Inbox."""
    items = _targets_for_bulk(db, current_user.id, data.ids)
    for n in items:
        n.is_archived = False
        n.archived_at = None
    db.commit()
    return {"updated": len(items)}


@router.post("/bulk/delete", status_code=status.HTTP_200_OK)
def bulk_delete(
    data: NotificationBulkAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Move the selected notifications to Trash (soft delete — restorable).

    Rows are kept so the user can restore them; the retention purge is what
    removes them for good.
    """
    items = _targets_for_bulk(db, current_user.id, data.ids)
    now = datetime.utcnow()
    for n in items:
        n.is_deleted = True
        n.deleted_at = now
    db.commit()
    return {"updated": len(items)}


@router.post("/bulk/restore", status_code=status.HTTP_200_OK)
def bulk_restore(
    data: NotificationBulkAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Restore the selected notifications from Trash.

    Restores to Inbox rather than back to Archived — the user is pulling the
    item back to act on it, so surfacing it is the useful behaviour.
    """
    items = _targets_for_bulk(db, current_user.id, data.ids)
    for n in items:
        n.is_deleted = False
        n.deleted_at = None
        n.is_archived = False
        n.archived_at = None
    db.commit()
    return {"updated": len(items)}


@router.post("/bulk/purge", status_code=status.HTTP_200_OK)
def bulk_purge(
    data: NotificationBulkAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Permanently delete the selected notifications. Cannot be undone.

    Only items already in Trash can be purged, so a stray call can never
    destroy something the user hasn't first deleted.
    """
    items = _targets_for_bulk(db, current_user.id, data.ids)
    purged = 0
    for n in items:
        if n.is_deleted:
            db.delete(n)
            purged += 1
    db.commit()
    return {"purged": purged}


@router.post("/trash/empty", status_code=status.HTTP_200_OK)
def empty_trash(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete everything in the caller's Trash. Cannot be undone."""
    purged = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_deleted == True)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"purged": purged}


# ── POST /internal — API Key required — for other modules to push notifications ──
@router.post("/internal", status_code=status.HTTP_201_CREATED)
def internal_push(
    data: NotificationCreate,
    db: Session = Depends(get_db),
    x_internal_key: Optional[str] = Header(None)
):
    """
    Internal endpoint for other modules to trigger notifications.
    Requires X-Internal-Key header.
    """
    # No built-in default: a key committed to the repo is public, and would let
    # anyone push official-looking notifications (with links) to any user.
    # Unset INTERNAL_API_KEY = endpoint disabled.
    internal_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_key:
        raise HTTPException(status_code=503, detail="Internal notifications are not configured")
    if not x_internal_key or not hmac.compare_digest(x_internal_key, internal_key):
        raise HTTPException(status_code=403, detail="Invalid internal key")
    if not db.query(User.id).filter(User.id == data.user_id).first():
        raise HTTPException(status_code=404, detail="User not found")

    notif = Notification(
        user_id=data.user_id,
        message=data.message,
        type=data.type,
        link=data.link,
        category=data.category,
        entity_type=data.entity_type,
        entity_id=data.entity_id,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return {"id": notif.id, "status": "delivered"}

