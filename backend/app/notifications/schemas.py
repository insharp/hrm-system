from pydantic import BaseModel, Field, field_validator
from typing import List, Literal, Optional
from datetime import datetime


class NotificationCreate(BaseModel):
    user_id: int
    message: str = Field(..., min_length=1, max_length=500)
    type: Literal["info", "success", "warning", "error"] = "info"
    link: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=50)
    entity_type: Optional[str] = Field(default=None, max_length=50)
    entity_id: Optional[str] = Field(default=None, max_length=100)

    @field_validator("link")
    @classmethod
    def _in_app_link(cls, v):
        # Links are rendered as clickable in the bell/inbox — only allow paths
        # inside this app, never "https://evil…" or "javascript:" URLs.
        if v and (not v.startswith("/") or v.startswith("//")):
            raise ValueError("link must be an in-app path starting with '/'")
        return v


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    message: str
    type: str
    link: Optional[str] = None
    is_read: bool
    created_at: Optional[datetime] = None
    category: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    is_archived: bool = False
    is_deleted: bool = False

    class Config:
        from_attributes = True


class NotificationBulkAction(BaseModel):
    """
    Payload for bulk inbox actions (archive / delete / restore / read).

    ``ids`` is capped so a single request can't be used to scan the table.
    Only the caller's own notifications are ever touched — enforced in the router.

    An empty list is allowed and treated as a clean no-op by the router (rather
    than a noisy 422), while foreign/unknown ids are handled there too.
    """

    ids: List[int] = Field(default_factory=list, max_length=500)


class NotificationCounts(BaseModel):
    """Per-folder counts used to render the sidebar badges."""

    inbox: int
    unread: int
    archived: int
    trash: int
