from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime

SUBJECT_MAX = 200
CONTENT_MAX = 10000


def _required(v: str, label: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{label} cannot be empty")
    return v


class MessageCreate(BaseModel):
    """Client only sends target_group, subject, content. Sender info comes from JWT."""
    target_group: str = Field(..., max_length=100)
    subject: str = Field(..., max_length=SUBJECT_MAX)
    content: str = Field(..., max_length=CONTENT_MAX)

    @field_validator("target_group")
    @classmethod
    def _target(cls, v):
        return _required(v, "Recipient group")

    @field_validator("subject")
    @classmethod
    def _subject(cls, v):
        return _required(v, "Subject")

    @field_validator("content")
    @classmethod
    def _content(cls, v):
        return _required(v, "Message")


class MessageUpdate(BaseModel):
    subject: str
    content: str


class MessageResponse(BaseModel):
    id: int
    sender_id: int
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    content: str
    target_group: Optional[str] = None
    is_read: bool = False
    is_deleted: bool = False
    sender_deleted: bool = False
    created_at: datetime

    class Config:
        from_attributes = True
