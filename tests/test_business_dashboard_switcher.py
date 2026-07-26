# tests/test_business_dashboard_switcher.py
"""Переключатель между салонами одного владельца в шапке бизнес-панели —
раньше строился (switcher_html), но никогда не вставлялся в HTML (мёртвый
код). Плюс ссылка «Добавить салон», видимая только настоящим владельцам
(is_creator), а не нанятым сотрудникам."""
from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
)


async def _login(client, phone, password="Testpass1"):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": password})
    assert r.status_code == 302, r.text


async def test_switcher_and_add_salon_link_shown_for_owner_with_multiple_salons(client, db_session):
    async with db_session() as db:
        owner = User(phone="+79996660001", full_name="Owner",
                    hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon_a = Salon(name="Салон А", address="a", phone="+70000000400",
                        latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                        moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                        creator_id=owner.id)
        salon_b = Salon(name="Салон Б", address="b", phone="+70000000401",
                        latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                        moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                        creator_id=owner.id)
        db.add_all([salon_a, salon_b])
        await db.commit()
        await db.refresh(salon_a)
        await db.refresh(salon_b)

        db.add(SalonMember(salon_id=salon_a.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        db.add(SalonMember(salon_id=salon_b.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        await db.commit()
        salon_a_id, salon_b_id = salon_a.id, salon_b.id

    await _login(client, "+79996660001")
    r = await client.get("/business/dashboard")
    assert r.status_code == 200
    assert 'class="salon-switcher"' in r.text
    assert "Салон А" in r.text and "Салон Б" in r.text
    assert 'class="salon-switcher-add"' in r.text
    assert 'href="/business/register-salon"' in r.text

    # Переключение на второй салон через ?salon_id=
    r = await client.get(f"/business/dashboard?salon_id={salon_b_id}")
    assert r.status_code == 200
    assert "Салон Б" in r.text


async def test_add_salon_link_hidden_for_hired_admin(client, db_session):
    async with db_session() as db:
        owner = User(phone="+79996660002", full_name="Owner2",
                    hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        admin = User(phone="+79996660003", full_name="Admin2",
                    hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        db.add_all([owner, admin])
        await db.commit()
        await db.refresh(owner)
        await db.refresh(admin)

        salon = Salon(name="Салон В", address="c", phone="+70000000402",
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                      moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                      creator_id=owner.id)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        db.add(SalonMember(salon_id=salon.id, user_id=admin.id, role=SalonRole.ADMIN,
                           is_creator=False, permissions={"manage_salon": True}, is_active=True))
        await db.commit()

    await _login(client, "+79996660003")  # нанятый админ, не создатель
    r = await client.get("/business/dashboard")
    assert r.status_code == 200
    assert 'class="salon-switcher-add"' not in r.text
