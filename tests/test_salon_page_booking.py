"""Страница салона и мастера: запись под рукой, соло говорит о человеке.

Решение 0011, п. 13. Проверяется:
  * запись достижима с любого места страницы — липкая колонка на широком экране
    и закреплённая кнопка с листом на телефоне;
  * в соло страница говорит о ЧЕЛОВЕКЕ, в команде — о салоне, и это идёт через
    один словарь (``public_words``), а не через тернарники по файлам;
  * путь «окно в карточке каталога → созданная бронь» доходит до конца.
"""
import itertools
import json
import re

from app.core.security import get_password_hash
from app.models.models import (
    Master, Salon, SalonModerationStatus, SalonPanelMode, Service, User, UserRole,
)
from tests.conftest import register_user

ROOT_SHEET = "bookSheet"
_phone = itertools.count(1)

_ALL_DAY = json.dumps({d: "00:00-23:59" for d in
                       ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


def _slot_href(catalog_html: str) -> str:
    """Первая ссылка свободного окна из каталога. &amp; разэкранирован: в
    разметке амперсанд обязан быть сущностью, а по ссылке надо сходить."""
    href = re.findall(r'class="r-slot" href="([^"]+)"', catalog_html)[0]
    return href.replace("&amp;", "&")


async def _stand(db_session, name, *, mode=SalonPanelMode.SOLO, masters=1,
                 master_name="Анна Смирнова", services=(("Маникюр", 1500, 60),)):
    async with db_session() as db:
        owner = User(phone=f"+7994{next(_phone):07d}", full_name=master_name,
                     hashed_password=get_password_hash("Bizpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(name=name, description="", address="Томск, ул. Тестовая 1",
                      city="Томск", phone=f"+7994{next(_phone):07d}",
                      latitude=56.5, longitude=84.9, working_hours=_ALL_DAY,
                      timezone="Asia/Novosibirsk", panel_mode=mode,
                      moderation_status=SalonModerationStatus.APPROVED,
                      is_active=True, creator_id=owner.id)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        ids = []
        for i in range(masters):
            muser = owner
            if i:
                muser = User(phone=f"+7994{next(_phone):07d}", full_name=f"Борис Петров {i}",
                             hashed_password=get_password_hash("Bizpass1"),
                             role=UserRole.BUSINESS)
                db.add(muser)
                await db.commit()
                await db.refresh(muser)
            m = Master(user_id=muser.id, salon_id=salon.id, specialization="Парикмахер",
                       is_active=True, break_minutes=0, experience_years=4)
            db.add(m)
            await db.commit()
            await db.refresh(m)
            ids.append(m.id)
            for sname, price, duration in services:
                db.add(Service(master_id=m.id, name=sname, price=price,
                               duration_minutes=duration, is_active=True))
            await db.commit()
        return salon.id, ids


# ─────────────────── соло говорит о человеке ───────────────────

async def test_solo_page_speaks_to_the_person(client, db_session):
    salon_id, _ = await _stand(db_session, "Анна Смирнова", master_name="Анна Смирнова")
    html = (await client.get(f"/salons/{salon_id}")).text

    assert "Записаться к Анне" in html
    assert "Запись к Анне" in html
    assert "О мастере" in html or "Отзывы о мастере" in html
    # Раздела «Мастера» в соло нет: показывать одного человека списком людей
    # значит называть его организацией. Проверяем саму сетку, а не подпись:
    # подпись в соло пустая, и раздел с пустым заголовком прошёл бы мимо.
    assert ">Мастера<" not in html
    assert 'class="team-grid"' not in html


async def test_team_page_speaks_about_the_salon(client, db_session):
    salon_id, _ = await _stand(db_session, "Салон РадугаZZ", masters=2,
                               mode=SalonPanelMode.TEAM)
    html = (await client.get(f"/salons/{salon_id}")).text

    assert "Запись в «Салон РадугаZZ»" in html
    assert ">Мастера<" in html
    assert "Отзывы о салоне" in html
    assert "Записаться к" not in html


async def test_a_solo_master_whose_name_is_not_declinable_keeps_a_working_label(
        client, db_session):
    """Падеж не дался — подпись обязана остаться целой, а не оборваться."""
    salon_id, _ = await _stand(db_session, "Hair StudioZZ", master_name="Hair Studio")
    html = (await client.get(f"/salons/{salon_id}")).text
    assert "Записаться к " not in html
    assert ">Записаться<" in html


async def test_solo_does_not_repeat_the_name_twice(client, db_session):
    """У частного мастера салон обычно назван своим именем, и «Анна Смирнова /
    Анна Смирнова» двумя строками читается как ошибка вёрстки."""
    salon_id, _ = await _stand(db_session, "Анна Смирнова", master_name="Анна Смирнова")
    html = (await client.get(f"/salons/{salon_id}")).text
    head = html[html.index('class="salon-head__top"'):html.index('class="salon-facts"')]
    assert head.count("Анна Смирнова") == 1, head


# ─────────────────── запись под рукой ───────────────────

async def test_booking_is_reachable_from_anywhere_on_the_page(client, db_session):
    salon_id, master_ids = await _stand(db_session, "ПодРукойZZ")
    html = (await client.get(f"/salons/{salon_id}")).text

    # Колонка справа — для широкого экрана.
    assert 'class="salon-aside"' in html and 'id="bookingHost"' in html
    # Закреплённая кнопка — для телефона, и она поднимает существующий лист.
    assert 'class="r-dock"' in html
    opener = re.search(r'data-sheet-open="([^"]+)"', html)
    assert opener, "у закреплённой кнопки нет листа"
    assert f'id="{opener.group(1)}"' in html
    # В листе есть, чем его закрыть, кроме жеста.
    sheet = html[html.index(f'id="{opener.group(1)}"'):]
    assert "data-sheet-close" in sheet
    assert 'role="dialog"' in sheet and 'aria-modal="true"' in sheet


async def test_the_widget_exists_once_and_carries_the_services(client, db_session):
    """Виджет один на страницу: два экземпляра одних и тех же полей — это два
    экземпляра одних и тех же id."""
    salon_id, master_ids = await _stand(db_session, "ОдинВиджетZZ")
    html = (await client.get(f"/salons/{salon_id}")).text

    assert html.count('id="bookingWidget"') == 1
    assert html.count('id="bookBody"') == 1
    data = re.search(r"data-masters='(.*?)'", html, re.S).group(1)
    masters = json.loads(data.replace("&quot;", '"'))
    assert masters[0]["id"] == master_ids[0]
    assert masters[0]["services"][0]["name"] == "Маникюр"


async def test_the_page_tells_the_truth_about_the_reminder(client, db_session):
    """Шаг «Напоминание» с выбором «за 30 минут / за час / за день» убран: его
    значение никуда не уходило (BookingCreate его не принимает), а сервер ставит
    напоминание всегда за два часа."""
    salon_id, _ = await _stand(db_session, "НапоминаниеZZ")
    html = (await client.get(f"/salons/{salon_id}")).text
    assert "Напомним за два часа" in html
    assert "За 30 мин" not in html
    assert 'id="reminder-toggle"' not in html


async def test_a_salon_without_services_says_so_instead_of_an_empty_widget(
        client, db_session):
    salon_id, _ = await _stand(db_session, "БезУслугZZ", services=())
    html = (await client.get(f"/salons/{salon_id}")).text
    assert "записаться нельзя" in html
    assert 'id="bookingWidget"' not in html
    assert 'class="r-dock"' not in html


# ─────────────────── предвыбор из каталога ───────────────────

async def test_the_slot_from_the_catalog_arrives_preselected(client, db_session):
    salon_id, master_ids = await _stand(db_session, "ПредвыборZZ")
    href = _slot_href((await client.get("/salons")).text)

    page = await client.get(href.replace("#booking", ""))
    assert page.status_code == 200
    preset = json.loads(
        re.search(r"data-preset='(.*?)'", page.text, re.S).group(1).replace("&quot;", '"')
    )
    assert preset["master"] == master_ids[0]
    assert preset["service"]
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", preset["slot"])


async def test_a_junk_preset_does_not_reach_the_markup(client, db_session):
    """Значения приходят из URL, то есть от кого угодно."""
    salon_id, _ = await _stand(db_session, "МусорZZ")
    page = await client.get(
        f"/salons/{salon_id}?master=abc&service=<script>&slot=' onload='x"
    )
    assert page.status_code == 200
    preset = json.loads(
        re.search(r"data-preset='(.*?)'", page.text, re.S).group(1).replace("&quot;", '"')
    )
    assert preset["master"] is None and preset["service"] is None
    assert "<script>" not in page.text.split("</head>")[1][:4000]


# ─────────────────── сквозной путь ───────────────────

async def test_booking_from_a_catalog_slot_creates_a_booking(client, db_session):
    """Путь «искал → выбрал → записался» целиком: окно в карточке каталога,
    страница салона с предвыбором, созданная бронь."""
    salon_id, master_ids = await _stand(db_session, "СквознойZZ")

    href = _slot_href((await client.get("/salons")).text)
    params = dict(re.findall(r"[?&](\w+)=([^&#]+)", href))
    slot = params["slot"]

    data = await register_user(client, "+79941110001", full_name="Клиент Тестов")
    client.cookies.set("access_token", data["access_token"])

    page = await client.get(href.replace("#booking", ""))
    assert page.status_code == 200
    assert "Записаться к Анне" in page.text

    created = await client.post("/api/v1/bookings", json={
        "master_id": int(params["master"]),
        "service_id": int(params["service"]),
        "start_time": slot,
    })
    assert created.status_code == 201, created.text
    assert created.json()["master_id"] == master_ids[0]

    # То же окно больше не предлагается — ни в каталоге, ни в API.
    api = await client.get(
        f"/api/v1/bookings/available/{params['master']}"
        f"?date={slot[:10]}&service_id={params['service']}"
    )
    assert slot not in api.json()["slots"]
    client.cookies.clear()


# ─────────────────── страница мастера ───────────────────

async def test_master_page_has_its_own_booking(client, db_session):
    """Раньше на странице мастера записи не было вовсе — только кнопка,
    возвращавшая на страницу салона."""
    salon_id, master_ids = await _stand(db_session, "МастерZZ", master_name="Ольга Ким")
    html = (await client.get(f"/masters/{master_ids[0]}")).text

    assert "Записаться к Ольге" in html
    assert 'id="bookingWidget"' in html
    assert 'class="r-dock"' in html
    assert "Маникюр" in html and "1 500 ₽" in html


async def test_missing_master_and_salon_offer_the_catalog(client):
    for path in ("/masters/99999", "/salons/99999"):
        r = await client.get(path)
        assert "Такой страницы нет" in r.text, path
        assert 'href="/salons"' in r.text, path


async def test_the_confirmation_text_comes_from_the_markup_not_from_the_script(
        client, db_session):
    """Подписи, которые подставляет JS, разметочными тестами не ловятся —
    поэтому правило: текст приходит из data-атрибута, а не из строки в .js
    (мелкий долг из docs/status.md). Здесь это и проверяется: экран «готово»
    берёт фразу из словаря, и в соло она про мастера."""
    salon_id, master_ids = await _stand(db_session, "ГотовоZZ", master_name="Анна Смирнова")
    html = (await client.get(f"/salons/{salon_id}")).text
    assert "data-done='Мастер подтвердит запись.'" in html

    team_id, _ = await _stand(db_session, "ГотовоКомандаZZ", masters=2,
                              mode=SalonPanelMode.TEAM)
    team = (await client.get(f"/salons/{team_id}")).text
    assert "data-done='Салон подтвердит запись.'" in team

    master = (await client.get(f"/masters/{master_ids[0]}")).text
    assert "data-done='Мастер подтвердит запись.'" in master


def test_the_script_takes_that_text_from_the_attribute():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent /
           "static" / "src" / "js" / "salon-detail.js").read_text()
    assert "widget.dataset.done" in src
    assert "подтвердит запись" not in src, "фраза захардкожена в скрипте"
