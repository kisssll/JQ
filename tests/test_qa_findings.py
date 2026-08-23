"""Регрессы по отчёту QA (стейдж, 23.08.2026).

Каждый тест закрывает конкретную находку — чтобы она не вернулась.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Salon, SalonModerationStatus,
    SalonSubscriptionStatus, Service, User, UserRole,
)
from app.services.booking_service import can_mark_no_show_now
from app.services.subscription import register_plan_change, register_headcount


def _salon(**kw):
    base = dict(
        business_tier="lite", billed_plan="lite", billed_masters=3,
        prorated_masters=3, proration_from=datetime(2026, 5, 10, tzinfo=timezone.utc),
        pending_proration=0.0, subscription_status=SalonSubscriptionStatus.ACTIVE,
        last_downgrade_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── B2: перещёлкивание тарифов не должно копить доплату ──────────────────────

def test_plan_flip_does_not_stack_proration():
    """QA B2: lite→business→lite→business раздувал доплату на каждом повышении.

    Теперь доплата капает по дням фактического превышения, а планка тарифа не
    даёт взять дважды за один и тот же уровень.
    """
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon()
    register_plan_change(s, "business", 3, at=t0)
    assert s.business_tier == "business"
    assert s.billed_plan == "lite"      # оплачен по-прежнему Лайт

    # день на повышенном тарифе — доплата за день
    register_plan_change(s, "lite", 3, at=t0 + timedelta(days=1))
    after_one_day = s.pending_proration
    assert after_one_day > 0

    # возврат наверх и обратно в тот же момент — ничего не добавилось
    register_plan_change(s, "business", 3, at=t0 + timedelta(days=1))
    register_plan_change(s, "lite", 3, at=t0 + timedelta(days=1))
    assert s.pending_proration == after_one_day

def test_plan_upgrade_charges_only_the_increment():
    """Путь lite→business→corporate стоит столько же, сколько сразу corporate:
    платим за фактическое время на каждом уровне, а не за каждый переход."""
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    step = _salon()
    register_plan_change(step, "corporate", 3, at=t0)
    register_plan_change(step, "corporate", 3, at=t0 + timedelta(days=3))

    direct = _salon()
    register_plan_change(direct, "corporate", 3, at=t0)
    register_plan_change(direct, "corporate", 3, at=t0 + timedelta(days=3))

    assert abs(step.pending_proration - direct.pending_proration) < 0.02


def test_no_charge_for_plan_change_on_trial():
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon(subscription_status=SalonSubscriptionStatus.TRIALING)
    register_plan_change(s, "corporate", 3, at=t0)
    register_plan_change(s, "corporate", 3, at=t0 + timedelta(days=5))
    assert s.pending_proration == 0.0


def test_payment_resets_plan_watermark():
    """После оплаты планка едет за фактическим тарифом (в т.ч. вниз)."""
    from app.services.subscription import apply_successful_payment

    s = _salon(billed_plan="corporate", business_tier="lite", pending_proration=500.0)
    apply_successful_payment(s, datetime.now(timezone.utc) + timedelta(days=30), active_masters=3)
    assert s.billed_plan == "lite"
    assert s.pending_proration == 0.0


# ── S1: неявку нельзя отметить до начала записи ──────────────────────────────

def test_no_show_gate_blocks_future_booking():
    """QA S1: no-show ставился за сутки до визита и освобождал слот."""
    future = SimpleNamespace(start_time=datetime.now() + timedelta(days=1))
    started = SimpleNamespace(start_time=datetime.now() - timedelta(minutes=1))
    assert can_mark_no_show_now(future, "Asia/Novosibirsk") is False
    assert can_mark_no_show_now(started, "Asia/Novosibirsk") is True


# ── R1: гонка за слот ────────────────────────────────────────────────────────

async def _setup_slot(db_session):
    async with db_session() as db:
        owner = User(phone="+79993330001", full_name="В",
                     hashed_password=get_password_hash("Bizpass1"), role=UserRole.BUSINESS)
        client = User(phone="+79993330002", full_name="К",
                      hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        db.add_all([owner, client])
        await db.commit()
        await db.refresh(owner); await db.refresh(client)

        salon = Salon(name="ГонкаZZ", address="Т", phone="+70000001000",
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      creator_id=owner.id, is_active=True,
                      moderation_status=SalonModerationStatus.APPROVED)
        db.add(salon)
        await db.commit(); await db.refresh(salon)

        master = Master(user_id=owner.id, salon_id=salon.id, specialization="м")
        db.add(master)
        await db.commit(); await db.refresh(master)

        svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(svc)
        await db.commit(); await db.refresh(svc)
        return client.id, master.id, svc.id


async def test_db_rejects_second_booking_on_same_slot(db_session):
    """QA R1: проверка занятости и вставка не атомарны — теперь второй бронью
    на тот же слот занимается сама БД (частичный уникальный индекс)."""
    from sqlalchemy.exc import IntegrityError

    client_id, master_id, service_id = await _setup_slot(db_session)
    start = (datetime.now() + timedelta(days=1)).replace(hour=11, minute=30, second=0, microsecond=0)

    async with db_session() as db:
        db.add(Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                       start_time=start, end_time=start + timedelta(hours=1),
                       status=BookingStatus.PENDING, final_price=1000))
        await db.commit()

    async with db_session() as db:
        db.add(Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                       start_time=start, end_time=start + timedelta(hours=1),
                       status=BookingStatus.PENDING, final_price=1000))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_cancelled_booking_frees_the_slot(db_session):
    """Индекс не должен мешать записаться заново после отмены."""
    client_id, master_id, service_id = await _setup_slot(db_session)
    start = (datetime.now() + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)

    async with db_session() as db:
        b = Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                    start_time=start, end_time=start + timedelta(hours=1),
                    status=BookingStatus.PENDING, final_price=1000)
        db.add(b)
        await db.commit()
        b.status = BookingStatus.CANCELLED
        await db.commit()

    async with db_session() as db:  # тот же слот снова свободен
        db.add(Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                       start_time=start, end_time=start + timedelta(hours=1),
                       status=BookingStatus.PENDING, final_price=1000))
        await db.commit()


# ── B1 (смягчено): доплата по фактически отработанным дням ───────────────────

def test_hire_and_fire_same_day_costs_nothing():
    """QA B1: нанял и в тот же день уволил — счёт не должен вырасти."""
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon(billed_masters=3, prorated_masters=3, proration_from=t0)

    register_headcount(s, 4, at=t0)                      # нанял
    register_headcount(s, 3, at=t0)                      # и сразу убрал
    assert s.pending_proration == 0.0


def test_short_hire_costs_only_days_worked():
    """Мастер проработал 3 дня из 30 — платим примерно за 3 дня, а не за месяц."""
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon(billed_masters=3, prorated_masters=3, proration_from=t0)

    register_headcount(s, 4, at=t0)
    register_headcount(s, 3, at=t0 + timedelta(days=3))
    # Лайт: 4-й мастер = +250 ₽/мес → 3 дня ≈ 25 ₽
    assert abs(s.pending_proration - 25.0) < 0.5

    # дальше штат вернулся к оплаченному — доплата больше не растёт
    register_headcount(s, 3, at=t0 + timedelta(days=20))
    assert abs(s.pending_proration - 25.0) < 0.5


def test_settle_adds_the_final_stretch():
    """Перед счётом досчитываем отрезок с последнего изменения до оплаты."""
    from app.services.subscription import settle_proration

    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon(billed_masters=3, prorated_masters=3, proration_from=t0)
    register_headcount(s, 4, at=t0)
    total = settle_proration(s, at=t0 + timedelta(days=6))
    assert abs(total - 50.0) < 0.5      # 6 дней × (250/30)


async def test_overlapping_bookings_rejected_by_db(db_session):
    """Полная атомарная защита: пересечение с ДРУГИМ временем начала.

    Уникальный индекс ловил только совпадение start_time — 11:30–12:30 и
    12:00–12:30 у одного мастера проходили. Теперь пересечение любых видов
    невозможно на уровне БД (EXCLUDE gist по диапазону).
    """
    from sqlalchemy.exc import IntegrityError

    client_id, master_id, service_id = await _setup_slot(db_session)
    base = (datetime.now() + timedelta(days=3)).replace(hour=11, minute=30, second=0, microsecond=0)

    async with db_session() as db:
        db.add(Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                       start_time=base, end_time=base + timedelta(hours=1),
                       status=BookingStatus.PENDING, final_price=1000))
        await db.commit()

    async with db_session() as db:  # начинается позже, но внутри занятого часа
        db.add(Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                       start_time=base + timedelta(minutes=30),
                       end_time=base + timedelta(hours=1),
                       status=BookingStatus.PENDING, final_price=1000))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_adjacent_bookings_are_allowed(db_session):
    """Встык (конец одной = начало другой) — не пересечение, должно проходить."""
    client_id, master_id, service_id = await _setup_slot(db_session)
    base = (datetime.now() + timedelta(days=4)).replace(hour=9, minute=0, second=0, microsecond=0)

    async with db_session() as db:
        db.add(Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                       start_time=base, end_time=base + timedelta(hours=1),
                       status=BookingStatus.PENDING, final_price=1000))
        await db.commit()

    async with db_session() as db:
        db.add(Booking(client_id=client_id, master_id=master_id, service_id=service_id,
                       start_time=base + timedelta(hours=1),
                       end_time=base + timedelta(hours=2),
                       status=BookingStatus.PENDING, final_price=1000))
        await db.commit()   # не должно упасть
