"""Уход из сервиса: удаление аккаунта и удаление своей карточки мастера.

Решение 0016, п. 1. До него удаление аккаунта ставило ``users.is_active=False``
и больше ничего: карточка мастера и салон оставались в каталоге, к человеку
можно было записаться, и клиент пришёл бы к тому, кого нет.

Правила, принятые здесь (они же описаны в решении):

- **Свой салон** — где человек единственный живой владелец — закрывается так
  же, как при удалении салона владельцем: ``is_active=False``, ``is_deleted=True``.
  Админ возвращает его кнопкой «Восстановить» во вкладке «Салоны».
- **Салон с совладельцем** остаётся работать: уходит только карточка этого
  человека и его записи. Если ушёл создатель, автопродление тарифа гасится —
  карта, с которой шли списания, его, а не совладельца, — и совладельцам
  уходит сообщение, что тариф дальше продлевают они.
- **Оплаченный тариф** автоматически не возвращается: оплаченный период
  остаётся на салоне (``access_until`` не трогаем) и продолжится, если админ
  салон восстановит. Автопродление выключается всегда, чтобы с карты ушедшего
  человека больше ничего не списалось. Возврат — по обращению в поддержку,
  у админа для этого уже есть механизм.
- **Записи**: отменяются все ожидающие и подтверждённые, которые ещё не
  начались по часам салона, — в том числе сегодняшние. Человек, удаливший
  аккаунт, к ним не придёт, а клиент должен узнать об этом до выхода из дома.
  Визит, который уже идёт, не трогаем. Сколько записей отменится (и сколько из
  них сегодня), человек видит до подтверждения.

Всё мягкое: ни одной строки не удаляется. Аккаунт, карточка и салон
возвращаются флагами, отменённые записи остаются в истории.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    AdminAudit, Booking, BookingStatus, Master, Salon, SalonMember, SalonRole, User,
)
from app.utils.timezone import get_salon_time

logger = logging.getLogger(__name__)

#: Записи, которые ещё могут состояться. Завершённые и неявки — история.
UPCOMING_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


@dataclass
class Departure:
    """Что случится (или случилось) при уходе. Одна структура на предпросмотр
    в профиле и на само действие — чтобы обещанное на экране совпадало с
    сделанным."""
    master: Master | None = None
    closed_salons: list[Salon] = field(default_factory=list)
    shared_salons: list[Salon] = field(default_factory=list)
    bookings: list[Booking] = field(default_factory=list)
    today: int = 0

    @property
    def touches_anything(self) -> bool:
        return bool(self.master or self.closed_salons or self.shared_salons or self.bookings)


async def _upcoming_bookings(db: AsyncSession, master_ids: list[int]) -> tuple[list[Booking], int]:
    """Не начавшиеся записи к этим мастерам и сколько из них сегодня.

    ``start_time`` хранится наивным временем салона, поэтому «ещё не началась»
    решаем по часам КАЖДОГО салона, а не по серверным. В SQL отсекаем
    заведомо прошлое с запасом в сутки (больше любой разницы поясов), точное
    сравнение — ниже.
    """
    if not master_ids:
        return [], 0
    floor = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    rows = (await db.execute(
        select(Booking, Salon.timezone)
        .join(Master, Master.id == Booking.master_id)
        .join(Salon, Salon.id == Master.salon_id)
        .where(
            Booking.master_id.in_(master_ids),
            Booking.status.in_(UPCOMING_STATUSES),
            Booking.start_time > floor,
        )
        .order_by(Booking.start_time)
    )).all()
    upcoming, today = [], 0
    for booking, tz in rows:
        now_local = get_salon_time(tz).replace(tzinfo=None)
        if booking.start_time <= now_local:
            continue
        upcoming.append(booking)
        if booking.start_time.date() == now_local.date():
            today += 1
    return upcoming, today


async def _owned_salons(db: AsyncSession, user_id: int) -> tuple[list[Salon], list[Salon]]:
    """Салоны, где человек владелец: (только его, с другим живым владельцем)."""
    salons = (await db.execute(
        select(Salon)
        .join(SalonMember, SalonMember.salon_id == Salon.id)
        .where(
            SalonMember.user_id == user_id,
            SalonMember.role == SalonRole.OWNER,
            SalonMember.is_active == True,  # noqa: E712
            Salon.is_deleted == False,  # noqa: E712
        )
        .order_by(Salon.id)
    )).scalars().all()
    # Салоны времён до SalonMember: владельца знает только creator_id.
    legacy = (await db.execute(
        select(Salon).where(
            Salon.creator_id == user_id,
            Salon.is_deleted == False,  # noqa: E712
            ~exists().where(SalonMember.salon_id == Salon.id,
                            SalonMember.role == SalonRole.OWNER,
                            SalonMember.is_active == True),  # noqa: E712
        ).order_by(Salon.id)
    )).scalars().all()
    closed, shared = list(legacy), []
    for salon in salons:
        other_owner = (await db.execute(
            select(SalonMember.id)
            .join(User, User.id == SalonMember.user_id)
            .where(
                SalonMember.salon_id == salon.id,
                SalonMember.user_id != user_id,
                SalonMember.role == SalonRole.OWNER,
                SalonMember.is_active == True,  # noqa: E712
                User.is_active == True,  # noqa: E712
            ).limit(1)
        )).scalar_one_or_none()
        (shared if other_owner else closed).append(salon)
    return closed, shared


async def plan_account_departure(db: AsyncSession, user: User) -> Departure:
    """Что уйдёт вместе с аккаунтом. Ничего не меняет."""
    master = (await db.execute(
        select(Master).where(Master.user_id == user.id)
    )).scalar_one_or_none()
    closed, shared = await _owned_salons(db, user.id)

    master_ids: set[int] = set()
    # Карточку берём и отключённую: записи к ней могли остаться с тех пор,
    # как владелец салона её выключил, а человек всё равно уходит.
    if master is not None:
        master_ids.add(master.id)
    if closed:
        # Салон закрывается целиком — к его мастерам тоже больше не записаться,
        # и их клиентов нужно предупредить так же.
        master_ids.update((await db.execute(
            select(Master.id).where(Master.salon_id.in_([s.id for s in closed]))
        )).scalars().all())
    bookings, today = await _upcoming_bookings(db, sorted(master_ids))
    return Departure(
        master=master if master is not None and master.is_active else None,
        closed_salons=closed, shared_salons=shared, bookings=bookings, today=today,
    )


def _cancel(bookings: list[Booking]) -> None:
    for booking in bookings:
        booking.status = BookingStatus.CANCELLED


async def _notify_cancelled(db: AsyncSession, bookings: list[Booking], *, leaver_id: int,
                            base_url: str) -> None:
    """Уведомления после коммита: сбой доставки не должен откатывать уход."""
    from app.services.notifications import notify_booking_cancelled_master_left

    for booking in bookings:
        try:
            await notify_booking_cancelled_master_left(
                db, booking, leaver_id=leaver_id, base_url=base_url,
            )
        except Exception:
            logger.exception("уход %s: клиент записи %s не уведомлён", leaver_id, booking.id)


def _stop_auto_renew(target) -> bool:
    """Выключить автопродление. True — было включено.

    Как кнопка «Отключить автопродление»: у Т-Кассы нет подписки на её
    стороне, списание запускаем мы сами, значит достаточно не запускать.
    """
    was_on = bool(target.auto_renew)
    target.auto_renew = False
    target.recurring_token = None
    return was_on


async def depart_account(db: AsyncSession, user: User, *, base_url: str) -> Departure:
    """Удаление аккаунта со всей цепочкой. Коммитит сама."""
    plan = await plan_account_departure(db, user)
    user_id, phone = user.id, user.phone

    user.is_active = False
    _stop_auto_renew(user)  # тариф «модели» платит сам человек
    if plan.master is not None:
        plan.master.is_active = False

    for salon in plan.closed_salons:
        salon.is_active = False
        salon.is_deleted = True
        _stop_auto_renew(salon)
        db.add(AdminAudit(
            actor_id=user_id, action="account_deleted_salon_closed",
            target_type="salon", target_id=salon.id, salon_id=salon.id,
            detail=f"Владелец удалил аккаунт — салон «{salon.name}» закрыт "
                   "(восстанавливается кнопкой «Восстановить»)",
        ))

    renew_stopped: list[Salon] = []
    for salon in plan.shared_salons:
        if salon.creator_id == user_id and _stop_auto_renew(salon):
            renew_stopped.append(salon)
        db.add(AdminAudit(
            actor_id=user_id, action="account_deleted_owner_left",
            target_type="salon", target_id=salon.id, salon_id=salon.id,
            detail=f"Совладелец {phone} удалил аккаунт — салон работает дальше"
                   + ("; автопродление выключено" if salon in renew_stopped else ""),
        ))

    _cancel(plan.bookings)

    parts = []
    if plan.master is not None:
        parts.append(f"карточка мастера #{plan.master.id} снята")
    if plan.closed_salons:
        parts.append("закрыты салоны: " + ", ".join(f"#{s.id}" for s in plan.closed_salons))
    parts.append(f"отменено записей: {len(plan.bookings)}")
    db.add(AdminAudit(
        actor_id=user_id, action="delete_own_account",
        target_type="user", target_id=user_id,
        detail=f"{phone} удалил аккаунт; " + "; ".join(parts),
    ))
    await db.commit()

    await _notify_cancelled(db, plan.bookings, leaver_id=user_id, base_url=base_url)
    for salon in renew_stopped:
        await _tell_co_owners(db, salon, leaver_id=user_id)
    return plan


async def _tell_co_owners(db: AsyncSession, salon: Salon, *, leaver_id: int) -> None:
    """Совладельцам: создатель ушёл, автопродление выключено."""
    from app.services.notifications import deliver
    from app.services.vk_community import Audience

    owners = (await db.execute(
        select(User)
        .join(SalonMember, SalonMember.user_id == User.id)
        .where(
            SalonMember.salon_id == salon.id,
            SalonMember.user_id != leaver_id,
            SalonMember.role == SalonRole.OWNER,
            SalonMember.is_active == True,  # noqa: E712
            User.is_active == True,  # noqa: E712
        )
    )).scalars().all()
    for owner in owners:
        try:
            await deliver(
                owner,
                f"💳 «{salon.name}»: создатель салона удалил аккаунт в Руми. Салон "
                "работает дальше, но автопродление тарифа выключено — оно шло с его "
                "карты. Чтобы салон не пропал из каталога, когда оплаченный период "
                "закончится, оплатите тариф в разделе «Тариф» панели.",
                subject="Тариф — Руми", audience=Audience.BUSINESS,
            )
        except Exception:
            logger.exception("уход %s: совладелец салона %s не уведомлён", leaver_id, salon.id)


async def plan_card_removal(db: AsyncSession, master: Master) -> Departure:
    """Что случится при удалении своей карточки мастера. Ничего не меняет."""
    bookings, today = await _upcoming_bookings(db, [master.id])
    return Departure(master=master, bookings=bookings, today=today)


async def remove_own_master_card(db: AsyncSession, master: Master, *, actor_id: int,
                                 base_url: str) -> Departure:
    """«Удалить карточку мастера»: человек перестаёт быть мастером, аккаунт
    остаётся. Карточка мягко гаснет; завести её заново — та же кнопка
    «Создать мою карточку мастера» (ensure_owner_master включает прежнюю:
    карточка у человека одна, masters.user_id уникален)."""
    plan = await plan_card_removal(db, master)
    master.is_active = False
    _cancel(plan.bookings)
    db.add(AdminAudit(
        actor_id=actor_id, action="delete_own_master_card",
        target_type="master", target_id=master.id, salon_id=master.salon_id,
        detail=f"Удалил свою карточку мастера; отменено записей: {len(plan.bookings)}",
    ))
    await db.commit()
    await _notify_cancelled(db, plan.bookings, leaver_id=actor_id, base_url=base_url)
    return plan
