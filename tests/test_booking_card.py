"""Живая карточка записи (решение 0021): тап правит ТО ЖЕ сообщение.

До 0021 каждый тап слал новое сообщение, а исходная карточка оставалась с
прежним временем и живыми кнопками: после переноса на 13:00 она по-прежнему
предлагала подтвердить визит на 10:00. Здесь проверяется, что этого больше
нет — во всех трёх мессенджерах, а не только в Telegram.

Стенд тот же, что у переноса (test_booking_reschedule): салон в зоне, где
сейчас ~12:00, график на весь день.
"""
import asyncio
import pathlib
from datetime import timedelta

import asyncpg
import pytest
from sqlalchemy import select, update

import app.services.notifications as notif
import app.tasks as tasks
from app import max_bot, tg_bot, vk_bot
from app.core.config import settings
from app.models.models import Booking, BookingStatus, NotifyChannel, User
from app.services import booking_card
from tests.conftest import _pg_dsn
from tests.test_booking_reschedule import _at, _book, _local_today, _setup


async def _client_user(db_session, n: int) -> int:
    async with db_session() as db:
        return (await db.execute(
            select(User.id).where(User.phone == f"+7997555{n:04d}")
        )).scalar_one()


async def _booking(db_session, booking_id):
    async with db_session() as db:
        return await db.get(Booking, booking_id)


@pytest.fixture()
def queue(monkeypatch):
    """Очередь ARQ в список — и для уведомлений, и для обновления карточки.

    booking_card.enqueue_refresh берёт пул из app.core.worker в момент
    вызова, поэтому подменять нужно именно там: подмены в notifications,
    как в соседних тестах, здесь мало.
    """
    import app.core.worker as worker_mod
    import app.services.notify_channel as nc

    jobs: list[tuple] = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            jobs.append((fn, args, kwargs))

    async def pool():
        return FakePool()

    monkeypatch.setattr(worker_mod, "get_arq_pool", pool)
    monkeypatch.setattr(notif, "get_arq_pool", pool)
    monkeypatch.setattr(nc, "get_arq_pool", pool, raising=False)
    monkeypatch.setattr(notif.settings, "TG_NOTIFY_ENABLED", True)
    return jobs


# ── Поддельные события трёх мессенджеров ────────────────────────────────────

class FakeTgMessage:
    """Сообщение aiogram: правка и ответ — в списки, без сети."""

    def __init__(self, chat_id: int, message_id: int = 555, fail_edit: Exception | None = None):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.message_id = message_id
        self.edits: list[tuple] = []
        self.answers: list[tuple] = []
        self._fail_edit = fail_edit

    async def edit_text(self, text, reply_markup=None):
        if self._fail_edit is not None:
            raise self._fail_edit
        self.edits.append((text, reply_markup))

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))
        return type("Sent", (), {"message_id": self.message_id})()


class FakeTgCallback:
    def __init__(self, data: str, chat_id: int, **kw):
        self.data = data
        self.message = FakeTgMessage(chat_id, **kw)
        self.answered: list = []

    async def answer(self, text=None, **kw):
        self.answered.append(text)


class FakeMaxEvent:
    """MessageCallback maxapi: edit правит сообщение и отвечает на нажатие."""

    def __init__(self, chat_id: int, mid: str = "mid-1", fail_edit: Exception | None = None):
        self._chat_id = chat_id
        self.message = type("M", (), {"body": type("B", (), {"mid": mid})()})()
        self.edits: list[tuple] = []
        self.sent: list[tuple] = []
        self._fail_edit = fail_edit
        outer = self

        class FakeBot:
            async def send_message(self, chat_id, text, attachments=None):
                outer.sent.append((text, attachments))
                return type("S", (), {"message": type("M", (), {
                    "body": type("B", (), {"mid": "mid-new"})()})()})()

        self.bot = FakeBot()

    def get_ids(self):
        return self._chat_id, self._chat_id

    async def edit(self, text=None, attachments=None, **kw):
        if self._fail_edit is not None:
            raise self._fail_edit
        self.edits.append((text, attachments))


@pytest.fixture()
def vk_calls(monkeypatch):
    """Клиентское сообщество ВК: отправка и правка — в списки.

    Роль процесса по умолчанию бизнесовая, а кнопки записи клиентские
    (решение 0013) — подменяем явно.
    """
    import app.core.config as config_mod
    from app.services import vk_api

    monkeypatch.setattr(config_mod.settings, "VK_BOT_ROLE", "client")
    calls = {"sent": [], "edited": []}

    async def send_message(peer_id, text, keyboard=None, *, token):
        calls["sent"].append({"peer": peer_id, "text": text, "kb": keyboard})
        return 7000 + len(calls["sent"])

    async def edit_message(peer_id, text, keyboard=None, *, message_id=None, cmid=None, token):
        calls["edited"].append({"peer": peer_id, "text": text, "kb": keyboard,
                                "message_id": message_id, "cmid": cmid})
        return 1

    monkeypatch.setattr(vk_api, "send_message", send_message)
    monkeypatch.setattr(vk_api, "edit_message", edit_message)
    return calls


async def _link(db_session, user_id: int, **fields):
    async with db_session() as db:
        await db.execute(update(User).where(User.id == user_id).values(**fields))
        await db.commit()


def _tg_labels(markup) -> list[str]:
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


def _vk_labels(kb) -> list[str]:
    if not kb:
        return []
    return [b["action"]["label"] for row in kb["buttons"] for b in row]


def _max_labels(attachments) -> list[str]:
    if not attachments:
        return []
    return [b.text for row in attachments[0].payload.buttons for b in row]


# ── Тап по «Перенести»: та же карточка, без нового сообщения ────────────────

async def test_tg_reschedule_edits_the_same_message(client, db_session, queue):
    ctx = await _setup(client, db_session, 60)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, 60)
    await _link(db_session, user_id, tg_chat_id=9060)

    cb = FakeTgCallback(f"rsc:{booked['id']}", 9060)
    await tg_bot.on_reschedule(cb)

    assert cb.message.answers == []          # ни одного лишнего сообщения
    assert len(cb.message.edits) == 1
    text, markup = cb.message.edits[0]
    assert "Выберите новое время" in text
    assert "Стрижка" in text                 # карточка осталась карточкой
    assert len(_tg_labels(markup)) == 7      # шесть окон и «Другое время»


async def test_vk_reschedule_edits_the_same_message(client, db_session, queue, vk_calls):
    ctx = await _setup(client, db_session, 61)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, 61)
    await _link(db_session, user_id, vk_client_peer_id=961)

    await vk_bot.reschedule_from_bot(961, booked["id"], "", 321)

    assert vk_calls["sent"] == []
    assert len(vk_calls["edited"]) == 1
    edited = vk_calls["edited"][0]
    assert edited["cmid"] == 321 and edited["peer"] == 961
    assert "Выберите новое время" in edited["text"]
    assert len(_vk_labels(edited["kb"])) == 7


async def test_max_reschedule_edits_the_same_message(client, db_session, queue):
    ctx = await _setup(client, db_session, 62)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, 62)
    await _link(db_session, user_id, max_chat_id=9062)

    event = FakeMaxEvent(9062)
    await max_bot._reschedule_from_bot(event, booked["id"], "")

    assert event.sent == []
    assert len(event.edits) == 1
    text, attachments = event.edits[0]
    assert "Выберите новое время" in text
    assert len(_max_labels(attachments)) == 7


# ── Тап по окну: карточка с новым временем ──────────────────────────────────

@pytest.mark.parametrize("channel", ["tg", "vk", "max"])
async def test_tap_on_a_slot_returns_the_card_with_the_new_time(
        channel, client, db_session, queue, vk_calls):
    n = {"tg": 63, "vk": 64, "max": 65}[channel]
    ctx = await _setup(client, db_session, n)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, n)

    async with db_session() as db:
        from app.services.bot_actions import reschedule_options
        _, buttons = await reschedule_options(db, user_id, booked["id"])
    chosen = buttons[0].command.split(":", 2)[2]

    if channel == "tg":
        await _link(db_session, user_id, tg_chat_id=9000 + n)
        cb = FakeTgCallback(f"rsc:{booked['id']}:{chosen}", 9000 + n)
        await tg_bot.on_reschedule(cb)
        assert cb.message.answers == []
        [(text, markup)] = cb.message.edits
        labels = _tg_labels(markup)
    elif channel == "vk":
        await _link(db_session, user_id, vk_client_peer_id=9000 + n)
        await vk_bot.reschedule_from_bot(9000 + n, booked["id"], chosen, 777)
        assert vk_calls["sent"] == []
        [edited] = vk_calls["edited"]
        text, labels = edited["text"], _vk_labels(edited["kb"])
    else:
        await _link(db_session, user_id, max_chat_id=9000 + n)
        event = FakeMaxEvent(9000 + n)
        await max_bot._reschedule_from_bot(event, booked["id"], chosen)
        assert event.sent == []
        [(text, attachments)] = event.edits
        labels = _max_labels(attachments)

    moved = await _booking(db_session, booked["id"])
    assert moved.rescheduled_count == 1
    assert f"{moved.start_time:%d.%m в %H:%M}" in text
    assert booking_card.NOTE_RESCHEDULED in text
    # Перенесённую запись ещё можно подтвердить или отменить
    assert labels == ["Буду", "Перенести", "Не смогу"]


# ── «Буду»: карточка с галочкой и без кнопок ────────────────────────────────

@pytest.mark.parametrize("channel", ["tg", "vk", "max"])
async def test_confirm_leaves_the_card_without_buttons(
        channel, client, db_session, queue, vk_calls):
    n = {"tg": 66, "vk": 67, "max": 68}[channel]
    ctx = await _setup(client, db_session, n)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, n)

    if channel == "tg":
        await _link(db_session, user_id, tg_chat_id=9000 + n)
        cb = FakeTgCallback(f"cfm:{booked['id']}", 9000 + n)
        await tg_bot.on_confirm_booking(cb)
        assert cb.message.answers == []
        [(text, markup)] = cb.message.edits
        labels = _tg_labels(markup)
    elif channel == "vk":
        await _link(db_session, user_id, vk_client_peer_id=9000 + n)
        await vk_bot.confirm_from_bot(9000 + n, booked["id"], 778)
        assert vk_calls["sent"] == []
        [edited] = vk_calls["edited"]
        text, labels = edited["text"], _vk_labels(edited["kb"])
    else:
        await _link(db_session, user_id, max_chat_id=9000 + n)
        event = FakeMaxEvent(9000 + n)
        await max_bot._confirm_from_bot(event, booked["id"])
        assert event.sent == []
        [(text, attachments)] = event.edits
        labels = _max_labels(attachments)

    assert booking_card.NOTE_CONFIRMED in text
    assert labels == []
    assert (await _booking(db_session, booked["id"])).client_confirmed_at is not None


async def test_cancel_leaves_the_card_without_buttons(client, db_session, queue):
    ctx = await _setup(client, db_session, 69)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, 69)
    await _link(db_session, user_id, tg_chat_id=9069)

    cb = FakeTgCallback(f"cnl:{booked['id']}", 9069)
    await tg_bot.on_cancel_booking(cb)

    assert cb.message.answers == []
    [(text, markup)] = cb.message.edits
    assert booking_card.NOTE_CANCELLED in text
    assert _tg_labels(markup) == []
    assert (await _booking(db_session, booked["id"])).status == BookingStatus.CANCELLED


async def test_stranger_does_not_get_someone_elses_card(client, db_session, queue):
    """Карточку чужой записи не рисуем: по номеру записи иначе вытаскивалось
    бы время и название салона чужого визита."""
    ctx = await _setup(client, db_session, 70)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    async with db_session() as db:
        stranger = (await db.execute(
            select(User.id).where(User.phone == ctx["owner_phone"]))).scalar_one()
    await _link(db_session, stranger, tg_chat_id=9070)

    cb = FakeTgCallback(f"cfm:{booked['id']}", 9070)
    await tg_bot.on_confirm_booking(cb)

    assert cb.message.edits == [] and cb.message.answers == []
    assert cb.answered == ["Запись не найдена."]


@pytest.mark.parametrize("channel", ["vk", "max"])
async def test_stranger_still_gets_an_answer(channel, client, db_session, queue, vk_calls):
    """Карточки чужой записи нет — но нажатие без ответа выглядит как
    сломанный бот, поэтому отказ человек видит."""
    n = {"vk": 86, "max": 87}[channel]
    ctx = await _setup(client, db_session, n)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    async with db_session() as db:
        stranger = (await db.execute(
            select(User.id).where(User.phone == ctx["owner_phone"]))).scalar_one()

    if channel == "vk":
        await _link(db_session, stranger, vk_client_peer_id=9000 + n)
        told = await vk_bot.confirm_from_bot(9000 + n, booked["id"], 123)
        assert told == "Запись не найдена."
        assert vk_calls["edited"] == [] and vk_calls["sent"] == []
    else:
        await _link(db_session, stranger, max_chat_id=9000 + n)
        event = FakeMaxEvent(9000 + n)
        await max_bot._confirm_from_bot(event, booked["id"])
        assert event.edits == []
        assert event.sent == [("Запись не найдена.", None)]


# ── Номер сообщения сохраняется при отправке напоминания ────────────────────

@pytest.mark.parametrize("channel,field,sent_id,expected", [
    ("tg", "tg_chat_id", 4242, "4242"),
    ("max", "max_chat_id", "mid-7", "mid-7"),
    ("vk", "vk_client_peer_id", 909, "909"),
])
async def test_reminder_remembers_where_the_card_is(
        channel, field, sent_id, expected, client, db_session, monkeypatch):
    n = {"tg": 71, "max": 72, "vk": 73}[channel]

    async def tg(chat_id, text, reply_markup=None):
        return sent_id

    async def mx(chat_id, text, attachments=None):
        return sent_id

    async def vk(peer_id, text, keyboard=None, *, community):
        return sent_id

    monkeypatch.setattr(tasks, "_send_via_telegram", tg)
    monkeypatch.setattr(tasks, "_send_via_max", mx)
    monkeypatch.setattr(tasks, "_send_via_vk", vk)

    ctx = await _setup(client, db_session, n)
    user_id = await _client_user(db_session, n)
    chat = 9100 + n
    await _link(db_session, user_id, **{field: chat},
                notify_channel=NotifyChannel(channel))
    start = _local_today(ctx["tz"]) + timedelta(hours=1, minutes=50)
    booked = await _book(client, ctx, start)

    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0) == "sent"

    b = await _booking(db_session, booked["id"])
    assert b.card_channel == NotifyChannel(channel)
    assert b.card_chat_id == chat
    assert b.card_message_id == expected


async def test_email_reminder_remembers_nothing(client, db_session, monkeypatch):
    """У почты номера сообщения нет — и писать в карточку нечего."""
    async def smtp(to, subject, body, html=None):
        return True

    monkeypatch.setattr(tasks, "_send_via_smtp", smtp)
    ctx = await _setup(client, db_session, 74)
    user_id = await _client_user(db_session, 74)
    await _link(db_session, user_id, email="c74@example.com",
                notify_channel=NotifyChannel.EMAIL)
    start = _local_today(ctx["tz"]) + timedelta(hours=1, minutes=50)
    booked = await _book(client, ctx, start)

    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0) == "sent"
    assert (await _booking(db_session, booked["id"])).card_message_id is None


# ── Изменения мимо карточки ─────────────────────────────────────────────────

async def test_cancelling_on_the_site_asks_to_redraw_the_card(client, db_session, queue):
    ctx = await _setup(client, db_session, 75)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))

    r = await client.post(f"/api/v1/bookings/{booked['id']}/cancel")
    assert r.status_code == 200, r.text

    refresh = [a for fn, a, _ in queue if fn == "refresh_booking_card"]
    assert refresh == [(booked["id"], booking_card.NOTE_CANCELLED)]


async def test_rescheduling_on_the_site_asks_to_redraw_the_card(client, db_session, queue):
    ctx = await _setup(client, db_session, 76)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))

    r = await client.post(f"/api/v1/bookings/{booked['id']}/reschedule",
                          json={"start_time": _at(ctx["today"] + timedelta(days=1),
                                                  15).isoformat()})
    assert r.status_code == 200, r.text
    refresh = [a for fn, a, _ in queue if fn == "refresh_booking_card"]
    assert refresh == [(booked["id"], booking_card.NOTE_RESCHEDULED)]


async def test_tap_in_the_bot_does_not_ask_the_worker_for_a_second_redraw(
        client, db_session, queue):
    """Бот правит карточку сам, на месте: вторая правка из очереди её бы
    только трясла."""
    ctx = await _setup(client, db_session, 77)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, 77)
    await _link(db_session, user_id, tg_chat_id=9077)

    await tg_bot.on_cancel_booking(FakeTgCallback(f"cnl:{booked['id']}", 9077))
    assert [fn for fn, _, _ in queue if fn == "refresh_booking_card"] == []


@pytest.mark.parametrize("channel", ["tg", "vk", "max"])
async def test_worker_redraws_the_stored_card(channel, client, db_session, monkeypatch):
    n = {"tg": 78, "vk": 79, "max": 80}[channel]
    ctx = await _setup(client, db_session, n)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booked["id"]).values(
            card_channel=NotifyChannel(channel), card_chat_id=4321,
            card_message_id="55", status=BookingStatus.CANCELLED))
        await db.commit()

    edits = []

    async def tg(chat_id, message_id, text, reply_markup=None):
        edits.append((chat_id, message_id, text, reply_markup))
        return True

    async def mx(message_id, text, attachments=None):
        edits.append((None, message_id, text, attachments))
        return True

    async def vk(peer_id, message_id, text, keyboard=None, *, community):
        edits.append((peer_id, message_id, text, keyboard))
        return True

    monkeypatch.setattr(tasks, "_edit_via_telegram", tg)
    monkeypatch.setattr(tasks, "_edit_via_max", mx)
    monkeypatch.setattr(tasks, "_edit_via_vk", vk)

    assert await tasks.refresh_booking_card(
        {"job_try": 1}, booked["id"], booking_card.NOTE_CANCELLED) == "updated"
    [(_, message_id, text, markup)] = edits
    assert message_id == "55"
    assert booking_card.NOTE_CANCELLED in text
    assert markup is None            # у отменённой записи кнопок нет


async def test_worker_skips_a_booking_without_a_card(client, db_session):
    ctx = await _setup(client, db_session, 81)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    assert await tasks.refresh_booking_card({"job_try": 1}, booked["id"]) == "skipped:no-card"


# ── Удалённое сообщение не роняет ни отмену, ни перенос ─────────────────────

async def test_deleted_message_does_not_break_cancelling_from_the_bot(
        client, db_session, queue):
    ctx = await _setup(client, db_session, 82)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, 82)
    await _link(db_session, user_id, tg_chat_id=9082)

    cb = FakeTgCallback(f"cnl:{booked['id']}", 9082,
                        fail_edit=RuntimeError("message to edit not found"))
    await tg_bot.on_cancel_booking(cb)

    # Отмена состоялась, а ответ человеку ушёл обычным сообщением
    assert (await _booking(db_session, booked["id"])).status == BookingStatus.CANCELLED
    assert len(cb.message.answers) == 1
    assert booking_card.NOTE_CANCELLED in cb.message.answers[0][0]


async def test_too_old_vk_message_does_not_break_rescheduling(
        client, db_session, queue, vk_calls, monkeypatch):
    """ВК отказывает в правке слишком старого сообщения (ошибка 909) —
    перенос всё равно состоялся, а ответ пришёл отдельным сообщением."""
    from app.services import vk_api

    async def too_old(*a, **kw):
        raise vk_api.VkApiError(vk_api.EDIT_TOO_OLD, "too old")

    monkeypatch.setattr(vk_api, "edit_message", too_old)

    ctx = await _setup(client, db_session, 83)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, 83)
    await _link(db_session, user_id, vk_client_peer_id=9083)
    async with db_session() as db:
        from app.services.bot_actions import reschedule_options
        _, buttons = await reschedule_options(db, user_id, booked["id"])
    chosen = buttons[0].command.split(":", 2)[2]

    await vk_bot.reschedule_from_bot(9083, booked["id"], chosen, 999)

    assert (await _booking(db_session, booked["id"])).rescheduled_count == 1
    assert len(vk_calls["sent"]) == 1
    assert booking_card.NOTE_RESCHEDULED in vk_calls["sent"][0]["text"]


async def test_refused_edit_does_not_break_the_worker(client, db_session, monkeypatch):
    ctx = await _setup(client, db_session, 84)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booked["id"]).values(
            card_channel=NotifyChannel.TG, card_chat_id=4321, card_message_id="55"))
        await db.commit()

    async def refuse(chat_id, message_id, text, reply_markup=None):
        return False

    monkeypatch.setattr(tasks, "_edit_via_telegram", refuse)
    assert await tasks.refresh_booking_card({"job_try": 1}, booked["id"]) == "skipped:refused"


async def test_broken_queue_does_not_break_cancelling_on_the_site(
        client, db_session, monkeypatch):
    """Обновление карточки — побочное действие: недоступная очередь не имеет
    права отменить отмену."""
    import app.core.worker as worker_mod

    async def boom():
        raise RuntimeError("redis недоступен")

    monkeypatch.setattr(worker_mod, "get_arq_pool", boom)
    monkeypatch.setattr(notif, "get_arq_pool", boom)

    ctx = await _setup(client, db_session, 85)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    r = await client.post(f"/api/v1/bookings/{booked['id']}/cancel")
    assert r.status_code == 200, r.text
    assert (await _booking(db_session, booked["id"])).status == BookingStatus.CANCELLED


# ── Миграция ────────────────────────────────────────────────────────────────

def test_migration_downgrade_and_upgrade():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(pathlib.Path(__file__).resolve().parents[1] / "alembic.ini"))
    columns_sql = ("select column_name from information_schema.columns "
                   "where table_name='bookings'")

    async def columns() -> set[str]:
        conn = await asyncpg.connect(_pg_dsn(settings.POSTGRES_DB))
        rows = await conn.fetch(columns_sql)
        await conn.close()
        return {r["column_name"] for r in rows}

    card = {"card_channel", "card_chat_id", "card_message_id"}
    try:
        alembic_command.downgrade(cfg, "b1c4e7f20a33")
        assert not (card & asyncio.run(columns()))
    finally:
        alembic_command.upgrade(cfg, "head")
    assert card <= asyncio.run(columns())


# Все тесты выше подменяют сами функции отправки, поэтому разбор настоящего
# ответа мессенджера ими не проверяется вовсе: номер сообщения там приходит
# готовым. А это единственное новое место, где мы читаем чужой формат, и
# ошибка в нём тихая — карточка просто никогда не обновится извне.


async def test_telegram_sender_returns_the_message_number(monkeypatch):
    """Номер карточки берётся из настоящего ответа Bot API, а не из воздуха."""
    import httpx

    monkeypatch.setattr(settings, "TG_BOT_TOKEN", "123:ABC")
    real_init = httpx.AsyncClient.__init__

    def mocked(self, *a, **kw):
        kw.pop("proxy", None)
        kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(
            200, json={"ok": True, "result": {"message_id": 4242, "chat": {"id": 1}}}))
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", mocked)
    assert await tasks._send_via_telegram(1, "привет") == 4242
    monkeypatch.undo()


async def test_vk_sender_returns_the_message_number(monkeypatch):
    """У ВК номер приходит прямо числом в ответе messages.send.

    Ключ сообщества подменяем: без него отправка выходит в dev-заглушку и
    настоящий разбор ответа не выполняется вовсе.
    """
    from app.services import vk_api, vk_community
    from app.services.vk_community import Audience

    async def fake_send(peer_id, text, keyboard=None, *, token):
        assert token == "ключ-клиентского"
        return 777

    real_get = vk_community.get
    monkeypatch.setattr(
        vk_community, "get",
        lambda c: type("T", (), {"token": "ключ-клиентского", "audience": real_get(c).audience})(),
    )
    monkeypatch.setattr(vk_api, "send_message", fake_send)
    assert await tasks._send_via_vk(5, "привет", community=Audience.CLIENT) == 777
