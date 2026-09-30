from datetime import date
from pydantic import BaseModel, Field, field_validator
from typing import Optional

class HolidayCreate(BaseModel):
    name: str = Field(..., max_length=100)
    # Kept as a "YYYY-MM-DD" string (that's the column type, and leave
    # calculations compare it lexically), but it must be a REAL date.
    date: str
    is_mercantile: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Holiday name is required")
        return v

    @field_validator("date")
    @classmethod
    def _date(cls, v):
        try:
            d = date.fromisoformat(v.strip())
        except (ValueError, AttributeError):
            raise ValueError("Date must be a valid date in YYYY-MM-DD format")
        if not 2000 <= d.year <= 2100:
            raise ValueError("Date must be between the years 2000 and 2100")
        return d.isoformat()

class HolidayResponse(BaseModel):
    id: int
    name: str
    date: str
    is_mercantile: bool

    class Config:
        from_attributes = True
