import secrets
import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import Time, case, cast, func, or_, select, update
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
    SPORT_PERMISSION_KEYS,
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
from app.services.sparta_documents import training_agreements
from app.services.uploads import UploadError, delete_stored, save_image, save_sport_document
from app.web.auth import get_current_user_from_cookie
from app.web.pages.legal import LEGAL_VERSION

router = APIRouter()

_SPORT_ROLE_PERMISSIONS = {
    "owner": SPORT_OWNER_PERMISSIONS,
    "manager": SPORT_MANAGER_PERMISSIONS,
    "admin": SPORT_ADMIN_PERMISSIONS,
}
_SPORT_STAFF_PERMISSIONS = {
    "owner": "manage_owners", "manager": "manage_managers",
    "admin": "manage_admins", "trainer": "manage_coaches",
}


def _sport_permissions(member: SportGymMember | None) -> dict[str, bool]:
    if member is None:
        return dict.fromkeys(SPORT_PERMISSION_KEYS, False)
    if member.is_creator:
        return dict(SPORT_OWNER_PERMISSIONS)
    stored = member.permissions or {}
    defaults = _SPORT_ROLE_PERMISSIONS[member.role]
    return {key: stored.get(key, defaults[key]) is True for key in SPORT_PERMISSION_KEYS}


def _can_sport(member: SportGymMember | None, key: str) -> bool:
    return _sport_permissions(member)[key]


def _can_assign_sport_permissions(member: SportGymMember | None) -> bool:
    return member is not None and (member.is_creator or member.role == "owner")


def _can_manage_sport_member(actor: SportGymMember, target: SportGymMember) -> bool:
    if target.is_creator:
        return actor.id == target.id
    if _can_assign_sport_permissions(actor):
        return True
    actor_permissions = _sport_permissions(actor)
    return target.role != "owner" and all(
        not allowed or actor_permissions[key] for key, allowed in _sport_permissions(target).items()
    )


def _organization_response(organization: SportOrganization) -> SportOrganizationResponse:
    return SportOrganizationResponse.model_validate(organization, from_attributes=True)


def _sport_booking_time(booking: SportBooking, training: SportTraining | None) -> str:
    if booking.start_time:
        return booking.start_time.strftime("%H:%M")
    return training.start_time.strftime("%H:%M") if training else ""


def _sport_staff_card(staff: SportCoach | SportGymMember, phone: str | None, name: str | None = None) -> dict:
    common = {"id": staff.id, "phone": staff.contact_phone or phone or "",
              "hasAccount": staff.user_id is not None,
              "photo": staff.photo_url, "about": staff.bio or ""}
    if isinstance(staff, SportCoach):
        return {**common, "name": staff.name, "role": "trainer", "title": staff.role,
                "experience": staff.experience, "tags": staff.tags}
    return {**common, "name": staff.display_name or name or phone, "role": staff.role,
            "permissions": _sport_permissions(staff), "isCreator": staff.is_creator}


def _sport_payment_card(payment: SportPayment) -> dict:
    return {
        "id": str(payment.id), "name": payment.member_name, "plan": payment.plan_name,
        "amount": payment.amount, "date": payment.payment_date.isoformat(), "month": payment.month,
        "paidAt": payment.paid_at.date().isoformat() if payment.paid_at else "",
        "status": payment.status, "method": payment.method,
    }


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
    if membership is None and coach is None and (user.has_role(UserRole.ADMIN) or getattr(user, "is_admin", False)):
        membership = SportGymMember(
            organization_id=organization_id,
            user_id=user.id,
            role="owner",
            permissions=dict(SPORT_OWNER_PERMISSIONS),
            is_creator=True,
            is_active=True,
        )
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
    closures = (await db.execute(select(SportScheduleClosure).where(
        SportScheduleClosure.organization_id == organization.id,
        SportScheduleClosure.date >= today,
        SportScheduleClosure.date <= today + timedelta(days=14),
    ))).scalars().all()
    closure_coaches = {item.id: item.name for item in (await db.execute(select(SportCoach).where(
        SportCoach.organization_id == organization.id,
    ))).scalars().all()}
    closed_slots = {
        f"{closed.date}:{training.code}": False
        for closed in closures for training in trainings
        if (closed.coach_id is None or closed.coach_id == training.coach_id or closure_coaches.get(closed.coach_id) == training.coach)
        and (closed.venue_id is None or closed.venue_id == training.venue_id)
    }
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
                color=item.color,
            )
            for item in trainings
        ],
        exceptions={**closed_slots, **{
            f"{item.class_date}:{code}": False
            for item, code in exceptions
        }},
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
        "documents": organization.site_documents or [],
        "agreements": training_agreements(organization.training_agreements) if slug == "sparta" else None,
        "organization": {
            "slug": organization.slug,
            "name": organization.name,
            "city": organization.city,
            "description": organization.description,
            "logo_url": organization.logo_url,
            "address": organization.address,
            "phone": organization.phone,
            "email": organization.email,
            "cover_url": organization.cover_url,
            "vk_url": organization.vk_url,
            "telegram_url": organization.telegram_url,
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
            {"key": item.name, "name": item.name, "text": item.description, "level": item.level, "photo": item.photo_url}
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
                "time": _sport_booking_time(item, training),
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

    permissions = _sport_permissions(membership)
    can_assign_permissions = _can_assign_sport_permissions(membership)
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
            or_(SportBooking.coach_id == coach.id, SportBooking.training_id.in_(training_ids)),
        )
        payments_query = select(SportPayment).where(False)
    if membership is not None and not permissions["manage_bookings"]:
        bookings_query = bookings_query.where(False)
    if not permissions["view_finances"]:
        payments_query = payments_query.where(False)

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
        ).order_by(SportCoach.sort_order, SportCoach.id)
    )).all()
    exception_rows = (await db.execute(
        select(SportTrainingException, SportTraining.code)
        .join(SportTraining, SportTraining.id == SportTrainingException.training_id)
        .where(
            SportTraining.organization_id == organization.id,
            SportTrainingException.is_cancelled.is_(True),
            *((SportTraining.coach_id == coach.id,) if membership is None else ()),
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
        "permissions": permissions,
        "canAssignPermissions": can_assign_permissions,
        "agreements": training_agreements(organization.training_agreements) if slug == "sparta" else None,
        "today": datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date().isoformat(),
        "organization": {
            "id": organization.id, "slug": organization.slug, "name": organization.name,
            "city": organization.city, "address": organization.address, "phone": organization.phone,
            "email": organization.email, "description": organization.description,
            "logo_url": organization.logo_url,
            "cover_url": organization.cover_url,
            "vk_url": organization.vk_url,
            "telegram_url": organization.telegram_url,
            "moderation_status": organization.moderation_status,
        },
        "venues": [
            {"id": item.id, "name": item.name, "address": item.address,
             "description": item.description, "hours": item.hours, "photo_url": item.photo_url}
            for item in venue_rows
        ],
        "disciplines": [
            {"id": item.id, "name": item.name, "description": item.description, "level": item.level, "photo_url": item.photo_url}
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
        "coaches": [
            {"id": item.id, "name": item.name, "role": item.role, "tags": item.tags,
             "exp": item.experience, "about": item.bio, "photo": item.photo_url}
            for item, _ in team_coaches if membership is not None or item.id == coach.id
        ],
        "trainings": [
            {
                "id": item.code, "days": item.weekdays,
                "time": item.start_time.strftime("%H:%M"),
                "end": item.end_time.strftime("%H:%M"), "coach": item.coach, "coachId": item.coach_id,
                "gym": item.gym, "discipline": item.discipline, "active": item.is_active, "color": item.color,
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
                "time": _sport_booking_time(item, trainings_by_id.get(item.training_id)),
                "status": "new" if item.status == "pending" else item.status,
                "kind": item.kind, "participant": item.participant,
                "childName": item.child_name,
                "childAge": str(item.child_age) if item.child_age is not None else "",
                "coach": trainings_by_id[item.training_id].coach if item.training_id in trainings_by_id else "",
                "sessionId": trainings_by_id[item.training_id].code if item.training_id in trainings_by_id else "",
            }
            for item in bookings
        ],
        "payments": [_sport_payment_card(item) for item in payments],
        "team": ([
            _sport_staff_card(item, member.phone, member.full_name)
            for item, member in team_members if can_assign_permissions or (
                permissions[_SPORT_STAFF_PERMISSIONS[item.role]] and _can_manage_sport_member(membership, item)
            )
        ] + [
            _sport_staff_card(item, phone)
            for item, phone in team_coaches if permissions["manage_coaches"]
        ]) if membership is not None else [],
        "exceptions": {
            f"{item.class_date}:{code}": False
            for item, code in exception_rows
        },
        "can_manage": membership is not None,
    }


async def _sport_clients_organization(request: Request, db: AsyncSession, slug: str) -> SportOrganization:
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(404, "Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if not _can_sport(membership, "manage_bookings"):
        raise HTTPException(403, "Нет доступа к клиентам клуба")
    return organization


_SPORT_PARTICIPANT_KEY = case(
    (SportBooking.participant == "child", func.lower(func.trim(func.coalesce(SportBooking.child_name, "")))),
    else_="",
)
_SPORT_PARTICIPANT_NAME = case(
    (SportBooking.participant == "child", func.coalesce(func.nullif(SportBooking.child_name, ""), SportBooking.contact_name)),
    else_=SportBooking.contact_name,
)


@router.get("/organizations/{slug}/manage/clients")
async def list_sport_clients(
    request: Request,
    slug: str,
    search: str = Query("", max_length=160),
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    organization = await _sport_clients_organization(request, db, slug)
    participant = (SportBooking.client_id, SportBooking.participant, _SPORT_PARTICIPANT_KEY)
    directory = select(
        SportBooking.id.label("id"),
        _SPORT_PARTICIPANT_NAME.label("name"),
        SportBooking.contact_name.label("contact"),
        User.phone.label("phone"),
        SportBooking.participant.label("participant"),
        func.count().filter(SportBooking.status == "came").over(partition_by=participant).label("visits"),
        func.max(SportBooking.requested_date).filter(SportBooking.status == "came")
        .over(partition_by=participant).label("last_visit"),
        func.row_number().over(partition_by=participant, order_by=(SportBooking.created_at.desc(), SportBooking.id.desc()))
        .label("latest"),
    ).join(User, User.id == SportBooking.client_id).where(
        SportBooking.organization_id == organization.id
    ).subquery()
    query = select(directory).where(directory.c.latest == 1)
    if term := search.strip():
        matches = [directory.c.name.icontains(term, autoescape=True), directory.c.contact.icontains(term, autoescape=True)]
        phone = try_normalize_phone(term)
        digits = re.sub(r"\D", "", term)
        if digits:
            matches.append(directory.c.phone.contains(phone or digits))
        query = query.where(or_(*matches))
    rows = (await db.execute(query.order_by(func.lower(directory.c.name), directory.c.id).offset(offset).limit(limit + 1))).mappings().all()
    return {
        "clients": [{key: value for key, value in row.items() if key != "latest"} for row in rows[:limit]],
        "has_more": len(rows) > limit,
    }


@router.get("/organizations/{slug}/manage/visits/calendar")
async def get_sport_visit_calendar(
    request: Request,
    slug: str,
    month: date,
    db: AsyncSession = Depends(get_db),
):
    organization = await _sport_clients_organization(request, db, slug)
    start = month.replace(day=1)
    end = month.replace(day=monthrange(month.year, month.month)[1])
    rows = (await db.execute(
        select(SportBooking.requested_date, func.count()).where(
            SportBooking.organization_id == organization.id,
            SportBooking.status == "came",
            SportBooking.requested_date >= start,
            SportBooking.requested_date <= end,
        ).group_by(SportBooking.requested_date)
    )).all()
    return {"counts": {day.isoformat(): count for day, count in rows}}


@router.get("/organizations/{slug}/manage/visits")
async def list_sport_visits(
    request: Request,
    slug: str,
    day: date | None = None,
    client: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    organization = await _sport_clients_organization(request, db, slug)
    if (day is None) == (client is None):
        raise HTTPException(400, "Выберите дату или клиента")
    query = select(SportBooking, SportTraining, SportCoach.name).outerjoin(
        SportTraining, SportTraining.id == SportBooking.training_id
    ).outerjoin(SportCoach, SportCoach.id == SportBooking.coach_id).where(
        SportBooking.organization_id == organization.id, SportBooking.status == "came"
    )
    if day is not None:
        query = query.where(SportBooking.requested_date == day).order_by(SportBooking.requested_gym)
    else:
        anchor = (await db.execute(
            select(SportBooking.client_id, SportBooking.participant, _SPORT_PARTICIPANT_KEY).where(
                SportBooking.id == client, SportBooking.organization_id == organization.id
            )
        )).one_or_none()
        if anchor is None:
            raise HTTPException(404, "Клиент не найден")
        query = query.where(
            SportBooking.client_id == anchor[0],
            SportBooking.participant == anchor[1],
            _SPORT_PARTICIPANT_KEY == anchor[2],
        ).order_by(SportBooking.requested_date.desc().nulls_last())
    # For older visits the training time is the only available time.
    visit_time = func.coalesce(cast(SportBooking.start_time, Time), SportTraining.start_time)
    rows = (await db.execute(query.order_by(visit_time.nulls_last(), SportBooking.id).offset(offset).limit(limit + 1))).all()
    return {
        "visits": [
            {"id": booking.id,
             "name": (booking.child_name or booking.contact_name) if booking.participant == "child" else booking.contact_name,
             "date": booking.requested_date, "time": _sport_booking_time(booking, training),
             "gym": booking.requested_gym, "discipline": booking.requested_discipline,
             "coach": training.coach if training else coach_name or ""}
            for booking, training, coach_name in rows[:limit]
        ],
        "has_more": len(rows) > limit,
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
    if membership is not None and not _can_sport(membership, "manage_schedule"):
        raise HTTPException(403, "Нет прав для изменения расписания")
    if membership is None and data.exceptions:
        raise HTTPException(403, "Отменять занятия может сотрудник с доступом к расписанию клуба")
    codes = [item.id for item in data.trainings]
    if len(codes) != len(set(codes)):
        raise HTTPException(status_code=400, detail="Идентификаторы тренировок должны быть уникальными")

    training_by_code = {
        item.code: item
        for item in (await db.execute(
            select(SportTraining).where(SportTraining.organization_id == organization.id)
            .order_by(SportTraining.id).with_for_update()
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
    added_training = False
    for item in data.trainings:
        training = training_by_code.get(item.id)
        old_coach_name = training.coach if training is not None else ""
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
                color=item.color,
            )
            db.add(training)
            added_training = True
        training.weekdays = item.days
        training.start_time = item.time
        training.end_time = item.end
        training.coach = coach.name if coach is not None and membership is None else item.coach
        training.gym = item.gym
        training.discipline = item.discipline
        training.is_active = item.active
        training.color = item.color
        training.coach_id = (
            coach.id
            if coach is not None and membership is None
            else coaches_by_name[item.coach].id if item.coach in coaches_by_name
            else training.coach_id if item.coach == old_coach_name else None
        )
        training.venue_id = venues_by_address[item.gym].id if item.gym in venues_by_address else None
        training.discipline_id = disciplines_by_name[item.discipline].id if item.discipline in disciplines_by_name else None
        changed[item.id] = training

    if added_training and data.exceptions:
        await db.flush()
    for key, is_active in data.exceptions.items():
        try:
            date_text, code = key.split(":", 1)
            exception_date = date.fromisoformat(date_text)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Некорректная дата отмены")
        training = changed.get(code) or training_by_code.get(code)
        if training is None:
            raise HTTPException(status_code=400, detail="Тренировка для отмены не найдена")
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
        else:
            exception.is_cancelled = True
    await db.commit()
    return {"ok": True}


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
    if membership is not None and not _can_sport(membership, "manage_bookings"):
        raise HTTPException(403, "Нет прав для изменения заявок")
    booking = (await db.execute(
        select(SportBooking).where(
            SportBooking.id == booking_id,
            SportBooking.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if membership is None:
        assigned = booking.coach_id == coach.id or (booking.training_id is not None and await db.scalar(
            select(SportTraining.id).where(
                SportTraining.id == booking.training_id,
                SportTraining.coach_id == coach.id,
            )
        ) is not None)
        if not assigned:
            raise HTTPException(status_code=403, detail="Тренер может менять только заявки на свои занятия")
    if status_value == "came" and booking.start_time is None:
        training = await db.get(SportTraining, booking.training_id) if booking.training_id else None
        if booking.requested_date is None:
            now = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).replace(tzinfo=None)
            booking.requested_date = now.date()
            booking.start_time = now
        elif training is not None:
            booking.start_time = datetime.combine(booking.requested_date, training.start_time)
            booking.end_time = datetime.combine(booking.requested_date, training.end_time)
    booking.status = status_value
    await db.commit()
    return {"ok": True, "status": status_value,
            "date": booking.requested_date.isoformat() if booking.requested_date else "",
            "time": booking.start_time.strftime("%H:%M") if booking.start_time else ""}


async def _save_sport_staff_profile(
    db: AsyncSession,
    staff: SportCoach | SportGymMember,
    *,
    name: str,
    contact_phone: str | None,
    about: str | None,
    title: str | None,
    experience: str | None,
    tags: str | None,
    photo: UploadFile | None,
    remove_photo: bool = False,
):
    if contact_phone is not None:
        staff.contact_phone = try_normalize_phone(contact_phone) if contact_phone.strip() else None
        if contact_phone.strip() and staff.contact_phone is None:
            raise HTTPException(400, "Проверьте контактный телефон")
    if isinstance(staff, SportCoach):
        if staff.name != name and staff.id is not None:
            await db.execute(update(SportTraining).where(
                SportTraining.organization_id == staff.organization_id,
                SportTraining.coach_id == staff.id,
            ).values(coach=name))
        staff.name = name
        if title is not None:
            staff.role = title.strip() or "Тренер"
        if experience is not None:
            staff.experience = experience.strip()
        if tags is not None:
            staff.tags = tags.strip()
    else:
        staff.display_name = name
    if about is not None:
        staff.bio = about.strip()

    original_url = staff.photo_url
    uploaded_url = None
    if photo is not None:
        try:
            uploaded_url = await save_image(photo, "sport-staff")
        except UploadError as exc:
            raise HTTPException(400, str(exc)) from exc
        staff.photo_url = uploaded_url
    elif remove_photo:
        staff.photo_url = None
    try:
        await db.commit()
    except Exception:
        if uploaded_url:
            delete_stored(uploaded_url)
        raise
    if original_url and original_url != staff.photo_url and "/sport-staff/" in original_url:
        delete_stored(original_url)


@router.post("/organizations/{slug}/staff")
async def add_sport_staff(
    request: Request,
    slug: str,
    phone: str = Form(...),
    name: str = Form(...),
    role: str = Form(...),
    contact_phone: str | None = Form(None, max_length=24),
    about: str | None = Form(None, max_length=4000),
    title: str | None = Form(None, max_length=160),
    experience: str | None = Form(None, max_length=160),
    tags: str | None = Form(None, max_length=300),
    photo: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(status_code=404, detail="Спортивная организация не найдена")
    user, membership, _ = await _gym_access(request, db, organization.id)
    if role not in {"admin", "manager", "trainer", "owner"}:
        raise HTTPException(status_code=400, detail="Допустимые роли: owner, manager, admin или trainer")
    if role == "trainer" and not _can_assign_sport_permissions(membership):
        raise HTTPException(403, "Карточки тренеров на сайте редактирует владелец клуба")
    if not _can_sport(membership, _SPORT_STAFF_PERMISSIONS[role]):
        raise HTTPException(403, "Нет прав для добавления сотрудника с этой ролью")
    normalized_phone = try_normalize_phone(phone)
    name = name.strip()
    if normalized_phone is None or len(name) < 2 or len(name) > 160:
        raise HTTPException(status_code=400, detail="Проверьте имя и номер телефона")
    if normalized_phone == user.phone and role != "trainer":
        raise HTTPException(status_code=400, detail="Нельзя добавить себя отдельным сотрудником")

    staff_user = (await db.execute(
        select(User).where(User.phone == normalized_phone)
    )).scalar_one_or_none()
    credentials = None
    if staff_user is not None and not staff_user.is_active:
        raise HTTPException(409, "Аккаунт с этим номером неактивен")
    if staff_user is None:
        password = secrets.token_urlsafe(12)
        staff_user = User(
            phone=normalized_phone,
            full_name=name,
            hashed_password=get_password_hash(password),
            role=UserRole.CLIENT,
            is_active=True,
            is_guest=True,
        )
        db.add(staff_user)
        await db.flush()
        credentials = {"name": name, "login": normalized_phone, "password": password}
    elif staff_user.is_guest and not staff_user.full_name:
        staff_user.full_name = name

    if role in ("admin", "manager", "owner"):
        existing = await db.scalar(
            select(SportGymMember).where(
                SportGymMember.organization_id == organization.id,
                SportGymMember.user_id == staff_user.id,
            ).with_for_update()
        )
        if existing is not None and existing.is_active:
            raise HTTPException(status_code=409, detail="Сотрудник уже состоит в команде клуба")
        if existing is not None and existing.is_creator and role != "owner":
            raise HTTPException(403, "Нельзя изменить роль создателя")
        if role == "owner":
            perms = dict(SPORT_OWNER_PERMISSIONS)
        elif role == "manager":
            perms = dict(SPORT_MANAGER_PERMISSIONS)
        else:
            perms = dict(SPORT_ADMIN_PERMISSIONS)
        if membership and membership.role != "owner" and not membership.is_creator:
            actor_permissions = _sport_permissions(membership)
            perms = {key: allowed and actor_permissions[key] for key, allowed in perms.items()}
        if existing is not None:
            staff = existing
            staff.role = role
            staff.permissions = perms
            staff.is_active = True
        else:
            staff = SportGymMember(
                organization_id=organization.id,
                user_id=staff_user.id,
                role=role,
                permissions=perms,
                is_active=True,
                is_creator=False,
            )
            db.add(staff)
        if role == "owner" and staff_user.role == UserRole.CLIENT:
            staff_user.role = UserRole.BUSINESS
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
            staff = existing
            staff.is_active = True
        else:
            unassigned_coach = (await db.execute(
                select(SportCoach).where(
                    SportCoach.organization_id == organization.id,
                    SportCoach.name == name,
                    SportCoach.user_id.is_(None),
                    SportCoach.is_active.is_(True),
                ).order_by(SportCoach.id).limit(1).with_for_update()
            )).scalar_one_or_none()
            if unassigned_coach is not None:
                staff = unassigned_coach
                staff.user_id = staff_user.id
            else:
                last_position = await db.scalar(select(func.max(SportCoach.sort_order)).where(
                    SportCoach.organization_id == organization.id,
                    SportCoach.is_active.is_(True),
                ))
                staff = SportCoach(
                    organization_id=organization.id,
                    user_id=staff_user.id,
                    name=name,
                    role="Тренер",
                    sort_order=0 if last_position is None else last_position + 1,
                    is_active=True,
                )
                db.add(staff)
    await _save_sport_staff_profile(
        db, staff, name=name, contact_phone=contact_phone, about=about, title=title,
        experience=experience, tags=tags, photo=photo,
    )
    return JSONResponse({
        "ok": True, "role": role, "name": name, "member": _sport_staff_card(staff, staff_user.phone),
        "credentials": credentials,
    }, headers={"Cache-Control": "no-store"})


@router.put("/organizations/{slug}/staff/{role}/{staff_id}")
async def update_sport_staff(
    request: Request,
    slug: str,
    role: str,
    staff_id: int,
    name: str = Form(..., min_length=2, max_length=160),
    contact_phone: str = Form("", max_length=24),
    about: str = Form("", max_length=4000),
    title: str = Form("", max_length=160),
    experience: str = Form("", max_length=160),
    tags: str = Form("", max_length=300),
    photo: UploadFile | None = File(None),
    remove_photo: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(404, "Спортивная организация не найдена")
    user, membership, _ = await _gym_access(request, db, organization.id)
    if role not in _SPORT_STAFF_PERMISSIONS or not _can_sport(membership, _SPORT_STAFF_PERMISSIONS[role]):
        raise HTTPException(403, "Нет прав для изменения сотрудника с этой ролью")
    if role == "trainer" and not _can_assign_sport_permissions(membership):
        raise HTTPException(403, "Карточки тренеров на сайте редактирует владелец клуба")
    name = name.strip()
    if len(name) < 2:
        raise HTTPException(400, "Укажите имя сотрудника")
    if role == "trainer":
        query = select(SportCoach).where(SportCoach.id == staff_id, SportCoach.organization_id == organization.id,
                                         SportCoach.is_active.is_(True))
    elif role in {"admin", "manager", "owner"}:
        query = select(SportGymMember).where(SportGymMember.id == staff_id, SportGymMember.organization_id == organization.id,
                                             SportGymMember.is_active.is_(True), SportGymMember.role == role)
    else:
        raise HTTPException(400, "Недопустимая роль сотрудника")
    staff = await db.scalar(query.with_for_update())
    if staff is None:
        raise HTTPException(404, "Сотрудник не найден")
    if isinstance(staff, SportGymMember) and not _can_manage_sport_member(membership, staff):
        raise HTTPException(403, "Недостаточно прав для изменения этого сотрудника")
    credentials = None
    if isinstance(staff, SportCoach) and staff.user_id is None and contact_phone.strip():
        normalized_phone = try_normalize_phone(contact_phone)
        if normalized_phone is None:
            raise HTTPException(400, "Проверьте номер телефона для входа")
        staff_user = await db.scalar(select(User).where(User.phone == normalized_phone).with_for_update())
        if staff_user is not None and not staff_user.is_active:
            raise HTTPException(409, "Аккаунт с этим номером неактивен")
        if staff_user is not None:
            already_linked = await db.scalar(select(SportCoach.id).where(
                SportCoach.organization_id == organization.id,
                SportCoach.user_id == staff_user.id,
                SportCoach.is_active.is_(True),
                SportCoach.id != staff.id,
            ))
            if already_linked is not None:
                raise HTTPException(409, "Этот номер уже привязан к другому тренеру клуба")
        else:
            password = secrets.token_urlsafe(12)
            staff_user = User(
                phone=normalized_phone,
                full_name=name,
                hashed_password=get_password_hash(password),
                role=UserRole.CLIENT,
                is_active=True,
                is_guest=True,
            )
            db.add(staff_user)
            await db.flush()
            credentials = {"name": name, "login": normalized_phone, "password": password}
        staff.user_id = staff_user.id
    account_phone = await db.scalar(select(User.phone).where(User.id == staff.user_id)) if staff.user_id is not None else None
    await _save_sport_staff_profile(
        db, staff, name=name, contact_phone=contact_phone, about=about, title=title,
        experience=experience, tags=tags, photo=photo, remove_photo=remove_photo,
    )
    return JSONResponse({
        "ok": True, "member": _sport_staff_card(staff, account_phone),
        "credentials": credentials,
    }, headers={"Cache-Control": "no-store"})


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
    if role not in {"admin", "manager", "trainer", "owner"} or not _can_sport(membership, _SPORT_STAFF_PERMISSIONS[role]):
        raise HTTPException(403, "Нет прав для удаления сотрудника с этой ролью")
    if role == "trainer" and not _can_assign_sport_permissions(membership):
        raise HTTPException(403, "Карточки тренеров на сайте редактирует владелец клуба")
    if role in ("admin", "manager", "owner"):
        staff = (await db.execute(
            select(SportGymMember).where(
                SportGymMember.id == staff_id,
                SportGymMember.organization_id == organization.id,
                SportGymMember.role == role,
            ).with_for_update()
        )).scalar_one_or_none()
        if staff is not None:
            if not _can_manage_sport_member(membership, staff):
                raise HTTPException(403, "Недостаточно прав для удаления этого сотрудника")
            staff.is_active = False
    elif role == "trainer":
        staff = (await db.execute(
            select(SportCoach).where(
                SportCoach.id == staff_id,
                SportCoach.organization_id == organization.id,
            )
        )).scalar_one_or_none()
        if staff is not None:
            staff.is_active = False
            await db.execute(update(SportTraining).where(
                SportTraining.organization_id == organization.id, SportTraining.coach_id == staff.id,
            ).values(is_active=False))
    else:
        raise HTTPException(status_code=400, detail="Недопустимая роль сотрудника")
    if staff is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    await db.commit()
    staff_name = getattr(staff, "name", "")
    return {"ok": True, "role": role, "name": staff_name}


@router.post("/organizations/{slug}/manage/coaches/{coach_id}/move")
async def move_sport_coach(
    request: Request,
    slug: str,
    coach_id: int,
    direction: str = Form(..., pattern="^(up|down)$"),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(404, "Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if not _can_assign_sport_permissions(membership) or not _can_sport(membership, "manage_coaches"):
        raise HTTPException(403, "Нет прав для изменения порядка тренеров")

    # Serialize reorder requests for this club before reading the current order.
    await db.execute(select(SportOrganization.id).where(SportOrganization.id == organization.id).with_for_update())
    coaches = (await db.scalars(select(SportCoach).where(
        SportCoach.organization_id == organization.id,
        SportCoach.is_active.is_(True),
    ).order_by(SportCoach.sort_order, SportCoach.id).with_for_update())).all()
    ids = [coach.id for coach in coaches]
    if coach_id not in ids:
        raise HTTPException(404, "Тренер не найден")
    index = ids.index(coach_id)
    destination = index + (-1 if direction == "up" else 1)
    if 0 <= destination < len(coaches):
        coaches[index], coaches[destination] = coaches[destination], coaches[index]
        for position, coach in enumerate(coaches):
            coach.sort_order = position
    order = [coach.id for coach in coaches]
    await db.commit()
    return {"order": order}


@router.put("/organizations/{slug}/manage/staff/{staff_id}/permissions")
async def update_sport_staff_permissions(
    request: Request,
    slug: str,
    staff_id: int,
    permissions: dict[str, bool] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(404, "Спортивная организация не найдена")
    _, actor, _ = await _gym_access(request, db, organization.id)
    if not _can_assign_sport_permissions(actor):
        raise HTTPException(403, "Распределять права может владелец клуба")
    if permissions.keys() - (set(SPORT_PERMISSION_KEYS) - {"manage_owners"}):
        raise HTTPException(422, "Переданы недоступные права")
    staff = await db.scalar(select(SportGymMember).where(
        SportGymMember.id == staff_id,
        SportGymMember.organization_id == organization.id,
        SportGymMember.is_active.is_(True),
    ).with_for_update())
    if staff is None:
        raise HTTPException(404, "Сотрудник не найден")
    if staff.is_creator or staff.role == "owner":
        raise HTTPException(403, "Права владельца защищены")
    staff.permissions = {**(staff.permissions or {}), **permissions}
    staff_user = await db.get(User, staff.user_id)
    result = _sport_staff_card(staff, staff_user.phone, staff_user.full_name)
    await db.commit()
    return {"member": result}


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
    if not _can_sport(membership, "view_finances"):
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
    today = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date()
    payment = SportPayment(
        organization_id=organization.id,
        member_name=name,
        plan_id=plan.id,
        plan_name=plan.name,
        amount=plan.price,
        payment_date=today,
        month=month or today.strftime("%Y-%m"),
        status="pending",
        created_by_id=user.id,
    )
    db.add(payment)
    await db.commit()
    return {"ok": True, "payment": _sport_payment_card(payment)}


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
    if not _can_sport(membership, "view_finances"):
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
    if not _can_assign_sport_permissions(membership):
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
    if "phone" in data.model_fields_set:
        norm = try_normalize_phone(data.phone) if data.phone and data.phone.strip() else None
        if data.phone and data.phone.strip() and norm is None:
            raise HTTPException(status_code=400, detail="Некорректный номер телефона")
        organization.phone = norm
    for field in ("email", "logo_url", "cover_url", "vk_url", "telegram_url"):
        if field in data.model_fields_set:
            value = getattr(data, field)
            setattr(organization, field, str(value) if value else None)
    await db.commit()
    await db.refresh(organization)
    return {"ok": True, "organization": _organization_response(organization)}


async def _sport_site_owner(request: Request, db: AsyncSession, slug: str) -> SportOrganization:
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(404, "Спортивная организация не найдена")
    _, membership, _ = await _gym_access(request, db, organization.id)
    if not _can_assign_sport_permissions(membership):
        raise HTTPException(403, "Публичный сайт редактирует владелец клуба")
    return organization


def _sparta_document_data(organization: SportOrganization) -> dict:
    return {
        "documents": organization.site_documents or [],
        "agreements": training_agreements(organization.training_agreements),
    }


async def _sparta_document_owner(request: Request, db: AsyncSession, slug: str, *, lock: bool = False) -> SportOrganization:
    if slug != "sparta":
        raise HTTPException(404, "Раздел документов не найден")
    organization = await _sport_site_owner(request, db, slug)
    if lock:
        organization = (await db.execute(
            select(SportOrganization).where(SportOrganization.id == organization.id)
            .with_for_update().execution_options(populate_existing=True)
        )).scalar_one()
    return organization


@router.get("/organizations/{slug}/manage/documents")
async def get_sparta_documents(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    return _sparta_document_data(await _sparta_document_owner(request, db, slug))


@router.put("/organizations/{slug}/manage/agreements/{audience}")
async def save_sparta_agreement(
    request: Request, slug: str, audience: Literal["adult", "minor"],
    title: str = Form(..., min_length=1, max_length=200),
    text: str = Form(..., min_length=1, max_length=20000),
    db: AsyncSession = Depends(get_db),
):
    org = await _sparta_document_owner(request, db, slug, lock=True)
    if not title.strip() or not text.strip():
        raise HTTPException(400, "Введите название и текст согласия")
    org.training_agreements = {**(org.training_agreements or {}), audience: {"title": title.strip(), "text": text.strip()}}
    await db.commit()
    return _sparta_document_data(org)


async def _save_sparta_document(org, db, document_id, title, file):
    rows = list(org.site_documents or [])
    previous = next((row for row in rows if row["id"] == document_id), None) if document_id else None
    if document_id and previous is None:
        raise HTTPException(404, "Документ не найден")
    if not title.strip() or (previous is None and file is None):
        raise HTTPException(400, "Укажите название и добавьте файл")
    if previous is None and len(rows) >= 50:
        raise HTTPException(400, "В списке уже 50 документов")
    uploaded = None
    if file is not None:
        try:
            uploaded = await save_sport_document(file)
        except UploadError as exc:
            raise HTTPException(400, str(exc)) from exc
    row = {"id": document_id or secrets.token_hex(12), "title": title.strip(),
           "url": uploaded or previous["url"]}
    if previous:
        rows[rows.index(previous)] = row
    else:
        rows.append(row)
    org.site_documents = rows
    try:
        await db.commit()
    except Exception:
        if uploaded:
            delete_stored(uploaded)
        raise
    if uploaded and previous:
        delete_stored(previous["url"])
    return _sparta_document_data(org)


@router.post("/organizations/{slug}/manage/documents")
async def create_sparta_document(
    request: Request, slug: str, title: str = Form(..., max_length=200),
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
):
    org = await _sparta_document_owner(request, db, slug, lock=True)
    return await _save_sparta_document(org, db, None, title, file)


@router.put("/organizations/{slug}/manage/documents/{document_id}")
async def update_sparta_document(
    request: Request, slug: str, document_id: str, title: str = Form(..., max_length=200),
    file: UploadFile | None = File(None), db: AsyncSession = Depends(get_db),
):
    org = await _sparta_document_owner(request, db, slug, lock=True)
    return await _save_sparta_document(org, db, document_id, title, file)


@router.delete("/organizations/{slug}/manage/documents/{document_id}")
async def delete_sparta_document(request: Request, slug: str, document_id: str, db: AsyncSession = Depends(get_db)):
    org = await _sparta_document_owner(request, db, slug, lock=True)
    rows = org.site_documents or []
    previous = next((row for row in rows if row["id"] == document_id), None)
    if previous is None:
        raise HTTPException(404, "Документ не найден")
    org.site_documents = [row for row in rows if row["id"] != document_id]
    await db.commit()
    delete_stored(previous["url"])
    return _sparta_document_data(org)


@router.post("/organizations/{slug}/manage/site-photo")
async def upload_sport_site_photo(request: Request, slug: str, photo: UploadFile = File(...), section: str = Form(""), db: AsyncSession = Depends(get_db)):
    organization = await _sport_site_owner(request, db, slug)
    if section == "gallery":
        count = await db.scalar(select(func.count(SportGalleryImage.id)).where(
            SportGalleryImage.organization_id == organization.id,
            SportGalleryImage.is_active.is_(True),
        ))
        if count >= 16:
            raise HTTPException(400, "В галерее может быть не более 16 фотографий")
    try:
        return {"url": await save_image(photo, "sport-site")}
    except UploadError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _sport_site_item(request, db, slug, model, item_id):
    organization = await _sport_site_owner(request, db, slug)
    item = await db.scalar(select(model).where(
        model.id == item_id, model.organization_id == organization.id, model.is_active.is_(True),
    ).with_for_update())
    if item is None:
        raise HTTPException(404, "Запись не найдена")
    return item


async def _save_sport_site_item(db, item, data, *, omit=None):
    for key, value in data.model_dump(exclude=omit).items():
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    await db.commit()
    return {"ok": True, "id": item.id}


@router.put("/organizations/{slug}/manage/venues/{item_id}")
async def update_sport_venue(request: Request, slug: str, item_id: int, data: SportVenueCreate, db: AsyncSession = Depends(get_db)):
    item = await _sport_site_item(request, db, slug, SportVenue, item_id)
    address = data.address.strip()
    if address != item.address:
        await db.execute(update(SportTraining).where(
            SportTraining.organization_id == item.organization_id, SportTraining.gym == item.address,
        ).values(gym=address))
    return await _save_sport_site_item(db, item, data)


@router.put("/organizations/{slug}/manage/disciplines/{item_id}")
async def update_sport_discipline(request: Request, slug: str, item_id: int, data: SportDisciplineCreate, db: AsyncSession = Depends(get_db)):
    item = await _sport_site_item(request, db, slug, SportDiscipline, item_id)
    return await _save_sport_site_item(db, item, data)


@router.put("/organizations/{slug}/manage/plans/{item_id}")
async def update_sport_plan(request: Request, slug: str, item_id: int, data: SportPlanCreate, db: AsyncSession = Depends(get_db)):
    item = await _sport_site_item(request, db, slug, SportMembershipPlan, item_id)
    return await _save_sport_site_item(db, item, data, omit={"code"})


@router.put("/organizations/{slug}/manage/gallery/{item_id}")
async def update_sport_gallery_image(request: Request, slug: str, item_id: int, data: SportGalleryCreate, db: AsyncSession = Depends(get_db)):
    item = await _sport_site_item(request, db, slug, SportGalleryImage, item_id)
    return await _save_sport_site_item(db, item, data)


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
    if not _can_assign_sport_permissions(membership):
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
    if not _can_assign_sport_permissions(membership):
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
    await db.execute(update(SportTraining).where(
        SportTraining.organization_id == organization.id, SportTraining.gym == venue.address,
    ).values(is_active=False))
    await db.commit()
    return {"ok": True}


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
    if not _can_assign_sport_permissions(membership):
        raise HTTPException(status_code=403, detail="Недостаточно прав для добавления направлений")
    discipline = SportDiscipline(
        organization_id=organization.id,
        name=data.name.strip(),
        description=data.description.strip(),
        level=data.level.strip(),
        photo_url=data.photo_url,
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
    if not _can_assign_sport_permissions(membership):
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
    return {"ok": True}


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
    if not _can_assign_sport_permissions(membership):
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
    if not _can_assign_sport_permissions(membership):
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
    return {"ok": True}


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
    if not _can_assign_sport_permissions(membership):
        raise HTTPException(status_code=403, detail="Недостаточно прав для добавления фото")
    photo_count = await db.scalar(select(func.count(SportGalleryImage.id)).where(
        SportGalleryImage.organization_id == organization.id,
        SportGalleryImage.is_active.is_(True),
    ))
    if photo_count >= 16:
        raise HTTPException(status_code=400, detail="В галерее может быть не более 16 фотографий")
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
    is_self = membership is None and coach_profile is not None and coach_profile.id == coach_id
    is_admin = _can_sport(membership, "manage_schedule")
    if not (is_self or is_admin):
        raise HTTPException(status_code=403, detail="Недостаточно прав для изменения графика тренера")
    if not await db.scalar(select(SportCoach.id).where(
        SportCoach.id == coach_id, SportCoach.organization_id == organization.id,
        SportCoach.is_active.is_(True),
    )):
        raise HTTPException(404, "Тренер не найден")

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
    if not _can_sport(membership, "manage_coaches"):
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
    if not _can_assign_sport_permissions(membership):
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
    delete_stored(image.image_url)
    return {"ok": True}


# ==========================================
# 1. ЗАКРЫТИЯ КАЛЕНДАРЯ / ВЫХОДНЫЕ ТРЕНЕРОВ
# ==========================================

@router.get("/organizations/{slug}/closures")
async def list_sport_closures(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    organization = await _organization(db, slug, published_only=False)
    if organization is None:
        raise HTTPException(404, "Спортивная организация не найдена")
    _, membership, coach = await _gym_access(request, db, organization.id)
    if not _can_sport(membership, "manage_schedule") and coach is None:
        raise HTTPException(403, "Недостаточно прав")
    query = select(SportScheduleClosure).where(
        SportScheduleClosure.organization_id == organization.id,
        SportScheduleClosure.date >= datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date(),
    ).order_by(SportScheduleClosure.date).limit(500)
    if membership is None:
        query = query.where(SportScheduleClosure.coach_id == coach.id)
    rows = (await db.execute(query)).scalars().all()
    return [{"id": row.id, "coach_id": row.coach_id, "venue_id": row.venue_id,
             "date": row.date.isoformat(), "reason": row.reason} for row in rows]

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
    _, membership, _ = await _gym_access(request, db, organization.id)
    if not _can_sport(membership, "manage_schedule"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для установки закрытых дат")
    if data.coach_id is not None and not await db.scalar(select(SportCoach.id).where(
        SportCoach.id == data.coach_id, SportCoach.organization_id == organization.id,
    )):
        raise HTTPException(404, "Тренер не найден")
    if data.venue_id is not None and not await db.scalar(select(SportVenue.id).where(
        SportVenue.id == data.venue_id, SportVenue.organization_id == organization.id,
    )):
        raise HTTPException(404, "Зал не найден")

    last = data.date_to or data.date
    if last < data.date or (last - data.date).days > 90:
        raise HTTPException(400, "Период должен быть от 1 до 91 дня")
    existing = set((await db.scalars(select(SportScheduleClosure.date).where(
        SportScheduleClosure.organization_id == organization.id,
        SportScheduleClosure.coach_id == data.coach_id,
        SportScheduleClosure.venue_id == data.venue_id,
        SportScheduleClosure.date >= data.date,
        SportScheduleClosure.date <= last,
    ))).all())
    new_closures = []
    for offset in range((last - data.date).days + 1):
        closed_date = data.date + timedelta(days=offset)
        if closed_date not in existing:
            closure = SportScheduleClosure(
                organization_id=organization.id, coach_id=data.coach_id,
                venue_id=data.venue_id, date=closed_date, reason=data.reason.strip(),
            )
            db.add(closure)
            new_closures.append(closure)
    await db.flush()
    closed_coach_name = await db.scalar(select(SportCoach.name).where(
        SportCoach.id == data.coach_id, SportCoach.organization_id == organization.id,
    )) if data.coach_id is not None else None
    affected_trainings = select(SportTraining.id).where(
        SportTraining.organization_id == organization.id,
        *((or_(SportTraining.coach_id == data.coach_id, SportTraining.coach == closed_coach_name),) if data.coach_id is not None else ()),
        *((SportTraining.venue_id == data.venue_id,) if data.venue_id is not None else ()),
    )
    cancelled_bookings = await db.execute(update(SportBooking).where(
        SportBooking.organization_id == organization.id,
        SportBooking.training_id.in_(affected_trainings),
        SportBooking.requested_date >= data.date,
        SportBooking.requested_date <= last,
        SportBooking.status.in_(["pending", "new", "confirmed"]),
    ).values(status="cancelled"))
    await db.commit()
    return {"ok": True, "id": new_closures[0].id if new_closures else None,
            "date": data.date.isoformat(), "date_to": last.isoformat(),
            "reason": data.reason.strip(), "cancelled_bookings": cancelled_bookings.rowcount}


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
    if not _can_sport(membership, "manage_schedule"):
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
    return {"ok": True}


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

    user, membership, _ = await _gym_access(request, db, organization.id)

    booking = (await db.execute(
        select(SportBooking).where(
            SportBooking.id == booking_id,
            SportBooking.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    # Клиент может отменить свою запись, сотрудник — запись своего клуба при наличии права.
    is_client = booking.client_id == user.id
    is_staff = _can_sport(membership, "manage_bookings")
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

    user, membership, _ = await _gym_access(request, db, organization.id)

    booking = (await db.execute(
        select(SportBooking).where(
            SportBooking.id == booking_id,
            SportBooking.organization_id == organization.id,
        )
    )).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    is_client = booking.client_id == user.id
    is_staff = _can_sport(membership, "manage_bookings")
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
    if not _can_sport(membership, "manage_reviews"):
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
    if not _can_sport(membership, "manage_payroll"):
        raise HTTPException(403, "Нет прав для настройки вознаграждений")
    if not await db.scalar(select(SportCoach.id).where(
        SportCoach.id == coach_id, SportCoach.organization_id == organization.id,
    )):
        raise HTTPException(404, "Тренер не найден")

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
    is_mgmt = _can_sport(membership, "manage_payroll")
    is_self = coach_profile is not None and coach_profile.id == coach_id
    if not (is_mgmt or is_self):
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра финансовой сводки")
    if not await db.scalar(select(SportCoach.id).where(
        SportCoach.id == coach_id, SportCoach.organization_id == organization.id,
    )):
        raise HTTPException(404, "Тренер не найден")

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
        "notes": payroll.notes if payroll else "",
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
    accepted_agreement = None
    if organization.slug == "sparta":
        if not data.statement_consent:
            raise HTTPException(400, "Подтвердите согласие на посещение тренировок")
        audience = "minor" if data.participant == "child" else "adult"
        agreement = training_agreements(organization.training_agreements)[audience]
        if data.statement_version != agreement["version"]:
            raise HTTPException(409, "Согласие изменилось. Обновите страницу и прочитайте новый текст.")
        accepted_agreement = {**agreement, "audience": audience, "accepted_at": datetime.now(timezone.utc).isoformat()}

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
        closed_coach_ids = select(SportCoach.id).where(
            SportCoach.organization_id == organization.id, SportCoach.name == training.coach,
        )
        closed = await db.scalar(select(SportScheduleClosure.id).where(
            SportScheduleClosure.organization_id == organization.id,
            SportScheduleClosure.date == data.booking_date,
            or_(SportScheduleClosure.coach_id.is_(None),
                SportScheduleClosure.coach_id == training.coach_id,
                SportScheduleClosure.coach_id.in_(closed_coach_ids)),
            (SportScheduleClosure.venue_id.is_(None) | (SportScheduleClosure.venue_id == training.venue_id)),
        ))
        if closed is not None:
            raise HTTPException(status_code=409, detail="Тренировка отменена на эту дату")
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
        training_agreement=accepted_agreement,
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
