"""Тур в самой панели: запуск, переходы, выход и возврат (решение 0008).

Здесь проверяется то, что состоит из базы и страницы, а не из значений:
шаг переживает перезагрузку, автозапуск срабатывает один раз, у наёмного
мастера тура нет, «пройти заново» сбрасывает состояние. Состав шагов проверен
отдельно и без базы — tests/test_panel_tour_steps.py.
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
from app.services import panel_sections, panel_tour

_WEEK_OPEN = json.dumps({d: "10:00-20:00" for d in
                         ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})

BAR = 'id="panelTour"'
INVITE = 'id="panelTourInvite"'
HIGHLIGHT = 'class="tab-item is-tour"'


async def _salon(db_session, phone, mode=SalonPanelMode.SOLO, *, booking=False,
                 published=True, sections=None):
    """Салон, к которому можно записаться (если не сломать нарочно)."""
    async with db_session() as db:
        owner = User(phone=phone, full_name="Ольга Мастерова",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name=f"Тур {phone}", address="Томск, ул. Ленина, 1",
            phone="+73822000777", latitude=56.4, longitude=84.9, timezone="Asia/Tomsk",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=mode, panel_sections=sections,
            working_hours=_WEEK_OPEN, guest_booking_enabled=True,
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

        master = Master(user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
                        experience_years=3, rating=0.0, is_active=True)
        db.add(master)
        await db.commit()
        await db.refresh(master)
        svc = Service(master_id=master.id, name="Маникюр", price=2000,
                      duration_minutes=60, is_active=True, is_model_practice=False)
        db.add(svc)
        for wd in range(5):
            db.add(Schedule(master_id=master.id, day_of_week=wd,
                            start_time=time(10, 0), end_time=time(19, 0)))
        await db.commit()
        await db.refresh(svc)

        if booking:
            client = User(phone="+7987" + phone[4:], full_name="Клиент",
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


async def _login(client, phone):
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": phone, "password": "Testpass1"})
    assert r.status_code == 302, r.text


async def _get(client, salon_id, query=""):
    page = await client.get(f"/business/dashboard?salon_id={salon_id}{query}")
    assert page.status_code == 200
    return page.text


async def _tour_state(db_session, user_id):
    async with db_session() as db:
        u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        return u.panel_tour_started_at, u.panel_tour_done_at, u.panel_tour_step


def _steps(mode=SalonPanelMode.SOLO, sections=None):
    class S:
        panel_mode = mode
        panel_sections = sections
    s = S()
    return panel_tour.build(s, visible_keys=panel_sections.ordered_keys(s))


# ─────────────────────────── автозапуск ───────────────────────────

async def test_first_entry_starts_the_tour_and_remembers_it(client, db_session):
    owner_id, salon_id = await _salon(db_session, "+79995550001", published=False)
    await _login(client, "+79995550001")
    html = await _get(client, salon_id)
    assert BAR in html, "первый заход владельца — тур сам"
    assert "Шаг 1 из" in html
    started, done, step = await _tour_state(db_session, owner_id)
    assert started is not None and done is None
    assert step == _steps()[0].key


async def test_the_tour_does_not_start_a_second_time_by_itself(client, db_session):
    """Автозапуск один раз: иначе полоса всплывала бы при каждом заходе у
    человека, который её однажды закрыл."""
    owner_id, salon_id = await _salon(db_session, "+79995550002", published=False)
    await _login(client, "+79995550002")
    await _get(client, salon_id)                        # первый заход — тур
    html = await _get(client, salon_id, "&tour=off")    # вышел
    assert BAR not in html
    again = await _get(client, salon_id)                # зашёл снова
    assert BAR not in again
    assert INVITE in again, "но продолжить предлагаем"


async def test_a_working_salon_with_bookings_gets_an_invitation_not_the_tour(client, db_session):
    """Решение 0008, п. 5: у кого всё работает и запись есть — не тащим."""
    owner_id, salon_id = await _salon(db_session, "+79995550003", booking=True)
    await _login(client, "+79995550003")
    html = await _get(client, salon_id)
    assert BAR not in html
    assert INVITE in html
    assert "Пройти знакомство" in html
    started, _, step = await _tour_state(db_session, owner_id)
    assert started is None and step is None, "приглашение не считается запуском"


async def test_a_working_salon_can_still_take_the_tour(client, db_session):
    owner_id, salon_id = await _salon(db_session, "+79995550004", booking=True)
    await _login(client, "+79995550004")
    html = await _get(client, salon_id, "&tour=on")
    assert BAR in html
    started, _, step = await _tour_state(db_session, owner_id)
    assert started is not None and step == _steps()[0].key


async def test_a_salon_that_cannot_take_bookings_yet_gets_the_tour(client, db_session):
    """Обратная сторона исключения: салон опубликован, но записей нет — ему тур
    как раз и нужен."""
    _, salon_id = await _salon(db_session, "+79995550005")
    await _login(client, "+79995550005")
    assert BAR in await _get(client, salon_id)


# ─────────────── шаг переживает перезагрузку и переходы ───────────────

async def test_the_step_survives_a_page_reload(client, db_session):
    """Главное требование к реализации (решение 0008, п. 8): перезагрузка не
    сбрасывает тур на начало. Шаг берётся из базы, а не из разметки и не из
    хранилища браузера, — поэтому «перезагрузка» здесь это новый GET без
    единого параметра тура."""
    owner_id, salon_id = await _salon(db_session, "+79995550010", published=False)
    await _login(client, "+79995550010")
    steps = _steps()
    await _get(client, salon_id)
    # Три «Дальше»
    for s in steps[1:4]:
        html = await _get(client, salon_id, f"&tab={s.tab}&tour={s.key}")
        assert BAR in html
    assert (await _tour_state(db_session, owner_id))[2] == steps[3].key

    # Перезагрузка страницы шага — тот же шаг, тот же номер
    reloaded = await _get(client, salon_id, f"&tab={steps[3].tab}&tour={steps[3].key}")
    assert f"Шаг 4 из {len(steps)}" in reloaded

    # И возврат «вслепую», без ключа в адресе: шаг знает база
    resumed = await _get(client, salon_id, "&tour=on")
    assert f"Шаг 4 из {len(steps)}" in resumed


async def test_saving_something_mid_tour_does_not_lose_the_step(client, db_session):
    """Панель во время тура живая (решение 0008, п. 8): человек меняет что-то в
    разделе, страница перезагружается уже без параметров тура — шаг на месте."""
    owner_id, salon_id = await _salon(db_session, "+79995550011", published=False)
    await _login(client, "+79995550011")
    steps = _steps()
    await _get(client, salon_id)
    await _get(client, salon_id, f"&tab={steps[4].tab}&tour={steps[4].key}")

    r = await client.post("/api/v1/business/my-salon/panel-sections",
                          json={"salon_id": salon_id,
                                "sections": list(panel_sections.ALL_KEYS)})
    assert r.status_code == 200, r.text

    assert (await _tour_state(db_session, owner_id))[2] == steps[4].key
    assert f"Шаг 5 из" in await _get(client, salon_id, "&tour=on")


async def test_the_tour_highlights_the_section_of_the_current_step(client, db_session):
    _, salon_id = await _salon(db_session, "+79995550012", published=False)
    await _login(client, "+79995550012")
    steps = _steps()
    step = [s for s in steps if s.tab == "services"][0]
    html = await _get(client, salon_id, f"&tab=services&tour={step.key}")
    assert HIGHLIGHT in html
    marked = html[html.index(HIGHLIGHT):]
    assert 'data-key="services"' in marked[:200]


async def test_tab_links_keep_the_tour_alive(client, db_session):
    """Уйти в другой раздел посреди шага можно, и полоса от этого не исчезает."""
    _, salon_id = await _salon(db_session, "+79995550013", published=False)
    await _login(client, "+79995550013")
    html = await _get(client, salon_id)
    assert "&amp;tour=on" in html or "&tour=on" in html


async def test_finishing_the_tour_marks_it_done_and_closes_the_bar(client, db_session):
    owner_id, salon_id = await _salon(db_session, "+79995550014", published=False)
    await _login(client, "+79995550014")
    steps = _steps()
    await _get(client, salon_id)
    last = await _get(client, salon_id, f"&tab={steps[-1].tab}&tour={steps[-1].key}")
    assert "Готово" in last and "Дальше" not in last

    html = await _get(client, salon_id, "&tour=done")
    assert BAR not in html and INVITE not in html
    started, done, _ = await _tour_state(db_session, owner_id)
    assert started is not None and done is not None

    # и больше сам не всплывает
    assert BAR not in await _get(client, salon_id)


async def test_an_unknown_step_key_does_not_break_the_panel(client, db_session):
    _, salon_id = await _salon(db_session, "+79995550015", published=False)
    await _login(client, "+79995550015")
    html = await _get(client, salon_id, "&tour=visible:no-such-section")
    assert BAR in html and "Шаг 1 из" in html


async def test_the_tour_never_leads_into_a_section_the_owner_turned_off(client, db_session):
    """Владелец убрал «Модели» — шага про них нет ни в полосе, ни в ссылках."""
    kept = [k for k in panel_sections.ALL_KEYS if k != "models"]
    _, salon_id = await _salon(db_session, "+79995550016", published=False, sections=kept)
    await _login(client, "+79995550016")
    steps = _steps(sections=kept)
    assert "models" not in [s.tab for s in steps]
    html = await _get(client, salon_id, "&tour=chosen:models")
    assert "tour=chosen:models" not in html
    assert f"из {len(steps)}" in html


# ─────────────────────────── кому тура нет ───────────────────────────

async def test_a_member_without_manage_salon_has_no_tour(client, db_session):
    """Почти все действия тура ему недоступны (решение 0008, п. 5)."""
    _, salon_id = await _salon(db_session, "+79995550020", published=False)
    async with db_session() as db:
        helper = User(phone="+79995550021", full_name="Администратор",
                      hashed_password=get_password_hash("Testpass1"),
                      role=UserRole.BUSINESS, is_active=True)
        db.add(helper)
        await db.commit()
        await db.refresh(helper)
        db.add(SalonMember(
            salon_id=salon_id, user_id=helper.id, role=SalonRole.ADMIN, is_creator=False,
            permissions={"manage_schedule": True}, is_active=True,
        ))
        await db.commit()
    await _login(client, "+79995550021")
    html = await _get(client, salon_id)
    assert BAR not in html and INVITE not in html
    # и принудительно его тоже не поднять
    assert BAR not in await _get(client, salon_id, "&tour=on")


async def test_the_hired_master_panel_has_no_tour(client, db_session):
    """У наёмного мастера своя панель и свои задачи — тур ему будет другим
    (решение 0008, отложено)."""
    _, salon_id = await _salon(db_session, "+79995550030", SalonPanelMode.TEAM)
    async with db_session() as db:
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        hired = User(phone="+79995550031", full_name="Наёмный мастер",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.MASTER, is_active=True)
        db.add(hired)
        await db.commit()
        await db.refresh(hired)
        db.add(Master(user_id=hired.id, salon_id=salon.id, specialization="Брови",
                      experience_years=1, rating=0.0, is_active=True))
        await db.commit()
    await _login(client, "+79995550031")
    page = await client.get("/business/dashboard")
    assert page.status_code == 200
    assert BAR not in page.text and INVITE not in page.text


# ─────────────────────────── пройти заново ───────────────────────────

async def test_restart_resets_the_tour_to_the_first_step(client, db_session):
    owner_id, salon_id = await _salon(db_session, "+79995550040", published=False)
    await _login(client, "+79995550040")
    steps = _steps()
    await _get(client, salon_id)
    await _get(client, salon_id, f"&tab={steps[-1].tab}&tour={steps[-1].key}")
    await _get(client, salon_id, "&tour=done")
    started_before, done_before, _ = await _tour_state(db_session, owner_id)
    assert done_before is not None

    html = await _get(client, salon_id, "&tour=restart")
    assert BAR in html and "Шаг 1 из" in html
    started, done, step = await _tour_state(db_session, owner_id)
    assert done is None, "отметка «прошёл до конца» снята"
    assert step == steps[0].key
    assert started == started_before, "«запустили впервые» не перезаписываем"


async def test_the_instructions_tab_offers_to_take_the_tour_again(client, db_session):
    _, salon_id = await _salon(db_session, "+79995550041", published=False)
    await _login(client, "+79995550041")
    html = await _get(client, salon_id, "&tab=instructions&tour=off")
    assert "Пройти знакомство заново" in html
    assert "tour=restart" in html


async def test_the_instructions_tab_in_solo_mode_uses_the_solo_label(client, db_session):
    """Справочник называет разделы так же, как панель: в соло «Сотрудники» —
    это «Моя карточка мастера» (один реестр, решение 0008, п. 7)."""
    _, salon_id = await _salon(db_session, "+79995550042", published=False)
    await _login(client, "+79995550042")
    html = await _get(client, salon_id, "&tab=instructions&tour=off")
    body = html[html.index('id="tab-instructions"'):]
    assert "Моя карточка мастера" in body
