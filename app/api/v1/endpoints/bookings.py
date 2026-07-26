# app/api/v1/endpoints/bookings.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Body, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import timedelta, datetime, timezone as tz
from typing import List

from app.db.session import get_db
from app.models.models import Booking, Master, Service, User, BookingStatus, Review, Salon, SalonModerationStatus


async def _salon_bookable(db, master_id: int) -> bool:
    """Салон мастера одобрен и активен → к нему можно записаться.

    Пока заявка салона на модерации (pending) или отклонена — запись закрыта
    (модерация регистрации бизнеса).
    """
    row = (await db.execute(
        select(Salon.is_active, Salon.moderation_status, Salon.is_hidden, Master.is_active)
        .join(Master, Master.salon_id == Salon.id)
        .where(Master.id == master_id)
    )).first()
    # Салон одобрен, активен и не скрыт владельцем И сам мастер активен
    # (мягко удалённый — is_active=False — записи не принимает).
    return bool(row) and row[0] and row[1] == SalonModerationStatus.APPROVED and not row[2] and row[3]
from app.schemas.booking import BookingCreate, BookingResponse, BookingCancel
from app.api.deps import get_current_user, get_salon_membership
from app.services.notifications import notify_booking_cancelled, notify_booking_created
from app.services.booking_service import BookingService
from app.services.loyalty_service import LoyaltyService, LoyaltyError
from app.services.schedule_utils import get_effective_work_intervals, is_within_booking_window, MAX_BOOKING_DAYS_AHEAD
from app.utils.timezone import get_salon_time

router = APIRouter()

@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    booking_data: BookingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Создать новую запись."""
    service_result = await db.execute(select(Service).where(
        Service.id == booking_data.service_id, Service.is_active == True, Service.is_model_practice == False,
    ))
    service = service_result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    
    if service.master_id != booking_data.master_id:
        raise HTTPException(status_code=400, detail="Услуга не принадлежит этому мастеру")

    if not await _salon_bookable(db, booking_data.master_id):
        raise HTTPException(status_code=403, detail="Салон ещё не подтверждён — запись недоступна.")

    now = datetime.now()
    if booking_data.start_time.replace(tzinfo=None) < now:
        raise HTTPException(status_code=400, detail="Нельзя записаться на прошедшее время.")
    
    is_available = await BookingService.is_slot_available(
        db, booking_data.master_id,
        booking_data.start_time.replace(tzinfo=None),
        service.duration_minutes
    )
    
    if not is_available:
        raise HTTPException(status_code=409, detail="Это время уже занято")
    
    final_price = await BookingService.calculate_price(current_user, service)
    start_time = booking_data.start_time.replace(tzinfo=None)
    end_time = start_time + timedelta(minutes=service.duration_minutes)
    
    booking = Booking(
        client_id=current_user.id,
        master_id=booking_data.master_id,
        service_id=booking_data.service_id,
        start_time=start_time.replace(tzinfo=None),
        end_time=end_time.replace(tzinfo=None),
        status=BookingStatus.PENDING,
        final_price=final_price
    )
    
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    await notify_booking_created(db, booking)
    return booking

@router.get("/my", response_model=List[BookingResponse])
async def get_my_bookings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Booking).where(Booking.client_id == current_user.id).order_by(Booking.start_time.asc())
    )
    return result.scalars().all()

# POST-алиас: фронт (bookings.js) отменяет POST'ом без тела; исторический
# PATCH с BookingCancel оставлен для API-клиентов — тело стало опциональным.
@router.patch("/{booking_id}/cancel", response_model=BookingResponse)
@router.post("/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: int,
    cancel_data: Optional[BookingCancel] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Booking).where(Booking.id == booking_id, Booking.client_id == current_user.id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Запись уже отменена")
    if booking.status == BookingStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Нельзя отменить выполненную запись")
    booking.status = BookingStatus.CANCELLED
    await db.commit()
    await db.refresh(booking)
    await notify_booking_cancelled(db, booking)
    return booking

@router.get("/available/{master_id}")
async def get_available_slots(
    master_id: int,
    date: str,
    service_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Возвращает доступные слоты с учётом графика салона, услуги и перерыва."""
    
    master = (await db.execute(
        select(Master).where(Master.id == master_id, Master.is_active == True)
    )).scalar_one_or_none()
    if not master:
        return {"slots": [], "message": "Мастер не найден"}
    
    service = (await db.execute(select(Service).where(
        Service.id == service_id, Service.is_active == True,
    ))).scalar_one_or_none()
    if not service:
        return {"slots": [], "message": "Услуга не найдена"}
    
    salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
    if not salon or not salon.working_hours:
        return {"slots": [], "message": "График работы салона не задан"}

    try:
        target_date = datetime.fromisoformat(date)
    except (ValueError, TypeError):
        target_date = datetime.now()

    if not is_within_booking_window(target_date):
        return {"slots": [], "message": f"Запись открыта максимум на {MAX_BOOKING_DAYS_AHEAD} дней вперёд"}

    intervals = await get_effective_work_intervals(db, salon, master_id, target_date)
    if not intervals:
        return {"slots": [], "message": "Мастер не работает в этот день, день закрыт или график задан с ошибкой"}

    slot_duration = service.duration_minutes + master.break_minutes

    # Занятые интервалы берём за весь день — они могут попадать в любой из
    # рабочих окон мастера (при сплит-сменах их несколько).
    day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    booked = await db.execute(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.start_time >= day_start,
            Booking.start_time < day_end,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
        ).order_by(Booking.start_time)
    )
    booked_slots = booked.scalars().all()

    now = get_salon_time(salon.timezone)
    now = now.replace(tzinfo=None)

    slots = []
    for work_start, work_end in intervals:
        current = work_start
        while current + timedelta(minutes=slot_duration) <= work_end:
            slot_end = current + timedelta(minutes=slot_duration)

            if current < now:
                current += timedelta(minutes=slot_duration)
                continue

            is_free = True
            for b in booked_slots:
                b_start = b.start_time.replace(tzinfo=None) if b.start_time.tzinfo else b.start_time
                b_end = b.end_time.replace(tzinfo=None) if b.end_time.tzinfo else b.end_time
                if current < b_end and slot_end > b_start:
                    is_free = False
                    break

            if is_free:
                slots.append(current.strftime("%Y-%m-%dT%H:%M"))

            current += timedelta(minutes=slot_duration)

    return {
        "date": date,
        "slots": slots,
        "service_duration": service.duration_minutes,
        "break": master.break_minutes,
        "total_slot": slot_duration
    }

@router.get("/master-schedule", response_model=List[BookingResponse])
async def get_master_schedule(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role.value != "master":
        raise HTTPException(status_code=403, detail="Только мастер может просматривать расписание")
    result = await db.execute(select(Master).where(Master.user_id == current_user.id))
    master = result.scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=404, detail="Профиль мастера не найден")
    bookings_result = await db.execute(
        select(Booking).where(
            Booking.master_id == master.id,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
        ).order_by(Booking.start_time.asc())
    )
    return bookings_result.scalars().all()

@router.post("/bookings", response_class=HTMLResponse)
async def create_booking_web(
    request: Request,
    master_id: int = Form(...),
    start_time: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    from app.web.auth import get_current_user_from_cookie
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    result = await db.execute(select(Master).where(Master.id == master_id))
    master = result.scalar_one_or_none()
    if not master:
        return HTMLResponse(content="<h1>Мастер не найден</h1>", status_code=404)
    if not await _salon_bookable(db, master_id):
        return HTMLResponse(content="<h1>Салон ещё не подтверждён — запись недоступна</h1>", status_code=403)
    svc_result = await db.execute(select(Service).where(
        Service.master_id == master_id, Service.is_active == True, Service.is_model_practice == False,
    ).limit(1))
    service = svc_result.scalar_one_or_none()
    if not service:
        return HTMLResponse(content="<h1>У мастера пока нет услуг</h1>", status_code=400)
    try:
        start = datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
        end = start + timedelta(minutes=service.duration_minutes)
    except:
        return HTMLResponse(content="<h1>Неверный формат даты</h1>", status_code=400)
    booking = Booking(
        client_id=user.id, master_id=master_id, service_id=service.id,
        start_time=start, end_time=end, status=BookingStatus.PENDING, final_price=service.price
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    await notify_booking_created(db, booking)
    return RedirectResponse(url="/bookings?success=1", status_code=302)

@router.post("/confirm")
async def confirm_booking_web(
    request: Request,
    master_id: int = Form(...),
    service_id: int = Form(...),
    start_time: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    from app.web.auth import get_current_user_from_cookie
    
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    service = (await db.execute(select(Service).where(
        Service.id == service_id, Service.is_active == True, Service.is_model_practice == False,
    ))).scalar_one_or_none()
    if not service:
        return HTMLResponse(content="<h1>Услуга не найдена</h1>", status_code=404)
    
    try:
        start = datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
        end = start + timedelta(minutes=service.duration_minutes)
    except:
        return HTMLResponse(content="<h1>Неверный формат даты</h1>", status_code=400)
    
    # ===== ПРОВЕРКА 1: Нельзя записаться на то же время в любой салон =====
    duplicate = await db.execute(
        select(Booking).where(
            Booking.client_id == user.id,
            Booking.start_time == start,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
        )
    )
    if duplicate.scalar_one_or_none():
        return HTMLResponse(content="""
        <!DOCTYPE html><html><body style="text-align:center;padding:3rem;font-family:sans-serif">
        <h2 style="color:#e53e3e">⚠️ Вы уже записаны</h2>
        <p>У вас уже есть запись на это время в другой салон.</p>
        <a href="/bookings" style="color:#F28C6F">Мои записи</a> · 
        <a href="/salons" style="color:#F28C6F">Назад к салонам</a>
        </body></html>""", status_code=409)
    
    # ===== ПРОВЕРКА 2: Не больше 5 предстоящих записей =====
    active_count = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.client_id == user.id,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
            Booking.start_time > datetime.now()
        )
    )
    #if active_count.scalar() >= 5:
        #return HTMLResponse(content="""
        #<!DOCTYPE html><html><body style="text-align:center;padding:3rem;font-family:sans-serif">
        #<h2 style="color:#e53e3e">⚠️ Слишком много записей</h2>
        #<p>У вас уже 5 активных записей. Отмените ненужные, чтобы записаться снова.</p>
        #<a href="/bookings" style="color:#F28C6F">Мои записи</a>
        #</body></html>""", status_code=429)
    
    # ===== ПРОВЕРКА 3: Слот ещё свободен (единая проверка пересечений + рабочие часы) =====
    is_available = await BookingService.is_slot_available(db, master_id, start, service.duration_minutes)
    if not is_available:
        return HTMLResponse(content="""
        <!DOCTYPE html><html><body style="text-align:center;padding:3rem;font-family:sans-serif">
        <h2 style="color:#e53e3e">⚠️ Время занято</h2>
        <p>Кто-то уже записался на это время. Выберите другой слот.</p>
        <a href="javascript:history.back()" style="color:#F28C6F">← Назад</a>
        </body></html>""", status_code=409)
    
    if not await _salon_bookable(db, master_id):
        return HTMLResponse(content="<h1>Салон ещё не подтверждён — запись недоступна</h1>", status_code=403)

    booking = Booking(
        client_id=user.id, master_id=master_id, service_id=service_id,
        start_time=start, end_time=end, status=BookingStatus.PENDING, final_price=service.price
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    await notify_booking_created(db, booking)
    return RedirectResponse(url="/bookings?success=1", status_code=302)

# Создание отзыва вынесено в единый эндпоинт reviews.py (через ReviewService).
# Прежний дублирующий create_review_web здесь удалён — он не проверял
# завершённость записи и позволял накручивать рейтинг.


async def _can_mark_booking(db: AsyncSession, user: User, booking: Booking) -> bool:
    """Может ли user отметить эту запись выполненной/неявкой: сам мастер записи
    либо участник салона с правом manage_schedule."""
    master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
    if master is not None and master.user_id == user.id:
        return True
    membership = await get_salon_membership(db, user.id, master.salon_id if master else -1)
    return membership is not None and (
        membership.is_creator or membership.permissions.get("manage_schedule", False)
    )


class CompleteBookingRequest(BaseModel):
    """Скидка лояльности, применяемая при завершении записи. Опционально —
    без тела запись просто завершается по цене услуги, как раньше."""
    discount_choice: str = "none"  # none | regular_client | personal | promo
    promo_code: Optional[str] = None
    bonus_points_redeemed: int = 0


@router.post("/{booking_id}/complete", response_model=BookingResponse)
async def complete_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    body: Optional[CompleteBookingRequest] = Body(None),
):
    """Отметить запись выполненной — сам мастер или owner/admin салона с manage_schedule.
    Выбор скидки лояльности (в `body`) доступен только администратору салона —
    оплату оформляет он, не мастер: даже если тело запроса передано, мастеру
    по своей записи применить скидку нельзя."""
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if not await _can_mark_booking(db, current_user, booking):
        raise HTTPException(status_code=403, detail="Нет прав отмечать эту запись")

    wants_discount = body is not None and (body.discount_choice != "none" or body.bonus_points_redeemed)
    if wants_discount:
        master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
        membership = await get_salon_membership(db, current_user.id, master.salon_id if master else -1)
        is_admin = membership is not None and (
            membership.is_creator or membership.permissions.get("manage_schedule", False)
        )
        if not is_admin:
            raise HTTPException(status_code=403, detail="Скидку лояльности может применить только администратор салона")

    try:
        booking = await BookingService.complete_booking(db, booking)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if wants_discount:
        try:
            booking = await LoyaltyService.complete_with_discount(
                db, booking=booking,
                discount_choice=body.discount_choice,
                promo_code=body.promo_code,
                bonus_points_redeemed=body.bonus_points_redeemed,
                actor=current_user,
            )
        except LoyaltyError as e:
            raise HTTPException(status_code=e.status, detail=e.message)

    return booking


@router.post("/{booking_id}/no-show", response_model=BookingResponse)
async def no_show_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отметить неявку клиента — сам мастер или owner/admin салона с manage_schedule."""
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if not await _can_mark_booking(db, current_user, booking):
        raise HTTPException(status_code=403, detail="Нет прав отмечать эту запись")
    try:
        return await BookingService.mark_no_show(db, booking)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{booking_id}/mark-seen", response_model=BookingResponse)
async def mark_booking_seen(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Мастер отмечает, что видел плановую запись — только сам мастер этой
    записи (не owner/admin: это его личное подтверждение, не действие салона)."""
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
    if master is None or master.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Отметить «видел» может только сам мастер записи")
    return await BookingService.mark_seen_by_master(db, booking)


async def _email_guest_status(booking: Booking, status_text: str) -> None:
    """Письмо гостю (гостевая запись) о смене статуса — если оставлял email."""
    if not booking.guest_email:
        return
    try:
        from app.core.worker import get_arq_pool
        pool = await get_arq_pool()
        when = booking.start_time.strftime("%d.%m.%Y %H:%M") if booking.start_time else ""
        await pool.enqueue_job(
            "send_email", booking.guest_email, "Статус записи — Руми",
            f"Ваша запись {when}: {status_text}.\n\n"
            "Управление бронью — по ссылке, которую вы получили при записи на rrumi.ru.",
        )
    except Exception:
        pass


@router.post("/{booking_id}/accept", response_model=BookingResponse)
async def accept_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Салон подтверждает запись: PENDING → CONFIRMED (owner/admin/manage_schedule/мастер)."""
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if not await _can_mark_booking(db, current_user, booking):
        raise HTTPException(status_code=403, detail="Нет прав подтверждать эту запись")
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(status_code=400, detail="Запись не в статусе ожидания")
    booking.status = BookingStatus.CONFIRMED
    await db.commit()
    await db.refresh(booking)
    await _email_guest_status(booking, "подтверждена салоном ✅")
    return booking


@router.post("/{booking_id}/reject", response_model=BookingResponse)
async def reject_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Салон отклоняет/отменяет запись: → CANCELLED (owner/admin/manage_schedule/мастер)."""
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if not await _can_mark_booking(db, current_user, booking):
        raise HTTPException(status_code=403, detail="Нет прав отклонять эту запись")
    if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
        raise HTTPException(status_code=400, detail="Эту запись уже нельзя отклонить")
    booking.status = BookingStatus.CANCELLED
    await db.commit()
    await db.refresh(booking)
    await _email_guest_status(booking, "отклонена салоном")
    await notify_booking_cancelled(db, booking)
    return booking

