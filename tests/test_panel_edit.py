"""Режим редактирования бизнес-панели (решение 0007, дополнение 30.09.2026).

Проверяем то, что режим редактирования добавил к заходу 1:
  1. порядок разделов — чистые функции panel_sections (без БД и HTTP);
  2. панель: меню в сохранённом порядке, шестерёнка, скрытые разделы, вход по ?edit=1;
  3. сохранение одним запросом и что именно попадает в журнал;
  4. соло-режим: мастера нельзя добавить и через эндпоинт, не только кнопкой.
"""
import pytest
from types import SimpleNamespace

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
    SalonPanelMode, Master, AdminAudit, OWNER_DEFAULT_PERMISSIONS,
)
from app.services import panel_sections as ps


# ─────────────────────────── 1. Порядок разделов ───────────────────────────

def _salon(mode, stored=None):
    return SimpleNamespace(panel_mode=mode, panel_sections=stored)


def _canonical(mode):
    return [k for k in ps.ALL_KEYS if k in ps.default_keys(mode)]


def test_normalize_keeps_the_order_the_owner_sent():
    """Главное отличие от захода 1: порядок владельца — это данные, а не шум."""
    sent = ["overview", "services", "records", "schedule", "billing", "employees", "crm"]
    assert ps.normalize(SalonPanelMode.SOLO, sent) == sent


def test_normalize_pins_overview_first_even_if_sent_last():
    stored = ps.normalize(SalonPanelMode.TEAM, ["crm", "services", "overview", "records",
                                                "schedule", "billing", "edit"])
    assert stored[0] == "overview"


def test_normalize_appends_missing_locked_sections():
    """Обязательные добавляем всегда — но в конец, чтобы не ломать порядок."""
    stored = ps.normalize(SalonPanelMode.SOLO, ["overview", "crm"])
    assert stored[:2] == ["overview", "crm"]
    assert ps.locked_keys(SalonPanelMode.SOLO) <= frozenset(stored)


def test_normalize_drops_unknown_keys_and_duplicates():
    stored = ps.normalize(SalonPanelMode.SOLO, ["overview", "crm", "no_such_tab", "crm"])
    assert "no_such_tab" not in stored
    assert stored.count("crm") == 1


def test_normalize_is_none_when_set_and_order_match_the_mode():
    assert ps.normalize(SalonPanelMode.SOLO, _canonical(SalonPanelMode.SOLO)) is None
    assert ps.normalize(SalonPanelMode.TEAM, _canonical(SalonPanelMode.TEAM)) is None


def test_normalize_keeps_a_list_when_only_the_order_differs():
    """Тот же состав, но переставленный, — это правка владельца: «как по
    режиму» тут сохранять нельзя, иначе порядок потеряется при первом же
    открытии панели."""
    shuffled = _canonical(SalonPanelMode.SOLO)
    shuffled.insert(1, shuffled.pop())       # последний раздел поднят на второе место
    assert ps.normalize(SalonPanelMode.SOLO, shuffled) == shuffled


def test_ordered_keys_follows_the_mode_when_nothing_is_stored():
    assert ps.ordered_keys(_salon(SalonPanelMode.SOLO)) == _canonical(SalonPanelMode.SOLO)
    assert ps.ordered_keys(_salon(SalonPanelMode.TEAM, [])) == _canonical(SalonPanelMode.TEAM)


def test_ordered_keys_returns_the_stored_order():
    stored = ["overview", "crm", "services", "schedule", "records", "billing", "employees"]
    assert ps.ordered_keys(_salon(SalonPanelMode.SOLO, stored)) == stored


def test_ordered_keys_repairs_a_broken_stored_list():
    """В JSON может лежать что угодно: чужой ключ, потерянный обязательный,
    «Обзор» не первым. Панель обязана открыться."""
    ordered = ps.ordered_keys(_salon(SalonPanelMode.SOLO, ["crm", "no_such_tab", "overview"]))
    assert ordered[0] == "overview"
    assert "no_such_tab" not in ordered
    assert ps.locked_keys(SalonPanelMode.SOLO) <= frozenset(ordered)


def test_enabled_keys_matches_ordered_keys():
    """Видимость и порядок обязаны отвечать одно и то же — иначе раздел
    появится в меню, но не откроется (или наоборот)."""
    salon = _salon(SalonPanelMode.SOLO, ["overview", "crm", "warehouse"])
    assert ps.enabled_keys(salon) == frozenset(ps.ordered_keys(salon))


# ─────────────────────────── 2. Панель ───────────────────────────

async def _make_salon(db_session, phone, mode, *, sections=None, with_master=False):
    async with db_session() as db:
        owner = User(
            phone=phone, full_name="Хозяин",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name="Порядок", address="ул. Тестовая, 4", phone="+70000000903",
            latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=mode, panel_sections=sections,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        db.add(SalonMember(
            salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
            is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        if with_master:
            db.add(Master(
                user_id=owner.id, salon_id=salon.id,
                specialization="Маникюр", experience_years=0, rating=0.0,
            ))
        await db.commit()
        return owner.id, salon.id


async def _login(client, phone):
    r = await client.post(
        "/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"},
    )
    assert r.status_code == 302, r.text


def _menu_order(html: str):
    """Ключи разделов в том порядке, в котором они стоят в ленте вкладок.

    Смотрим только саму ленту: ниже в странице лежат ещё и заготовки плиток
    для скрытых разделов (<template> режима редактирования).
    """
    import re
    nav = html.split('id="panelNav"', 1)[1].split('panel-edit-gear', 1)[0]
    return re.findall(r'<div class="tab-item"[^>]*data-key="([a-z_]+)"', nav)


async def test_menu_is_rendered_in_the_saved_order(client, db_session):
    stored = ["overview", "crm", "services", "schedule", "records", "billing", "employees"]
    _, salon_id = await _make_salon(
        db_session, "+79995561001", SalonPanelMode.SOLO, sections=stored,
    )
    await _login(client, "+79995561001")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert r.status_code == 200
    assert _menu_order(r.text) == stored


async def test_overview_stays_first_in_the_menu(client, db_session):
    """«Обзор» — вход в панель и место, куда уводит скрытая ссылка."""
    _, salon_id = await _make_salon(
        db_session, "+79995561002", SalonPanelMode.SOLO,
        sections=["crm", "services", "schedule", "records", "billing", "employees"],
    )
    await _login(client, "+79995561002")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert _menu_order(r.text)[0] == "overview"


async def test_panel_has_the_настроить_button(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995561003", SalonPanelMode.SOLO)
    await _login(client, "+79995561003")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert 'id="panelEditBtn"' in r.text
    assert 'aria-pressed="false"' in r.text
    assert "Настроить панель" in r.text
    # Кнопки режима — тоже из разметки, не из JS: их подписи должен читать
    # экранный диктор, а не собирать скрипт.
    assert "Готово" in r.text and "Отмена" in r.text


async def test_hidden_sections_are_offered_to_return(client, db_session):
    """Скрытые разделы — та же «библиотека приложений»: видно, что их можно
    вернуть, но ссылки на них в панели по-прежнему нет."""
    _, salon_id = await _make_salon(db_session, "+79995561004", SalonPanelMode.SOLO)
    await _login(client, "+79995561004")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert "Скрытые разделы" in r.text
    assert 'data-key="warehouse"' in r.text, "скрытый «Склад» должно быть чем вернуть"
    # Но открыть его по-прежнему нельзя — ссылки нет.
    assert "&tab=warehouse" not in r.text


async def test_team_panel_says_there_is_nothing_hidden(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995561005", SalonPanelMode.TEAM)
    await _login(client, "+79995561005")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert "Скрытых разделов нет" in r.text


async def test_section_without_permission_is_not_offered_to_return(client, db_session):
    """Вернуть раздел, который человеку всё равно не покажут по правам, —
    обман: кнопка есть, результата нет."""
    from sqlalchemy import select

    _, salon_id = await _make_salon(db_session, "+79995561006", SalonPanelMode.SOLO)
    async with db_session() as db:
        member = (await db.execute(
            select(SalonMember).where(SalonMember.salon_id == salon_id)
        )).scalar_one()
        perms = dict(member.permissions)
        perms["manage_inventory"] = False
        member.permissions = perms
        member.is_creator = False
        await db.commit()

    await _login(client, "+79995561006")
    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert 'data-key="warehouse"' not in r.text


# ─────────────────────────── 3. Сохранение ───────────────────────────

async def test_save_keeps_the_order_and_survives_a_reload(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995562001", SalonPanelMode.SOLO)
    await _login(client, "+79995562001")

    order = ["overview", "crm", "services", "schedule", "records", "billing", "employees", "models"]
    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": order},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sections"] == order

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert _menu_order(r.text) == order


async def test_save_puts_overview_first_and_keeps_locked_sections(client, db_session):
    """Запрос можно подделать — правило держит сервер, а не разметка."""
    _, salon_id = await _make_salon(db_session, "+79995562002", SalonPanelMode.SOLO)
    await _login(client, "+79995562002")

    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": ["models", "overview"]},
    )
    assert r.status_code == 200, r.text
    saved = r.json()["sections"]
    assert saved[0] == "overview"
    assert ps.locked_keys(SalonPanelMode.SOLO) <= frozenset(saved)

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=billing")
    assert 'id="tab-billing"' in r.text


async def test_reordering_is_logged(client, db_session):
    """Состав не менялся — но и перестановку владельцу надо чем-то объяснить,
    если он спросит «почему у меня всё не так»."""
    from sqlalchemy import select

    _, salon_id = await _make_salon(db_session, "+79995562003", SalonPanelMode.SOLO)
    await _login(client, "+79995562003")

    order = _canonical(SalonPanelMode.SOLO)
    order.insert(1, order.pop())
    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": order},
    )
    assert r.status_code == 200, r.text

    async with db_session() as db:
        rows = (await db.execute(
            select(AdminAudit).where(
                AdminAudit.salon_id == salon_id, AdminAudit.action == "salon_panel_sections",
            )
        )).scalars().all()
    assert len(rows) == 1
    assert "порядок" in rows[0].detail.lower()


async def test_save_without_permission_is_refused(client, db_session):
    from sqlalchemy import select

    _, salon_id = await _make_salon(db_session, "+79995562004", SalonPanelMode.SOLO)
    async with db_session() as db:
        member = (await db.execute(
            select(SalonMember).where(SalonMember.salon_id == salon_id)
        )).scalar_one()
        perms = dict(member.permissions)
        perms["manage_salon"] = False
        member.permissions = perms
        member.is_creator = False
        await db.commit()

    await _login(client, "+79995562004")
    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": ["overview", "models"]},
    )
    assert r.status_code == 403, r.text


async def test_settings_tab_links_to_the_panel_instead_of_checkboxes(client, db_session):
    """Два интерфейса к одной настройке разъезжаются — в настройках осталась
    ссылка, а не второй список галочек."""
    _, salon_id = await _make_salon(db_session, "+79995562010", SalonPanelMode.SOLO)
    await _login(client, "+79995562010")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=edit")
    assert r.status_code == 200
    assert 'name="sections"' not in r.text, "галочек в настройках больше нет"
    assert f"/business/dashboard?salon_id={salon_id}&edit=1" in r.text
    # Выбор режима остаётся здесь же.
    assert 'name="mode" value="team"' in r.text


# ─────────────────────────── 4. Соло: мастера не добавить ───────────────────────────

async def test_solo_mode_refuses_to_create_a_master(client, db_session):
    """Кнопка — удобство, запрет — правило: страницу можно открыть в двух
    вкладках и сменить режим в одной из них."""
    from sqlalchemy import select

    _, salon_id = await _make_salon(
        db_session, "+79995563001", SalonPanelMode.SOLO, with_master=True,
    )
    await _login(client, "+79995563001")

    r = await client.post("/api/v1/master/create-web", data={
        "full_name": "Наёмный мастер", "phone": "+79995563099",
        "specialization": "Брови", "experience_years": "0", "salon_id": str(salon_id),
    })
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "solo_mode"
    assert "у меня команда" in body["detail"]

    async with db_session() as db:
        masters = (await db.execute(
            select(Master).where(Master.salon_id == salon_id)
        )).scalars().all()
    assert len(masters) == 1, "в соло-режиме второй мастер не должен появиться"


async def test_team_mode_still_creates_a_master(client, db_session):
    from sqlalchemy import select

    _, salon_id = await _make_salon(db_session, "+79995563002", SalonPanelMode.TEAM)
    await _login(client, "+79995563002")

    r = await client.post("/api/v1/master/create-web", data={
        "full_name": "Наёмный мастер", "phone": "+79995563098",
        "specialization": "Брови", "experience_years": "0", "salon_id": str(salon_id),
    })
    assert r.status_code == 200, r.text
    async with db_session() as db:
        masters = (await db.execute(
            select(Master).where(Master.salon_id == salon_id)
        )).scalars().all()
    assert len(masters) == 1


async def test_solo_owner_can_still_create_their_own_card(client, db_session):
    """Запрет на найм не должен закрыть единственный путь завести себя."""
    from sqlalchemy import select

    _, salon_id = await _make_salon(db_session, "+79995563003", SalonPanelMode.SOLO)
    await _login(client, "+79995563003")

    r = await client.post(
        "/api/v1/business/my-salon/master-card",
        data={"salon_id": str(salon_id), "specialization": "Маникюр"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    async with db_session() as db:
        masters = (await db.execute(
            select(Master).where(Master.salon_id == salon_id)
        )).scalars().all()
    assert len(masters) == 1


async def test_checkout_hides_the_employee_count_in_solo(client):
    """Платить за троих и не мочь их завести — обман (решение 0007, п. 7)."""
    r = await client.get("/business/checkout?plan=lite")
    assert r.status_code == 200
    # Поле есть в разметке, но показывает его только режим «у меня команда»…
    assert "employee-count-wrap" in r.text
    assert "!forMaster && !panelModeIsSolo()) ? '' : 'none'" in r.text, (
        "видимость поля должна зависеть от режима"
    )
    # …а в соло уходит единица, а не то, что осталось в скрытом поле.
    assert "} else if (panelModeIsSolo()) {" in r.text
    assert "employeeCount = 1;" in r.text
