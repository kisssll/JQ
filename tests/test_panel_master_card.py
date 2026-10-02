"""Соло-режим: «Моя карточка мастера» вобрала настройки салона (решение 0009).

Что здесь проверяется и почему именно это:

  1. **Дверь в режим команды.** Переключатель режима переехал вместе с
     остальным. Если бы он остался в исчезнувшей вкладке, соло-мастер никогда
     не перешёл бы в «у меня команда» и не смог бы нанять человека. Это
     главный риск переноса, и он проверяется до конца — не «радиокнопка есть в
     разметке», а «переключился и получил командную панель».
  2. **Ни одно поле не потеряно.** Для каждой формы бывшей вкладки есть тест,
     который сохраняет значение ИЗ НОВОГО МЕСТА и читает его из базы. Проверка
     «страница открылась» такого не поймала бы: поле могло уехать из разметки
     вместе с куском f-строки.
  3. **Ничего не стало недостижимым.** Прямой ?tab=edit, действия блока
     готовности, право уйти с платформы (152-ФЗ).
  4. **Командный режим не изменился.** Та же вкладка, те же блоки, «Сеть
     салонов» на месте.
  5. **Подписи говорят с человеком.** Отдельный тест на то, что в соло панель
     не называет человека салоном, со списком честных исключений.
"""
import json

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    Master, OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember, SalonModerationStatus,
    SalonPanelMode, SalonRole, User, UserRole,
)
from app.services import panel_sections as ps
from app.services import panel_tour


async def _make_salon(db_session, phone, mode=SalonPanelMode.SOLO, *, with_master=True):
    async with db_session() as db:
        owner = User(
            phone=phone, full_name="Ольга Мастерова",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS,
            is_active=True,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name="Ольга Мастерова", address="Томск, ул. Ленина, 1",
            phone="+73822000111", latitude=56.4, longitude=84.9, timezone="Asia/Tomsk",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=mode, guest_booking_enabled=True,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(
            salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER, is_creator=True,
            permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        if with_master:
            db.add(Master(
                user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
                experience_years=3, rating=0.0, is_active=True,
            ))
        await db.commit()
        return owner.id, salon.id


async def _login(client, phone):
    r = await client.post(
        "/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"},
    )
    assert r.status_code == 302, r.text


async def _card(client, salon_id) -> str:
    """Разметка раздела «Моя карточка мастера»."""
    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=employees")
    assert r.status_code == 200
    return r.text


async def _reload(db_session, salon_id) -> Salon:
    async with db_session() as db:
        return (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()


# ═══════════════ 1. Дверь в режим команды (главный риск) ═══════════════

async def test_the_mode_switch_is_reachable_in_solo(client, db_session):
    """Переключатель обязан быть в единственном разделе настроек соло-режима."""
    _, salon_id = await _make_salon(db_session, "+79995571001")
    await _login(client, "+79995571001")

    html = await _card(client, salon_id)
    assert 'action="/api/v1/business/my-salon/panel-mode"' in html
    assert 'name="mode" value="solo"' in html
    assert 'name="mode" value="team"' in html


async def test_a_solo_master_can_actually_switch_to_team_and_back(client, db_session):
    """Не «кнопка есть», а «дверь открывается». Односторонняя дверь означала бы,
    что человек не может нанять мастера вообще никогда (решение 0009, п. 3)."""
    _, salon_id = await _make_salon(db_session, "+79995571002")
    await _login(client, "+79995571002")

    r = await client.post(
        "/api/v1/business/my-salon/panel-mode",
        data={"salon_id": str(salon_id), "mode": "team"}, follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    # Уводит в настройки того режима, который только что выбрали, а не в «Обзор».
    assert "tab=edit" in r.headers["location"]
    assert (await _reload(db_session, salon_id)).panel_mode is SalonPanelMode.TEAM

    page = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert "&tab=edit" in page.text, "в команде вкладка настроек вернулась"
    assert "Добавить мастера" in await _card(client, salon_id), "найм стал доступен"

    # И обратно — чтобы дверь не оказалась односторонней в другую сторону.
    r = await client.post(
        "/api/v1/business/my-salon/panel-mode",
        data={"salon_id": str(salon_id), "mode": "solo"}, follow_redirects=False,
    )
    assert r.status_code == 302
    assert "tab=employees" in r.headers["location"]
    assert (await _reload(db_session, salon_id)).panel_mode is SalonPanelMode.SOLO


async def test_the_section_with_the_mode_switch_cannot_be_hidden_in_solo(client, db_session):
    """Через эндпоинт тоже: страницу можно открыть в двух вкладках."""
    _, salon_id = await _make_salon(db_session, "+79995571003")
    await _login(client, "+79995571003")

    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": ["overview", "models"]},
    )
    assert r.status_code == 200, r.text
    assert "employees" in r.json()["sections"]
    assert 'name="mode" value="team"' in await _card(client, salon_id)


# ═══════════════ 2. Ни одно поле не потеряно ═══════════════

async def test_every_field_of_the_old_tab_is_in_the_new_place(client, db_session):
    """Поля формы — по именам элементов, на которых висит сохранение
    (static/src/js/business/tabs/my-salon.js). Пропавшее поле означает, что
    кусок f-строки не переехал."""
    _, salon_id = await _make_salon(db_session, "+79995572001")
    await _login(client, "+79995572001")
    html = await _card(client, salon_id)

    for field in (
        'id="salonEditNameInput"', 'id="salonEditPhoneInput"', 'id="salonEditCityInput"',
        'id="salonEditAddressInput"', 'id="salonEditEmailInput"', 'id="salonEditDescInput"',
        'id="guestToggle"', 'id="photoDropZone"', 'id="salonVisibilityBtn"',
        'id="salonDeleteBtn"', 'id="salonEditToggleBtn"',
    ):
        assert field in html, f"поле {field} потерялось при переносе"

    # Часы работы — семь дней, у каждого начало, конец и «выходной».
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        assert f'id="wh-start-{day}"' in html, day
        assert f'id="wh-end-{day}"' in html, day
        assert f'class="wh-closed" data-day="{day}"' in html, day

    # Эндпоинты, на которые эти формы отправляют.
    for endpoint in (
        f'/api/v1/upload/salon/{salon_id}/photo',
        '/api/v1/business/my-salon/panel-mode',
        f'/business/dashboard?salon_id={salon_id}&edit=1',
    ):
        assert endpoint in html, endpoint

    # window.salonId читают все эти скрипты — без неё формы молча не сохраняют.
    assert f"window.salonId = {salon_id}" in html


async def test_basic_information_saves_from_the_new_place(client, db_session):
    """Одна форма — одно сохранение, и каждое поле читается из базы обратно."""
    _, salon_id = await _make_salon(db_session, "+79995572002")
    await _login(client, "+79995572002")
    assert 'id="salonEditNameInput"' in await _card(client, salon_id)

    r = await client.put(
        f"/api/v1/business/my-salon?salon_id={salon_id}",
        json={
            "name": "Ольга Петрова", "phone": "+79990001122",
            "city": "Томск", "address": "Томск, ул. Ленина, 5",
            "latitude": 56.46, "longitude": 84.95,
            "email": "olga@example.com", "description": "Маникюр и педикюр",
        },
    )
    assert r.status_code == 200, r.text

    salon = await _reload(db_session, salon_id)
    assert salon.name == "Ольга Петрова"
    assert salon.phone == "+79990001122"
    assert salon.city == "Томск"
    assert salon.address == "Томск, ул. Ленина, 5"
    assert salon.email == "olga@example.com"
    assert salon.description == "Маникюр и педикюр"


async def test_working_hours_save_from_the_new_place(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995572003")
    await _login(client, "+79995572003")
    assert 'id="wh-start-mon"' in await _card(client, salon_id)

    hours = {d: "09:00-18:00" for d in ("mon", "tue", "wed", "thu", "fri")}
    hours.update({"sat": "closed", "sun": "closed"})
    r = await client.put(
        f"/api/v1/business/my-salon?salon_id={salon_id}",
        json={"working_hours": json.dumps(hours)},
    )
    assert r.status_code == 200, r.text
    assert json.loads((await _reload(db_session, salon_id)).working_hours) == hours


async def test_guest_booking_toggle_works_from_the_new_place(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995572004")
    await _login(client, "+79995572004")
    assert 'id="guestToggle"' in await _card(client, salon_id)

    before = (await _reload(db_session, salon_id)).guest_booking_enabled
    r = await client.post(f"/api/v1/business/my-salon/guest-toggle?salon_id={salon_id}")
    assert r.status_code == 200, r.text
    assert (await _reload(db_session, salon_id)).guest_booking_enabled is (not before)


async def test_hiding_yourself_works_from_the_new_place(client, db_session):
    """Право уйти должно быть достижимо (152-ФЗ) — в соло тоже."""
    _, salon_id = await _make_salon(db_session, "+79995572005")
    await _login(client, "+79995572005")
    html = await _card(client, salon_id)
    assert 'id="salonVisibilityBtn"' in html
    assert "Скрыть меня из ленты" in html

    r = await client.post(f"/api/v1/business/my-salon/visibility-toggle?salon_id={salon_id}")
    assert r.status_code == 200, r.text
    assert (await _reload(db_session, salon_id)).is_hidden is True


async def test_deleting_yourself_works_from_the_new_place(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995572006")
    await _login(client, "+79995572006")
    html = await _card(client, salon_id)
    assert 'id="salonDeleteBtn"' in html
    assert "Удалить мой профиль" in html

    r = await client.delete(f"/api/v1/business/my-salon?salon_id={salon_id}")
    assert r.status_code == 200, r.text
    assert (await _reload(db_session, salon_id)).is_active is False


async def test_the_visibility_button_carries_its_texts_for_the_script(client, db_session):
    """Подписи кнопки перерисовывает скрипт. Пока они жили в нём строкой, в
    соло он бы написал «Скрыть салон» поверх «Скрыть меня из ленты»."""
    _, salon_id = await _make_salon(db_session, "+79995572007")
    await _login(client, "+79995572007")
    html = await _card(client, salon_id)
    for attr in ("data-label-on", "data-label-off", "data-hint-on", "data-hint-off"):
        assert attr in html, attr
    assert 'data-label-on="Показать меня в ленте"' in html


# ═══════════════ 3. Ничего не стало недостижимым ═══════════════

async def test_solo_has_no_edit_section_in_the_menu(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995573001")
    await _login(client, "+79995573001")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert r.status_code == 200
    assert "&tab=edit" not in r.text
    assert ps.label("edit", SalonPanelMode.TEAM) not in r.text
    assert "&tab=employees" in r.text


async def test_direct_tab_edit_in_solo_lands_on_the_master_card(client, db_session):
    """Не в «Обзор»: содержимое вкладки никуда не делось, и старая ссылка
    (закладка, редирект /business/my-salon) обязана вести туда, где оно лежит."""
    _, salon_id = await _make_salon(db_session, "+79995573002")
    await _login(client, "+79995573002")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=edit")
    assert r.status_code == 200
    assert 'id="tab-employees" class="tab-content active"' in r.text
    assert 'id="tab-edit"' not in r.text
    assert 'id="tab-overview" class="tab-content active"' not in r.text


async def test_direct_tab_edit_in_solo_works_as_partial_too(client, db_session):
    """partial=1 — тот же вход в панель, и он тоже должен попасть по адресу."""
    _, salon_id = await _make_salon(db_session, "+79995573003")
    await _login(client, "+79995573003")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=edit&partial=1")
    assert r.status_code == 200
    assert 'id="tab-employees"' in r.text


async def test_the_legacy_my_salon_url_still_lands_on_the_settings(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995573004")
    await _login(client, "+79995573004")

    r = await client.get("/business/my-salon", follow_redirects=True)
    assert r.status_code == 200
    assert 'id="tab-employees"' in r.text


async def test_solo_is_not_offered_the_edit_section_among_hidden_ones(client, db_session):
    """Плюс в режиме редактирования панели вернул бы вкладку, чьи формы уже
    лежат в другой — два источника правды."""
    _, salon_id = await _make_salon(db_session, "+79995573005")
    await _login(client, "+79995573005")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    chips = r.text.split('class="panel-edit-chips"', 1)[1].split("</div>", 1)[0]
    assert 'data-key="edit"' not in chips


async def test_readiness_actions_in_solo_lead_where_the_settings_are(client, db_session):
    """Блок «Можно ли к вам записаться» — список ссылок. Ссылка в исчезнувший
    раздел вернула бы человека в «Обзор», откуда он и пришёл."""
    _, salon_id = await _make_salon(db_session, "+79995573006", with_master=False)
    await _login(client, "+79995573006")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert r.status_code == 200
    block = r.text.split('class="readiness', 1)[1].split("</section>", 1)[0]
    assert "readiness-action" in block, "в блоке должны быть действия"
    assert "tab=edit" not in block
    assert f"tab=employees#{panel_tour.ANCHOR_CARD_WORK}" in block


# ═══════════════ 4. Группы и якоря ═══════════════

async def test_the_master_card_has_two_groups_with_anchors(client, db_session):
    """Якоря — не украшение: на них ссылаются шаги тура и действия блока
    готовности. Переименовали якорь — отвалились обе ссылки."""
    _, salon_id = await _make_salon(db_session, "+79995574001")
    await _login(client, "+79995574001")
    html = await _card(client, salon_id)

    assert f'id="{panel_tour.ANCHOR_CARD_PUBLIC}"' in html
    assert f'id="{panel_tour.ANCHOR_CARD_WORK}"' in html
    assert "Как вас видят клиенты" in html
    assert "Рабочие настройки" in html
    # Порядок групп задан решением: сначала витрина, потом рабочие настройки.
    assert html.index(panel_tour.ANCHOR_CARD_PUBLIC) < html.index(panel_tour.ANCHOR_CARD_WORK)


async def test_the_chain_block_is_not_offered_in_solo(client, db_session):
    """Предлагать объединить в сеть то, чего нет, — предложение ни о чём
    (решение 0009, п. 4)."""
    _, salon_id = await _make_salon(db_session, "+79995574002")
    await _login(client, "+79995574002")
    html = await _card(client, salon_id)
    assert "Сеть салонов" not in html
    assert 'id="chainSearchInput"' not in html


# ═══════════════ 5. Командный режим не изменился ═══════════════

async def test_team_keeps_the_edit_tab_with_everything_in_it(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995575001", SalonPanelMode.TEAM)
    await _login(client, "+79995575001")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab=edit")
    assert r.status_code == 200
    html = r.text
    assert 'id="tab-edit" class="tab-content active"' in html
    for block in (
        "Основная информация", "Часы работы", "Запись без регистрации",
        "Разделы панели", "Сеть салонов", "Видимость и удаление",
        "Скрыть салон", "Удалить салон",
    ):
        assert block in html, f"в командном режиме пропал блок «{block}»"
    assert "Как вас видят клиенты" not in html, "групп в команде нет"
    assert "Рабочие настройки" not in html


async def test_team_employees_tab_has_no_salon_settings(client, db_session):
    """Настройки в команде остались в своей вкладке: иначе они бы оказались в
    двух местах сразу."""
    _, salon_id = await _make_salon(db_session, "+79995575002", SalonPanelMode.TEAM)
    await _login(client, "+79995575002")
    html = await _card(client, salon_id)

    assert 'id="salonEditNameInput"' not in html
    assert 'id="wh-start-mon"' not in html
    assert 'id="salonDeleteBtn"' not in html
    assert "Добавить мастера" in html, "найм в команде на месте"


# ═══════════════ 6. Подписи говорят с человеком ═══════════════

#: Места, где слово «салон» в соло-панели законно, — и почему.
_SALON_IS_FINE = (
    # Создать ЕЩЁ один салон: кнопка про новый бизнес, а не про этого человека.
    "Добавить салон",
    # Человек уже мастер в другом СВОЁМ салоне — речь ровно о том салоне.
    "в другом своём салоне",
    # Подсказка про режимы: слово «салон» здесь — название второго режима.
    "Сеть салонов",
)


def _strip_allowed(text: str) -> str:
    for allowed in _SALON_IS_FINE:
        text = text.replace(allowed, "")
    return text


@pytest.mark.parametrize("tab", [
    "overview", "employees", "services", "schedule", "records",
    "models", "promos", "reviews", "crm", "billing", "instructions",
])
async def test_no_panel_caption_in_solo_calls_the_person_a_salon(client, db_session, tab):
    """130 подписей панели говорили «салон». У соло-мастера салона нет.

    Смотрим только содержимое <main> — шапка сайта, боковое меню и подвал общие
    для всего сервиса и этой задачей не правятся (решение 0009, п. 5).

    «Инструкция» была исключением, пока её текст ждал захода 5: ослаблять тест
    под неё было нельзя, он должен ловить панель. Заход 5 прозу переписал, и
    исключение снято — справочник теперь под той же защитой, что и остальное.
    """
    _, salon_id = await _make_salon(db_session, f"+7999557{6000 + hash(tab) % 900}")
    phone = f"+7999557{6000 + hash(tab) % 900}"
    await _login(client, phone)

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tab={tab}&tour=off")
    assert r.status_code == 200
    main = r.text.split("<main", 1)[1].rsplit("</main>", 1)[0]
    cleaned = _strip_allowed(main)
    assert "алон" not in cleaned.replace("salon", ""), (
        f"вкладка {tab} в соло-режиме всё ещё говорит про салон: "
        + next(
            (line.strip() for line in cleaned.splitlines() if "алон" in line),
            "",
        )[:200]
    )


async def test_the_panel_header_speaks_to_the_person_in_solo(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995577001")
    await _login(client, "+79995577001")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tour=off")
    head = r.text.split('class="header-title"', 1)[1].split("</div>", 1)[0]
    assert "Моя панель" in head
    assert "Панель салона" not in head


async def test_the_panel_header_is_unchanged_in_team(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995577002", SalonPanelMode.TEAM)
    await _login(client, "+79995577002")

    r = await client.get(f"/business/dashboard?salon_id={salon_id}&tour=off")
    head = r.text.split('class="header-title"', 1)[1].split("</div>", 1)[0]
    assert "Панель салона" in head
