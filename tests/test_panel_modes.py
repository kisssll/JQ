"""Режимы бизнес-панели: «работаю один» и «у меня команда» (решение 0007).

Проверяем три разные вещи, и нарочно не смешиваем их в одном тесте:
  1. правила видимости как чистые функции (без БД и HTTP) — сервис panel_sections;
  2. панель: меню, прямая ссылка на выключенный раздел, переименование «Сотрудников»;
  3. подключение и настройки: откуда берётся режим и что попадает в журнал салона.
"""
import pytest
from types import SimpleNamespace

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
    SalonPanelMode, Master, AdminAudit, OWNER_DEFAULT_PERMISSIONS,
)
from app.services import panel_sections as ps


# ─────────────────────────── 1. Правила видимости ───────────────────────────

def _salon(mode, stored=None):
    """Достаточно объекта с двумя полями — сервис не должен требовать ORM/БД."""
    return SimpleNamespace(panel_mode=mode, panel_sections=stored)


def test_solo_default_is_the_short_set():
    assert ps.default_keys(SalonPanelMode.SOLO) == frozenset({
        "overview", "employees", "services", "schedule", "records", "crm",
        "reviews", "promos", "models", "billing", "instructions",
    })


def test_team_default_is_everything():
    assert ps.default_keys(SalonPanelMode.TEAM) == frozenset(ps.ALL_KEYS)


def test_solo_hides_exactly_the_four_team_sections():
    """Соло отличается от команды пятью разделами, и причины у них разные —
    если список разделов вырастет, этот тест заставит решить, куда его отнести.

    Четыре раздела ВЫКЛЮЧЕНЫ по умолчанию: они существуют только при штате, но
    владелец может включить их сам. «Редактировать салон» не выключен, а НЕ
    СУЩЕСТВУЕТ в этом режиме — его содержимое переехало в «Мою карточку
    мастера» (решение 0009, п. 2), и вернуть раздел нельзя ничем."""
    assert frozenset(ps.ALL_KEYS) - ps.default_keys(SalonPanelMode.SOLO) == frozenset(
        {"analytics", "payroll", "cost", "warehouse", "edit"}
    )
    assert ps.unavailable_keys(SalonPanelMode.SOLO) == frozenset({"edit"})
    assert ps.unavailable_keys(SalonPanelMode.TEAM) == frozenset()
    # А эти четыре именно выключены: владелец их включает в самой панели.
    assert {"analytics", "payroll", "cost", "warehouse"} <= ps.available_keys(
        SalonPanelMode.SOLO
    )


def test_models_enabled_in_both_modes():
    """Решение владельца: «Модели» — отличительная черта сервиса, не прячем."""
    assert "models" in ps.default_keys(SalonPanelMode.SOLO)
    assert "models" in ps.default_keys(SalonPanelMode.TEAM)


def test_empty_stored_means_follow_the_mode():
    """Пустое значение — «как по режиму», чтобы смена режима обновляла набор сама."""
    assert ps.enabled_keys(_salon(SalonPanelMode.SOLO, None)) == ps.default_keys(SalonPanelMode.SOLO)
    assert ps.enabled_keys(_salon(SalonPanelMode.SOLO, [])) == ps.default_keys(SalonPanelMode.SOLO)
    assert ps.enabled_keys(_salon(SalonPanelMode.TEAM, None)) == ps.default_keys(SalonPanelMode.TEAM)


def test_stored_list_overrides_the_mode_default():
    salon = _salon(SalonPanelMode.SOLO, ["overview", "warehouse"])
    enabled = ps.enabled_keys(salon)
    assert "warehouse" in enabled          # владелец включил вручную
    assert "crm" not in enabled            # и выключил то, что давал режим


def test_locked_sections_survive_any_stored_list():
    """Обзор, Услуги, Расписание, Записи, Тариф, Настройки не гаснут никогда."""
    assert ps.LOCKED_KEYS == frozenset(
        {"overview", "services", "schedule", "records", "billing", "edit"}
    )
    assert ps.locked_keys(SalonPanelMode.TEAM) == ps.LOCKED_KEYS
    enabled = ps.enabled_keys(_salon(SalonPanelMode.TEAM, ["models"]))
    assert ps.LOCKED_KEYS <= enabled


def test_solo_cannot_switch_off_the_section_that_holds_the_mode_switch():
    """Главный риск переноса (решение 0009, п. 3): переключатель режима живёт в
    «Моей карточке мастера», и если бы раздел можно было выключить, соло-мастер
    запер бы себя в соло навсегда — нанять человека стало бы нечем."""
    assert ps.locked_keys(SalonPanelMode.SOLO) == frozenset(
        {"overview", "services", "schedule", "records", "billing", "employees"}
    )
    enabled = ps.enabled_keys(_salon(SalonPanelMode.SOLO, ["models"]))
    assert "employees" in enabled
    # И через эндпоинт тоже не выключить — normalize дописывает обязательные.
    assert "employees" in ps.normalize(SalonPanelMode.SOLO, ["models"])


def test_solo_never_gets_the_edit_section_back():
    """Ключ мог остаться в сохранённом JSON (список пережил смену режима,
    кто-то поправил столбец руками). Возвращать раздел нельзя: его формы уже
    живут в «Моей карточке мастера», вышло бы два источника правды."""
    stored = ["overview", "edit", "crm"]
    assert "edit" not in ps.ordered_keys(_salon(SalonPanelMode.SOLO, stored))
    assert "edit" not in (ps.normalize(SalonPanelMode.SOLO, stored) or [])
    # В команде ровно наоборот — раздел обязательный.
    assert "edit" in ps.ordered_keys(_salon(SalonPanelMode.TEAM, stored))


def test_unknown_stored_key_is_ignored():
    """Список хранится как JSON: переименовали раздел — панель не должна падать."""
    enabled = ps.enabled_keys(_salon(SalonPanelMode.TEAM, ["overview", "no_such_tab"]))
    assert "no_such_tab" not in enabled


def test_normalize_returns_none_when_the_choice_equals_the_mode_default():
    """Вернул набор к «как по режиму» — храним пусто, а не копию списка.

    Сравнивается и порядок: с тех пор как порядок разделов принадлежит
    владельцу (дополнение 30.09), «как по режиму» — это канонический порядок,
    а не любой набор тех же ключей. Подробнее — tests/test_panel_edit.py.
    """
    canonical_solo = [k for k in ps.ALL_KEYS if k in ps.default_keys(SalonPanelMode.SOLO)]
    assert ps.normalize(SalonPanelMode.SOLO, canonical_solo) is None
    assert ps.normalize(SalonPanelMode.TEAM, ps.ALL_KEYS) is None


def test_normalize_keeps_locked_and_drops_junk():
    stored = ps.normalize(SalonPanelMode.SOLO, ["models", "no_such_tab"])
    assert stored is not None
    assert ps.locked_keys(SalonPanelMode.SOLO) <= frozenset(stored)
    assert "no_such_tab" not in stored
    assert "models" in stored


def test_employees_section_is_renamed_in_solo():
    assert ps.label("employees", SalonPanelMode.SOLO) == "Моя карточка мастера"
    assert ps.label("employees", SalonPanelMode.TEAM) == "Сотрудники"
    # Остальные подписи от режима не зависят.
    assert ps.label("services", SalonPanelMode.SOLO) == ps.label("services", SalonPanelMode.TEAM)


def test_mode_for_master_count_is_the_migration_rule():
    """Тот же порог, по которому миграция разводит существующие салоны."""
    assert ps.mode_for_master_count(0) is SalonPanelMode.SOLO
    assert ps.mode_for_master_count(1) is SalonPanelMode.SOLO
    assert ps.mode_for_master_count(2) is SalonPanelMode.TEAM
    assert ps.mode_for_master_count(3) is SalonPanelMode.TEAM


# ─────────────────────────── 2. Панель ───────────────────────────

async def _make_salon(db_session, phone, mode, *, with_master=False, sections=None):
    async with db_session() as db:
        owner = User(
            phone=phone, full_name="Хозяин",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name="Режимный", address="ул. Тестовая, 2", phone="+70000000901",
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


async def test_solo_menu_shows_the_short_set(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995551001", SalonPanelMode.SOLO)
    await _login(client, "+79995551001")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert r.status_code == 200
    for hidden in ("&tab=analytics", "&tab=payroll", "&tab=cost", "&tab=warehouse"):
        assert hidden not in r.text, f"соло-панель не должна показывать {hidden}"
    for shown in ("&tab=models", "&tab=crm", "&tab=reviews", "&tab=promos"):
        assert shown in r.text, f"соло-панель должна показывать {shown}"


async def test_team_menu_shows_everything(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995551002", SalonPanelMode.TEAM)
    await _login(client, "+79995551002")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert r.status_code == 200
    for slug in ps.ALL_KEYS:
        assert f"&tab={slug}" in r.text, f"команде не показали раздел {slug}"


@pytest.mark.parametrize("hidden_tab", ["analytics", "payroll", "cost", "warehouse"])
async def test_hidden_section_is_not_reachable_by_direct_link(client, db_session, hidden_tab):
    """Выключенный раздел не только исчезает из меню — по ссылке он даёт «Обзор»,
    а не пустую страницу и не 500."""
    _, salon_id = await _make_salon(db_session, f"+7999555200{['analytics','payroll','cost','warehouse'].index(hidden_tab)}", SalonPanelMode.SOLO)
    await _login(client, f"+7999555200{['analytics','payroll','cost','warehouse'].index(hidden_tab)}")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab={hidden_tab}")
    assert r.status_code == 200
    assert f'id="tab-{hidden_tab}"' not in r.text
    assert 'id="tab-overview"' in r.text


async def test_hidden_section_is_not_reachable_as_partial(client, db_session):
    """partial=1 — тот же вход в панель, и он тоже должен быть закрыт."""
    _, salon_id = await _make_salon(db_session, "+79995552010", SalonPanelMode.SOLO)
    await _login(client, "+79995552010")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=warehouse&partial=1")
    assert r.status_code == 200
    assert 'id="tab-warehouse"' not in r.text
    assert 'id="tab-overview"' in r.text


async def test_solo_calls_employees_tab_my_master_card(client, db_session):
    _, salon_id = await _make_salon(
        db_session, "+79995552020", SalonPanelMode.SOLO, with_master=True,
    )
    await _login(client, "+79995552020")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert r.status_code == 200
    assert "Моя карточка мастера" in r.text
    assert "Добавить мастера" not in r.text
    assert "Добавить участника" not in r.text


async def test_team_employees_tab_is_unchanged(client, db_session):
    _, salon_id = await _make_salon(
        db_session, "+79995552021", SalonPanelMode.TEAM, with_master=True,
    )
    await _login(client, "+79995552021")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert r.status_code == 200
    assert "Моя карточка мастера" not in r.text
    assert "Добавить мастера" in r.text


async def test_solo_without_master_card_offers_to_create_it(client, db_session):
    """Ровно та дыра, из-за которой салон на проде остался с нулём мастеров:
    в соло-режиме найма нет, значит завести себя должно быть чем-то одним."""
    _, salon_id = await _make_salon(db_session, "+79995552022", SalonPanelMode.SOLO)
    await _login(client, "+79995552022")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert r.status_code == 200
    assert "Создать мою карточку мастера" in r.text


# ─────────────────────────── 3. Настройки и подключение ───────────────────────────

async def test_owner_turns_a_section_on_and_it_appears(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995553001", SalonPanelMode.SOLO)
    await _login(client, "+79995553001")

    keys = sorted(ps.default_keys(SalonPanelMode.SOLO) | {"warehouse"})
    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": keys},
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert "&tab=warehouse" in r.text
    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=warehouse")
    assert 'id="tab-warehouse"' in r.text


async def test_locked_section_cannot_be_turned_off_through_the_endpoint(client, db_session):
    """Переключателя у обязательного раздела нет — но и подделанная форма
    не должна его погасить."""
    _, salon_id = await _make_salon(db_session, "+79995553002", SalonPanelMode.SOLO)
    await _login(client, "+79995553002")

    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": ["models"]},
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=billing")
    assert 'id="tab-billing"' in r.text


async def test_mode_switch_is_saved_and_logged(client, db_session):
    owner_id, salon_id = await _make_salon(db_session, "+79995553003", SalonPanelMode.SOLO)
    await _login(client, "+79995553003")

    r = await client.post(
        "/api/v1/business/my-salon/panel-mode",
        data={"salon_id": str(salon_id), "mode": "team"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert "&tab=analytics" in r.text, "после перехода в «команду» набор должен смениться сам"

    async with db_session() as db:
        from sqlalchemy import select
        rows = (await db.execute(
            select(AdminAudit).where(
                AdminAudit.salon_id == salon_id, AdminAudit.action == "salon_panel_mode",
            )
        )).scalars().all()
    assert len(rows) == 1, "смена режима должна попасть в журнал салона"
    assert rows[0].actor_id == owner_id


async def test_mode_switch_resets_the_owner_edits(client, db_session):
    """Иначе человек переключился бы в «команду» и не увидел ни аналитики, ни
    склада: их гасил бы список, сохранённый в соло-режиме."""
    _, salon_id = await _make_salon(
        db_session, "+79995553010", SalonPanelMode.SOLO,
        # Соло-набор, из которого владелец вычеркнул «Модели» и «Клиентов».
        sections=sorted(ps.default_keys(SalonPanelMode.SOLO) - {"models", "crm"}),
    )
    await _login(client, "+79995553010")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert "&tab=models" not in r.text, "правка владельца должна была погасить «Модели»"

    r = await client.post(
        "/api/v1/business/my-salon/panel-mode",
        data={"salon_id": str(salon_id), "mode": "team"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    for slug in ps.ALL_KEYS:
        assert f"&tab={slug}" in r.text, (
            f"после перехода в «команду» набор должен стать полным, нет {slug}"
        )

    async with db_session() as db:
        from sqlalchemy import select
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
    assert salon.panel_sections is None, "набор должен вернуться к «как по режиму»"


async def test_section_toggle_is_logged(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995553004", SalonPanelMode.SOLO)
    await _login(client, "+79995553004")

    keys = sorted(ps.default_keys(SalonPanelMode.SOLO) | {"cost"})
    await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": keys},
    )
    async with db_session() as db:
        from sqlalchemy import select
        rows = (await db.execute(
            select(AdminAudit).where(
                AdminAudit.salon_id == salon_id, AdminAudit.action == "salon_panel_sections",
            )
        )).scalars().all()
    assert len(rows) == 1


async def test_settings_tab_has_the_mode_switch(client, db_session):
    """Набор разделов из настроек переехал в саму панель (дополнение 30.09,
    проверка — tests/test_panel_edit.py), а выбор режима остался здесь: он про
    устройство бизнеса, а не про оформление панели."""
    _, salon_id = await _make_salon(db_session, "+79995553005", SalonPanelMode.SOLO)
    await _login(client, "+79995553005")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=edit")
    assert r.status_code == 200
    assert "Разделы панели" in r.text
    assert 'name="mode" value="solo"' in r.text
    assert 'name="mode" value="team"' in r.text


async def test_apply_in_solo_mode_creates_the_owner_master_card(client, db_session):
    async with db_session() as db:
        u = User(
            phone="+79995554001", full_name="Соло",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT,
        )
        db.add(u)
        await db.commit()
    await _login(client, "+79995554001")

    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Соло-студия", "phone": "+79995554001", "plan": "lite",
        "offer_accepted": "1", "pd_consent": "1", "panel_mode": "solo",
    })
    assert r.status_code == 200, r.text
    salon_id = r.json()["salon_id"]

    async with db_session() as db:
        from sqlalchemy import select
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        assert salon.panel_mode is SalonPanelMode.SOLO
        masters = (await db.execute(select(Master).where(Master.salon_id == salon_id))).scalars().all()
    assert len(masters) == 1, "в соло-режиме владелец заводится мастером сам"


async def test_apply_in_team_mode_does_not_create_a_master(client, db_session):
    async with db_session() as db:
        u = User(
            phone="+79995554002", full_name="Команда",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT,
        )
        db.add(u)
        await db.commit()
    await _login(client, "+79995554002")

    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Салон с командой", "phone": "+79995554002", "plan": "business",
        "offer_accepted": "1", "pd_consent": "1", "panel_mode": "team",
    })
    assert r.status_code == 200, r.text
    salon_id = r.json()["salon_id"]

    async with db_session() as db:
        from sqlalchemy import select
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        assert salon.panel_mode is SalonPanelMode.TEAM
        masters = (await db.execute(select(Master).where(Master.salon_id == salon_id))).scalars().all()
    assert masters == []


async def test_apply_for_master_stays_solo_without_asking(client, db_session):
    async with db_session() as db:
        u = User(
            phone="+79995554003", full_name="Частный мастер",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT,
        )
        db.add(u)
        await db.commit()
    await _login(client, "+79995554003")

    # for_master приходит с лендинга и режим не спрашивает; даже если в форму
    # подсунуть team, ответ уже известен.
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Анна Смирнова", "phone": "+79995554003", "plan": "lite",
        "offer_accepted": "1", "pd_consent": "1", "for_master": "1",
        "specialization": "Маникюр", "panel_mode": "team",
    })
    assert r.status_code == 200, r.text
    async with db_session() as db:
        from sqlalchemy import select
        salon = (await db.execute(
            select(Salon).where(Salon.id == r.json()["salon_id"])
        )).scalar_one()
    assert salon.panel_mode is SalonPanelMode.SOLO


async def test_solo_owner_creates_master_card_from_the_panel(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995554010", SalonPanelMode.SOLO)
    await _login(client, "+79995554010")

    r = await client.post(
        "/api/v1/business/my-salon/master-card",
        data={"salon_id": str(salon_id), "specialization": "Брови"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text

    async with db_session() as db:
        from sqlalchemy import select
        masters = (await db.execute(select(Master).where(Master.salon_id == salon_id))).scalars().all()
    assert len(masters) == 1
    assert masters[0].specialization == "Брови"


async def test_checkout_asks_about_the_mode(client):
    r = await client.get("/business/checkout?plan=lite")
    assert r.status_code == 200
    assert 'type="radio" name="panel_mode" value="solo"' in r.text
    assert 'type="radio" name="panel_mode" value="team"' in r.text
    assert "Вы работаете один или с командой?" in r.text


async def test_master_checkout_does_not_ask_about_the_mode(client):
    """У частного мастера ответ уже известен — вопрос лишний."""
    r = await client.get("/business/checkout?plan=lite&for=master")
    assert r.status_code == 200
    assert 'type="radio" name="panel_mode"' not in r.text
    assert "Вы работаете один или с командой?" not in r.text


async def test_solo_master_card_keeps_photo_but_not_delete(client, db_session):
    """В соло-режиме карточка — своя собственная: фото и портфолио нужны
    (без них нечего показать клиенту), а «удалить» вернуло бы человека в то же
    состояние «ко мне нельзя записаться». Одинаково в таблице и в карточках
    для телефона — раньше они разъезжались."""
    _, salon_id = await _make_salon(
        db_session, "+79995555001", SalonPanelMode.SOLO, with_master=True,
    )
    await _login(client, "+79995555001")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert r.status_code == 200
    assert r.text.count('title="Фото и портфолио"') == 2, "фото нужны в обоих видах"
    assert 'title="Удалить"' not in r.text
    assert 'title="Сбросить пароль"' not in r.text


async def test_team_master_card_keeps_all_actions(client, db_session):
    _, salon_id = await _make_salon(
        db_session, "+79995555002", SalonPanelMode.TEAM, with_master=True,
    )
    await _login(client, "+79995555002")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert r.text.count('title="Фото и портфолио"') == 2
    assert r.text.count('title="Удалить"') == 2
    assert r.text.count('title="Сбросить пароль"') == 2


async def test_second_click_on_create_master_card_does_not_break(client, db_session):
    """Двойной клик по кнопке уже ломал регистрацию (см. историю проекта):
    второй запрос должен молча привести туда же, а не отдать 500."""
    _, salon_id = await _make_salon(db_session, "+79995555003", SalonPanelMode.SOLO)
    await _login(client, "+79995555003")

    for _ in range(2):
        r = await client.post(
            "/api/v1/business/my-salon/master-card",
            data={"salon_id": str(salon_id), "specialization": "Маникюр"},
            follow_redirects=False,
        )
        assert r.status_code == 302, r.text

    async with db_session() as db:
        from sqlalchemy import select
        masters = (await db.execute(select(Master).where(Master.salon_id == salon_id))).scalars().all()
    assert len(masters) == 1


async def test_solo_owner_who_is_master_elsewhere_gets_an_explanation(client, db_session):
    """Мастер у человека может быть только один (masters.user_id уникален).
    Владельцу второго салона кнопка «создать карточку» не поможет — она молча
    ничего не сделает, поэтому вместо неё объясняем, почему."""
    from sqlalchemy import select

    _, first_salon = await _make_salon(
        db_session, "+79995556001", SalonPanelMode.SOLO, with_master=True,
    )
    # Второй салон того же владельца — без мастера.
    async with db_session() as db:
        owner = (await db.execute(select(User).where(User.phone == "+79995556001"))).scalar_one()
        second = Salon(
            name="Второй", address="ул. Тестовая, 3", phone="+70000000902",
            latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=SalonPanelMode.SOLO,
        )
        db.add(second)
        await db.commit()
        await db.refresh(second)
        db.add(SalonMember(
            salon_id=second.id, user_id=owner.id, role=SalonRole.OWNER,
            is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        await db.commit()
        second_id = second.id

    await _login(client, "+79995556001")
    r = await client.get(f"/business/dashboard?salon_id={second_id}&tab=employees")
    assert r.status_code == 200
    assert "Создать мою карточку мастера" not in r.text, (
        "кнопка, которая заведомо ничего не сделает, хуже объяснения"
    )
    assert "уже заведены мастером" in r.text


async def test_solo_still_shows_existing_co_owners(client, db_session):
    """Салон с командой переключили в «работаю один», а совладелец остался.
    Прятать его целиком нельзя: тогда снять его будет неоткуда. Показываем
    список, но без приглашения новых — найма в соло по-прежнему нет."""
    from sqlalchemy import select

    owner_id, salon_id = await _make_salon(
        db_session, "+79995557001", SalonPanelMode.SOLO, with_master=True,
    )
    async with db_session() as db:
        mate = User(
            phone="+79995557002", full_name="Совладелец",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS,
        )
        db.add(mate)
        await db.commit()
        await db.refresh(mate)
        db.add(SalonMember(
            salon_id=salon_id, user_id=mate.id, role=SalonRole.OWNER,
            is_creator=False, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        await db.commit()

    await _login(client, "+79995557001")
    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert r.status_code == 200
    assert "Совладелец" in r.text, "совладельца нельзя прятать — его надо чем-то снимать"
    assert "Добавить участника" not in r.text, "но приглашать новых в соло нельзя"


async def test_solo_alone_has_no_members_section(client, db_session):
    """А когда владелец действительно один, список из одного себя — шум."""
    _, salon_id = await _make_salon(
        db_session, "+79995557010", SalonPanelMode.SOLO, with_master=True,
    )
    await _login(client, "+79995557010")
    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert "Участники салона" not in r.text
