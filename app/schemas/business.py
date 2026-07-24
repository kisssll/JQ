# app/schemas/business.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class SalonUpdateRequest(BaseModel):
    """Данные, которые владелец может изменить в своём салоне."""
    name: Optional[str] = None
    description: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    working_hours: Optional[str] = None  # JSON-строка с графиком
    photos: Optional[List[str]] = None   # Список URL всех фото
    logo_url: Optional[str] = None       # URL обложки

class SalonPhotoResponse(BaseModel):
    id: int
    url: str

    class Config:
        from_attributes = True

class SalonResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    address: str
    phone: str
    logo_url: Optional[str] = None
    rating: float
    reviews_count: int
    working_hours: Optional[str] = None
    photos: List[SalonPhotoResponse] = []

    class Config:
        from_attributes = True

class MasterResponse(BaseModel):
    id: int
    specialization: str
    experience_years: int
    rating: float
    photo_url: Optional[str] = None

    class Config:
        from_attributes = True

class ServiceResponse(BaseModel):
    id: int
    name: str
    price: int
    duration_minutes: int

    class Config:
        from_attributes = True

class PromotionResponse(BaseModel):
    title: str
    description: Optional[str] = None
    tag: str
    is_active: bool = True

    class Config:
        from_attributes = True