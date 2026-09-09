# tests/test_outreach_match.py
"""Сверка холодной базы аутрича с базой Руми по хешам телефонов.

Метод внутренний, но открыт наружу — значит, проверяем не только «что считает
правильно», но и «кого не пускает» и «что не отдаёт лишнего».
"""
import hashlib

import pytest

from tests.conftest import register_user

SALT = "тестовая-соль"


def fp(phone: str) -> str:
    return hashlib.sha256(f"{SALT}:{phone.strip().lower()}".encode()).hexdigest()


@pytest.fixture(autouse=True)
def _salt(monkeypatch):
    monkeypatch.setenv("OUTREACH_HASH_SALT", SALT)


async def _login_admin(client, db_session):
    """Модератор: роль назначается напрямую, через API её получить нельзя."""
    from sqlalchemy import select
    from app.models.models import User, UserRole

    phone = "+79990000001"
    await register_user(client, phone, password="Adminpass1")
    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        user.role = UserRole.ADMIN
        await db.commit()
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": phone, "password": "Adminpass1"})
    assert r.status_code in (302, 200)


async def test_requires_moderator(client):
    """Без прав — 403, и ни слова о том, кто есть в базе."""
    r = await client.post("/api/v1/admin/outreach/match", json={"hashes": [fp("+79991112233")]})
    assert r.status_code == 403


async def test_unknown_phone_reports_absent(client, db_session):
    await _login_admin(client, db_session)
    digest = fp("+79995554433")
    r = await client.post("/api/v1/admin/outreach/match", json={"hashes": [digest]})
    assert r.status_code == 200
    assert r.json() == {digest: "нет"}


async def test_registered_user_is_found(client, db_session):
    await _login_admin(client, db_session)
    phone = "+79991112233"
    await register_user(client, phone, password="Testpass1")
    digest = fp(phone)
    r = await client.post("/api/v1/admin/outreach/match", json={"hashes": [digest]})
    assert r.json()[digest] == "зарегистрирован"


async def test_response_contains_only_asked_hashes(client, db_session):
    """Метод не должен становиться способом выгрузить чужую базу: отвечаем
    ровно на спрошенное, никаких телефонов и имён в ответе."""
    await _login_admin(client, db_session)
    await register_user(client, "+79991112233", password="Testpass1")
    asked = fp("+79995554433")
    r = await client.post("/api/v1/admin/outreach/match", json={"hashes": [asked]})
    body = r.json()
    assert set(body) == {asked}
    assert "79991112233" not in r.text


async def test_batch_is_capped(client, db_session):
    """Неограниченный список превратил бы метод в перебор телефонов."""
    await _login_admin(client, db_session)
    r = await client.post("/api/v1/admin/outreach/match",
                          json={"hashes": [fp(str(i)) for i in range(501)]})
    assert r.status_code == 422


async def test_missing_salt_fails_loudly(client, db_session, monkeypatch):
    """Молчаливое «никого не нашли» хуже явной ошибки: сотрудник решил бы,
    что до продукта не дошёл никто."""
    await _login_admin(client, db_session)
    monkeypatch.delenv("OUTREACH_HASH_SALT", raising=False)
    r = await client.post("/api/v1/admin/outreach/match", json={"hashes": [fp("+79991112233")]})
    assert r.status_code == 503
