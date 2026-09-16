# tests/test_delivery_refusal.py
"""Правило отказа доставки — общее для всех мессенджеров.

Раньше постоянный отказ (бот заблокирован, чат удалён) уходил в журнал, канал
оставался прежним, и человек молча переставал получать напоминания. Теперь:
мессенджер помечается сломанным, привязка сохраняется, ЭТО уведомление сразу
уходит запасным каналом, профиль зовёт переподключить, а «Начать» в боте
возвращает всё назад.
"""
import httpx
import pytest

from app import tasks
from app.core.security import get_password_hash
from app.models.models import NotifyChannel, User, UserRole
from app.services.notify_channel import (
    broken_channels, clear_broken, has_channel_clause, resolve,
)


async def _user(db_session, phone="+79997770001", **kw) -> int:
    async with db_session() as db:
        user = User(phone=phone, full_name="Клиент", role=UserRole.CLIENT,
                    hashed_password=get_password_hash("x"), **kw)
        db.add(user)
        await db.commit()
        return user.id


class _Pool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, *args))


@pytest.fixture()
def pool(monkeypatch):
    fake = _Pool()

    async def _get():
        return fake

    monkeypatch.setattr("app.core.worker.get_arq_pool", _get)
    return fake


def _tg_refuses(monkeypatch):
    async def refuse(chat_id, text, reply_markup=None):
        raise tasks.RecipientGone("Forbidden: bot was blocked by the user")

    monkeypatch.setattr(tasks, "_send_via_telegram", refuse)


# ── выбор канала ────────────────────────────────────────────────────────────

def test_broken_messenger_is_skipped_but_kept():
    from datetime import datetime, timezone

    user = User(phone="+79990000000", tg_chat_id=1, email="a@b.ru",
                notify_channel=NotifyChannel.TG,
                tg_broken_at=datetime.now(timezone.utc))
    assert resolve(user) == (NotifyChannel.EMAIL, "a@b.ru")
    assert broken_channels(user) == [NotifyChannel.TG]
    assert user.tg_chat_id == 1   # привязка на месте


async def test_only_broken_channel_means_unreachable(client, db_session):
    from datetime import datetime, timezone

    from sqlalchemy import select

    broken_id = await _user(db_session, tg_chat_id=11, notify_channel=NotifyChannel.TG,
                            tg_broken_at=datetime.now(timezone.utc))
    ok_id = await _user(db_session, phone="+79997770002", tg_chat_id=12,
                        notify_channel=NotifyChannel.TG)
    async with db_session() as db:
        ids = set((await db.execute(select(User.id).where(has_channel_clause()))).scalars())
    assert ok_id in ids and broken_id not in ids


# ── отказ при отправке ──────────────────────────────────────────────────────

async def test_refusal_marks_broken_and_reroutes_now(client, db_session, monkeypatch, pool):
    _tg_refuses(monkeypatch)
    user_id = await _user(db_session, tg_chat_id=21, email="client@example.com",
                          notify_channel=NotifyChannel.TG)

    result = await tasks.send_tg_message({"job_try": 1}, 21, "⏰ Напоминание")

    assert result == "gone:rerouted:1"
    assert pool.jobs == [("send_email", "client@example.com", "Руми", "⏰ Напоминание")]
    async with db_session() as db:
        user = await db.get(User, user_id)
        assert user.tg_broken_at is not None
        assert user.tg_chat_id == 21
        assert resolve(user)[0] == NotifyChannel.EMAIL


async def test_refusal_reroutes_messenger_to_messenger(client, db_session, monkeypatch, pool):
    _tg_refuses(monkeypatch)
    await _user(db_session, tg_chat_id=22, max_chat_id=922, notify_channel=NotifyChannel.TG)

    await tasks.send_tg_message({"job_try": 1}, 22, "текст")
    assert pool.jobs == [("send_max_message", 922, "текст")]


async def test_refusal_without_fallback_still_marks(client, db_session, monkeypatch, pool):
    _tg_refuses(monkeypatch)
    user_id = await _user(db_session, tg_chat_id=23, notify_channel=NotifyChannel.TG)

    assert await tasks.send_tg_message({"job_try": 1}, 23, "текст") == "gone:rerouted:0"
    assert pool.jobs == []
    async with db_session() as db:
        assert (await db.get(User, user_id)).tg_broken_at is not None


async def test_refusal_from_unlinked_chat(client, db_session, monkeypatch, pool):
    """Ответ поддержки в чат, не привязанный к аккаунту: помечать некого."""
    _tg_refuses(monkeypatch)
    assert await tasks.send_tg_message({"job_try": 1}, 24, "ответ") == "gone:unlinked"
    assert pool.jobs == []


async def test_max_refusal_reroutes(client, db_session, monkeypatch, pool):
    async def refuse(chat_id, text, attachments=None):
        raise tasks.RecipientGone("chat.denied")

    monkeypatch.setattr(tasks, "_send_via_max", refuse)
    user_id = await _user(db_session, max_chat_id=925, email="m@example.com",
                          notify_channel=NotifyChannel.MAX)

    await tasks.send_max_message({"job_try": 1}, 925, "текст")
    assert pool.jobs == [("send_email", "m@example.com", "Руми", "текст")]
    async with db_session() as db:
        assert (await db.get(User, user_id)).max_broken_at is not None


async def test_reminder_is_rerouted_with_its_subject(client, db_session, monkeypatch, pool):
    """Напоминание шлётся напрямую, мимо send_tg_message — правило то же."""
    _tg_refuses(monkeypatch)
    await _user(db_session, tg_chat_id=26, email="r@example.com", notify_channel=NotifyChannel.TG)

    await tasks._deliver(NotifyChannel.TG, 26, "⏰ Сегодня в 18:00", subject="Напоминание о записи — Руми")
    assert pool.jobs == [("send_email", "r@example.com", "Напоминание о записи — Руми", "⏰ Сегодня в 18:00")]


# ── что считается отказом получателя, а что нет ─────────────────────────────

@pytest.fixture()
def tg_answers(monkeypatch):
    import app.core.config as config_mod

    monkeypatch.setattr(config_mod.settings, "TG_BOT_TOKEN", "000:x")

    def answer(status, description):
        async def fake_post(self, url, json=None):
            return httpx.Response(status, request=httpx.Request("POST", url),
                                  json={"ok": False, "description": description})
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    return answer


@pytest.mark.parametrize("status,description", [
    (403, "Forbidden: bot was blocked by the user"),
    (403, "Forbidden: user is deactivated"),
    (400, "Bad Request: chat not found"),
])
async def test_telegram_recipient_gone(tg_answers, status, description):
    tg_answers(status, description)
    with pytest.raises(tasks.RecipientGone):
        await tasks._send_via_telegram(1, "hi")


@pytest.mark.parametrize("status,description", [
    (400, "Bad Request: message is too long"),   # наша ошибка, не человека
    (401, "Unauthorized"),                       # сломан токен — сломались мы
])
async def test_telegram_our_fault_does_not_blame_recipient(tg_answers, status, description):
    tg_answers(status, description)
    assert await tasks._send_via_telegram(1, "hi") is False


@pytest.mark.parametrize("code,expected", [
    (403, tasks.RecipientGone),
    (404, tasks.RecipientGone),
    (503, tasks.TransientTaskError),
    (429, tasks.TransientTaskError),
    (400, False),
])
async def test_max_error_classification(monkeypatch, code, expected):
    import app.core.config as config_mod
    from maxapi import Bot
    from maxapi.exceptions.max import MaxApiError

    monkeypatch.setattr(config_mod.settings, "MAX_BOT_TOKEN", "max-token")

    async def send_message(self, **kw):
        raise MaxApiError(code=code, raw={"code": "x", "message": "y"})

    async def close_session(self):
        return None

    monkeypatch.setattr(Bot, "send_message", send_message)
    monkeypatch.setattr(Bot, "close_session", close_session)

    if expected is False:
        assert await tasks._send_via_max(1, "hi") is False
    else:
        with pytest.raises(expected):
            await tasks._send_via_max(1, "hi")


# ── возврат и видимость ─────────────────────────────────────────────────────

async def test_pressing_start_revives_channel(client, db_session, monkeypatch):
    from datetime import datetime, timezone

    from app import tg_bot

    user_id = await _user(db_session, tg_chat_id=31, email="x@example.com",
                          notify_channel=NotifyChannel.TG,
                          tg_broken_at=datetime.now(timezone.utc))
    await tg_bot._revive_channel(31)
    async with db_session() as db:
        user = await db.get(User, user_id)
        assert user.tg_broken_at is None
        assert resolve(user) == (NotifyChannel.TG, 31)


async def test_max_start_revives_channel(client, db_session):
    from datetime import datetime, timezone

    from app import max_bot

    user_id = await _user(db_session, max_chat_id=32, notify_channel=NotifyChannel.MAX,
                          max_broken_at=datetime.now(timezone.utc))
    await max_bot._revive_channel(32)
    async with db_session() as db:
        assert (await db.get(User, user_id)).max_broken_at is None


async def test_clear_broken_touches_only_that_chat(client, db_session):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    other = await _user(db_session, tg_chat_id=41, tg_broken_at=now)
    await _user(db_session, phone="+79997770009", tg_chat_id=42, tg_broken_at=now)
    async with db_session() as db:
        assert await clear_broken(db, NotifyChannel.TG, 42) == 1
    async with db_session() as db:
        assert (await db.get(User, other)).tg_broken_at is not None


def test_profile_shows_banner_with_reconnect(monkeypatch):
    from datetime import datetime, timezone

    import app.core.config as config_mod
    from app.web.pages.profile import _notify_channel_block

    monkeypatch.setattr(config_mod.settings, "TG_BOT_USERNAME", "rumi_beauty_bot")
    user = User(phone="+79990000000", tg_chat_id=1, email="a@b.ru",
                notify_channel=NotifyChannel.TG,
                tg_broken_at=datetime.now(timezone.utc))
    html = _notify_channel_block(user)
    assert "Telegram не принимает наши сообщения" in html
    assert "https://t.me/rumi_beauty_bot" in html
    assert "не доставляется" in html
    assert "Пока уведомления приходят: <strong>почта</strong>" in html


def test_profile_has_no_banner_when_delivery_works():
    from app.web.pages.profile import _notify_channel_block

    user = User(phone="+79990000000", tg_chat_id=1, notify_channel=NotifyChannel.TG)
    assert "не принимает наши сообщения" not in _notify_channel_block(user)
