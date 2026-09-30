from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Any, Optional


class DashboardLayoutResponse(BaseModel):
    widgets: List[Dict[str, Any]]
    role: Optional[str] = None
    allowed_widgets: Optional[List[str]] = None


class WidgetPosition(BaseModel):
    """One react-grid-layout item. Unknown keys are dropped, not stored."""
    model_config = ConfigDict(extra="ignore")

    i: str = Field(..., min_length=1, max_length=50)
    x: int = Field(..., ge=0, le=100)
    y: int = Field(..., ge=0, le=1000)
    w: int = Field(..., ge=1, le=12)
    h: int = Field(..., ge=1, le=50)


class DashboardLayoutUpdate(BaseModel):
    widgets: List[WidgetPosition] = Field(..., max_length=50)
