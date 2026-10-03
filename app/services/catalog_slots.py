"""Что показывать в карточке каталога: услуги с ценой, акции, категории и
ближайшие свободные окна — ОДНИМ запросом на всю страницу.

Зачем модуль. Карточка без фотографии должна выглядеть намеренной, а фото у нас
почти нет (на 03.10.2026: обложка у двух салонов из девяти), поэтому карточку
несут услуги, цены и свободное время (решение 0011, п. 11). Но свободное время
считается на связку «мастер + услуга + дата» (``bookings.get_available_slots``),
и наивная реализация сделала бы по запросу на каждую карточку — каталог самый
посещаемый публичный экран, и его уже однажды разгоняли с девяти секунд.

Поэтому здесь ровно один SELECT: все масивы (мастера, их услуги, графики,
брони, закрытые дни, акции, категории) собираются в JSON на стороне Postgres, а
сами окна считаются в Python ТЕМИ ЖЕ чистыми функциями, что и в эндпоинте
записи (``schedule_utils``). Второй реализации правил доступности быть не
должно: разошедшись, она покажет в каталоге время, которого нет.

Ограничение честности: окно привязано к КОНКРЕТНОЙ услуге (самой дешёвой из
карточки) и к её мастеру — его имя и название услуги уезжают в ссылку. Окна
«вообще» означали бы обещание, которое нельзя проверить: у другой услуги другая
длительность и другая сетка.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import BookingStatus
from app.services.schedule_utils import (
    MAX_BOOKING_DAYS_AHEAD,
    compute_effective_intervals,
    get_salon_work_hours,
    merge_intervals,
)
from app.utils.timezone import get_salon_time

#: На сколько дней вперёд ищем ближайшие окна. Семь — это «на этой неделе»:
#: дальше окно в карточке каталога уже не повод зайти, а два месяца горизонта
#: записи превратили бы один запрос в выгрузку всех броней сервиса.
SLOT_DAYS = 7

#: Сколько окон показываем в карточке. Больше трёх — это уже расписание, а не
#: приглашение; на 375px четвёртая плашка уезжает во вторую строку.
SLOTS_PER_CARD = 3

#: Сколько услуг показываем в карточке.
SERVICES_PER_CARD = 3

_DAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
               "июля", "августа", "сентября", "октября", "ноября", "декабря"]


@dataclass
class CardService:
    id: int
    name: str
    price: int
    price_max: Optional[int]
    duration: int
    master_id: int


@dataclass
class CardSlot:
    """Свободное окно: машинное значение для ссылки и подпись для глаза."""
    start: datetime
    label: str

    @property
    def value(self) -> str:
        return self.start.strftime("%Y-%m-%dT%H:%M")

    @property
    def full(self) -> str:
        """Полная дата для подсказки: «сегодня» считается по часам САЛОНА, а
        посетитель может смотреть из другого пояса."""
        return (f"{self.start.day} {_MONTHS_GEN[self.start.month - 1]}, "
                f"{self.start:%H:%M} по времени салона")


@dataclass
class CardExtras:
    services: list[CardService] = field(default_factory=list)
    #: Полное число услуг — чтобы честно сказать «и ещё 7», а не обрезать молча.
    services_total: int = 0
    slots: list[CardSlot] = field(default_factory=list)
    #: Услуга, к которой относятся окна (без неё окна показывать нельзя).
    slot_service: Optional[CardService] = None
    promos: list[tuple[str, str]] = field(default_factory=list)


# Один SELECT на всю страницу. Массивы собираются в JSON на стороне Postgres:
# это дороже по CPU базы, чем шесть отдельных выборок, но дешевле по кругам
# до неё, а именно круги и съедали время в прошлый раз.
_SQL = """
SELECT s.id AS salon_id,
       s.working_hours,
       s.timezone,
       (SELECT json_agg(json_build_object('tag', pr.tag, 'title', pr.title) ORDER BY pr.id)
          FROM promotions pr
         WHERE pr.salon_id = s.id AND pr.is_active = true) AS promos,
       (SELECT json_agg(json_build_object(
                   'id', m.id,
                   'brk', m.break_minutes,
                   'svc', (SELECT json_agg(json_build_object(
                                     'id', sv.id, 'n', sv.name, 'p', sv.price,
                                     'pm', sv.price_max, 'd', sv.duration_minutes)
                                   ORDER BY sv.price, sv.id)
                             FROM services sv
                            WHERE sv.master_id = m.id AND sv.is_active = true
                              AND sv.is_model_practice = false),
                   'sch', (SELECT json_agg(json_build_object(
                                     'd', sc.day_of_week,
                                     's', to_char(sc.start_time, 'HH24:MI'),
                                     'e', to_char(sc.end_time, 'HH24:MI')))
                             FROM schedule sc WHERE sc.master_id = m.id),
                   'bk', (SELECT json_agg(json_build_object(
                                     's', to_char(b.start_time, 'YYYY-MM-DD HH24:MI'),
                                     'e', to_char(b.end_time, 'YYYY-MM-DD HH24:MI')))
                            FROM bookings b
                           WHERE b.master_id = m.id
                             AND b.start_time >= :day_from
                             AND b.start_time < :day_to
                             AND b.status IN :live_statuses))
                 ORDER BY m.id)
          FROM masters m
         WHERE m.salon_id = s.id AND m.is_active = true) AS masters,
       (SELECT json_agg(json_build_object('d', to_char(cl.date, 'YYYY-MM-DD'),
                                          'm', cl.master_id))
          FROM schedule_closures cl
         WHERE cl.salon_id = s.id AND cl.date >= :date_from AND cl.date <= :date_to) AS closures
  FROM salons s
 WHERE s.id IN :ids
"""


def _parse_hm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def _day_intervals(rows, target: datetime) -> list[tuple[datetime, datetime]]:
    """Смены мастера на этот день недели как интервалы datetime.

    Делает то же, что ``schedule_utils.build_day_intervals``, но на словарях из
    JSON, а не на ORM-строках: ходить за объектами Schedule значило бы вернуть
    запрос на мастера, от которого мы здесь и уходим.
    """
    out = []
    for r in rows or []:
        if r.get("d") != target.weekday():
            continue
        try:
            sh, sm = _parse_hm(r["s"])
            eh, em = _parse_hm(r["e"])
        except (KeyError, ValueError, AttributeError):
            continue
        start = target.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = target.replace(hour=eh, minute=em, second=0, microsecond=0)
        if end > start:
            out.append((start, end))
    return merge_intervals(out)


def _busy(master: dict) -> list[tuple[datetime, datetime]]:
    out = []
    for b in master.get("bk") or []:
        try:
            out.append((
                datetime.strptime(b["s"], "%Y-%m-%d %H:%M"),
                datetime.strptime(b["e"], "%Y-%m-%d %H:%M"),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _label(start: datetime, today) -> str:
    """«сегодня 15:00» / «завтра 10:30» / «сб 12:00».

    День словом, а не числом: карточка каталога — это не календарь, и «3 окт»
    человек всё равно переводит в «это послезавтра».
    """
    delta = (start.date() - today).days
    if delta == 0:
        day = "сегодня"
    elif delta == 1:
        day = "завтра"
    else:
        day = _DAYS_SHORT[start.weekday()]
    return f"{day} {start:%H:%M}"


def nearest_slots(
    *,
    working_hours: Optional[str],
    tz: Optional[str],
    master: dict,
    service: CardService,
    closures: list[dict],
    limit: int = SLOTS_PER_CARD,
    days: int = SLOT_DAYS,
) -> list[CardSlot]:
    """Ближайшие свободные окна одного мастера под одну услугу.

    Правила доступности берутся из ``schedule_utils`` — те же, что в
    ``/api/v1/bookings/available``: часы салона, индивидуальный график мастера
    (а его отсутствие означает «работает по часам салона»), закрытые дни на
    салон или на мастера, занятые интервалы и шаг «длительность + перерыв».
    """
    step = service.duration + int(master.get("brk") or 0)
    if step <= 0:
        return []

    now = get_salon_time(tz).replace(tzinfo=None)
    today = now.date()
    busy = _busy(master)
    schedule_rows = master.get("sch") or []
    has_any_schedule = len(schedule_rows) > 0
    closed_all = {c["d"] for c in closures if c.get("m") is None}
    closed_mine = {c["d"] for c in closures if c.get("m") == master.get("id")}

    out: list[CardSlot] = []
    for offset in range(min(days, MAX_BOOKING_DAYS_AHEAD + 1)):
        day = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        key = day.strftime("%Y-%m-%d")
        if key in closed_all or key in closed_mine:
            continue
        salon_hours = get_salon_work_hours(working_hours, day)
        intervals = compute_effective_intervals(
            salon_hours, has_any_schedule, _day_intervals(schedule_rows, day)
        )
        for work_start, work_end in intervals:
            cursor = work_start
            while cursor + timedelta(minutes=step) <= work_end:
                slot_end = cursor + timedelta(minutes=step)
                if cursor >= now and not any(cursor < be and slot_end > bs for bs, be in busy):
                    out.append(CardSlot(cursor, _label(cursor, today)))
                    if len(out) >= limit:
                        return out
                cursor = slot_end
    return out


def _collect_services(masters: list[dict]) -> tuple[list[CardService], int]:
    """Услуги салона по возрастанию цены, без повторов по названию.

    Один и тот же «Маникюр» может быть у трёх мастеров с разной ценой — в
    карточке это читалось бы как три разные услуги. Оставляем самую дешёвую:
    цена в карточке — это «от».
    """
    by_name: dict[str, CardService] = {}
    for m in masters or []:
        for sv in m.get("svc") or []:
            try:
                item = CardService(
                    id=int(sv["id"]), name=sv["n"] or "", price=int(sv["p"]),
                    price_max=sv.get("pm"), duration=int(sv["d"]),
                    master_id=int(m["id"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            seen = by_name.get(item.name)
            if seen is None or item.price < seen.price:
                by_name[item.name] = item
    items = sorted(by_name.values(), key=lambda s: (s.price, s.id))
    return items, len(items)


async def load_card_extras(
    db: AsyncSession, salon_ids: list[int], *, with_slots: bool = True
) -> dict[int, CardExtras]:
    """Содержимое карточек для текущей страницы каталога. ОДИН запрос.

    ``with_slots=False`` оставляет услуги и акции, но не считает окна — этим
    переключателем тест измеряет цену слотов в запросах, не правя код.
    """
    if not salon_ids:
        return {}

    now = datetime.now()
    day_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Горизонт на день шире, чем SLOT_DAYS: салон может быть в поясе впереди
    # серверного, и его «сегодня» начинается раньше нашего.
    day_to = day_from + timedelta(days=SLOT_DAYS + 1)

    stmt = text(_SQL).bindparams(
        bindparam("ids", expanding=True),
        bindparam("live_statuses", expanding=True),
    )
    rows = (await db.execute(stmt, {
        "ids": salon_ids,
        "live_statuses": [BookingStatus.PENDING.name, BookingStatus.CONFIRMED.name],
        "day_from": day_from - timedelta(days=1),
        "day_to": day_to,
        "date_from": (day_from - timedelta(days=1)).date(),
        "date_to": day_to.date(),
    })).mappings().all()

    out: dict[int, CardExtras] = {}
    for row in rows:
        masters = row["masters"] or []
        services, total = _collect_services(masters)
        extras = CardExtras(
            services=services[:SERVICES_PER_CARD],
            services_total=total,
            promos=[(p.get("tag") or "", p.get("title") or "") for p in (row["promos"] or [])],
        )
        if with_slots and services:
            lead = services[0]
            master = next((m for m in masters if int(m["id"]) == lead.master_id), None)
            if master is not None:
                extras.slots = nearest_slots(
                    working_hours=row["working_hours"],
                    tz=row["timezone"],
                    master=master,
                    service=lead,
                    closures=row["closures"] or [],
                )
                if extras.slots:
                    extras.slot_service = lead
        out[row["salon_id"]] = extras
    return out
