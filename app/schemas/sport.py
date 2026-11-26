from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator
from app.web.pages.legal import LEGAL_VERSION


class SportOrganizationResponse(BaseModel):
    slug: str
    name: str
    city: str
    description: str
    logo_url: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    cover_url: Optional[str] = None
    vk_url: Optional[str] = None
    telegram_url: Optional[str] = None


class SportTrainingResponse(BaseModel):
    id: str
    days: list[int]
    time: str
    end: str
    coach: str
    gym: str
    discipline: str
    active: bool
    color: str = "red"


class SportScheduleResponse(BaseModel):
    organization: SportOrganizationResponse
    trainings: list[SportTrainingResponse]
    exceptions: dict[str, bool]


class SportTrainingUpdate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    days: list[int] = Field(min_length=1, max_length=7)
    time: time
    end: time
    coach: str = Field(min_length=1, max_length=160)
    gym: str = Field(min_length=1, max_length=200)
    discipline: str = Field(min_length=1, max_length=120)
    active: bool
    color: str = Field(default="red", pattern=r"^(red|#[0-9a-fA-F]{6})$")

    @field_validator("days")
    @classmethod
    def _valid_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("Дни недели должны быть уникальными числами от 0 до 6")
        return value

    @field_validator("coach", "gym", "discipline", mode="before")
    @classmethod
    def _trim_schedule_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_time_range(self):
        if self.end <= self.time:
            raise ValueError("Время окончания должно быть позже времени начала")
        return self


class SportScheduleUpdate(BaseModel):
    trainings: list[SportTrainingUpdate] = Field(max_length=500)
    exceptions: dict[str, bool] = Field(default_factory=dict)


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
    statement_consent: bool = False
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


def _image_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if value.startswith(("/uploads/", "/photos/", "/static/")) and "\\" not in value:
        return value
    HttpUrl(value)
    return value


class SportProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=4000)
    address: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=24)
    email: Optional[EmailStr] = None
    logo_url: Optional[str] = Field(default=None, max_length=500)
    cover_url: Optional[str] = Field(default=None, max_length=500)
    vk_url: Optional[HttpUrl] = None
    telegram_url: Optional[HttpUrl] = None

    _validate_images = field_validator("logo_url", "cover_url")(_image_url)

    @field_validator("vk_url", "telegram_url")
    @classmethod
    def validate_social_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and len(str(value)) > 500:
            raise ValueError("Ссылка должна быть не длиннее 500 символов")
        return value


def _site_title(value: str) -> str:
    if not value.strip():
        raise ValueError("Заполните обязательное поле")
    return value.strip()


class SportVenueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    address: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    hours: str = Field(default="", max_length=160)
    photo_url: Optional[str] = Field(default=None, max_length=500)

    _validate_image = field_validator("photo_url")(_image_url)
    _validate_title = field_validator("name", "address")(_site_title)


class SportDisciplineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    level: str = Field(default="", max_length=120)
    photo_url: Optional[str] = Field(default=None, max_length=500)

    _validate_image = field_validator("photo_url")(_image_url)
    _validate_title = field_validator("name")(_site_title)


class SportPlanCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    price: int = Field(ge=0)
    unit: str = Field(default="", max_length=80)
    items: list[str] = Field(default_factory=list)
    featured: bool = False

    _validate_title = field_validator("code", "name")(_site_title)


class SportGalleryCreate(BaseModel):
    image_url: str = Field(min_length=1, max_length=500)
    alt_text: str = Field(default="", max_length=200)

    @field_validator("image_url")
    @classmethod
    def validate_image(cls, value: str) -> str:
        if not (url := _image_url(value)):
            raise ValueError("Укажите фотографию")
        return url


class SportCoachScheduleItem(BaseModel):
    day_of_week: int = Field(ge=0, le=6)  # 0=Mon ... 6=Sun
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    slot_duration_minutes: int = Field(default=60, ge=15, le=240)
    break_minutes: int = Field(default=15, ge=0, le=120)


class SportCoachScheduleUpdate(BaseModel):
    schedules: list[SportCoachScheduleItem]


class SportServiceCreate(BaseModel):
    coach_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    price: int = Field(ge=0)
    duration_minutes: int = Field(default=60, ge=15, le=240)


class SportCoachBookingCreate(BaseModel):
    coach_id: int
    service_id: int
    start_time: datetime
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=6, max_length=24)
    email: Optional[EmailStr] = None
    consent_version: str = Field(default=LEGAL_VERSION)
    pd_consent: bool = True


class SportStaffInvite(BaseModel):
    phone: str = Field(min_length=6, max_length=24)
    full_name: str = Field(min_length=2, max_length=100)
    role: Literal["owner", "manager", "admin", "trainer"] = "admin"
    permissions: dict[str, bool] = Field(default_factory=dict)


class SportScheduleClosureCreate(BaseModel):
    coach_id: Optional[int] = None
    venue_id: Optional[int] = None
    date: date
    date_to: Optional[date] = None
    reason: str = Field(default="", max_length=255)


class SportBookingReschedule(BaseModel):
    new_start_time: datetime


class SportReviewCreate(BaseModel):
    coach_id: Optional[int] = None
    booking_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)


class SportReviewReply(BaseModel):
    admin_response: str = Field(min_length=1, max_length=2000)


class SportCoachPayrollUpdate(BaseModel):
    commission_percent: int = Field(default=50, ge=0, le=100)
    base_rate_per_session: int = Field(default=0, ge=0)
    bonus: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=255)

