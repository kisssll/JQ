"""Каналы связи и ручное управление подпиской из админки.

Закрывает три замечания: в админке не было видно оплаченный тариф и не было
кнопки продления; вошедшие через VK/Яндекс оставались вообще без канала связи
(почту провайдер отдавал, но мы её не сохраняли); телефон можно было
подтвердить только Telegram.
"""
from datetime import datetime, timedelta, timezone
import types

import pytest

from app.core.security import get_password_hash
from app.models.models import (
    NotifyChannel, Salon, SalonModerationStatus, SalonSubscriptionStatus,
    User, UserRole,
)


# ── OAuth: почта становится каналом связи ────────────────────────────────────

async def _mk_user(db_session, phone, **kw):
    async with db_session() as db:
        u = User(phone=phone, full_name="Т", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.CLIENT, **kw)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def test_oauth_email_becomes_channel(db_session):
    from app.services.notify_channel import adopt_oauth_email

    uid = await _mk_user(db_session, "+79994440001")
    async with db_session() as db:
        user = await db.get(User, uid)
        assert user.notify_channel == NotifyChannel.NONE  # вошёл через VK/Яндекс — связи нет
        await adopt_oauth_email(db, user, "Vasya@Example.RU")
        await db.refresh(user)
        assert user.email == "vasya@example.ru"          # нормализуем регистр
        assert user.notify_channel == NotifyChannel.EMAIL


async def test_oauth_email_not_stolen_from_another_account(db_session):
    from app.services.notify_channel import adopt_oauth_email

    await _mk_user(db_session, "+79994440002", email="taken@example.ru")
    uid = await _mk_user(db_session, "+79994440003")
    async with db_session() as db:
        user = await db.get(User, uid)
        await adopt_oauth_email(db, user, "taken@example.ru")
        await db.refresh(user)
        assert user.email is None                        # чужой адрес не занимаем
        assert user.notify_channel == NotifyChannel.NONE


async def test_oauth_email_does_not_override_messenger(db_session):
    from app.services.notify_channel import adopt_oauth_email

    uid = await _mk_user(db_session, "+79994440004", tg_chat_id=555,
                         notify_channel=NotifyChannel.TG)
    async with db_session() as db:
        user = await db.get(User, uid)
        await adopt_oauth_email(db, user, "new@example.ru")
        await db.refresh(user)
        assert user.email == "new@example.ru"
        assert user.notify_channel == NotifyChannel.TG   # мессенджер приоритетнее


# ── Отвязка мессенджера ──────────────────────────────────────────────────────

async def _login(client, phone, pw="Testpass1"):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": pw})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])


async def test_cannot_disconnect_last_channel(client, db_session):
    uid = await _mk_user(db_session, "+79994440010", tg_chat_id=111,
                         notify_channel=NotifyChannel.TG)
    await _login(client, "+79994440010")

    r = await client.post("/api/v1/users/me/disconnect-channel", data={"channel": "tg"},
                          follow_redirects=False)
    assert r.status_code == 302
    assert "notify_channel_last" in r.headers["location"]
    async with db_session() as db:
        u = await db.get(User, uid)
        assert u.tg_chat_id == 111        # канал на месте


async def test_disconnect_switches_to_remaining_channel(client, db_session):
    uid = await _mk_user(db_session, "+79994440011", tg_chat_id=111, max_chat_id=222,
                         notify_channel=NotifyChannel.TG)
    await _login(client, "+79994440011")

    r = await client.post("/api/v1/users/me/disconnect-channel", data={"channel": "tg"},
                          follow_redirects=False)
    assert r.status_code == 302
    assert "notify_channel_disconnected" in r.headers["location"]
    async with db_session() as db:
        u = await db.get(User, uid)
        assert u.tg_chat_id is None
        assert u.notify_channel == NotifyChannel.MAX   # переехали на оставшийся


# ── Админка: ручное управление подпиской ─────────────────────────────────────

async def _mk_senior_admin(db_session, phone):
    async with db_session() as db:
        u = User(phone=phone, full_name="Админ", hashed_password=get_password_hash("Adminpass1"),
                 role=UserRole.ADMIN, is_senior_admin=True)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _mk_salon(db_session, owner_id, name, **kw):
    async with db_session() as db:
        s = Salon(name=name, address="Т", phone="+70000000900", latitude=1.0, longitude=1.0,
                  is_active=True, creator_id=owner_id,
                  moderation_status=SalonModerationStatus.APPROVED, **kw)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_admin_grants_paid_access(client, db_session):
    await _mk_senior_admin(db_session, "+79994440020")
    owner = await _mk_user(db_session, "+79994440021")
    sid = await _mk_salon(db_session, owner, "ВыдачаДоступаZZ",
                          subscription_status=SalonSubscriptionStatus.NONE)
    await _login(client, "+79994440020", pw="Adminpass1")

    r = await client.post(f"/api/v1/admin/salons/{sid}/grant-access", data={"months": "3"},
                          follow_redirects=False)
    assert r.status_code == 302, r.text
    async with db_session() as db:
        s = await db.get(Salon, sid)
        assert s.subscription_status == SalonSubscriptionStatus.ACTIVE
        # ~90 дней доступа
        assert s.access_until > datetime.now(timezone.utc) + timedelta(days=85)
        assert s.business_tier                       # тариф проставился сам


async def test_admin_revokes_access(client, db_session):
    await _mk_senior_admin(db_session, "+79994440022")
    owner = await _mk_user(db_session, "+79994440023")
    sid = await _mk_salon(db_session, owner, "СнятиеДоступаZZ",
                          subscription_status=SalonSubscriptionStatus.ACTIVE,
                          business_tier="lite",
                          access_until=datetime.now(timezone.utc) + timedelta(days=30))
    await _login(client, "+79994440022", pw="Adminpass1")

    r = await client.post(f"/api/v1/admin/salons/{sid}/revoke-access", follow_redirects=False)
    assert r.status_code == 302, r.text
    async with db_session() as db:
        s = await db.get(Salon, sid)
        assert s.access_until <= datetime.now(timezone.utc)
        assert s.subscription_status == SalonSubscriptionStatus.CANCELED
    # и пропал из каталога
    assert "СнятиеДоступаZZ" not in (await client.get("/salons")).text


async def test_admin_sets_plan(client, db_session):
    await _mk_senior_admin(db_session, "+79994440024")
    owner = await _mk_user(db_session, "+79994440025")
    sid = await _mk_salon(db_session, owner, "СменаТарифаZZ",
                          subscription_status=SalonSubscriptionStatus.ACTIVE,
                          business_tier="lite")
    await _login(client, "+79994440024", pw="Adminpass1")

    r = await client.post(f"/api/v1/admin/salons/{sid}/set-plan", data={"plan": "business"},
                          follow_redirects=False)
    assert r.status_code == 302, r.text
    async with db_session() as db:
        assert (await db.get(Salon, sid)).business_tier == "business"
