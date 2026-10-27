"""Мастер и владелец одновременно (решение 0015, п. 5).

Роль у человека одна, а заявка на салон переписывает её в BUSINESS. Поэтому
мастерские разделы открываются по факту активной карточки мастера, а не по
role. Проверяем обе стороны: кто должен войти — входит; у кого карточки нет —
не входит, даже со старой role=MASTER; и данные по-прежнему только свои.
"""
import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    InventoryItem, Master, OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember,
    SalonModerationStatus, SalonPanelMode, SalonRole, User, UserRole,
)


async def _user(db, phone, role=UserRole.CLIENT, name="Тест Тестов"):
    u = User(
        phone=phone, full_name=name, role=role, is_active=True,
        hashed_password=get_password_hash("Testpass1"),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _salon(db, owner, name, mode=SalonPanelMode.TEAM):
    s = Salon(
        name=name, address="Томск, ул. Ленина, 1", phone="+73822000111",
        latitude=56.4, longitude=84.9, timezone="Asia/Tomsk",
        moderation_status=SalonModerationStatus.APPROVED, is_active=True,
        creator_id=owner.id, panel_mode=mode,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    db.add(SalonMember(
        salon_id=s.id, user_id=owner.id, role=SalonRole.OWNER, is_creator=True,
        permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
    ))
    await db.commit()
    return s


async def _card(db, user, salon, active=True):
    m = Master(
        user_id=user.id, salon_id=salon.id, specialization="Маникюр",
        experience_years=1, rating=0.0, is_active=active,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def _login(client, phone):
    r = await client.post(
        "/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"},
    )
    assert r.status_code == 302, r.text


MASTER_PAGES_API = ("/api/v1/master/schedule", "/api/v1/inventory/my/stock")


# ─────────────── 1. Мастерские разделы — по карточке, не по роли ───────────────

async def test_owner_who_is_a_master_keeps_master_sections(client, db_session):
    """Заявка на салон сделала role=BUSINESS, но карточка мастера осталась —
    склад и расписание должны открываться, как и до заявки."""
    async with db_session() as db:
        owner = await _user(db, "+79996660001", UserRole.BUSINESS)
        salon = await _salon(db, owner, "Свой салон")
        await _card(db, owner, salon)
    await _login(client, "+79996660001")

    for path in MASTER_PAGES_API:
        r = await client.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
    r = await client.get("/master/inventory", follow_redirects=False)
    assert r.status_code == 200, "владельца-мастера выкинуло со своего склада"
    assert "Профиль мастера не найден" not in r.text


@pytest.mark.parametrize("card", ["none", "inactive"])
async def test_stale_master_role_without_a_card_is_not_enough(client, db_session, card):
    """role=MASTER, оставшаяся с прошлого, доступа больше не даёт: карточку
    сняли или отключили — мастерских разделов нет."""
    phone = "+79996660002" if card == "none" else "+79996660003"
    async with db_session() as db:
        owner = await _user(db, "+79996660009" if card == "none" else "+79996660008", UserRole.BUSINESS)
        salon = await _salon(db, owner, "Салон")
        former = await _user(db, phone, UserRole.MASTER)
        if card == "inactive":
            await _card(db, former, salon, active=False)
    await _login(client, phone)

    for path in MASTER_PAGES_API:
        r = await client.get(path)
        assert r.status_code == 403, f"{path}: {r.status_code}"
    r = await client.post(
        "/api/v1/inventory/my/consumption",
        json={"booking_id": 1, "items": [{"item_id": 1, "quantity": 1}]},
    )
    assert r.status_code == 403
    r = await client.get("/master/inventory", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"


async def test_master_sees_only_the_stock_of_own_salon(client, db_session):
    """Доступ по карточке не расширяет данные: склад берётся из салона, где
    лежит карточка, а не из салона, которым человек владеет или нет."""
    async with db_session() as db:
        anya = await _user(db, "+79996660011", UserRole.BUSINESS, "Аня")
        anyas = await _salon(db, anya, "Салон Ани")
        stranger = await _user(db, "+79996660012", UserRole.BUSINESS, "Чужой")
        other = await _salon(db, stranger, "Чужой салон")
        master = await _user(db, "+79996660013", UserRole.MASTER, "Мастер Ани")
        await _card(db, master, anyas)
        db.add_all([
            InventoryItem(salon_id=anyas.id, name="Гель Ани", unit="мл", cost_per_unit=10),
            InventoryItem(salon_id=other.id, name="Гель чужой", unit="мл", cost_per_unit=10),
        ])
        await db.commit()
    await _login(client, "+79996660013")

    r = await client.get("/api/v1/inventory/my/stock")
    assert r.status_code == 200
    names = {i["name"] for i in r.json()}
    assert names == {"Гель Ани"}


# ─────────────── 2. В команде владелец заводит себя мастером ───────────────

async def test_team_owner_without_a_card_is_offered_one(client, db_session):
    async with db_session() as db:
        owner = await _user(db, "+79996660021", UserRole.BUSINESS, "Хозяйка")
        salon = await _salon(db, owner, "Командный")
        hired = await _user(db, "+79996660022", UserRole.MASTER, "Нанятая")
        await _card(db, hired, salon)
        salon_id = salon.id
    await _login(client, "+79996660021")

    page = f"/business/dashboard?salon_id={salon_id}&tab=employees"
    r = await client.get(page)
    assert r.status_code == 200
    assert "Вы тоже принимаете клиентов?" in r.text
    assert "Создать мою карточку мастера" in r.text

    r = await client.post(
        "/api/v1/business/my-salon/master-card",
        data={"salon_id": str(salon_id), "specialization": "Стрижки"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    async with db_session() as db:
        mine = (await db.execute(
            select(Master).where(Master.user_id == owner.id)
        )).scalar_one()
    assert mine.salon_id == salon_id and mine.specialization == "Стрижки"

    r = await client.get(page)
    assert "Вы тоже принимаете клиентов?" not in r.text, "карточка уже есть — предлагать нечего"


# ─────────────── 3–4. Мастер чужого салона со своим салоном ───────────────

async def _anyas_master_with_own_salon(db_session):
    """Мастер Ани открыл свой командный салон. Плюс третий салон — чтобы
    проверить, что его панель не открыть подстановкой salon_id."""
    async with db_session() as db:
        anya = await _user(db, "+79996660031", UserRole.BUSINESS, "Аня")
        anyas = await _salon(db, anya, "Салон Ани")
        me = await _user(db, "+79996660032", UserRole.BUSINESS, "Мастер Ани")
        await _card(db, me, anyas)
        mine = await _salon(db, me, "Мой салон")
        third_owner = await _user(db, "+79996660033", UserRole.BUSINESS, "Третий")
        third = await _salon(db, third_owner, "Третий салон")
        hired = await _user(db, "+79996660034", UserRole.MASTER, "Мастер третьего")
        await _card(db, hired, third)
        return mine.id, third.id


async def test_elsewhere_text_tells_the_truth_about_someone_elses_salon(client, db_session):
    mine_id, _ = await _anyas_master_with_own_salon(db_session)
    await _login(client, "+79996660032")

    r = await client.get(f"/business/dashboard?salon_id={mine_id}&tab=employees")
    assert r.status_code == 200
    assert "Вы мастер в салоне «Салон Ани»" in r.text
    assert "своём салоне" not in r.text and "вашем салоне" not in r.text, (
        "салон Ани не его — прежний текст здесь врал"
    )
    assert "Создать мою карточку мастера" not in r.text, "кнопка ничего бы не сделала"
    assert 'href="/business/dashboard?as=master"' in r.text


async def test_own_salon_wins_but_master_panel_has_an_entry(client, db_session):
    mine_id, _ = await _anyas_master_with_own_salon(db_session)
    await _login(client, "+79996660032")

    r = await client.get("/business/dashboard")
    assert r.status_code == 200
    assert "Панель мастера · Салон Ани" in r.text

    r = await client.get("/business/dashboard?as=master")
    assert r.status_code == 200
    assert "Салон Ани" in r.text and "· Панель мастера" in r.text
    assert 'href="/business/dashboard" ' in r.text and "Моя бизнес-панель" in r.text


async def test_as_master_cannot_open_someone_elses_panel(client, db_session):
    """Параметр выбирает вид, а не салон: салон берётся из карточки."""
    _, third_id = await _anyas_master_with_own_salon(db_session)
    await _login(client, "+79996660032")

    r = await client.get(f"/business/dashboard?as=master&salon_id={third_id}")
    assert r.status_code == 200
    assert "Третий салон" not in r.text
    assert "Салон Ани" in r.text


async def test_as_master_without_a_card_is_just_the_own_panel(client, db_session):
    async with db_session() as db:
        owner = await _user(db, "+79996660041", UserRole.MASTER, "Без карточки")
        await _salon(db, owner, "Просто салон")
        other_owner = await _user(db, "+79996660042", UserRole.BUSINESS, "Другой")
        other = await _salon(db, other_owner, "Чужая панель")
        hired = await _user(db, "+79996660043", UserRole.MASTER)
        await _card(db, hired, other)
    await _login(client, "+79996660041")

    r = await client.get("/business/dashboard?as=master")
    assert r.status_code == 200
    assert "· Панель мастера" not in r.text
    assert "Чужая панель" not in r.text
    assert "Панель мастера ·" not in r.text, "ссылки на чужую панель быть не должно"


async def test_no_master_entry_when_the_card_is_in_the_own_salon(client, db_session):
    """Владелец-мастер своего же салона и так видит всё в своей панели."""
    async with db_session() as db:
        owner = await _user(db, "+79996660051", UserRole.BUSINESS)
        salon = await _salon(db, owner, "Свой")
        await _card(db, owner, salon)
    await _login(client, "+79996660051")
    r = await client.get("/business/dashboard")
    assert "as=master" not in r.text
