"""Гостю (бронь без регистрации с email) уходит письмо со ссылкой отслеживания
статуса — /guest-booking/<token>. Проверяем, что задача send_email ставится в
очередь с этой ссылкой в HTML и в тексте."""
from datetime import datetime, timedelta

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, Master, Service, Booking, BookingStatus, SalonModerationStatus,
)
from app.services import notifications


async def test_guest_booking_email_contains_tracking_link(db_session, monkeypatch):
    captured = {}

    class _FakePool:
        async def enqueue_job(self, name, *args, **kwargs):
            captured["name"] = name
            captured["args"] = args

    async def _fake_pool():
        return _FakePool()

    monkeypatch.setattr(notifications, "get_arq_pool", _fake_pool)

    async with db_session() as db:
        owner = User(phone="+79994440001", full_name="O", hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        muser = User(phone="+79994440002", full_name="M", hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add_all([owner, muser])
        await db.commit()
        await db.refresh(owner)
        await db.refresh(muser)

        salon = Salon(name="Тест-салон", address="a", phone="+70000000950", latitude=1.0, longitude=1.0,
                      timezone="Europe/Moscow", moderation_status=SalonModerationStatus.APPROVED,
                      is_active=True, creator_id=owner.id)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        master = Master(salon_id=salon.id, user_id=muser.id, specialization="X")
        db.add(master)
        await db.commit()
        await db.refresh(master)
        svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)

        start = datetime.now() + timedelta(days=1)
        booking = Booking(client_id=owner.id, master_id=master.id, service_id=svc.id,
                          start_time=start, end_time=start + timedelta(minutes=60),
                          status=BookingStatus.PENDING, final_price=1000,
                          guest_email="guest@example.com", guest_manage_token="TOK123")
        db.add(booking)
        await db.commit()
        await db.refresh(booking)

        await notifications.send_guest_booking_email(
            db, booking, "https://staging.example", "Заявка создана", "текст",
        )

    assert captured.get("name") == "send_email"
    to, subject, plain, html = captured["args"]
    assert to == "guest@example.com"
    assert "guest-booking/TOK123" in html, "ссылка отслеживания должна быть в HTML"
    assert "guest-booking/TOK123" in plain, "ссылка отслеживания должна быть и в тексте"
    assert "Тест-салон" in html


async def test_no_email_when_guest_left_no_address(db_session, monkeypatch):
    captured = {}

    async def _fake_pool():
        raise AssertionError("enqueue не должен вызываться без email гостя")

    monkeypatch.setattr(notifications, "get_arq_pool", _fake_pool)

    async with db_session() as db:
        u = User(phone="+79994440003", full_name="C", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.CLIENT, is_active=True)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        booking = Booking(client_id=u.id, master_id=1, service_id=1,
                          start_time=datetime.now(), end_time=datetime.now() + timedelta(minutes=60),
                          status=BookingStatus.PENDING, final_price=0, guest_email=None)
        # guest_email is None -> функция должна тихо выйти, не трогая очередь
        await notifications.send_guest_booking_email(db, booking, "https://x", "T", "i")
