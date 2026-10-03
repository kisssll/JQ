"""Живой чек-лист «Путь к первому клиенту» в «Обзоре» (решение 0010, заход 6).

Почему проверяется именно это. Каждый пункт блока — утверждение о состоянии
чужого бизнеса: «обложки нет», «акций нет», «отзыва нет». Соврать здесь можно в
две стороны, и обе плохи. Сказать «не сделано» про сделанное — отправить
человека делать работу второй раз и подорвать доверие ко всему блоку. Сказать
«сделано» про несделанное — оставить его без клиентов, пока он считает, что всё
в порядке.

Отсюда состав файла:

  1. **Вердикт про запись не растворился.** Жёсткое условие решения 0010, п. 1:
     блок поглотил «Можно ли к вам записаться», и если записаться нельзя, об
     этом сказано теми же словами и тем же классом состояния (значит, тем же
     цветом), а не бодрым «выполнено 4 из 11».
  2. **По три проверки на каждый пункт группы 2:** выполнен, не выполнен, не
     применим. Третье состояние — не украшение: акция без услуг и вечерние окна
     без часов приёма физически не сработают.
  3. **Условный пункт про отзыв** появляется только после первой завершённой
     записи и исчезает, когда отзыв есть. Отзыв возможен лишь после
     завершённого через Руми визита — до него это была бы галочка, которую
     человек не в силах поставить.
  4. **Группа 3 не появляется раньше времени** и блок не исчезает ни в одном
     состоянии: он успел стать местом, куда человек смотрит.
  5. **Запросов не стало больше, чем обещано.** «Обзор» — самый посещаемый
     раздел панели (82 открытия из 229 за 25 дней), и его однажды разгоняли с
     девяти секунд до двух с половиной. Считаем счётчиком, а не на глаз.

Первая половина файла — без базы: evaluate() работает на значениях. Вторая
открывает панель по-настоящему: разметку, порядок и число запросов на значениях
не проверить.
"""
import json
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, OWNER_DEFAULT_PERMISSIONS, Promotion, Review,
    ReviewTargetType, Salon, SalonEveningDeal, SalonMember, SalonModerationStatus,
    SalonPanelMode, SalonRole, Schedule, Service, User, UserRole,
)
from app.services import booking_readiness, growth_checklist, panel_guide
from app.web.pages.business.tabs import overview

_WEEK_OPEN = json.dumps({d: "10:00-20:00" for d in
                         ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})

#: Признак блока в разметке — тот же, по которому его опознаёт
#: tests/test_overview_blocks.py: класс состояния у блока остался прежним.
BLOCK = 'class="readiness readiness-'
GROUP_NEXT = "Куда смотреть дальше"


def _values(**over):
    """Значения для evaluate(): всё сделано, кроме того, что передали."""
    base = dict(
        solo=False, has_cover=True, has_description=True, services_total=3,
        has_active_promo=True, evening_on=True, salon_hours_set=True,
        promoted_tier=True, has_completed_booking=False, has_review=False,
    )
    base.update(over)
    return base


def _keys(checklist):
    return [i.key for i in checklist.items]


def _pending(checklist):
    return [i.key for i in checklist.pending]


# ─────────────────── группа 2: по три состояния на пункт ───────────────────

@pytest.mark.parametrize("key, undone", [
    ("cover", {"has_cover": False}),
    ("description", {"has_description": False}),
    ("services", {"services_total": 0}),
    ("promo", {"has_active_promo": False}),
    ("evening", {"evening_on": False}),
    ("tariff", {"promoted_tier": False}),
])
def test_each_item_is_done_when_the_salon_has_it(key, undone):
    """Выполненный пункт в списке дел не висит — он уходит в «Сделано: N»."""
    done = growth_checklist.evaluate(**_values())
    assert key in _keys(done), f"пункт {key} вообще не появился"
    assert key not in _pending(done), f"пункт {key} висит выполненным"

    not_done = growth_checklist.evaluate(**_values(**undone))
    assert key in _pending(not_done), f"пункт {key} пропал невыполненным"


def test_done_items_collapse_into_a_count():
    """Решение 0010, п. 5: шесть галочек подряд — обои, а не список дел."""
    one_left = growth_checklist.evaluate(**_values(has_cover=False))
    assert _pending(one_left) == ["cover"]
    assert one_left.done_count == 5
    assert not one_left.all_done

    nothing_left = growth_checklist.evaluate(**_values())
    assert nothing_left.pending == ()
    assert nothing_left.done_count == 6
    assert nothing_left.all_done


def test_a_promo_without_services_is_not_shown_at_all():
    """Скидка без услуг ни к чему не применяется. Такой пункт не просто не
    выполнен — его нельзя выполнить, и в «Сделано: N» он тоже не идёт."""
    c = growth_checklist.evaluate(**_values(services_total=0, has_active_promo=False))
    assert "promo" not in _keys(c)
    assert "services" in _pending(c), "а вот про услуги сказать обязаны"


def test_evening_windows_are_not_shown_without_opening_hours():
    """Вечерних окон не бывает, пока нет часов приёма: свободных слотов нет ни
    в один день, и настраивать скидку на них бессмысленно."""
    c = growth_checklist.evaluate(**_values(salon_hours_set=False, evening_on=False))
    assert "evening" not in _keys(c)


def test_evening_windows_are_not_shown_without_services():
    c = growth_checklist.evaluate(**_values(services_total=0, evening_on=False))
    assert "evening" not in _keys(c)


def test_the_tariff_item_is_the_last_one():
    """Решение 0010, п. 3: единственный пункт, который стоит денег, стоит
    последним — иначе список читается как счёт, а не как путь."""
    c = growth_checklist.evaluate(**_values(
        has_cover=False, has_description=False, services_total=0,
        has_active_promo=False, evening_on=False, promoted_tier=False,
    ))
    assert _keys(c)[-1] == "tariff"


def test_the_tariff_item_states_a_fact_without_pressure():
    """Текст пункта — факт про выдачу, а не давление: ни «подключите», ни
    «пора», ни восклицания."""
    for solo in (False, True):
        text = dict((k, t) for k, t, _a, _r in
                    panel_guide.check_items(solo=solo))["tariff"]
        assert "!" not in text
        for pushy in ("пора", "стоит подключить", "успейте", "выгодно"):
            assert pushy not in text.lower(), pushy


@pytest.mark.parametrize("tier, promoted", [
    ("business", True), ("corporate", True), ("custom", True),
    ("lite", False), ("", False), (None, False),
])
def test_promoted_tiers_match_the_catalog(tier, promoted):
    """Набор тарифов с подъёмом — тот же, что отбирает каталог (salons.py,
    _PAID). Разъехавшись с ним, пункт начал бы врать про выдачу."""
    assert ((tier or "") in growth_checklist.PROMOTED_TIERS) is promoted


# ─────────────────── условный пункт про отзыв ───────────────────

def test_the_review_item_appears_only_after_the_first_completed_visit():
    before = growth_checklist.evaluate(**_values(has_completed_booking=False))
    assert "review" not in _keys(before), \
        "отзыв невозможен до завершённой записи — просить его нельзя"

    after = growth_checklist.evaluate(**_values(has_completed_booking=True))
    assert "review" in _pending(after)


def test_the_review_item_disappears_once_there_is_a_review():
    c = growth_checklist.evaluate(**_values(has_completed_booking=True, has_review=True))
    assert "review" not in _keys(c)
    assert c.all_done, "отзыв есть — дел не осталось"


def test_the_review_item_never_counts_as_done():
    """Он либо нужен, либо его нет: «сделано» про просьбу к клиенту платформа
    знать не может."""
    c = growth_checklist.evaluate(**_values(has_completed_booking=True))
    assert c.done_count == 6
    assert _pending(c) == ["review"]


# ─────────────────── контракт с booking_readiness ───────────────────

def test_the_hours_key_we_lean_on_still_exists():
    """«Часы приёма не заданы» мы берём ключом причины, а не вторым разбором
    working_hours. Ключ входит в контракт booking_readiness — переименуют его
    молча, и вечерние окна начнут требоваться у салона без часов."""
    assert growth_checklist._NO_HOURS_KEY in booking_readiness.ISSUE_KEYS


# ─────────────────── группа 3 ───────────────────

@pytest.mark.parametrize("mode, expected", [
    (SalonPanelMode.TEAM, ("records", "analytics", "reviews", "crm")),
    (SalonPanelMode.SOLO, ("records", "overview", "reviews", "crm")),
])
def test_the_next_group_links_match_the_mode(mode, expected):
    """В соло «Аналитики» нет вовсе (panel_sections), и ссылка вела бы в
    выключенную вкладку — на её месте сам «Обзор»."""
    salon = Salon(name="Т", panel_mode=mode)
    links = growth_checklist.next_links(
        salon, solo=mode is SalonPanelMode.SOLO, visible_keys=expected,
    )
    assert tuple(k for k, _label, _phrase in links) == expected
    for _k, label, phrase in links:
        assert label and phrase


def test_the_next_group_skips_a_section_the_person_has_not_got():
    """Ссылка в выключенный раздел не ошибка 404, а молчаливый возврат в
    «Обзор»: человек нажимает и оказывается там, откуда нажал."""
    salon = Salon(name="Т", panel_mode=SalonPanelMode.TEAM)
    links = growth_checklist.next_links(
        salon, solo=False, visible_keys=("records", "reviews"),
    )
    assert [k for k, _l, _p in links] == ["records", "reviews"]


# ═══════════════════════ панель по-настоящему ═══════════════════════

async def _salon(db_session, phone, mode, *, master=True, service=True, hours=True,
                 published=True, tariff=True, cover=False, description=False,
                 promo=False, evening=False, tier="lite", completed=False,
                 review=False):
    """Салон с нужным состоянием. Флаги — ровно те, из которых состоит блок."""
    async with db_session() as db:
        owner = User(phone=phone, full_name="Ольга Мастерова",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name=f"Путь {phone}", address="Томск, ул. Ленина, 1",
            phone="+73822000777", latitude=56.4, longitude=84.9, timezone="Asia/Tomsk",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=mode,
            working_hours=_WEEK_OPEN if hours else None,
            guest_booking_enabled=True, business_tier=tier,
            logo_url="/static/uploads/cover.jpg" if cover else None,
            description="Маникюр и педикюр рядом с центром." if description else None,
            access_until=(datetime.now(timezone.utc) + timedelta(days=30)
                          if tariff else None),
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
        if promo:
            db.add(Promotion(salon_id=salon.id, title="Первый визит -20%",
                             tag="Скидка", is_active=True))
        if evening:
            db.add(SalonEveningDeal(salon_id=salon.id, enabled=True,
                                    discount_percent=15, weekdays=[], service_ids=[]))
        await db.commit()

        if master:
            m = Master(user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
                       experience_years=3, rating=0.0, is_active=True)
            db.add(m)
            await db.commit()
            await db.refresh(m)
            if service:
                db.add(Service(master_id=m.id, name="Маникюр", price=2000,
                               duration_minutes=60, is_active=True,
                               is_model_practice=False))
            for wd in range(5):
                db.add(Schedule(master_id=m.id, day_of_week=wd,
                                start_time=time(10, 0), end_time=time(19, 0)))
            await db.commit()

            if completed and service:
                svc = (await db.execute(
                    select(Service).where(Service.master_id == m.id)
                )).scalars().first()
                client_user = User(phone="+7994" + phone[-7:],
                                   full_name="Клиент",
                                   hashed_password=get_password_hash("Testpass1"),
                                   role=UserRole.CLIENT, is_active=True)
                db.add(client_user)
                await db.commit()
                await db.refresh(client_user)
                start = datetime.now().replace(hour=12, minute=0, second=0,
                                               microsecond=0) - timedelta(days=1)
                booking = Booking(client_id=client_user.id, master_id=m.id,
                                  service_id=svc.id, start_time=start,
                                  end_time=start + timedelta(minutes=60),
                                  status=BookingStatus.COMPLETED, final_price=2000)
                db.add(booking)
                await db.commit()
                if review:
                    await db.refresh(booking)
                    db.add(Review(client_id=client_user.id, salon_id=salon.id,
                                  target_type=ReviewTargetType.MASTER, master_id=m.id,
                                  rating=5, comment="Хорошо", is_verified=True,
                                  booking_id=booking.id))
                    await db.commit()
        return salon.id


async def _open(client, phone, salon_id):
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": phone, "password": "Testpass1"})
    assert r.status_code == 302, r.text
    page = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert page.status_code == 200
    return page.text[page.text.index('id="tab-overview"'):]


# ─────────── жёсткое условие: красный вердикт на месте ───────────

async def test_the_red_verdict_survived_the_merge(client, db_session):
    """Решение 0010, п. 1. Блок поглотил «Можно ли к вам записаться», и это
    единственная строка в панели, из которой человек узнаёт, что заявок не
    будет. Проверяем и слова, и класс состояния: класс — это цвет."""
    salon_id = await _salon(db_session, "+79995550001", SalonPanelMode.SOLO,
                            master=False, service=False)
    body = await _open(client, "+79995550001", salon_id)
    assert "Записаться к вам сейчас нельзя" in body
    assert 'class="readiness readiness-bad growth"' in body
    assert "Пока это не исправлено, заявок не будет — даже по ссылке." in body
    # Причины группы 1 — из booking_readiness, как были.
    assert "Нет вашей карточки мастера" in body
    # И «выполнено N из 11» вердикт не заменило.
    assert "выполнено" not in body.lower()


async def test_the_green_verdict_keeps_its_words_too(client, db_session):
    salon_id = await _salon(db_session, "+79995550002", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550002", salon_id)
    assert "Записаться к вам можно" in body
    assert 'class="readiness readiness-ok growth"' in body


# ─────────── четыре состояния: блок не исчезает ни в одном ───────────

async def test_an_empty_salon_sees_the_path_with_both_groups(client, db_session):
    """Состояние 1: пустой салон. Группа 1 полна причин, группа 2 — дел."""
    salon_id = await _salon(db_session, "+79995550010", SalonPanelMode.SOLO,
                            master=False, service=False, hours=False,
                            published=False, tariff=False)
    body = await _open(client, "+79995550010", salon_id)
    assert BLOCK in body
    assert panel_guide.CHECKLIST_TITLE in body
    assert "Чтобы вас было видно" in body
    assert "Чтобы выбирали вас" in body
    assert "Обложка не выбрана" in body
    # Неприменимое не висит: ни акции без услуг, ни вечерних окон без часов.
    assert "Акций нет" not in body
    assert "Вечерние окна со скидкой выключены" not in body
    assert GROUP_NEXT not in body


async def test_a_salon_with_booking_working_still_has_things_to_do(client, db_session):
    """Состояние 2: группа 1 закрыта, группа 2 — нет."""
    salon_id = await _salon(db_session, "+79995550011", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550011", salon_id)
    assert BLOCK in body
    assert panel_guide.CHECK_VISIBLE_CLEAR in body, "группа 1 исчезла вместо итога"
    assert "Обложка не выбрана" in body
    assert "Акций нет" in body
    assert "Вечерние окна со скидкой выключены" in body
    assert GROUP_NEXT not in body


async def test_everything_closed_turns_the_block_into_a_signpost(client, db_session):
    """Состояние 3: дел нет — блок меняет роль, но не исчезает."""
    salon_id = await _salon(db_session, "+79995550012", SalonPanelMode.SOLO,
                            cover=True, description=True, promo=True, evening=True,
                            tier="business")
    body = await _open(client, "+79995550012", salon_id)
    assert BLOCK in body
    assert GROUP_NEXT in body
    assert f"{panel_guide.CHECK_DONE_PREFIX}: 6" in body
    # Ни одного дела не осталось — значит ни одной строки «не выбрана / нет».
    assert "Обложка не выбрана" not in body
    assert "Акций нет" not in body
    assert "tab=records" in body, "группа 3 должна вести в разделы"


async def test_a_salon_with_a_finished_visit_is_asked_for_a_review(client, db_session):
    """Состояние 4: всё закрыто, визит завершён, отзыва нет."""
    salon_id = await _salon(db_session, "+79995550013", SalonPanelMode.SOLO,
                            cover=True, description=True, promo=True, evening=True,
                            tier="business", completed=True)
    body = await _open(client, "+79995550013", salon_id)
    assert "попросите клиента" in body
    assert GROUP_NEXT not in body, "дело есть — группе 3 ещё рано"


async def test_the_review_request_goes_away_when_the_review_arrives(client, db_session):
    salon_id = await _salon(db_session, "+79995550014", SalonPanelMode.SOLO,
                            cover=True, description=True, promo=True, evening=True,
                            tier="business", completed=True, review=True)
    body = await _open(client, "+79995550014", salon_id)
    assert "попросите клиента" not in body
    assert GROUP_NEXT in body


async def test_a_pending_booking_is_not_a_finished_visit(client, db_session):
    """Записи есть, но ни одна не завершена: отзыв пока невозможен, и просить
    его нельзя. Этот случай и отличает «есть записи» от «визит состоялся»."""
    salon_id = await _salon(db_session, "+79995550015", SalonPanelMode.SOLO,
                            cover=True, description=True, promo=True, evening=True,
                            tier="business")
    async with db_session() as db:
        m = (await db.execute(select(Master).where(Master.salon_id == salon_id))
             ).scalars().first()
        svc = (await db.execute(select(Service).where(Service.master_id == m.id))
               ).scalars().first()
        c = User(phone="+79994440015", full_name="Клиент",
                 hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.CLIENT, is_active=True)
        db.add(c)
        await db.commit()
        await db.refresh(c)
        start = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
        db.add(Booking(client_id=c.id, master_id=m.id, service_id=svc.id,
                       start_time=start, end_time=start + timedelta(minutes=60),
                       status=BookingStatus.CONFIRMED, final_price=2000))
        await db.commit()
    body = await _open(client, "+79995550015", salon_id)
    assert "попросите клиента" not in body
    assert GROUP_NEXT in body


# ─────────── место блока ───────────

async def test_in_solo_the_path_comes_first(client, db_session):
    salon_id = await _salon(db_session, "+79995550020", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550020", salon_id)
    assert body.index(BLOCK) < body.index('class="booking-link-title"')


async def test_in_a_team_the_path_comes_below_the_numbers(client, db_session):
    """Решение 0010, «место блока»: салону с командой первый экран занимать
    есть чем."""
    salon_id = await _salon(db_session, "+79995550021", SalonPanelMode.TEAM,
                            completed=True)
    body = await _open(client, "+79995550021", salon_id)
    positions = [body.index(m) for m in
                 ('class="stats-grid-4"', "Выручка за неделю", BLOCK)]
    assert positions == sorted(positions), positions


# ─────────── адреса действий ───────────

async def test_in_solo_the_settings_actions_lead_to_the_master_card(client, db_session):
    """В соло вкладки «Редактировать салон» нет: её содержимое лежит в «Моей
    карточке мастера» двумя группами (решение 0009). Ссылка в неё молча
    вернула бы человека в «Обзор»."""
    salon_id = await _salon(db_session, "+79995550030", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550030", salon_id)
    assert "tab=employees#panel-card-public" in body
    assert "tab=edit" not in body


async def test_in_a_team_the_settings_actions_lead_to_the_salon_tab(client, db_session):
    salon_id = await _salon(db_session, "+79995550031", SalonPanelMode.TEAM)
    body = await _open(client, "+79995550031", salon_id)
    assert "tab=edit" in body


async def test_the_evening_action_lands_on_the_evening_section(client, db_session):
    """Без якоря ссылка привела бы в начало длинных «Акций», где секции
    вечерних окон не видно."""
    salon_id = await _salon(db_session, "+79995550032", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550032", salon_id)
    assert f"tab=promos#{growth_checklist.ANCHOR_EVENING}" in body
    promos = await client.get(
        f"/business/dashboard?salon_id={salon_id}&tab=promos")
    assert f'id="{growth_checklist.ANCHOR_EVENING}"' in promos.text, \
        "якорь есть в ссылке, но не в самой секции"


# ─────────── цена блока в запросах ───────────

def _counting_queries():
    """Счётчик SQL-запросов на время блока with.

    Считаем на уровне курсора, а не вызовов сервиса: так в счёт попадает ВСЁ,
    включая случайный запрос в цикле, который на глаз в коде не виден. «Обзор»
    — самый посещаемый раздел панели, и его однажды разгоняли с девяти секунд
    до двух с половиной; поэтому цена блока измеряется, а не оценивается.
    """
    import contextlib

    from sqlalchemy import event

    from app.db.session import engine

    @contextlib.contextmanager
    def ctx():
        seen: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            yield seen
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)

    return ctx()


async def test_the_block_costs_no_more_than_three_queries(client, db_session, monkeypatch):
    """Решение 0010 и бюджет захода: на весь блок — не больше трёх новых
    запросов, и ни одного в цикле по мастерам или услугам.

    «До» измеряем на том же самом запросе с выключённым сбором группы 2:
    сравнивать с числом, записанным руками, нельзя — оно устареет на первом же
    чужом коммите в «Обзор».

    Салон здесь в самом дорогом состоянии: часы заданы, услуги есть, записи
    есть — то есть оба запроса сбора действительно уходят в базу.
    """
    salon_id = await _salon(db_session, "+79995550040", SalonPanelMode.TEAM,
                            cover=True, description=True, promo=True, evening=True,
                            tier="business", completed=True, review=True)
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": "+79995550040", "password": "Testpass1"})
    assert r.status_code == 302
    url = f"/business/dashboard?salon_id={salon_id}"

    # Прогрев: первый запрос в тесте тянет за собой разовые запросы пула.
    assert (await client.get(url)).status_code == 200

    real_collect = growth_checklist.collect

    async def _no_collect(*a, **kw):
        return growth_checklist.Checklist()

    monkeypatch.setattr(growth_checklist, "collect", _no_collect)
    with _counting_queries() as before:
        assert (await client.get(url)).status_code == 200
    was = len(before)

    monkeypatch.setattr(growth_checklist, "collect", real_collect)
    with _counting_queries() as after:
        page = await client.get(url)
        assert page.status_code == 200
    now = len(after)

    assert GROUP_NEXT in page.text, "мерили состояние, в котором блок полон"
    assert now - was <= 3, f"запросов стало {now} вместо {was}: {after[was:]}"
    # Фиксируем и фактическую цену: два запроса, не три.
    assert now - was == 2, f"цена блока изменилась: {now - was}"


async def test_a_brand_new_salon_pays_nothing_for_the_second_group(client, db_session,
                                                                  monkeypatch):
    """У салона без часов приёма и без записей сбор группы 2 в базу не ходит
    вовсе: вечерние окна неприменимы, а отзыв без завершённой записи невозможен.
    Это тот самый салон, который чаще всего и открывает «Обзор»."""
    salon_id = await _salon(db_session, "+79995550041", SalonPanelMode.SOLO,
                            master=False, service=False, hours=False)
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": "+79995550041", "password": "Testpass1"})
    assert r.status_code == 302
    url = f"/business/dashboard?salon_id={salon_id}"
    assert (await client.get(url)).status_code == 200

    real_collect = growth_checklist.collect

    async def _no_collect(*a, **kw):
        return growth_checklist.Checklist()

    monkeypatch.setattr(growth_checklist, "collect", _no_collect)
    with _counting_queries() as before:
        assert (await client.get(url)).status_code == 200

    monkeypatch.setattr(growth_checklist, "collect", real_collect)
    with _counting_queries() as after:
        assert (await client.get(url)).status_code == 200

    assert len(after) == len(before), f"лишние запросы: {after[len(before):]}"


async def test_nothing_is_queried_per_master_or_per_service(client, db_session,
                                                            monkeypatch):
    """N+1 ловится не чтением кода, а числом: добавляем мастеров и услуги и
    смотрим, что цена блока не поехала. Без этого теста запрос в цикле прожил
    бы до первого салона с десятком мастеров."""
    async def _cost(phone, extra):
        salon_id = await _salon(db_session, phone, SalonPanelMode.TEAM,
                                cover=True, description=True, promo=True,
                                evening=True, tier="business", completed=True)
        if extra:
            async with db_session() as db:
                salon = (await db.execute(
                    select(Salon).where(Salon.id == salon_id))).scalar_one()
                for n in range(extra):
                    u = User(phone=f"+7993{phone[-6:]}{n}", full_name=f"Мастер {n}",
                             hashed_password=get_password_hash("Testpass1"),
                             role=UserRole.BUSINESS, is_active=True)
                    db.add(u)
                    await db.commit()
                    await db.refresh(u)
                    m = Master(user_id=u.id, salon_id=salon.id,
                               specialization="Брови", experience_years=1,
                               rating=0.0, is_active=True)
                    db.add(m)
                    await db.commit()
                    await db.refresh(m)
                    for k in range(3):
                        db.add(Service(master_id=m.id, name=f"Услуга {n}-{k}",
                                       price=1000, duration_minutes=30,
                                       is_active=True, is_model_practice=False))
                    db.add(Schedule(master_id=m.id, day_of_week=0,
                                    start_time=time(11, 0), end_time=time(18, 0)))
                await db.commit()
        r = await client.post("/api/v1/auth/login-web",
                              data={"phone": phone, "password": "Testpass1"})
        assert r.status_code == 302
        url = f"/business/dashboard?salon_id={salon_id}"
        assert (await client.get(url)).status_code == 200

        real_collect = growth_checklist.collect

        async def _no_collect(*a, **kw):
            return growth_checklist.Checklist()

        monkeypatch.setattr(growth_checklist, "collect", _no_collect)
        with _counting_queries() as before:
            assert (await client.get(url)).status_code == 200
        monkeypatch.setattr(growth_checklist, "collect", real_collect)
        with _counting_queries() as after:
            assert (await client.get(url)).status_code == 200
        return len(after) - len(before)

    assert await _cost("+79995550050", 0) == await _cost("+79995550051", 4)


# ═════════ свёртка и линия прогресса (решение 0010, дополнение 03.10.2026) ═════════
#
# Заход 6.5 — про подачу, а не про пункты. Поэтому проверяется ровно то, что
# подача может сломать:
#
#   1. **Вердикт нельзя спрятать.** Свёрнутый блок — не способ убрать с экрана
#      «записаться нельзя» (п. 4 дополнения). Значит, вердикт и его класс
#      состояния обязаны лежать СНАРУЖИ свёртки: не «такие же», а те же самые.
#   2. **Прогресс считает применимое.** Линия, считающая скрытые пункты,
#      соврала бы дважды: показала бы «сделано» за то, чего человек не делал, и
#      прыгнула бы при любой нашей правке применимости.
#   3. **Без JS ничего не потеряно.** Серверный HTML у нас основа. Свёртка
#      включается классом из скрипта, и без него блок читается целиком.

PROGRESS = 'class="growth-progress-track"'
BODY_SPLIT = '<div class="growth-body"'


def _split_header(body):
    """Шапка блока и его свёртываемое тело — отдельно.

    Шапка — это то, что видно в ЛЮБОМ состоянии. Разделять по разметке, а не
    верить глазам: «вердикт остался красным» проверяется именно тем, что он
    лежит вне свёртки, и никакой CSS его оттуда не уберёт.
    """
    section = body[body.index(BLOCK) - len('class="'):]
    section = section[:section.index("</section>")]
    assert BODY_SPLIT in section, "у блока нет свёртываемого тела"
    head, _, tail = section.partition(BODY_SPLIT)
    return head, tail


# ─────────── вердикт лежит снаружи свёртки ───────────

@pytest.mark.parametrize("flags,state,words", [
    (dict(master=False, service=False), "bad", "Записаться к вам сейчас нельзя"),
    (dict(), "ok", "Записаться к вам можно"),
])
async def test_the_verdict_stays_outside_the_collapse(client, db_session, flags,
                                                      state, words):
    """Жёсткое условие п. 4 дополнения. Вердикт, его класс состояния и приписка
    под ним — в шапке, а не в свёртываемом теле: в свёрнутом виде они читаются
    теми же словами и тем же цветом, потому что это ровно тот же HTML."""
    phone = "+7999555060" + ("1" if state == "bad" else "2")
    salon_id = await _salon(db_session, phone, SalonPanelMode.SOLO, **flags)
    body = await _open(client, phone, salon_id)
    head, tail = _split_header(body)

    assert f"readiness-{state} growth" in head, "класс состояния уехал в тело"
    assert words in head
    assert words not in tail
    # Линия прогресса тоже в шапке: иначе в свёрнутом виде её не было бы видно.
    assert PROGRESS in head
    # А группы — в теле: свёртке нечего было бы скрывать.
    assert "Чтобы вас было видно" in tail


async def test_the_red_verdict_is_not_softened_by_the_progress_line(client, db_session):
    """Полоса рядом с красным вердиктом не должна превращать его в «почти всё
    хорошо»: слова и приписка про «заявок не будет» остаются на месте."""
    salon_id = await _salon(db_session, "+79995550603", SalonPanelMode.SOLO,
                            master=False, service=False, hours=False,
                            published=False, tariff=False)
    body = await _open(client, "+79995550603", salon_id)
    head, _tail = _split_header(body)
    assert "Записаться к вам сейчас нельзя" in head
    assert "Пока это не исправлено, заявок не будет — даже по ссылке." in head
    assert "выполнено" not in body.lower()


# ─────────── «сделано N из M» по применимым пунктам обеих групп ───────────

def test_the_progress_counts_the_gates_of_the_first_group():
    """«Всего» группы 1 — число ворот, и оно одно и то же у любого салона.

    Иначе линия прыгала бы на ровном месте: причины внутри ворот стоят через
    elif, и закрытие одной открывает другую (нет мастера → мастер без услуг).
    """
    keys = set()
    for _gate, gate_keys in overview._VISIBLE_GATES:
        keys |= set(gate_keys)
    assert keys == booking_readiness.ISSUE_KEYS, (
        "в booking_readiness появилась причина, не попавшая ни в одни ворота — "
        "линия прогресса молча перестанет её считать"
    )


def _readiness(**kw):
    base = dict(
        solo=True, is_active=True, is_deleted=False, is_hidden=False,
        moderation_status=SalonModerationStatus.APPROVED,
        published_at=datetime(2026, 1, 1), has_tariff=True,
        guest_booking_enabled=True, active_masters=1, bookable_masters=1,
        salon_hours_set=True, open_weekdays=5,
    )
    base.update(kw)
    return booking_readiness.evaluate(**base)


def test_the_progress_of_a_clean_first_group_is_full():
    done, total = overview._path_progress(_readiness(), None)
    assert (done, total) == (8, 8)


@pytest.mark.parametrize("broken,open_gates", [
    (dict(has_tariff=False), 1),
    (dict(published_at=None), 1),
    (dict(active_masters=0, bookable_masters=0), 1),
    (dict(salon_hours_set=False), 1),
    (dict(is_hidden=True), 1),
    (dict(guest_booking_enabled=False), 1),
    (dict(moderation_status=SalonModerationStatus.PENDING), 1),
    (dict(has_tariff=False, published_at=None, is_hidden=True), 3),
])
def test_each_broken_gate_costs_exactly_one(broken, open_gates):
    done, total = overview._path_progress(_readiness(**broken), None)
    assert total == 8
    assert done == 8 - open_gates


def test_closing_one_reason_inside_a_gate_does_not_move_the_line_backwards():
    """Человек заводит карточку мастера — и вместо «записываться не к кому»
    появляется «ни одной услуги». Это одно и то же условие, рассказанное двумя
    фразами, и прогресс обязан остаться на месте, а не отчитаться и отобрать."""
    before = overview._path_progress(
        _readiness(active_masters=0, bookable_masters=0), None)
    after = overview._path_progress(
        _readiness(active_masters=1, bookable_masters=0), None)
    assert before == after == (7, 8)
    # А настоящее закрытие ворот прогресс двигает.
    assert overview._path_progress(_readiness(), None) == (8, 8)


def test_a_deleted_salon_does_not_get_credit_for_unchecked_conditions():
    """evaluate() обрывается на удалённом салоне и остальных условий не
    проверяет вовсе. Записать их в «сделано» значило бы отчитаться за проверки,
    которых не было, — поэтому группа 1 сжимается до 0 из 1."""
    done, total = overview._path_progress(_readiness(is_deleted=True), None)
    assert (done, total) == (0, 1)


def _checklist(**kw):
    base = dict(
        solo=True, has_cover=False, has_description=False, services_total=1,
        has_active_promo=False, evening_on=False, salon_hours_set=True,
        promoted_tier=False, has_completed_booking=False, has_review=False,
    )
    base.update(kw)
    return growth_checklist.evaluate(**base)


def test_the_progress_adds_up_both_groups():
    """Группа 2 идёт в линию как есть: применимых пунктов шесть, выполнена
    одна («услуги добавлены»), и к восьми закрытым воротам прибавляется она."""
    done, total = overview._path_progress(_readiness(), _checklist())
    assert (done, total) == (9, 14)


def test_nothing_done_and_everything_done():
    nothing = overview._path_progress(
        _readiness(has_tariff=False, published_at=None, active_masters=0,
                   bookable_masters=0, salon_hours_set=False),
        _checklist(services_total=0, salon_hours_set=False),
    )
    # Четыре открытых ворот из восьми; в группе 2 применимы только четыре
    # пункта из шести — акция и вечерние окна без услуг не сработают.
    assert nothing == (4, 12)

    everything = overview._path_progress(
        _readiness(),
        _checklist(has_cover=True, has_description=True, has_active_promo=True,
                   evening_on=True, promoted_tier=True),
    )
    assert everything == (14, 14)


def test_an_inapplicable_item_falls_out_of_both_n_and_m():
    """Скрытый пункт не попадает ни в «сделано», ни в «всего». Иначе человек с
    пустым салоном увидел бы «сделано 4 из 14» и пошёл искать дела, которых ему
    не показывают."""
    shown = overview._path_progress(_readiness(), _checklist(services_total=1))
    hidden = overview._path_progress(
        _readiness(active_masters=1, bookable_masters=0),
        _checklist(services_total=0),
    )
    assert shown[1] - hidden[1] == 2, "акция и вечерние окна должны выпасть из «всего»"
    # И в «сделано» они тоже не попали: единственное, что было сделано в
    # группе 2 — услуги, и без них «сделано» группы 2 равно нулю.
    assert hidden[0] == 7, "за скрытые пункты начислили «сделано»"


def test_the_review_item_counts_in_the_total_but_never_as_done():
    """Условный пункт про отзыв — такое же дело, как остальные: он в «всего» и
    он не «сделано» (сделанным он быть не может, он для этого и появился)."""
    without = overview._path_progress(_readiness(), _checklist())
    withit = overview._path_progress(
        _readiness(), _checklist(has_completed_booking=True))
    assert withit[1] == without[1] + 1
    assert withit[0] == without[0]


# ─────────── состояние по умолчанию и жизнь без JS ───────────

async def test_by_default_the_block_is_open_while_there_are_things_to_do(
        client, db_session):
    salon_id = await _salon(db_session, "+79995550610", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550610", salon_id)
    head, _tail = _split_header(body)
    assert "is-collapsed" not in head, "блок с делами пришёл свёрнутым"
    assert 'aria-expanded="true"' in head


async def test_by_default_the_block_is_collapsed_when_nothing_is_left(
        client, db_session):
    """Дел не осталось — внутри только «куда смотреть дальше», и держать его
    раскрытым незачем (решение 0010, дополнение, п. 3)."""
    salon_id = await _salon(db_session, "+79995550611", SalonPanelMode.SOLO,
                            cover=True, description=True, promo=True, evening=True,
                            tier="business")
    body = await _open(client, "+79995550611", salon_id)
    head, tail = _split_header(body)
    assert "is-collapsed" in head
    # Но содержимое на месте — свёрнут, а не выпотрошен.
    assert GROUP_NEXT in tail
    assert panel_guide.check_progress(14, 14) in head


async def test_without_js_the_block_is_readable_whole(client, db_session):
    """Класс is-collapsible ставит скрипт, и правила свёртки в CSS висят только
    на нём. В серверной разметке его нет — значит страница без JS (или до
    загрузки бандла) показывает блок целиком, включая свёрнутый по умолчанию."""
    salon_id = await _salon(db_session, "+79995550612", SalonPanelMode.SOLO,
                            cover=True, description=True, promo=True, evening=True,
                            tier="business")
    body = await _open(client, "+79995550612", salon_id)
    assert "is-collapsible" not in body
    # Все группы и итоги — в разметке, а не подгружаются по клику.
    assert panel_guide.CHECK_VISIBLE_CLEAR in body
    assert "Чтобы вас было видно" in body
    assert "Чтобы выбирали вас" in body
    assert GROUP_NEXT in body
    assert f"{panel_guide.CHECK_DONE_PREFIX}: 6" in body
    # Кнопка без скрипта не притворяется работающей.
    assert "<button class=\"growth-toggle\" type=\"button\" hidden" in body


async def test_the_toggle_is_a_real_button_tied_to_the_body(client, db_session):
    """Свёртка — кнопка с aria-expanded и aria-controls, а не div с onclick:
    иначе её не видно ни с клавиатуры, ни с экранного диктора."""
    salon_id = await _salon(db_session, "+79995550613", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550613", salon_id)
    head, _tail = _split_header(body)
    assert f'aria-controls="growth-body-{salon_id}"' in head
    assert f'<div class="growth-body" id="growth-body-{salon_id}"' in body
    assert panel_guide.CHECK_IMPROVE in head


async def test_the_progress_line_is_readable_without_colour(client, db_session):
    """Полоса — не единственный носитель числа: рядом стоит подпись, и то же
    число лежит в aria-valuetext для тех, кто полосу не видит вовсе."""
    salon_id = await _salon(db_session, "+79995550614", SalonPanelMode.SOLO)
    body = await _open(client, "+79995550614", salon_id)
    note = panel_guide.check_progress(9, 14)
    assert f'aria-valuetext="{note}"' in body
    assert f'<p class="growth-progress-note">{note}</p>' in body
    assert 'aria-valuemax="14"' in body and 'aria-valuenow="9"' in body
