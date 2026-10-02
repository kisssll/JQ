"""Smoke-тест бизнес-панели: КАЖДАЯ вкладка должна открываться без 500.

Ловит целый класс регрессий, который проходил мимо остальных тестов:
- рассинхрон сигнатур при мерже (диспетчер звал render_promo_models_tab(db,
  salon), а функция требовала masters → TypeError → 500 на вкладке «Модели»);
- падения рендера вкладок на пустых данных.

Владелец-создатель видит все вкладки (is_creator → все права), поэтому
проверяем весь набор одним проходом. Салон здесь в режиме «у меня команда»:
режим задаёт НАБОР разделов (решение 0007), а этот тест про то, что рендер
каждой вкладки не падает, — набор ему нужен полный. Видимость разделов по
режиму проверяется отдельно, в tests/test_panel_modes.py.
"""
import re

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
    SalonPanelMode,
)

DASHBOARD_TABS = [
    "overview", "analytics", "schedule", "employees", "services", "payroll",
    "cost", "records", "warehouse", "models", "promos", "reviews", "crm", "edit",
    "instructions",
]


async def test_all_business_dashboard_tabs_render(client, db_session):
    async with db_session() as db:
        owner = User(
            phone="+79995550777", full_name="SmokeOwner",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name="Smoke Salon", address="ул. Тестовая, 1", phone="+70000000900",
            latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=SalonPanelMode.TEAM,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        db.add(SalonMember(
            salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
            is_creator=True, permissions={}, is_active=True,
        ))
        await db.commit()

    r = await client.post(
        "/api/v1/auth/login-web",
        data={"phone": "+79995550777", "password": "Testpass1"},
    )
    assert r.status_code == 302, r.text

    for tab in DASHBOARD_TABS:
        r = await client.get(f"/business/dashboard?tab={tab}")
        assert r.status_code == 200, f"вкладка {tab!r} → {r.status_code}: {r.text[:400]}"
        assert f'id="tab-{tab}"' in r.text, f"вкладка {tab!r}: контент не отрендерился"

    # «Инструкция» — по секции на каждую остальную вкладку панели (15: все
    # DASHBOARD_TABS кроме самой «instructions», плюс «billing» — она не в
    # DASHBOARD_TABS выше, но есть в панели, см. tab_buttons в dashboard.py).
    # Заход 5 заменил аккордеон открытыми секциями с якорями, поэтому считаем
    # якоря секций: группы и «с чего начать» сюда не попадают.
    r = await client.get("/business/dashboard?tab=instructions")
    assert r.status_code == 200
    anchors = [
        a for a in re.findall(r'id="manual-([a-z]+)"', r.text) if a != "start"
    ]
    assert len(anchors) == 15, anchors


async def test_all_solo_dashboard_tabs_render(client, db_session):
    """То же самое для соло-режима: у него свой набор разделов и своя вкладка
    «Моя карточка мастера» — она рендерится другим кодом, чем «Сотрудники»."""
    from app.services import panel_sections

    async with db_session() as db:
        owner = User(
            phone="+79995550778", full_name="SoloOwner",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name="Solo Salon", address="ул. Тестовая, 1", phone="+70000000901",
            latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=SalonPanelMode.SOLO,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        db.add(SalonMember(
            salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
            is_creator=True, permissions={}, is_active=True,
        ))
        await db.commit()

    r = await client.post(
        "/api/v1/auth/login-web",
        data={"phone": "+79995550778", "password": "Testpass1"},
    )
    assert r.status_code == 302, r.text

    for tab in sorted(panel_sections.default_keys(SalonPanelMode.SOLO)):
        r = await client.get(f"/business/dashboard?tab={tab}")
        assert r.status_code == 200, f"соло-вкладка {tab!r} → {r.status_code}: {r.text[:400]}"
        assert f'id="tab-{tab}"' in r.text, f"соло-вкладка {tab!r}: контент не отрендерился"
