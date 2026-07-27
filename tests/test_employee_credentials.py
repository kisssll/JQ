"""Реквизиты сотрудника/мастера: AJAX-ответ с логином/паролем (не в URL),
сброс пароля, отправка на почту салона, поле почты салона."""
from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus, Master,
)
from app.services import notifications


async def _owner_salon(db, phone="+79994441000", salon_phone="+70000000960", email=None):
    owner = User(phone=phone, full_name="Owner", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.BUSINESS, is_active=True)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    salon = Salon(name="S", address="a", phone=salon_phone, latitude=1.0, longitude=1.0,
                  timezone="Europe/Moscow", moderation_status=SalonModerationStatus.APPROVED,
                  is_active=True, creator_id=owner.id, email=email)
    db.add(salon)
    await db.commit()
    await db.refresh(salon)
    db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                       is_creator=True, permissions={}, is_active=True))
    await db.commit()
    return owner, salon


async def _login(client, phone):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"})
    assert r.status_code == 302, r.text


async def test_add_new_master_returns_credentials(client, db_session):
    async with db_session() as db:
        owner, salon = await _owner_salon(db)
        salon_id = salon.id
    await _login(client, owner.phone)
    r = await client.post("/api/v1/master/create-web", data={
        "full_name": "Новый Мастер", "phone": "+79994441111",
        "specialization": "Барбер", "salon_id": salon_id,
    })
    assert r.status_code == 200, r.text
    creds = r.json()["credentials"]
    assert creds and creds["login"] == "+79994441111" and creds["password"]


async def test_add_existing_account_master_has_no_credentials(client, db_session):
    async with db_session() as db:
        owner, salon = await _owner_salon(db)
        salon_id = salon.id
        # заранее создаём пользователя с известным паролем
        db.add(User(phone="+79994441222", full_name="Есть", hashed_password=get_password_hash("Testpass1"),
                    role=UserRole.CLIENT, is_active=True))
        await db.commit()
    await _login(client, owner.phone)
    r = await client.post("/api/v1/master/create-web", data={
        "full_name": "Есть", "phone": "+79994441222", "specialization": "X", "salon_id": salon_id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["credentials"] is None  # у существующего аккаунта свой пароль


async def test_reset_master_password_returns_new_credentials(client, db_session):
    async with db_session() as db:
        owner, salon = await _owner_salon(db)
        salon_id = salon.id
    await _login(client, owner.phone)
    r = await client.post("/api/v1/master/create-web", data={
        "full_name": "М", "phone": "+79994441333", "specialization": "X", "salon_id": salon_id,
    })
    # найдём master_id
    from sqlalchemy import select
    async with db_session() as db:
        u = (await db.execute(select(User).where(User.phone == "+79994441333"))).scalar_one()
        m = (await db.execute(select(Master).where(Master.user_id == u.id))).scalar_one()
        master_id = m.id
    r = await client.post(f"/api/v1/master/{master_id}/reset-password")
    assert r.status_code == 200, r.text
    assert r.json()["credentials"]["password"]


async def test_send_credentials_requires_salon_email(client, db_session):
    async with db_session() as db:
        owner, salon = await _owner_salon(db, email=None)
        salon_id = salon.id
    await _login(client, owner.phone)
    r = await client.post("/api/v1/business/staff/send-credentials", json={
        "salon_id": salon_id, "name": "М", "login": "+79994441444", "password": "pw",
    })
    assert r.status_code == 400
    assert "почт" in r.json()["detail"].lower()


async def test_send_credentials_enqueues_with_email(client, db_session, monkeypatch):
    captured = {}

    class _Pool:
        async def enqueue_job(self, name, *a, **k):
            captured["name"] = name
            captured["args"] = a

    async def _pool():
        return _Pool()
    monkeypatch.setattr(notifications, "get_arq_pool", _pool)

    async with db_session() as db:
        owner, salon = await _owner_salon(db, email="salon@example.com")
        salon_id = salon.id
    await _login(client, owner.phone)
    r = await client.post("/api/v1/business/staff/send-credentials", json={
        "salon_id": salon_id, "name": "М", "login": "+79994441555", "password": "secretpw",
    })
    assert r.status_code == 200, r.text
    assert r.json()["sent_to"] == "salon@example.com"
    assert captured["name"] == "send_email"
    assert captured["args"][0] == "salon@example.com"


async def test_salon_email_saved_via_update(client, db_session):
    async with db_session() as db:
        owner, salon = await _owner_salon(db)
        salon_id = salon.id
    await _login(client, owner.phone)
    r = await client.put(f"/api/v1/business/my-salon?salon_id={salon_id}", json={"email": "new@salon.ru"})
    assert r.status_code == 200, r.text
    from sqlalchemy import select
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        assert s.email == "new@salon.ru"
