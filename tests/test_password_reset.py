# tests/test_password_reset.py
"""Сброс пароля (блок 08): токены, каналы, анти-перебор."""
import httpx
import pytest
from sqlalchemy import select

import app.services.password_reset as pwreset
from app.core.limiter import get_redis
from app.models.models import User
from tests.conftest import register_user

PHONE = "+79994443322"
OLD_PASSWORD = "Testpass1"
NEW_PASSWORD = "Newpass22"


@pytest.fixture()
def sent_jobs(monkeypatch):
    jobs: list[tuple] = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            jobs.append((fn, args))

    async def _pool():
        return FakePool()

    monkeypatch.setattr(pwreset, "get_arq_pool", _pool)
    return jobs


async def _issued_token(user_id: int) -> str | None:
    return await get_redis().get(f"pwreset:user:{user_id}")


async def test_full_reset_flow_via_telegram(client: httpx.AsyncClient, db_session, sent_jobs):
    data = await register_user(client, PHONE)
    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
        user.tg_chat_id = 777001
        await db.commit()

    # 1. Запрос сброса: нейтральный ответ + доставка в TG поставлена
    r = await client.post("/api/v1/auth/forgot-password", data={"phone": PHONE})
    assert r.status_code == 302 and "sent=1" in r.headers["location"]
    tg_jobs = [j for j in sent_jobs if j[0] == "send_tg_message"]
    assert len(tg_jobs) == 1 and tg_jobs[0][1][0] == 777001
    assert "/reset-password?token=" in tg_jobs[0][1][1]

    token = await _issued_token(data["user"]["id"])
    assert token and token in tg_jobs[0][1][1]

    # 2. Смена пароля по токену
    r = await client.post(
        "/api/v1/auth/reset-password",
        data={"token": token, "password": NEW_PASSWORD},
    )
    assert r.status_code == 302 and r.headers["location"] == "/login?reset=1"

    # 3. Старый пароль больше не работает, новый — работает
    r = await client.post("/api/v1/auth/login", json={"phone": PHONE, "password": OLD_PASSWORD})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"phone": PHONE, "password": NEW_PASSWORD})
    assert r.status_code == 200

    # 4. Токен одноразовый
    r = await client.post(
        "/api/v1/auth/reset-password",
        data={"token": token, "password": "Another33"},
    )
    assert "error=bad_token" in r.headers["location"]

    # 5. Security-уведомление о смене поставлено
    notice = [j for j in sent_jobs if j[0] == "send_tg_message" and "изменён" in j[1][1]]
    assert notice


async def test_unknown_phone_same_answer_no_delivery(client: httpx.AsyncClient, sent_jobs):
    """Существование аккаунта не раскрывается: ответ тот же, доставки нет."""
    r = await client.post("/api/v1/auth/forgot-password", data={"phone": "+79990001111"})
    assert r.status_code == 302 and "sent=1" in r.headers["location"]
    assert sent_jobs == []


async def test_email_channel_included_when_present(client, db_session, sent_jobs):
    await register_user(client, PHONE)
    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
        user.email = "u@example.com"
        await db.commit()

    await client.post("/api/v1/auth/forgot-password", data={"phone": PHONE})
    email_jobs = [j for j in sent_jobs if j[0] == "send_email"]
    assert len(email_jobs) == 1 and email_jobs[0][1][0] == "u@example.com"


async def test_new_request_revokes_previous_token(client, db_session, sent_jobs):
    data = await register_user(client, PHONE)
    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
        user.tg_chat_id = 777002
        await db.commit()

    await client.post("/api/v1/auth/forgot-password", data={"phone": PHONE})
    first = await _issued_token(data["user"]["id"])
    await client.post("/api/v1/auth/forgot-password", data={"phone": PHONE})
    second = await _issued_token(data["user"]["id"])
    assert first != second

    r = await client.post(
        "/api/v1/auth/reset-password",
        data={"token": first, "password": NEW_PASSWORD},
    )
    assert "error=bad_token" in r.headers["location"]  # старый отозван


async def test_weak_password_keeps_token_alive(client, db_session, sent_jobs):
    data = await register_user(client, PHONE)
    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
        user.tg_chat_id = 777003
        await db.commit()

    await client.post("/api/v1/auth/forgot-password", data={"phone": PHONE})
    token = await _issued_token(data["user"]["id"])

    r = await client.post(
        "/api/v1/auth/reset-password", data={"token": token, "password": "weak"}
    )
    assert "error=weak_password" in r.headers["location"]
    # токен не сожжён — человек исправит пароль и попробует снова
    r = await client.post(
        "/api/v1/auth/reset-password", data={"token": token, "password": NEW_PASSWORD}
    )
    assert r.headers["location"] == "/login?reset=1"


async def test_pages_render(client: httpx.AsyncClient):
    r = await client.get("/forgot-password")
    assert r.status_code == 200 and "Забыли пароль" in r.text
    r = await client.get("/reset-password", params={"token": "abc"})
    assert r.status_code == 200 and "Новый пароль" in r.text
    r = await client.get("/reset-password")
    assert "Ссылка не подходит" in r.text


async def test_sport_reset_link_and_return_to_training(client, db_session, sent_jobs, monkeypatch):
    host = "sport-staging.rrumi.ru"
    monkeypatch.setattr(pwreset.settings, "SPORT_HOST", host)
    user_data = await register_user(client, PHONE)
    async with db_session() as db:
        user = await db.get(User, user_data["user"]["id"])
        user.tg_chat_id = 777001
        await db.commit()
    form = {"auth_variant": "sport", "redirect": "/sport/sparta/schedule?day=2"}
    await client.post("/api/v1/auth/forgot-password", data={**form, "phone": PHONE})
    token = await _issued_token(user_data["user"]["id"])
    assert f"https://{host}/sport/reset-password?token={token}&redirect=%2Fsport%2Fsparta" in sent_jobs[0][1][1]
    response = await client.post("/api/v1/auth/reset-password",
                                 data={**form, "token": token, "password": NEW_PASSWORD})
    assert response.headers["location"] == "/sport/login?reset=1&redirect=%2Fsport%2Fsparta%2Fschedule%3Fday%3D2"
    login = await client.post("/api/v1/auth/login-web", data={**form, "phone": PHONE, "password": NEW_PASSWORD})
    assert login.headers["location"] == form["redirect"]
