from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from datetime import datetime, timezone
from app.database.base import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    target_group = Column(String, nullable=True)
    sender_deleted = Column(Boolean, default=False)
    sender_permanent_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class MessageRecipient(Base):
    __tablename__ = "message_recipients"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_read = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    is_permanent_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)


class MessageGroup(Base):
    """
    Legacy: custom messaging groups (superadmin-created). The feature was
    removed because groups never had members, so messages sent to one
    reached nobody. The model is kept only so the existing message_groups
    table and its migrations stay untouched; nothing reads or writes it.
    """
    __tablename__ = "message_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

