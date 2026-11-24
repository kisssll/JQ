import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.models import AdminAudit, Salon, User, UserRole
from app.models.sport import SportOrganization
from app.services.sport_tariffs import (
    SPORT_ADDITIONAL_VENUE_PRICE,
    SPORT_COACH_MONTHLY_PRICE,
    SPORT_GYM_BASE_MONTHLY_PRICE,
    calculate_sport_monthly_price,
)


def test_calculate_sport_monthly_price():
    # 1. Coach price: 399 ₽ (same as single master in beauty)
    assert calculate_sport_monthly_price(is_coach=True) == SPORT_COACH_MONTHLY_PRICE
    assert calculate_sport_monthly_price(is_coach=True) == 399

    # 2. 1 Gym: 3 500 ₽
    assert calculate_sport_monthly_price(venues_count=1, is_coach=False) == SPORT_GYM_BASE_MONTHLY_PRICE
    assert calculate_sport_monthly_price(venues_count=1, is_coach=False) == 3500

    # 3. 2 Gyms: 3 500 + 2 500 = 6 000 ₽
    assert calculate_sport_monthly_price(venues_count=2, is_coach=False) == 6000

    # 4. 3 Gyms: 3 500 + 2 * 2 500 = 8 500 ₽
    assert calculate_sport_monthly_price(venues_count=3, is_coach=False) == 8500

    # 5. 5 Gyms: 3 500 + 4 * 2 500 = 13 500 ₽
    assert calculate_sport_monthly_price(venues_count=5, is_coach=False) == 13500

    # 6. Custom offer overrides platform calculation
    assert calculate_sport_monthly_price(venues_count=5, custom_price=2900) == 2900
    assert calculate_sport_monthly_price(is_coach=True, custom_price=0) == 0


async def _auth_admin(db_session, client, is_senior=True):
    async with db_session() as db:
        admin = User(
            phone="+79990001122",
            full_name="Главный Администратор",
            hashed_password=get_password_hash("Adminpass1"),
            role=UserRole.ADMIN,
            is_senior_admin=is_senior,
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        admin_id = admin.id
    token = create_access_token(admin_id)
    client.cookies.set("access_token", token)
    return admin_id


async def test_admin_salon_custom_offer(client, db_session):
    admin_id = await _auth_admin(db_session, client)

    # 1. Create a test salon
    async with db_session() as db:
        salon = Salon(
            name="Салон Элит",
            city="Москва",
            address="ул. Тверская, 1",
            latitude=55.751244,
            longitude=37.618423,
            phone="+79991112233",
            creator_id=admin_id,
            is_active=True,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        salon_id = salon.id

    # 2. Post custom offer from admin panel
    resp = await client.post(
        f"/api/v1/admin/salons/{salon_id}/custom-offer",
        data={"price": "2700", "notes": "Спецусловия первого года"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # 3. Verify in database
    async with db_session() as db:
        updated = await db.scalar(select(Salon).where(Salon.id == salon_id))
        assert updated.custom_subscription_price == 2700
        assert updated.custom_subscription_notes == "Спецусловия первого года"

        # Check audit log
        audit = await db.scalar(
            select(AdminAudit).where(
                AdminAudit.action == "set_custom_offer",
                AdminAudit.target_type == "salon",
                AdminAudit.target_id == salon_id,
            )
        )
        assert audit is not None
        assert "2700" in audit.detail

    # 4. Reset custom offer back to standard
    reset_resp = await client.post(
        f"/api/v1/admin/salons/{salon_id}/custom-offer",
        data={"reset": "1"},
        follow_redirects=False,
    )
    assert reset_resp.status_code == 302

    async with db_session() as db:
        reloaded = await db.scalar(select(Salon).where(Salon.id == salon_id))
        assert reloaded.custom_subscription_price is None
        assert reloaded.custom_subscription_notes is None


async def test_admin_sport_organization_custom_offer_and_access(client, db_session):
    admin_id = await _auth_admin(db_session, client)

    # 1. Create a sport organization
    async with db_session() as db:
        org = SportOrganization(
            slug="titan-sport-offer",
            name="Клуб Титан",
            city="Москва",
            creator_id=admin_id,
            is_published=True,
            moderation_status="approved",
        )
        db.add(org)
        await db.commit()
        await db.refresh(org)
        org_id = org.id

    # 2. Set custom offer for sports club
    resp = await client.post(
        f"/api/v1/admin/sport/organizations/{org_id}/custom-offer",
        data={"price": "4500", "notes": "Спецусловия для сети клубов"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    async with db_session() as db:
        updated = await db.scalar(select(SportOrganization).where(SportOrganization.id == org_id))
        assert updated.custom_subscription_price == 4500
        assert updated.custom_subscription_notes == "Спецусловия для сети клубов"

    # 3. Grant trial
    trial_resp = await client.post(
        f"/api/v1/admin/sport/organizations/{org_id}/grant-trial",
        data={"days": "45"},
        follow_redirects=False,
    )
    assert trial_resp.status_code == 302

    async with db_session() as db:
        trial_org = await db.scalar(select(SportOrganization).where(SportOrganization.id == org_id))
        assert trial_org.subscription_status == "trialing"
        assert trial_org.subscription_expires_at is not None

    # 4. Grant access (months)
    access_resp = await client.post(
        f"/api/v1/admin/sport/organizations/{org_id}/grant-access",
        data={"months": "3"},
        follow_redirects=False,
    )
    assert access_resp.status_code == 302

    async with db_session() as db:
        access_org = await db.scalar(select(SportOrganization).where(SportOrganization.id == org_id))
        assert access_org.subscription_status == "active"

    # 5. Reset custom offer
    reset_resp = await client.post(
        f"/api/v1/admin/sport/organizations/{org_id}/custom-offer",
        data={"reset": "1"},
        follow_redirects=False,
    )
    assert reset_resp.status_code == 302

    async with db_session() as db:
        reset_org = await db.scalar(select(SportOrganization).where(SportOrganization.id == org_id))
        assert reset_org.custom_subscription_price is None
        assert reset_org.custom_subscription_notes is None
