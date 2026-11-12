"""Подтверждение и перенос записи из бота (решение 0020, сессия B).

Стенд тот же, что у переноса (test_booking_reschedule): салон в зоне, где
сейчас ~12:00, график на весь день. Проверяем три вещи, за которые платит
живой человек: «Буду» не трогает денежный статус, кнопки доезжают во все три
мессенджера (и не доезжают в почту), а занятое окно не оставляет диалог в
тупике.
"""
import asyncio
import json
import pathlib
from datetime import datetime, timedelta

import asyncpg
import pytest
from sqlalchemy import select, update

import app.services.notifications as notif
import app.tasks as tasks
from app import vk_bot
from app.core.config import settings
from app.models.models import Booking, BookingStatus, NotifyChannel, User
from app.services import bot_actions, bot_keyboards
from tests.conftest import _pg_dsn
from tests.test_booking_reschedule import _at, _book, _local_today, _setup


async def _client_user(db_session, ctx, n: int) -> int:
    async with db_session() as db:
        return (await db.execute(
            select(User.id).where(User.phone == f"+7997555{n:04d}")
        )).scalar_one()


async def _booking(db_session, booking_id):
    async with db_session() as db:
        return await db.get(Booking, booking_id)


@pytest.fixture()
def fake_pool(monkeypatch):
    """Очередь уведомлений в список: что именно ушло салону."""
    jobs: list[tuple] = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            jobs.append((fn, args, kwargs))

    async def pool():
        return FakePool()

    monkeypatch.setattr(notif, "get_arq_pool", pool)
    import app.services.notify_channel as nc
    monkeypatch.setattr(nc, "get_arq_pool", pool, raising=False)
    monkeypatch.setattr(notif.settings, "TG_NOTIFY_ENABLED", True)
    return jobs


@pytest.fixture()
def vk_bot_sent(monkeypatch):
    """Клиентское сообщество ВК, отправка — в список.

    Роль процесса по умолчанию бизнесовая, а кнопки записи клиентские: без
    подмены бот искал бы человека по бизнесовому диалогу (решение 0013).
    """
    import app.core.config as config_mod
    from app.services import vk_api

    monkeypatch.setattr(config_mod.settings, "VK_BOT_ROLE", "client")
    sent = []

    async def send_message(peer_id, text, keyboard=None, *, token):
        sent.append({"peer": peer_id, "text": text, "kb": keyboard})

    monkeypatch.setattr(vk_api, "send_message", send_message)
    return sent


# ── «Буду»: новое поле, не статус ───────────────────────────────────────────

async def test_confirm_writes_field_and_never_touches_status(client, db_session):
    """Статус CONFIRMED считается выручкой — тап клиента его не ставит."""
    ctx = await _setup(client, db_session, 30)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, ctx, 30)

    async with db_session() as db:
        ok, text = await bot_actions.confirm_booking(db, user_id, booked["id"])
    assert ok and "ждём вас" in text

    b = await _booking(db_session, booked["id"])
    assert b.client_confirmed_at is not None
    assert b.status == BookingStatus.PENDING


async def test_second_tap_does_not_rewrite_the_time(client, db_session, fake_pool):
    ctx = await _setup(client, db_session, 31)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, ctx, 31)

    async with db_session() as db:
        await bot_actions.confirm_booking(db, user_id, booked["id"])
    first = (await _booking(db_session, booked["id"])).client_confirmed_at
    sent_after_first = len(fake_pool)

    async with db_session() as db:
        ok, text = await bot_actions.confirm_booking(db, user_id, booked["id"])
    assert not ok and "уже подтвердили" in text
    assert (await _booking(db_session, booked["id"])).client_confirmed_at == first
    # и салон не дёргаем вторым сообщением об одном и том же нажатии
    assert len(fake_pool) == sent_after_first


async def test_confirm_tells_the_master(client, db_session, fake_pool):
    ctx = await _setup(client, db_session, 32)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, ctx, 32)
    async with db_session() as db:
        await db.execute(update(User).where(User.phone == f"+7988555{32:04d}")
                         .values(tg_chat_id=9032))
        await db.commit()

    async with db_session() as db:
        await bot_actions.confirm_booking(db, user_id, booked["id"])

    texts = [a[1] for fn, a, _ in fake_pool if fn == "send_tg_message"]
    assert any("подтвердил визит" in t for t in texts), fake_pool


async def test_stranger_cannot_confirm_someone_elses_booking(client, db_session):
    ctx = await _setup(client, db_session, 33)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    async with db_session() as db:
        stranger = (await db.execute(
            select(User.id).where(User.phone == ctx["owner_phone"]))).scalar_one()
        ok, text = await bot_actions.confirm_booking(db, stranger, booked["id"])
    assert (ok, text) == (False, "Запись не найдена.")
    assert (await _booking(db_session, booked["id"])).client_confirmed_at is None


# ── Напоминание: текст и кнопки ─────────────────────────────────────────────

async def test_reminder_text_is_the_one_chosen(client, db_session, monkeypatch):
    sent = []

    async def tg_send(chat_id, text, reply_markup=None):
        sent.append((text, reply_markup))
        return True

    monkeypatch.setattr(tasks, "_send_via_telegram", tg_send)
    ctx = await _setup(client, db_session, 34)
    async with db_session() as db:
        await db.execute(update(User).where(User.phone == f"+7997555{34:04d}")
                         .values(tg_chat_id=9034))
        await db.commit()
    start = _local_today(ctx["tz"]) + timedelta(hours=1, minutes=50)
    booked = await _book(client, ctx, start)

    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0) == "sent"
    text, markup = sent[0]
    assert text == (
        f"Сегодня в {start:%H:%M} ждём вас: «Стрижка», «ПереносZZ34»\n"
        "Томск, ул. 1\n\n"
        "Подтвердите пожалуйста — мастеру так спокойнее."
    )
    labels = [b["text"] for row in markup["inline_keyboard"] for b in row]
    assert labels == ["Буду", "Перенести", "Не смогу"]


def test_reminder_says_tomorrow_when_the_visit_is_past_midnight():
    """Напоминание за два часа до визита в 00:30 уходит накануне — «сегодня»
    в нём было бы неправдой."""
    salon = type("S", (), {"timezone": "Etc/GMT0", "name": "Радуга", "address": "ул. Ленина 1"})()
    service = type("Svc", (), {"name": "Стрижка"})()
    tomorrow = datetime.utcnow().replace(hour=0, minute=30, second=0, microsecond=0) \
        + timedelta(days=1)
    booking = type("B", (), {"start_time": tomorrow})()
    assert tasks.reminder_text(booking, salon, service).startswith("Завтра в 00:30 ждём вас")


@pytest.mark.parametrize("channel", [NotifyChannel.TG, NotifyChannel.VK, NotifyChannel.MAX])
async def test_buttons_reach_every_messenger(channel, monkeypatch):
    """Три кнопки под напоминанием доезжают в каждый мессенджер."""
    got = {}

    async def tg(chat_id, text, reply_markup=None):
        got["kb"] = [b["text"] for row in reply_markup["inline_keyboard"] for b in row]
        return True

    async def vk(peer_id, text, keyboard=None, *, community):
        got["kb"] = [b["action"]["label"] for row in keyboard["buttons"] for b in row]
        return True

    async def mx(chat_id, text, attachments=None):
        got["kb"] = [b.text for row in attachments[0].payload.buttons for b in row]
        return True

    monkeypatch.setattr(tasks, "_send_via_telegram", tg)
    monkeypatch.setattr(tasks, "_send_via_vk", vk)
    monkeypatch.setattr(tasks, "_send_via_max", mx)

    await tasks._deliver(channel, 500, "Напоминание", audience="client",
                         buttons=bot_actions.booking_buttons(77))
    assert got["kb"] == ["Буду", "Перенести", "Не смогу"]


async def test_email_gets_a_link_instead_of_buttons(monkeypatch):
    """У почты кнопок нет — но действие должно остаться доступным."""
    letters = []

    async def smtp(to, subject, body, html=None):
        letters.append(body)
        return True

    monkeypatch.setattr(tasks, "_send_via_smtp", smtp)
    await tasks._deliver(NotifyChannel.EMAIL, "c@example.com", "Напоминание",
                         audience="client", buttons=bot_actions.booking_buttons(77))
    assert "/bookings" in letters[0]
    assert "Буду" not in letters[0]


def test_vk_keyboard_stays_within_six_rows():
    """Шесть окон плюс ссылка: по две кнопки в ряд — иначе ВК не отправит."""
    buttons = [bot_actions.BotButton(f"окно {n}", f"rsc:1:2026-11-13T1{n}:00")
               for n in range(6)]
    buttons.append(bot_actions.BotButton("Другое время", url="https://rrumi.ru/bookings"))
    rows = bot_keyboards.vk(buttons)["buttons"]
    assert len(rows) == 4 and [len(r) for r in rows] == [2, 2, 2, 1]
    assert json.loads(rows[0][0]["action"]["payload"])["c"].startswith("rsc:1:")


# ── Перенос из бота ─────────────────────────────────────────────────────────

async def test_bot_reschedule_moves_the_same_booking(client, db_session, fake_pool):
    ctx = await _setup(client, db_session, 35)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, ctx, 35)

    async with db_session() as db:
        text, buttons = await bot_actions.reschedule_options(db, user_id, booked["id"])
    assert "новое время" in text
    assert len(buttons) == bot_actions.RESCHEDULE_SLOTS + 1   # окна плюс «Другое время»
    assert buttons[-1].url.endswith("/bookings")

    chosen = buttons[0].command.split(":", 2)[2]
    async with db_session() as db:
        ok, told = await bot_actions.reschedule_to(db, user_id, booked["id"], chosen)
    assert ok, told

    b = await _booking(db_session, booked["id"])
    assert b.id == booked["id"] and b.rescheduled_count == 1
    assert b.start_time == datetime.fromisoformat(chosen)


async def test_taken_slot_shows_a_fresh_list_instead_of_a_dead_end(
        client, db_session, vk_bot_sent, fake_pool):
    ctx = await _setup(client, db_session, 36)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, ctx, 36)
    async with db_session() as db:
        await db.execute(update(User).where(User.id == user_id).values(vk_client_peer_id=936))

        text, buttons = await bot_actions.reschedule_options(db, user_id, booked["id"])
        chosen = buttons[0].command.split(":", 2)[2]
        # Пока человек выбирал, окно занял другой клиент.
        taken = datetime.fromisoformat(chosen)
        db.add(Booking(client_id=user_id + 0, master_id=ctx["master_id"],
                       service_id=ctx["service_id"], start_time=taken,
                       end_time=taken + timedelta(minutes=60),
                       status=BookingStatus.PENDING, final_price=1000))
        await db.commit()

    await vk_bot.reschedule_from_bot(936, booked["id"], chosen)

    # Первое сообщение — отказ, второе — свежий список с кнопками.
    assert "занят" in vk_bot_sent[0]["text"].lower()
    assert vk_bot_sent[1]["kb"] is not None
    assert (await _booking(db_session, booked["id"])).rescheduled_count == 0


async def test_vk_bookings_list_offers_all_three_buttons(client, db_session, vk_bot_sent):
    ctx = await _setup(client, db_session, 37)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, ctx, 37)
    async with db_session() as db:
        await db.execute(update(User).where(User.id == user_id).values(vk_client_peer_id=937))
        await db.commit()

    await vk_bot.show_bookings(937)
    commands = [json.loads(b["action"]["payload"])["c"]
                for row in vk_bot_sent[-1]["kb"]["buttons"] for b in row]
    assert commands == [f"cfm:{booked['id']}", f"rsc:{booked['id']}", f"cnl:{booked['id']}"]


def test_client_community_accepts_the_new_commands(monkeypatch):
    """Кнопки записи клиентские — клиентское сообщество обязано их принять.

    Роль подменяем явно: у бизнесового _allowed пропускает всё подряд
    (там остались кнопки из старых сообщений), и проверка была бы пустой.
    """
    import app.core.config as config_mod

    monkeypatch.setattr(config_mod.settings, "VK_BOT_ROLE", "client")
    assert vk_bot._is_client()
    assert vk_bot._allowed("cfm:1") and vk_bot._allowed("rsc:1:2026-11-13T10:00")


# ── Панель салона ───────────────────────────────────────────────────────────

async def test_panel_marks_client_confirmation(client, db_session):
    ctx = await _setup(client, db_session, 38)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, ctx, 38)
    owner = await client.post("/api/v1/auth/login",
                              json={"phone": ctx["owner_phone"], "password": "Bizpass1"})
    client_token = client.cookies.get("access_token")

    async def panel(tab):
        client.cookies.set("access_token", owner.json()["access_token"])
        r = await client.get(f"/business/dashboard?salon_id={ctx['salon_id']}&tab={tab}")
        client.cookies.set("access_token", client_token)
        assert r.status_code == 200, r.text[:300]
        return r.text

    chip = "Клиент подтвердил</span>"
    for tab in ("records", "schedule"):
        assert chip not in await panel(tab)

    async with db_session() as db:
        await bot_actions.confirm_booking(db, user_id, booked["id"])
    for tab in ("records", "schedule"):
        assert chip in await panel(tab), tab


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
        alembic_command.downgrade(cfg, "a765971adfd9")
        assert "client_confirmed_at" not in asyncio.run(columns())
    finally:
        alembic_command.upgrade(cfg, "head")
    assert "client_confirmed_at" in asyncio.run(columns())
