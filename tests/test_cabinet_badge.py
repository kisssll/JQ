"""Бейдж подписки в кабинете (решение 0015, п. 3).

У владельца — тариф его салона, у модели — её тариф, у клиента — ничего:
клиентского платного тарифа нет, и подпись «Про» у человека, который ничего
не покупал, была бы ложным обещанием. Кончился тариф — так и пишем.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import get_password_hash
from app.models.models import (
    OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember, SalonModerationStatus, SalonRole,
    SalonSubscriptionStatus as St, SubscriptionTier, User, UserRole,
)
from app.services.cabinet_badge import badge_text

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
SOON = NOW + timedelta(days=10)
PAST = NOW - timedelta(days=1)


@pytest.mark.parametrize("status, until, expected", [
    (St.NONE, None, ""),
    (St.ACTIVE, SOON, "Салон · Лайт до 06.11.2026"),
    (St.CANCELED, SOON, "Салон · Лайт до 06.11.2026"),
    (St.TRIALING, SOON, "Салон · пробный до 06.11.2026"),
    (St.PAST_DUE, SOON, "Салон · платёж не прошёл"),
    (St.ACTIVE, PAST, "Салон · тариф закончился"),
    (St.CANCELED, None, "Салон · тариф закончился"),
    (St.NONE, NOW + timedelta(days=30 * 365), "Салон · доступ открыт"),
])
def test_badge_text(status, until, expected):
    assert badge_text("Салон", status, "Лайт", until, now=NOW) == expected


def test_expired_badge_never_names_the_plan():
    assert "Про" not in badge_text("Модель", St.ACTIVE, "Про", PAST, now=NOW)


async def _login(client, phone):
    r = await client.post(
        "/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"},
    )
    assert r.status_code == 302, r.text


async def _user(db_session, phone, **kw):
    async with db_session() as db:
        u = User(phone=phone, full_name="Тест Тестов", is_active=True,
                 hashed_password=get_password_hash("Testpass1"), **kw)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


CABINET = ("/profile", "/bookings", "/favorites")


async def test_client_has_no_badge(client, db_session):
    await _user(db_session, "+79997770001", role=UserRole.CLIENT)
    await _login(client, "+79997770001")
    for path in CABINET:
        r = await client.get(path)
        assert r.status_code == 200
        assert 'class="acc-badge"' not in r.text, f"{path}: у клиента нет тарифа"


@pytest.mark.parametrize("until, shown, hidden", [
    (datetime.now(timezone.utc) + timedelta(days=10), "Салон · Бизнес до", "закончился"),
    (datetime.now(timezone.utc) - timedelta(days=1), "Салон · тариф закончился", "Бизнес до"),
])
async def test_owner_sees_the_salon_tariff(client, db_session, until, shown, hidden):
    phone = "+79997770002" if "Бизнес" in shown else "+79997770003"
    owner = await _user(db_session, phone, role=UserRole.BUSINESS)
    async with db_session() as db:
        s = Salon(
            name="С тарифом", address="Томск", phone="+73822000111",
            latitude=56.4, longitude=84.9, timezone="Asia/Tomsk",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, business_tier="business",
            subscription_status=St.ACTIVE, access_until=until,
        )
        db.add(s)
        await db.commit()
        db.add(SalonMember(
            salon_id=s.id, user_id=owner.id, role=SalonRole.OWNER, is_creator=True,
            permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        await db.commit()
    await _login(client, phone)
    for path in CABINET:
        r = await client.get(path)
        assert shown in r.text, path
        assert hidden not in r.text, path


async def test_model_sees_own_tariff_and_not_pro_when_expired(client, db_session):
    await _user(db_session, "+79997770004", role=UserRole.CLIENT, is_model=True,
                subscription_tier=SubscriptionTier.PRO, subscription_status=St.ACTIVE,
                access_until=datetime.now(timezone.utc) - timedelta(hours=1))
    await _login(client, "+79997770004")
    r = await client.get("/profile")
    assert "Модель · тариф закончился" in r.text
    assert "· Про" not in r.text


async def test_model_with_a_live_tariff_sees_its_name(client, db_session):
    await _user(db_session, "+79997770005", role=UserRole.CLIENT, is_model=True,
                subscription_tier=SubscriptionTier.PRO, subscription_status=St.ACTIVE,
                access_until=datetime.now(timezone.utc) + timedelta(days=5))
    await _login(client, "+79997770005")
    r = await client.get("/favorites")
    assert "Модель · Про до" in r.text


async def test_panel_header_shows_the_real_tariff(client, db_session):
    """В шапке панели годами висело «Бизнес PRO» при любом тарифе — у салона
    с кончившейся подпиской прямо над полосой «подписка не оплачена»."""
    from datetime import datetime, timedelta, timezone

    from app.models.models import (
        OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember, SalonModerationStatus,
        SalonRole, SalonSubscriptionStatus, User, UserRole,
    )
    from app.core.security import get_password_hash

    async with db_session() as db:
        owner = User(phone="+79993330077", full_name="Хозяин Просрочки",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        salon = Salon(name="Просроченный", description="", address="Томск, ул. 2",
                      latitude=56.5, longitude=84.9, phone="+79990002222", city="Томск",
                      is_active=True, creator_id=owner.id,
                      moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.TRIALING,
                      access_until=datetime.now(timezone.utc) - timedelta(days=5))
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS),
                           is_active=True))
        await db.commit()

    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": "+79993330077", "password": "Testpass1"})
    assert r.status_code == 302
    r = await client.get("/business/dashboard")
    assert r.status_code == 200
    assert "Бизнес PRO" not in r.text
    assert "тариф закончился" in r.text
