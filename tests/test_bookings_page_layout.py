# tests/test_bookings_page_layout.py
"""Карточка записи на «Мои записи» — 3 колонки (салон+контакты / мастер+
услуга+время / цена) вместо одного списка полей, плюс кликабельное название
салона, ведущее на /salons?highlight=<id> для перехода к карточке салона."""
from datetime import datetime, timedelta

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, Master, Service, Booking, BookingStatus,
    SalonModerationStatus,
)


async def _login(client, phone, password="Testpass1"):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": password})
    assert r.status_code == 302, r.text


async def test_booking_card_has_three_columns_and_salon_link(client, db_session):
    async with db_session() as db:
        client_user = User(phone="+79997770001", full_name="Client",
                            hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        master_user = User(phone="+79997770002", full_name="Master One",
                            hashed_password=get_password_hash("Testpass1"), role=UserRole.MASTER)
        db.add_all([client_user, master_user])
        await db.commit()
        await db.refresh(client_user)
        await db.refresh(master_user)

        salon = Salon(name="Тестовый салон", address="ул. Тестовая, 1", phone="+70000000500",
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                      creator_id=master_user.id)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        master = Master(user_id=master_user.id, salon_id=salon.id, specialization="Стрижки", is_active=True)
        db.add(master)
        await db.commit()
        await db.refresh(master)

        service = Service(master_id=master.id, name="Стрижка", price=1500, duration_minutes=45)
        db.add(service)
        await db.commit()
        await db.refresh(service)

        start = datetime.now() + timedelta(days=1)
        booking = Booking(
            client_id=client_user.id, master_id=master.id, service_id=service.id,
            start_time=start, end_time=start + timedelta(minutes=45),
            status=BookingStatus.CONFIRMED, final_price=1500,
        )
        db.add(booking)
        await db.commit()
        salon_id = salon.id

    await _login(client, "+79997770001")
    r = await client.get("/bookings")
    assert r.status_code == 200

    assert '<div class="booking-info-grid">' in r.text
    assert 'class="booking-col booking-col-salon"' in r.text
    assert 'class="booking-col booking-col-service"' in r.text
    assert 'class="booking-col booking-col-price"' in r.text

    # Название салона — кликабельная ссылка на /salons?highlight=<id>
    assert f'<a href="/salons?highlight={salon_id}" class="booking-salon-link">Тестовый салон</a>' in r.text
    assert "ул. Тестовая, 1" in r.text
    assert "+70000000500" in r.text

    # Длительность посчитана из start/end_time (45 минут)
    assert "45 мин" in r.text
