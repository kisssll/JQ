import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.models import ConsentDocument, User, UserRole
from app.models.sport import (
    SportBooking,
    SportOrganization,
    SportTraining,
    SportTrainingException,
)
from app.schemas.sport import (
    SportBookingCreate,
    SportOrganizationResponse,
    SportScheduleResponse,
    SportTrainingResponse,
)
from app.schemas.user import try_normalize_phone
from app.services.consent_service import record_consent
from app.web.pages.legal import LEGAL_VERSION

router = APIRouter()


def _organization_response(organization: SportOrganization) -> SportOrganizationResponse:
    return SportOrganizationResponse.model_validate(organization, from_attributes=True)


@router.get("/organizations", response_model=list[SportOrganizationResponse])
async def list_sport_organizations(db: AsyncSession = Depends(get_db)):
    organizations = (
        await db.execute(
            select(SportOrganization)
            .where(SportOrganization.is_published.is_(True))
            .order_by(SportOrganization.sort_order, SportOrganization.name)
        )
    ).scalars().all()
    return [_organization_response(item) for item in organizations]


@router.get("/organizations/{slug}", response_model=SportOrganizationResponse)
async def get_sport_organization(slug: str, db: AsyncSession = Depends(get_db)):
    organization = (
        await db.execute(
            select(SportOrganization).where(
                SportOrganization.slug == slug,
                SportOrganization.is_published.is_(True),
            )
        )
    ).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    return _organization_response(organization)


@router.get("/organizations/{slug}/schedule", response_model=SportScheduleResponse)
async def get_sport_schedule(slug: str, db: AsyncSession = Depends(get_db)):
    organization = (
        await db.execute(
            select(SportOrganization).where(
                SportOrganization.slug == slug,
                SportOrganization.is_published.is_(True),
            )
        )
    ).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")

    trainings = (
        await db.execute(
            select(SportTraining)
            .where(
                SportTraining.organization_id == organization.id,
                SportTraining.is_active.is_(True),
            )
            .order_by(SportTraining.start_time, SportTraining.code)
        )
    ).scalars().all()
    today = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date()
    exceptions = (
        await db.execute(
            select(SportTrainingException, SportTraining.code)
            .join(SportTraining, SportTraining.id == SportTrainingException.training_id)
            .where(
                SportTraining.organization_id == organization.id,
                SportTrainingException.is_cancelled.is_(True),
                SportTrainingException.class_date >= today,
                SportTrainingException.class_date < today + timedelta(days=14),
            )
        )
    ).all()
    return SportScheduleResponse(
        organization=_organization_response(organization),
        trainings=[
            SportTrainingResponse(
                id=item.code,
                days=item.weekdays,
                time=item.start_time.strftime("%H:%M"),
                end=item.end_time.strftime("%H:%M"),
                coach=item.coach,
                gym=item.gym,
                discipline=item.discipline,
                active=item.is_active,
            )
            for item in trainings
        ],
        exceptions={
            f"{item.class_date}:{code}": False
            for item, code in exceptions
        },
    )


@router.post("/organizations/{slug}/bookings", status_code=201)
@limiter.limit("5/minute")
async def create_sport_booking(
    request: Request,
    slug: str,
    data: SportBookingCreate,
    db: AsyncSession = Depends(get_db),
):
    phone = try_normalize_phone(data.phone)
    if phone is None:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона")
    if data.consent_version != LEGAL_VERSION:
        raise HTTPException(
            status_code=400,
            detail="Версия согласия устарела. Обновите страницу и подтвердите согласие ещё раз.",
        )

    organization = (
        await db.execute(
            select(SportOrganization).where(
                SportOrganization.slug == slug,
                SportOrganization.is_published.is_(True),
            )
        )
    ).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")

    training = None
    if data.training_id:
        training = (
            await db.execute(
                select(SportTraining).where(
                    SportTraining.organization_id == organization.id,
                    SportTraining.code == data.training_id,
                    SportTraining.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if training is None:
            raise HTTPException(status_code=400, detail="Выбранная тренировка недоступна")

        assert data.booking_date is not None
        now = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE))
        today = now.date()
        if data.booking_date < today:
            raise HTTPException(status_code=400, detail="Нельзя записаться на прошедшую дату")
        if data.booking_date > today + timedelta(days=14):
            raise HTTPException(status_code=400, detail="Запись доступна не более чем на 14 дней вперёд")
        if (data.booking_date.weekday() + 1) % 7 not in training.weekdays:
            raise HTTPException(status_code=400, detail="В этот день тренировка не проводится")
        if datetime.combine(data.booking_date, training.start_time, tzinfo=now.tzinfo) <= now:
            raise HTTPException(status_code=400, detail="Нельзя записаться на прошедшее время")
        cancelled = await db.scalar(
            select(SportTrainingException.id).where(
                SportTrainingException.training_id == training.id,
                SportTrainingException.class_date == data.booking_date,
                SportTrainingException.is_cancelled.is_(True),
            )
        )
        if cancelled is not None:
            raise HTTPException(status_code=409, detail="Эта тренировка отменена")
    else:
        today = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date()
        if data.booking_date is not None and data.booking_date < today:
            raise HTTPException(status_code=400, detail="Нельзя выбрать прошедшую дату")
        if data.booking_date is not None and data.booking_date > today + timedelta(days=14):
            raise HTTPException(status_code=400, detail="Запись доступна не более чем на 14 дней вперёд")
        gym_exists = await db.scalar(
            select(SportTraining.id).where(
                SportTraining.organization_id == organization.id,
                SportTraining.gym == data.gym,
            ).limit(1)
        )
        if gym_exists is None:
            raise HTTPException(status_code=400, detail="Зал этой организации не найден")

    user = (
        await db.execute(select(User).where(User.phone == phone))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            phone=phone,
            full_name=data.name,
            hashed_password=get_password_hash(secrets.token_hex(32)),
            role=UserRole.CLIENT,
            is_active=True,
            is_guest=True,
        )
        db.add(user)
        await db.flush()
    elif user.is_guest and not user.full_name:
        user.full_name = data.name

    booking = SportBooking(
        organization_id=organization.id,
        training_id=training.id if training else None,
        client_id=user.id,
        contact_name=data.name,
        participant=data.participant,
        child_name=data.child_name,
        child_age=data.child_age,
        contact_email=str(data.email) if data.email else None,
        experience=data.experience,
        kind=data.kind,
        requested_date=data.booking_date,
        requested_gym=training.gym if training else data.gym,
        requested_discipline=training.discipline if training else data.discipline,
        status="pending",
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    booking_id, user_id = booking.id, user.id
    await record_consent(
        db,
        document=ConsentDocument.PD_CONSENT,
        version=data.consent_version,
        source="sport_guest_booking",
        user_id=user_id,
        phone=phone,
        request=request,
    )
    return {"booking_id": booking_id, "status": "pending"}
