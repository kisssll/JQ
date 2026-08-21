# tests/test_otp_max.py
"""Блок 18, этап 2: подтверждение телефона через MAX-бота.

Механика зеркальна Telegram (см. test_otp_telegram.py): бот эмулируется
чистой функцией check_max_contact + переводом записи в confirmed в Redis.
"""
import httpx
import pytest

import app.services.otp as otp_mod
from app.max_bot import (
    VERDICT_FOREIGN_CONTACT,
    VERDICT_NOT_FOUND,
    VERDICT_OK,
    VERDICT_PHONE_MISMATCH,
    check_max_contact,
)
from app.services.otp import TG_STATUS_CONFIRMED, _hash, _key

PHONE = "+79997778899"
PASSWORD = "Testpass1"

settings = otp_mod.settings


@pytest.fixture()
def max_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MAX_VERIFY_ENABLED", True)
    monkeypatch.setattr(settings, "MAX_BOT_TOKEN", "max-test-token")
    monkeypatch.setattr(settings, "MAX_BOT_USERNAME", "rumi_test_max_bot")


def _record(phone: str = PHONE, status: str = "pending") -> dict:
    return {"channel": "max", "status": status, "phone_hash": _hash(phone)}


# ── Чистая логика бота ───────────────────────────────────────────────────────

def test_max_contact_accepts_own_verified_contact():
    assert check_max_contact(_record(), 42, 42, "79997778899", True) == VERDICT_OK


def test_max_contact_rejects_foreign_or_unsigned():
    # Чужой контакт (переслан) и контакт без платформенной подписи hash
    assert check_max_contact(_record(), 999, 42, "79997778899", True) == VERDICT_FOREIGN_CONTACT
    assert check_max_contact(_record(), None, 42, "79997778899", True) == VERDICT_FOREIGN_CONTACT
    assert check_max_contact(_record(), 42, 42, "79997778899", False) == VERDICT_FOREIGN_CONTACT


def test_max_contact_rejects_wrong_phone_and_stale():
    assert check_max_contact(_record(), 42, 42, "79990000000", True) == VERDICT_PHONE_MISMATCH
    assert check_max_contact({}, 42, 42, "79997778899", True) == VERDICT_NOT_FOUND
    tg_record = {"channel": "telegram", "status": "pending", "phone_hash": _hash(PHONE)}
    assert check_max_contact(tg_record, 42, 42, "79997778899", True) == VERDICT_NOT_FOUND


# ── Эндпоинты и сквозной флоу ────────────────────────────────────────────────

async def test_max_start_404_when_disabled(client: httpx.AsyncClient):
    r = await client.post("/api/v1/auth/register/max-start", json={"phone": PHONE})
    assert r.status_code == 404


async def test_max_full_flow(client: httpx.AsyncClient, max_enabled):
    r = await client.post("/api/v1/auth/register/max-start", json={"phone": PHONE})
    assert r.status_code == 200, r.text
    data = r.json()
    request_id = data["request_id"]
    assert data["deep_link"] == f"https://max.ru/rumi_test_max_bot?start={request_id}"

    # Общий статус-эндпоинт обслуживает и MAX-записи
    r = await client.get("/api/v1/auth/register/tg-status", params={"request_id": request_id})
    assert r.json()["status"] == "pending"

    # «Бот»: собственный подписанный контакт с совпадающим номером
    redis = otp_mod.get_redis()
    record = await redis.hgetall(_key(request_id))
    assert check_max_contact(record, 42, 42, "79997778899", True) == VERDICT_OK
    await redis.hset(_key(request_id), "status", TG_STATUS_CONFIRMED)

    r = await client.post(
        "/api/v1/auth/register-web",
        data={"phone": PHONE, "password": PASSWORD, "pd_consent": "1", "full_name": "МАКС Тест",
              "request_id": request_id, "code": ""},
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/profile"

    # Одноразовость
    r = await client.post(
        "/api/v1/auth/register-web",
        data={"phone": "+79997778898", "password": PASSWORD, "pd_consent": "1",
              "request_id": request_id, "code": ""},
    )
    assert "error=bad_code" in r.headers["location"]
