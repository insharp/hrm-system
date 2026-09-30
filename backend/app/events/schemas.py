from pydantic import BaseModel, Field, field_serializer, field_validator
from typing import Optional
from datetime import datetime

from app.core.app_time import to_utc_naive


def _clean_optional(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class EventCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    event_date: datetime
    location: Optional[str] = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Title is required")
        return v

    _clean = field_validator("description", "location", mode="before")(_clean_optional)

    @field_validator("event_date")
    @classmethod
    def _utc(cls, v):
        # Stored as naive UTC (compared against utcnow() everywhere).
        return to_utc_naive(v)


class EventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    event_date: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        # title/event_date are NOT NULL columns: an explicit null must be a 422,
        # not a database error.
        if v is None or not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()

    _clean = field_validator("description", "location", mode="before")(_clean_optional)

    @field_validator("event_date")
    @classmethod
    def _utc(cls, v):
        if v is None:
            raise ValueError("Event date cannot be empty")
        return to_utc_naive(v)


class EventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    event_date: datetime
    location: Optional[str] = None
    created_by: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_serializer("event_date")
    def _as_utc(self, v: datetime) -> str:
        # Mark the stored naive-UTC value as UTC ("…Z") so every client converts
        # it to the viewer's local time the same way.
        return v.replace(tzinfo=None).isoformat() + "Z"


class EventWithStatus(EventResponse):
    is_saved: bool = False
