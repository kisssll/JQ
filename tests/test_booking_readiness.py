"""«Можно ли к вам записаться» — блок на главном экране панели (решение 0007, п. 6).

Этот блок — обещание человеку: он говорит, принимают ли у него записи, и если
нет, то почему. Соврать здесь дороже всего: мастер поверит, что всё настроено,
и будет ждать клиентов, которых физически не может быть. Поэтому каждое
условие проверяется отдельным тестом, а сами условия выписаны из кода записи,
а не придуманы.

Откуда взято каждое условие — в app/services/booking_readiness.py, рядом с
соответствующей проверкой.
"""
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.models import SalonModerationStatus
from app.services import booking_readiness as br


def _args(**over):
    """Полностью готовый к записи салон — от него отклоняемся по одному условию."""
    base = dict(
        solo=True,
        is_active=True,
        is_deleted=False,
        is_hidden=False,
        moderation_status=SalonModerationStatus.APPROVED,
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        has_tariff=True,
        guest_booking_enabled=True,
        active_masters=1,
        bookable_masters=1,
        salon_hours_set=True,
        open_weekdays=5,
    )
    base.update(over)
    return base


def _keys(readiness):
    return [i.key for i in readiness.issues]


# ─────────────────────────── «всё готово» ───────────────────────────

def test_ready_salon_has_no_issues():
    r = br.evaluate(**_args())
    assert r.issues == ()
    assert r.can_book is True
    assert r.link_works is True


# ──────────────────── по одному тесту на условие ────────────────────

def test_deleted_salon_blocks_and_hides_everything_else():
    """Удалённый салон не существует публично: остальные строки — шум."""
    r = br.evaluate(**_args(is_active=False, bookable_masters=0, salon_hours_set=False))
    assert _keys(r) == ["salon_deleted"]
    assert r.can_book is False


def test_soft_deleted_flag_blocks_too():
    """is_deleted — вторая, независимая от is_active причина (см. _salon_bookable)."""
    r = br.evaluate(**_args(is_deleted=True))
    assert _keys(r) == ["salon_deleted"]


def test_moderation_pending_blocks():
    r = br.evaluate(**_args(moderation_status=SalonModerationStatus.PENDING))
    assert "moderation_pending" in _keys(r)
    assert r.can_book is False


def test_moderation_rejected_blocks():
    r = br.evaluate(**_args(moderation_status=SalonModerationStatus.REJECTED))
    assert "moderation_rejected" in _keys(r)
    assert r.can_book is False


def test_unpaid_tariff_blocks():
    r = br.evaluate(**_args(has_tariff=False))
    assert "no_tariff" in _keys(r)
    assert r.can_book is False


def test_unpublished_salon_blocks():
    r = br.evaluate(**_args(published_at=None))
    assert "not_published" in _keys(r)
    assert r.can_book is False


def test_no_master_blocks():
    """Салон на проде остался без мастера вообще — записаться не к кому."""
    r = br.evaluate(**_args(active_masters=0, bookable_masters=0))
    assert "no_master" in _keys(r)
    assert r.can_book is False


def test_no_services_blocks_when_master_exists():
    """Мастер есть, но услуг нет: гостевая запись выкидывает такого мастера."""
    r = br.evaluate(**_args(active_masters=1, bookable_masters=0))
    keys = _keys(r)
    assert "no_services" in keys
    assert "no_master" not in keys
    assert r.can_book is False


def test_no_salon_hours_blocks():
    r = br.evaluate(**_args(salon_hours_set=False))
    assert "no_salon_hours" in _keys(r)
    assert r.can_book is False


def test_no_workdays_blocks_when_hours_are_set():
    """Часы салона заданы, но график мастера не пересекается с ними ни в один день."""
    r = br.evaluate(**_args(open_weekdays=0))
    keys = _keys(r)
    assert "no_workdays" in keys
    assert "no_salon_hours" not in keys
    assert r.can_book is False


def test_no_workdays_not_reported_without_bookable_master():
    """Без мастера с услугами нулевой график — следствие, а не отдельная причина."""
    r = br.evaluate(**_args(active_masters=0, bookable_masters=0, open_weekdays=0))
    assert "no_workdays" not in _keys(r)


# ───────── предупреждения: записаться можно, но не как ожидается ─────────

def test_guest_booking_off_kills_the_link_but_not_booking():
    """Гостевую запись выключили: /book/{id} закрыт, но запись из каталога
    для клиентов с аккаунтом не проверяет этот флаг (см. _salon_bookable)."""
    r = br.evaluate(**_args(guest_booking_enabled=False))
    assert "guest_booking_off" in _keys(r)
    assert r.can_book is True
    assert r.link_works is False


def test_hidden_salon_keeps_the_link_but_leaves_the_catalog():
    """is_hidden закрывает запись из каталога, а гостевая страница его не смотрит."""
    r = br.evaluate(**_args(is_hidden=True))
    assert "hidden" in _keys(r)
    assert r.can_book is True
    assert r.link_works is True


def test_warnings_are_not_blocking():
    r = br.evaluate(**_args(is_hidden=True, guest_booking_enabled=False))
    assert r.blocking == ()
    assert len(r.warnings) == 2


# ─────────────────────── порядок и адресность строк ───────────────────────

def test_blocking_issues_come_before_warnings():
    r = br.evaluate(**_args(bookable_masters=0, active_masters=0, guest_booking_enabled=False))
    keys = _keys(r)
    assert keys.index("no_master") < keys.index("guest_booking_off")


def test_tariff_is_asked_before_publishing():
    """Публикация без тарифа невозможна — просить опубликовать раньше оплаты бессмысленно."""
    r = br.evaluate(**_args(has_tariff=False, published_at=None))
    keys = _keys(r)
    assert keys.index("no_tariff") < keys.index("not_published")


# Все сценарии, которые вместе дают каждую причину хотя бы раз. Список проверяется
# на полноту тестом ниже: новая причина без сценария уронит его, а не проскользнёт.
_ALL_SCENARIOS = (
    dict(is_active=False),
    dict(is_deleted=True),
    dict(moderation_status=SalonModerationStatus.PENDING),
    dict(moderation_status=SalonModerationStatus.REJECTED),
    dict(has_tariff=False),
    dict(published_at=None),
    dict(active_masters=0, bookable_masters=0),
    dict(bookable_masters=0),
    dict(salon_hours_set=False),
    dict(open_weekdays=0),
    dict(is_hidden=True),
    dict(guest_booking_enabled=False),
)


def _all_issues():
    for over in _ALL_SCENARIOS:
        for issue in br.evaluate(**_args(**over)).issues:
            yield over, issue


def test_scenarios_cover_every_issue_the_service_can_produce():
    """Страховка для теста ниже: если появится причина, которую ни один
    сценарий не вызывает, инвариант «действие ⇔ адрес» её бы не проверил."""
    produced = {issue.key for _over, issue in _all_issues()}
    assert produced == br.ISSUE_KEYS


def test_every_issue_points_somewhere_or_explicitly_nowhere():
    """У строки либо есть раздел для действия, либо действие отсутствует вовсе.
    Подпись действия без адреса — кнопка в никуда."""
    for over, issue in _all_issues():
        assert bool(issue.action) == bool(issue.target), (over, issue.key)
        assert issue.text, (over, issue.key)


def test_solo_and_team_name_the_master_problem_differently():
    """В соло «мастер» — это сам человек, найма там нет."""
    solo = br.evaluate(**_args(solo=True, active_masters=0, bookable_masters=0))
    team = br.evaluate(**_args(solo=False, active_masters=0, bookable_masters=0))
    solo_row = next(i for i in solo.issues if i.key == "no_master")
    team_row = next(i for i in team.issues if i.key == "no_master")
    assert solo_row.text != team_row.text
    assert "вашей карточки" in solo_row.text


# ───────────── collect(): те же значения, что видит сама запись ─────────────
# evaluate() выше проверен на значениях; здесь проверяется, что значения
# собираются из базы правильно. Это отдельный риск: условие может быть описано
# верно, а данные для него собраны не те (например, «модельная» услуга
# посчитана за обычную — и человеку скажут, что записаться можно).

import json  # noqa: E402
from datetime import time, timezone as _tz  # noqa: E402

from app.core.security import get_password_hash  # noqa: E402
from app.models.models import (  # noqa: E402
    Master, OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember, SalonPanelMode,
    SalonRole, Schedule, Service, User, UserRole,
)

_WEEK_OPEN = json.dumps({d: "10:00-20:00" for d in
                         ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


async def _salon_in_db(db_session, phone, *, unpublish=False, **salon_over):
    """unpublish — отдельным UPDATE после вставки: conftest проставляет
    published_at любому салону, созданному сразу одобренным (грандфатеринг
    боевого бэкфилла), и через конструктор NULL туда не положить."""
    async with db_session() as db:
        owner = User(phone=phone, full_name="Хозяйка",
                     hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        fields = dict(
            name="Готовность", address="ул. Тестовая, 3", phone="+70000000902",
            latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=SalonPanelMode.SOLO,
            working_hours=_WEEK_OPEN, guest_booking_enabled=True,
            access_until=datetime.now(_tz.utc) + timedelta(days=30),
        )
        fields.update(salon_over)
        salon = Salon(**fields)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(
            salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER, is_creator=True,
            permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        if unpublish:
            salon.published_at = None
        await db.commit()
        return owner.id, salon.id


async def _add_master(db_session, owner_id, salon_id, *, service=None, schedule=None, active=True):
    """service: dict полей Service (или None — мастер без услуг).
    schedule: список (day_of_week, start, end) — или None, тогда график
    индивидуальный не задан и мастер работает по часам салона."""
    async with db_session() as db:
        master = Master(user_id=owner_id, salon_id=salon_id, specialization="Маникюр",
                        experience_years=0, rating=0.0, is_active=active)
        db.add(master)
        await db.commit()
        await db.refresh(master)
        if service is not None:
            fields = dict(master_id=master.id, name="Маникюр", price=1000,
                          duration_minutes=60, is_active=True, is_model_practice=False)
            fields.update(service)
            db.add(Service(**fields))
        for day, start, end in (schedule or []):
            db.add(Schedule(master_id=master.id, day_of_week=day, start_time=start, end_time=end))
        await db.commit()
        return master.id


async def _collect(db_session, salon_id, solo=True):
    async with db_session() as db:
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        masters = (await db.execute(select(Master).where(Master.salon_id == salon_id))).scalars().all()
        return await br.collect(db, salon, masters, solo=solo)


async def test_collect_sees_a_fully_ready_salon(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553001", published_at=datetime.now(_tz.utc),
    )
    await _add_master(db_session, owner_id, salon_id, service={})
    r = await _collect(db_session, salon_id)
    assert r.issues == (), _keys(r)
    assert r.link_works is True


async def test_collect_reports_the_salon_without_a_master(client, db_session):
    """Случай с прода: салон подключился и остался без мастера вообще."""
    _, salon_id = await _salon_in_db(
        db_session, "+79995553002", published_at=datetime.now(_tz.utc),
    )
    assert "no_master" in _keys(await _collect(db_session, salon_id))


async def test_collect_does_not_count_a_model_practice_service_as_bookable(client, db_session):
    """«Модельная» услуга обычным клиентам не показывается (is_model_practice
    отфильтрована и на странице записи, и в create_guest_booking)."""
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553003", published_at=datetime.now(_tz.utc),
    )
    await _add_master(db_session, owner_id, salon_id, service={"is_model_practice": True})
    assert "no_services" in _keys(await _collect(db_session, salon_id))


async def test_collect_does_not_count_a_deleted_service_as_bookable(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553004", published_at=datetime.now(_tz.utc),
    )
    await _add_master(db_session, owner_id, salon_id, service={"is_active": False})
    assert "no_services" in _keys(await _collect(db_session, salon_id))


async def test_collect_ignores_an_inactive_master(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553005", published_at=datetime.now(_tz.utc),
    )
    await _add_master(db_session, owner_id, salon_id, service={}, active=False)
    assert "no_master" in _keys(await _collect(db_session, salon_id))


async def test_collect_reports_empty_salon_hours(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553006", published_at=datetime.now(_tz.utc), working_hours=None,
    )
    await _add_master(db_session, owner_id, salon_id, service={})
    assert "no_salon_hours" in _keys(await _collect(db_session, salon_id))


async def test_collect_reports_a_week_of_days_off_as_no_hours(client, db_session):
    """Строка заполнена, но все дни выходные — окон не будет ни в один день,
    и get_salon_work_hours вернёт None на каждый из них."""
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553007", published_at=datetime.now(_tz.utc),
        working_hours=json.dumps({d: "выходной" for d in
                                  ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}),
    )
    await _add_master(db_session, owner_id, salon_id, service={})
    assert "no_salon_hours" in _keys(await _collect(db_session, salon_id))


async def test_collect_reports_a_master_schedule_outside_salon_hours(client, db_session):
    """График мастера есть, но не пересекается с часами салона ни в один день:
    compute_effective_intervals вернёт пусто всегда — окон не бывает."""
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553008", published_at=datetime.now(_tz.utc),
        working_hours=json.dumps({"mon": "10:00-20:00", **{d: "выходной" for d in
                                  ("tue", "wed", "thu", "fri", "sat", "sun")}}),
    )
    # Мастер работает только по вторникам, а салон открыт только в понедельник.
    await _add_master(db_session, owner_id, salon_id, service={},
                      schedule=[(1, time(10, 0), time(18, 0))])
    keys = _keys(await _collect(db_session, salon_id))
    assert "no_workdays" in keys
    assert "no_salon_hours" not in keys


async def test_collect_accepts_a_master_schedule_that_overlaps_one_day(client, db_session):
    """Хватает одного рабочего дня: записаться можно, пусть и раз в неделю."""
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553009", published_at=datetime.now(_tz.utc),
        working_hours=json.dumps({"mon": "10:00-20:00", **{d: "выходной" for d in
                                  ("tue", "wed", "thu", "fri", "sat", "sun")}}),
    )
    await _add_master(db_session, owner_id, salon_id, service={},
                      schedule=[(0, time(12, 0), time(16, 0))])
    assert _keys(await _collect(db_session, salon_id)) == []


async def test_collect_reports_an_expired_subscription(client, db_session):
    _, salon_id = await _salon_in_db(
        db_session, "+79995553010", published_at=datetime.now(_tz.utc),
        access_until=datetime.now(_tz.utc) - timedelta(days=1),
    )
    assert "no_tariff" in _keys(await _collect(db_session, salon_id))


async def test_collect_reports_guest_booking_switched_off(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995553011", published_at=datetime.now(_tz.utc),
        guest_booking_enabled=False,
    )
    await _add_master(db_session, owner_id, salon_id, service={})
    r = await _collect(db_session, salon_id)
    assert _keys(r) == ["guest_booking_off"]
    assert r.can_book is True and r.link_works is False


# ────────── сверка с живой страницей записи ──────────
# Самая ценная проверка: не «условие описано так, как я прочитал код», а
# «вердикт блока совпадает с тем, что реально отдаёт /book/{salon_id}».

async def test_verdict_matches_the_real_booking_page_when_ready(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995554001", published_at=datetime.now(_tz.utc),
    )
    await _add_master(db_session, owner_id, salon_id, service={})

    assert (await _collect(db_session, salon_id)).link_works is True
    page = await client.get(f"/book/{salon_id}")
    assert page.status_code == 200
    assert "Запись недоступна" not in page.text
    assert "Пока нельзя записаться" not in page.text


@pytest.mark.parametrize("over, expect_issue", [
    ({"published_at": None}, "not_published"),
    ({"guest_booking_enabled": False}, "guest_booking_off"),
    ({"moderation_status": SalonModerationStatus.PENDING}, "moderation_pending"),
])
async def test_closed_booking_page_always_has_a_reason_in_the_block(
    client, db_session, over, expect_issue,
):
    """Если /book/{id} закрыт, блок обязан назвать причину. Пустой список при
    закрытой странице — это и есть та ложь, которой тут быть нельзя."""
    phone = f"+7999555402{list(('not_published', 'guest_booking_off', 'moderation_pending')).index(expect_issue)}"
    base = {"published_at": datetime.now(_tz.utc)}
    base.update(over)
    unpublish = base.pop("published_at") is None
    owner_id, salon_id = await _salon_in_db(db_session, phone, unpublish=unpublish, **base)
    await _add_master(db_session, owner_id, salon_id, service={})

    page = await client.get(f"/book/{salon_id}")
    assert "Запись недоступна" in page.text, "страница должна быть закрыта"

    r = await _collect(db_session, salon_id)
    assert expect_issue in _keys(r)
    assert r.link_works is False


async def test_master_without_services_closes_the_page_and_the_block_says_why(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995554030", published_at=datetime.now(_tz.utc),
    )
    await _add_master(db_session, owner_id, salon_id, service=None)

    page = await client.get(f"/book/{salon_id}")
    assert "Пока нельзя записаться" in page.text
    assert "no_services" in _keys(await _collect(db_session, salon_id))


async def test_collect_reports_an_unpublished_salon(client, db_session):
    owner_id, salon_id = await _salon_in_db(
        db_session, "+79995554040", unpublish=True,
    )
    await _add_master(db_session, owner_id, salon_id, service={})
    r = await _collect(db_session, salon_id)
    assert "not_published" in _keys(r)
    assert r.can_book is False
