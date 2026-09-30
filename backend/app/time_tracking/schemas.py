from pydantic import BaseModel, Field, StrictFloat, StrictInt
from typing import Optional, List
from datetime import datetime


class CheckPairResponse(BaseModel):
    """One check-in / check-out segment within a day."""
    id: int
    check_in: datetime
    check_out: Optional[datetime] = None
    seconds: Optional[int] = None

    class Config:
        from_attributes = True


class DayEntryResponse(BaseModel):
    """Per-day summary with nested check-in/check-out pairs."""
    date: str                                    # YYYY-MM-DD
    total_hours: Optional[float] = None
    overtime: Optional[float] = None
    status: str = "active"                       # "active" | "paused" | "completed"
    pairs: List[CheckPairResponse] = []

    class Config:
        from_attributes = True


# --- Legacy-compatible flat response (kept for backward compat aliases) ---

class TimeEntryResponse(BaseModel):
    id: int
    user_id: int
    employee_id: Optional[str] = None
    clock_in: datetime                         # mapped from start_time
    clock_out: Optional[datetime] = None       # mapped from end_time
    total_hours: Optional[float] = None        # decimal hours e.g. 8.75
    overtime: Optional[float] = None           # hours beyond threshold, 0 if under
    status: str = "active"                     # "active" | "paused" | "completed"
    work_date: Optional[str] = None            # mapped from date (YYYY-MM-DD)

    class Config:
        from_attributes = True


class ClockStatusResponse(BaseModel):
    active: bool
    paused: bool = False                       # True when day is active but no open pair
    completed: bool = False                    # True when the work day has ended
    clock_in: Optional[datetime] = None        # UTC timestamp of the current open pair's check-in
    elapsed_seconds: int = 0                   # accumulated worked seconds from completed pairs
    entry_id: Optional[int] = None


class WeeklyStatsResponse(BaseModel):
    week_start: str                            # YYYY-MM-DD
    week_end: str
    total_hours: float
    regular_hours: float                       # total - overtime
    overtime_hours: float
    overtime_threshold: float = 8.0            # current effective threshold
    entries: List[DayEntryResponse] = []       # day-grouped


class OvertimeThresholdUpdate(BaseModel):
    # Strict types: plain bool/str ("8") are rejected instead of coerced
    # (True used to be accepted as 1 hour).
    threshold_hours: StrictFloat | StrictInt = Field(..., gt=0, le=24)


class OvertimeThresholdResponse(BaseModel):
    threshold_hours: float
    effective_date: str


class AllAttendanceItemResponse(BaseModel):
    user_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    employee_id: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    total_hours: float
    overtime: float

    class Config:
        from_attributes = True


class AllAttendanceResponse(BaseModel):
    period: str
    start_date: str
    end_date: str
    items: List[AllAttendanceItemResponse]
