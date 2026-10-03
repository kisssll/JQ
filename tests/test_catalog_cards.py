"""Карточка каталога в новой форме: услуги с ценой, свободные окна, цена в запросах.

Решение 0011, п. 11 и 12. Главное, что здесь проверяется:

  * карточка БЕЗ фотографии и БЕЗ описания отрисовывается полностью — на проде
    обложка есть у двух салонов из девяти, а описание не заполнено ни у кого,
    так что это не краевой случай, а обычный;
  * окно, показанное в каталоге, действительно свободно — то есть то же самое,
    что отдаёт /api/v1/bookings/available. Двух реализаций правил доступности
    быть не должно;
  * каталог не стал дороже по запросам. Его однажды уже разгоняли с девяти
    секунд, поэтому цена измеряется счётчиком, а не оценивается на глаз.
"""
import contextlib
import itertools
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import event

from app.core.security import get_password_hash
from app.models.models import (
    Master, Salon, SalonModerationStatus, SalonPanelMode, Service, User, UserRole,
)
from app.services.catalog_slots import SERVICES_PER_CARD, SLOTS_PER_CARD
from app.web.pages.home import HOME_CARDS

_phone = itertools.count(1)

# Круглосуточный график: иначе тест зависел бы от часа, в который его запустили,
# а свободные окна — ровно то, что он проверяет.
_ALL_DAY = json.dumps({d: "00:00-23:59" for d in
                       ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


async def _stand(db_session, name, *, services=(("Маникюр", 1500, 60),),
                 mode=SalonPanelMode.SOLO, masters=1, logo=None, description="",
                 hours=_ALL_DAY, city="Томск"):
    """Опубликованный салон с мастерами и услугами.

    Имена стендов тест задаёт сам и с уникальным хвостом — чистки «по шаблону»
    здесь нет и быть не может ни в какой базе.
    """
    async with db_session() as db:
        owner = User(phone=f"+7995{next(_phone):07d}", full_name="Анна Смирнова",
                     hashed_password=get_password_hash("Bizpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name=name, description=description, address=f"{city}, ул. Тестовая 1",
            city=city, phone=f"+7995{next(_phone):07d}", latitude=56.5, longitude=84.9,
            working_hours=hours, logo_url=logo, timezone="Asia/Novosibirsk",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=mode, rating=0.0, reviews_count=0,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        master_ids = []
        for i in range(masters):
            muser = owner if i == 0 else User(
                phone=f"+7995{next(_phone):07d}", full_name=f"Борис Петров {i}",
                hashed_password=get_password_hash("Bizpass1"), role=UserRole.BUSINESS)
            if i:
                db.add(muser)
                await db.commit()
                await db.refresh(muser)
            m = Master(user_id=muser.id, salon_id=salon.id, specialization="Мастер",
                       is_active=True, break_minutes=0, experience_years=3)
            db.add(m)
            await db.commit()
            await db.refresh(m)
            master_ids.append(m.id)
            for sname, price, duration in services:
                db.add(Service(master_id=m.id, name=sname, price=price,
                               duration_minutes=duration, is_active=True))
            await db.commit()
        return salon.id, master_ids


def _card(html: str, salon_id: int) -> str:
    """Разметка одной карточки — чтобы проверки не ловили чужой текст."""
    start = html.index(f'data-salon-id="{salon_id}"')
    start = html.rindex("<article", 0, start)
    return html[start:html.index("</article>", start)]


def _hrefs(card: str) -> list[str]:
    """Ссылки свободных окон. &amp; разэкранирован: в разметке амперсанд обязан
    быть сущностью, а сравнивать удобнее с настоящим URL."""
    return [h.replace("&amp;", "&") for h in re.findall(r'class="r-slot" href="([^"]+)"', card)]


# ─────────────────────── форма карточки ───────────────────────

async def test_card_without_photo_and_description_is_complete(client, db_session):
    """Фото нет, описания нет — карточка всё равно несёт имя, город, услугу с
    ценой и временем. Это обычное состояние прода, а не краевое."""
    salon_id, _ = await _stand(db_session, "БезФотоZZ",
                               services=(("Маникюр с покрытием", 1500, 60),))
    card = _card((await client.get("/salons")).text, salon_id)

    assert "БезФотоZZ" in card
    assert "Томск" in card
    assert "Маникюр с покрытием" in card
    assert "1 500 ₽" in card
    assert "60 мин" in card
    # Вместо снимка — монограмма, а не пустая рамка и не градиентная заглушка.
    assert 'class="r-mark r-mark--lg"' in card
    assert "<img" not in card.split('class="r-salon__tags"')[0] or "logo" not in card
    # Пустого места под описание не осталось вовсе.
    assert "salon-desc" not in card


async def test_card_shows_the_photo_when_there_is_one(client, db_session):
    salon_id, _ = await _stand(db_session, "СФотоZZ", logo="/static/images/x.jpg")
    card = _card((await client.get("/salons")).text, salon_id)
    assert '<img src="/static/images/x.jpg"' in card


async def test_card_limits_the_services_and_says_how_many_are_left(client, db_session):
    """Обрезать список молча нельзя: «и ещё 2» — это факт, а не многоточие."""
    many = tuple((f"Услуга {i}", 1000 + i * 100, 30) for i in range(SERVICES_PER_CARD + 2))
    salon_id, _ = await _stand(db_session, "МногоУслугZZ", services=many)
    card = _card((await client.get("/salons")).text, salon_id)
    assert card.count('class="r-svc__row"') == SERVICES_PER_CARD
    assert "и ещё 2" in card


async def test_same_service_of_several_masters_is_one_line(client, db_session):
    """Три мастера с «Маникюром» — это одна услуга салона, а не три."""
    salon_id, _ = await _stand(db_session, "ТриМастераZZ", masters=3,
                               mode=SalonPanelMode.TEAM)
    card = _card((await client.get("/salons")).text, salon_id)
    rows = re.findall(r'class="r-svc__name">([^<]+)<', card)
    assert rows == ["Маникюр"], rows


async def test_solo_and_team_cards_name_what_they_are(client, db_session):
    solo_id, _ = await _stand(db_session, "СолоZZ")
    team_id, _ = await _stand(db_session, "КомандаZZ", masters=2, mode=SalonPanelMode.TEAM)
    html = (await client.get("/salons")).text
    assert "Мастер · Томск" in _card(html, solo_id)
    assert "Салон · Томск" in _card(html, team_id)


# ─────────────────────── свободные окна ───────────────────────

async def test_card_shows_nearest_slots_that_lead_into_booking(client, db_session):
    salon_id, master_ids = await _stand(db_session, "СОкнамиZZ")
    card = _card((await client.get("/salons")).text, salon_id)

    assert "Ближайшее время · Маникюр" in card
    slots = _hrefs(card)
    assert slots, card
    assert len(slots) <= SLOTS_PER_CARD
    # Ссылка несёт мастера, услугу и время — иначе «записаться из списка»
    # означало бы «открыть салон и начать заново».
    assert f"/salons/{salon_id}?master={master_ids[0]}&service=" in slots[0]
    assert "&slot=" in slots[0] and slots[0].endswith("#booking")


async def test_slot_in_the_card_is_the_same_slot_the_booking_api_offers(client, db_session):
    """Единственная проверка, из-за которой окна в каталоге вообще можно
    показывать: правила доступности считаются ТЕМИ ЖЕ функциями, что в
    /api/v1/bookings/available. Разойдись они — каталог начнёт обещать время,
    которого нет."""
    salon_id, master_ids = await _stand(db_session, "СверкаZZ")
    card = _card((await client.get("/salons")).text, salon_id)
    href = _hrefs(card)[0]
    params = dict(re.findall(r"[?&](\w+)=([^&#]+)", href))
    slot = params["slot"]

    api = await client.get(
        f"/api/v1/bookings/available/{params['master']}"
        f"?date={slot[:10]}&service_id={params['service']}"
    )
    assert api.status_code == 200
    assert slot in api.json()["slots"], (slot, api.json()["slots"][:5])


async def test_a_busy_hour_disappears_from_the_card(client, db_session):
    """Занятое время не показывается — иначе человек ткнёт в него и получит
    отказ там, где мы уже знали ответ."""
    from app.models.models import Booking, BookingStatus

    salon_id, master_ids = await _stand(db_session, "ЗанятоZZ")
    card = _card((await client.get("/salons")).text, salon_id)
    first = dict(re.findall(r"[?&](\w+)=([^&#]+)", _hrefs(card)[0]))["slot"]

    start = datetime.strptime(first, "%Y-%m-%dT%H:%M")
    async with db_session() as db:
        client_user = User(phone=f"+7995{next(_phone):07d}", full_name="Клиент",
                           hashed_password=get_password_hash("Testpass1"),
                           role=UserRole.CLIENT)
        db.add(client_user)
        await db.commit()
        await db.refresh(client_user)
        service_id = int(re.findall(r"service=(\d+)", card)[0])
        db.add(Booking(client_id=client_user.id, master_id=master_ids[0],
                       service_id=service_id, start_time=start,
                       end_time=start + timedelta(minutes=60),
                       status=BookingStatus.CONFIRMED))
        await db.commit()

    again = _card((await client.get("/salons")).text, salon_id)
    shown = [dict(re.findall(r"[?&](\w+)=([^&#]+)", h))["slot"] for h in _hrefs(again)]
    assert first not in shown, (first, shown)


async def test_no_services_means_no_slots_and_no_empty_block(client, db_session):
    salon_id, _ = await _stand(db_session, "БезУслугZZ", services=())
    card = _card((await client.get("/salons")).text, salon_id)
    assert "Ближайшее время" not in card
    assert "r-slot" not in card
    assert "БезУслугZZ" in card  # карточка всё равно на месте


async def test_closed_salon_shows_prices_without_time(client, db_session):
    """График не задан — окон нет, но услуги с ценами остаются: это и есть
    поведение «не уложились в окна» из решения 0011."""
    salon_id, _ = await _stand(db_session, "БезГрафикаZZ", hours=None)
    card = _card((await client.get("/salons")).text, salon_id)
    assert "Маникюр" in card and "1 500 ₽" in card
    assert "Ближайшее время" not in card


# ─────────────────────── цена в запросах ───────────────────────

@contextlib.contextmanager
def _counting():
    """Счётчик SQL-запросов. Считаем на уровне курсора, а не вызовов сервиса:
    так в счёт попадает и случайный запрос в цикле, которого в коде не видно."""
    from app.db.session import engine

    seen: list[str] = []

    def before(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def test_catalog_costs_two_queries_for_the_cards(client, db_session, monkeypatch):
    """Бюджет захода: выборка салонов плюс ОДИН запрос на всё содержимое
    карточек (услуги, акции, свободные окна).

    «До» измеряется на том же самом запросе с выключенным сбором содержимого:
    сравнивать с числом, записанным руками, нельзя — оно устареет на первом же
    чужом коммите в каталог.
    """
    from app.services import catalog_slots
    from app.web.pages import salons as salons_page

    for i in range(5):
        await _stand(db_session, f"ЦенаZZ{i}", masters=2, mode=SalonPanelMode.TEAM,
                     services=(("Маникюр", 1500, 60), ("Педикюр", 2000, 90)))

    # Прогрев: первый запрос тянет за собой разовые запросы пула и проверку pg_trgm.
    assert (await client.get("/salons")).status_code == 200

    real = catalog_slots.load_card_extras

    async def _no_extras(db, ids, **kw):
        return {}

    monkeypatch.setattr(salons_page, "load_card_extras", _no_extras)
    with _counting() as before:
        assert (await client.get("/salons")).status_code == 200
    was = len(before)

    monkeypatch.setattr(salons_page, "load_card_extras", real)
    with _counting() as after:
        page = await client.get("/salons")
        assert page.status_code == 200
    now = len(after)

    assert "Ближайшее время" in page.text, "мерили состояние, в котором окна есть"
    assert now - was == 1, f"содержимое карточек стоит {now - was} запросов: {after[was:]}"


async def test_slots_do_not_cost_a_query_per_salon(client, db_session, monkeypatch):
    """Главная ловушка задачи: окна считаются на связку «мастер + услуга +
    дата», и наивная реализация сделала бы запрос на карточку. Проверяем, что
    цена не растёт вместе с числом салонов."""
    from app.services import catalog_slots
    from app.web.pages import salons as salons_page

    async def _no_extras(db, ids, **kw):
        return {}

    for i in range(2):
        await _stand(db_session, f"РостZZ{i}")
    assert (await client.get("/salons")).status_code == 200

    monkeypatch.setattr(salons_page, "load_card_extras", catalog_slots.load_card_extras)
    with _counting() as two:
        assert (await client.get("/salons")).status_code == 200
    cost_two = len(two)

    for i in range(8):
        await _stand(db_session, f"РостЕщёZZ{i}")
    with _counting() as ten:
        page = await client.get("/salons")
        assert page.status_code == 200
    cost_ten = len(ten)

    assert "Ближайшее время" in page.text
    assert cost_ten == cost_two, (
        f"на 2 салонах {cost_two} запросов, на 10 — {cost_ten}: цена растёт с числом карточек"
    )


# ─────────────────────── главная ───────────────────────

#: Сколько карточек на главной ещё читается как подборка, а не как «вся база».
#: Число literal, а не HOME_CARDS: тест, сверяющий код с самим собой, пропустил
#: бы сетку на тридцать мест — она ведь «равна HOME_CARDS».
_SANE_HOME_CARDS = 9


async def test_home_shows_a_limited_number_of_cards_and_a_link_to_all(client, db_session):
    """Шесть карточек и «смотреть все» — и при девяти салонах, и при девятистах.
    Сетка на тридцать мест с четырьмя заполненными выглядела бы сломанной."""
    stands = 16
    for i in range(stands):
        await _stand(db_session, f"ГлавнаяZZ{i}")
    html = (await client.get("/")).text
    shown = html.count('class="r-salon salon-card"')
    assert shown == HOME_CARDS
    assert shown <= _SANE_HOME_CARDS, "это уже не подборка, а каталог на главной"
    assert shown < stands, "главная показывает всё — тогда «смотреть все» некуда ведёт"
    assert 'href="/salons"' in html
    assert "Смотреть все" in html


async def test_home_uses_the_same_card_as_the_catalog(client, db_session):
    """Не «такая же», а та же: один компонент на две страницы."""
    salon_id, _ = await _stand(db_session, "ОдинКомпонентZZ")
    home = _card((await client.get("/")).text, salon_id)
    catalog = _card((await client.get("/salons")).text, salon_id)
    # Окна считаются на «сейчас», поэтому сравниваем всё до блока окон.
    cut = 'class="r-salon__slots"'
    assert home.split(cut)[0] == catalog.split(cut)[0]


async def test_home_with_no_salons_invites_instead_of_apologising(client, db_session):
    html = (await client.get("/")).text
    assert "Здесь появятся мастера и салоны" in html
    assert 'class="r-salon salon-card"' not in html
