# tests/test_tg_notifications.py
"""Уведомления о записях в Telegram: ETA напоминания, ретраи отправки,
привязка chat_id при регистрации, постановка задач при создании записи."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from arq import create_pool
from sqlalchemy import select
from arq.worker import Worker
from zoneinfo import ZoneInfo

import app.services.notifications as notif
import app.services.otp as otp_mod
import app.tasks as tasks
from app.core.worker import REDIS_SETTINGS
from app.models.models import (
    Booking,
    BookingStatus,
    Master,
    Salon,
    SalonMember,
    SalonRole,
    Service,
    User,
    UserRole,
)
from app.services.otp import TG_STATUS_CONFIRMED, _hash, _key
from app.tg_bot import check_contact, VERDICT_OK

QUEUE = "test_queue_tg"
settings = otp_mod.settings


# ── reminder_eta_utc: таймзона салона учитывается ────────────────────────────

def test_reminder_eta_is_two_hours_before_in_salon_tz():
    start_local = datetime.now(ZoneInfo("Asia/Vladivostok")).replace(tzinfo=None) + timedelta(hours=10)
    eta = notif.reminder_eta_utc(start_local, "Asia/Vladivostok")
    expected = start_local.replace(tzinfo=ZoneInfo("Asia/Vladivostok")).astimezone(timezone.utc) - timedelta(hours=2)
    assert eta == expected


def test_reminder_eta_none_for_soon_or_past():
    soon = datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None) + timedelta(minutes=30)
    assert notif.reminder_eta_utc(soon, "Europe/Moscow") is None
    past = datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None) - timedelta(hours=1)
    assert notif.reminder_eta_utc(past, "Europe/Moscow") is None


# ── Задача отправки: ретраи на временных сбоях ──────────────────────────────

async def test_send_tg_message_retries_on_transient(monkeypatch):
    calls = {"n": 0}

    async def flaky(chat_id, text):
        calls["n"] += 1
        if calls["n"] < 3:
            raise tasks.TransientTaskError("Bot API 502")

    monkeypatch.setattr(tasks, "_send_via_telegram", flaky)
    monkeypatch.setattr(tasks, "RETRY_BASE_DELAY", 0)

    pool = await create_pool(REDIS_SETTINGS)
    try:
        job = await pool.enqueue_job("send_tg_message", 42, "тест", _queue_name=QUEUE)
        worker = Worker(
            functions=[tasks.send_tg_message],
            redis_settings=REDIS_SETTINGS,
            queue_name=QUEUE,
            max_tries=5,
            poll_delay=0.1,
            handle_signals=False,
        )
        wtask = asyncio.create_task(worker.async_run())
        try:
            result = await job.result(timeout=15)
        finally:
            await worker.close()
            wtask.cancel()
    finally:
        await pool.aclose()

    assert result == "sent"
    assert calls["n"] == 3


async def test_transport_maps_status_codes(monkeypatch):
    """5xx/429 → транзиентная ошибка (ретрай); 403 — постоянный отказ, молча."""
    # _send_via_telegram берёт settings импортом в момент вызова — патчим
    # АКТУАЛЬНЫЙ объект app.core.config.settings (test_config_guards мог
    # пересоздать модуль reload'ом, и наш module-level settings уже не тот)
    import app.core.config as config_mod
    monkeypatch.setattr(config_mod.settings, "TG_BOT_TOKEN", "000:x")

    def set_status(status_code):
        async def fake_post(self, url, json=None):
            return httpx.Response(status_code, request=httpx.Request("POST", url), text="{}")
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    set_status(502)
    with pytest.raises(tasks.TransientTaskError):
        await tasks._send_via_telegram(1, "hi")
    set_status(429)
    with pytest.raises(tasks.TransientTaskError):
        await tasks._send_via_telegram(1, "hi")
    set_status(403)
    await tasks._send_via_telegram(1, "hi")  # не бросает — просто лог


# ── Привязка chat_id при регистрации через бота ─────────────────────────────

async def test_registration_saves_tg_chat_id(client, db_session, monkeypatch, tg_enabled=None):
    monkeypatch.setattr(settings, "TG_VERIFY_ENABLED", True)
    monkeypatch.setattr(settings, "TG_BOT_TOKEN", "000:x")
    monkeypatch.setattr(settings, "TG_BOT_USERNAME", "rumi_test_bot")

    phone = "+79995556677"
    r = await client.post("/api/v1/auth/register/tg-start", json={"phone": phone})
    request_id = r.json()["request_id"]

    # «Бот»: подтверждает и запоминает chat_id — ровно как app/tg_bot.py
    redis = otp_mod.get_redis()
    record = await redis.hgetall(_key(request_id))
    assert check_contact(record, 777, 777, "79995556677") == VERDICT_OK
    await redis.hset(_key(request_id), "status", TG_STATUS_CONFIRMED)
    await otp_mod.save_tg_chat_id(record["phone_hash"], 424242)

    r = await client.post(
        "/api/v1/auth/register-web",
        data={"phone": phone, "password": "Testpass1", "full_name": "ТГ",
              "request_id": request_id, "code": ""},
    )
    assert r.status_code == 302 and r.headers["location"] == "/profile"

    from sqlalchemy import select
    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        assert user.tg_chat_id == 424242


# ── Постановка уведомлений при создании записи ──────────────────────────────

async def test_notify_booking_created_enqueues_for_all_parties(db_session, monkeypatch):
    monkeypatch.setattr(settings, "TG_NOTIFY_ENABLED", True)

    enqueued: list[tuple] = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            enqueued.append((fn, args, kwargs))

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr(notif, "get_arq_pool", fake_pool)

    async with db_session() as db:
        owner = User(phone="+79990001001", hashed_password="x", role=UserRole.BUSINESS,
                     full_name="Владелец", tg_chat_id=111)
        master_user = User(phone="+79990001002", hashed_password="x", role=UserRole.MASTER,
                           full_name="Мастер", tg_chat_id=222)
        client_user = User(phone="+79990001003", hashed_password="x", role=UserRole.CLIENT,
                           full_name="Клиент", tg_chat_id=333)
        db.add_all([owner, master_user, client_user])
        await db.flush()

        salon = Salon(name="Тест-салон", address="ул. Тестовая, 1", timezone="Europe/Moscow",
                      creator_id=owner.id, latitude=55.75, longitude=37.62,
                      phone="+79990001000")
        db.add(salon)
        await db.flush()
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, is_active=True, permissions={}))
        master = Master(user_id=master_user.id, salon_id=salon.id,
                        specialization="стрижка")
        db.add(master)
        await db.flush()
        service = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(service)
        await db.flush()

        booking = Booking(
            client_id=client_user.id, master_id=master.id, service_id=service.id,
            start_time=datetime.now() + timedelta(days=1),
            end_time=datetime.now() + timedelta(days=1, hours=1),
            status=BookingStatus.PENDING, final_price=1000,
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)

        await notif.notify_booking_created(db, booking)

    fns = [e[0] for e in enqueued]
    # мгновенные: владельцу (111), мастеру (222), клиенту (333)
    chat_ids = [e[1][0] for e in enqueued if e[0] == "send_tg_message"]
    assert sorted(chat_ids) == [111, 222, 333]
    # отложенное напоминание клиенту с дедуп-ключом
    reminders = [e for e in enqueued if e[0] == "send_booking_reminder"]
    assert len(reminders) == 1
    assert reminders[0][2]["_job_id"] == f"booking-reminder:{booking.id}"
    assert reminders[0][2]["_defer_until"] is not None


# ── Этап 1 разграничения: матрица получателей по правам ─────────────────────

async def _matrix_fixture(db_session):
    """Салон с командой разных прав + мастер + клиент (у всех привязан TG)."""
    async with db_session() as db:
        creator = User(phone="+79991110001", hashed_password="x", role=UserRole.BUSINESS,
                       full_name="Создатель", tg_chat_id=1001)
        sched_admin = User(phone="+79991110002", hashed_password="x", role=UserRole.CLIENT,
                           full_name="Админ-расписание", tg_chat_id=1002)
        inv_admin = User(phone="+79991110003", hashed_password="x", role=UserRole.CLIENT,
                         full_name="Админ-склад", tg_chat_id=1003)
        no_tg_admin = User(phone="+79991110004", hashed_password="x", role=UserRole.CLIENT,
                           full_name="Без телеграма")  # прав много, чата нет
        master_user = User(phone="+79991110005", hashed_password="x", role=UserRole.MASTER,
                           full_name="Мастер", tg_chat_id=1005)
        client_user = User(phone="+79991110006", hashed_password="x", role=UserRole.CLIENT,
                           full_name="Клиент", tg_chat_id=1006)
        db.add_all([creator, sched_admin, inv_admin, no_tg_admin, master_user, client_user])
        await db.flush()

        salon = Salon(name="Матрица", address="а", phone="+79991110000",
                      latitude=1.0, longitude=1.0, timezone="Asia/Novosibirsk",
                      creator_id=creator.id)
        db.add(salon)
        await db.flush()
        db.add_all([
            SalonMember(salon_id=salon.id, user_id=creator.id, role=SalonRole.OWNER,
                        is_creator=True, is_active=True, permissions={}),
            SalonMember(salon_id=salon.id, user_id=sched_admin.id, role=SalonRole.ADMIN,
                        is_creator=False, is_active=True,
                        permissions={"manage_schedule": True}),
            SalonMember(salon_id=salon.id, user_id=inv_admin.id, role=SalonRole.ADMIN,
                        is_creator=False, is_active=True,
                        permissions={"manage_inventory": True, "manage_reviews": True}),
            SalonMember(salon_id=salon.id, user_id=no_tg_admin.id, role=SalonRole.ADMIN,
                        is_creator=False, is_active=True,
                        permissions={"manage_schedule": True}),
        ])
        master = Master(user_id=master_user.id, salon_id=salon.id, specialization="стрижка")
        db.add(master)
        await db.flush()
        service = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(service)
        await db.commit()
        return {
            "salon_id": salon.id, "master_id": master.id, "service_id": service.id,
            "client_id": client_user.id, "master_chat": 1005, "client_chat": 1006,
        }


@pytest.fixture()
def fake_pool(monkeypatch):
    enqueued: list[tuple] = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            enqueued.append((fn, args, kwargs))

    async def _pool():
        return FakePool()

    monkeypatch.setattr(notif, "get_arq_pool", _pool)
    monkeypatch.setattr(settings, "TG_NOTIFY_ENABLED", True)
    return enqueued


def _chats(enqueued):
    return sorted(e[1][0] for e in enqueued if e[0] == "send_tg_message")


async def test_booking_notify_routes_by_schedule_permission(db_session, fake_pool):
    ids = await _matrix_fixture(db_session)
    async with db_session() as db:
        booking = Booking(
            client_id=ids["client_id"], master_id=ids["master_id"], service_id=ids["service_id"],
            start_time=datetime.now() + timedelta(days=1),
            end_time=datetime.now() + timedelta(days=1, hours=1),
            status=BookingStatus.PENDING, final_price=1000,
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        await notif.notify_booking_created(db, booking)

    # клиент, мастер, создатель (всегда), админ-расписание. Админ-склад — НЕТ
    # (нет manage_schedule), без-телеграма — НЕТ (нет чата)
    assert _chats(fake_pool) == [1001, 1002, 1005, 1006]
    # у мастера — свой текст, у команды — свой
    texts = {e[1][0]: e[1][1] for e in fake_pool if e[0] == "send_tg_message"}
    assert "К вам новая запись" in texts[1005]
    assert "Новая запись в «Матрица»" in texts[1002]
    assert "Вы записаны" in texts[1006]


async def test_warehouse_request_routes_by_inventory_permission(db_session, fake_pool):
    from app.models.models import WarehouseRequest, WarehouseRequestStatus, WarehouseRequestType

    ids = await _matrix_fixture(db_session)
    async with db_session() as db:
        master_user_id = (
            await db.execute(select(User.id).where(User.tg_chat_id == 1005))
        ).scalar_one()
        req = WarehouseRequest(
            salon_id=ids["salon_id"], type=WarehouseRequestType.EQUIPMENT_BROKEN,
            created_by_id=master_user_id, comment="фен умер",
            status=WarehouseRequestStatus.PENDING,
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)
        await notif.notify_warehouse_request_created(db, req)

        # только создатель + админ-склад; расписание-админ и клиент — нет
        assert _chats(fake_pool) == [1001, 1003]

        fake_pool.clear()
        req.status = WarehouseRequestStatus.RESOLVED
        await db.commit()
        await notif.notify_warehouse_request_resolved(db, req)
        assert _chats(fake_pool) == [1005]  # автору-мастеру


async def test_review_routes_by_reviews_permission(db_session, fake_pool):
    from app.models.models import Review, ReviewTargetType

    ids = await _matrix_fixture(db_session)
    async with db_session() as db:
        review = Review(
            client_id=ids["client_id"], salon_id=ids["salon_id"], master_id=ids["master_id"],
            target_type=ReviewTargetType.MASTER, rating=5, comment="топ", is_verified=True,
        )
        db.add(review)
        await db.commit()
        await db.refresh(review)
        await notif.notify_new_review(db, review)

    # мастер (отзыв о нём) + создатель + админ с manage_reviews
    assert _chats(fake_pool) == [1001, 1003, 1005]


# ── Этап 2: личные подписки поверх прав ─────────────────────────────────────

def test_wants_defaults_on_and_respects_off():
    u = User(phone="+70000000010", hashed_password="x", tg_chat_id=1)
    assert notif.wants(u, notif.TOPIC_BOOKINGS) is True          # нет настройки
    u.tg_notify_prefs = {"bookings": False}
    assert notif.wants(u, notif.TOPIC_BOOKINGS) is False         # отключил
    assert notif.wants(u, notif.TOPIC_WAREHOUSE) is True         # прочее не тронуто


async def test_muted_member_not_notified_despite_permission(db_session, fake_pool):
    """Право есть, но тема лично отключена — уведомления нет."""
    ids = await _matrix_fixture(db_session)
    async with db_session() as db:
        sched_admin = (
            await db.execute(select(User).where(User.tg_chat_id == 1002))
        ).scalar_one()
        sched_admin.tg_notify_prefs = {"bookings": False}
        await db.commit()

        booking = Booking(
            client_id=ids["client_id"], master_id=ids["master_id"], service_id=ids["service_id"],
            start_time=datetime.now() + timedelta(days=1),
            end_time=datetime.now() + timedelta(days=1, hours=1),
            status=BookingStatus.PENDING, final_price=1000,
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        await notif.notify_booking_created(db, booking)

    # 1002 замьютил тему — выпал; остальные на месте
    assert _chats(fake_pool) == [1001, 1005, 1006]


async def test_available_topics_follow_roles(db_session):
    from app.tg_bot import _available_topics

    await _matrix_fixture(db_session)
    async with db_session() as db:
        client = (await db.execute(select(User).where(User.tg_chat_id == 1006))).scalar_one()
        master = (await db.execute(select(User).where(User.tg_chat_id == 1005))).scalar_one()
        inv_admin = (await db.execute(select(User).where(User.tg_chat_id == 1003))).scalar_one()
        creator = (await db.execute(select(User).where(User.tg_chat_id == 1001))).scalar_one()

        assert await _available_topics(db, client) == ["bookings", "reminders", "evening_deals"]
        assert set(await _available_topics(db, master)) == {"bookings", "reminders", "evening_deals", "warehouse", "reviews"}
        assert set(await _available_topics(db, inv_admin)) == {"bookings", "reminders", "evening_deals", "warehouse", "reviews", "reports"}
        assert set(await _available_topics(db, creator)) == {"bookings", "reminders", "evening_deals", "warehouse", "reviews", "reports"}


async def test_warehouse_respects_both_personal_filters(db_session, fake_pool):
    """Пуш склада фильтруется И per-салонным тумблером (SalonMember),
    И глобальной темой в боте (tg_notify_prefs)."""
    from app.models.models import SalonMember, WarehouseRequest, WarehouseRequestStatus, WarehouseRequestType

    ids = await _matrix_fixture(db_session)
    async with db_session() as db:
        # Создатель выключает per-салонный тумблер, админ-склад — глобальную тему
        creator_member = (await db.execute(
            select(SalonMember).join(User, User.id == SalonMember.user_id)
            .where(User.tg_chat_id == 1001)
        )).scalar_one()
        creator_member.notify_warehouse_requests = False
        inv_admin = (await db.execute(select(User).where(User.tg_chat_id == 1003))).scalar_one()
        inv_admin.tg_notify_prefs = {"warehouse": False}
        await db.commit()

        master_user_id = (
            await db.execute(select(User.id).where(User.tg_chat_id == 1005))
        ).scalar_one()
        req = WarehouseRequest(
            salon_id=ids["salon_id"], type=WarehouseRequestType.EQUIPMENT_BROKEN,
            created_by_id=master_user_id, status=WarehouseRequestStatus.PENDING,
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)
        await notif.notify_warehouse_request_created(db, req)

    assert _chats(fake_pool) == []  # оба замьютились каждый своим способом
