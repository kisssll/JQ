# tests/test_guest_booking.py
"""Запись без регистрации: PENDING-бронь, гость-User по номеру, отмена по токену,
тумблер салона, переиспользование существующего юзера."""
import json
from datetime import datetime, timedelta

from sqlalchemy import select

_WORK = json.dumps({d: "08:00-22:00" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, Master, Service, Booking, BookingStatus,
    SalonModerationStatus, SalonMember, SalonRole,
)
from tests.conftest import register_user


async def _setup(db_session, *, salon_phone, master_phone, guest_enabled=True):
    async with db_session() as db:
        salon = Salon(name="G", address="a", phone=salon_phone,
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                      guest_booking_enabled=guest_enabled, working_hours=_WORK)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        muser = User(phone=master_phone, full_name="M",
                     hashed_password=get_password_hash("x"), role=UserRole.CLIENT)
        db.add(muser)
        await db.commit()
        await db.refresh(muser)
        master = Master(salon_id=salon.id, user_id=muser.id, specialization="B")
        db.add(master)
        await db.commit()
        await db.refresh(master)
        svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)
        return salon.id, master.id, svc.id


def _payload(salon_id, master_id, svc_id, phone, **over):
    start = (datetime.now() + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    p = {"salon_id": salon_id, "master_id": master_id, "service_id": svc_id,
         "start_time": start.isoformat(),
        "pd_consent": True, "name": "Гость", "phone": phone}
    p.update(over)
    return p


async def test_guest_booking_creates_pending_and_guest_user(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000090", master_phone="+79993330090")
    r = await client.post("/api/v1/guest/booking",
                          json=_payload(salon_id, master_id, svc_id, "+7 999 111 22 33", email="g@x.ru"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending" and body["manage_token"]

    async with db_session() as db:
        u = (await db.execute(select(User).where(User.phone == "+79991112233"))).scalar_one()
        assert u.is_guest is True and u.full_name == "Гость"
        b = (await db.execute(select(Booking).where(Booking.id == body["booking_id"]))).scalar_one()
        assert b.status == BookingStatus.PENDING
        assert b.client_id == u.id and b.guest_email == "g@x.ru" and b.guest_manage_token

    # отмена по токену
    r = await client.post(f"/api/v1/guest/booking/{body['manage_token']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    async with db_session() as db:
        b = (await db.execute(select(Booking).where(Booking.id == body["booking_id"]))).scalar_one()
        assert b.status == BookingStatus.CANCELLED


async def test_guest_booking_reuses_existing_real_user(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000091", master_phone="+79993330091")
    phone = "+79994445566"
    async with db_session() as db:
        real = User(phone=phone, full_name="Реальный",
                    hashed_password=get_password_hash("Realpass1"), role=UserRole.CLIENT)
        db.add(real)
        await db.commit()
        await db.refresh(real)
        real_id = real.id

    r = await client.post("/api/v1/guest/booking",
                          json=_payload(salon_id, master_id, svc_id, phone))
    assert r.status_code == 200, r.text
    async with db_session() as db:
        # НЕ создан второй юзер; бронь привязана к реальному, он не стал гостем
        users = (await db.execute(select(User).where(User.phone == phone))).scalars().all()
        assert len(users) == 1 and users[0].id == real_id and users[0].is_guest is False
        b = (await db.execute(select(Booking).where(Booking.id == r.json()["booking_id"]))).scalar_one()
        assert b.client_id == real_id


async def test_guest_booking_disabled_by_salon(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000092", master_phone="+79993330092", guest_enabled=False)
    r = await client.post("/api/v1/guest/booking",
                          json=_payload(salon_id, master_id, svc_id, "+79995556677"))
    assert r.status_code == 403


async def test_guest_booking_page_renders(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000093", master_phone="+79993330093")
    r = await client.get(f"/book/{salon_id}")
    assert r.status_code == 200
    assert "guest-book" in r.text and "Стрижка" in r.text


async def test_guest_manage_page_renders(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000094", master_phone="+79993330094")
    r = await client.post("/api/v1/guest/booking",
                          json=_payload(salon_id, master_id, svc_id, "+79998887766"))
    token = r.json()["manage_token"]
    r = await client.get(f"/guest-booking/{token}")
    assert r.status_code == 200 and "Ваша запись" in r.text


async def test_guest_book_page_disabled_salon(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000095", master_phone="+79993330095", guest_enabled=False)
    r = await client.get(f"/book/{salon_id}")
    assert r.status_code == 200 and "недоступна" in r.text.lower()


async def test_guest_claim_on_register(client, db_session):
    """Регистрация тем же номером «забирает» гостя (is_guest→False), бронь остаётся."""
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000096", master_phone="+79993330096")
    phone = "+79993331111"
    r = await client.post("/api/v1/guest/booking", json=_payload(salon_id, master_id, svc_id, phone))
    booking_id = r.json()["booking_id"]
    async with db_session() as db:
        guest = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        assert guest.is_guest is True
        guest_id = guest.id

    await register_user(client, phone)  # send-code больше не блокирует гостя + claim

    async with db_session() as db:
        u = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        assert u.is_guest is False and u.id == guest_id
        b = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one()
        assert b.client_id == guest_id  # гостевая бронь осталась за ним


async def test_guest_qr_png(client, db_session):
    salon_id, _m, _s = await _setup(
        db_session, salon_phone="+70000000097", master_phone="+79993330097")
    r = await client.get(f"/book/{salon_id}/qr")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"


async def test_salon_accept_and_toggle(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000098", master_phone="+79993330098")
    async with db_session() as db:
        owner = User(phone="+79993330099", full_name="O",
                     hashed_password=get_password_hash("Ownpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        db.add(SalonMember(salon_id=salon_id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True,
                           permissions={"manage_schedule": True, "manage_salon": True},
                           is_active=True))
        await db.commit()

    r = await client.post("/api/v1/guest/booking", json=_payload(salon_id, master_id, svc_id, "+79993332222"))
    bid = r.json()["booking_id"]

    lr = await client.post("/api/v1/auth/login", json={"phone": "+79993330099", "password": "Ownpass1"})
    client.cookies.set("access_token", lr.json()["access_token"])

    # подтверждение PENDING→CONFIRMED
    r = await client.post(f"/api/v1/bookings/{bid}/accept")
    assert r.status_code == 200, r.text
    async with db_session() as db:
        b = (await db.execute(select(Booking).where(Booking.id == bid))).scalar_one()
        assert b.status == BookingStatus.CONFIRMED

    # тумблер салона
    r = await client.post(f"/api/v1/business/my-salon/guest-toggle?salon_id={salon_id}")
    assert r.status_code == 200 and r.json()["guest_booking_enabled"] is False
