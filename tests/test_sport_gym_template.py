from types import SimpleNamespace
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.sport import (
    SportDiscipline,
    SportGalleryImage,
    SportGymMember,
    SportMembershipPlan,
    SportOrganization,
    SportVenue,
)
from app.models.models import User
from app.web.pages.sport import render_sport_gym_template, render_sport_placeholder


def test_render_sport_gym_template_custom_club():
    venue1 = SimpleNamespace(name="Филиал Центр", address="ул. Ленина, 10", city="Москва")
    venue2 = SimpleNamespace(name="Филиал Север", address="ул. Мира, 5", city="Москва")
    discipline = SimpleNamespace(name="Кроссфит")
    plan = SimpleNamespace(name="Безлимит", price=4500)

    html = render_sport_gym_template(
        slug="titan-gym",
        name="Titan Gym & Fitness",
        city="Москва",
        logo_url="https://example.com/titan-logo.png",
        description="Современный бойцовский и кроссфит клуб в центре Москвы.",
        address="ул. Ленина, 10",
        venues=[venue1, venue2],
        disciplines=[discipline],
        plans=[plan],
    )

    assert "Titan Gym &amp; Fitness · Москва | Руми Спорт" in html
    assert 'data-gym-slug="titan-gym"' in html
    assert 'data-gym-name="Titan Gym &amp; Fitness"' in html
    assert 'data-gym-logo="https://example.com/titan-logo.png"' in html
    assert '<link rel="icon" href="https://example.com/titan-logo.png">' in html
    assert "Филиал Центр" in html
    assert "Филиал Север" in html
    assert "Кроссфит" in html
    assert 'schema.org' in html
    assert 'SportsOrganization' in html
    assert 'Titan Gym & Fitness' in html


def test_render_sport_gym_template_fallback_favicon():
    html = render_sport_gym_template(
        slug="my-club",
        name="Мой Клуб",
        city="Казань",
    )
    assert '<link rel="icon" href="/static/icons/favicon.ico">' in html
    assert 'data-gym-slug="my-club"' in html


def test_render_sport_placeholder_delegates_to_template():
    org = SportOrganization(
        slug="new-club",
        name="Новый Клуб",
        city="Самара",
        description="Новейший спортзал",
        is_published=True,
    )
    html = render_sport_placeholder(org)
    assert "Новый Клуб" in html
    assert 'data-gym-slug="new-club"' in html


@pytest.mark.asyncio
async def test_sport_gym_management_api(client, db_session):
    async with db_session() as session:
        # 1. Create owner and organization
        owner = User(
            email="gym_boss@test.com",
            phone="+79998887766",
            full_name="Gym Owner",
            hashed_password="hash",
            is_active=True,
        )
        session.add(owner)
        await session.flush()

        org = SportOrganization(
            slug="dynamo-fit",
            name="Динамо Фит",
            city="Сочи",
            address="Курортный проспект, 1",
            description="Клуббокс и фитнес",
            is_published=True,
            moderation_status="approved",
        )
        session.add(org)
        await session.flush()

        member = SportGymMember(
            organization_id=org.id,
            user_id=owner.id,
            role="owner",
            is_active=True,
        )
        session.add(member)
        await session.commit()

        token = create_access_token(subject=owner.id)
        headers = {"Authorization": f"Bearer {token}"}

    # 2. Update profile
    resp = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/profile",
        headers=headers,
        json={
            "name": "Динамо Фитнес Премиум",
            "city": "Сочи",
            "description": "Обновленное описание сети",
            "logo_url": "https://example.com/logo.png",
            "address": "ул. Морская, 15",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["organization"]["name"] == "Динамо Фитнес Премиум"
    assert data["organization"]["address"] == "ул. Морская, 15"
    assert data["organization"]["logo_url"] == "https://example.com/logo.png"

    # 3. Add venue
    resp_venue = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/venues",
        headers=headers,
        json={
            "name": "Зал на Набережной",
            "city": "Сочи",
            "address": "ул. Морская, 15",
            "phone": "+78622000000",
        },
    )
    assert resp_venue.status_code == 200, resp_venue.text
    venue_data = resp_venue.json()
    venue_id = venue_data["id"]
    assert venue_data["name"] == "Зал на Набережной"

    # 4. Add discipline
    resp_disc = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/disciplines",
        headers=headers,
        json={
            "name": "Бокс",
            "description": "Классический бокс для всех уровней",
            "icon": "boxing-glove",
            "color": "#ff4444",
        },
    )
    assert resp_disc.status_code == 200, resp_disc.text
    disc_data = resp_disc.json()
    disc_id = disc_data["id"]
    assert disc_data["name"] == "Бокс"

    # 5. Add plan
    resp_plan = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/plans",
        headers=headers,
        json={
            "code": "monthly-unlimited",
            "name": "Месячный Безлимит",
            "price": 5000,
            "unit": "руб/мес",
            "items": ["Тренажёрный зал", "Бассейн"],
            "featured": True,
        },
    )
    assert resp_plan.status_code == 200, resp_plan.text
    plan_data = resp_plan.json()
    plan_id = plan_data["id"]
    assert plan_data["price"] == 5000

    # 6. Add gallery image
    resp_gal = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/gallery",
        headers=headers,
        json={
            "image_url": "https://example.com/interior.jpg",
            "alt_text": "Главный ринг",
        },
    )
    assert resp_gal.status_code == 200, resp_gal.text
    gal_data = resp_gal.json()
    image_id = gal_data["id"]

    # 7. Check catalog reflects the newly added items
    resp_cat = await client.get(f"/api/v1/sport/organizations/{org.slug}/catalog")
    assert resp_cat.status_code == 200
    cat_data = resp_cat.json()
    assert len(cat_data["venues"]) == 1
    assert cat_data["venues"][0]["name"] == "Зал на Набережной"
    assert len(cat_data["disciplines"]) == 1
    assert cat_data["disciplines"][0]["name"] == "Бокс"
    assert len(cat_data["plans"]) == 1
    assert cat_data["plans"][0]["name"] == "Месячный Безлимит"
    assert len(cat_data["gallery"]) == 1
    assert cat_data["gallery"][0]["alt"] == "Главный ринг"
    assert cat_data["gallery"][0]["src"] == "https://example.com/interior.jpg"

    # 8. Check management overview returns full sections
    resp_mgmt = await client.get(
        f"/api/v1/sport/organizations/{org.slug}/manage",
        headers=headers,
    )
    assert resp_mgmt.status_code == 200
    mgmt_data = resp_mgmt.json()
    assert len(mgmt_data["venues"]) == 1
    assert len(mgmt_data["disciplines"]) == 1
    assert len(mgmt_data["plans"]) == 1
    assert len(mgmt_data["gallery"]) == 1

    # 9. Test SSR gym page returns updated info and venue in markup
    resp_web = await client.get(f"/sport/{org.slug}")
    assert resp_web.status_code == 200
    assert "Динамо Фитнес Премиум" in resp_web.text
    assert "Зал на Набережной" in resp_web.text
    assert "Бокс" in resp_web.text

    # 10. Delete gallery item and verify
    resp_del_gal = await client.delete(
        f"/api/v1/sport/organizations/{org.slug}/manage/gallery/{image_id}",
        headers=headers,
    )
    assert resp_del_gal.status_code == 200

    # 11. Unauthorized / non-member forbidden check
    async with db_session() as session:
        stranger = User(
            email="stranger@test.com",
            phone="+79991112233",
            full_name="Stranger",
            hashed_password="hash",
            is_active=True,
        )
        session.add(stranger)
        await session.commit()
    stranger_token = create_access_token(subject=stranger.id)
    stranger_headers = {"Authorization": f"Bearer {stranger_token}"}

    resp_forbidden = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/venues",
        headers=stranger_headers,
        json={"name": "Хак", "address": "Куда-то"},
    )
    assert resp_forbidden.status_code == 403
