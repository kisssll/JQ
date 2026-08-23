"""Публикация салона после модерации.

Одобрение админом больше не выводит салон в каталог автоматически: появляется
состояние «одобрен, но не опубликован» (published_at IS NULL), из которого
владелец публикует салон сам кнопкой в шапке панели. До публикации салон
полностью непубличен (нет в каталоге/поиске, карточка 404, запись закрыта).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
    SalonSubscriptionStatus, Master, Service,
)
from tests.conftest import register_user


async def _mk_owner(db_session, phone, pw="Bizpass1"):
    async with db_session() as db:
        u = User(phone=phone, full_name="Вл", hashed_password=get_password_hash(pw),
                 role=UserRole.BUSINESS)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _mk_approved_unpublished(db_session, owner_id, name="Салон",
                                   subscription_status=SalonSubscriptionStatus.ACTIVE):
    """Салон в состоянии «прошёл модерацию, но не опубликован».

    Создаём PENDING, затем UPDATE'ом переводим в APPROVED — ровно как это
    делает админ-эндпоинт: published_at при этом остаётся NULL (grandfather-
    листенер conftest срабатывает только на INSERT сразу-approved).

    subscription_status по умолчанию ACTIVE: после интеграции биллинга
    публикация закрыта, пока у салона не выбран тариф (subscription_status != none),
    поэтому «готовый к публикации» салон должен иметь активную подписку.
    """
    async with db_session() as db:
        s = Salon(name=name, description="", address="Томск, ул. 2",
                  latitude=56.5, longitude=84.9, phone="+79990000001",
                  rating=0.0, reviews_count=0, is_active=True,
                  subscription_status=subscription_status,
                  # Живая подписка = открытый доступ: без access_until салон не
                  # попадёт в каталог (см. services/subscription.py).
                  access_until=(datetime.now(timezone.utc) + timedelta(days=30)
                                if subscription_status != SalonSubscriptionStatus.NONE else None),
                  moderation_status=SalonModerationStatus.PENDING, creator_id=owner_id)
        db.add(s)
        await db.commit()
        db.add(SalonMember(salon_id=s.id, user_id=owner_id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        s.moderation_status = SalonModerationStatus.APPROVED
        await db.commit()
        await db.refresh(s)
        assert s.published_at is None
        return s.id


async def _login(client, phone, pw="Bizpass1"):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": pw})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])


# ── Непубличность до публикации ──────────────────────────────────────────────

async def test_approved_unpublished_hidden_from_catalog(client, db_session):
    owner = await _mk_owner(db_session, "+79995552001")
    await _mk_approved_unpublished(db_session, owner, name="НеОпубликованZZ")
    html = (await client.get("/salons")).text
    assert "НеОпубликованZZ" not in html


async def test_approved_unpublished_detail_404(client, db_session):
    owner = await _mk_owner(db_session, "+79995552002")
    sid = await _mk_approved_unpublished(db_session, owner, name="СкрытыйZZ")
    r = await client.get(f"/salons/{sid}")
    assert "не найден" in r.text.lower()


async def test_booking_blocked_until_published(client, db_session):
    owner = await _mk_owner(db_session, "+79995552003")
    sid = await _mk_approved_unpublished(db_session, owner)
    async with db_session() as db:
        m = Master(user_id=owner, salon_id=sid, specialization="мастер")
        db.add(m)
        await db.commit()
        await db.refresh(m)
        svc = Service(master_id=m.id, name="Стрижка", price=1000, duration_minutes=30)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)
        master_id, service_id = m.id, svc.id

    data = await register_user(client, "+79995552004")
    client.cookies.set("access_token", data["access_token"])
    start = (datetime.now() + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    r = await client.post("/api/v1/bookings", json={
        "master_id": master_id, "service_id": service_id, "start_time": start.isoformat(),
    })
    assert r.status_code == 403, r.text


# ── Публикация владельцем ────────────────────────────────────────────────────

async def test_owner_publishes_makes_public(client, db_session):
    owner = await _mk_owner(db_session, "+79995552010")
    sid = await _mk_approved_unpublished(db_session, owner, name="ПубликуемыйZZ",
                                          subscription_status=SalonSubscriptionStatus.ACTIVE)
    await _login(client, "+79995552010")

    r = await client.post(f"/api/v1/business/my-salon/publish?salon_id={sid}")
    assert r.status_code == 200, r.text
    assert r.json()["published"] is True
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.published_at is not None
    # теперь виден в каталоге
    assert "ПубликуемыйZZ" in (await client.get("/salons")).text


async def test_publish_is_idempotent(client, db_session):
    owner = await _mk_owner(db_session, "+79995552011")
    sid = await _mk_approved_unpublished(db_session, owner,
                                          subscription_status=SalonSubscriptionStatus.ACTIVE)
    await _login(client, "+79995552011")

    r1 = await client.post(f"/api/v1/business/my-salon/publish?salon_id={sid}")
    assert r1.status_code == 200
    first = r1.json()["published_at"]
    r2 = await client.post(f"/api/v1/business/my-salon/publish?salon_id={sid}")
    assert r2.status_code == 200
    # повторная публикация не сдвигает отметку времени
    assert r2.json()["published_at"] == first


async def test_publish_blocked_without_tariff(client, db_session):
    # После интеграции биллинга: салон без выбранного тарифа
    # (subscription_status=none) опубликовать нельзя — 409, published_at не ставится.
    owner = await _mk_owner(db_session, "+79995552015")
    sid = await _mk_approved_unpublished(
        db_session, owner, name="БезТарифаZZ",
        subscription_status=SalonSubscriptionStatus.NONE,
    )
    await _login(client, "+79995552015")

    r = await client.post(f"/api/v1/business/my-salon/publish?salon_id={sid}")
    assert r.status_code == 409, r.text
    assert "тариф" in r.json()["detail"].lower()
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.published_at is None
    assert "БезТарифаZZ" not in (await client.get("/salons")).text


async def test_publish_requires_approved(client, db_session):
    owner = await _mk_owner(db_session, "+79995552012")
    async with db_session() as db:
        s = Salon(name="Пендинг", description="", address="Т", latitude=1.0, longitude=1.0,
                  phone="+79990000009", is_active=True,
                  moderation_status=SalonModerationStatus.PENDING, creator_id=owner)
        db.add(s)
        await db.commit()
        db.add(SalonMember(salon_id=s.id, user_id=owner, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        await db.commit()
        sid = s.id
    await _login(client, "+79995552012")

    r = await client.post(f"/api/v1/business/my-salon/publish?salon_id={sid}")
    assert r.status_code == 409, r.text


async def test_publish_requires_subscription(client, db_session):
    owner = await _mk_owner(db_session, "+79995552015")
    # Хелпер по умолчанию даёт салону живую подписку (иначе он невидим в
    # каталоге) — здесь тариф нужен именно отсутствующим.
    sid = await _mk_approved_unpublished(
        db_session, owner, subscription_status=SalonSubscriptionStatus.NONE,
    )
    await _login(client, "+79995552015")

    r = await client.post(f"/api/v1/business/my-salon/publish?salon_id={sid}")
    assert r.status_code == 409, r.text
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.published_at is None


async def test_publish_requires_permission(client, db_session):
    owner = await _mk_owner(db_session, "+79995552013")
    sid = await _mk_approved_unpublished(db_session, owner)
    # посторонний пользователь без членства в салоне
    data = await register_user(client, "+79995552014")
    client.cookies.set("access_token", data["access_token"])

    r = await client.post(f"/api/v1/business/my-salon/publish?salon_id={sid}")
    assert r.status_code in (403, 404), r.text
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.published_at is None  # не опубликован посторонним


# ── Уведомление при одобрении зовёт опубликовать ─────────────────────────────

async def test_approve_notification_prompts_publish(client, db_session, monkeypatch):
    import app.core.worker as worker_mod

    jobs = []

    class _FakePool:
        async def enqueue_job(self, name, *args, **kwargs):
            jobs.append((name, args))

    async def _fake_pool():
        return _FakePool()

    monkeypatch.setattr(worker_mod, "get_arq_pool", _fake_pool)

    # владелец с почтой — чтобы ушла email-джоба
    async with db_session() as db:
        owner = User(phone="+79995552020", full_name="Вл", email="owner@example.com",
                     hashed_password=get_password_hash("Bizpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        s = Salon(name="КУведомлению", description="", address="Т", latitude=1.0, longitude=1.0,
                  phone="+79990000010", is_active=True,
                  moderation_status=SalonModerationStatus.PENDING, creator_id=owner.id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        sid = s.id

    admin_phone = "+79995552021"
    async with db_session() as db:
        db.add(User(phone=admin_phone, full_name="А",
                    hashed_password=get_password_hash("Adminpass1"), role=UserRole.ADMIN))
        await db.commit()
    await _login(client, admin_phone, "Adminpass1")

    r = await client.post(f"/api/v1/admin/salons/{sid}/approve")
    assert r.status_code == 302

    email_jobs = [j for j in jobs if j[0] == "send_email"]
    assert email_jobs, f"ожидали email-уведомление, jobs={jobs}"
    # send_email(to, subject, body)
    _, (to, subject, body) = email_jobs[0]
    assert to == "owner@example.com"
    assert "модерац" in (subject + body).lower()
    assert "опубликов" in body.lower()
