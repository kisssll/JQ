# tests/test_consent.py
"""Согласие на обработку персональных данных.

Проверяем две вещи, которых требует закон и сам текст Согласия:
формы без отметки не проходят, а данная отметка попадает в журнал вместе с
редакцией документа — п.8 Согласия считает моментом согласия именно её
проставление, и без записи подтвердить это нечем.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    ConsentDocument, Master, Salon, SalonModerationStatus, Service, User,
    UserConsent, UserRole,
)

_WORK = json.dumps({d: "08:00-22:00" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


async def _salon_with_service(db_session, *, salon_phone, master_phone):
    async with db_session() as db:
        salon = Salon(name="C", address="a", phone=salon_phone,
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                      guest_booking_enabled=True, working_hours=_WORK)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        muser = User(phone=master_phone, full_name="M",
                     hashed_password=get_password_hash("x"), role=UserRole.CLIENT)
        db.add(muser)
        await db.commit()
        await db.refresh(muser)

        master = Master(user_id=muser.id, salon_id=salon.id, specialization="B", is_active=True)
        db.add(master)
        await db.commit()
        await db.refresh(master)

        svc = Service(master_id=master.id, name="S", price=100, duration_minutes=60, is_active=True)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)
        return salon.id, master.id, svc.id


def _booking_payload(salon_id, master_id, svc_id, phone, **extra):
    start = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    payload = {
        "salon_id": salon_id, "master_id": master_id, "service_id": svc_id,
        "start_time": start.isoformat(), "name": "Гость", "phone": phone,
    }
    payload.update(extra)
    return payload


async def test_guest_booking_rejected_without_consent(client, db_session):
    """Форма собирает имя, телефон и почту — без отметки записи быть не должно."""
    salon_id, master_id, svc_id = await _salon_with_service(
        db_session, salon_phone="+70000000190", master_phone="+79993330190")

    r = await client.post("/api/v1/guest/booking",
                          json=_booking_payload(salon_id, master_id, svc_id, "+79991110001"))
    assert r.status_code == 400
    assert "персональных данных" in r.json()["detail"]

    async with db_session() as db:
        assert (await db.execute(select(User).where(User.phone == "+79991110001"))).scalar_one_or_none() is None


async def test_guest_booking_writes_consent_to_journal(client, db_session):
    """Отметка есть — бронь создаётся, и факт согласия попадает в журнал."""
    salon_id, master_id, svc_id = await _salon_with_service(
        db_session, salon_phone="+70000000191", master_phone="+79993330191")

    r = await client.post("/api/v1/guest/booking", json=_booking_payload(
        salon_id, master_id, svc_id, "+79991110002",
        pd_consent=True, consent_version="2026-08-21"))
    assert r.status_code == 200, r.text

    async with db_session() as db:
        rows = (await db.execute(
            select(UserConsent).where(UserConsent.phone == "+79991110002"))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.document == ConsentDocument.PD_CONSENT
        assert row.version == "2026-08-21"          # редакция документа сохранена
        assert row.source == "guest_booking"
        assert row.accepted_at is not None          # п.8: дата и время отметки
        assert row.user_id is not None              # гостю завели учётную запись


async def test_registration_rejected_without_consent(client, db_session):
    """Регистрация — это и есть сбор ПДн, без отметки её быть не должно."""
    r = await client.post("/api/v1/auth/register-web", data={
        "phone": "+79991110003", "password": "Testpass1", "full_name": "Без согласия",
    })
    assert r.status_code == 302
    assert "error=no_consent" in r.headers["location"]

    async with db_session() as db:
        assert (await db.execute(
            select(User).where(User.phone == "+79991110003"))).scalar_one_or_none() is None
