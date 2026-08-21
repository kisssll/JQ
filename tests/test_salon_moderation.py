"""Модерация регистрации бизнеса: заявка pending → одобрение/отклонение,
гейт публичного показа и записи, обязательная оферта."""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonModerationStatus, Master, Service,
)
from tests.conftest import register_user

ADMIN_PHONE = "+79995551001"


async def _mk_user(db_session, phone, role=UserRole.BUSINESS, pw="Bizpass1"):
    async with db_session() as db:
        u = User(phone=phone, full_name="Ю", hashed_password=get_password_hash(pw), role=role)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _mk_salon(db_session, status, creator_id=None, name="Салон"):
    async with db_session() as db:
        s = Salon(name=name, description="", address="Томск, ул. 1",
                  latitude=56.5, longitude=84.9, phone="+79990000000",
                  rating=0.0, reviews_count=0, is_active=True,
                  moderation_status=status, creator_id=creator_id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def _mk_master_service(db_session, salon_id, user_id):
    async with db_session() as db:
        m = Master(user_id=user_id, salon_id=salon_id, specialization="мастер")
        db.add(m)
        await db.commit()
        await db.refresh(m)
        svc = Service(master_id=m.id, name="Стрижка", price=1000, duration_minutes=30)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)
        return m.id, svc.id


async def _login(client, phone, pw):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": pw})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])


# ── Публичный гейт ───────────────────────────────────────────────────────────

async def test_pending_salon_hidden_from_catalog(client, db_session):
    # Публичный каталог — серверная страница /salons (API /api/v1/salons
    # перехватывается web catch-all — см. заметку в PR).
    await _mk_salon(db_session, SalonModerationStatus.APPROVED, name="ОдобренZZ")
    await _mk_salon(db_session, SalonModerationStatus.PENDING, name="ЗаявкаZZ")
    html = (await client.get("/salons")).text
    assert "ОдобренZZ" in html
    assert "ЗаявкаZZ" not in html


async def test_pending_salon_detail_hidden(client, db_session):
    pend = await _mk_salon(db_session, SalonModerationStatus.PENDING, name="СкрытыйZZ")
    r = await client.get(f"/salons/{pend}")
    assert "не найден" in r.text.lower()


# ── Гейт записи ──────────────────────────────────────────────────────────────

async def test_booking_blocked_for_pending_salon(client, db_session):
    master_user = await _mk_user(db_session, "+79995551011", role=UserRole.CLIENT)
    salon_id = await _mk_salon(db_session, SalonModerationStatus.PENDING)
    master_id, service_id = await _mk_master_service(db_session, salon_id, master_user)

    data = await register_user(client, "+79995551012")
    client.cookies.set("access_token", data["access_token"])
    start = (datetime.now() + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    r = await client.post("/api/v1/bookings", json={
        "master_id": master_id, "service_id": service_id, "start_time": start.isoformat(),
    })
    assert r.status_code == 403, r.text


# ── Регистрация: обязательная оферта + статус pending ────────────────────────

async def test_registration_requires_offer(client, db_session):
    data = await register_user(client, "+79995551020")
    client.cookies.set("access_token", data["access_token"])
    # без согласия с офертой — 400
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "Без оферты", "address": "Томск", "phone": "+79991112233",
    })
    assert r.status_code == 400
    # с офертой — создаётся ЗАЯВКА (pending), фиксируется offer_accepted_at
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "С офертой", "address": "Томск", "city": "Томск", "phone": "+79991112233",
        "offer_accepted": "1", "pd_consent": "1",
    })
    assert r.status_code in (302, 303)
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.name == "С офертой"))).scalar_one()
        assert s.moderation_status == SalonModerationStatus.PENDING
        assert s.offer_accepted_at is not None


# ── Админ-модерация ──────────────────────────────────────────────────────────

async def test_admin_approve_does_not_auto_publish(client, db_session):
    # Одобрение админом больше НЕ выводит салон в каталог само по себе —
    # published_at остаётся NULL, пока владелец не нажмёт «Опубликовать».
    await _mk_user(db_session, ADMIN_PHONE, role=UserRole.ADMIN, pw="Adminpass1")
    sid = await _mk_salon(db_session, SalonModerationStatus.PENDING, name="КОдобрениюZZ")
    await _login(client, ADMIN_PHONE, "Adminpass1")

    r = await client.post(f"/api/v1/admin/salons/{sid}/approve")
    assert r.status_code == 302 and "ok=" in r.headers["location"]
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.moderation_status == SalonModerationStatus.APPROVED
        assert s.is_active is True
        assert s.published_at is None  # ещё не опубликован
    # в каталоге пока НЕ виден — ждёт публикации владельцем
    assert "КОдобрениюZZ" not in (await client.get("/salons")).text


async def test_checkout_apply_requires_login(client):
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "X", "phone": "+70000000000", "offer_accepted": "1", "pd_consent": "1"})
    assert r.status_code == 401


async def test_checkout_apply_creates_pending_and_upgrades_role(client, db_session):
    data = await register_user(client, "+79995551030")  # регистрируется как CLIENT
    client.cookies.set("access_token", data["access_token"])
    # без согласия — 400
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Нео", "phone": "+79990000001"})
    assert r.status_code == 400
    # с согласием — заявка pending + роль BUSINESS + владелец
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "НовыйБиз", "phone": "+79990000001",
        "offer_accepted": "1", "pd_consent": "1", "plan": "business"})
    assert r.status_code == 200, r.text
    assert "/business/dashboard" in r.json()["redirect"]
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.name == "НовыйБиз"))).scalar_one()
        assert s.moderation_status == SalonModerationStatus.PENDING
        assert s.offer_accepted_at is not None
        assert s.creator_id is not None
        u = (await db.execute(select(User).where(User.phone == "+79995551030"))).scalar_one()
        assert u.role == UserRole.BUSINESS


async def test_admin_reject_stores_reason(client, db_session):
    await _mk_user(db_session, ADMIN_PHONE, role=UserRole.ADMIN, pw="Adminpass1")
    sid = await _mk_salon(db_session, SalonModerationStatus.PENDING, name="К отклонению")
    await _login(client, ADMIN_PHONE, "Adminpass1")

    r = await client.post(f"/api/v1/admin/salons/{sid}/reject", data={"reason": "нет договора"})
    assert r.status_code == 302
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.moderation_status == SalonModerationStatus.REJECTED
        assert s.rejection_reason == "нет договора"
        assert s.is_active is False
