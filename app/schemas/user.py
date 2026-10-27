# app/schemas/user.py

import re
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime
from app.models.models import UserRole, SubscriptionTier

PHONE_RE = re.compile(r"^\+7\d{10}$")


def _normalize_phone(value: str) -> str:
    """Приводит телефон к формату +7XXXXXXXXXX, иначе ValueError."""
    digits = re.sub(r"[^\d+]", "", value or "")
    if digits.startswith("8") and len(digits) == 11:
        digits = "+7" + digits[1:]
    elif digits.startswith("7") and len(digits) == 11:
        digits = "+" + digits
    if not PHONE_RE.match(digits):
        raise ValueError("Телефон должен быть в формате +7XXXXXXXXXX")
    return digits


def try_normalize_phone(value: str) -> Optional[str]:
    """Нормализация без исключения: вернёт +7XXXXXXXXXX или None для веб-форм."""
    try:
        return _normalize_phone(value)
    except ValueError:
        return None


class UserBase(BaseModel):
    phone: str
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None


class SendCodeRequest(BaseModel):
    """Запрос кода подтверждения телефона перед регистрацией."""
    phone: str

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        return _normalize_phone(v)


class RegisterRequest(BaseModel):
    """Регистрация. Роль НЕ принимается от клиента — всегда CLIENT на сервере.

    request_id/code — результат SendCodeRequest, подтверждают, что телефон
    реально принадлежит пользователю (проверяются в app.services.otp).
    """
    phone: str
    password: str
    full_name: Optional[str] = None
    request_id: str
    code: str

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        return _normalize_phone(v)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, v: Optional[str]) -> Optional[str]:
        """Имя из одних пробелов — не имя: в базе оно выглядит как заполненное,
        а на экране пусто. Формы профиля его уже чистят, регистрация — нет."""
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned[:100] or None


class LoginRequest(BaseModel):
    phone: str
    password: str

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        return _normalize_phone(v)

class UserResponse(UserBase):
    id: int
    role: UserRole
    avatar_url: Optional[str] = None
    subscription_tier: Optional[SubscriptionTier] = None
    subscription_expires_at: Optional[datetime] = None
    created_at: datetime
    managed_salon_id: Optional[int] = None  # <-- Добавь эту строку
    
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    phone: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None
    portfolio_desc: Optional[str] = None