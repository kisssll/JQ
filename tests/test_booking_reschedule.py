"""Перенос записи клиентом (решение 0020): та же запись, другое время.

Время детерминировано так же, как в test_evening_deals: салону выдаётся зона,
где сейчас ~12:00, график — на весь день, вечернее окно со скидкой 13:30–16:00.
Поэтому «сегодня 14:00» — вечернее окно со скидкой, «сегодня 17:00» и «завтра
10:00» — обычное время, «сегодня 09:00» — уже прошло.
"""
import asyncio
import pathlib
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import asyncpg
from sqlalchemy import func, select, update

import app.services.notifications as notif
import app.tasks as tasks
from app.core.config import settings
from app.models.models import Booking, BookingStatus, User
from tests.conftest import _pg_dsn, register_user
from tests.test_evening_deals import _mk_salon_deal


def _local_today(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz)).replace(tzinfo=None, second=0, microsecond=0)


def _at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute)


async def _setup(client, db_session, n: int, *, discount=40):
    """Салон с вечерней скидкой и залогиненный клиент. n — уникальный хвост
    телефонов, чтобы стенды разных тестов не пересекались."""
    ctx = await _mk_salon_deal(db_session, discount=discount, ev_from=time(13, 30),
                               ev_to=time(16, 0), owner_phone=f"+7999555{n:04d}",
                               name=f"ПереносZZ{n}")
    data = await register_user(client, f"+7997555{n:04d}")
    client.cookies.set("access_token", data["access_token"])
    ctx["today"] = _local_today(ctx["tz"])
    return ctx


async def _book(client, ctx, when: datetime):
    r = await client.post("/api/v1/bookings", json={
        "master_id": ctx["master_id"], "service_id": ctx["service_id"],
        "start_time": when.isoformat(),
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _move(client, booking_id, when: datetime):
    return await client.post(f"/api/v1/bookings/{booking_id}/reschedule",
                             json={"start_time": when.isoformat()})


# ── Ядро: та же запись, другое время ────────────────────────────────────────

async def test_reschedule_moves_the_same_booking(client, db_session):
    ctx = await _setup(client, db_session, 1)
    booked = await _book(client, ctx, _at(ctx["today"], 17))
    new_start = _at(ctx["today"] + timedelta(days=1), 10)

    r = await _move(client, booked["id"], new_start)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == booked["id"]
    assert body["rescheduled_count"] == 1

    async with db_session() as db:
        rows = (await db.execute(select(Booking))).scalars().all()
        assert len(rows) == 1  # перенос не плодит новую запись
        b = rows[0]
        assert b.id == booked["id"]
        assert b.start_time == new_start
        assert b.end_time == new_start + timedelta(minutes=60)
        assert b.status == BookingStatus.PENDING
        assert b.rescheduled_at is not None


async def test_counter_grows_with_each_reschedule(client, db_session):
    ctx = await _setup(client, db_session, 2)
    booked = await _book(client, ctx, _at(ctx["today"], 17))
    tomorrow = ctx["today"] + timedelta(days=1)

    assert (await _move(client, booked["id"], _at(tomorrow, 10))).status_code == 200
    r = await _move(client, booked["id"], _at(tomorrow, 15))
    assert r.status_code == 200, r.text
    assert r.json()["rescheduled_count"] == 2


async def test_booking_does_not_conflict_with_itself(client, db_session):
    """Сдвиг на полчаса внутри собственного интервала: без исключения своей
    записи из проверки такой перенос вечно получал бы «занято»."""
    ctx = await _setup(client, db_session, 3)
    booked = await _book(client, ctx, _at(ctx["today"], 17))

    r = await _move(client, booked["id"], _at(ctx["today"], 17, 30))
    assert r.status_code == 200, r.text
    assert r.json()["start_time"].startswith(_at(ctx["today"], 17, 30).isoformat()[:16])


# ── Отказы ──────────────────────────────────────────────────────────────────

async def test_taken_slot_gives_409(client, db_session):
    ctx = await _setup(client, db_session, 4)
    mine = await _book(client, ctx, _at(ctx["today"], 17))
    taken = _at(ctx["today"] + timedelta(days=1), 10)

    other = await register_user(client, "+79975550099")
    client.cookies.set("access_token", other["access_token"])
    await _book(client, ctx, taken)

    me = await client.post("/api/v1/auth/login", json={"phone": "+79975550004", "password": "Testpass1"})
    client.cookies.set("access_token", me.json()["access_token"])
    r = await _move(client, mine["id"], taken)
    assert r.status_code == 409, r.text

    async with db_session() as db:
        b = await db.get(Booking, mine["id"])
        assert b.start_time == _at(ctx["today"], 17)
        assert b.rescheduled_count == 0


async def test_past_time_gives_400(client, db_session):
    """«Прошлое» — по часам салона: в зоне салона сейчас ~12:00, и 09:00
    уже прошло, где бы ни стоял сервер."""
    ctx = await _setup(client, db_session, 5)
    booked = await _book(client, ctx, _at(ctx["today"], 17))

    r = await _move(client, booked["id"], _at(ctx["today"], 9))
    assert r.status_code == 400, r.text
    assert "прошедшее" in r.json()["detail"]


async def test_foreign_booking_is_not_found(client, db_session):
    ctx = await _setup(client, db_session, 6)
    booked = await _book(client, ctx, _at(ctx["today"], 17))

    stranger = await register_user(client, "+79975550098")
    client.cookies.set("access_token", stranger["access_token"])
    r = await _move(client, booked["id"], _at(ctx["today"] + timedelta(days=1), 10))
    assert r.status_code == 404
    # Ответ тот же, что на несуществующую: факт чужой записи не раскрываем.
    missing = await _move(client, 987654, _at(ctx["today"] + timedelta(days=1), 10))
    assert (missing.status_code, missing.json()) == (404, r.json())

    async with db_session() as db:
        assert (await db.get(Booking, booked["id"])).start_time == _at(ctx["today"], 17)


async def test_cancelled_booking_cannot_be_moved(client, db_session):
    ctx = await _setup(client, db_session, 7)
    booked = await _book(client, ctx, _at(ctx["today"], 17))
    assert (await client.post(f"/api/v1/bookings/{booked['id']}/cancel")).status_code == 200

    r = await _move(client, booked["id"], _at(ctx["today"] + timedelta(days=1), 10))
    assert r.status_code == 400
    assert "отменена" in r.json()["detail"]


# ── Скидка вечернего окна ───────────────────────────────────────────────────

async def test_evening_discount_is_dropped_when_moving_to_daytime(client, db_session):
    ctx = await _setup(client, db_session, 8, discount=40)
    booked = await _book(client, ctx, _at(ctx["today"], 14))
    assert (booked["discount_percent"], booked["final_price"]) == (40, 600)

    later = _at(ctx["today"], 17)
    q = await client.get(f"/api/v1/bookings/{booked['id']}/reschedule/quote",
                         params={"start_time": later.isoformat()})
    assert q.status_code == 200, q.text
    assert (q.json()["old_price"], q.json()["final_price"], q.json()["price_changed"]) == (600, 1000, True)

    r = await _move(client, booked["id"], later)
    assert r.status_code == 200, r.text
    assert (r.json()["discount_percent"], r.json()["final_price"]) == (0, 1000)


async def test_moving_into_evening_window_gives_no_new_discount(client, db_session):
    ctx = await _setup(client, db_session, 9, discount=40)
    booked = await _book(client, ctx, _at(ctx["today"], 17))
    assert booked["final_price"] == 1000

    r = await _move(client, booked["id"], _at(ctx["today"], 14, 30))
    assert r.status_code == 200, r.text
    assert (r.json()["discount_percent"], r.json()["final_price"]) == (0, 1000)


# ── Свободные окна для переноса ─────────────────────────────────────────────

async def test_reschedule_slots_free_the_booking_own_time(client, db_session):
    ctx = await _setup(client, db_session, 10)
    booked = await _book(client, ctx, _at(ctx["today"], 17))
    day = ctx["today"].date().isoformat()

    public = await client.get(f"/api/v1/bookings/available/{ctx['master_id']}",
                              params={"date": day, "service_id": ctx["service_id"]})
    mine = await client.get(f"/api/v1/bookings/{booked['id']}/reschedule/slots",
                            params={"date": day})
    assert mine.status_code == 200, mine.text
    public_slots, my_slots = set(public.json()["slots"]), set(mine.json()["slots"])
    # Окна, которые занимает сама запись, для её переноса свободны...
    assert public_slots < my_slots
    # ...но её нынешнее время не предлагается: перенос на него ничего не меняет.
    assert _at(ctx["today"], 17).strftime("%Y-%m-%dT%H:%M") not in my_slots


# ── Гостевая бронь по токену ────────────────────────────────────────────────

async def test_guest_reschedule_by_token(client, db_session):
    ctx = await _setup(client, db_session, 11)
    async with db_session() as db:
        from app.models.models import Salon
        await db.execute(update(Salon).where(Salon.id == ctx["salon_id"]).values(guest_booking_enabled=True))
        await db.commit()
    client.cookies.clear()
    r = await client.post("/api/v1/guest/booking", json={
        "salon_id": ctx["salon_id"], "master_id": ctx["master_id"], "service_id": ctx["service_id"],
        "start_time": _at(ctx["today"], 17).isoformat(), "name": "Гость", "phone": "+79975550011",
        "pd_consent": True,
    })
    assert r.status_code in (200, 201), r.text
    token, booking_id = r.json()["manage_token"], r.json()["booking_id"]

    new_start = _at(ctx["today"] + timedelta(days=1), 10)
    r = await client.post(f"/api/v1/guest/booking/{token}/reschedule",
                          json={"start_time": new_start.isoformat()})
    assert r.status_code == 200, r.text

    bad = await client.post("/api/v1/guest/booking/not-a-token/reschedule",
                            json={"start_time": new_start.isoformat()})
    assert bad.status_code == 404

    async with db_session() as db:
        b = await db.get(Booking, booking_id)
        assert (b.start_time, b.rescheduled_count) == (new_start, 1)
        assert await db.scalar(select(func.count()).select_from(Booking)) == 1


# ── Уведомления и напоминание ───────────────────────────────────────────────

async def test_notify_rescheduled_tells_master_and_requeues_reminder(client, db_session, monkeypatch):
    monkeypatch.setattr(notif.settings, "TG_NOTIFY_ENABLED", True)
    enqueued: list[tuple] = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            enqueued.append((fn, args, kwargs))

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr(notif, "get_arq_pool", fake_pool)
    import app.services.notify_channel as nc
    monkeypatch.setattr(nc, "get_arq_pool", fake_pool, raising=False)

    ctx = await _setup(client, db_session, 12)
    booked = await _book(client, ctx, _at(ctx["today"], 17))
    async with db_session() as db:
        await db.execute(update(User).where(User.phone == "+79975550012").values(tg_chat_id=333))
        await db.execute(update(User).where(User.phone == "+79885550012").values(tg_chat_id=222))
        await db.commit()

    enqueued.clear()
    new_start = _at(ctx["today"] + timedelta(days=1), 10)
    r = await _move(client, booked["id"], new_start)
    assert r.status_code == 200, r.text

    texts = [" ".join(map(str, args)) for fn, args, _ in enqueued if fn != "send_booking_reminder"]
    was, now = _at(ctx["today"], 17).strftime("%d.%m в %H:%M"), new_start.strftime("%d.%m в %H:%M")
    assert any(f"с {was} на {now}" in t for t in texts), texts

    [reminder] = [e for e in enqueued if e[0] == "send_booking_reminder"]
    assert reminder[1] == (booked["id"], 1)
    assert reminder[2]["_job_id"] == f"booking-reminder:{booked['id']}:1"


def test_topic_label_mentions_reschedules():
    assert notif.TOPIC_LABELS[notif.TOPIC_BOOKINGS] == "Записи (новые, переносы и отмены)"


async def test_reminder_is_silent_when_booking_time_changed(client, db_session):
    """Старое напоминание выстрелит в прежний час — задача обязана заметить,
    что время записи уже другое, и промолчать."""
    ctx = await _setup(client, db_session, 13)
    async with db_session() as db:
        await db.execute(update(User).where(User.phone == "+79975550013").values(tg_chat_id=444))
        await db.commit()
    # Запись через 1 ч 50 мин — сейчас как раз время напоминания.
    soon = _local_today(ctx["tz"]) + timedelta(hours=1, minutes=50)
    booked = await _book(client, ctx, soon)

    # Запись перенесли на завтра: прежний job приходит «вовремя» для старого
    # часа — и молчит, потому что для нынешнего start_time он не вовремя.
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booked["id"]).values(
            start_time=soon + timedelta(days=1), end_time=soon + timedelta(days=1, hours=1),
            rescheduled_count=1))
        await db.commit()
    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"]) == "skipped:stale"
    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0) == "skipped:stale"

    # Перенесли обратно, но номер переноса уже 2: job с номером 1 устарел,
    # хотя по времени попадает.
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booked["id"]).values(
            start_time=soon, end_time=soon + timedelta(hours=1), rescheduled_count=2))
        await db.commit()
    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 1) == "skipped:stale"


async def test_reminder_still_sent_for_untouched_booking(client, db_session, monkeypatch):
    """Обратная сторона защиты: нетронутая запись в окне напоминания — шлём."""
    sent = []

    async def tg_send(chat_id, text, *a, **kw):
        sent.append(chat_id)
        return True

    monkeypatch.setattr(tasks, "_send_via_telegram", tg_send, raising=False)
    ctx = await _setup(client, db_session, 14)
    async with db_session() as db:
        await db.execute(update(User).where(User.phone == "+79975550014").values(tg_chat_id=555))
        await db.commit()
    booked = await _book(client, ctx, _local_today(ctx["tz"]) + timedelta(hours=1, minutes=50))
    result = await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0)
    assert result == "sent" and sent == [555]


# ── Миграция ────────────────────────────────────────────────────────────────

def test_migration_downgrade_and_upgrade():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(pathlib.Path(__file__).resolve().parents[1] / "alembic.ini"))

    async def columns() -> set[str]:
        conn = await asyncpg.connect(_pg_dsn(settings.POSTGRES_DB))
        rows = await conn.fetch(
            "select column_name from information_schema.columns where table_name='bookings'")
        await conn.close()
        return {r["column_name"] for r in rows}

    try:
        alembic_command.downgrade(cfg, "7c3a91e5d2b8")
        assert not {"rescheduled_count", "rescheduled_at"} & asyncio.run(columns())
    finally:
        alembic_command.upgrade(cfg, "head")
    assert {"rescheduled_count", "rescheduled_at"} <= asyncio.run(columns())


# ── Интерфейс ───────────────────────────────────────────────────────────────

async def test_my_bookings_offers_reschedule_next_to_cancel(client, db_session):
    ctx = await _setup(client, db_session, 15)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    page = (await client.get("/bookings")).text
    assert f'data-reschedule-api="/api/v1/bookings/{booked["id"]}/reschedule"' in page
    assert 'id="rescheduleSheet"' in page
    assert "booking-cancel-btn" in page  # отмена никуда не делась


async def test_guest_page_offers_reschedule(client, db_session):
    ctx = await _setup(client, db_session, 16)
    async with db_session() as db:
        from app.models.models import Salon
        await db.execute(update(Salon).where(Salon.id == ctx["salon_id"]).values(guest_booking_enabled=True))
        await db.commit()
    client.cookies.clear()
    r = await client.post("/api/v1/guest/booking", json={
        "salon_id": ctx["salon_id"], "master_id": ctx["master_id"], "service_id": ctx["service_id"],
        "start_time": _at(ctx["today"] + timedelta(days=1), 10).isoformat(), "name": "Гость",
        "phone": "+79975550016", "pd_consent": True,
    })
    token = r.json()["manage_token"]
    page = (await client.get(f"/guest-booking/{token}")).text
    assert f'data-reschedule-api="/api/v1/guest/booking/{token}/reschedule"' in page
    assert 'id="rescheduleSheet"' in page


async def test_panel_marks_rescheduled_booking(client, db_session):
    ctx = await _setup(client, db_session, 17)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    owner = await client.post("/api/v1/auth/login",
                              json={"phone": ctx["owner_phone"], "password": "Bizpass1"})
    client_token = client.cookies.get("access_token")

    async def panel(tab):
        client.cookies.set("access_token", owner.json()["access_token"])
        r = await client.get(f"/business/dashboard?salon_id={ctx['salon_id']}&tab={tab}")
        client.cookies.set("access_token", client_token)
        assert r.status_code == 200, r.text[:300]
        return r.text

    assert "Перенесена" not in await panel("records")
    assert "Перенесена" not in await panel("schedule")

    r = await _move(client, booked["id"], _at(ctx["today"] + timedelta(days=1), 15))
    assert r.status_code == 200, r.text
    assert "Перенесена" in await panel("records")
    assert "Перенесена" in await panel("schedule")
