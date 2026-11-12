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
    rescheduled_count: int = 0
    created_at: datetime
    
    class Config:
        from_attributes = True

class BookingCancel(BaseModel):
    reason: Optional[str] = None

class BookingReschedule(BaseModel):
    """Новое начало записи — наивное время в зоне салона, как его отдаёт
    генератор свободных окон."""
    start_time: datetime


class RescheduleQuoteResponse(BaseModel):
    """Итог переноса до подтверждения: человек должен увидеть новую цену
    раньше, чем согласится (решение 0020, п. 9)."""
    start_time: datetime
    end_time: datetime
    final_price: Optional[int] = None
    old_price: Optional[int] = None
    price_changed: bool
