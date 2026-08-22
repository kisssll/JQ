"""Канал доставки уведомлений (TG / MAX / почта).

До этой фичи доставка была прибита к Telegram: подтвердившийся через MAX не
получал уведомлений вообще (его chat_id нигде не сохранялся), а пользователи
с одной лишь почтой молча выпадали из выборок «кому уведомить».
"""
import types

import pytest

from app.models.models import NotifyChannel, User, UserRole
from app.core.security import get_password_hash
from app.services import notifications
from app.services.notify_channel import has_channel, resolve


def _user(**kw) -> User:
    """Пользователь в памяти (в БД не пишем — резолв канала её не трогает)."""
    base = dict(
        id=1, phone="+79990000000", full_name="Т", hashed_password="x",
        role=UserRole.CLIENT, tg_chat_id=None, max_chat_id=None, email=None,
        notify_channel=NotifyChannel.NONE,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


# ── Резолв канала ────────────────────────────────────────────────────────────

def test_resolve_uses_preferred_channel():
    u = _user(notify_channel=NotifyChannel.MAX, max_chat_id=555, tg_chat_id=111)
    assert resolve(u) == (NotifyChannel.MAX, 555)


def test_resolve_degrades_when_preferred_address_lost():
    # Канал MAX выбран, но привязку сняли — уходим на живой Telegram
    u = _user(notify_channel=NotifyChannel.MAX, max_chat_id=None, tg_chat_id=111)
    assert resolve(u) == (NotifyChannel.TG, 111)


def test_resolve_falls_back_to_email():
    u = _user(notify_channel=NotifyChannel.NONE, email="a@b.ru")
    assert resolve(u) == (NotifyChannel.EMAIL, "a@b.ru")


def test_resolve_none_when_nowhere_to_send():
    assert resolve(_user()) == (NotifyChannel.NONE, None)
    assert resolve(None) == (NotifyChannel.NONE, None)


def test_has_channel():
    assert has_channel(_user(tg_chat_id=1)) is True
    assert has_channel(_user(max_chat_id=1)) is True
    assert has_channel(_user(email="a@b.ru")) is True
    assert has_channel(_user()) is False


# ── Доставка ставит задачу нужного канала ────────────────────────────────────

class _FakePool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))


@pytest.fixture()
def fake_pool(monkeypatch):
    pool = _FakePool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(notifications, "get_arq_pool", _get_pool)
    return pool


async def test_deliver_routes_to_max(fake_pool):
    ok = await notifications.deliver(_user(notify_channel=NotifyChannel.MAX, max_chat_id=777), "привет")
    assert ok is True
    assert fake_pool.jobs == [("send_max_message", (777, "привет"))]


async def test_deliver_routes_to_telegram(fake_pool):
    ok = await notifications.deliver(_user(notify_channel=NotifyChannel.TG, tg_chat_id=42), "привет")
    assert ok is True
    assert fake_pool.jobs == [("send_tg_message", (42, "привет"))]


async def test_deliver_routes_to_email_with_subject(fake_pool):
    ok = await notifications.deliver(
        _user(notify_channel=NotifyChannel.EMAIL, email="a@b.ru"), "текст", subject="Тема",
    )
    assert ok is True
    assert fake_pool.jobs == [("send_email", ("a@b.ru", "Тема", "текст"))]


async def test_deliver_without_channel_is_noop(fake_pool):
    # Нет канала — уведомление не уходит, но и ошибки нет: вызывающее
    # бизнес-действие не должно падать из-за недоставки.
    assert await notifications.deliver(_user(), "привет") is False
    assert fake_pool.jobs == []


# ── Привязка канала при подтверждении телефона ───────────────────────────────

async def _mk_user(db_session, phone):
    async with db_session() as db:
        u = User(phone=phone, full_name="Т", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.CLIENT)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def test_bind_sets_max_channel(db_session, monkeypatch):
    from app.services import notify_channel as nc
    from app.services import otp

    uid = await _mk_user(db_session, "+79995551101")

    async def no_tg(phone):
        return None

    async def yes_max(phone):
        return 987654321

    monkeypatch.setattr(otp, "pop_tg_chat_id", no_tg)
    monkeypatch.setattr(otp, "pop_max_chat_id", yes_max)

    async with db_session() as db:
        user = await db.get(User, uid)
        await nc.bind_after_verification(db, user, "+79995551101")
        await db.refresh(user)
        assert user.max_chat_id == 987654321
        assert user.notify_channel == NotifyChannel.MAX


async def test_bind_prefers_telegram(db_session, monkeypatch):
    from app.services import notify_channel as nc
    from app.services import otp

    uid = await _mk_user(db_session, "+79995551102")

    async def yes_tg(phone):
        return 123

    async def yes_max(phone):
        return 456

    monkeypatch.setattr(otp, "pop_tg_chat_id", yes_tg)
    monkeypatch.setattr(otp, "pop_max_chat_id", yes_max)

    async with db_session() as db:
        user = await db.get(User, uid)
        await nc.bind_after_verification(db, user, "+79995551102")
        await db.refresh(user)
        assert user.tg_chat_id == 123
        assert user.notify_channel == NotifyChannel.TG


# ── Смена канала в профиле ───────────────────────────────────────────────────

async def test_cannot_switch_to_unconnected_channel(client, db_session):
    from tests.conftest import register_user

    data = await register_user(client, "+79995551103")
    client.cookies.set("access_token", data["access_token"])

    r = await client.post("/api/v1/users/me/notify-channel", data={"channel": "max"},
                          follow_redirects=False)
    assert r.status_code == 302
    assert "notify_channel_unavailable" in r.headers["location"]
