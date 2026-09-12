# tests/test_admin_delete_user.py
"""Удаление пользователя админом: чистит клиентские зависимости (без 500),
блокирует удаление сотрудника салона."""
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, ClientLoyalty, SalonModel, ClientNote,
    SalonMember, SalonRole, OWNER_DEFAULT_PERMISSIONS,
)

ADMIN_PHONE = "+79993330099"


async def _senior_admin_login(client, db_session):
    async with db_session() as db:
        db.add(User(phone=ADMIN_PHONE, full_name="Admin",
                    hashed_password=get_password_hash("Adminpass1"),
                    role=UserRole.ADMIN, is_senior_admin=True))
        await db.commit()
    r = await client.post("/api/v1/auth/login", json={"phone": ADMIN_PHONE, "password": "Adminpass1"})
    client.cookies.set("access_token", r.json()["access_token"])


async def _make_salon(db_session) -> int:
    async with db_session() as db:
        s = Salon(name="S", address="a", phone="+70000000099",
                  latitude=1.0, longitude=1.0, timezone="Europe/Moscow")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_delete_client_with_loyalty_model_notes(client, db_session):
    """Раньше давало 500: ClientLoyalty/SalonModel/ClientNote не чистились."""
    salon_id = await _make_salon(db_session)
    async with db_session() as db:
        u = User(phone="+79993330030", full_name="Клиент",
                 hashed_password=get_password_hash("Pass1"), role=UserRole.CLIENT)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        db.add(ClientLoyalty(salon_id=salon_id, client_id=u.id, bonus_points=50))
        db.add(SalonModel(salon_id=salon_id, user_id=u.id, stage_name="M"))
        db.add(ClientNote(salon_id=salon_id, client_id=u.id, author_id=u.id, text="n"))
        await db.commit()
        cid = u.id

    await _senior_admin_login(client, db_session)
    r = await client.post(f"/api/v1/admin/users/{cid}/delete")
    assert r.status_code == 302 and "ok=" in r.headers["location"], r.headers["location"]

    async with db_session() as db:
        assert (await db.execute(select(User).where(User.id == cid))).scalar_one_or_none() is None
        assert (await db.execute(select(ClientLoyalty).where(ClientLoyalty.client_id == cid))).scalar_one_or_none() is None
        assert (await db.execute(select(SalonModel).where(SalonModel.user_id == cid))).scalar_one_or_none() is None
        assert (await db.execute(select(ClientNote).where(ClientNote.client_id == cid))).scalar_one_or_none() is None


async def test_delete_staff_blocked(client, db_session):
    """Сотрудника салона удалять нельзя (created_by-ссылки в аудите)."""
    salon_id = await _make_salon(db_session)
    async with db_session() as db:
        u = User(phone="+79993330031", full_name="Сотрудник",
                 hashed_password=get_password_hash("Pass1"), role=UserRole.BUSINESS)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        db.add(SalonMember(salon_id=salon_id, user_id=u.id, role=SalonRole.ADMIN,
                           permissions={}, is_active=True))
        await db.commit()
        cid = u.id

    await _senior_admin_login(client, db_session)
    r = await client.post(f"/api/v1/admin/users/{cid}/delete")
    assert r.status_code == 302 and "err=" in r.headers["location"]
    async with db_session() as db:
        assert (await db.execute(select(User).where(User.id == cid))).scalar_one_or_none() is not None


async def test_change_owner_revokes_old_owner_access(client, db_session):
    """Смена владельца: старый владелец теряет доступ (is_active=False)."""
    from app.api.deps import get_salon_membership

    async with db_session() as db:
        salon = Salon(name="S2", address="a", phone="+70000000098",
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow")
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        old = User(phone="+79993330040", full_name="Старый",
                   hashed_password=get_password_hash("Pass1"), role=UserRole.BUSINESS)
        new = User(phone="+79993330041", full_name="Новый",
                   hashed_password=get_password_hash("Pass1"), role=UserRole.CLIENT)
        db.add_all([old, new])
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        salon.creator_id = old.id
        db.add(SalonMember(salon_id=salon.id, user_id=old.id, role=SalonRole.OWNER,
                           is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS),
                           is_active=True))
        await db.commit()
        sid, old_id, new_id = salon.id, old.id, new.id

    await _senior_admin_login(client, db_session)
    r = await client.post(f"/api/v1/admin/salons/{sid}/owner",
                          data={"owner_phone": "+79993330041"})
    assert r.status_code == 302 and "ok=" in r.headers["location"], r.headers["location"]

    async with db_session() as db:
        old_m = (await db.execute(select(SalonMember).where(
            SalonMember.salon_id == sid, SalonMember.user_id == old_id))).scalar_one()
        assert old_m.is_active is False and old_m.is_creator is False
        # доступ снят: активного членства больше нет
        assert await get_salon_membership(db, old_id, sid) is None
        new_m = (await db.execute(select(SalonMember).where(
            SalonMember.salon_id == sid, SalonMember.user_id == new_id))).scalar_one()
        assert new_m.is_active is True and new_m.is_creator is True and new_m.role == SalonRole.OWNER
        salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert salon.creator_id == new_id


async def test_delete_ex_owner_inactive_membership_ok(client, db_session):
    """Снятый владелец/уволенный (неактивное членство) — удаляется, блок не срабатывает."""
    salon_id = await _make_salon(db_session)
    async with db_session() as db:
        u = User(phone="+79993330050", full_name="Экс-владелец",
                 hashed_password=get_password_hash("Pass1"), role=UserRole.CLIENT)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        db.add(SalonMember(salon_id=salon_id, user_id=u.id, role=SalonRole.OWNER,
                           permissions={}, is_active=False, is_creator=False))
        await db.commit()
        cid = u.id

    await _senior_admin_login(client, db_session)
    r = await client.post(f"/api/v1/admin/users/{cid}/delete")
    assert r.status_code == 302 and "ok=" in r.headers["location"], r.headers["location"]
    async with db_session() as db:
        assert (await db.execute(select(User).where(User.id == cid))).scalar_one_or_none() is None
        assert (await db.execute(select(SalonMember).where(SalonMember.user_id == cid))).scalar_one_or_none() is None


async def test_salon_delete_with_favorite_ok(client, db_session):
    """Удаление салона с избранным сохраняет историю и не даёт 500."""
    from app.models.models import Favorite

    salon_id = await _make_salon(db_session)
    async with db_session() as db:
        u = User(phone="+79993330060", full_name="Фан",
                 hashed_password=get_password_hash("Pass1"), role=UserRole.CLIENT)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        db.add(Favorite(user_id=u.id, salon_id=salon_id))
        await db.commit()

    await _senior_admin_login(client, db_session)
    r = await client.post(f"/api/v1/admin/salons/{salon_id}/delete")
    assert r.status_code == 302 and "ok=" in r.headers["location"], r.headers["location"]
    async with db_session() as db:
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        assert salon.is_deleted is True and salon.is_active is False
        assert (await db.execute(select(Favorite).where(Favorite.salon_id == salon_id))).scalar_one_or_none() is not None
