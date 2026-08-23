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
        pending_proration=0.0, subscription_status=SalonSubscriptionStatus.ACTIVE,
        last_downgrade_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── B2: перещёлкивание тарифов не должно копить доплату ──────────────────────

def test_plan_flip_does_not_stack_proration():
    """QA B2: lite→business→lite→business раздувал pending_proration на каждом
    повышении, а понижение не кредитовало."""
    s = _salon()
    first = register_plan_change(s, "business", 3)
    assert first > 0
    after_first = s.pending_proration

    # понижение (кредита нет — по решению Артёма), затем возврат наверх
    s.business_tier = "lite"
    second = register_plan_change(s, "business", 3)
    assert second == 0, "уровень уже оплачен — второй раз не берём"
    assert s.pending_proration == after_first, "доплата не должна расти"


def test_plan_upgrade_charges_only_the_increment():
    """Переход lite→business→corporate = разница lite→corporate, а не сумма
    двух полных доплат."""
    step = _salon()
    register_plan_change(step, "business", 3)
    register_plan_change(step, "corporate", 3)

    direct = _salon()
    register_plan_change(direct, "corporate", 3)

    assert abs(step.pending_proration - direct.pending_proration) < 0.02


def test_no_charge_for_plan_change_on_trial():
    s = _salon(subscription_status=SalonSubscriptionStatus.TRIALING)
    assert register_plan_change(s, "corporate", 3) == 0
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
