"""«Вечерние окна со скидкой»: настройка салона, определение окон, авто-скидка
при брони, страница-подборка, ежедневная ТГ-рассылка (cron-таск).

Детерминизм времени: салону выдаём таймзону, в которой сейчас ~12:00 (через
Etc/GMT-смещение), и рабочие часы на весь день — тогда вечернее окно 13:00–16:00
всегда в будущем и внутри графика независимо от реального времени CI.
"""
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonModerationStatus, SalonMember, SalonRole,
    Master, Service, Booking, BookingStatus, SalonEveningDeal,
)
from app.services import evening_deals_service as eds
from tests.conftest import register_user

WORK_ALL = json.dumps({d: "00:00-23:59" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


def _daytime_tz() -> str:
    """Имя Etc/GMT-зоны, в которой сейчас ~12:00 (детерминизм тестов времени)."""
    utc_h = datetime.now(timezone.utc).hour
    o = 12 - utc_h  # так, чтобы локальный час стал 12
    # Etc/GMT-N == UTC+N (знак инвертирован)
    if o == 0:
        return "Etc/GMT0"
    return f"Etc/GMT-{o}" if o > 0 else f"Etc/GMT+{-o}"


async def _mk_salon_deal(db_session, *, discount=20, ev_from=time(13, 0), ev_to=time(16, 0),
                         weekdays=None, service_ids=None, enabled=True, owner_phone="+79995554001",
                         name="ВечернийZZ", tz=None):
    tz = tz or _daytime_tz()
    async with db_session() as db:
        owner = User(phone=owner_phone, full_name="Вл", hashed_password=get_password_hash("Bizpass1"),
                     role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        salon = Salon(name=name, description="", address="Томск, ул. 1", latitude=56.5, longitude=84.9,
                      phone="+70000000000", is_active=True,
                      moderation_status=SalonModerationStatus.APPROVED, timezone=tz,
                      working_hours=WORK_ALL, creator_id=owner.id)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        master_user = User(phone=owner_phone.replace("+7999", "+7988"), full_name="Мастер",
                           hashed_password=get_password_hash("Testpass1"), role=UserRole.MASTER)
        db.add(master_user)
        await db.commit()
        await db.refresh(master_user)
        master = Master(user_id=master_user.id, salon_id=salon.id, specialization="парикмахер")
        db.add(master)
        await db.commit()
        await db.refresh(master)
        svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)
        deal = SalonEveningDeal(
            salon_id=salon.id, enabled=enabled, discount_percent=discount,
            evening_from=ev_from, evening_to=ev_to, weekdays=weekdays, service_ids=service_ids,
        )
        db.add(deal)
        await db.commit()
        return {"owner_phone": owner_phone, "salon_id": salon.id, "master_id": master.id,
                "service_id": svc.id, "tz": tz, "salon_name": name}


async def _login(client, phone, pw="Bizpass1"):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": pw})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])


async def _get_salon(db_session, sid):
    async with db_session() as db:
        return (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()


# ── Настройка (эндпоинты) ────────────────────────────────────────────────────

async def test_set_and_get_evening_deal(client, db_session):
    ctx = await _mk_salon_deal(db_session, enabled=False, discount=0, owner_phone="+79995554010")
    await _login(client, ctx["owner_phone"])
    sid = ctx["salon_id"]
    r = await client.post(f"/api/v1/business/my-salon/evening-deal?salon_id={sid}", json={
        "enabled": True, "discount_percent": 25, "evening_from": "18:00", "evening_to": "21:00",
        "weekdays": [0, 1, 2], "service_ids": [ctx["service_id"]],
    })
    assert r.status_code == 200, r.text
    g = await client.get(f"/api/v1/business/my-salon/evening-deal?salon_id={sid}")
    d = g.json()
    assert d["enabled"] and d["discount_percent"] == 25
    assert d["evening_from"] == "18:00" and d["evening_to"] == "21:00"
    assert d["weekdays"] == [0, 1, 2] and d["service_ids"] == [ctx["service_id"]]


async def test_set_evening_deal_validation(client, db_session):
    ctx = await _mk_salon_deal(db_session, enabled=False, owner_phone="+79995554011")
    await _login(client, ctx["owner_phone"])
    sid = ctx["salon_id"]
    # скидка вне диапазона
    r = await client.post(f"/api/v1/business/my-salon/evening-deal?salon_id={sid}", json={
        "enabled": True, "discount_percent": 150, "evening_from": "18:00", "evening_to": "21:00"})
    assert r.status_code == 422
    # начало позже конца
    r = await client.post(f"/api/v1/business/my-salon/evening-deal?salon_id={sid}", json={
        "enabled": True, "discount_percent": 20, "evening_from": "21:00", "evening_to": "18:00"})
    assert r.status_code == 422


async def test_set_evening_deal_requires_permission(client, db_session):
    ctx = await _mk_salon_deal(db_session, owner_phone="+79995554012")
    data = await register_user(client, "+79995554099")  # посторонний
    client.cookies.set("access_token", data["access_token"])
    r = await client.post(f"/api/v1/business/my-salon/evening-deal?salon_id={ctx['salon_id']}", json={
        "enabled": True, "discount_percent": 20, "evening_from": "18:00", "evening_to": "21:00"})
    assert r.status_code in (403, 404), r.text


# ── Определение окон / скидки ────────────────────────────────────────────────

async def test_evening_deal_discount_in_and_out_of_window(client, db_session):
    ctx = await _mk_salon_deal(db_session, discount=30, ev_from=time(13, 0), ev_to=time(16, 0),
                               owner_phone="+79995554020")
    salon = await _get_salon(db_session, ctx["salon_id"])
    tz = ctx["tz"]
    today = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    in_window = today.replace(hour=14, minute=0, second=0, microsecond=0)
    out_window = today.replace(hour=10, minute=0, second=0, microsecond=0)
    async with db_session() as db:
        assert await eds.evening_deal_discount(db, salon, in_window, ctx["service_id"]) == 30
        assert await eds.evening_deal_discount(db, salon, out_window, ctx["service_id"]) == 0


async def test_evening_deal_respects_weekday_and_service_filter(client, db_session):
    tz = _daytime_tz()
    today_wd = datetime.now(ZoneInfo(tz)).weekday()
    other_wd = (today_wd + 1) % 7
    ctx = await _mk_salon_deal(db_session, discount=20, weekdays=[other_wd],
                               owner_phone="+79995554021", tz=tz)
    salon = await _get_salon(db_session, ctx["salon_id"])
    today = datetime.now(ZoneInfo(tz)).replace(tzinfo=None).replace(hour=14, minute=0, second=0, microsecond=0)
    async with db_session() as db:
        # сегодня не входит в weekdays → скидки нет
        assert await eds.evening_deal_discount(db, salon, today, ctx["service_id"]) == 0

    # услуга вне фильтра
    ctx2 = await _mk_salon_deal(db_session, discount=20, service_ids=[999999],
                                owner_phone="+79995554022", tz=tz)
    salon2 = await _get_salon(db_session, ctx2["salon_id"])
    async with db_session() as db:
        assert await eds.evening_deal_discount(db, salon2, today, ctx2["service_id"]) == 0


async def test_any_windows_today(client, db_session):
    async with db_session() as db:
        assert await eds.any_windows_today(db) is False  # пусто
    await _mk_salon_deal(db_session, owner_phone="+79995554030")
    async with db_session() as db:
        assert await eds.any_windows_today(db) is True


async def test_build_feed_lists_discounted_services(client, db_session):
    ctx = await _mk_salon_deal(db_session, discount=25, name="ФидZZ", owner_phone="+79995554031")
    async with db_session() as db:
        feed = await eds.build_feed(db)
    names = [c["salon_name"] for c in feed["cards"]]
    assert "ФидZZ" in names
    card = next(c for c in feed["cards"] if c["salon_name"] == "ФидZZ")
    svc = card["masters"][0]["services"][0]
    assert svc["old_price"] == 1000 and svc["new_price"] == 750  # -25%


# ── Авто-скидка при брони ────────────────────────────────────────────────────

async def _book(client, master_id, service_id, when: datetime):
    return await client.post("/api/v1/bookings", json={
        "master_id": master_id, "service_id": service_id, "start_time": when.isoformat(),
    })


async def test_booking_in_window_gets_discount(client, db_session):
    ctx = await _mk_salon_deal(db_session, discount=40, ev_from=time(13, 30), ev_to=time(16, 0),
                               owner_phone="+79995554040")
    tz = ctx["tz"]
    today = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    data = await register_user(client, "+79995554041")
    client.cookies.set("access_token", data["access_token"])

    when = today.replace(hour=14, minute=0, second=0, microsecond=0)
    r = await _book(client, ctx["master_id"], ctx["service_id"], when)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["discount_percent"] == 40
    assert body["final_price"] == 600  # 1000 - 40%


async def test_booking_out_of_window_no_discount(client, db_session):
    ctx = await _mk_salon_deal(db_session, discount=40, ev_from=time(13, 30), ev_to=time(16, 0),
                               owner_phone="+79995554042")
    tz = ctx["tz"]
    today = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    data = await register_user(client, "+79995554043")
    client.cookies.set("access_token", data["access_token"])

    when = today.replace(hour=13, minute=0, second=0, microsecond=0)  # раньше окна, но в будущем
    r = await _book(client, ctx["master_id"], ctx["service_id"], when)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["discount_percent"] == 0
    assert body["final_price"] == 1000


# ── Страница ─────────────────────────────────────────────────────────────────

async def test_evening_deals_page_renders(client, db_session):
    await _mk_salon_deal(db_session, name="СтраницаZZ", owner_phone="+79995554050")
    r = await client.get("/evening-deals")
    assert r.status_code == 200
    assert "СтраницаZZ" in r.text


# ── Рассылка (cron-таск) ─────────────────────────────────────────────────────

async def test_blast_enqueues_for_opted_in(client, db_session, monkeypatch):
    import app.core.worker as worker_mod
    from app import tasks

    jobs = []

    class _FakePool:
        async def enqueue_job(self, name, *args, **kwargs):
            jobs.append((name, args))

    async def _fake_pool():
        return _FakePool()

    monkeypatch.setattr(worker_mod, "get_arq_pool", _fake_pool)

    await _mk_salon_deal(db_session, owner_phone="+79995554060")
    # клиент с привязанным ТГ, хочет рассылку; и второй — отключил.
    async with db_session() as db:
        db.add(User(phone="+79995554061", full_name="К1", tg_chat_id=111,
                    hashed_password=get_password_hash("x"), role=UserRole.CLIENT))
        db.add(User(phone="+79995554062", full_name="К2", tg_chat_id=222,
                    tg_notify_prefs={"evening_deals": False},
                    hashed_password=get_password_hash("x"), role=UserRole.CLIENT))
        await db.commit()

    res = await tasks.send_evening_deals_blast({"job_try": 1})
    assert res == "queued:1", res
    chat_ids = {args[0] for name, args in jobs if name == "send_tg_message"}
    assert chat_ids == {111}


async def test_blast_skipped_when_no_windows(client, db_session, monkeypatch):
    import app.core.worker as worker_mod
    from app import tasks

    async def _fake_pool():
        raise AssertionError("не должно вызываться, если окон нет")

    monkeypatch.setattr(worker_mod, "get_arq_pool", _fake_pool)
    # акция выключена → окон нет
    await _mk_salon_deal(db_session, enabled=False, owner_phone="+79995554070")
    async with db_session() as db:
        db.add(User(phone="+79995554071", full_name="К", tg_chat_id=333,
                    hashed_password=get_password_hash("x"), role=UserRole.CLIENT))
        await db.commit()
    res = await tasks.send_evening_deals_blast({"job_try": 1})
    assert res == "skipped:no-windows"
