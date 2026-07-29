"""Мэтчинг модель↔услуга: отклонение BOOKED-мэтча должно отменять созданную
по нему бронь (иначе остаётся «осиротевшая» активная запись), и decline
идемпотентен."""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, Master, Service, Booking,
    BookingStatus, SalonModerationStatus, ModelModerationStatus, ModelMatch, ModelMatchStatus,
)

MODEL_PHONE = "+79996661001"


async def _seed_booked_match(db) -> tuple[int, int]:
    owner = User(phone="+79996661000", full_name="Owner", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.BUSINESS, is_active=True)
    muser = User(phone="+79996661002", full_name="Master", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.BUSINESS, is_active=True)
    model = User(phone=MODEL_PHONE, full_name="Model", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.CLIENT, is_active=True, is_model=True,
                 model_moderation_status=ModelModerationStatus.APPROVED)
    db.add_all([owner, muser, model])
    await db.commit()
    for u in (owner, muser, model):
        await db.refresh(u)

    salon = Salon(name="M", address="a", phone="+70000000800", latitude=1.0, longitude=1.0,
                  timezone="Europe/Moscow", moderation_status=SalonModerationStatus.APPROVED,
                  is_active=True, creator_id=owner.id)
    db.add(salon)
    await db.commit()
    await db.refresh(salon)
    db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                       is_creator=True, permissions={}, is_active=True))
    await db.commit()

    master = Master(salon_id=salon.id, user_id=muser.id, specialization="Барбер")
    db.add(master)
    await db.commit()
    await db.refresh(master)

    svc = Service(master_id=master.id, name="Модельная стрижка", price=0, duration_minutes=60,
                  is_model_practice=True)
    db.add(svc)
    await db.commit()
    await db.refresh(svc)

    slot = datetime.now().replace(microsecond=0) + timedelta(days=2)
    booking = Booking(client_id=model.id, master_id=master.id, service_id=svc.id,
                      start_time=slot, end_time=slot + timedelta(minutes=60),
                      status=BookingStatus.PENDING, final_price=0)
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    match = ModelMatch(model_user_id=model.id, service_id=svc.id, master_id=master.id,
                       salon_id=salon.id, status=ModelMatchStatus.BOOKED, booking_id=booking.id,
                       chosen_slot=slot, model_liked=True, salon_liked=True)
    db.add(match)
    await db.commit()
    await db.refresh(match)
    return match.id, booking.id


async def _login(client, phone):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"})
    assert r.status_code == 302, r.text


async def test_decline_booked_match_cancels_booking(client, db_session):
    async with db_session() as db:
        match_id, booking_id = await _seed_booked_match(db)

    await _login(client, MODEL_PHONE)
    r = await client.post(f"/api/v1/model-matching/matches/{match_id}/decline")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined"

    async with db_session() as db:
        booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one()
        match = (await db.execute(select(ModelMatch).where(ModelMatch.id == match_id))).scalar_one()
        assert booking.status == BookingStatus.CANCELLED, "бронь BOOKED-мэтча должна отмениться"
        assert match.status == ModelMatchStatus.DECLINED
        assert match.declined_by == "model"

    # Повторный decline — идемпотентно, без ошибки
    r = await client.post(f"/api/v1/model-matching/matches/{match_id}/decline")
    assert r.status_code == 200, r.text
