# tests/test_manager_role.py
"""Роль «Управляющий» (SalonRole.MANAGER): шире обычного админа по правам
(кроме manage_owners), но назначить/снять/изменить его права может только
создатель салона — не любой совладелец с manage_owners и не обычный админ
с manage_admins. Исключение: сам управляющий может себя снять (покинуть
салон), но не может редактировать себе права (защита от самоэскалации)."""
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole,
    SalonModerationStatus, MANAGER_DEFAULT_PERMISSIONS,
)
from app.schemas.user import try_normalize_phone


async def _login(client, phone, password="Testpass1"):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": password})
    assert r.status_code == 302, r.text


async def _make_user(db, phone, *, role=UserRole.CLIENT, full_name="U") -> User:
    u = User(phone=phone, full_name=full_name, hashed_password=get_password_hash("Testpass1"), role=role)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _setup_salon(db_session):
    """Салон с создателем (полные права) + отдельным co-owner (не создатель,
    manage_owners=True) + отдельным admin (manage_admins=True)."""
    async with db_session() as db:
        salon = Salon(name="S", address="a", phone="+70000000300",
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      moderation_status=SalonModerationStatus.APPROVED, is_active=True)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        creator = await _make_user(db, "+79995550001", role=UserRole.BUSINESS, full_name="Creator")
        co_owner = await _make_user(db, "+79995550002", role=UserRole.BUSINESS, full_name="CoOwner")
        admin = await _make_user(db, "+79995550003", role=UserRole.BUSINESS, full_name="Admin")

        salon.creator_id = creator.id
        db.add(SalonMember(salon_id=salon.id, user_id=creator.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_owners": True, "manage_admins": True},
                           is_active=True))
        db.add(SalonMember(salon_id=salon.id, user_id=co_owner.id, role=SalonRole.OWNER,
                           is_creator=False, permissions={"manage_owners": True, "manage_admins": True},
                           is_active=True))
        db.add(SalonMember(salon_id=salon.id, user_id=admin.id, role=SalonRole.ADMIN,
                           is_creator=False, permissions={"manage_admins": True, "manage_owners": False},
                           is_active=True))
        await db.commit()
        return salon.id


async def _hire_manager(client, salon_id, phone="+79995550004") -> None:
    r = await client.post("/api/v1/business/staff/add-web",
                          data={"phone": phone, "full_name": "Manager", "role": "manager", "salon_id": salon_id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


async def test_creator_can_hire_manager_with_wide_default_permissions(client, db_session):
    salon_id = await _setup_salon(db_session)
    await _login(client, "+79995550001")  # creator
    await _hire_manager(client, salon_id)

    async with db_session() as db:
        u = (await db.execute(select(User).where(User.phone == try_normalize_phone("+79995550004")))).scalar_one()
        m = (await db.execute(select(SalonMember).where(
            SalonMember.user_id == u.id, SalonMember.salon_id == salon_id))).scalar_one()
        assert m.role == SalonRole.MANAGER
        assert m.permissions == MANAGER_DEFAULT_PERMISSIONS
        assert m.permissions["manage_owners"] is False
        assert m.permissions["manage_admins"] is True
        assert m.permissions["view_finances"] is True


async def test_non_creator_owner_cannot_hire_manager(client, db_session):
    """Co-owner с manage_owners=True, но не создатель — не может назначить управляющего."""
    salon_id = await _setup_salon(db_session)
    await _login(client, "+79995550002")  # co-owner, не создатель
    r = await client.post("/api/v1/business/staff/add-web",
                          data={"phone": "+79995550005", "full_name": "M2", "role": "manager", "salon_id": salon_id})
    assert r.status_code == 403


async def test_admin_cannot_edit_or_remove_manager(client, db_session):
    salon_id = await _setup_salon(db_session)
    await _login(client, "+79995550001")
    await _hire_manager(client, salon_id)

    async with db_session() as db:
        mgr_user = (await db.execute(select(User).where(User.phone == try_normalize_phone("+79995550004")))).scalar_one()
        mgr_member = (await db.execute(select(SalonMember).where(
            SalonMember.user_id == mgr_user.id, SalonMember.salon_id == salon_id))).scalar_one()
        member_id = mgr_member.id

    await _login(client, "+79995550003")  # обычный admin с manage_admins=True

    r = await client.post(f"/api/v1/business/staff/{member_id}/permissions", json={"permissions": {"view_finances": False}})
    assert r.status_code == 403

    r = await client.request("DELETE", f"/api/v1/business/staff/{member_id}")
    assert r.status_code == 403


async def test_non_creator_owner_cannot_edit_or_remove_manager(client, db_session):
    """Даже co-owner с manage_owners=True не может трогать управляющего — только создатель."""
    salon_id = await _setup_salon(db_session)
    await _login(client, "+79995550001")
    await _hire_manager(client, salon_id)

    async with db_session() as db:
        mgr_user = (await db.execute(select(User).where(User.phone == try_normalize_phone("+79995550004")))).scalar_one()
        mgr_member = (await db.execute(select(SalonMember).where(
            SalonMember.user_id == mgr_user.id, SalonMember.salon_id == salon_id))).scalar_one()
        member_id = mgr_member.id

    await _login(client, "+79995550002")  # co-owner, manage_owners=True, не создатель

    r = await client.post(f"/api/v1/business/staff/{member_id}/permissions", json={"permissions": {"view_finances": False}})
    assert r.status_code == 403

    r = await client.request("DELETE", f"/api/v1/business/staff/{member_id}")
    assert r.status_code == 403


async def test_creator_can_edit_and_remove_manager(client, db_session):
    salon_id = await _setup_salon(db_session)
    await _login(client, "+79995550001")
    await _hire_manager(client, salon_id)

    async with db_session() as db:
        mgr_user = (await db.execute(select(User).where(User.phone == try_normalize_phone("+79995550004")))).scalar_one()
        mgr_member = (await db.execute(select(SalonMember).where(
            SalonMember.user_id == mgr_user.id, SalonMember.salon_id == salon_id))).scalar_one()
        member_id = mgr_member.id

    r = await client.post(f"/api/v1/business/staff/{member_id}/permissions",
                          json={"permissions": {"view_finances": False}})
    assert r.status_code == 200, r.text
    assert r.json()["permissions"]["view_finances"] is False

    r = await client.request("DELETE", f"/api/v1/business/staff/{member_id}")
    assert r.status_code == 200, r.text

    async with db_session() as db:
        m = (await db.execute(select(SalonMember).where(SalonMember.id == member_id))).scalar_one()
        assert m.is_active is False


async def test_manager_can_remove_self_but_not_edit_own_permissions(client, db_session):
    salon_id = await _setup_salon(db_session)
    async with db_session() as db:
        # Создаём аккаунт заранее с известным паролем — иначе add-web сгенерит
        # случайный временный пароль и логин под менеджера в тесте не пройдёт.
        await _make_user(db, "+79995550004", role=UserRole.CLIENT, full_name="Manager")
    await _login(client, "+79995550001")
    await _hire_manager(client, salon_id)

    async with db_session() as db:
        mgr_user = (await db.execute(select(User).where(User.phone == try_normalize_phone("+79995550004")))).scalar_one()
        mgr_member = (await db.execute(select(SalonMember).where(
            SalonMember.user_id == mgr_user.id, SalonMember.salon_id == salon_id))).scalar_one()
        member_id = mgr_member.id

    await _login(client, "+79995550004")  # сам управляющий

    # Не может поднять себе права (защита от самоэскалации)
    r = await client.post(f"/api/v1/business/staff/{member_id}/permissions",
                          json={"permissions": {"manage_owners": True}})
    assert r.status_code == 403

    # Но может сам себя снять (покинуть салон)
    r = await client.request("DELETE", f"/api/v1/business/staff/{member_id}")
    assert r.status_code == 200, r.text

    async with db_session() as db:
        m = (await db.execute(select(SalonMember).where(SalonMember.id == member_id))).scalar_one()
        assert m.is_active is False
