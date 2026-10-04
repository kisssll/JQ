# tests/test_bookings_page_layout.py
"""Карточка записи на «Мои записи».

Файл переписан заходом «кабинет клиента» (решение 0011, п. 14): прежние
три колонки (.booking-info-grid, .booking-col-*) и вкладки заменены списком
фактов (.r-facts) и двумя разделами на странице. ПРОВЕРЯЕМОЕ СОДЕРЖИМОЕ
осталось тем же, потому что терять его нельзя: состояние записи, кликабельное
название салона со ссылкой на /salons?highlight=<id>, адрес, телефон и
длительность, посчитанная из start/end_time.
"""
from datetime import datetime, timedelta

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Salon, SalonModerationStatus, Service,
    User, UserRole,
)


async def _login(client, phone, password="Testpass1"):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": password})
    assert r.status_code == 302, r.text


async def _stand(db_session, *, client_phone, master_phone, salon_phone,
                 salon_name="Тестовый салон", master_name="Master One",
                 creator_is_master=False):
    """Стенд: клиент, мастер, салон, услуга. Телефоны передаёт вызывающий —
    у каждого теста свои, чтобы стенды не пересекались."""
    async with db_session() as db:
        client_user = User(phone=client_phone, full_name="Client",
                           hashed_password=get_password_hash("Testpass1"),
                           role=UserRole.CLIENT)
        master_user = User(phone=master_phone, full_name=master_name,
                           hashed_password=get_password_hash("Testpass1"),
                           role=UserRole.MASTER)
        db.add_all([client_user, master_user])
        await db.commit()
        await db.refresh(client_user)
        await db.refresh(master_user)

        salon = Salon(name=salon_name, address="ул. Тестовая, 1", phone=salon_phone,
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                      creator_id=master_user.id if creator_is_master else client_user.id)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        master = Master(user_id=master_user.id, salon_id=salon.id,
                        specialization="Стрижки", is_active=True)
        db.add(master)
        await db.commit()
        await db.refresh(master)

        service = Service(master_id=master.id, name="Стрижка", price=1500,
                          duration_minutes=45)
        db.add(service)
        await db.commit()
        await db.refresh(service)
        return client_user.id, master.id, service.id, salon.id


async def _book(db_session, *, client_id, master_id, service_id, when,
                status=BookingStatus.CONFIRMED, price=1500, minutes=45):
    async with db_session() as db:
        booking = Booking(client_id=client_id, master_id=master_id,
                          service_id=service_id, start_time=when,
                          end_time=when + timedelta(minutes=minutes),
                          status=status, final_price=price)
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        return booking.id


async def test_booking_card_keeps_facts_and_salon_link(client, db_session):
    """Карточка называет состояние словом и не теряет ни одного факта."""
    client_id, master_id, service_id, salon_id = await _stand(
        db_session, client_phone="+79997770001", master_phone="+79997770002",
        salon_phone="+70000000500")
    await _book(db_session, client_id=client_id, master_id=master_id,
                service_id=service_id, when=datetime.now() + timedelta(days=1))

    await _login(client, "+79997770001")
    r = await client.get("/bookings")
    assert r.status_code == 200

    # Список фактов — общий компонент ui.facts, а не своя сетка страницы.
    assert '<dl class="r-facts">' in r.text
    assert "booking-info-grid" not in r.text
    assert "booking-col-salon" not in r.text

    # Состояние — словом и общей плашкой ui.status.
    assert "Подтверждена" in r.text
    assert 'class="r-status r-status--success"' in r.text

    # Название салона — кликабельная ссылка на /salons?highlight=<id>
    assert (f'<a href="/salons?highlight={salon_id}" class="booking-salon-link">'
            "Тестовый салон</a>") in r.text
    assert "ул. Тестовая, 1" in r.text
    assert "+70000000500" in r.text

    # Длительность посчитана из start/end_time (45 минут)
    assert "45 мин" in r.text

    # Цена на месте
    assert "1500 ₽" in r.text


async def test_pending_and_confirmed_differ_in_words(client, db_session):
    """«Ждёт подтверждения» и «Подтверждена» — разные слова, а не только
    разный цвет: смысл не передаётся одним цветом (docs/design.md)."""
    client_id, master_id, service_id, _ = await _stand(
        db_session, client_phone="+79997770011", master_phone="+79997770012",
        salon_phone="+70000000501")
    await _book(db_session, client_id=client_id, master_id=master_id,
                service_id=service_id, when=datetime.now() + timedelta(days=1),
                status=BookingStatus.PENDING)

    await _login(client, "+79997770011")
    r = await client.get("/bookings")
    assert "Ждёт подтверждения" in r.text
    assert "Подтверждена" not in r.text


async def test_past_and_upcoming_are_separate_sections(client, db_session):
    """Предстоящие и прошедшие разделены, а вкладок с памятью в localStorage
    больше нет."""
    client_id, master_id, service_id, _ = await _stand(
        db_session, client_phone="+79997770021", master_phone="+79997770022",
        salon_phone="+70000000502")
    await _book(db_session, client_id=client_id, master_id=master_id,
                service_id=service_id, when=datetime.now() + timedelta(days=2))
    await _book(db_session, client_id=client_id, master_id=master_id,
                service_id=service_id, when=datetime.now() - timedelta(days=5),
                status=BookingStatus.COMPLETED)

    await _login(client, "+79997770021")
    r = await client.get("/bookings")
    assert "Предстоящие" in r.text
    assert "Прошедшие" in r.text
    assert "bookings-tabs" not in r.text
    assert 'data-tab="upcoming"' not in r.text


async def test_no_show_booking_names_its_state(client, db_session):
    """NO_SHOW показывал клиенту прочерк вместо состояния — проверяем слово."""
    client_id, master_id, service_id, _ = await _stand(
        db_session, client_phone="+79997770031", master_phone="+79997770032",
        salon_phone="+70000000503")
    await _book(db_session, client_id=client_id, master_id=master_id,
                service_id=service_id, when=datetime.now() - timedelta(days=1),
                status=BookingStatus.NO_SHOW)

    await _login(client, "+79997770031")
    r = await client.get("/bookings")
    assert "Пропущена" in r.text


async def test_solo_master_is_a_person_not_an_organisation(client, db_session):
    """Соло-мастер в записи называется человеком: «К кому — Анне», а не
    «Мастер» с названием салона (public_words, решение 0011, п. 13)."""
    client_id, master_id, service_id, _ = await _stand(
        db_session, client_phone="+79997770041", master_phone="+79997770042",
        salon_phone="+70000000504", master_name="Анна Смирнова",
        creator_is_master=True)
    await _book(db_session, client_id=client_id, master_id=master_id,
                service_id=service_id, when=datetime.now() + timedelta(days=1))

    await _login(client, "+79997770041")
    r = await client.get("/bookings")
    # Падеж из public_words.dative: «Анна» → «Анне».
    assert "<dt>К кому</dt><dd>Анне</dd>" in r.text
