"""Тесты для функционала предварительной консультации мастера по волосам (hair survey).

Проверяется:
1. Настройка анкеты волос мастером (API POST /api/v1/masters/{id}/hair-survey) — включение/выключение, кастомные теги.
2. Создание бронирования с анкетой волос (POST /api/v1/bookings).
3. Отображение настроек анкеты в данных виджета на странице салона/мастера.
4. Отображение параметров волос в расписании (schedule.py), журнале записей (records.py) и кабинете клиента (bookings.py).
"""
import itertools
import json
import pytest
from datetime import datetime, timedelta

from app.core.security import create_access_token, get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Salon, SalonModerationStatus, SalonPanelMode,
    Service, User, UserRole
)
from app.web.pages.business.tabs.schedule import render_schedule_tab
from app.web.pages.business.tabs.records import render_records_tab
from app.web.pages.bookings import render_bookings_page

_phone = itertools.count(100)
_ALL_DAY = json.dumps({d: "00:00-23:59" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


async def _create_test_environment(db_session):
    async with db_session() as db:
        owner = User(
            phone=f"+7995{next(_phone):07d}",
            full_name="Елена Волоскова",
            hashed_password=get_password_hash("MasterPass1"),
            role=UserRole.BUSINESS,
        )
        client = User(
            phone=f"+7995{next(_phone):07d}",
            full_name="Мария Клиентка",
            hashed_password=get_password_hash("ClientPass1"),
            role=UserRole.CLIENT,
        )
        db.add_all([owner, client])
        await db.commit()
        await db.refresh(owner)
        await db.refresh(client)

        salon = Salon(
            name="Студия реконструкции волос",
            address="ул. Красоты, 12",
            city="Москва",
            phone=f"+7995{next(_phone):07d}",
            latitude=55.75,
            longitude=37.61,
            working_hours=_ALL_DAY,
            timezone="Europe/Moscow",
            panel_mode=SalonPanelMode.SOLO,
            moderation_status=SalonModerationStatus.APPROVED,
            is_active=True,
            creator_id=owner.id,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        master = Master(
            salon_id=salon.id,
            user_id=owner.id,
            specialization="Мастер по кератину и ламинированию",
            experience_years=5,
            is_active=True,
            hair_survey_enabled=True,
            hair_survey_settings={
                "custom_tags": [
                    "Обесцвеченные / блонд",
                    "Ранее делался кератин",
                    "Сильная пористость",
                    "Тест пряди обязателен",
                ]
            },
        )
        db.add(master)
        await db.commit()
        await db.refresh(master)

        service = Service(
            master_id=master.id,
            name="Холодное восстановление волос",
            price=4500,
            duration_minutes=120,
            is_active=True,
        )
        db.add(service)
        await db.commit()
        await db.refresh(service)

        return owner, client, salon, master, service


@pytest.mark.asyncio
async def test_master_hair_survey_settings_api(client, db_session):
    """Проверка обновления настроек анкеты волос через API мастером."""
    owner, _, salon, master, _ = await _create_test_environment(db_session)
    token = create_access_token(subject=owner.id)

    # 1. Обновление через JSON
    new_settings = {
        "enabled": True,
        "custom_tags": ["Обесцвеченные", "Смывка цвета", "Наращивание"],
        "min_length_id": 2,
    }
    resp = await client.post(
        f"/api/v1/masters/{master.id}/hair-survey",
        headers={"Authorization": f"Bearer {token}"},
        json=new_settings,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["enabled"] is True
    assert "Смывка цвета" in data["settings"]["custom_tags"]

    # Проверяем в БД
    async with db_session() as db:
        m = await db.get(Master, master.id)
        assert m.hair_survey_enabled is True
        assert m.hair_survey_settings["custom_tags"] == ["Обесцвеченные", "Смывка цвета", "Наращивание"]

    # 2. Отключение анкеты
    resp_disable = await client.post(
        f"/api/v1/masters/{master.id}/hair-survey",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert resp_disable.status_code == 200
    assert resp_disable.json()["enabled"] is False

    async with db_session() as db:
        m = await db.get(Master, master.id)
        assert m.hair_survey_enabled is False


@pytest.mark.asyncio
async def test_booking_creation_with_hair_survey(client, db_session):
    """Проверка создания записи с сохранением параметров анкеты волос."""
    _, client_user, salon, master, service = await _create_test_environment(db_session)
    client_token = create_access_token(subject=client_user.id)

    start_time = (datetime.now() + timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
    survey_payload = {
        "length": {
            "id": 5,
            "title": "Длинные",
            "cm": "~55–60 см",
        },
        "type": {
            "id": "wavy",
            "title": "Легкая волна",
        },
        "density": {
            "id": "thick",
            "title": "Очень густые",
        },
        "features": [
            "Обесцвеченные / блонд",
            "Сухие / секущиеся концы",
        ],
    }

    booking_req = {
        "master_id": master.id,
        "service_id": service.id,
        "start_time": start_time.strftime("%Y-%m-%dT%H:%M"),
        "hair_survey": survey_payload,
    }

    create_resp = await client.post(
        "/api/v1/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=booking_req,
    )
    assert create_resp.status_code in (200, 201), create_resp.text
    booking_id = create_resp.json()["id"]

    async with db_session() as db:
        b = await db.get(Booking, booking_id)
        assert b is not None
        assert b.hair_survey is not None
        assert b.hair_survey["length"]["title"] == "Длинные"
        assert b.hair_survey["length"]["cm"] == "~55–60 см"
        assert b.hair_survey["type"]["id"] == "wavy"
        assert b.hair_survey["density"]["title"] == "Очень густые"
        assert "Обесцвеченные / блонд" in b.hair_survey["features"]


@pytest.mark.asyncio
async def test_salon_detail_widget_contains_hair_survey_data(client, db_session):
    """Проверка того, что страница салона передает настройки анкеты волос в data-masters."""
    _, _, salon, master, _ = await _create_test_environment(db_session)

    resp = await client.get(f"/salons/{salon.id}")
    assert resp.status_code == 200
    html = resp.text
    assert 'data-masters=' in html

    # Извлекаем JSON из data-masters
    import re
    match = re.search(r'id="bookingWidget"[^>]*data-masters=(["\'])(.*?)\1', html, re.DOTALL)
    assert match is not None
    import html as html_module
    masters_json = html_module.unescape(match.group(2))
    masters_list = json.loads(masters_json)
    assert len(masters_list) > 0
    m_data = next((m for m in masters_list if m["id"] == master.id), None)
    assert m_data is not None
    assert "hair_survey" in m_data
    assert m_data["hair_survey"]["enabled"] is True
    assert "Тест пряди обязателен" in m_data["hair_survey"]["settings"]["custom_tags"]


@pytest.mark.asyncio
async def test_hair_survey_rendering_in_schedule_and_records(db_session):
    """Проверка отображения анкеты волос в расписании, журнале записей и ЛК клиента."""
    owner, client_user, salon, master, service = await _create_test_environment(db_session)

    start_time = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end_time = start_time + timedelta(hours=2)

    survey = {
        "length": {"id": 4, "title": "Средние (до лопаток)", "cm": "~40–45 см"},
        "type": {"id": "curly", "title": "Кудрявые"},
        "density": {"id": "medium", "title": "Средняя густота"},
        "features": ["Окрашенные", "Пористые"],
    }

    async with db_session() as db:
        booking = Booking(
            master_id=master.id,
            service_id=service.id,
            client_id=client_user.id,
            start_time=start_time,
            end_time=end_time,
            status=BookingStatus.CONFIRMED,
            final_price=4500,
            hair_survey=survey,
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)

    async with db_session() as db:
        # 1. Расписание
        schedule_html = await render_schedule_tab(
            db=db,
            salon=salon,
            masters=[master],
            can_manage_schedule=True,
            schedule_master_id=master.id,
        )
        assert "Волосы:" in schedule_html
        assert "Средние (до лопаток)" in schedule_html
        assert "~40–45 см" in schedule_html
        assert "Окрашенные" in schedule_html
        assert "Пористые" in schedule_html

        # 2. Журнал записей
        records_html = await render_records_tab(
            db=db,
            salon=salon,
            masters=[master],
            master_ids=[master.id],
            filters={},
            can_manage_schedule=True,
        )
        assert "💇 Средние (до лопаток) (~40–45 см)" in records_html
        assert "Волосы:" in records_html

        # 3. Страница «Мои записи» клиента
        client_bookings_html = await render_bookings_page(
            db=db,
            user=client_user,
        )
        assert "Волосы" in client_bookings_html
        assert "Средние (до лопаток)" in client_bookings_html
