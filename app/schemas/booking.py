# app/schemas/booking.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.models import BookingStatus

class BookingCreate(BaseModel):
    master_id: int
    service_id: int
    start_time: datetime

class BookingResponse(BaseModel):
    id: int
    client_id: int
    master_id: int
    service_id: int
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    discount_percent: int = 0
    final_price: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class BookingCancel(BaseModel):
    reason: Optional[str] = None