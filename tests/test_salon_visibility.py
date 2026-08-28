"""Почему салон не виден в каталоге — и знает ли об этом владелец.

Живой случай: салон прошёл модерацию, был опубликован и всё равно не появился
в списке. Аудит показал мягкое удаление через секунду после одобрения —
is_active=False. Панель владельцу об этом не говорила ни слова.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import get_password_hash
from app.web.pages.legal import LEGAL_VERSION
from app.models.models import (
    OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember, SalonModerationStatus,
    SalonRole, SalonSubscriptionStatus, User, UserRole,
)


async def _salon(db, **kw):
    owner = User(phone=kw.pop("phone"), full_name="В",
                 hashed_password=get_password_hash("Bizpass1"),
                 role=UserRole.BUSINESS, is_active=True)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    now = datetime.now(timezone.utc)
    base = dict(
        name="Видимый", address="Т", phone="+70000000800", latitude=1.0, longitude=1.0,
        city="Томск", is_active=True, creator_id=owner.id,
        moderation_status=SalonModerationStatus.APPROVED,
        business_tier="lite", subscription_status=SalonSubscriptionStatus.ACTIVE,
        published_at=now,
    )
    base.update(kw)
    salon = Salon(**base)
    db.add(salon)
    await db.commit()
    await db.refresh(salon)
    db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                       is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS),
                       is_active=True))
    await db.commit()
    salon.access_until = now + timedelta(days=30)
    await db.commit()
    return salon, owner


async def test_deleted_salon_disappears_from_catalog(client, db_session):
    """Мягко удалённый салон не должен попадать в каталог — это и есть смысл
    удаления, проверяем, что условие не потерялось."""
    async with db_session() as db:
        alive, _ = await _salon(db, phone="+79990007001", name="Живой салон")
        dead, _ = await _salon(db, phone="+79990007002", name="Удалённый салон",
                               is_active=False)

    r = await client.get("/salons")
    assert r.status_code == 200
    assert "Живой салон" in r.text
    assert "Удалённый салон" not in r.text


async def test_owner_of_deleted_salon_is_told_why(client, db_session):
    """Раньше владелец видел обычную панель и не понимал, куда делся салон."""
    async with db_session() as db:
        salon, owner = await _salon(db, phone="+79990007003", is_active=False)
        salon_id, phone = salon.id, owner.phone

    r = await client.post("/api/v1/auth/login",
                          json={"phone": phone, "password": "Bizpass1"})
    assert r.status_code == 200
    client.cookies.set("access_token", r.json()["access_token"])

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert r.status_code == 200
    assert "Салон удалён" in r.text
    assert "hello@rrumi.ru" in r.text


async def test_creating_a_salon_does_not_demote_an_admin(client, db_session):
    """Модератор, заведя себе салон, молча терял доступ в админку: роль одна
    на пользователя, и её перезаписывали на BUSINESS."""
    async with db_session() as db:
        admin = User(phone="+79990007004", full_name="Модератор",
                     hashed_password=get_password_hash("Adminp1"),
                     role=UserRole.ADMIN, is_senior_admin=True, is_active=True)
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        admin_id = admin.id

    r = await client.post("/api/v1/auth/login",
                          json={"phone": "+79990007004", "password": "Adminp1"})
    assert r.status_code == 200
    client.cookies.set("access_token", r.json()["access_token"])

    # Именно этот путь (оформление салона с /business/checkout) повышает роль
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Салон модератора", "phone": "+70000000801",
        "offer_accepted": "1", "pd_consent": "1", "consent_version": LEGAL_VERSION,
    }, follow_redirects=False)
    assert r.status_code in (200, 201, 302), r.text

    async with db_session() as db:
        # Салон обязан реально создаться — иначе проверка роли ничего не значит
        created = (await db.execute(
            select(Salon).where(Salon.name == "Салон модератора")
        )).scalar_one_or_none()
        assert created is not None, f"салон не создан, ответ {r.status_code}: {r.headers.get('location')}"
        again = await db.get(User, admin_id)
        assert again.role == UserRole.ADMIN, "роль администратора перезаписана"
        assert again.is_senior_admin is True
