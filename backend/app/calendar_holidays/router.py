from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database.database import get_db, SessionLocal
from app.core.deps import get_current_user, require_permission
from app.auth.models import User
from app.calendar_holidays.models import Holiday
from app.calendar_holidays.schemas import HolidayCreate, HolidayResponse
from sqlalchemy import text, func

router = APIRouter()

HOLIDAYS_TO_SEED = [
    # 2025
    {"name": "Thai Pongal", "date": "2025-01-14"},
    {"name": "National Day", "date": "2025-02-04"},
    {"name": "Maha Sivarathri Day", "date": "2025-02-26"},
    {"name": "Eid ul Fitr", "date": "2025-03-31"},
    {"name": "Day prior to Sinhala & Tamil New Year", "date": "2025-04-13"},
    {"name": "Sinhala & Tamil New Year", "date": "2025-04-14"},
    {"name": "Good Friday", "date": "2025-04-18"},
    {"name": "May Day", "date": "2025-05-01"},
    {"name": "Vesak Full Moon Poya", "date": "2025-05-12"},
    {"name": "Day following Vesak Full Moon Poya", "date": "2025-05-13"},
    {"name": "Poson Full Moon Poya", "date": "2025-06-11"},
    {"name": "Esala Full Moon Poya", "date": "2025-07-10"},
    {"name": "Nikini Full Moon Poya", "date": "2025-08-09"},
    {"name": "Milad un Nabi", "date": "2025-09-05"},
    {"name": "Binara Full Moon Poya", "date": "2025-09-07"},
    {"name": "Vap Full Moon Poya", "date": "2025-10-06"},
    {"name": "Deepavali", "date": "2025-10-20"},
    {"name": "Il Full Moon Poya", "date": "2025-11-05"},
    {"name": "Unduvap Full Moon Poya", "date": "2025-12-04"},
    {"name": "Christmas Day", "date": "2025-12-25"},
    # 2026
    {"name": "Thai Pongal", "date": "2026-01-14"},
    {"name": "National Day", "date": "2026-02-04"},
    {"name": "Maha Sivarathri Day", "date": "2026-02-15"},
    {"name": "Eid ul Fitr", "date": "2026-03-20"},
    {"name": "Good Friday", "date": "2026-04-03"},
    {"name": "Day prior to Sinhala & Tamil New Year", "date": "2026-04-13"},
    {"name": "Sinhala & Tamil New Year", "date": "2026-04-14"},
    {"name": "May Day", "date": "2026-05-01"},
    {"name": "Vesak Full Moon Poya", "date": "2026-05-01"},
    {"name": "Day following Vesak Full Moon Poya", "date": "2026-05-02"},
    {"name": "Poson Full Moon Poya", "date": "2026-05-31"},
    {"name": "Esala Full Moon Poya", "date": "2026-06-30"},
    {"name": "Nikini Full Moon Poya", "date": "2026-07-29"},
    {"name": "Binara Full Moon Poya", "date": "2026-08-28"},
    {"name": "Milad un Nabi", "date": "2026-08-27"},
    {"name": "Vap Full Moon Poya", "date": "2026-09-26"},
    {"name": "Deepavali", "date": "2026-11-08"},
    {"name": "Il Full Moon Poya", "date": "2026-10-26"},
    {"name": "Unduvap Full Moon Poya", "date": "2026-11-24"},
    {"name": "Christmas Day", "date": "2026-12-25"},
]

def seed_holidays():
    db = SessionLocal()
    try:
        if db.query(Holiday).count() == 0:
            for h in HOLIDAYS_TO_SEED:
                db.add(Holiday(name=h["name"], date=h["date"], is_mercantile=True))
            db.commit()
    finally:
        db.close()

@router.get("", response_model=List[HolidayResponse])
def get_holidays(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Holiday).order_by(Holiday.date).all()

def _reject_duplicate(db: Session, data: HolidayCreate, exclude_id: int = None) -> None:
    """The same holiday twice on one date would double-count in the calendar."""
    q = db.query(Holiday).filter(Holiday.date == data.date, func.lower(Holiday.name) == data.name.lower())
    if exclude_id is not None:
        q = q.filter(Holiday.id != exclude_id)
    if q.first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This holiday already exists on that date")


@router.post("", response_model=HolidayResponse)
def add_holiday(data: HolidayCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("widget.calendar.edit"))):
    _reject_duplicate(db, data)
    holiday = Holiday(name=data.name, date=data.date, is_mercantile=data.is_mercantile, created_by=current_user.id)
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday

@router.put("/{holiday_id}", response_model=HolidayResponse)
def update_holiday(holiday_id: int, data: HolidayCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("widget.calendar.edit"))):
    holiday = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    _reject_duplicate(db, data, exclude_id=holiday_id)
    holiday.name = data.name
    holiday.date = data.date
    holiday.is_mercantile = data.is_mercantile
    db.commit()
    db.refresh(holiday)
    return holiday

@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("widget.calendar.edit"))):
    holiday = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    db.delete(holiday)
    db.commit()
    return {"message": "Deleted"}
