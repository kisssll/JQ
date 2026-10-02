"""Состав главного экрана панели — вкладки «Обзор» (решение 0007, п. 6, заход 2).

Проверяем не вёрстку, а СОСТАВ и ПОРЯДОК блоков: что соло-мастер видит ответ
«можно ли ко мне записаться» и ссылку с QR, что пустых счётчиков и графика у
него нет, что салону с командой прежние блоки оставили, а панель наёмного
мастера не трогали вовсе.
"""
import json
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember,
    SalonModerationStatus, SalonPanelMode, SalonRole, Schedule, Service, User, UserRole,
)

_WEEK_OPEN = json.dumps({d: "10:00-20:00" for d in
                         ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})

# Признаки блоков в разметке — по ним и опознаём состав экрана.
READINESS = 'class="readiness readiness-'
BOOKING_LINK = 'class="booking-link-title"'
MODELS_INVITE = 'class="models-invite-title"'
STATS = 'class="stats-grid-4"'
CHART = 'Выручка за неделю'


async def _salon(db_session, phone, mode, *, with_master=True, with_service=True,
                 hours=True, published=True, booking=False, name=None):
    async with db_session() as db:
        owner = User(phone=phone, full_name="Ольга Мастерова",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name=name or f"Обзор {phone}", address="Томск, ул. Ленина, 1",
            phone="+73822000777", latitude=56.4, longitude=84.9, timezone="Asia/Tomsk",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=mode,
            working_hours=_WEEK_OPEN if hours else None,
            guest_booking_enabled=True,
            access_until=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        if not published:
            salon.published_at = None
        db.add(SalonMember(
            salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER, is_creator=True,
            permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        await db.commit()

        if with_master:
            master = Master(user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
                            experience_years=3, rating=0.0, is_active=True)
            db.add(master)
            await db.commit()
            await db.refresh(master)
            if with_service:
                svc = Service(master_id=master.id, name="Маникюр", price=2000,
                              duration_minutes=60, is_active=True, is_model_practice=False)
                db.add(svc)
            for wd in range(5):
                db.add(Schedule(master_id=master.id, day_of_week=wd,
                                start_time=time(10, 0), end_time=time(19, 0)))
            await db.commit()

            if booking and with_service:
                svc = (await db.execute(
                    select(Service).where(Service.master_id == master.id)
                )).scalars().first()
                client = User(phone=phone.replace("+7999", "+7988"), full_name="Клиент",
                              hashed_password=get_password_hash("Testpass1"),
                              role=UserRole.CLIENT, is_active=True)
                db.add(client)
                await db.commit()
                await db.refresh(client)
                start = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
                db.add(Booking(client_id=client.id, master_id=master.id, service_id=svc.id,
                               start_time=start, end_time=start + timedelta(minutes=60),
                               status=BookingStatus.CONFIRMED, final_price=2000))
                await db.commit()
        return owner.id, salon.id


async def _open(client, phone, salon_id):
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": phone, "password": "Testpass1"})
    assert r.status_code == 302, r.text
    page = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert page.status_code == 200
    return page.text


# ─────────────────────────── соло-режим ───────────────────────────

async def test_solo_overview_answers_the_booking_question_and_gives_the_link(client, db_session):
    _, salon_id = await _salon(db_session, "+79996660001", SalonPanelMode.SOLO)
    html = await _open(client, "+79996660001", salon_id)
    assert READINESS in html, "соло-мастеру отвечаем всегда, даже когда всё хорошо"
    assert "Записаться к вам можно" in html
    assert BOOKING_LINK in html
    assert f"/book/{salon_id}/qr" in html
    assert MODELS_INVITE in html


def _order(html, *marks):
    return [html.index(m) for m in marks]


async def test_solo_overview_puts_the_answer_and_the_link_first(client, db_session):
    """Порядок — часть задачи: ссылка должна быть на первом экране, а не под
    графиком. Проверяем позициями в разметке, а не глазами."""
    _, salon_id = await _salon(db_session, "+79996660002", SalonPanelMode.SOLO, booking=True)
    html = await _open(client, "+79996660002", salon_id)
    body = html[html.index('id="tab-overview"'):]
    positions = _order(body, READINESS, BOOKING_LINK, "Сегодня", MODELS_INVITE, STATS)
    assert positions == sorted(positions), positions


async def test_solo_master_without_bookings_sees_no_empty_money(client, db_session):
    """Четыре нуля и график из семи засечек — не информация."""
    _, salon_id = await _salon(db_session, "+79996660003", SalonPanelMode.SOLO)
    html = await _open(client, "+79996660003", salon_id)
    body = html[html.index('id="tab-overview"'):]
    assert STATS not in body
    assert CHART not in body


async def test_solo_master_sees_money_as_soon_as_there_is_one_booking(client, db_session):
    _, salon_id = await _salon(db_session, "+79996660004", SalonPanelMode.SOLO, booking=True)
    html = await _open(client, "+79996660004", salon_id)
    body = html[html.index('id="tab-overview"'):]
    assert STATS in body
    assert CHART in body


async def test_solo_empty_today_invites_to_share_the_link(client, db_session):
    _, salon_id = await _salon(db_session, "+79996660005", SalonPanelMode.SOLO)
    html = await _open(client, "+79996660005", salon_id)
    assert "Записей на сегодня нет — раздайте клиентам ссылку для записи." in html


async def test_solo_salon_without_a_master_is_told_what_is_wrong(client, db_session):
    """Тот самый случай с прода: подключился и остался без мастера."""
    _, salon_id = await _salon(db_session, "+79996660006", SalonPanelMode.SOLO,
                               with_master=False, with_service=False)
    html = await _open(client, "+79996660006", salon_id)
    assert "Записаться к вам сейчас нельзя" in html
    assert "Нет вашей карточки мастера" in html
    assert f"salon_id={salon_id}&amp;tab=employees" in html or \
           f"salon_id={salon_id}&tab=employees" in html


# ─────────────────────────── режим команды ───────────────────────────

async def test_team_overview_keeps_the_old_blocks_and_adds_the_link(client, db_session):
    _, salon_id = await _salon(db_session, "+79996660010", SalonPanelMode.TEAM, booking=True)
    html = await _open(client, "+79996660010", salon_id)
    body = html[html.index('id="tab-overview"'):]
    assert STATS in body
    assert CHART in body
    assert 'class="overview-grid-2-1"' in body
    assert BOOKING_LINK in body


async def test_team_overview_invites_to_models_too(client, db_session):
    """Решение владельца 03.10.2026: приглашение в «Модели» показываем в обоих
    режимах. Раздел включён по умолчанию везде (решение 0007, п. 2), а узнать о
    нём человеку больше негде: за 25 дней его открывали один раз."""
    _, salon_id = await _salon(db_session, "+79996660012", SalonPanelMode.TEAM, booking=True)
    body = (await _open(client, "+79996660012", salon_id))
    body = body[body.index('id="tab-overview"'):]
    assert MODELS_INVITE in body


async def test_team_overview_stays_quiet_while_nothing_is_wrong(client, db_session):
    """Салону с командой первый экран занимать нечем: блок готовности
    появляется, только когда есть что исправлять."""
    _, salon_id = await _salon(db_session, "+79996660011", SalonPanelMode.TEAM, booking=True)
    html = await _open(client, "+79996660011", salon_id)
    assert READINESS not in html[html.index('id="tab-overview"'):]


async def test_team_overview_warns_when_booking_is_broken(client, db_session):
    _, salon_id = await _salon(db_session, "+79996660012", SalonPanelMode.TEAM,
                               with_master=False, with_service=False)
    html = await _open(client, "+79996660012", salon_id)
    assert READINESS in html
    assert "Ни одного активного мастера" in html


# ─────────────────── панель наёмного мастера не трогали ───────────────────

async def test_hired_master_panel_has_no_readiness_and_no_link(client, db_session):
    """master_dashboard зовёт тот же рендер. Наёмному мастеру ни ссылка салона,
    ни действия в чужие разделы не нужны — новые блоки выключены по умолчанию,
    и этот тест держит умолчание."""
    owner_id, salon_id = await _salon(db_session, "+79996660020", SalonPanelMode.TEAM,
                                      booking=True)
    async with db_session() as db:
        hired = User(phone="+79996660021", full_name="Наёмный мастер",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(hired)
        await db.commit()
        await db.refresh(hired)
        db.add(Master(user_id=hired.id, salon_id=salon_id, specialization="Брови",
                      experience_years=1, rating=0.0, is_active=True))
        await db.commit()

    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": "+79996660021", "password": "Testpass1"})
    assert r.status_code == 302
    page = await client.get("/business/dashboard")
    assert page.status_code == 200
    assert 'id="tab-overview"' in page.text, "мастер должен попасть на свою панель"
    assert READINESS not in page.text
    assert BOOKING_LINK not in page.text
    assert MODELS_INVITE not in page.text


async def test_member_without_manage_salon_gets_no_dead_actions(client, db_session):
    """Участник без права менять салон не откроет ни один раздел, куда ведут
    действия блока готовности. Показать ему список ссылок, возвращающих в
    «Обзор», хуже, чем не показывать блок вовсе."""
    _, salon_id = await _salon(db_session, "+79996660030", SalonPanelMode.TEAM,
                               with_master=False, with_service=False)
    async with db_session() as db:
        staff = User(phone="+79996660031", full_name="Администратор",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(staff)
        await db.commit()
        await db.refresh(staff)
        db.add(SalonMember(
            salon_id=salon_id, user_id=staff.id, role=SalonRole.ADMIN, is_creator=False,
            permissions={"manage_salon": False}, is_active=True,
        ))
        await db.commit()

    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": "+79996660031", "password": "Testpass1"})
    assert r.status_code == 302
    page = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert page.status_code == 200
    assert 'id="tab-overview"' in page.text
    assert READINESS not in page.text
    assert BOOKING_LINK not in page.text


async def test_hired_master_still_sees_personal_stats_and_warehouse(client, db_session):
    """Панель мастера дописывает свои карточки в конец «Обзора».
    Раньше она вклеивала их поиском подстроки в готовой разметке, и перестановка
    блоков уводила их в середину экрана; теперь это параметр extra_html, а тест
    держит и наличие карточек, и их место."""
    _, salon_id = await _salon(db_session, "+79996660040", SalonPanelMode.TEAM, booking=True)
    async with db_session() as db:
        hired = User(phone="+79996660041", full_name="Наёмный мастер",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(hired)
        await db.commit()
        await db.refresh(hired)
        db.add(Master(user_id=hired.id, salon_id=salon_id, specialization="Брови",
                      experience_years=1, rating=0.0, is_active=True))
        await db.commit()

    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": "+79996660041", "password": "Testpass1"})
    assert r.status_code == 302
    page = await client.get("/business/dashboard")
    assert page.status_code == 200
    assert "Ваша статистика" in page.text, "личные карточки мастера отклеились"
    assert "Ваших записей сегодня" in page.text
    assert "Склад" in page.text
    # Присутствия мало: при вклейке по подстроке карточки оказывались в
    # середине «Обзора» — сразу после счётчиков, перед графиком и «Сегодня».
    body = page.text[page.text.index('id="tab-overview"'):]
    assert body.index("Ваша статистика") > body.index("Выручка за неделю"), \
        "личный блок уехал выше графика"
    assert body.index("Ваша статистика") > body.index("Сегодня"), \
        "личный блок уехал выше «Сегодня»"
