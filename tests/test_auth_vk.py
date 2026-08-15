# tests/test_auth_vk.py
"""Вход через VK ID (OAuth 2.1 + PKCE): state-CSRF + code_challenge, device_id,
связка по проверенному номеру."""
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import select

import app.api.v1.endpoints.auth_vk as vk
import app.services.otp as otp_mod
from app.models.models import User
from tests.conftest import register_user

settings = otp_mod.settings  # тот же общий инстанс, что у приложения

PHONE = "+79996667788"


def _vk_on(monkeypatch):
    monkeypatch.setattr(settings, "VK_OAUTH_ENABLED", True)
    monkeypatch.setattr(settings, "VK_CLIENT_ID", "test-app-id")


def _mock_vk(monkeypatch, profile: dict | None, token_ok: bool = True):
    async def fake_exchange(code, code_verifier, device_id, redirect_uri):
        return "fake-token" if token_ok else None

    async def fake_profile(access_token):
        return profile

    monkeypatch.setattr(vk, "_exchange_code", fake_exchange)
    monkeypatch.setattr(vk, "_fetch_profile", fake_profile)


async def _start_and_get_state(client: httpx.AsyncClient) -> str:
    r = await client.get("/api/v1/auth/vk/start")
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://id.vk.ru/authorize")
    q = parse_qs(urlparse(location).query)
    # PKCE: challenge обязателен, метод S256
    assert q["code_challenge"][0] and q["code_challenge_method"][0] == "S256"
    return q["state"][0]


async def test_disabled_redirects_to_login(client):
    r = await client.get("/api/v1/auth/vk/start")
    assert r.status_code == 302 and r.headers["location"] == "/login"


async def test_callback_rejects_unknown_state(client, monkeypatch):
    _vk_on(monkeypatch)
    _mock_vk(monkeypatch, {"phone": PHONE})
    r = await client.get(
        "/api/v1/auth/vk/callback",
        params={"code": "c", "state": "чужой", "device_id": "d1"},
    )
    assert r.status_code == 302 and "error=vk" in r.headers["location"]


async def test_callback_requires_device_id(client, monkeypatch):
    _vk_on(monkeypatch)
    _mock_vk(monkeypatch, {"phone": PHONE})
    state = await _start_and_get_state(client)
    r = await client.get(
        "/api/v1/auth/vk/callback", params={"code": "c", "state": state}
    )  # без device_id
    assert "error=vk" in r.headers["location"]


async def test_new_user_created_from_verified_phone(client, db_session, monkeypatch):
    _vk_on(monkeypatch)
    _mock_vk(monkeypatch, {
        "user_id": "42", "phone": "79996667788",
        "first_name": "Иван", "last_name": "Петров",
    })
    state = await _start_and_get_state(client)
    r = await client.get(
        "/api/v1/auth/vk/callback",
        params={"code": "c", "state": state, "device_id": "d1"},
    )
    assert r.status_code == 302 and r.headers["location"] == "/profile"
    assert "access_token" in r.cookies or "access_token" in r.headers.get("set-cookie", "")

    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
        assert user.full_name == "Иван Петров"
        assert user.role.value == "client"

    # state одноразовый: повтор с тем же state — отказ
    r = await client.get(
        "/api/v1/auth/vk/callback",
        params={"code": "c", "state": state, "device_id": "d1"},
    )
    assert "error=vk" in r.headers["location"]


async def test_existing_user_logged_in_by_phone(client, db_session, monkeypatch):
    _vk_on(monkeypatch)
    data = await register_user(client, PHONE)
    _mock_vk(monkeypatch, {"phone": "79996667788"})
    state = await _start_and_get_state(client)
    r = await client.get(
        "/api/v1/auth/vk/callback",
        params={"code": "c", "state": state, "device_id": "d1"},
    )
    assert r.status_code == 302 and r.headers["location"] == "/profile"

    async with db_session() as db:
        users = (await db.execute(select(User).where(User.phone == PHONE))).scalars().all()
        assert len(users) == 1  # вошли в существующий, дубль не создан
        assert users[0].id == data["user"]["id"]


async def test_no_phone_goes_to_register(client, monkeypatch):
    _vk_on(monkeypatch)
    _mock_vk(monkeypatch, {"user_id": "42", "email": "a@b.ru"})  # без phone
    state = await _start_and_get_state(client)
    r = await client.get(
        "/api/v1/auth/vk/callback",
        params={"code": "c", "state": state, "device_id": "d1"},
    )
    assert "register?error=vk_no_phone" in r.headers["location"]


async def test_token_failure_redirects_to_login(client, monkeypatch):
    _vk_on(monkeypatch)
    _mock_vk(monkeypatch, {"phone": PHONE}, token_ok=False)
    state = await _start_and_get_state(client)
    r = await client.get(
        "/api/v1/auth/vk/callback",
        params={"code": "c", "state": state, "device_id": "d1"},
    )
    assert "error=vk" in r.headers["location"]
