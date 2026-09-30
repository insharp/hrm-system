from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime

TITLE_MAX = 200
CONTENT_MAX = 5000


def _required_text(v, label):
    if v is None or not v.strip():
        raise ValueError(f"{label} cannot be empty")
    return v.strip()


class AnnouncementBase(BaseModel):
    title: str
    content: str


class AnnouncementCreate(AnnouncementBase):
    title: str = Field(..., max_length=TITLE_MAX)
    content: str = Field(..., max_length=CONTENT_MAX)

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return _required_text(v, "Title")

    @field_validator("content")
    @classmethod
    def _content(cls, v):
        return _required_text(v, "Content")


class AnnouncementUpdate(BaseModel):
    # Omit a field to leave it unchanged; sending it blank is an error.
    title: Optional[str] = Field(default=None, max_length=TITLE_MAX)
    content: Optional[str] = Field(default=None, max_length=CONTENT_MAX)

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return None if v is None else _required_text(v, "Title")

    @field_validator("content")
    @classmethod
    def _content(cls, v):
        return None if v is None else _required_text(v, "Content")


class AnnouncementResponse(AnnouncementBase):
    id: int
    created_by: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
