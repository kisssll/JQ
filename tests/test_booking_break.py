# tests/test_booking_break.py
"""Перерыв мастера: сетка окон и проверка записи должны считать одинаково.

Разошлись они так: генератор свободных окон строит сетку по
`masters.break_minutes` (мастер задаёт его сам в панели), а проверка
`BookingService.is_slot_available` добавляла к чужой записи жёсткие 15 минут.
У мастера с перерывом короче 15 человек видел окно сразу после чужой записи и
получал «Это время уже занято» — система показывала то, чего не отдавала.

На проде 04.10.2026 у всех десяти мастеров перерыв ровно 15 минут, поэтому
расхождение ещё не стреляло: оно ждало первого, кто поставит себе короче.
"""
import json
from datetime import datetime, timedelta

import pytest

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Salon, SalonModerationStatus, Service, User, UserRole,
)
from app.services.booking_service import BookingService

_WORK = json.dumps(
    {d: "08:00-22:00" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
)


async def _master_with_break(db_session, break_minutes: int, phone: str):
    """Мастер с заданным перерывом и одна чужая запись 10:00–11:00."""
    async with db_session() as db:
        owner = User(phone=phone, full_name="Мастер", role=UserRole.BUSINESS,
                     hashed_password=get_password_hash("x"))
        db.add(owner)
        await db.flush()
        salon = Salon(name="Стенд перерыва", address="Томск", city="Томск",
                      creator_id=owner.id, is_active=True,
                      moderation_status=SalonModerationStatus.APPROVED,
                      working_hours=_WORK,
                      latitude=56.5, longitude=85.0,
                      phone="+73822000000", email="stand@example.com")
        db.add(salon)
        await db.flush()
        master = Master(user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
                        experience_years=1, rating=0.0, break_minutes=break_minutes,
                        is_active=True)
        db.add(master)
        await db.flush()
        service = Service(master_id=master.id, name="Маникюр",
                          price=1000, duration_minutes=60, is_active=True)
        db.add(service)
        await db.flush()

        day = (datetime.now() + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0)
        db.add(Booking(client_id=owner.id, master_id=master.id, service_id=service.id,
                       start_time=day, end_time=day + timedelta(minutes=60),
                       status=BookingStatus.CONFIRMED))
        await db.commit()
        return master.id, day


@pytest.mark.parametrize("break_minutes,offered", [(5, True), (30, False)])
async def test_the_check_uses_the_master_s_own_break(client, db_session, break_minutes, offered):
    """Окно через 10 минут после чужой записи: при перерыве 5 минут оно
    свободно, при перерыве 30 — занято. Раньше ответ был один и тот же,
    потому что проверка всегда считала по 15."""
    master_id, booked_at = await _master_with_break(
        db_session, break_minutes, f"+7999444{break_minutes:04d}")
    probe = booked_at + timedelta(minutes=70)  # через 10 минут после конца записи

    async with db_session() as db:
        assert await BookingService.is_slot_available(db, master_id, probe, 60) is offered


async def test_booked_slots_grow_with_the_break(client, db_session):
    """Занятый интервал включает перерыв мастера, а не фиксированные 15 минут."""
    master_id, booked_at = await _master_with_break(db_session, 45, "+79994440045")
    async with db_session() as db:
        slots = await BookingService.get_booked_slots(db, master_id, booked_at)
    assert len(slots) == 1
    start, end = slots[0]
    assert end - start == timedelta(minutes=60 + 45)


async def test_a_missing_master_falls_back_to_the_default(client, db_session):
    """Мастера удалили, пока бронь висела: падать нельзя, берём значение по умолчанию."""
    async with db_session() as db:
        assert await BookingService._break_minutes(db, 10 ** 6) == \
            BookingService.DEFAULT_BREAK_MINUTES
