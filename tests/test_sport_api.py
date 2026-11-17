from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import settings
from app.models.models import ConsentDocument, User, UserConsent
from app.models.sport import SportBooking, SportOrganization, SportTraining
from app.web.pages.legal import LEGAL_VERSION


async def _seed_organization(db_session, booking_date):
    weekday = (booking_date.weekday() + 1) % 7
    async with db_session() as db:
        organization = SportOrganization(
            slug="test-sport-club",
            name="Тестовый клуб",
            city="Томск",
            description="",
            is_published=True,
        )
        db.add(organization)
        await db.flush()
        training = SportTraining(
            organization_id=organization.id,
            code="test-session",
            weekdays=[weekday],
            start_time=time(23, 0),
            end_time=time(23, 59),
            coach="Тренер",
            gym="Тестовый зал",
            discipline="Дзю-дзютцу",
            is_active=True,
        )
        db.add(training)
        await db.commit()
        return training.code


def _booking_date():
    today = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date()
    return today + timedelta(days=2)


def _booking_payload(booking_date, **overrides):
    payload = {
        "name": "Тестовый клиент",
        "phone": "+79990001122",
        "kind": "Пробное",
        "participant": "self",
        "training_id": "test-session",
        "booking_date": booking_date.isoformat(),
        "gym": "Тестовый зал",
        "discipline": "Дзю-дзютцу",
        "pd_consent": True,
        "consent_version": LEGAL_VERSION,
    }
    payload.update(overrides)
    return payload


async def test_sport_booking_creates_guest_and_records_consent(client, db_session):
    booking_date = _booking_date()
    await _seed_organization(db_session, booking_date)

    response = await client.post(
        "/api/v1/sport/organizations/test-sport-club/bookings",
        json=_booking_payload(booking_date),
    )
    assert response.status_code == 201, response.text

    async with db_session() as db:
        booking = await db.get(SportBooking, response.json()["booking_id"])
        user = (
            await db.execute(select(User).where(User.phone == "+79990001122"))
        ).scalar_one()
        consent = (
            await db.execute(
                select(UserConsent).where(
                    UserConsent.phone == "+79990001122",
                    UserConsent.document == ConsentDocument.PD_CONSENT,
                )
            )
        ).scalar_one()

        assert booking.status == "pending"
        assert booking.training_id is not None
        assert user.is_guest is True
        assert consent.version == LEGAL_VERSION
        assert consent.source == "sport_guest_booking"


async def test_sport_booking_rejects_stale_consent_without_creating_user(client, db_session):
    booking_date = _booking_date()
    await _seed_organization(db_session, booking_date)

    response = await client.post(
        "/api/v1/sport/organizations/test-sport-club/bookings",
        json=_booking_payload(booking_date, consent_version="outdated"),
    )
    assert response.status_code == 400

    async with db_session() as db:
        assert (
            await db.execute(select(User).where(User.phone == "+79990001122"))
        ).scalar_one_or_none() is None
