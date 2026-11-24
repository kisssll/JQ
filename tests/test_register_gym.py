import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.models import User, UserRole
from app.models.sport import (
    SportGymMember,
    SportMembershipPlan,
    SportOrganization,
    SportVenue,
)
from app.web.pages.legal import LEGAL_VERSION


async def _auth_user(db_session, client, phone="+79998881122", full_name="Тестовый пользователь"):
    async with db_session() as db:
        user = User(
            phone=phone,
            full_name=full_name,
            hashed_password=get_password_hash("Testpass1"),
            role=UserRole.CLIENT,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    token = create_access_token(user_id)
    client.cookies.set("access_token", token)
    return user_id


async def test_register_gym_page_redirects_unauthenticated(client):
    response = await client.get("/sport/business/register-gym")
    assert response.status_code == 302
    assert response.headers["location"] == "/sport/login?redirect=/sport/business/register-gym"

    alias_response = await client.get("/sport/register-gym")
    assert alias_response.status_code == 302
    assert alias_response.headers["location"] == "/sport/login?redirect=/sport/business/register-gym"


async def test_register_gym_page_renders_for_authenticated_user(client, db_session):
    await _auth_user(db_session, client, phone="+79998881122", full_name="Владелец зала")

    response = await client.get("/sport/business/register-gym")
    assert response.status_code == 200
    html = response.text
    assert "Добавить спортивный клуб" in html
    assert 'action="/api/v1/sport/business/apply"' in html
    assert 'name="name"' in html
    assert 'name="description"' in html
    assert 'name="city"' in html
    assert 'name="address"' in html
    assert 'name="phone"' in html
    assert 'name="email"' in html
    assert 'name="offer_accepted"' in html
    assert 'name="pd_consent"' in html
    assert f'value="{LEGAL_VERSION}"' in html


async def test_apply_sport_business_validation_errors(client, db_session):
    phone = "+79998881123"
    await _auth_user(db_session, client, phone=phone, full_name="Тестовый тренер")

    # 1. Missing offer accepted
    r1 = await client.post("/api/v1/sport/business/apply", data={
        "name": "Спортклуб Чемпион",
        "city": "Москва",
        "address": "ул. Ленина, 1",
        "phone": phone,
        "offer_accepted": "",
        "pd_consent": "1",
        "consent_version": LEGAL_VERSION,
    })
    assert r1.status_code == 400
    assert "Нужно принять условия оферты" in r1.text

    # 2. Missing PD consent
    r2 = await client.post("/api/v1/sport/business/apply", data={
        "name": "Спортклуб Чемпион",
        "city": "Москва",
        "address": "ул. Ленина, 1",
        "phone": phone,
        "offer_accepted": "1",
        "pd_consent": "",
        "consent_version": LEGAL_VERSION,
    })
    assert r2.status_code == 400
    assert "Отметьте согласие на обработку персональных данных" in r2.text

    # 3. Invalid city
    r3 = await client.post("/api/v1/sport/business/apply", data={
        "name": "Спортклуб Чемпион",
        "city": "НесуществующийГород123",
        "address": "ул. Ленина, 1",
        "phone": phone,
        "offer_accepted": "1",
        "pd_consent": "1",
        "consent_version": LEGAL_VERSION,
    })
    assert r3.status_code == 400
    assert "Выберите город из списка" in r3.text

    # 4. Invalid phone
    r4 = await client.post("/api/v1/sport/business/apply", data={
        "name": "Спортклуб Чемпион",
        "city": "Москва",
        "address": "ул. Ленина, 1",
        "phone": "invalid-phone",
        "offer_accepted": "1",
        "pd_consent": "1",
        "consent_version": LEGAL_VERSION,
    })
    assert r4.status_code == 400
    assert "Проверьте номер телефона" in r4.text


async def test_apply_sport_business_success_creates_full_gym_entity(client, db_session):
    phone = "+79998881124"
    await _auth_user(db_session, client, phone=phone, full_name="Алексей Владелец")

    response = await client.post("/api/v1/sport/business/apply", data={
        "name": "Бойцовский Клуб Руми",
        "city": "Томск",
        "address": "ул. Спортивная, д. 15",
        "phone": phone,
        "email": "club@rumi-sport.ru",
        "description": "Клуб смешанных единоборств и бокса",
        "offer_accepted": "1",
        "pd_consent": "1",
        "consent_version": LEGAL_VERSION,
    })
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/sport/business?submitted=")

    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        assert user.role == UserRole.BUSINESS

        org = (
            await db.execute(select(SportOrganization).where(SportOrganization.name == "Бойцовский Клуб Руми"))
        ).scalar_one()
        assert org.creator_id == user.id
        assert org.moderation_status == "pending"
        assert org.is_published is False
        assert org.city == "Томск"
        assert org.address == "ул. Спортивная, д. 15"
        assert org.email == "club@rumi-sport.ru"
        # Slug has readable transliteration
        assert org.slug.startswith("boytsovskiy-klub-rumi-")

        # Owner member created
        member = (
            await db.execute(select(SportGymMember).where(SportGymMember.organization_id == org.id))
        ).scalar_one()
        assert member.user_id == user.id
        assert member.role == "owner"
        assert member.is_creator is True
        assert member.is_active is True

        # Main venue created
        venue = (
            await db.execute(select(SportVenue).where(SportVenue.organization_id == org.id))
        ).scalar_one()
        assert venue.name == "Основной зал"
        assert venue.address == "ул. Спортивная, д. 15"

        # Default plans created
        plans = (
            await db.execute(select(SportMembershipPlan).where(SportMembershipPlan.organization_id == org.id))
        ).scalars().all()
        assert len(plans) >= 2


async def test_my_gym_alias_endpoint(client, db_session):
    phone = "+79998881125"
    await _auth_user(db_session, client, phone=phone, full_name="Иван Зал")

    response = await client.post("/api/v1/sport/business/my-gym", data={
        "name": "Фитнес Зал Старт",
        "city": "Новосибирск",
        "address": "Красный проспект, 100",
        "phone": phone,
        "offer_accepted": "1",
        "pd_consent": "1",
        "consent_version": LEGAL_VERSION,
    })
    assert response.status_code == 303
    assert response.headers["location"].startswith("/sport/business?submitted=")


async def test_sport_business_page_shows_success_banner_and_register_cta(client, db_session):
    phone = "+79998881126"
    await _auth_user(db_session, client, phone=phone, full_name="Ольга Спорт")

    # Normal page has CTA
    resp = await client.get("/sport/business")
    assert resp.status_code == 200
    assert "/sport/business/register-gym" in resp.text
    assert "Заполнить анкету и добавить клуб" in resp.text

    # After submission has success banner
    submitted_resp = await client.get("/sport/business?submitted=999")
    assert submitted_resp.status_code == 200
    assert "Заявка на подключение клуба принята!" in submitted_resp.text
