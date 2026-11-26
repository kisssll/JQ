from datetime import datetime, time, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.models import ConsentDocument, User, UserConsent, UserRole
from app.models.sport import (
    SportBooking,
    SportCoach,
    SportDiscipline,
    SportGalleryImage,
    SportGymMember,
    SportMembershipPlan,
    SportOrganization,
    SportTraining,
    SportVenue,
)
from app.schemas.sport import SportTrainingUpdate
from app.web.pages.legal import LEGAL_VERSION
from tests.conftest import register_user


async def _seed_organization(db_session, booking_date, slug="test-sport-club"):
    weekday = (booking_date.weekday() + 1) % 7
    async with db_session() as db:
        organization = SportOrganization(
            slug=slug,
            name="Тестовый клуб",
            city="Томск",
            description="",
            is_published=True,
        )
        db.add(organization)
        await db.flush()
        db.add(SportVenue(
            organization_id=organization.id,
            name="Тестовый зал",
            address="Тестовый зал",
        ))
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


def test_sport_training_schedule_requires_positive_duration():
    with pytest.raises(ValidationError):
        SportTrainingUpdate(
            id="invalid-time",
            days=[1],
            time="19:00",
            end="19:00",
            coach="Тренер",
            gym="Зал",
            discipline="Борьба",
            active=True,
        )


def _booking_date():
    today = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date()
    return today + timedelta(days=2)


def _booking_payload(default_booking_date, **overrides):
    payload = {
        "name": "Тестовый клиент",
        "phone": "+79990001122",
        "kind": "Пробное",
        "participant": "self",
        "training_id": "test-session",
        "booking_date": default_booking_date.isoformat(),
        "gym": "Тестовый зал",
        "discipline": "Дзю-дзютцу",
        "pd_consent": True,
        "statement_consent": True,
        "consent_version": LEGAL_VERSION,
    }
    payload.update(overrides)
    return payload


async def test_sport_booking_creates_guest_and_records_consent(client, db_session):
    booking_date = _booking_date()
    await _seed_organization(db_session, booking_date)

    response = await client.post(
        "/api/v1/sport/organizations/test-sport-club/bookings",
        json=_booking_payload(booking_date, phone="8 (999) 000-11-22", email="parent@example.com",
                              participant="child", child_name="Участник", child_age=10, experience="Начинающий"),
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
        assert booking.client_id == user.id
        assert booking.contact_email == "parent@example.com"
        assert booking.child_name == "Участник"
        assert booking.child_age == 10
        assert booking.requested_date == booking_date
        assert booking.experience == "Начинающий"
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


async def test_sport_booking_requires_participation_statement_consent(client, db_session):
    booking_date = _booking_date()
    await _seed_organization(db_session, booking_date, slug="sparta")

    response = await client.post(
        "/api/v1/sport/organizations/sparta/bookings",
        json=_booking_payload(booking_date, statement_consent=False),
    )

    assert response.status_code == 400
    assert "Необходимо согласие с заявлением участника" in response.text
    async with db_session() as db:
        assert (
            await db.execute(select(User).where(User.phone == "+79990001122"))
        ).scalar_one_or_none() is None


async def test_sport_booking_can_request_a_time_before_schedule_is_published(client, db_session):
    await _seed_organization(db_session, _booking_date())
    response = await client.post(
        "/api/v1/sport/organizations/test-sport-club/bookings",
        json=_booking_payload(
            _booking_date(),
            training_id=None,
            booking_date=None,
            gym="Тестовый зал",
        ),
    )
    assert response.status_code == 201, response.text

    async with db_session() as db:
        booking = await db.get(SportBooking, response.json()["booking_id"])
        assert booking.training_id is None
        assert booking.requested_gym == "Тестовый зал"


async def test_sport_catalog_searches_and_filters_gym_cards(client, db_session):
    await _seed_organization(db_session, _booking_date())
    async with db_session() as db:
        db.add(
            SportOrganization(
                slug="other-city-club",
                name="Другой клуб",
                city="Новосибирск",
                description="Фитнес",
                is_published=True,
            )
        )
        await db.commit()

    response = await client.get(
        "/sport/clubs?q=Тестовый&city=Томск&partial=1"
    )
    assert response.status_code == 200
    assert 'class="r-salon gym-card"' in response.text
    assert 'href="/sport/test-sport-club"' in response.text
    assert "Другой клуб" not in response.text

    home = await client.get("/sport")
    assert home.status_code == 200
    assert 'action="/sport/clubs"' in home.text

    page = await client.get("/sport/clubs")
    assert page.status_code == 200
    assert 'id="gymsFilterForm"' in page.text
    assert 'id="gyms-list"' in page.text


async def test_sport_catalog_reads_gym_content_from_database(client, db_session):
    await _seed_organization(db_session, _booking_date())
    async with db_session() as db:
        organization = (
            await db.execute(
                select(SportOrganization).where(SportOrganization.slug == "test-sport-club")
            )
        ).scalar_one()
        db.add_all([
            SportVenue(
                organization_id=organization.id,
                name="Главный зал",
                address="Тестовая, 1",
                description="Большой зал",
            ),
            SportCoach(
                organization_id=organization.id,
                name="Иван Тренер",
                role="Тренер",
                tags="Главный зал",
                experience="5 лет",
                bio="Тренирует группы",
            ),
            SportDiscipline(
                organization_id=organization.id,
                name="Борьба",
                description="Тренировки",
                level="Для всех",
            ),
            SportMembershipPlan(
                organization_id=organization.id,
                code="monthly",
                name="Месяц",
                price=3500,
                unit="в месяц",
                items=["Занятия по расписанию"],
            ),
            SportGalleryImage(
                organization_id=organization.id,
                image_url="/photos/test.jpg",
                alt_text="Тренировка",
            ),
        ])
        await db.commit()

    response = await client.get("/api/v1/sport/organizations/test-sport-club/catalog")
    assert response.status_code == 200, response.text
    data = response.json()
    main_venue = next(venue for venue in data["venues"] if venue["name"] == "Главный зал")
    assert main_venue["address"] == "Тестовая, 1"
    assert data["coaches"][0]["name"] == "Иван Тренер"
    assert data["disciplines"][0]["key"] == "Борьба"
    assert data["plans"][0]["price"] == 3500
    assert data["gallery"][0]["src"] == "/photos/test.jpg"


async def test_sport_business_application_starts_pending_and_creates_owner_membership(
    client, db_session
):
    await register_user(client, "+79990001001", full_name="Владелец клуба")
    login = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79990001001", "password": "Testpass1"},
    )
    client.cookies.set("access_token", login.json()["access_token"])

    response = await client.post("/api/v1/sport/business/apply", data={
        "name": "Клуб Томск",
        "city": "Томск",
        "address": "Спортивная, 10",
        "phone": "+79990001001",
        "email": "",
        "description": "Клуб для теста",
        "offer_accepted": "1",
        "pd_consent": "1",
        "consent_version": LEGAL_VERSION,
    })
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/sport/business?submitted=")

    async with db_session() as db:
        organization = (
            await db.execute(select(SportOrganization).where(SportOrganization.name == "Клуб Томск"))
        ).scalar_one()
        membership = (
            await db.execute(
                select(SportGymMember).where(
                    SportGymMember.organization_id == organization.id,
                )
            )
        ).scalar_one()
        assert organization.moderation_status == "pending"
        assert organization.is_published is False
        assert membership.role == "owner"
        assert membership.is_creator is True
        assert (
            await db.execute(select(User).where(User.id == organization.creator_id))
        ).scalar_one().role == UserRole.BUSINESS


async def test_admin_can_assign_existing_sport_club_to_owner_by_phone(client, db_session):
    from app.core.security import get_password_hash

    await _seed_organization(db_session, _booking_date())
    async with db_session() as db:
        organization = (
            await db.execute(
                select(SportOrganization).where(SportOrganization.slug == "test-sport-club")
            )
        ).scalar_one()
        owner = User(
            phone="+79990001005",
            full_name="Владелец Спарты",
            hashed_password=get_password_hash("Testpass1"),
            role=UserRole.CLIENT,
        )
        new_owner = User(
            phone="+79990001008",
            full_name="Новый владелец",
            hashed_password=get_password_hash("Testpass1"),
            role=UserRole.CLIENT,
        )
        admin = User(
            phone="+79990001006",
            full_name="Старший модератор",
            hashed_password=get_password_hash("Testpass1"),
            role=UserRole.ADMIN,
            is_senior_admin=True,
        )
        db.add_all([owner, new_owner, admin])
        await db.commit()
        organization_id = organization.id

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79990001006", "password": "Testpass1"},
    )
    client.cookies.set("access_token", login.json()["access_token"])
    admin_page = await client.get("/admin?tab=sport")
    assert admin_page.status_code == 200
    assert f"/api/v1/admin/sport/organizations/{organization_id}/owner" in admin_page.text
    response = await client.post(
        f"/api/v1/admin/sport/organizations/{organization_id}/owner",
        data={"owner_phone": "8 (999) 000-10-05"},
    )
    assert response.status_code == 302
    assert "tab=sport" in response.headers["location"]

    async with db_session() as db:
        owner = (
            await db.execute(select(User).where(User.phone == "+79990001005"))
        ).scalar_one()
        organization = await db.get(SportOrganization, organization_id)
        membership = (
            await db.execute(
                select(SportGymMember).where(
                    SportGymMember.organization_id == organization_id,
                    SportGymMember.user_id == owner.id,
                )
            )
        ).scalar_one()
        assert owner.role == UserRole.BUSINESS
        assert organization.creator_id == owner.id
        assert membership.role == "owner"
        assert membership.is_creator and membership.is_active
        old_owner_id = owner.id

    reassigned = await client.post(
        f"/api/v1/admin/sport/organizations/{organization_id}/owner",
        data={"owner_phone": "+79990001008"},
    )
    assert reassigned.status_code == 302
    async with db_session() as db:
        old_membership = (
            await db.execute(
                select(SportGymMember).where(
                    SportGymMember.organization_id == organization_id,
                    SportGymMember.user_id == old_owner_id,
                )
            )
        ).scalar_one()
        assert old_membership.is_active is False
        assert old_membership.is_creator is False

    client.cookies.clear()
    owner_login = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79990001008", "password": "Testpass1"},
    )
    client.cookies.set("access_token", owner_login.json()["access_token"])
    dashboard = await client.get("/sport/business/dashboard")
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/sport/test-sport-club/admin"
    panel = await client.get(dashboard.headers["location"])
    assert panel.status_code == 200
    assert 'data-gym-slug="test-sport-club"' in panel.text


async def test_only_senior_admin_can_assign_sport_club_owner(client, db_session):
    await _seed_organization(db_session, _booking_date())
    await register_user(client, "+79990001007", full_name="Модератор")
    async with db_session() as db:
        moderator = (
            await db.execute(select(User).where(User.phone == "+79990001007"))
        ).scalar_one()
        moderator.role = UserRole.ADMIN
        organization = (
            await db.execute(
                select(SportOrganization).where(SportOrganization.slug == "test-sport-club")
            )
        ).scalar_one()
        await db.commit()
        organization_id = organization.id
    login = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79990001007", "password": "Testpass1"},
    )
    client.cookies.set("access_token", login.json()["access_token"])
    response = await client.post(
        f"/api/v1/admin/sport/organizations/{organization_id}/owner",
        data={"owner_phone": "+79990001005"},
    )
    assert response.status_code == 302
    assert "/login?redirect=/admin" in response.headers["location"]

    async with db_session() as db:
        organization = await db.get(SportOrganization, organization_id)
        assert organization.creator_id is None


async def test_sport_management_is_scoped_and_owner_can_add_staff(client, db_session):
    await _seed_organization(db_session, _booking_date())
    await register_user(client, "+79990001002", full_name="Владелец")
    login = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79990001002", "password": "Testpass1"},
    )
    client.cookies.set("access_token", login.json()["access_token"])
    async with db_session() as db:
        owner = (await db.execute(select(User).where(User.phone == "+79990001002"))).scalar_one()
        organization = (
            await db.execute(
                select(SportOrganization).where(SportOrganization.slug == "test-sport-club")
            )
        ).scalar_one()
        db.add(SportGymMember(
            organization_id=organization.id,
            user_id=owner.id,
            role="owner",
            is_creator=True,
        ))
        await db.commit()

    manager = await client.get("/api/v1/sport/organizations/test-sport-club/manage")
    assert manager.status_code == 200, manager.text
    assert manager.json()["role"] == "owner"

    response = await client.post(
        "/api/v1/sport/organizations/test-sport-club/staff",
        data={"phone": "+79990001003", "name": "Администратор", "role": "admin"},
    )
    assert response.status_code == 200, response.text
    credentials = response.json()["credentials"]
    assert credentials["login"] == "+79990001003"
    assert response.headers["Cache-Control"] == "no-store"
    owner_token = client.cookies.get("access_token")
    client.cookies.clear()
    staff_login = await client.post("/api/v1/auth/login-web", data={
        "phone": credentials["login"], "password": credentials["password"],
        "auth_variant": "sport", "redirect": "/sport/test-sport-club/admin",
    }, follow_redirects=False)
    assert staff_login.headers["Location"] == "/sport/test-sport-club/admin"
    staff_panel = await client.get("/api/v1/sport/organizations/test-sport-club/manage")
    assert staff_panel.json()["role"] == "admin"
    client.cookies.clear()
    client.cookies.set("access_token", owner_token)
    async with db_session() as db:
        staff_user = (
            await db.execute(select(User).where(User.phone == "+79990001003"))
        ).scalar_one()
        membership = (
            await db.execute(
                select(SportGymMember).where(SportGymMember.user_id == staff_user.id)
            )
        ).scalar_one()
        assert staff_user.is_guest is True
        assert membership.role == "admin"
        staff_id = membership.id

    removed = await client.delete(
        f"/api/v1/sport/organizations/test-sport-club/staff/admin/{staff_id}"
    )
    assert removed.status_code == 200, removed.text
    readded = await client.post(
        "/api/v1/sport/organizations/test-sport-club/staff",
        data={"phone": "+79990001003", "name": "Администратор", "role": "admin"},
    )
    assert readded.status_code == 200, readded.text
    assert readded.json()["credentials"] is None
    client.cookies.clear()
    await register_user(client, "+79990001003", full_name="Администратор")
    async with db_session() as db:
        staff_user = (
            await db.execute(select(User).where(User.phone == "+79990001003"))
        ).scalar_one()
        membership = (
            await db.execute(
                select(SportGymMember).where(SportGymMember.user_id == staff_user.id)
            )
        ).scalar_one()
        assert staff_user.is_guest is False
        assert membership.is_active is True

    client.cookies.clear()
    await register_user(client, "+79990001004", full_name="Посторонний")
    login = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79990001004", "password": "Testpass1"},
    )
    client.cookies.set("access_token", login.json()["access_token"])
    denied = await client.get("/api/v1/sport/organizations/test-sport-club/manage")
    assert denied.status_code == 403


async def _sport_owner_panel(client, db_session):
    await _seed_organization(db_session, _booking_date())
    async with db_session() as db:
        organization = await db.scalar(select(SportOrganization).where(SportOrganization.slug == "test-sport-club"))
        owner = User(phone="+79990001800", full_name="Владелец", hashed_password="unused", role=UserRole.CLIENT)
        db.add(owner)
        await db.flush()
        db.add(SportGymMember(organization_id=organization.id, user_id=owner.id, role="owner"))
        await db.commit()
    client.cookies.set("access_token", create_access_token(owner.id))
    return "/api/v1/sport/organizations/test-sport-club", organization.id


async def test_sport_owner_can_delegate_and_revoke_staff_permissions(client, db_session):
    base, organization_id = await _sport_owner_panel(client, db_session)
    owner_token = client.cookies.get("access_token")
    added = await client.post(f"{base}/staff", data={
        "phone": "+79990001809", "name": "Администратор", "role": "admin",
    })
    assert added.status_code == 200, added.text
    staff_id = added.json()["member"]["id"]
    async with db_session() as db:
        admin_id = await db.scalar(select(User.id).where(User.phone == "+79990001809"))
        db.add(SportMembershipPlan(organization_id=organization_id, code="base", name="Абонемент", price=2000))
        await db.commit()

    endpoint = f"{base}/manage/staff/{staff_id}/permissions"
    granted = await client.put(endpoint, json={"view_finances": True, "manage_schedule": False, "manage_bookings": False})
    assert granted.status_code == 200, granted.text
    client.cookies.set("access_token", create_access_token(admin_id))
    panel = await client.get(f"{base}/manage")
    assert panel.status_code == 200, panel.text
    assert panel.json()["permissions"]["view_finances"] is True
    assert panel.json()["bookings"] == []
    payment = await client.post(f"{base}/payments", data={"member_name": "Клиент", "plan_code": "base"})
    assert payment.status_code == 200, payment.text
    assert (await client.get(f"{base}/manage/clients")).status_code == 403
    disabled_schedule = await client.put(f"{base}/manage/schedule", json={"trainings": [], "exceptions": {}})
    assert disabled_schedule.status_code == 403
    assert (await client.put(endpoint, json={"manage_schedule": True})).status_code == 403

    client.cookies.set("access_token", owner_token)
    assert (await client.put(endpoint, json={"view_finances": False, "manage_schedule": True})).status_code == 200
    client.cookies.set("access_token", create_access_token(admin_id))
    assert (await client.put(f"{base}/manage/schedule", json={"trainings": [], "exceptions": {}})).status_code == 200
    assert (await client.get(f"{base}/manage")).json()["payments"] == []
    denied_payment = await client.post(f"{base}/payments", data={"member_name": "Клиент", "plan_code": "base"})
    assert denied_payment.status_code == 403


async def test_manage_schedule_saves_new_training_and_date_exception(client, db_session):
    base, _ = await _sport_owner_panel(client, db_session)
    day = _booking_date()
    key = f"{day}:new-training"
    training = {"id": "new-training", "days": [(day.weekday() + 1) % 7], "time": "19:00", "end": "20:00",
                "coach": "Тренер", "gym": "Тестовый зал", "discipline": "Борьба", "active": True}
    saved = await client.put(f"{base}/manage/schedule", json={"trainings": [training], "exceptions": {key: False}})
    assert saved.status_code == 200, saved.text
    result = (await client.get(f"{base}/manage")).json()
    assert result["exceptions"][key] is False
    assert any(item["id"] == "test-session" for item in result["trainings"])
    restored = await client.put(f"{base}/manage/schedule", json={"trainings": [], "exceptions": {key: True}})
    assert restored.status_code == 200, restored.text
    assert key not in (await client.get(f"{base}/manage")).json()["exceptions"]


async def test_sport_payment_and_catalog_changes_return_success_after_commit(client, db_session):
    base, organization_id = await _sport_owner_panel(client, db_session)
    async with db_session() as db:
        plan = SportMembershipPlan(organization_id=organization_id, code="base", name="Абонемент", price=2000)
        discipline = SportDiscipline(organization_id=organization_id, name="Борьба")
        venue = await db.scalar(select(SportVenue).where(SportVenue.organization_id == organization_id))
        db.add_all([plan, discipline])
        await db.commit()
    payment = await client.post(f"{base}/payments", data={"member_name": "Клиент", "plan_code": "base"})
    assert payment.status_code == 200, payment.text
    assert payment.json()["payment"]["amount"] == 2000
    for path in (f"venues/{venue.id}", f"disciplines/{discipline.id}", f"plans/{plan.id}"):
        deleted = await client.delete(f"{base}/manage/{path}")
        assert deleted.status_code == 200, deleted.text
    closure = await client.post(f"{base}/closures", json={"date": _booking_date().isoformat()})
    assert closure.status_code == 200, closure.text
    deleted_closure = await client.delete(f"{base}/closures/{closure.json()['id']}")
    assert deleted_closure.status_code == 200, deleted_closure.text
    management = (await client.get(f"{base}/manage")).json()
    assert management["venues"] == management["disciplines"] == management["plans"] == []
    assert management["payments"] == [payment.json()["payment"]]


async def test_sport_client_history_groups_participants_and_preserves_visit_time(client, db_session):
    base, organization_id = await _sport_owner_panel(client, db_session)
    day = _booking_date() - timedelta(days=10)
    async with db_session() as db:
        parent = User(phone="+79990001801", full_name="Родитель", hashed_password="unused", role=UserRole.CLIENT)
        db.add(parent)
        await db.flush()
        training = await db.scalar(select(SportTraining).where(SportTraining.organization_id == organization_id))
        common = dict(organization_id=organization_id, training_id=training.id, client_id=parent.id,
                      contact_name=parent.full_name, kind="Обычное", requested_date=day,
                      requested_gym="Тестовый зал", requested_discipline="Борьба")
        first = SportBooking(**common, participant="child", child_name="Аня", status="pending")
        second = SportBooking(**common, participant="child", child_name="Аня", status="came")
        sibling = SportBooking(**common, participant="child", child_name="Коля", status="came")
        adult = SportBooking(**common, participant="self", status="pending")
        db.add_all([first, second, sibling, adult])
        await db.commit()
    marked = await client.post(f"{base}/bookings/{first.id}/status", data={"status": "came"})
    assert marked.status_code == 200, marked.text
    assert marked.json()["time"] == "23:00"
    async with db_session() as db:
        training = await db.get(SportTraining, training.id)
        training.start_time = time(22, 0)
        await db.commit()

    directory = await client.get(f"{base}/manage/clients", params={"search": "900 01801"})
    assert directory.status_code == 200, directory.text
    assert {row["name"]: row["visits"] for row in directory.json()["clients"]} == {"Аня": 2, "Коля": 1, "Родитель": 0}
    calendar = await client.get(f"{base}/manage/visits/calendar", params={"month": day.isoformat()})
    assert calendar.json() == {"counts": {day.isoformat(): 3}}
    by_day = await client.get(f"{base}/manage/visits", params={"day": day.isoformat()})
    assert {visit["id"] for visit in by_day.json()["visits"]} == {first.id, second.id, sibling.id}
    history = await client.get(f"{base}/manage/visits", params={"client": second.id, "limit": 1})
    assert history.json()["has_more"] is True
    assert history.json()["visits"][0]["id"] == second.id
    next_page = await client.get(f"{base}/manage/visits", params={"client": second.id, "limit": 1, "offset": 1})
    assert next_page.json() == {"has_more": False, "visits": [
        {"id": first.id, "name": "Аня", "date": day.isoformat(), "time": "23:00", "gym": "Тестовый зал",
         "discipline": "Борьба", "coach": "Тренер"},
    ]}
    client.cookies.clear()
    client.cookies.set("access_token", create_access_token(parent.id))
    denied = await client.get(f"{base}/manage/visits", params={"client": second.id})
    assert denied.status_code == 403


async def test_sport_staff_edits_unlinked_coach_and_uploads_photo(client, db_session, monkeypatch, tmp_path):
    base, organization_id = await _sport_owner_panel(client, db_session)
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    async with db_session() as db:
        coach = SportCoach(organization_id=organization_id, name="Тренер", bio="Старое описание")
        db.add(coach)
        await db.flush()
        training = await db.scalar(select(SportTraining).where(SportTraining.organization_id == organization_id))
        training.coach_id = coach.id
        await db.commit()
    photo = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(photo, format="PNG")
    profile = {"name": "Новый тренер", "contact_phone": "8 (999) 000-18-02", "about": "Ведёт детские группы",
               "title": "Старший тренер", "experience": "10 лет", "tags": "Борьба"}
    saved = await client.put(f"{base}/staff/trainer/{coach.id}", data=profile,
                             files={"photo": ("coach.png", photo.getvalue(), "image/png")})
    assert saved.status_code == 200, saved.text
    assert saved.headers["Cache-Control"] == "no-store"
    card = saved.json()["member"]
    assert card["phone"] == "+79990001802"
    assert card["hasAccount"] is True
    credentials = saved.json()["credentials"]
    assert credentials["login"] == "+79990001802"
    owner_token = client.cookies.get("access_token")
    client.cookies.clear()
    staff_login = await client.post("/api/v1/auth/login-web", data={
        "phone": credentials["login"], "password": credentials["password"],
        "auth_variant": "sport", "redirect": "/sport/test-sport-club/admin",
    }, follow_redirects=False)
    assert staff_login.headers["Location"] == "/sport/test-sport-club/admin"
    assert (await client.get(f"{base}/manage")).json()["role"] == "trainer"
    client.cookies.clear()
    client.cookies.set("access_token", owner_token)
    assert card["about"] == profile["about"]
    photo_file = tmp_path / card["photo"].split("/uploads/")[1]
    assert photo_file.is_file()
    manage = (await client.get(f"{base}/manage")).json()
    assert card in manage["team"]
    assert manage["trainings"][0]["coach"] == profile["name"]
    updated = await client.put(f"{base}/staff/trainer/{coach.id}", data={**profile, "remove_photo": "true"})
    assert updated.json()["member"]["photo"] is None
    assert updated.json()["credentials"] is None
    assert not photo_file.exists()
