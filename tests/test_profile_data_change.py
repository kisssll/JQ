# tests/test_profile_data_change.py
"""Смена данных в профиле: город, email, пароль, телефон (TG), удаление.

Заменили фронтовые заглушки (alert «имитация») на реальные эндпоинты
/api/v1/users/me/{city,email,phone,delete}-form. OTP-флоу телефона покрыт
отдельно (test_otp_telegram); здесь happy-path телефона мокает verify_code.
"""
import httpx
import pytest
from sqlalchemy import select

from app.models.models import User
from tests.conftest import register_user


async def _login_web(client: httpx.AsyncClient, phone: str, password: str = "Testpass1") -> None:
    r = await client.post(
        "/api/v1/auth/login-web",
        data={"phone": phone, "password": password},
    )
    assert r.status_code == 302, r.text


async def _get_user(db_session, phone: str) -> User:
    async with db_session() as db:
        return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def test_city_update(client, db_session):
    phone = "+79993330001"
    await register_user(client, phone)
    await _login_web(client, phone)

    r = await client.post("/api/v1/users/me/city-form", data={"city": "Томск"})
    assert r.status_code == 302 and "success=city_updated" in r.headers["location"]

    user = await _get_user(db_session, phone)
    assert user.city == "Томск"

    # Пустой город → сбрасывается в NULL
    r = await client.post("/api/v1/users/me/city-form", data={"city": "  "})
    assert r.status_code == 302
    user = await _get_user(db_session, phone)
    assert user.city is None


@pytest.fixture()
def fake_arq(monkeypatch):
    """send_email_code ставит письмо в очередь — подменяем пул, ловим джобы."""
    jobs = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            jobs.append((fn, args))

    async def _pool():
        return FakePool()

    monkeypatch.setattr("app.services.email_verify.get_arq_pool", _pool)
    return jobs


async def test_email_update_with_code(client, db_session, fake_arq):
    phone = "+79993330002"
    await register_user(client, phone)
    await _login_web(client, phone)

    # Шаг 1: запросить код на новый адрес
    r = await client.post("/api/v1/users/me/email/send-code", data={"email": "me@rrumi.ru"})
    assert r.status_code == 200, r.text
    d = r.json()
    code = d["dev_code"]
    assert code  # mock-режим отдаёт код
    assert any(j[0] == "send_email" for j in fake_arq)  # письмо поставлено в очередь

    # Шаг 2: применить с кодом
    r = await client.post(
        "/api/v1/users/me/email-form",
        data={"email": "me@rrumi.ru", "request_id": d["request_id"], "code": code},
    )
    assert r.status_code == 302 and "success=email_updated" in r.headers["location"]
    user = await _get_user(db_session, phone)
    assert user.email == "me@rrumi.ru"


async def test_email_wrong_code_rejected(client, db_session, fake_arq):
    phone = "+79993330012"
    await register_user(client, phone)
    await _login_web(client, phone)

    r = await client.post("/api/v1/users/me/email/send-code", data={"email": "new@rrumi.ru"})
    d = r.json()
    r = await client.post(
        "/api/v1/users/me/email-form",
        data={"email": "new@rrumi.ru", "request_id": d["request_id"], "code": "9999"},
    )
    assert r.status_code == 302 and "error=email_not_verified" in r.headers["location"]
    user = await _get_user(db_session, phone)
    assert user.email != "new@rrumi.ru"


async def test_email_send_code_conflict(client, db_session, fake_arq):
    phone_a = "+79993330003"
    phone_b = "+79993330013"
    await register_user(client, phone_a)
    await register_user(client, phone_b)

    # A занимает email (через код)
    await _login_web(client, phone_a)
    r = await client.post("/api/v1/users/me/email/send-code", data={"email": "taken@rrumi.ru"})
    d = r.json()
    await client.post(
        "/api/v1/users/me/email-form",
        data={"email": "taken@rrumi.ru", "request_id": d["request_id"], "code": d["dev_code"]},
    )

    # B даже не может запросить код на занятый адрес
    await _login_web(client, phone_b)
    r = await client.post("/api/v1/users/me/email/send-code", data={"email": "taken@rrumi.ru"})
    assert r.status_code == 409


async def test_password_change(client, db_session):
    phone = "+79993330004"
    await register_user(client, phone)
    await _login_web(client, phone)

    # Неверный текущий пароль
    r = await client.post(
        "/api/v1/users/me/password-form",
        data={"current_password": "Wrong1", "new_password": "Newpass1", "confirm_password": "Newpass1"},
    )
    assert r.status_code == 302 and "error=wrong_password" in r.headers["location"]

    # Успешная смена → вход по новому паролю
    r = await client.post(
        "/api/v1/users/me/password-form",
        data={"current_password": "Testpass1", "new_password": "Newpass1", "confirm_password": "Newpass1"},
    )
    assert r.status_code == 302 and "success=password_updated" in r.headers["location"]
    await _login_web(client, phone, password="Newpass1")


async def test_phone_change_verified(client, db_session, monkeypatch):
    phone = "+79993330005"
    new_phone = "+79993330099"
    await register_user(client, phone)
    await _login_web(client, phone)

    # Подтверждение владения номером эмулируем (TG-флоу покрыт отдельно)
    async def _ok(request_id, code, ph):
        return True

    monkeypatch.setattr("app.services.otp.verify_code", _ok)

    r = await client.post(
        "/api/v1/users/me/phone-form",
        data={"phone": new_phone, "request_id": "whatever"},
    )
    assert r.status_code == 302 and "success=phone_updated" in r.headers["location"]
    user = await _get_user(db_session, new_phone)
    assert user.phone == new_phone


async def test_phone_change_conflict(client, db_session, monkeypatch):
    phone_a = "+79993330006"
    phone_b = "+79993330007"
    await register_user(client, phone_a)
    await register_user(client, phone_b)
    await _login_web(client, phone_a)

    async def _ok(request_id, code, ph):
        return True

    monkeypatch.setattr("app.services.otp.verify_code", _ok)

    # Пытаемся занять номер, уже принадлежащий другому юзеру
    r = await client.post(
        "/api/v1/users/me/phone-form",
        data={"phone": phone_b, "request_id": "whatever"},
    )
    assert r.status_code == 302 and "error=phone_exists" in r.headers["location"]


async def test_phone_change_not_verified(client, db_session, monkeypatch):
    phone = "+79993330008"
    await register_user(client, phone)
    await _login_web(client, phone)

    async def _fail(request_id, code, ph):
        return False

    monkeypatch.setattr("app.services.otp.verify_code", _fail)

    r = await client.post(
        "/api/v1/users/me/phone-form",
        data={"phone": "+79993330100", "request_id": "bad"},
    )
    assert r.status_code == 302 and "error=phone_not_verified" in r.headers["location"]


async def test_delete_account_soft(client, db_session):
    phone = "+79993330009"
    await register_user(client, phone)
    await _login_web(client, phone)

    # Неверный пароль не удаляет
    r = await client.post("/api/v1/users/me/delete-form", data={"password": "Wrong1"})
    assert r.status_code == 302 and "error=wrong_password" in r.headers["location"]
    user = await _get_user(db_session, phone)
    assert user.is_active is True

    # Верный пароль → мягкое удаление (деактивация), cookie сброшен
    r = await client.post("/api/v1/users/me/delete-form", data={"password": "Testpass1"})
    assert r.status_code == 302 and "account_deleted=1" in r.headers["location"]
    user = await _get_user(db_session, phone)
    assert user.is_active is False


async def test_inactive_user_blocked_on_web(client, db_session):
    """Деактивированный (мягко удалённый) юзер: cookie не работает и вход закрыт."""
    phone = "+79993330020"
    await register_user(client, phone)
    await _login_web(client, phone)  # cookie установлена

    async with db_session() as db:
        u = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        u.is_active = False
        await db.commit()

    # Существующая cookie больше не аутентифицирует веб-ручки
    r = await client.post("/api/v1/users/me/city-form", data={"city": "Х"})
    assert r.status_code == 302 and "/login" in r.headers["location"]

    # И заново залогиниться нельзя
    r = await client.post(
        "/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"}
    )
    assert r.status_code == 302 and "error=locked" in r.headers["location"]


async def test_update_form_does_not_change_email(client, db_session):
    """update-form (имя/аватар/био) НЕ меняет email — только верифиц. путь."""
    phone = "+79993330021"
    await register_user(client, phone)
    await _login_web(client, phone)

    r = await client.post(
        "/api/v1/users/me/update-form",
        data={"full_name": "Новое Имя", "email": "sneaky@x.ru"},
    )
    assert r.status_code == 302
    user = await _get_user(db_session, phone)
    assert user.full_name == "Новое Имя"
    assert user.email != "sneaky@x.ru"


@pytest.mark.parametrize("path", ["/api/v1/users/me/update-form", "/api/v1/users/me"])
async def test_profile_name_is_stripped_and_never_blank(client, db_session, path):
    """Имя из пробелов раньше доходило до базы как есть, и этикетка в шапке
    валила 500 на каждой странице. Обе формы профиля чистят имя и пустое не
    принимают — прежнее имя при этом остаётся."""
    phone = "+79993330091" if path.endswith("update-form") else "+79993330092"
    await register_user(client, phone, full_name="Анна")
    await _login_web(client, phone)

    r = await client.post(path, data={"full_name": "   "})
    assert r.status_code == 302 and "error=bad_name" in r.headers["location"]
    assert (await _get_user(db_session, phone)).full_name == "Анна"

    r = await client.post(path, data={"full_name": "x" * 101})
    assert "error=bad_name" in r.headers["location"], "длиннее колонки — 500 от базы"

    r = await client.post(path, data={"full_name": "  Анна Петрова \t"})
    assert "success=updated" in r.headers["location"]
    assert (await _get_user(db_session, phone)).full_name == "Анна Петрова"


async def test_profile_api_rejects_a_blank_name(client, db_session):
    phone = "+79993330093"
    tokens = await register_user(client, phone, full_name="Анна")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = await client.patch("/api/v1/users/me", json={"full_name": " "}, headers=headers)
    assert r.status_code == 422
    assert (await _get_user(db_session, phone)).full_name == "Анна"
