# tests/test_role_escalation.py
"""Владелец салона, добавляя админа, НЕ должен делать его сайт-модератором.
Салонный ADMIN = SalonMember(ADMIN) + права салона; сайт-роль остаётся CLIENT."""
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
)
from app.schemas.user import try_normalize_phone


async def test_owner_adding_admin_does_not_grant_site_moderator(client, db_session):
    async with db_session() as db:
        salon = Salon(name="S", address="a", phone="+70000000200",
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      moderation_status=SalonModerationStatus.APPROVED, is_active=True)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        owner = User(phone="+79993330200", full_name="Owner",
                     hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True,
                           permissions={"manage_admins": True, "manage_owners": True},
                           is_active=True))
        await db.commit()
        salon_id = salon.id

    # логин владельца (cookie)
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": "+79993330200", "password": "Testpass1"})
    assert r.status_code == 302

    # владелец добавляет админа салона
    new_phone = "+79993330201"
    r = await client.post("/api/v1/business/staff/add-web",
                          data={"phone": new_phone, "full_name": "Салон-Админ",
                                "role": "admin", "salon_id": salon_id})
    assert r.status_code == 302, r.text

    async with db_session() as db:
        u = (await db.execute(select(User).where(User.phone == try_normalize_phone(new_phone)))).scalar_one()
        # КЛЮЧЕВОЕ: сайт-роль НЕ повышена, старшим модератором НЕ стал
        assert u.role == UserRole.CLIENT, f"сайт-роль эскалировала: {u.role}"
        assert u.is_senior_admin is False, "добавленный получил старшего модератора!"
        # салонная роль — ADMIN (в пределах салона)
        m = (await db.execute(select(SalonMember).where(
            SalonMember.user_id == u.id, SalonMember.salon_id == salon_id))).scalar_one()
        assert m.role == SalonRole.ADMIN
