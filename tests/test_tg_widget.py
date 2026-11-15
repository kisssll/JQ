"""Карточка записи виджетом Telegram (решение 0021, сессия 2).

Главное, что здесь стережётся:

- без флага TG_WIDGET_CHAT_IDS всё как до виджета: sendMessage и
  editMessageText (этот тест защищает прод);
- с флагом уходит sendWidget, а правка — тремя методами, не через
  editMessageText: HTML отправленного виджета заменить нельзя;
- шаблон и chat_data укладываются в лимиты Bot API, иначе виджет однажды
  упрётся в 400 уже на живом человеке.

Транспорт подменяем настоящий (httpx.MockTransport), а не функции отправки:
разбор ответа и имя метода в URL — как раз то, что тут проверяется.
"""
import json
import shutil
import subprocess
import zlib
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import update

import app.tasks as tasks
from app import max_bot, tg_bot, vk_bot
import app.core.config as config_mod
from app.models.models import Booking, BookingStatus, NotifyChannel, User
from app.services import booking_card, tg_widget
from tests.test_booking_card import (  # noqa: F401  (queue — фикстура)
    FakeTgCallback, FakeTgMessage, FakeMaxEvent, _booking, _client_user, _link,
    _max_labels, _tg_labels, _vk_labels, queue, vk_calls,
)
from tests.test_booking_reschedule import _at, _book, _local_today, _setup

CHAT = 9500


# settings берём через модуль в момент вызова: часть тестов набора
# перезагружает app.core.config, и объект, импортированный при сборе, к
# полному прогону уже не тот, что видит воркер (в одиночном запуске не видно).
@pytest.fixture()
def bot_api(monkeypatch):
    """Bot API через MockTransport. install() зовём ПОСЛЕ подготовки стенда:
    подмена конструктора httpx.AsyncClient зацепила бы и тестовый клиент."""
    monkeypatch.setattr(config_mod.settings, "TG_BOT_TOKEN", "123:ABC")
    calls: list[tuple[str, dict]] = []
    refuse: dict[str, tuple[int, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append((method, json.loads(request.content)))
        if method in refuse:
            code, description = refuse[method]
            return httpx.Response(code, json={"ok": False, "description": description})
        return httpx.Response(200, json={"ok": True, "result": {
            "message_id": 4711, "chat": {"id": CHAT}}})

    real_init = httpx.AsyncClient.__init__

    def install():
        def mocked(self, *a, **kw):
            kw.pop("proxy", None)
            kw["transport"] = httpx.MockTransport(handler)
            real_init(self, *a, **kw)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", mocked)

    calls_api = type("Api", (), {})()
    calls_api.calls, calls_api.refuse, calls_api.install = calls, refuse, install
    calls_api.methods = lambda: [m for m, _ in calls]
    return calls_api


async def _reminder_stand(client, db_session, n: int):
    ctx = await _setup(client, db_session, n)
    user_id = await _client_user(db_session, n)
    await _link(db_session, user_id, tg_chat_id=CHAT, notify_channel=NotifyChannel.TG)
    start = _local_today(ctx["tz"]) + timedelta(hours=1, minutes=50)
    booked = await _book(client, ctx, start)
    return ctx, user_id, booked


# ── Лимиты Bot API ──────────────────────────────────────────────────────────

def test_template_fits_botapi_limits(capsys):
    """Главный тест: ≤32768 байт и ≤4096 после zlib уровня 9."""
    raw = tg_widget.WIDGET_HTML.encode("utf-8")
    packed = len(zlib.compress(raw, 9))
    print(f"шаблон: {len(raw)} байт, после zlib-9: {packed} байт")
    assert 1 <= len(raw) <= 32768
    assert packed <= 4096


def test_template_has_no_booking_data_and_no_queries():
    """Данные записи в разметку не подставляются, а сеть виджету не нужна."""
    html = tg_widget.WIDGET_HTML
    assert "innerHTML" not in html and "insertAdjacentHTML" not in html
    assert "document.write" not in html
    assert "allow_queries" not in html and "fetch(" not in html


LONG = "Ж" * 300


def test_chat_data_stays_within_1024_bytes_on_long_names():
    out = tg_widget.build_chat_data(
        tg_widget.SCREEN_SLOTS, date="15.11", time="13:00", service=LONG, master=LONG,
        price="от " + "9" * 200 + " ₽", slots=[LONG] * 20, start_epoch=1_900_000_000)
    assert len(out.encode("utf-8")) <= 1024
    data = json.loads(out)                    # усечение не ломает разбор
    assert data["s"] == "slots" and data["t"] == "13:00"
    assert 0 < len(data["sv"]) <= 40 and len(data.get("sl", [])) <= 6


def test_chat_data_drops_slots_before_dropping_the_card():
    """Четырёхбайтные символы в окнах: режем окна с хвоста, скелет остаётся."""
    out = tg_widget.build_chat_data(
        tg_widget.SCREEN_SLOTS, date="15.11", time="13:00", service="Стрижка",
        slots=["😀" * 16] * 6)
    assert len(out.encode("utf-8")) <= 1024
    data = json.loads(out)
    assert data["sv"] == "Стрижка"


def test_chat_data_with_control_characters_still_fits():
    """Управляющий символ в JSON занимает шесть байт (\\u0001): худший ввод
    салона. Окна режутся с хвоста, остальное остаётся."""
    out = tg_widget.build_chat_data(
        tg_widget.SCREEN_SLOTS, date="15.11", time="13:00", service="\x01" * 40,
        master="\x01" * 28, price="\x01" * 22, slots=["\x01" * 16] * 6)
    assert len(out.encode("utf-8")) <= 1024
    data = json.loads(out)
    assert 0 < len(data["sl"]) < 6 and data["sv"]      # окна урезаны, карточка цела


def test_chat_data_falls_back_to_a_skeleton(monkeypatch):
    """Если усечения полей когда-нибудь ослабят, граница Bot API всё равно
    держится: лучше карточка без услуги, чем 400 и карточка, которая застыла."""
    monkeypatch.setitem(tg_widget._FIELD_LIMITS, "sv", 5000)
    out = tg_widget.build_chat_data(
        tg_widget.SCREEN_CARD, date="15.11", time="13:00", service="Ж" * 5000)
    assert len(out.encode("utf-8")) <= 1024
    assert json.loads(out) == {"s": "card", "d": "15.11", "t": "13:00"}


def test_caption_is_cut_to_1024_characters():
    assert len(tg_widget.fit_caption("я" * 5000)) == 1024
    assert tg_widget.fit_caption("коротко") == "коротко"


def test_flag_parser_survives_garbage(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", " 12, ,abc,-5 ,7x,34")
    assert config_mod.settings.tg_widget_chat_ids == {12, -5, 34}
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "")
    assert config_mod.settings.tg_widget_chat_ids == set()
    assert not tg_widget.enabled_for(12)
    assert not tg_widget.enabled_for(None)


# ── JS: чистая функция разбора chat_data ────────────────────────────────────

def _run_view(cases: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node не установлен — JS-разбор проверяется только с ним")
    html = tg_widget.WIDGET_HTML
    start = html.index("var SCREENS")
    end = html.index("function draw")
    script = html[start:end] + (
        "\nconst cases = JSON.parse(process.argv[1]);"
        "\nconsole.log(JSON.stringify(cases.map(c => viewOf(c.raw, c.now))));")
    out = subprocess.run([node, "-e", script, json.dumps(cases)],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_widget_js_maps_chat_data_to_screens():
    now = 1_900_000_000 * 1000
    base = {"d": "15.11", "t": "13:00", "sv": "Стрижка", "m": "Анна", "p": "1 500 ₽"}

    def raw(**kw):
        return json.dumps({**base, **kw}, ensure_ascii=False)

    views = _run_view([
        {"raw": raw(s="card"), "now": now},
        {"raw": raw(s="ok"), "now": now},
        {"raw": raw(s="moved"), "now": now},
        {"raw": raw(s="off"), "now": now},
        {"raw": raw(s="past"), "now": now},
        {"raw": raw(s="slots", sl=["Сегодня 14:00", "Завтра 10:00"]), "now": now},
        {"raw": raw(s="busy", sl=["Завтра 10:00"]), "now": now},
        {"raw": raw(s="slots"), "now": now},
        {"raw": raw(s="ok", e=1_900_000_000 - 100), "now": now},        # визит ещё идёт
        {"raw": raw(s="ok", e=1_900_000_000 - 3 * 3600), "now": now},   # гаснет по часам
        {"raw": raw(s="off", e=1_900_000_000 - 3 * 3600), "now": now},  # отмена остаётся отменой
        {"raw": "это не json", "now": now},
        {"raw": None, "now": now},
        {"raw": "[1,2]", "now": now},
    ])
    card, ok, moved, off, past, slots, busy, nowin, running, gone, off_old, junk, null, arr = views
    assert card["badge"] == "Ждём подтверждения" and card["time"] == "13:00"
    assert card["who"] == "Анна · 1 500 ₽" and card["tone"] == "card"
    assert ok["badge"] == "Подтверждено" and moved["badge"] == "Перенесено"
    assert off["tone"] == "off" and past["tone"] == "past"
    assert slots["tone"] == "slots" and slots["slots"] == ["Сегодня 14:00", "Завтра 10:00"]
    assert "заняли" in busy["title"]
    assert "нет" in nowin["title"] and nowin["slots"] == []
    assert running["tone"] == "ok" and gone["tone"] == "past"
    assert off_old["tone"] == "off"
    for v in (junk, null, arr):               # мусор не роняет экран
        assert v["tone"] == "card" and v["time"] == ""


# ── Флаг выключен: прежнее поведение (защита прода) ─────────────────────────

async def test_flag_off_reminder_is_a_plain_message(client, db_session, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "")
    _, _, booked = await _reminder_stand(client, db_session, 120)
    bot_api.install()

    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0) == "sent"

    [(method, body)] = bot_api.calls
    assert method == "sendMessage"
    assert set(body) == {"chat_id", "text", "reply_markup"}
    assert body["text"].startswith("Сегодня в ") or body["text"].startswith("Завтра в ")
    assert [b["text"] for row in body["reply_markup"]["inline_keyboard"] for b in row] == [
        "Буду", "Перенести", "Не смогу"]


async def test_flag_for_another_chat_leaves_this_chat_alone(
        client, db_session, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "1,2,3")
    _, _, booked = await _reminder_stand(client, db_session, 121)
    bot_api.install()
    await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0)
    assert bot_api.methods() == ["sendMessage"]


async def test_flag_off_worker_edits_the_card_as_text(client, db_session, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "")
    ctx, user_id, booked = await _reminder_stand(client, db_session, 122)
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booked["id"]).values(
            card_channel=NotifyChannel.TG, card_chat_id=CHAT, card_message_id="55"))
        await db.commit()
    bot_api.install()

    assert await tasks.refresh_booking_card({"job_try": 1}, booked["id"]) == "updated"
    assert bot_api.methods() == ["editMessageText"]


async def test_flag_off_tap_edits_the_message_as_text(client, db_session, queue, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "")
    ctx = await _setup(client, db_session, 123)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    await _link(db_session, await _client_user(db_session, 123), tg_chat_id=9123)
    cb = FakeTgCallback(f"cfm:{booked['id']}", 9123)
    await tg_bot.on_confirm_booking(cb)
    assert len(cb.message.edits) == 1 and cb.message.answers == []


# ── Флаг включён ────────────────────────────────────────────────────────────

async def test_flag_on_reminder_goes_as_widget(client, db_session, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", str(CHAT))
    _, _, booked = await _reminder_stand(client, db_session, 124)
    bot_api.install()

    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0) == "sent"

    [(method, body)] = bot_api.calls
    assert method == "sendWidget"
    assert body["html"] == tg_widget.WIDGET_HTML          # статический шаблон
    assert "allow_queries" not in body
    assert body["caption"].startswith(("Сегодня в ", "Завтра в "))
    assert "Подтвердите пожалуйста" in body["caption"]    # подпись — текст напоминания
    assert [b["text"] for row in body["reply_markup"]["inline_keyboard"] for b in row] == [
        "Буду", "Перенести", "Не смогу"]
    data = json.loads(body["chat_data"])
    assert data["s"] == "card" and data["sv"] == "Стрижка"
    assert len(body["chat_data"].encode("utf-8")) <= 1024
    # название салона в разметку не попало
    assert "ПереносZZ124" not in body["html"]
    # номер сообщения взят из настоящего ответа Bot API и запомнен
    assert (await _booking(db_session, booked["id"])).card_message_id == "4711"


async def test_widget_refused_falls_back_to_a_plain_reminder(
        client, db_session, bot_api, monkeypatch):
    """Постоянный отказ на виджет не должен стоить человеку напоминания."""
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", str(CHAT))
    _, _, booked = await _reminder_stand(client, db_session, 125)
    bot_api.refuse["sendWidget"] = (400, "Bad Request: unsupported")
    bot_api.install()

    assert await tasks.send_booking_reminder({"job_try": 1}, booked["id"], 0) == "sent"
    assert bot_api.methods() == ["sendWidget", "sendMessage"]


async def test_flag_on_worker_redraws_with_three_widget_methods(
        client, db_session, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", str(CHAT))
    ctx, user_id, booked = await _reminder_stand(client, db_session, 126)
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booked["id"]).values(
            card_channel=NotifyChannel.TG, card_chat_id=CHAT, card_message_id="55",
            status=BookingStatus.CANCELLED))
        await db.commit()
    bot_api.install()

    assert await tasks.refresh_booking_card(
        {"job_try": 1}, booked["id"], booking_card.NOTE_CANCELLED) == "updated"

    assert bot_api.methods() == ["editMessageWidgetData", "editMessageCaption",
                                 "editMessageReplyMarkup"]
    data, caption, markup = (b for _, b in bot_api.calls)
    assert data["message_id"] == 55 and json.loads(data["chat_data"])["s"] == "off"
    assert booking_card.NOTE_CANCELLED in caption["caption"]
    assert markup["reply_markup"] == {"inline_keyboard": []}   # у отменённой кнопок нет


async def test_widget_edit_refusal_does_not_break_the_worker(
        client, db_session, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", str(CHAT))
    ctx, user_id, booked = await _reminder_stand(client, db_session, 127)
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booked["id"]).values(
            card_channel=NotifyChannel.TG, card_chat_id=CHAT, card_message_id="55"))
        await db.commit()
    bot_api.refuse["editMessageWidgetData"] = (400, "Bad Request: message can't be edited")
    bot_api.install()

    assert await tasks.refresh_booking_card({"job_try": 1}, booked["id"]) == "skipped:refused"
    assert bot_api.methods() == ["editMessageWidgetData"]       # дальше не идём


async def test_not_modified_counts_as_success(client, db_session, bot_api, monkeypatch):
    """Двойной тап даёт ту же карточку — это не отказ."""
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", str(CHAT))
    bot_api.refuse["editMessageCaption"] = (400, "Bad Request: message is not modified")
    bot_api.install()
    assert await tasks._edit_widget_via_telegram(CHAT, "5", "текст", "{}") is True
    assert bot_api.methods() == ["editMessageWidgetData", "editMessageCaption",
                                 "editMessageReplyMarkup"]


async def test_flag_on_tap_redraws_via_widget_methods(
        client, db_session, queue, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "9124")
    ctx = await _setup(client, db_session, 128)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    await _link(db_session, await _client_user(db_session, 128), tg_chat_id=9124)
    bot_api.install()

    cb = FakeTgCallback(f"rsc:{booked['id']}", 9124)
    await tg_bot.on_reschedule(cb)

    assert cb.message.edits == [] and cb.message.answers == []    # не editMessageText
    assert bot_api.methods() == ["editMessageWidgetData", "editMessageCaption",
                                 "editMessageReplyMarkup"]
    data, caption, markup = (b for _, b in bot_api.calls)
    state = json.loads(data["chat_data"])
    assert state["s"] == "slots" and len(state["sl"]) == 6
    assert "Выберите новое время" in caption["caption"]
    flat = [b for row in markup["reply_markup"]["inline_keyboard"] for b in row]
    assert len(flat) == 7                                         # шесть окон и «Другое время»


async def test_flag_on_busy_slot_shows_the_busy_screen(
        client, db_session, queue, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "9125")
    ctx = await _setup(client, db_session, 129)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    await _link(db_session, await _client_user(db_session, 129), tg_chat_id=9125)
    bot_api.install()

    past = (ctx["today"] - timedelta(days=1)).strftime("%Y-%m-%d") + "T10:00:00"
    cb = FakeTgCallback(f"rsc:{booked['id']}:{past}", 9125)
    await tg_bot.on_reschedule(cb)

    state = json.loads(bot_api.calls[0][1]["chat_data"])
    assert state["s"] == "busy"


async def test_widget_edit_failure_in_tap_answers_with_a_message(
        client, db_session, queue, bot_api, monkeypatch):
    """Флаг выключили, виджеты остались: правка не пройдёт, но ответ человеку будет."""
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "9126")
    ctx = await _setup(client, db_session, 130)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    await _link(db_session, await _client_user(db_session, 130), tg_chat_id=9126)
    bot_api.refuse["editMessageWidgetData"] = (400, "Bad Request: no widget")
    bot_api.install()

    cb = FakeTgCallback(f"cfm:{booked['id']}", 9126)
    await tg_bot.on_confirm_booking(cb)
    assert len(cb.message.answers) == 1


async def test_flag_on_bookings_list_sends_widgets(client, db_session, bot_api, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "9127")
    ctx = await _setup(client, db_session, 131)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    await _link(db_session, await _client_user(db_session, 131), tg_chat_id=9127)
    bot_api.install()

    msg = FakeTgMessage(9127)
    await tg_bot.on_my_bookings(msg)

    assert msg.answers == []
    [(method, body)] = bot_api.calls
    assert method == "sendWidget" and body["chat_id"] == 9127
    assert "Стрижка" in body["caption"]
    assert (await _booking(db_session, booked["id"])).card_message_id == "4711"


# ── /bookings: у подтверждённой записи кнопок нет — во всех трёх ботах ───────

async def _confirmed_stand(client, db_session, n: int):
    ctx = await _setup(client, db_session, n)
    booked = await _book(client, ctx, _at(ctx["today"] + timedelta(days=1), 10))
    user_id = await _client_user(db_session, n)
    return ctx, booked, user_id


async def _confirm(db_session, booking_id: int):
    from datetime import datetime, timezone
    async with db_session() as db:
        await db.execute(update(Booking).where(Booking.id == booking_id).values(
            client_confirmed_at=datetime.now(timezone.utc)))
        await db.commit()


async def test_tg_bookings_list_hides_buttons_once_confirmed(client, db_session, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "TG_WIDGET_CHAT_IDS", "")
    ctx, booked, user_id = await _confirmed_stand(client, db_session, 132)
    await _link(db_session, user_id, tg_chat_id=9132)

    msg = FakeTgMessage(9132)
    await tg_bot.on_my_bookings(msg)
    assert len(_tg_labels(msg.answers[0][1])) == 3          # до подтверждения — три

    await _confirm(db_session, booked["id"])
    msg = FakeTgMessage(9132)
    await tg_bot.on_my_bookings(msg)
    assert _tg_labels(msg.answers[0][1]) == []


async def test_vk_bookings_list_hides_buttons_once_confirmed(
        client, db_session, vk_calls):
    ctx, booked, user_id = await _confirmed_stand(client, db_session, 133)
    await _link(db_session, user_id, vk_client_peer_id=9133)

    await vk_bot.show_bookings(9133)
    assert len(_vk_labels(vk_calls["sent"][-1]["kb"])) == 3

    await _confirm(db_session, booked["id"])
    await vk_bot.show_bookings(9133)
    assert _vk_labels(vk_calls["sent"][-1]["kb"]) == []


async def test_max_bookings_list_hides_buttons_once_confirmed(client, db_session):
    ctx, booked, user_id = await _confirmed_stand(client, db_session, 134)
    await _link(db_session, user_id, max_chat_id=9134)
    sent: list = []

    class Bot:
        async def send_message(self, chat_id, text, attachments=None):
            sent.append(attachments)
            return type("S", (), {"message": type("M", (), {
                "body": type("B", (), {"mid": "m1"})()})()})()

    await max_bot._show_bookings(Bot(), 9134)
    assert len(_max_labels(sent[-1])) == 3

    await _confirm(db_session, booked["id"])
    await max_bot._show_bookings(Bot(), 9134)
    assert _max_labels(sent[-1]) == []
