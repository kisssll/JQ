# app/api/v1/endpoints/guest.py
"""Запись без регистрации (гостевая, по ссылке/QR).

Гость вводит имя+телефон(+email опц.), выбирает мастера/услугу/слот. Бронь
создаётся PENDING — салон подтверждает/отклоняет её вручную (модерация).
Пользователь заводится/переиспользуется по номеру (is_guest); при регистрации
этим номером аккаунт «забирается» (см. auth_web.register_web).
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import (
    User, UserRole, Salon, Master, Service, Booking, BookingStatus,
    SalonModerationStatus,
)
from app.schemas.user import try_normalize_phone
from app.core.security import get_password_hash
from app.core.limiter import limiter
from app.services.booking_service import BookingService
from app.services.notifications import notify_booking_created, send_guest_booking_email

router = APIRouter()


class GuestBookingRequest(BaseModel):
    salon_id: int
    master_id: int
    service_id: int
    start_time: datetime
    name: str
    phone: str
    email: Optional[str] = None


@router.post("/booking")
@limiter.limit("5/minute")
async def create_guest_booking(
    request: Request,
    data: GuestBookingRequest,
    db: AsyncSession = Depends(get_db),
):
    """Создать гостевую бронь (PENDING). Возвращает токен управления."""
    norm_phone = try_normalize_phone(data.phone)
    if not norm_phone:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона")
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите имя")

    salon = (await db.execute(select(Salon).where(Salon.id == data.salon_id))).scalar_one_or_none()
    if (
        not salon
        or not salon.is_active
        or salon.moderation_status != SalonModerationStatus.APPROVED
        or salon.published_at is None
    ):
        raise HTTPException(status_code=404, detail="Салон недоступен")
    if not salon.guest_booking_enabled:
        raise HTTPException(status_code=403, detail="Салон не принимает записи без регистрации")

    service = (await db.execute(
        select(Service).where(
            Service.id == data.service_id, Service.is_active == True, Service.is_model_practice == False,
        )
    )).scalar_one_or_none()
    if not service or service.master_id != data.master_id:
        raise HTTPException(status_code=400, detail="Услуга недоступна")

    master = (await db.execute(
        select(Master).where(
            Master.id == data.master_id,
            Master.is_active == True,
            Master.salon_id == salon.id,
        )
    )).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=400, detail="Мастер недоступен")

    start = data.start_time.replace(tzinfo=None)
    if start < datetime.now():
        raise HTTPException(status_code=400, detail="Нельзя записаться на прошедшее время")

    if not await BookingService.is_slot_available(db, data.master_id, start, service.duration_minutes):
        raise HTTPException(status_code=409, detail="Это время уже занято")

    # Reuse/create пользователя по номеру. Номер уникален — дубль невозможен;
    # существующий (гость ИЛИ реальный) переиспользуется.
    user = (await db.execute(select(User).where(User.phone == norm_phone))).scalar_one_or_none()
    if user is None:
        user = User(
            phone=norm_phone,
            full_name=name,
            hashed_password=get_password_hash(secrets.token_hex(32)),
            role=UserRole.CLIENT,
            is_active=True,
            is_guest=True,
        )
        db.add(user)
        await db.flush()
    elif user.is_guest and not user.full_name:
        user.full_name = name

    token = secrets.token_urlsafe(32)
    end = start + timedelta(minutes=service.duration_minutes)
    booking = Booking(
        client_id=user.id,
        master_id=data.master_id,
        service_id=data.service_id,
        start_time=start,
        end_time=end,
        status=BookingStatus.PENDING,
        final_price=service.price,  # без лояльности/подписки для гостя
        guest_manage_token=token,
        guest_email=(data.email or "").strip().lower() or None,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    await notify_booking_created(db, booking)  # салон/мастер узнают о заявке
    # Гостю (если оставил email) — письмо со ссылкой отслеживания статуса.
    await send_guest_booking_email(
        db, booking, str(request.base_url),
        "Заявка на запись создана",
        "Мы приняли вашу заявку — салон скоро её подтвердит, и вы получите ещё одно "
        "письмо. Следить за статусом записи можно по кнопке ниже.",
    )

    return {"status": "pending", "booking_id": booking.id, "manage_token": token}


@router.post("/booking/{token}/cancel")
@limiter.limit("10/minute")
async def cancel_guest_booking(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    """Отмена гостевой брони по токену управления (без аккаунта)."""
    from app.services.notifications import notify_booking_cancelled

    booking = (await db.execute(
        select(Booking).where(Booking.guest_manage_token == token)
    )).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Бронь не найдена")
    if booking.status == BookingStatus.CANCELLED:
        return {"status": "cancelled"}
    if booking.status in (BookingStatus.COMPLETED, BookingStatus.NO_SHOW):
        raise HTTPException(status_code=400, detail="Эту запись уже нельзя отменить")

    booking.status = BookingStatus.CANCELLED
    await db.commit()
    await db.refresh(booking)
    await notify_booking_cancelled(db, booking)
    return {"status": "cancelled"}
