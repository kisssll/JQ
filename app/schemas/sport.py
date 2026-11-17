from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class SportOrganizationResponse(BaseModel):
    slug: str
    name: str
    city: str
    description: str
    logo_url: Optional[str] = None


class SportTrainingResponse(BaseModel):
    id: str
    days: list[int]
    time: str
    end: str
    coach: str
    gym: str
    discipline: str
    active: bool


class SportScheduleResponse(BaseModel):
    organization: SportOrganizationResponse
    trainings: list[SportTrainingResponse]
    exceptions: dict[str, bool]


class SportBookingCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=10, max_length=24)
    email: Optional[EmailStr] = None
    experience: Optional[str] = Field(default=None, max_length=80)
    kind: Literal["Пробное", "Обычное"]
    participant: Literal["self", "child"]
    child_name: Optional[str] = Field(default=None, max_length=100)
    child_age: Optional[int] = Field(default=None, ge=5, le=17)
    training_id: Optional[str] = Field(default=None, max_length=64)
    booking_date: Optional[date] = None
    gym: str = Field(min_length=2, max_length=200)
    discipline: str = Field(min_length=2, max_length=120)
    pd_consent: bool
    consent_version: str = Field(min_length=1, max_length=32)

    @field_validator("name", "gym", "discipline", mode="before")
    @classmethod
    def _trim_required_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone", mode="before")
    @classmethod
    def _trim_phone(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def _trim_email(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_participant(self):
        if self.participant == "child" and (not self.child_name or self.child_age is None):
            raise ValueError("Для записи ребёнка укажите имя и возраст")
        if self.participant == "self" and (self.child_name or self.child_age is not None):
            raise ValueError("Данные ребёнка допустимы только при записи ребёнка")
        if (self.training_id is None) != (self.booking_date is None):
            raise ValueError("Для записи на тренировку выберите и дату, и занятие")
        if not self.pd_consent:
            raise ValueError("Необходимо согласие на обработку персональных данных")
        return self
