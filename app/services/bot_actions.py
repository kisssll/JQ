"""Действия из ботов: свои записи, отмена, отзыв после визита.

Логика одна на Telegram и MAX — различается только рисование кнопок. Держим
её здесь, чтобы правила («какие записи показывать», «можно ли отменить»)
не разъехались между двумя ботами.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Сколько ближайших записей показываем в боте: список должен помещаться в
# одно сообщение и оставаться обозримым.
UPCOMING_LIMIT = 5

# Через сколько после визита просим отзыв. Человек успел уйти, впечатление
# ещё свежее.
REVIEW_DELAY = timedelta(hours=2)


async def upcoming_bookings(db, user_id: int, limit: int = UPCOMING_LIMIT) -> list:
    """Ближайшие активные записи клиента: (booking, salon, master_name, service)."""
    from sqlalchemy import select

    from app.models.models import (
        Booking, BookingStatus, Master, Salon, Service, User,
    )

    # Booking.start_time хранится БЕЗ часового пояса (DateTime(timezone=False)),
    # поэтому сравниваем с таким же наивным «сейчас» — aware-значение asyncpg
    # просто не примет. Зона берётся продуктовая, как и в остальных выборках
    # по записям (панель салона, аналитика).
    from app.utils.timezone import get_salon_time

    now = get_salon_time().replace(tzinfo=None)
    rows = (await db.execute(
        select(Booking, Salon, Service, User.full_name)
        .join(Master, Booking.master_id == Master.id)
        .join(Salon, Master.salon_id == Salon.id)
        .join(Service, Booking.service_id == Service.id)
        .join(User, Master.user_id == User.id, isouter=True)
        .where(
            Booking.client_id == user_id,
            Booking.start_time >= now,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
        .order_by(Booking.start_time)
        .limit(limit)
    )).all()
    return rows


def format_booking(booking, salon, service, master_name: Optional[str]) -> str:
    who = f" · {master_name}" if master_name else ""
    return (f"📅 {booking.start_time:%d.%m в %H:%M} — «{salon.name}»\n"
            f"{service.name}{who} · {service.price:,} ₽".replace(",", " "))


async def cancel_booking(db, user_id: int, booking_id: int) -> tuple[bool, str]:
    """Отменить свою запись из бота. → (получилось, что сказать человеку).

    Правила те же, что на сайте: отменить можно любую активную запись,
    временного окна нет. Разные правила в разных каналах путают людей, а
    вводить окно — решение про политику салона, а не про бота.
    """
    from sqlalchemy import select

    from app.models.models import Booking, BookingStatus

    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )).scalar_one_or_none()
    if booking is None:
        return False, "Запись не найдена."
    if booking.client_id != user_id:
        # Чужую запись не отменяем и не подтверждаем сам факт её наличия.
        return False, "Запись не найдена."
    if booking.status == BookingStatus.CANCELLED:
        return False, "Эта запись уже отменена."
    if booking.status == BookingStatus.COMPLETED:
        return False, "Визит уже состоялся — отменить нельзя."

    booking.status = BookingStatus.CANCELLED
    await db.commit()

    try:
        from app.services.notifications import notify_booking_cancelled

        await notify_booking_cancelled(db, booking)
    except Exception:
        logger.exception("bot: салон не уведомлён об отмене записи %s", booking_id)

    return True, "Запись отменена. Салон получил уведомление."


async def schedule_review_request(booking_id: int) -> None:
    """Поставить отложенный вопрос об отзыве после отметки «Пришёл».

    _job_id по booking_id: повторная отметка не должна слать второй вопрос.
    Сбой планировщика не должен ронять саму отметку посещения.
    """
    try:
        from app.core.worker import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job(
            "ask_for_review", booking_id,
            _job_id=f"review-request:{booking_id}",
            _defer_by=REVIEW_DELAY,
        )
    except Exception:
        logger.exception("bot: не поставлен вопрос об отзыве по записи %s", booking_id)


async def review_already_left(db, user_id: int, booking_id: int) -> bool:
    """Отзыв по этой записи уже есть — повторно не спрашиваем."""
    from sqlalchemy import select

    from app.models.models import Review

    return (await db.execute(
        select(Review.id).where(
            Review.booking_id == booking_id, Review.client_id == user_id,
        )
    )).scalars().first() is not None


async def save_review(db, *, user_id: int, booking_id: int, rating: int,
                      comment: str = "") -> tuple[bool, str]:
    """Отзыв из бота. Идёт через ReviewService — он сам проверит визит,
    проставит is_verified и пересчитает рейтинги салона и мастера."""
    from sqlalchemy import select

    from app.models.models import Booking, Master, ReviewTargetType
    from app.services.review_service import ReviewError, ReviewService

    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )).scalar_one_or_none()
    if booking is None or booking.client_id != user_id:
        return False, "Запись не найдена."

    master = (await db.execute(
        select(Master).where(Master.id == booking.master_id)
    )).scalar_one_or_none()
    if master is None:
        return False, "Мастер больше не работает в салоне — отзыв не сохранить."

    try:
        await ReviewService.create_review(
            db, client_id=user_id, salon_id=master.salon_id,
            target_type=ReviewTargetType.MASTER, rating=rating,
            comment=comment, master_id=master.id, booking_id=booking_id,
        )
    except ReviewError as exc:
        return False, str(exc)

    return True, "Спасибо! Отзыв опубликован."
