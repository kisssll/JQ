import secrets
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.models import ConsentDocument, User, UserRole
from app.models.sport import (
    SPORT_ADMIN_PERMISSIONS,
    SPORT_MANAGER_PERMISSIONS,
    SPORT_OWNER_PERMISSIONS,
    SportBooking,
    SportCoach,
    SportCoachPayroll,
    SportCoachSchedule,
    SportGalleryImage,
    SportGymMember,
    SportDiscipline,
    SportMembershipPlan,
    SportOrganization,
    SportPayment,
    SportReview,
    SportScheduleClosure,
    SportService,
    SportTraining,
    SportTrainingException,
    SportVenue,
)
from app.schemas.sport import (
    SportBookingCreate,
    SportBookingReschedule,
    SportCoachBookingCreate,
    SportCoachPayrollUpdate,
    SportCoachScheduleUpdate,
    SportDisciplineCreate,
    SportGalleryCreate,
    SportOrganizationResponse,
    SportPlanCreate,
    SportProfileUpdate,
    SportReviewCreate,
    SportReviewReply,
    SportScheduleClosureCreate,
    SportScheduleUpdate,
    SportScheduleResponse,
    SportServiceCreate,
    SportStaffInvite,
    SportTrainingResponse,
    SportVenueCreate,
)
from app.schemas.user import try_normalize_phone
from app.services.consent_service import record_consent
from app.web.auth import get_current_user_from_cookie
from app.web.pages.legal import LEGAL_VERSION

router = APIRouter()


def _organization_response(organization: SportOrganization) -> SportOrganizationResponse:
    return SportOrganizationResponse.model_validate(organization, from_attributes=True)


async def _organization(db: AsyncSession, slug: str, *, published_only: bool = True):
    statement = select(SportOrganization).where(SportOrganization.slug == slug)
    if published_only:
        statement = statement.where(SportOrganization.is_published.is_(True))
    return (await db.execute(statement)).scalar_one_or_none()


async def _gym_access(request: Request, db: AsyncSession, organization_id: int):
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Войдите в аккаунт")
    membership = (
        await db.execute(
            select(SportGymMember).where(
                SportGymMember.organization_id == organization_id,
                SportGymMember.user_id == user.id,
                SportGymMember.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    coach = (
        await db.execute(
            select(SportCoach).where(
                SportCoach.organization_id == organization_id,
                SportCoach.user_id == user.id,
                SportCoach.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    return user, membership, coach


async def _visible_organization(request: Request, db: AsyncSession, slug: str):
    organization = await _organization(db, slug, published_only=False)
    if organization is None or organization.is_published:
        return organization
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if user is None:
        return None
    member = await db.scalar(
        select(SportGymMember.id).where(
            SportGymMember.organization_id == organization.id,
            SportGymMember.user_id == user.id,
            SportGymMember.is_active.is_(True),
        )
    )
    coach = await db.scalar(
        select(SportCoach.id).where(
            SportCoach.organization_id == organization.id,
            SportCoach.user_id == user.id,
            SportCoach.is_active.is_(True),
        )
    )
    return organization if member is not None or coach is not None else None


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
async def get_sport_schedule(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    organization = await _visible_organization(request, db, slug)
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


@router.get("/organizations/{slug}/catalog")
async def get_sport_catalog(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    organization = await _visible_organization(request, db, slug)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")

    venues = (await db.execute(
        select(SportVenue).where(
            SportVenue.organization_id == organization.id,
            SportVenue.is_active.is_(True),
        ).order_by(SportVenue.sort_order, SportVenue.id)
    )).scalars().all()
    coaches = (await db.execute(
        select(SportCoach).where(
            SportCoach.organization_id == organization.id,
            SportCoach.is_active.is_(True),
        ).order_by(SportCoach.sort_order, SportCoach.id)
    )).scalars().all()
    disciplines = (await db.execute(
        select(SportDiscipline).where(
            SportDiscipline.organization_id == organization.id,
            SportDiscipline.is_active.is_(True),
        ).order_by(SportDiscipline.sort_order, SportDiscipline.id)
    )).scalars().all()
    plans = (await db.execute(
        select(SportMembershipPlan).where(
            SportMembershipPlan.organization_id == organization.id,
            SportMembershipPlan.is_active.is_(True),
        ).order_by(SportMembershipPlan.sort_order, SportMembershipPlan.id)
    )).scalars().all()
    gallery = (await db.execute(
        select(SportGalleryImage).where(
            SportGalleryImage.organization_id == organization.id,
            SportGalleryImage.is_active.is_(True),
        ).order_by(SportGalleryImage.sort_order, SportGalleryImage.id)
    )).scalars().all()
    schedule = await get_sport_schedule(slug, request, db)
    return {
        "organization": {
            "slug": organization.slug,
            "name": organization.name,
            "city": organization.city,
            "description": organization.description,
            "logo_url": organization.logo_url,
            "address": organization.address,
            "phone": organization.phone,
            "email": organization.email,
        },
        "venues": [
            {"id": str(item.id), "name": item.name, "address": item.address,
             "note": item.description, "hours": item.hours, "photo": item.photo_url}
            for item in venues
        ],
        "coaches": [
            {"id": item.id, "name": item.name, "role": item.role, "tags": item.tags,
             "exp": item.experience, "about": item.bio, "photo": item.photo_url}
            for item in coaches
        ],
        "disciplines": [
            {"key": item.name, "name": item.name, "text": item.description, "level": item.level}
            for item in disciplines
        ],
        "plans": [
            {"id": item.code, "name": item.name, "price": item.price, "unit": item.unit,
             "items": item.items, "featured": item.featured}
            for item in plans
        ],
        "gallery": [
            {"src": item.image_url, "alt": item.alt_text}
            for item in gallery
        ],
        "trainings": [
            item.model_dump() for item in schedule.trainings
        ],
        "exceptions": schedule.exceptions,
    }


@router.get("/organizations/{slug}/account")
async def get_sport_account(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    from app.web.auth import get_current_user_from_cookie

    organization = await _organization(db, slug)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    user = await get_current_user_from_cookie(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Войдите, чтобы увидеть историю заявок")
    booking_rows = (await db.execute(
        select(SportBooking, SportTraining)
        .outerjoin(SportTraining, SportTraining.id == SportBooking.training_id)
        .where(
            SportBooking.organization_id == organization.id,
            SportBooking.client_id == user.id,
        ).order_by(SportBooking.created_at.desc())
    )).all()
    return {
        "bookings": [
            {
                "id": str(item.id),
                "name": item.contact_name,
                "phone": user.phone,
                "email": item.contact_email,
                "experience": item.experience,
                "discipline": item.requested_discipline,
                "gym": item.requested_gym,
                "date": item.requested_date.isoformat() if item.requested_date else "",
                "time": training.start_time.strftime("%H:%M") if training else "",
                "status": "new" if item.status == "pending" else item.status,
                "kind": item.kind,
                "participant": item.participant,
                "childName": item.child_name,
                "childAge": str(item.child_age) if item.child_age is not None else "",
                "coach": training.coach if training else "",
                "sessionId": training.code if training else "",
            }
            for item, training in booking_rows
        ]
    }


@router.get("/organizations/{slug}/manage")
async def get_sport_management(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    user, membership, coach = await _gym_access(request, db, organization.id)
    if membership is None and coach is None:
        raise HTTPException(status_code=403, detail="Нет доступа к кабинету этого клуба")

    if membership is not None:
        bookings_query = select(SportBooking).where(
            SportBooking.organization_id == organization.id
        )
        payments_query = select(SportPayment).where(
            SportPayment.organization_id == organization.id
        )
    else:
        training_ids = select(SportTraining.id).where(
            SportTraining.organization_id == organization.id,
            SportTraining.coach_id == coach.id,
        )
        bookings_query = select(SportBooking).where(
            SportBooking.organization_id == organization.id,
            SportBooking.training_id.in_(training_ids),
        )
        payments_query = select(SportPayment).where(False)

    bookings = (await db.execute(
        bookings_query.order_by(SportBooking.created_at.desc()).limit(500)
    )).scalars().all()
    phones_by_user = {}
    if bookings:
        phones_by_user = dict((await db.execute(
            select(User.id, User.phone).where(
                User.id.in_({item.client_id for item in bookings})
            )
        )).all())
    trainings_by_id = {}
    if bookings:
        training_ids = {item.training_id for item in bookings if item.training_id is not None}
        if training_ids:
            trainings_by_id = {
                item.id: item
                for item in (await db.execute(
                    select(SportTraining).where(SportTraining.id.in_(training_ids))
                )).scalars().all()
            }
    payments = (await db.execute(
        payments_query.order_by(SportPayment.payment_date.desc(), SportPayment.id.desc()).limit(500)
    )).scalars().all()
    team_members = (await db.execute(
        select(SportGymMember, User)
        .join(User, User.id == SportGymMember.user_id)
        .where(
            SportGymMember.organization_id == organization.id,
            SportGymMember.is_active.is_(True),
        )
    )).all()
    team_coaches = (await db.execute(
        select(SportCoach, User.phone)
        .outerjoin(User, User.id == SportCoach.user_id)
        .where(
            SportCoach.organization_id == organization.id,
            SportCoach.is_active.is_(True),
            SportCoach.user_id.is_not(None),
        )
    )).all()
    exception_rows = (await db.execute(
        select(SportTrainingException, SportTraining.code)
        .join(SportTraining, SportTraining.id == SportTrainingException.training_id)
        .where(
            SportTraining.organization_id == organization.id,
            SportTrainingException.is_cancelled.is_(True),
            SportTrainingException.class_date >= datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date(),
        )
    )).all()
    venue_rows = (await db.execute(
        select(SportVenue).where(
            SportVenue.organization_id == organization.id,
            SportVenue.is_active.is_(True),
        ).order_by(SportVenue.sort_order, SportVenue.id)
    )).scalars().all()
    discipline_rows = (await db.execute(
        select(SportDiscipline).where(
            SportDiscipline.organization_id == organization.id,
            SportDiscipline.is_active.is_(True),
        ).order_by(SportDiscipline.sort_order, SportDiscipline.id)
    )).scalars().all()
    plan_rows = (await db.execute(
        select(SportMembershipPlan).where(
            SportMembershipPlan.organization_id == organization.id,
            SportMembershipPlan.is_active.is_(True),
        ).order_by(SportMembershipPlan.sort_order, SportMembershipPlan.id)
    )).scalars().all()
    gallery_rows = (await db.execute(
        select(SportGalleryImage).where(
            SportGalleryImage.organization_id == organization.id,
            SportGalleryImage.is_active.is_(True),
        ).order_by(SportGalleryImage.sort_order, SportGalleryImage.id)
    )).scalars().all()
    return {
        "role": membership.role if membership else "trainer",
        "organization": {
            "id": organization.id, "slug": organization.slug, "name": organization.name,
            "city": organization.city, "address": organization.address, "phone": organization.phone,
            "email": organization.email, "description": organization.description,
            "logo_url": organization.logo_url,
            "moderation_status": organization.moderation_status,
        },
        "venues": [
            {"id": item.id, "name": item.name, "address": item.address,
             "description": item.description, "hours": item.hours, "photo_url": item.photo_url}
            for item in venue_rows
        ],
        "disciplines": [
            {"id": item.id, "name": item.name, "description": item.description, "level": item.level}
            for item in discipline_rows
        ],
        "plans": [
            {"id": item.id, "code": item.code, "name": item.name, "price": item.price,
             "unit": item.unit, "items": item.items, "featured": item.featured}
            for item in plan_rows
        ],
        "gallery": [
            {"id": item.id, "image_url": item.image_url, "alt_text": item.alt_text}
            for item in gallery_rows
        ],
        "trainings": [
            {
                "id": item.code, "days": item.weekdays,
                "time": item.start_time.strftime("%H:%M"),
                "end": item.end_time.strftime("%H:%M"), "coach": item.coach,
                "gym": item.gym, "discipline": item.discipline, "active": item.is_active,
            }
            for item in (await db.execute(
                select(SportTraining).where(
                    SportTraining.organization_id == organization.id,
                    *((SportTraining.coach_id == coach.id,) if coach and membership is None else ()),
                ).order_by(SportTraining.start_time, SportTraining.code)
            )).scalars().all()
        ],
        "bookings": [
            {
                "id": str(item.id), "name": item.contact_name, "phone": phones_by_user.get(item.client_id, ""),
                "email": item.contact_email, "experience": item.experience,
                "discipline": item.requested_discipline, "gym": item.requested_gym,
                "date": item.requested_date.isoformat() if item.requested_date else "",
                "time": trainings_by_id[item.training_id].start_time.strftime("%H:%M") if item.training_id in trainings_by_id else "",
                "status": "new" if item.status == "pending" else item.status,
                "kind": item.kind, "participant": item.participant,
                "childName": item.child_name,
                "childAge": str(item.child_age) if item.child_age is not None else "",
                "coach": trainings_by_id[item.training_id].coach if item.training_id in trainings_by_id else "",
                "sessionId": trainings_by_id[item.training_id].code if item.training_id in trainings_by_id else "",
            }
            for item in bookings
        ],
        "payments": [
            {
                "id": str(item.id), "name": item.member_name, "plan": item.plan_name,
                "amount": item.amount, "date": item.payment_date.isoformat(),
                "month": item.month,
                "paidAt": item.paid_at.date().isoformat() if item.paid_at else "",
                "status": item.status, "method": item.method,
            }
            for item in payments
        ],
        "team": ([
            {"id": item.id, "name": member.full_name or member.phone, "phone": member.phone, "role": item.role}
            for item, member in team_members
        ] + [
            {"id": item.id, "name": item.name, "phone": phone or "", "role": "trainer"}
            for item, phone in team_coaches
        ]) if membership is not None else [],
        "exceptions": {
            f"{item.class_date}:{code}": False
            for item, code in exception_rows
        },
        "can_manage": membership is not None,
    }


@router.put("/organizations/{slug}/manage/schedule")
async def update_sport_schedule(
    request: Request,
    slug: str,
    data: SportScheduleUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, coach = await _gym_access(request, db, organization.id)
    if membership is None and coach is None:
        raise HTTPException(status_code=403, detail="Нет доступа к расписанию клуба")
    codes = [item.id for item in data.trainings]
    if len(codes) != len(set(codes)):
        raise HTTPException(status_code=400, detail="Идентификаторы тренировок должны быть уникальными")

    training_by_code = {
        item.code: item
        for item in (await db.execute(
            select(SportTraining).where(SportTraining.organization_id == organization.id)
        )).scalars().all()
    }
    if coach is not None and membership is None:
        if any(
            code not in training_by_code
            or training_by_code[code].coach_id != coach.id
            or next(item for item in data.trainings if item.id == code).coach != coach.name
            for code in codes
        ):
            raise HTTPException(status_code=403, detail="Тренер может менять только своё расписание")

    venue_rows = (await db.execute(
        select(SportVenue).where(
            SportVenue.organization_id == organization.id,
            SportVenue.is_active.is_(True),
        )
    )).scalars().all()
    coach_rows = (await db.execute(
        select(SportCoach).where(
            SportCoach.organization_id == organization.id,
            SportCoach.is_active.is_(True),
        )
    )).scalars().all()
    discipline_rows = (await db.execute(
        select(SportDiscipline).where(
            SportDiscipline.organization_id == organization.id,
            SportDiscipline.is_active.is_(True),
        )
    )).scalars().all()
    venues_by_address = {item.address: item for item in venue_rows}
    coaches_by_name = {item.name: item for item in coach_rows}
    disciplines_by_name = {item.name: item for item in discipline_rows}
    changed = {}
    for item in data.trainings:
        training = training_by_code.get(item.id)
        if training is None:
            if coach is not None and membership is None:
                raise HTTPException(status_code=403, detail="Тренер не может создавать тренировки")
            training = SportTraining(
                organization_id=organization.id,
                code=item.id,
                weekdays=item.days,
                start_time=item.time,
                end_time=item.end,
                coach=item.coach,
                gym=item.gym,
                discipline=item.discipline,
                is_active=item.active,
            )
            db.add(training)
        training.weekdays = item.days
        training.start_time = item.time
        training.end_time = item.end
        training.coach = coach.name if coach is not None and membership is None else item.coach
        training.gym = item.gym
        training.discipline = item.discipline
        training.is_active = item.active
        training.coach_id = (
            coach.id
            if coach is not None and membership is None
            else coaches_by_name[item.coach].id if item.coach in coaches_by_name else None
        )
        training.venue_id = venues_by_address[item.gym].id if item.gym in venues_by_address else None
        training.discipline_id = disciplines_by_name[item.discipline].id if item.discipline in disciplines_by_name else None
        changed[item.id] = training

    for key, is_active in data.exceptions.items():
        try:
            date_text, code = key.split(":", 1)
            exception_date = date.fromisoformat(date_text)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Некорректная дата отмены")
        training = changed.get(code) or training_by_code.get(code)
        if training is None:
            raise HTTPException(status_code=400, detail="Тренировка для отмены не найдена")
        if coach is not None and membership is None and training.coach_id != coach.id:
            raise HTTPException(status_code=403, detail="Тренер может менять отмены только своих занятий")
        exception = (await db.execute(
            select(SportTrainingException).where(
                SportTrainingException.training_id == training.id,
                SportTrainingException.class_date == exception_date,
            )
        )).scalar_one_or_none()
        if is_active:
            if exception is not None:
                await db.delete(exception)
        elif exception is None:
            db.add(SportTrainingException(
                training_id=training.id,
                class_date=exception_date,
                is_cancelled=True,
            ))
    await db.commit()
    return {"ok": True, "role": role, "name": name}


@router.post("/organizations/{slug}/bookings/{booking_id}/status")
async def update_sport_booking_status(
    request: Request,
    slug: str,
    booking_id: int,
    status_value: str = Form(..., alias="status"),
    db: AsyncSession = Depends(get_db),
):
    if status_value not in {"pending", "confirmed", "came", "cancelled"}:
        raise HTTPException(status_code=400, detail="Недопустимый статус заявки")
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, coach = await _gym_access(request, db, organization.id)
    if membership is None and coach is None:
        raise HTTPException(status_code=403, detail="Нет доступа к заявкам этого клуба")
    booking = (await db.execute(
        select(SportBooking).where(
            SportBooking.id == booking_id,
            SportBooking.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if membership is None:
        assigned = booking.training_id is not None and await db.scalar(
            select(SportTraining.id).where(
                SportTraining.id == booking.training_id,
                SportTraining.coach_id == coach.id,
            )
        ) is not None
        if not assigned:
            raise HTTPException(status_code=403, detail="Тренер может менять только заявки на свои занятия")
    booking.status = status_value
    await db.commit()
    return {"ok": True, "status": status_value}


@router.post("/organizations/{slug}/staff")
async def add_sport_staff(
    request: Request,
    slug: str,
    phone: str = Form(...),
    name: str = Form(...),
    role: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    user, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role != "owner":
        raise HTTPException(status_code=403, detail="Добавлять сотрудников может владелец клуба")
    if role not in {"admin", "manager", "trainer"}:
        raise HTTPException(status_code=400, detail="Допустимые роли: manager, admin или trainer")
    normalized_phone = try_normalize_phone(phone)
    name = name.strip()
    if normalized_phone is None or len(name) < 2 or len(name) > 160:
        raise HTTPException(status_code=400, detail="Проверьте имя и номер телефона")
    if normalized_phone == user.phone:
        raise HTTPException(status_code=400, detail="Нельзя добавить себя отдельным сотрудником")

    staff_user = (await db.execute(
        select(User).where(User.phone == normalized_phone)
    )).scalar_one_or_none()
    if staff_user is None:
        staff_user = User(
            phone=normalized_phone,
            full_name=name,
            hashed_password=get_password_hash(secrets.token_hex(32)),
            role=UserRole.CLIENT,
            is_active=True,
            is_guest=True,
        )
        db.add(staff_user)
        await db.flush()
    elif staff_user.is_guest and not staff_user.full_name:
        staff_user.full_name = name

    if role in ("admin", "manager"):
        existing = await db.scalar(
            select(SportGymMember).where(
                SportGymMember.organization_id == organization.id,
                SportGymMember.user_id == staff_user.id,
            ).with_for_update()
        )
        if existing is not None and existing.is_active:
            raise HTTPException(status_code=409, detail="Сотрудник уже состоит в команде клуба")
        perms = SPORT_MANAGER_PERMISSIONS if role == "manager" else SPORT_ADMIN_PERMISSIONS
        if existing is not None:
            existing.role = role
            existing.permissions = perms
            existing.is_active = True
        else:
            db.add(SportGymMember(
                organization_id=organization.id,
                user_id=staff_user.id,
                role=role,
                permissions=perms,
                is_active=True,
            ))
    else:
        existing = await db.scalar(
            select(SportCoach).where(
                SportCoach.organization_id == organization.id,
                SportCoach.user_id == staff_user.id,
            ).with_for_update()
        )
        if existing is not None and existing.is_active:
            raise HTTPException(status_code=409, detail="Сотрудник уже состоит в команде клуба")
        if existing is not None:
            existing.name = name
            existing.is_active = True
        else:
            unassigned_coach = (await db.execute(
                select(SportCoach).where(
                    SportCoach.organization_id == organization.id,
                    SportCoach.name == name,
                    SportCoach.user_id.is_(None),
                    SportCoach.is_active.is_(True),
                )
            )).scalar_one_or_none()
            if unassigned_coach is not None:
                unassigned_coach.user_id = staff_user.id
            else:
                db.add(SportCoach(
                    organization_id=organization.id,
                    user_id=staff_user.id,
                    name=name,
                    role="Тренер",
                    is_active=True,
                ))
    await db.commit()
    return {"ok": True, "role": role, "name": name}


@router.delete("/organizations/{slug}/staff/{role}/{staff_id}")
async def remove_sport_staff(
    request: Request,
    slug: str,
    role: str,
    staff_id: int,
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role != "owner":
        raise HTTPException(status_code=403, detail="Управлять составом клуба может владелец")
    if role in ("admin", "manager"):
        staff = (await db.execute(
            select(SportGymMember).where(
                SportGymMember.id == staff_id,
                SportGymMember.organization_id == organization.id,
                SportGymMember.role == role,
            )
        )).scalar_one_or_none()
        if staff is not None:
            staff.is_active = False
    elif role == "trainer":
        staff = (await db.execute(
            select(SportCoach).where(
                SportCoach.id == staff_id,
                SportCoach.organization_id == organization.id,
                SportCoach.user_id.is_not(None),
            )
        )).scalar_one_or_none()
        if staff is not None:
            staff.is_active = False
    else:
        raise HTTPException(status_code=400, detail="Недопустимая роль сотрудника")
    if staff is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    await db.commit()
    staff_name = getattr(staff, "name", "")
    return {"ok": True, "role": role, "name": staff_name}


@router.post("/organizations/{slug}/payments")
async def create_sport_payment(
    request: Request,
    slug: str,
    member_name: str = Form(...),
    plan_code: str = Form(...),
    month: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    user, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Нет прав для учёта оплат")
    plan = (await db.execute(
        select(SportMembershipPlan).where(
            SportMembershipPlan.organization_id == organization.id,
            SportMembershipPlan.code == plan_code,
            SportMembershipPlan.is_active.is_(True),
        )
    )).scalar_one_or_none()
    name = member_name.strip()
    if plan is None or len(name) < 2 or len(name) > 160:
        raise HTTPException(status_code=400, detail="Проверьте участника и тариф")
    if month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=400, detail="Укажите месяц в формате ГГГГ-ММ")
    today = date.today()
    db.add(SportPayment(
        organization_id=organization.id,
        member_name=name,
        plan_id=plan.id,
        plan_name=plan.name,
        amount=plan.price,
        payment_date=today,
        month=month or today.strftime("%Y-%m"),
        status="pending",
        created_by_id=user.id,
    ))
    await db.commit()
    return {"ok": True, "role": role, "name": name}


@router.post("/organizations/{slug}/payments/{payment_id}/status")
async def update_sport_payment_status(
    request: Request,
    slug: str,
    payment_id: int,
    status_value: str = Form(..., alias="status"),
    method: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if status_value not in {"paid", "pending"}:
        raise HTTPException(status_code=400, detail="Недопустимый статус оплаты")
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Нет прав для учёта оплат")
    payment = (await db.execute(
        select(SportPayment).where(
            SportPayment.id == payment_id,
            SportPayment.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Оплата не найдена")
    method = method.strip()
    if status_value == "paid" and len(method) > 80:
        raise HTTPException(status_code=400, detail="Название способа оплаты слишком длинное")
    payment.status = status_value
    payment.method = method if status_value == "paid" else ""
    payment.paid_at = datetime.now(timezone.utc) if status_value == "paid" else None
    await db.commit()
    return {"ok": True, "status": status_value}


@router.post("/organizations/{slug}/manage/profile")
async def update_sport_profile(
    request: Request,
    slug: str,
    data: SportProfileUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для редактирования профиля")
    if data.name is not None:
        name = data.name.strip()
        if len(name) < 2:
            raise HTTPException(status_code=400, detail="Название слишком короткое")
        organization.name = name
    if data.description is not None:
        organization.description = data.description.strip()
    if data.address is not None:
        organization.address = data.address.strip()
    if data.phone is not None:
        norm = try_normalize_phone(data.phone)
        if norm is None:
            raise HTTPException(status_code=400, detail="Некорректный номер телефона")
        organization.phone = norm
    if data.email is not None:
        organization.email = str(data.email).strip() or None
    if data.logo_url is not None:
        organization.logo_url = data.logo_url.strip() or None
    await db.commit()
    await db.refresh(organization)
    return {"ok": True, "organization": _organization_response(organization)}


@router.post("/organizations/{slug}/manage/venues")
async def create_sport_venue(
    request: Request,
    slug: str,
    data: SportVenueCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для добавления залов")
    venue = SportVenue(
        organization_id=organization.id,
        name=data.name.strip(),
        address=data.address.strip(),
        description=data.description.strip(),
        hours=data.hours.strip(),
        photo_url=data.photo_url.strip() if data.photo_url else None,
    )
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    return {"ok": True, "id": venue.id, "name": venue.name, "address": venue.address}


@router.delete("/organizations/{slug}/manage/venues/{venue_id}")
async def delete_sport_venue(
    request: Request,
    slug: str,
    venue_id: int,
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления залов")
    venue = (await db.execute(
        select(SportVenue).where(
            SportVenue.id == venue_id,
            SportVenue.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Зал не найден")
    venue.is_active = False
    await db.commit()
    return {"ok": True, "role": role, "name": name}


@router.post("/organizations/{slug}/manage/disciplines")
async def create_sport_discipline(
    request: Request,
    slug: str,
    data: SportDisciplineCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для добавления направлений")
    discipline = SportDiscipline(
        organization_id=organization.id,
        name=data.name.strip(),
        description=data.description.strip(),
        level=data.level.strip(),
    )
    db.add(discipline)
    await db.commit()
    await db.refresh(discipline)
    return {"ok": True, "id": discipline.id, "name": discipline.name}


@router.delete("/organizations/{slug}/manage/disciplines/{discipline_id}")
async def delete_sport_discipline(
    request: Request,
    slug: str,
    discipline_id: int,
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления направлений")
    discipline = (await db.execute(
        select(SportDiscipline).where(
            SportDiscipline.id == discipline_id,
            SportDiscipline.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if discipline is None:
        raise HTTPException(status_code=404, detail="Направление не найдено")
    discipline.is_active = False
    await db.commit()
    return {"ok": True, "role": role, "name": name}


@router.post("/organizations/{slug}/manage/plans")
async def create_sport_plan(
    request: Request,
    slug: str,
    data: SportPlanCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для добавления тарифов")
    plan = SportMembershipPlan(
        organization_id=organization.id,
        code=data.code.strip(),
        name=data.name.strip(),
        price=data.price,
        unit=data.unit.strip(),
        items=data.items,
        featured=data.featured,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {"ok": True, "id": plan.id, "name": plan.name, "price": plan.price}


@router.delete("/organizations/{slug}/manage/plans/{plan_id}")
async def delete_sport_plan(
    request: Request,
    slug: str,
    plan_id: int,
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления тарифов")
    plan = (await db.execute(
        select(SportMembershipPlan).where(
            SportMembershipPlan.id == plan_id,
            SportMembershipPlan.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    plan.is_active = False
    await db.commit()
    return {"ok": True, "role": role, "name": name}


@router.post("/organizations/{slug}/manage/gallery")
async def create_sport_gallery_image(
    request: Request,
    slug: str,
    data: SportGalleryCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для добавления фото")
    image = SportGalleryImage(
        organization_id=organization.id,
        image_url=data.image_url.strip(),
        alt_text=data.alt_text.strip(),
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return {"ok": True, "id": image.id, "image_url": image.image_url}


@router.get("/coaches/{coach_id}/services")
async def get_coach_services(
    coach_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Список услуг тренера."""
    coach = (await db.execute(select(SportCoach).where(SportCoach.id == coach_id, SportCoach.is_active.is_(True)))).scalar_one_or_none()
    if coach is None:
        raise HTTPException(status_code=404, detail="Тренер не найден")
    services = (
        await db.execute(
            select(SportService).where(
                or_(SportService.coach_id == coach_id, SportService.coach_id.is_(None)),
                SportService.organization_id == coach.organization_id,
                SportService.is_active.is_(True),
            )
        )
    ).scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "price": s.price,
            "duration_minutes": s.duration_minutes,
        }
        for s in services
    ]


@router.post("/organizations/{slug}/coaches/{coach_id}/schedule")
async def update_coach_schedule(
    request: Request,
    slug: str,
    coach_id: int,
    data: SportCoachScheduleUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Настройка окон тренера (статичные слоты по дням недели)."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    user, membership, coach_profile = await _gym_access(request, db, organization.id)
    # Тренер может настраивать своё расписание, владелец/админ — любого
    is_self = coach_profile is not None and coach_profile.id == coach_id
    is_admin = membership is not None and membership.role in ("owner", "admin")
    if not (is_self or is_admin):
        raise HTTPException(status_code=403, detail="Недостаточно прав для изменения графика тренера")

    # Деактивируем предыдущие графики тренера
    existing = (
        await db.execute(select(SportCoachSchedule).where(SportCoachSchedule.coach_id == coach_id))
    ).scalars().all()
    for item in existing:
        item.is_active = False

    # Добавляем новые интервалы
    for item in data.schedules:
        sh, sm = map(int, item.start_time.split(":"))
        eh, em = map(int, item.end_time.split(":"))
        sched = SportCoachSchedule(
            coach_id=coach_id,
            day_of_week=item.day_of_week,
            start_time=time(sh, sm),
            end_time=time(eh, em),
            slot_duration_minutes=item.slot_duration_minutes,
            break_minutes=item.break_minutes,
            is_active=True,
        )
        db.add(sched)
    await db.commit()
    return {"ok": True, "count": len(data.schedules)}


@router.get("/coaches/{coach_id}/available-slots")
async def get_coach_available_slots(
    coach_id: int,
    date_str: str = Query(..., alias="date"),
    duration_minutes: int = Query(60),
    db: AsyncSession = Depends(get_db),
):
    """Получить свободные окна тренера на указанную дату."""
    from app.services.sport_booking_service import SportBookingService
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты (ожидается ГГГГ-ММ-ДД)")

    slots = await SportBookingService.get_coach_available_slots(
        db=db,
        coach_id=coach_id,
        target_date=target_date,
        duration_minutes=duration_minutes,
    )
    return {"coach_id": coach_id, "date": date_str, "slots": slots}


@router.post("/organizations/{slug}/manage/services")
async def create_sport_service(
    request: Request,
    slug: str,
    data: SportServiceCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Добавление индивидуальной услуги тренера/клуба."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для добавления услуг")

    service = SportService(
        organization_id=organization.id,
        coach_id=data.coach_id,
        name=data.name.strip(),
        description=data.description.strip(),
        price=data.price,
        duration_minutes=data.duration_minutes,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return {"ok": True, "id": service.id, "name": service.name, "price": service.price}


@router.post("/organizations/{slug}/book-coach", status_code=201)
@limiter.limit("5/minute")
async def book_coach_slot(
    request: Request,
    slug: str,
    data: SportCoachBookingCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Индивидуальная запись к тренеру на услугу по слотам (алгоритм как в бьюти)."""
    from app.services.sport_booking_service import SportBookingService, commit_sport_booking, SportSlotTakenError

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

    # Проверяем тренера
    coach = (
        await db.execute(
            select(SportCoach).where(
                SportCoach.id == data.coach_id,
                SportCoach.organization_id == organization.id,
                SportCoach.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if coach is None:
        raise HTTPException(status_code=404, detail="Тренер не найден в данном клубе")

    # Проверяем услугу
    service = (
        await db.execute(
            select(SportService).where(
                SportService.id == data.service_id,
                SportService.organization_id == organization.id,
                SportService.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="Услуга не найдена")

    start_time = data.start_time.replace(tzinfo=None)
    now = datetime.now()
    if start_time <= now:
        raise HTTPException(status_code=400, detail="Нельзя записаться на прошедшее время")

    # Проверяем доступность слота по алгоритму
    is_available = await SportBookingService.is_slot_available(
        db=db,
        coach_id=coach.id,
        start_time=start_time,
        duration_minutes=service.duration_minutes,
    )
    if not is_available:
        raise HTTPException(status_code=409, detail="Это время уже занято или тренер не работает в этот интервал")

    end_time = start_time + timedelta(minutes=service.duration_minutes)

    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
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

    booking = SportBooking(
        organization_id=organization.id,
        coach_id=coach.id,
        service_id=service.id,
        client_id=user.id,
        contact_name=data.name,
        contact_email=str(data.email) if data.email else None,
        participant="self",
        kind="individual",
        start_time=start_time,
        end_time=end_time,
        price=service.price,
        requested_date=start_time.date(),
        requested_gym=organization.name,
        requested_discipline=service.name,
        status="pending",
    )
    db.add(booking)
    try:
        await commit_sport_booking(db, booking)
    except SportSlotTakenError:
        raise HTTPException(status_code=409, detail="Этот слот только что заняли — выберите другое время")

    await record_consent(
        db,
        document=ConsentDocument.PD_CONSENT,
        version=data.consent_version,
        source="sport_coach_booking",
        user_id=user.id,
        phone=phone,
        request=request,
    )

    return {
        "ok": True,
        "booking_id": booking.id,
        "coach": coach.name,
        "service": service.name,
        "start_time": booking.start_time.isoformat(),
        "price": booking.price,
        "status": booking.status,
    }


@router.delete("/organizations/{slug}/manage/gallery/{image_id}")
async def delete_sport_gallery_image(
    request: Request,
    slug: str,
    image_id: int,
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления фото")
    image = (await db.execute(
        select(SportGalleryImage).where(
            SportGalleryImage.id == image_id,
            SportGalleryImage.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail="Фотография не найдена")
    image.is_active = False
    await db.commit()
    return {"ok": True}


# ==========================================
# 1. ЗАКРЫТИЯ КАЛЕНДАРЯ / ВЫХОДНЫЕ ТРЕНЕРОВ
# ==========================================

@router.post("/organizations/{slug}/closures")
async def create_sport_closure(
    request: Request,
    slug: str,
    data: SportScheduleClosureCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Добавить закрытую дату (отпуск тренера или закрытие зала/клуба)."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, coach_profile = await _gym_access(request, db, organization.id)
    is_admin = membership is not None and membership.role in ("owner", "manager", "admin")
    is_self_coach = coach_profile is not None and coach_profile.id == data.coach_id
    if not (is_admin or is_self_coach):
        raise HTTPException(status_code=403, detail="Недостаточно прав для установки закрытых дат")

    closure = SportScheduleClosure(
        organization_id=organization.id,
        coach_id=data.coach_id,
        venue_id=data.venue_id,
        date=data.date,
        reason=data.reason.strip(),
    )
    db.add(closure)
    await db.commit()
    await db.refresh(closure)
    return {"ok": True, "id": closure.id, "date": closure.date.isoformat(), "reason": closure.reason}


@router.delete("/organizations/{slug}/closures/{closure_id}")
async def delete_sport_closure(
    request: Request,
    slug: str,
    closure_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Удалить закрытую дату."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "manager", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    closure = (await db.execute(
        select(SportScheduleClosure).where(
            SportScheduleClosure.id == closure_id,
            SportScheduleClosure.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if closure is None:
        raise HTTPException(status_code=404, detail="Запись о закрытии не найдена")
    await db.delete(closure)
    await db.commit()
    return {"ok": True, "role": role, "name": name}


# ==========================================
# 2. ПЕРЕНОС И ОТМЕНА ЗАПИСЕЙ КЛИЕНТОМ / КЛУБОМ
# ==========================================

@router.post("/organizations/{slug}/bookings/{booking_id}/cancel")
async def cancel_sport_booking(
    request: Request,
    slug: str,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Отмена брони клиентом или администрацией."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")

    user = await get_current_user_from_cookie(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Войдите в аккаунт")

    booking = (await db.execute(
        select(SportBooking).where(
            SportBooking.id == booking_id,
            SportBooking.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    # Клиент может отменить только свою запись, админ/тренер — любую
    is_client = booking.client_id == user.id
    is_staff = await db.scalar(
        select(SportGymMember.id).where(
            SportGymMember.organization_id == organization.id,
            SportGymMember.user_id == user.id,
            SportGymMember.is_active.is_(True),
        )
    ) is not None
    if not (is_client or is_staff):
        raise HTTPException(status_code=403, detail="Недостаточно прав для отмены записи")

    booking.status = "cancelled"
    await db.commit()
    return {"ok": True, "status": "cancelled"}


@router.post("/organizations/{slug}/bookings/{booking_id}/reschedule")
async def reschedule_sport_booking(
    request: Request,
    slug: str,
    booking_id: int,
    data: SportBookingReschedule = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Перенос индивидуальной брони на новое время с проверкой слота."""
    from app.services.sport_booking_service import SportBookingService, commit_sport_booking, SportSlotTakenError

    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")

    user = await get_current_user_from_cookie(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Войдите в аккаунт")

    booking = (await db.execute(
        select(SportBooking).where(
            SportBooking.id == booking_id,
            SportBooking.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    is_client = booking.client_id == user.id
    is_staff = await db.scalar(
        select(SportGymMember.id).where(
            SportGymMember.organization_id == organization.id,
            SportGymMember.user_id == user.id,
            SportGymMember.is_active.is_(True),
        )
    ) is not None
    if not (is_client or is_staff):
        raise HTTPException(status_code=403, detail="Недостаточно прав для переноса")

    new_start = data.new_start_time.replace(tzinfo=None)
    if new_start <= datetime.now():
        raise HTTPException(status_code=400, detail="Нельзя перенести на прошедшее время")

    duration = 60
    if booking.service_id:
        service_dur = await db.scalar(select(SportService.duration_minutes).where(SportService.id == booking.service_id))
        if service_dur:
            duration = service_dur

    if booking.coach_id:
        is_available = await SportBookingService.is_slot_available(
            db=db,
            coach_id=booking.coach_id,
            start_time=new_start,
            duration_minutes=duration,
            exclude_booking_id=booking.id,
        )
        if not is_available:
            raise HTTPException(status_code=409, detail="Новое время недоступно или занято")

    booking.start_time = new_start
    booking.end_time = new_start + timedelta(minutes=duration)
    booking.requested_date = new_start.date()
    try:
        await commit_sport_booking(db, booking)
    except SportSlotTakenError:
        raise HTTPException(status_code=409, detail="Время только что заняли")

    return {"ok": True, "booking_id": booking.id, "start_time": booking.start_time.isoformat()}


# ==========================================
# 3. ОТЗЫВЫ О КЛУБЕ И ТРЕНЕРАХ
# ==========================================

@router.post("/organizations/{slug}/reviews")
async def create_sport_review(
    request: Request,
    slug: str,
    data: SportReviewCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Оставить отзыв о клубе или тренере."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")

    user = await get_current_user_from_cookie(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Войдите, чтобы оставить отзыв")

    review = SportReview(
        organization_id=organization.id,
        coach_id=data.coach_id,
        client_id=user.id,
        booking_id=data.booking_id,
        rating=data.rating,
        comment=data.comment.strip(),
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return {"ok": True, "id": review.id, "rating": review.rating, "comment": review.comment}


@router.get("/organizations/{slug}/reviews")
async def get_sport_reviews(
    slug: str,
    coach_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Список опубликованных отзывов о клубе или тренере."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")

    query = select(SportReview, User.full_name).join(User, User.id == SportReview.client_id).where(
        SportReview.organization_id == organization.id,
        SportReview.is_published.is_(True),
    )
    if coach_id is not None:
        query = query.where(SportReview.coach_id == coach_id)

    rows = (await db.execute(query.order_by(SportReview.created_at.desc()))).all()
    return [
        {
            "id": r.SportReview.id,
            "author": r.full_name or "Клиент",
            "rating": r.SportReview.rating,
            "comment": r.SportReview.comment,
            "admin_response": r.SportReview.admin_response,
            "created_at": r.SportReview.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/organizations/{slug}/reviews/{review_id}/reply")
async def reply_sport_review(
    request: Request,
    slug: str,
    review_id: int,
    data: SportReviewReply = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Ответ администрации на отзыв."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "manager", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    review = (await db.execute(
        select(SportReview).where(
            SportReview.id == review_id,
            SportReview.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if review is None:
        raise HTTPException(status_code=404, detail="Отзыв не найден")

    review.admin_response = data.admin_response.strip()
    await db.commit()
    return {"ok": True, "admin_response": review.admin_response}


# ==========================================
# 4. РАСЧЕТ ЗАРПЛАТЫ И СТАВОК ТРЕНЕРОВ (PAYROLL)
# ==========================================

@router.post("/organizations/{slug}/coaches/{coach_id}/payroll")
async def update_coach_payroll_settings(
    request: Request,
    slug: str,
    coach_id: int,
    data: SportCoachPayrollUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Настройка ставки/процента вознаграждения тренера."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if membership is None or membership.role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Только владелец или управляющий может настраивать зарплаты")

    payroll = (await db.execute(
        select(SportCoachPayroll).where(
            SportCoachPayroll.coach_id == coach_id,
            SportCoachPayroll.organization_id == organization.id,
        )
    )).scalar_one_or_none()

    if payroll is None:
        payroll = SportCoachPayroll(
            organization_id=organization.id,
            coach_id=coach_id,
            commission_percent=data.commission_percent,
            base_rate_per_session=data.base_rate_per_session,
            bonus=data.bonus,
            notes=data.notes,
        )
        db.add(payroll)
    else:
        payroll.commission_percent = data.commission_percent
        payroll.base_rate_per_session = data.base_rate_per_session
        payroll.bonus = data.bonus
        payroll.notes = data.notes

    await db.commit()
    await db.refresh(payroll)
    return {
        "ok": True,
        "coach_id": coach_id,
        "commission_percent": payroll.commission_percent,
        "base_rate_per_session": payroll.base_rate_per_session,
        "bonus": payroll.bonus,
    }


@router.get("/organizations/{slug}/coaches/{coach_id}/payroll/summary")
async def get_coach_payroll_summary(
    request: Request,
    slug: str,
    coach_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Сводка по заработанному вознаграждению тренера за проведённые тренировки."""
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    user, membership, coach_profile = await _gym_access(request, db, organization.id)
    is_mgmt = membership is not None and membership.role in ("owner", "manager")
    is_self = coach_profile is not None and coach_profile.id == coach_id
    if not (is_mgmt or is_self):
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра финансовой сводки")

    payroll = (await db.execute(
        select(SportCoachPayroll).where(
            SportCoachPayroll.coach_id == coach_id,
            SportCoachPayroll.organization_id == organization.id,
        )
    )).scalar_one_or_none()

    commission_pct = payroll.commission_percent if payroll else 50
    base_rate = payroll.base_rate_per_session if payroll else 0
    bonus = payroll.bonus if payroll else 0

    completed_bookings = (await db.execute(
        select(SportBooking).where(
            SportBooking.coach_id == coach_id,
            SportBooking.organization_id == organization.id,
            SportBooking.status.in_(["came", "confirmed"]),
        )
    )).scalars().all()

    total_sessions = len(completed_bookings)
    total_revenue = sum(b.price or 0 for b in completed_bookings)
    earned_commission = int(total_revenue * (commission_pct / 100))
    earned_base = total_sessions * base_rate
    total_payout = earned_commission + earned_base + bonus

    return {
        "coach_id": coach_id,
        "total_sessions": total_sessions,
        "total_revenue": total_revenue,
        "commission_percent": commission_pct,
        "earned_commission": earned_commission,
        "base_rate": base_rate,
        "earned_base": earned_base,
        "bonus": bonus,
        "total_payout": total_payout,
    }


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
            select(SportVenue.id).where(
                SportVenue.organization_id == organization.id,
                SportVenue.address == data.gym,
                SportVenue.is_active.is_(True),
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


_TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _slugify_sport(text: str) -> str:
    lowered = text.lower()
    translit = "".join(_TRANSLIT_MAP.get(ch, ch) for ch in lowered)
    cleaned = re.sub(r"[^a-z0-9]+", "-", translit).strip("-")
    return cleaned or "gym"


@router.post("/business/apply")
@router.post("/business/my-gym")
async def apply_sport_business(
    request: Request,
    name: str = Form(...),
    city: str = Form(...),
    address: str = Form(...),
    phone: str = Form(...),
    email: str = Form(""),
    description: str = Form(""),
    offer_accepted: str = Form(""),
    pd_consent: str = Form(""),
    consent_version: str = Form(""),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import HTMLResponse, RedirectResponse
    from app.models.models import ConsentDocument
    from app.services.consent_service import record_consents
    from app.services.notifications import notify_admins
    from app.web.auth import get_current_user_from_cookie
    from app.web.cities import RUSSIAN_CITIES
    from app.web.pages.register_gym import render_register_gym_page

    user = await get_current_user_from_cookie(request, db)
    if user is None:
        return RedirectResponse("/sport/login?redirect=%2Fsport%2Fbusiness%2Fregister-gym", status_code=303)

    if offer_accepted != "1":
        return HTMLResponse(
            content=render_register_gym_page(user, error="Нужно принять условия оферты."),
            status_code=400,
        )
    if pd_consent != "1":
        return HTMLResponse(
            content=render_register_gym_page(
                user, error="Отметьте согласие на обработку персональных данных."
            ),
            status_code=400,
        )
    if consent_version != LEGAL_VERSION:
        return HTMLResponse(
            content=render_register_gym_page(
                user, error="Версия согласия устарела. Обновите страницу."
            ),
            status_code=400,
        )

    name, city, address = name.strip(), city.strip(), address.strip()
    if not name:
        return HTMLResponse(
            content=render_register_gym_page(user, error="Укажите название клуба или зала."),
            status_code=400,
        )

    if city not in RUSSIAN_CITIES:
        return HTMLResponse(
            content=render_register_gym_page(user, error="Выберите город из списка."),
            status_code=400,
        )

    if not address:
        return HTMLResponse(
            content=render_register_gym_page(user, error="Укажите адрес основного зала."),
            status_code=400,
        )

    normalized_phone = try_normalize_phone(phone)
    if normalized_phone is None:
        return HTMLResponse(
            content=render_register_gym_page(user, error="Проверьте номер телефона для связи."),
            status_code=400,
        )

    email = email.strip()
    description = description.strip()
    if (
        len(name) > 160 or len(city) > 100 or len(address) > 300
        or len(normalized_phone) > 24 or len(email) > 254 or len(description) > 4000
    ):
        return HTMLResponse(
            content=render_register_gym_page(user, error="Одно из полей заявки превышает допустимую длину."),
            status_code=400,
        )
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return HTMLResponse(
            content=render_register_gym_page(user, error="Проверьте адрес электронной почты."),
            status_code=400,
        )

    if settings.YANDEX_MAPS_API_KEY:
        if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return HTMLResponse(
                content=render_register_gym_page(
                    user, error="Выберите адрес из подсказок, чтобы мы могли определить точное расположение зала."
                ),
                status_code=400,
            )

    base_slug = _slugify_sport(name)
    slug = f"{base_slug[:65]}-{secrets.token_hex(3)}"
    organization = SportOrganization(
        slug=slug,
        name=name,
        city=city,
        description=description,
        address=address,
        phone=normalized_phone,
        email=email or None,
        creator_id=user.id,
        moderation_status="pending",
        is_published=False,
        sort_order=100,
    )
    db.add(organization)
    await db.flush()
    # Права по умолчанию для создателя
    db.add(SportGymMember(
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
        permissions=SPORT_OWNER_PERMISSIONS,
        is_creator=True,
        is_active=True,
    ))
    db.add(SportVenue(
        organization_id=organization.id,
        name="Основной зал",
        address=address,
        description="",
        hours="По расписанию групп",
        sort_order=0,
    ))
    db.add_all([
        SportMembershipPlan(
            organization_id=organization.id,
            code="trial",
            name="Пробная тренировка",
            price=0,
            unit="первое занятие",
            items=["Ознакомительная тренировка"],
            sort_order=0,
        ),
        SportMembershipPlan(
            organization_id=organization.id,
            code="base",
            name="Абонемент",
            price=0,
            unit="стоимость уточняется",
            items=["Условия уточнит администратор клуба"],
            sort_order=1,
        ),
    ])
    if user.role != UserRole.ADMIN:
        user.role = UserRole.BUSINESS
    user_id, user_phone = user.id, user.phone
    await db.commit()
    organization_id = organization.id

    await notify_admins(
        db,
        "Новая заявка на подключение спортивного клуба",
        f"«{name}», тел. {normalized_phone}. Одобрить заявку можно в админ-панели.",
    )
    await record_consents(
        db,
        documents=(ConsentDocument.OFFER, ConsentDocument.PD_CONSENT),
        version=consent_version,
        source="sport_business_apply",
        user_id=user_id,
        phone=user_phone,
        request=request,
    )
    return RedirectResponse(
        f"/sport/business?submitted={organization_id}",
        status_code=303,
    )
