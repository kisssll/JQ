"""Ограничение по времени на отметку «Пришёл» (complete).

«Пришёл» нельзя отметить раньше, чем за час до начала записи. «Не пришёл»
(no-show) этим гейтом не ограничен. Время — салонно-локальное (start_time
хранится наивным в зоне салона).
"""
from datetime import timedelta

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonModerationStatus, Master, Service, Booking, BookingStatus,
)
from app.services.booking_service import can_mark_completed_now
from app.utils.timezone import get_salon_time

TZ = "Europe/Moscow"


async def _setup(db_session, master_phone, start_offset, status=BookingStatus.CONFIRMED):
    async with db_session() as db:
        master_user = User(phone=master_phone, full_name="Мастер",
                           hashed_password=get_password_hash("Testpass1"), role=UserRole.MASTER)
        client_user = User(phone=master_phone.replace("+7999", "+7988"), full_name="Клиент",
                           hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        db.add_all([master_user, client_user])
        await db.commit()
        await db.refresh(master_user)
        await db.refresh(client_user)
        salon = Salon(name="S", description="", address="Москва, ул. 1",
                      latitude=55.75, longitude=37.61, phone="+70000000000",
                      is_active=True, moderation_status=SalonModerationStatus.APPROVED, timezone=TZ)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        master = Master(user_id=master_user.id, salon_id=salon.id, specialization="м")
        db.add(master)
        await db.commit()
        await db.refresh(master)
        svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)
        start = get_salon_time(TZ).replace(tzinfo=None) + start_offset
        booking = Booking(client_id=client_user.id, master_id=master.id, service_id=svc.id,
                          start_time=start, end_time=start + timedelta(minutes=60), status=status)
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        return master_phone, booking.id


async def _login(client, phone, pw="Testpass1"):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": pw})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])


async def _status(db_session, bid):
    async with db_session() as db:
        return (await db.execute(select(Booking.status).where(Booking.id == bid))).scalar_one()


# ── Серверный гейт ───────────────────────────────────────────────────────────

async def test_complete_blocked_more_than_hour_before(client, db_session):
    phone, bid = await _setup(db_session, "+79995553001", timedelta(hours=2))
    await _login(client, phone)
    r = await client.post(f"/api/v1/bookings/{bid}/complete")
    assert r.status_code == 409, r.text
    assert await _status(db_session, bid) == BookingStatus.CONFIRMED  # не изменился


async def test_complete_allowed_within_hour(client, db_session):
    phone, bid = await _setup(db_session, "+79995553002", timedelta(minutes=30))
    await _login(client, phone)
    r = await client.post(f"/api/v1/bookings/{bid}/complete")
    assert r.status_code == 200, r.text
    assert await _status(db_session, bid) == BookingStatus.COMPLETED


async def test_complete_allowed_after_start(client, db_session):
    phone, bid = await _setup(db_session, "+79995553003", timedelta(minutes=-30))
    await _login(client, phone)
    r = await client.post(f"/api/v1/bookings/{bid}/complete")
    assert r.status_code == 200, r.text
    assert await _status(db_session, bid) == BookingStatus.COMPLETED


async def test_no_show_not_time_gated(client, db_session):
    # «Не пришёл» можно отметить и задолго до начала — гейт только на «Пришёл».
    phone, bid = await _setup(db_session, "+79995553004", timedelta(hours=5))
    await _login(client, phone)
    r = await client.post(f"/api/v1/bookings/{bid}/no-show")
    assert r.status_code == 200, r.text
    assert await _status(db_session, bid) == BookingStatus.NO_SHOW


# ── Хелпер (используется и рендером кнопки) ──────────────────────────────────

def test_can_mark_completed_now_boundary():
    class _B:
        pass
    b = _B()
    now_local = get_salon_time(TZ).replace(tzinfo=None)
    b.start_time = now_local + timedelta(hours=2)
    assert can_mark_completed_now(b, TZ) is False       # за 2ч — рано
    b.start_time = now_local + timedelta(minutes=30)
    assert can_mark_completed_now(b, TZ) is True         # за 30мин — можно
    b.start_time = now_local - timedelta(hours=1)
    assert can_mark_completed_now(b, TZ) is True          # уже прошло — можно
