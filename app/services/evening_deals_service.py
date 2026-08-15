"""«Вечерние окна со скидкой» — общая логика.

Вечернее окно = пустой слот салона на СЕГОДНЯ (в таймзоне салона), начинающийся
в диапазоне [evening_from, evening_to) участвующего салона, если сегодняшний
день недели входит в настройку и услуга проходит фильтр. Слоты нигде не хранятся
— считаются из реального расписания (рабочие интервалы мастера минус брони).

Модель настройки — SalonEveningDeal (1:1 к салону). Скидка применяется к брони на
сервере при записи (ре-валидация окна), клиенту не доверяем.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Salon, SalonEveningDeal, SalonModerationStatus, Master, Service, Booking, BookingStatus,
)
from app.services.schedule_utils import get_effective_work_intervals
from app.utils.timezone import get_salon_time

Interval = Tuple[datetime, datetime]

# Минимальная длина свободного куска, чтобы считать его вечерним окном.
MIN_WINDOW_MINUTES = 15


def salon_city(salon: Salon) -> str:
    """Город салона — первая часть адреса (у салона нет отдельного поля города,
    как и в карточке салона: address.split(',')[0])."""
    return (salon.address or "").split(",")[0].strip()


def _today_local(salon: Salon) -> datetime:
    """Начало сегодняшнего дня в таймзоне салона (наивное, как start_time)."""
    now = get_salon_time(salon.timezone).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def deal_active_today(deal: Optional[SalonEveningDeal], salon: Salon) -> bool:
    """Участие включено и сегодняшний день недели входит в настройку."""
    if deal is None or not deal.enabled or deal.discount_percent <= 0:
        return False
    weekday = _today_local(salon).weekday()  # 0=Пн … 6=Вс
    days = deal.weekdays or []
    return not days or weekday in days


async def get_deal(db: AsyncSession, salon_id: int) -> Optional[SalonEveningDeal]:
    return (await db.execute(
        select(SalonEveningDeal).where(SalonEveningDeal.salon_id == salon_id)
    )).scalar_one_or_none()


def deal_to_dict(deal: Optional[SalonEveningDeal]) -> dict:
    """Настройка → JSON-совместимый словарь (для API и рендера панели)."""
    if deal is None:
        return {"enabled": False, "discount_percent": 0, "evening_from": "17:00",
                "evening_to": "21:00", "weekdays": [], "service_ids": []}
    return {
        "enabled": deal.enabled,
        "discount_percent": deal.discount_percent,
        "evening_from": deal.evening_from.strftime("%H:%M"),
        "evening_to": deal.evening_to.strftime("%H:%M"),
        "weekdays": deal.weekdays or [],
        "service_ids": deal.service_ids or [],
    }


def _subtract(segments: List[Interval], busy: List[Interval]) -> List[Interval]:
    """Вырезать занятые интервалы из свободных сегментов."""
    for bs, be in busy:
        new: List[Interval] = []
        for cs, ce in segments:
            if be <= cs or bs >= ce:
                new.append((cs, ce))
                continue
            if bs > cs:
                new.append((cs, min(bs, ce)))
            if be < ce:
                new.append((max(be, cs), ce))
        segments = new
    return segments


async def free_evening_intervals(
    db: AsyncSession, salon: Salon, master_id: int, deal: SalonEveningDeal,
) -> List[Interval]:
    """Свободные вечерние интервалы мастера на сегодня (после текущего момента)."""
    today = _today_local(salon)
    intervals = await get_effective_work_intervals(db, salon, master_id, today)
    if not intervals:
        return []

    ev_from = datetime.combine(today.date(), deal.evening_from)
    ev_to = datetime.combine(today.date(), deal.evening_to)
    now_local = get_salon_time(salon.timezone).replace(tzinfo=None)

    day_end = today + timedelta(days=1)
    booked = (await db.execute(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.start_time >= today,
            Booking.start_time < day_end,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
    )).scalars().all()
    busy = [(b.start_time, b.end_time) for b in booked]

    free: List[Interval] = []
    for ws, we in intervals:
        s = max(ws, ev_from, now_local)  # не предлагаем уже прошедшее
        e = min(we, ev_to)
        if s >= e:
            continue
        free.extend(seg for seg in _subtract([(s, e)], busy) if seg[0] < seg[1])

    return [(s, e) for s, e in free if (e - s) >= timedelta(minutes=MIN_WINDOW_MINUTES)]


async def salon_has_window_today(db: AsyncSession, salon: Salon, deal: SalonEveningDeal) -> bool:
    """Есть ли у салона хоть одно свободное вечернее окно сегодня."""
    if not deal_active_today(deal, salon):
        return False
    masters = (await db.execute(
        select(Master).where(Master.salon_id == salon.id, Master.is_active == True)  # noqa: E712
    )).scalars().all()
    for m in masters:
        if await free_evening_intervals(db, salon, m.id, deal):
            return True
    return False


def _public_salon_filter():
    """Публичный салон (на этой ветке published_at нет): активен, одобрен, не скрыт."""
    return (
        (Salon.is_active == True)  # noqa: E712
        & (Salon.moderation_status == SalonModerationStatus.APPROVED)
        & (Salon.is_hidden == False)  # noqa: E712
    )


async def participating_salons(db: AsyncSession) -> List[Tuple[Salon, SalonEveningDeal]]:
    """Публичные салоны с включённой сегодня акцией (без проверки наличия окон)."""
    rows = (await db.execute(
        select(Salon, SalonEveningDeal)
        .join(SalonEveningDeal, SalonEveningDeal.salon_id == Salon.id)
        .where(_public_salon_filter(), SalonEveningDeal.enabled == True)  # noqa: E712
    )).all()
    return [(s, d) for s, d in rows if deal_active_today(d, s)]


async def any_windows_today(db: AsyncSession) -> bool:
    """Есть ли хоть где-то вечернее окно сегодня — гейт ежедневной рассылки."""
    for salon, deal in await participating_salons(db):
        if await salon_has_window_today(db, salon, deal):
            return True
    return False


def _service_allowed(deal: SalonEveningDeal, service_id: int) -> bool:
    ids = deal.service_ids or []
    return not ids or service_id in ids


def discounted_price(base_price: int, discount_percent: int) -> int:
    return max(0, round(base_price * (100 - discount_percent) / 100))


async def evening_deal_discount(
    db: AsyncSession, salon: Salon, start_time: datetime, service_id: int,
) -> int:
    """Ре-валидация окна при брони: возвращает %скидки (0 — не вечернее окно).

    start_time — салонно-локальный наив (как хранится). Проверяем: акция
    включена и активна сегодня, слот на сегодня, попадает в вечерний диапазон,
    услуга проходит фильтр. Не проверяем занятость — это делает бронь отдельно.
    """
    deal = await get_deal(db, salon.id)
    if not deal_active_today(deal, salon):
        return 0
    today = _today_local(salon)
    if start_time.date() != today.date():
        return 0
    if not (deal.evening_from <= start_time.time() < deal.evening_to):
        return 0
    if not _service_allowed(deal, service_id):
        return 0
    return deal.discount_percent


async def build_feed(db: AsyncSession, city: Optional[str] = None) -> dict:
    """Данные для страницы /evening-deals: города + карточки салон→мастер→услуги
    со скидкой, у которых есть свободные вечерние окна сегодня."""
    salons_deals = await participating_salons(db)

    # Все города среди участников (для селектора) — считаем до фильтра.
    cities = sorted({salon_city(s) for s, _ in salons_deals if salon_city(s)})

    cards = []
    for salon, deal in salons_deals:
        if city and salon_city(salon).lower() != city.strip().lower():
            continue
        masters = (await db.execute(
            select(Master).where(Master.salon_id == salon.id, Master.is_active == True)  # noqa: E712
        )).scalars().all()
        master_cards = []
        for m in masters:
            free = await free_evening_intervals(db, salon, m.id, deal)
            if not free:
                continue
            services = (await db.execute(
                select(Service).where(
                    Service.master_id == m.id, Service.is_active == True,  # noqa: E712
                    Service.is_model_practice == False,  # noqa: E712
                )
            )).scalars().all()
            svc_cards = []
            for s in services:
                if not _service_allowed(deal, s.id):
                    continue
                svc_cards.append({
                    "id": s.id, "name": s.name,
                    "old_price": s.price,
                    "new_price": discounted_price(s.price, deal.discount_percent),
                })
            if not svc_cards:
                continue
            from app.models.models import User
            mu = (await db.execute(select(User).where(User.id == m.user_id))).scalar_one_or_none()
            master_cards.append({
                "master_id": m.id,
                "name": (mu.full_name if mu and mu.full_name else "Мастер"),
                "specialization": m.specialization,
                "windows": [f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}" for s, e in free],
                "services": svc_cards,
            })
        if master_cards:
            cards.append({
                "salon_id": salon.id, "salon_name": salon.name,
                "address": salon.address, "city": salon_city(salon),
                "discount_percent": deal.discount_percent,
                "masters": master_cards,
            })

    return {"cities": cities, "selected_city": city, "cards": cards,
            "discount_any": any(c["discount_percent"] for c in cards)}
