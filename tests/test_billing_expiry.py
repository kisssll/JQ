# tests/test_billing_expiry.py
"""14-дневный триал без оплаты: пока не истёк subscription_expires_at, салон
остаётся в каталоге и владелец только видит предупреждение в бизнес-панели
(app.web.pages.business.dashboard) — «оплатите, иначе пропадёт». Как только
expire_unpaid_salons (app/tasks.py, cron) обнаруживает, что срок истёк, а
подписка не ACTIVE, салон скрывается из каталога (is_hidden=True,
hidden_reason="billing"), а баннер меняется на «появится после оплаты».
Оплата (вебхук Т-Кассы) возвращает салон в каталог автоматически.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
    SalonSubscriptionStatus,
)


async def _mk_owner(db_session, phone, pw="Bizpass1"):
    async with db_session() as db:
        u = User(phone=phone, full_name="Владелец", hashed_password=get_password_hash(pw),
                 role=UserRole.BUSINESS)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _mk_published_salon(db_session, owner_id, name, **salon_kwargs):
    """Опубликованный (виден в каталоге) салон с заданным состоянием подписки."""
    async with db_session() as db:
        s = Salon(
            name=name, description="", address="Томск, ул. 1",
            latitude=56.5, longitude=84.9, phone="+79990001234",
            rating=0.0, reviews_count=0, is_active=True,
            moderation_status=SalonModerationStatus.APPROVED,
            published_at=datetime.now(timezone.utc), creator_id=owner_id,
            **salon_kwargs,
        )
        db.add(s)
        await db.commit()
        db.add(SalonMember(salon_id=s.id, user_id=owner_id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True, "manage_tariff": True}, is_active=True))
        await db.commit()
        await db.refresh(s)
        return s.id


async def _login(client, phone, pw="Bizpass1"):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": pw})
    assert r.status_code == 302, r.text


# ── expire_unpaid_salons (cron) ──────────────────────────────────────────────

async def test_expire_hides_salon_whose_trial_ran_out_unpaid(db_session):
    from app.tasks import expire_unpaid_salons

    owner = await _mk_owner(db_session, "+79996661001")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    sid = await _mk_published_salon(
        db_session, owner, "ТриалИстёкZZ",
        subscription_status=SalonSubscriptionStatus.TRIALING,
        trial_ends_at=past, subscription_expires_at=past,
    )

    await expire_unpaid_salons({})

    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.is_hidden is True
        assert s.hidden_reason == "billing"
        assert s.subscription_status == SalonSubscriptionStatus.CANCELED


async def test_expire_hides_past_due_salon_after_grace_period(db_session):
    from app.tasks import expire_unpaid_salons

    owner = await _mk_owner(db_session, "+79996661002")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    sid = await _mk_published_salon(
        db_session, owner, "ГрейсИстёкZZ",
        subscription_status=SalonSubscriptionStatus.PAST_DUE,
        subscription_expires_at=past,
    )

    await expire_unpaid_salons({})

    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.is_hidden is True
        assert s.hidden_reason == "billing"


async def test_expire_leaves_active_trial_untouched(db_session):
    from app.tasks import expire_unpaid_salons

    owner = await _mk_owner(db_session, "+79996661003")
    future = datetime.now(timezone.utc) + timedelta(days=10)
    sid = await _mk_published_salon(
        db_session, owner, "ТриалИдётZZ",
        subscription_status=SalonSubscriptionStatus.TRIALING,
        trial_ends_at=future, subscription_expires_at=future,
    )

    await expire_unpaid_salons({})

    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.is_hidden is False
        assert s.hidden_reason is None
        assert s.subscription_status == SalonSubscriptionStatus.TRIALING


async def test_expire_does_not_touch_manually_hidden_salon(db_session):
    """Владелец сам скрыл салон (is_hidden=True, hidden_reason=None) — задача
    не должна трогать её и переставлять причину на billing."""
    from app.tasks import expire_unpaid_salons

    owner = await _mk_owner(db_session, "+79996661004")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    sid = await _mk_published_salon(
        db_session, owner, "СамСкрылZZ",
        subscription_status=SalonSubscriptionStatus.TRIALING,
        trial_ends_at=past, subscription_expires_at=past,
        is_hidden=True,
    )

    await expire_unpaid_salons({})

    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.is_hidden is True
        assert s.hidden_reason is None  # не подменена причина
        assert s.subscription_status == SalonSubscriptionStatus.TRIALING  # не тронут


async def test_expired_salon_disappears_from_catalog(client, db_session):
    from app.tasks import expire_unpaid_salons

    owner = await _mk_owner(db_session, "+79996661005")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await _mk_published_salon(
        db_session, owner, "ПропадаетZZ",
        subscription_status=SalonSubscriptionStatus.TRIALING,
        trial_ends_at=past, subscription_expires_at=past,
    )
    assert "ПропадаетZZ" in (await client.get("/salons")).text

    await expire_unpaid_salons({})

    assert "ПропадаетZZ" not in (await client.get("/salons")).text


# ── Баннеры в бизнес-панели ───────────────────────────────────────────────────

async def test_dashboard_shows_trial_countdown_banner(client, db_session):
    owner = await _mk_owner(db_session, "+79996661010")
    trial_end = datetime.now(timezone.utc) + timedelta(days=5)
    sid = await _mk_published_salon(
        db_session, owner, "СкороТриалZZ",
        subscription_status=SalonSubscriptionStatus.TRIALING,
        trial_ends_at=trial_end, subscription_expires_at=trial_end,
    )
    await _login(client, "+79996661010")

    r = await client.get(f"/business/dashboard?salon_id={sid}")
    assert r.status_code == 200
    assert "Идёт бесплатный пробный период" in r.text
    assert "Оплатите подписку" in r.text


async def test_dashboard_shows_past_due_banner(client, db_session):
    owner = await _mk_owner(db_session, "+79996661011")
    sid = await _mk_published_salon(
        db_session, owner, "НеСписалосьZZ",
        subscription_status=SalonSubscriptionStatus.PAST_DUE,
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    await _login(client, "+79996661011")

    r = await client.get(f"/business/dashboard?salon_id={sid}")
    assert r.status_code == 200
    assert "Не удалось списать оплату" in r.text


async def test_dashboard_shows_hidden_by_billing_banner(client, db_session):
    owner = await _mk_owner(db_session, "+79996661012")
    sid = await _mk_published_salon(
        db_session, owner, "СкрытБиллингомZZ",
        subscription_status=SalonSubscriptionStatus.CANCELED,
        subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        is_hidden=True, hidden_reason="billing",
    )
    await _login(client, "+79996661012")

    r = await client.get(f"/business/dashboard?salon_id={sid}")
    assert r.status_code == 200
    assert "Салон скрыт из каталога" in r.text
    assert "снова появится" in r.text


async def test_dashboard_no_billing_banner_when_active(client, db_session):
    owner = await _mk_owner(db_session, "+79996661013")
    sid = await _mk_published_salon(
        db_session, owner, "ВсёОплаченоZZ",
        subscription_status=SalonSubscriptionStatus.ACTIVE,
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=20),
    )
    await _login(client, "+79996661013")

    r = await client.get(f"/business/dashboard?salon_id={sid}")
    assert r.status_code == 200
    assert "Идёт бесплатный пробный период" not in r.text
    assert "Не удалось списать оплату" not in r.text
    assert "Салон скрыт из каталога" not in r.text


# ── Тумблер «скрыть/показать» не должен обходить неоплату ───────────────────

async def test_owner_cannot_unhide_billing_hidden_salon_without_payment(client, db_session):
    owner = await _mk_owner(db_session, "+79996661020")
    sid = await _mk_published_salon(
        db_session, owner, "НеОбойдёшьZZ",
        subscription_status=SalonSubscriptionStatus.CANCELED,
        subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        is_hidden=True, hidden_reason="billing",
    )
    await _login(client, "+79996661020")

    r = await client.post(f"/api/v1/business/my-salon/visibility-toggle?salon_id={sid}")
    assert r.status_code == 409, r.text
    assert "оплатите" in r.json()["detail"].lower()

    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one()
        assert s.is_hidden is True  # не сдвинулось


async def test_owner_can_hide_and_unhide_manually_when_billing_active(client, db_session):
    owner = await _mk_owner(db_session, "+79996661021")
    sid = await _mk_published_salon(
        db_session, owner, "РучноеСкрытиеZZ",
        subscription_status=SalonSubscriptionStatus.ACTIVE,
        subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=20),
    )
    await _login(client, "+79996661021")

    r1 = await client.post(f"/api/v1/business/my-salon/visibility-toggle?salon_id={sid}")
    assert r1.status_code == 200
    assert r1.json()["is_hidden"] is True

    r2 = await client.post(f"/api/v1/business/my-salon/visibility-toggle?salon_id={sid}")
    assert r2.status_code == 200
    assert r2.json()["is_hidden"] is False
