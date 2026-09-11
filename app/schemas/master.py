# app/schemas/master.py
from pydantic import BaseModel
from typing import Optional, List
from app.schemas.user import UserResponse

class ServiceResponse(BaseModel):
    id: int
    name: str
    price: int
    duration_minutes: int
    price_max: Optional[int] = None
    description: Optional[str] = None
    
    class Config:
        from_attributes = True

class MasterBase(BaseModel):
    specialization: str
    experience_years: int
    bio: Optional[str] = None

class MasterCreate(MasterBase):
    user_id: int
    salon_id: int

class MasterResponse(MasterBase):
    id: int
    user: Optional[UserResponse] = None
    salon_id: int
    rating: float
    photo_url: Optional[str] = None
    services: List[ServiceResponse] = []
    is_active: bool
    
    class Config:
        from_attributes = True