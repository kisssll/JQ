# tests/test_otp_telegram.py
"""Блок 18: подтверждение телефона через Telegram-бота.

Бот в тестах не запускается — его решение эмулируется так же, как оно
происходит в проде: чистая функция check_contact + перевод записи в
confirmed в Redis. Поллинг/verify проверяются через реальные эндпоинты.
"""
import httpx
import pytest

import app.services.otp as otp_mod
from app.services.otp import TG_STATUS_CONFIRMED, _hash, _key
from tests.conftest import register_user
from app.tg_bot import (
    VERDICT_FOREIGN_CONTACT,
    VERDICT_NOT_FOUND,
    VERDICT_OK,
    VERDICT_PHONE_MISMATCH,
    check_contact,
)

PHONE = "+79993334455"
PASSWORD = "Testpass1"

# Все модули приложения импортировали ОДИН экземпляр settings при старте —
# патчим именно его (после reload'ов в test_config_guards глобальный
# app.core.config.settings может быть уже другим объектом).
settings = otp_mod.settings


@pytest.fixture()
def tg_enabled(monkeypatch):
    monkeypatch.setattr(settings, "TG_VERIFY_ENABLED", True)
    monkeypatch.setattr(settings, "TG_BOT_TOKEN", "000:test-token")
    monkeypatch.setattr(settings, "TG_BOT_USERNAME", "rumi_test_bot")


def _record(phone: str = PHONE, status: str = "pending") -> dict:
    return {"channel": "telegram", "status": status, "phone_hash": _hash(phone)}


# ── Чистая логика бота ───────────────────────────────────────────────────────

def test_check_contact_accepts_own_matching_contact():
    assert check_contact(_record(), 42, 42, "79993334455") == VERDICT_OK


def test_check_contact_rejects_forwarded_foreign_contact():
    # Пересланный контакт другого человека: contact.user_id != отправитель
    assert check_contact(_record(), 999, 42, "79993334455") == VERDICT_FOREIGN_CONTACT
    # У контактов не из Telegram user_id может отсутствовать вовсе
    assert check_contact(_record(), None, 42, "79993334455") == VERDICT_FOREIGN_CONTACT


def test_check_contact_rejects_wrong_phone():
    assert check_contact(_record(), 42, 42, "79990000000") == VERDICT_PHONE_MISMATCH


def test_check_contact_rejects_stale_or_alien_records():
    assert check_contact({}, 42, 42, "79993334455") == VERDICT_NOT_FOUND
    assert check_contact(_record(status="confirmed"), 42, 42, "79993334455") == VERDICT_NOT_FOUND
    sms_record = {"phone_hash": _hash(PHONE), "code_hash": "x", "attempts": "0"}
    assert check_contact(sms_record, 42, 42, "79993334455") == VERDICT_NOT_FOUND


# ── Эндпоинты и сквозной флоу ────────────────────────────────────────────────

async def test_tg_endpoints_404_when_disabled(client: httpx.AsyncClient):
    r = await client.post("/api/v1/auth/register/tg-start", json={"phone": PHONE})
    assert r.status_code == 404
    r = await client.get("/api/v1/auth/register/tg-status", params={"request_id": "x"})
    assert r.status_code == 404


async def test_tg_full_flow_and_one_shot(client: httpx.AsyncClient, tg_enabled):
    # 1. Страница начинает верификацию
    r = await client.post("/api/v1/auth/register/tg-start", json={"phone": PHONE})
    assert r.status_code == 200
    data = r.json()
    request_id = data["request_id"]
    assert data["deep_link"] == f"https://t.me/rumi_test_bot?start={request_id}"

    r = await client.get("/api/v1/auth/register/tg-status", params={"request_id": request_id})
    assert r.json()["status"] == "pending"

    # 2. «Бот»: проверяет собственный контакт с совпадающим номером и подтверждает
    redis = otp_mod.get_redis()
    record = await redis.hgetall(_key(request_id))
    assert check_contact(record, 42, 42, "79993334455") == VERDICT_OK
    await redis.hset(_key(request_id), "status", TG_STATUS_CONFIRMED)

    r = await client.get("/api/v1/auth/register/tg-status", params={"request_id": request_id})
    assert r.json()["status"] == "confirmed"

    # 3. Регистрация с подтверждённым request_id, код не нужен
    r = await client.post(
        "/api/v1/auth/register-web",
        data={"phone": PHONE, "password": PASSWORD, "pd_consent": "1", "full_name": "ТГ Тест",
              "request_id": request_id, "code": ""},
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/profile"

    # 4. Запись одноразовая: повторное использование того же request_id — отказ
    r = await client.post(
        "/api/v1/auth/register-web",
        data={"phone": "+79993334456", "password": PASSWORD, "pd_consent": "1",
              "request_id": request_id, "code": ""},
    )
    assert r.status_code == 302
    assert "error=bad_code" in r.headers["location"]


async def test_pending_request_id_is_not_enough(client: httpx.AsyncClient, tg_enabled):
    """Токен из deep link'а без подтверждения ботом регистрацию не открывает."""
    r = await client.post("/api/v1/auth/register/tg-start", json={"phone": PHONE})
    request_id = r.json()["request_id"]

    r = await client.post(
        "/api/v1/auth/register-web",
        data={"phone": PHONE, "password": PASSWORD, "pd_consent": "1", "request_id": request_id, "code": ""},
    )
    assert r.status_code == 302
    assert "error=bad_code" in r.headers["location"]


async def test_tg_confirmation_is_bound_to_phone(client: httpx.AsyncClient, tg_enabled):
    """Подтвердил один номер — зарегистрировать с ним другой нельзя."""
    r = await client.post("/api/v1/auth/register/tg-start", json={"phone": PHONE})
    request_id = r.json()["request_id"]
    await otp_mod.get_redis().hset(_key(request_id), "status", TG_STATUS_CONFIRMED)

    r = await client.post(
        "/api/v1/auth/register-web",
        data={"phone": "+79990001122", "password": PASSWORD, "pd_consent": "1",
              "request_id": request_id, "code": ""},
    )
    assert r.status_code == 302
    assert "error=bad_code" in r.headers["location"]


async def test_tg_start_rejects_registered_phone(client: httpx.AsyncClient, tg_enabled):
    await register_user(client, PHONE)
    r = await client.post("/api/v1/auth/register/tg-start", json={"phone": PHONE})
    assert r.status_code == 409


async def test_find_pending_register_token_rescue(tg_enabled):
    """Спасение без deep-link токена: находит ожидающую TG-регистрацию по номеру."""
    from app.tg_bot import _find_pending_register_token
    import app.services.otp as otp_mod

    phone = "+79993334455"
    started = await otp_mod.start_tg_verification(phone)
    r = otp_mod.get_redis()

    # находит ожидающую регистрацию по номеру
    assert await _find_pending_register_token(r, phone) == started["request_id"]
    # другой номер — не находит
    assert await _find_pending_register_token(r, "+79990000000") is None
    # после подтверждения (status != pending) — больше не находит
    await r.hset(_key(started["request_id"]), "status", TG_STATUS_CONFIRMED)
    assert await _find_pending_register_token(r, phone) is None
