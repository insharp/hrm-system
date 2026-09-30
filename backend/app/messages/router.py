from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.database.database import get_db
from app.core.deps import get_current_user, get_user_permissions, require_permission, require_any_permission
from app.auth.models import User
from app.roles.models import Role
from app.messages import models, schemas

router = APIRouter()

# Inbox access — anyone who can receive messages
can_receive = require_permission("messaging.receive")
# Trash/delete/restore touch both inbox copies and sent copies
can_message = require_any_permission("messaging.receive", "messaging.send")


# ── POST send message ───────────────────────────────────────────────────────────
@router.post("/", response_model=schemas.MessageResponse)
def send_message(
    message: schemas.MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send a new message to a target group (All, All Employees, HR, or a department).
    Requires the 'messaging.send' permission.
    Creates a Message record and one MessageRecipient row per recipient,
    skipping the sender themselves.
    """
    # Dynamic Permission Check
    permissions = get_user_permissions(current_user, db)
    if "messaging.send" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to send messages"
        )

    # Determine recipients based on target_group — BEFORE saving anything, so a
    # message that would reach nobody is refused instead of silently vanishing.
    recipients_query = db.query(User.id).filter(User.id != current_user.id)
    if message.target_group == "All":
        pass  # All users
    elif message.target_group == "All Employees":
        # Dynamically filter users who have the "Employee" role
        recipients_query = recipients_query.filter(User.roles.any(Role.role_name == "Employee"))
    elif message.target_group in ("HR", "HR Manager"):
        # Dynamically filter users who have the "HR" role
        recipients_query = recipients_query.filter(User.roles.any(Role.role_name == "HR"))
    else:
        from app.departments.models import Department
        if not db.query(Department.id).filter(Department.name == message.target_group).first():
            # Only the built-in groups and real departments can be delivered
            # to (custom message groups were removed — they had no members).
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{message.target_group}' is not a group messages can be delivered to.",
            )
        recipients_query = recipients_query.filter(User.department == message.target_group)

    recipient_ids = [uid for (uid,) in recipients_query.filter(
        (User.is_active == True) | (User.is_active.is_(None))
    ).all()]
    if not recipient_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nobody is in the selected group yet, so the message was not sent.",
        )

    # Message + all recipient rows commit together (no orphan messages).
    db_message = models.Message(
        sender_id=current_user.id,
        subject=message.subject,
        content=message.content,
        target_group=message.target_group,
    )
    db.add(db_message)
    db.flush()
    db.add_all(
        models.MessageRecipient(message_id=db_message.id, recipient_id=uid)
        for uid in recipient_ids
    )
    db.commit()
    db.refresh(db_message)
    
    return {
        "id": db_message.id,
        "sender_id": db_message.sender_id,
        "subject": db_message.subject,
        "content": db_message.content,
        "target_group": db_message.target_group,
        "created_at": db_message.created_at,
        "sender_name": f"{current_user.first_name} {current_user.last_name}".strip() or current_user.email,
        "is_read": False,
        "is_deleted": False,
        "sender_deleted": db_message.sender_deleted
    }


# ── GET inbox ───────────────────────────────────────────────────────────────────
@router.get("/inbox", response_model=List[schemas.MessageResponse])
def get_inbox(
    db: Session = Depends(get_db),
    current_user: User = Depends(can_receive),
):
    """
    Return all non-deleted inbox messages for the current user,
    ordered newest first. Joins Message, MessageRecipient, and sender User
    to build the full response shape.
    """
    results = (
        db.query(models.Message, models.MessageRecipient, User)
        .join(models.MessageRecipient, models.Message.id == models.MessageRecipient.message_id)
        .join(User, models.Message.sender_id == User.id)
        .filter(
            models.MessageRecipient.recipient_id == current_user.id,
            models.MessageRecipient.is_deleted == False,
            models.MessageRecipient.is_permanent_deleted == False
        )
        .order_by(models.Message.created_at.desc())
        .all()
    )

    messages = []
    for msg, rec, sender in results:
        messages.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "subject": msg.subject,
            "content": msg.content,
            "target_group": msg.target_group,
            "created_at": msg.created_at,
            "sender_name": f"{sender.first_name} {sender.last_name}".strip() or sender.email,
            "is_read": rec.is_read,
            "is_deleted": rec.is_deleted,
            "sender_deleted": msg.sender_deleted
        })
    return messages


# ── GET sent ────────────────────────────────────────────────────────────────────
@router.get("/sent", response_model=List[schemas.MessageResponse])
def get_sent(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all non-deleted sent messages for the current user.
    Only accessible to users with the 'messaging.send' permission,
    since only those users can originate messages.
    """
    # Only users with messaging.send permission have a sent box
    permissions = get_user_permissions(current_user, db)
    if "messaging.send" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access the sent box"
        )

    results = (
        db.query(models.Message)
        .filter(
            models.Message.sender_id == current_user.id,
            models.Message.sender_deleted == False,
            models.Message.sender_permanent_deleted == False
        )
        .order_by(models.Message.created_at.desc())
        .all()
    )
    
    messages = []
    for msg in results:
        messages.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "subject": msg.subject,
            "content": msg.content,
            "target_group": msg.target_group,
            "created_at": msg.created_at,
            "sender_name": "Me",
            "is_read": True,
            "is_deleted": False,
            "sender_deleted": msg.sender_deleted
        })
    return messages


# ── GET trash ───────────────────────────────────────────────────────────────────
@router.get("/trash", response_model=List[schemas.MessageResponse])
def get_trash(
    db: Session = Depends(get_db),
    current_user: User = Depends(can_message),
):
    """
    Return all soft-deleted (but not permanently deleted) messages for the current user.
    Combines inbox trash and sent trash into a single list sorted by date descending.
    """
    # Inbox trash
    inbox_trash = (
        db.query(models.Message, models.MessageRecipient, User)
        .join(models.MessageRecipient, models.Message.id == models.MessageRecipient.message_id)
        .join(User, models.Message.sender_id == User.id)
        .filter(
            models.MessageRecipient.recipient_id == current_user.id,
            models.MessageRecipient.is_deleted == True,
            models.MessageRecipient.is_permanent_deleted == False
        )
        .all()
    )

    # Sent trash
    sent_trash = (
        db.query(models.Message)
        .filter(
            models.Message.sender_id == current_user.id,
            models.Message.sender_deleted == True,
            models.Message.sender_permanent_deleted == False
        )
        .all()
    )

    messages = []
    for msg, rec, sender in inbox_trash:
        messages.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "subject": msg.subject,
            "content": msg.content,
            "target_group": msg.target_group,
            "created_at": msg.created_at,
            "sender_name": f"{sender.first_name} {sender.last_name}".strip() or sender.email,
            "is_read": rec.is_read,
            "is_deleted": rec.is_deleted,
            "sender_deleted": msg.sender_deleted
        })
    
    for msg in sent_trash:
        messages.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "subject": msg.subject,
            "content": msg.content,
            "target_group": msg.target_group,
            "created_at": msg.created_at,
            "sender_name": "Me",
            "is_read": True,
            "is_deleted": True,
            "sender_deleted": True
        })
    
    return sorted(messages, key=lambda x: x["created_at"], reverse=True)


# ── PUT delete (soft delete) ─────────────────────────────────────────────────────
@router.put("/{message_id}/delete")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(can_message),
):
    """
    Soft-delete a message by moving it to trash.
    Handles both inbox messages (sets MessageRecipient.is_deleted)
    and sent messages (sets Message.sender_deleted).
    Returns 404 if the message is not found for the current user.
    """
    # Check if in inbox
    recipient_rec = db.query(models.MessageRecipient).filter(
        models.MessageRecipient.message_id == message_id,
        models.MessageRecipient.recipient_id == current_user.id
    ).first()

    if recipient_rec:
        recipient_rec.is_deleted = True
        recipient_rec.deleted_at = datetime.now(timezone.utc)
    
    # Check if in sent
    message_rec = db.query(models.Message).filter(
        models.Message.id == message_id,
        models.Message.sender_id == current_user.id
    ).first()

    if message_rec:
        message_rec.sender_deleted = True

    if not recipient_rec and not message_rec:
        raise HTTPException(status_code=404, detail="Message not found")

    db.commit()
    return {"message": "Message moved to trash"}


# ── PUT restore ─────────────────────────────────────────────────────────────────
@router.put("/{message_id}/restore")
def restore_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(can_message),
):
    """
    Restore a soft-deleted message from trash back to its original folder.
    Clears is_deleted / sender_deleted flags accordingly.
    """
    recipient_rec = db.query(models.MessageRecipient).filter(
        models.MessageRecipient.message_id == message_id,
        models.MessageRecipient.recipient_id == current_user.id
    ).first()

    if recipient_rec:
        recipient_rec.is_deleted = False
        recipient_rec.deleted_at = None
    
    message_rec = db.query(models.Message).filter(
        models.Message.id == message_id,
        models.Message.sender_id == current_user.id
    ).first()

    if message_rec:
        message_rec.sender_deleted = False

    if not recipient_rec and not message_rec:
        raise HTTPException(status_code=404, detail="Message not found")

    db.commit()
    return {"message": "Message restored"}


# ── DELETE permanent ────────────────────────────────────────────────────────────
@router.delete("/{message_id}/permanent")
def permanent_delete(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(can_message),
):
    """
    Permanently delete a message that is already in the trash.
    Sets is_permanent_deleted / sender_permanent_deleted so it no longer
    appears in trash queries. The message row itself is kept for audit purposes.
    Returns 404 if the message is not found in the user's trash.
    """
    # Inbox permanent delete
    recipient_rec = db.query(models.MessageRecipient).filter(
        models.MessageRecipient.message_id == message_id,
        models.MessageRecipient.recipient_id == current_user.id,
        models.MessageRecipient.is_deleted == True
    ).first()

    if recipient_rec:
        recipient_rec.is_permanent_deleted = True
        db.commit()
        return {"message": "Message permanently deleted from inbox"}
    
    # Sent permanent delete
    message_rec = db.query(models.Message).filter(
        models.Message.id == message_id,
        models.Message.sender_id == current_user.id,
        models.Message.sender_deleted == True
    ).first()

    if message_rec:
        message_rec.sender_permanent_deleted = True
        db.commit()
        return {"message": "Message permanently deleted from sent"}
    
    raise HTTPException(status_code=404, detail="Message not found in trash")


# ── PUT read ────────────────────────────────────────────────────────────────────
@router.put("/{message_id}/read")
def mark_read(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(can_receive),
):
    """
    Mark an inbox message as read for the current user.
    Updates the MessageRecipient.is_read flag.
    Returns 404 if the message is not found in the user's inbox.
    """
    recipient_rec = db.query(models.MessageRecipient).filter(
        models.MessageRecipient.message_id == message_id,
        models.MessageRecipient.recipient_id == current_user.id
    ).first()

    if not recipient_rec:
        raise HTTPException(status_code=404, detail="Message not found in inbox")

    recipient_rec.is_read = True
    db.commit()
    return {"message": "Message marked as read"}
