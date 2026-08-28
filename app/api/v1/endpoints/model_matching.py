# app/api/v1/endpoints/model_matching.py
"""Мэтчинг «модель ↔ конкретная опубликованная услуга»: профиль модели,
свайпы (обе стороны), создание записи после выбора реального свободного
слота в расписании мастера. Оффера как отдельного шага нет — цена и
длительность уже заданы услугой на момент публикации. См.
app/services/model_matching_service.py для общей логики выборок/свайпов."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_salon_permission, get_current_user, require_approved_model, require_is_model
from app.db.session import get_db
from app.models.models import (
    Booking, BookingStatus, Master, ModelMatch, ModelMatchStatus, ModelModerationStatus, Service, User,
)
from app.services.booking_service import BookingService
from app.services.model_matching_service import (
    count_booked_for_service, get_active_matches_for_model, get_candidate_models, get_feed_cards,
    get_history_for_model, get_invitations_for_model, get_salon_matches, is_service_open_for_models, record_swipe,
)
from app.services.notifications import notify_booking_cancelled, notify_booking_created, notify_model_match
from app.services.uploads import UploadError, delete_stored, save_image

router = APIRouter()


# ── Профиль модели ────────────────────────────────────────────────────────

@router.post("/profile")
async def upsert_model_profile(
    bio: str = Form(""),
    looking_for: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Включает статус «модель» и сохраняет анкету. Идемпотентно — тем же
    эндпоинтом модель потом редактирует профиль.

    Модерация (см. ModelModerationStatus) ставится в PENDING только при
    первом включении — повторные правки уже одобренной анкеты не отправляют
    её на повторную проверку (как и у салонов)."""
    was_model = current_user.is_model

    if photo is not None and photo.filename:
        try:
            url = await save_image(photo, "models")
        except UploadError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        old = current_user.model_photo_url
        current_user.model_photo_url = url
        if old and old.startswith("/uploads/"):
            delete_stored(old)

    current_user.is_model = True
    current_user.model_bio = bio or None
    current_user.model_looking_for = looking_for or None
    if not was_model:
        current_user.model_moderation_status = ModelModerationStatus.PENDING
        current_user.model_rejection_reason = None
    await db.commit()
    return {
        "status": "ok", "is_model": True, "model_photo_url": current_user.model_photo_url,
        "moderation_status": current_user.model_moderation_status.value,
    }


# ── Лента модели ──────────────────────────────────────────────────────────

@router.get("/feed")
async def get_feed(
    current_user: User = Depends(require_approved_model),
    db: AsyncSession = Depends(get_db),
):
    return await get_feed_cards(db, current_user.id)


@router.get("/invitations")
async def get_invitations(
    current_user: User = Depends(require_approved_model),
    db: AsyncSession = Depends(get_db),
):
    """Услуги, чей салон лайкнул модель первым — она ещё не ответила."""
    return await get_invitations_for_model(db, current_user.id)


@router.get("/history")
async def get_history(
    current_user: User = Depends(require_is_model),
    db: AsyncSession = Depends(get_db),
):
    """Мэтчи, дошедшие до записи — прошедшие и предстоящие визиты.

    Не гейтим require_approved_model — если анкету потом отклонили, старая
    история визитов всё равно должна остаться видна."""
    return await get_history_for_model(db, current_user.id)


class SwipeRequest(BaseModel):
    like: bool


@router.post("/feed/{service_id}/swipe")
async def swipe_service(
    service_id: int,
    payload: SwipeRequest,
    current_user: User = Depends(require_approved_model),
    db: AsyncSession = Depends(get_db),
):
    service = (await db.execute(
        select(Service).where(Service.id == service_id, Service.is_model_practice == True)  # noqa: E712
    )).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Услуга не найдена")

    match, is_fresh_match = await record_swipe(
        db, model_user_id=current_user.id, service_id=service_id,
        like=payload.like, actor="model",
    )
    if is_fresh_match:
        await notify_model_match(db, match)
    return {"status": match.status.value}


@router.get("/matches")
async def get_my_matches(
    current_user: User = Depends(require_is_model),
    db: AsyncSession = Depends(get_db),
):
    """Мэтчи модели, ожидающие выбора слота (взаимный лайк уже есть)."""
    return await get_active_matches_for_model(db, current_user.id)


class AcceptSlotRequest(BaseModel):
    slot: datetime


@router.post("/matches/{match_id}/accept-slot")
async def accept_slot(
    match_id: int,
    payload: AcceptSlotRequest,
    current_user: User = Depends(require_is_model),
    db: AsyncSession = Depends(get_db),
):
    """Модель выбирает реальный свободный слот в расписании мастера —
    цена/услуга уже зафиксированы мэтчем, здесь только время и проверка,
    что оно правда свободно (see /api/v1/bookings/available для списка)."""
    match = (await db.execute(select(ModelMatch).where(ModelMatch.id == match_id))).scalar_one_or_none()
    if match is None or match.model_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мэтч не найден")
    if match.status != ModelMatchStatus.MATCHED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Мэтч не в состоянии, допускающем запись")

    service = (await db.execute(
        select(Service).where(Service.id == match.service_id, Service.is_active == True)  # noqa: E712
    )).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Услуга недоступна")

    if not await BookingService.is_slot_available(db, match.master_id, payload.slot, service.duration_minutes):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Это время уже занято")

    end_time = payload.slot + timedelta(minutes=service.duration_minutes)
    booking = Booking(
        client_id=match.model_user_id, master_id=match.master_id, service_id=service.id,
        start_time=payload.slot, end_time=end_time, status=BookingStatus.PENDING,
        final_price=service.price,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    match.status = ModelMatchStatus.BOOKED
    match.booking_id = booking.id
    match.chosen_slot = payload.slot
    await db.commit()

    await notify_booking_created(db, booking)
    return {"status": "booked", "booking_id": booking.id}


@router.post("/matches/{match_id}/decline")
async def decline_match(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отклонение мэтча — с любой стороны (модель сама, либо участник
    салона с правом manage_masters на мастере этого мэтча)."""
    match = (await db.execute(select(ModelMatch).where(ModelMatch.id == match_id))).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мэтч не найден")

    if match.model_user_id == current_user.id:
        declined_by = "model"
    else:
        await check_salon_permission(db, current_user, match.salon_id, "manage_masters")
        declined_by = "salon"

    if match.status == ModelMatchStatus.DECLINED:
        return {"status": "declined"}  # идемпотентно — повторный decline не ошибка

    # Если по мэтчу уже создана бронь (BOOKED) — отменяем её, иначе останется
    # «осиротевшая» активная запись при отменённом мэтче.
    if match.status == ModelMatchStatus.BOOKED and match.booking_id is not None:
        booking = (await db.execute(select(Booking).where(Booking.id == match.booking_id))).scalar_one_or_none()
        if booking is not None and booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            booking.status = BookingStatus.CANCELLED
            await db.flush()
            await notify_booking_cancelled(db, booking)

    match.status = ModelMatchStatus.DECLINED
    match.declined_by = declined_by
    match.declined_at = datetime.now().astimezone()
    await db.commit()
    return {"status": "declined"}


# ── Сторона салона ────────────────────────────────────────────────────────

class ServiceSeekingRequest(BaseModel):
    model_quota: Optional[int] = None
    model_seeking_open: bool = True


@router.patch("/services/{service_id}/seeking")
async def set_service_seeking(
    service_id: int,
    payload: ServiceSeekingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Квота моделей на конкретную услугу + ручной рубильник открыто/закрыто —
    определяет, видна ли эта услуга в ленте моделей (см. get_feed_cards)."""
    service = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Услуга не найдена")
    master = (await db.execute(select(Master).where(Master.id == service.master_id))).scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мастер не найден")
    await check_salon_permission(db, current_user, master.salon_id, "manage_masters")
    if payload.model_quota is not None and payload.model_quota < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Квота должна быть не меньше 1")

    service.model_quota = payload.model_quota
    service.model_seeking_open = payload.model_seeking_open
    await db.commit()
    booked_count = await count_booked_for_service(db, service.id)
    return {
        "status": "ok", "model_quota": service.model_quota, "model_seeking_open": service.model_seeking_open,
        "booked_count": booked_count, "is_open": is_service_open_for_models(service, booked_count),
    }


@router.get("/services/{service_id}/candidates")
async def list_candidates(
    service_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Услуга не найдена")
    master = (await db.execute(select(Master).where(Master.id == service.master_id))).scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мастер не найден")
    await check_salon_permission(db, current_user, master.salon_id, "manage_masters")
    return await get_candidate_models(db, service_id)


@router.post("/services/{service_id}/candidates/{model_user_id}/swipe")
async def swipe_candidate(
    service_id: int,
    model_user_id: int,
    payload: SwipeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Услуга не найдена")
    master = (await db.execute(select(Master).where(Master.id == service.master_id))).scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мастер не найден")
    await check_salon_permission(db, current_user, master.salon_id, "manage_masters")

    model_user = (await db.execute(select(User).where(
        User.id == model_user_id, User.is_model == True, User.model_moderation_status == ModelModerationStatus.APPROVED,  # noqa: E712
    ))).scalar_one_or_none()
    if model_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Анкета не найдена")

    match, is_fresh_match = await record_swipe(
        db, model_user_id=model_user_id, service_id=service_id,
        like=payload.like, actor="salon", actor_id=current_user.id,
    )
    if is_fresh_match:
        await notify_model_match(db, match)
    return {"status": match.status.value}


@router.get("/salon/{salon_id}/matches")
async def list_salon_matches(
    salon_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_masters")
    return await get_salon_matches(db, salon_id)
