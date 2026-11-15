"""Действия из ботов: свои записи, подтверждение, перенос, отмена, отзыв.

Логика одна на Telegram, MAX и ВК — различается только рисование кнопок.
Держим её здесь, чтобы правила («какие записи показывать», «можно ли
отменить», «какие окна предложить») не разъехались между тремя ботами.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)
from app.services.price import format_service_price

# Сколько ближайших записей показываем в боте: список должен помещаться в
# одно сообщение и оставаться обозримым.
UPCOMING_LIMIT = 5

# Через сколько после визита просим отзыв. Человек успел уйти, впечатление
# ещё свежее.
REVIEW_DELAY = timedelta(hours=2)

#: Сколько свободных окон показываем при переносе из бота и на сколько дней
#: вперёд за ними ходим. Шесть выбрал владелец (решение 0020, п. 5): больше
#: не читается с телефона, а по две кнопки в ряд они вместе со ссылкой ещё
#: помещаются в шесть рядов — предел клавиатуры ВК.
RESCHEDULE_SLOTS = 6
RESCHEDULE_DAYS = 14

#: Команды кнопок под сообщением бота. Префиксы те же по смыслу, что уже
#: живут в трёх ботах (cnl:, ntf:, rev:, sup:), и их список в vk_bot
#: (_CLIENT_COMMANDS) нужно пополнять вместе с этим.
CMD_CONFIRM = "cfm:"      # cfm:ID          — «Буду»
CMD_RESCHEDULE = "rsc:"   # rsc:ID          — показать окна
                          # rsc:ID:ГГГГ-ММ-ДДTЧЧ:ММ — перенести на это окно
CMD_CANCEL = "cnl:"       # cnl:ID          — «Не смогу»


@dataclass(frozen=True)
class BotButton:
    """Кнопка под сообщением бота: подпись и что она делает.

    Описание одно на все каналы, рисует каждый своё: у Telegram
    reply_markup, у ВК inline_keyboard, у MAX InlineKeyboardBuilder, а у
    почты кнопок нет вовсе. Без общего описания один и тот же набор кнопок
    пришлось бы собирать в четырёх местах — и он бы разъехался, как
    когда-то разъехались тексты (см. bot_texts).
    """
    label: str
    command: str = ""   # callback-команда
    url: str = ""       # ссылка вместо команды (кнопки «на сайт»)


def booking_buttons(booking_id: int) -> list[BotButton]:
    """Три кнопки записи: подтвердить, перенести, отменить.

    Один набор на напоминание и на /bookings — человек видит в обоих местах
    одно и то же.
    """
    return [
        BotButton("Буду", f"{CMD_CONFIRM}{booking_id}"),
        BotButton("Перенести", f"{CMD_RESCHEDULE}{booking_id}"),
        BotButton("Не смогу", f"{CMD_CANCEL}{booking_id}"),
    ]


def card_buttons(booking) -> list[BotButton]:
    """Кнопки записи в списке /bookings: те же, что на карточке.

    Подтверждённая запись кнопок не имеет (booking_card.render): «Буду» уже
    отработала, а «Перенести» и «Не смогу» на карточке после неё не
    предлагаются. Список обязан показывать то же, иначе у одной записи в
    переписке две разные правды о том, что с ней можно сделать.
    """
    if booking.client_confirmed_at is not None:
        return []
    return booking_buttons(booking.id)


async def upcoming_bookings(db, user_id: int, limit: int = UPCOMING_LIMIT) -> list:
    """Ближайшие активные записи клиента: (booking, salon, master_name, service)."""
    from sqlalchemy import select

    from app.models.models import (
        Booking, BookingStatus, Master, Salon, Service, User,
    )

    # Booking.start_time хранится БЕЗ часового пояса (DateTime(timezone=False)),
    # поэтому сравниваем с таким же наивным «сейчас» — aware-значение asyncpg
    # просто не примет. Зона берётся продуктовая, как и в остальных выборках
    # по записям (панель салона, аналитика).
    from app.utils.timezone import get_salon_time

    now = get_salon_time().replace(tzinfo=None)
    rows = (await db.execute(
        select(Booking, Salon, Service, User.full_name)
        .join(Master, Booking.master_id == Master.id)
        .join(Salon, Master.salon_id == Salon.id)
        .join(Service, Booking.service_id == Service.id)
        .join(User, Master.user_id == User.id, isouter=True)
        .where(
            Booking.client_id == user_id,
            Booking.start_time >= now,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
        .order_by(Booking.start_time)
        .limit(limit)
    )).all()
    return rows


def format_booking(booking, salon, service, master_name: Optional[str]) -> str:
    who = f" · {master_name}" if master_name else ""
    return (f"📅 {booking.start_time:%d.%m в %H:%M} — «{salon.name}»\n"
            f"{service.name}{who} · {format_service_price(service.price, service.price_max)}")


async def cancel_booking(db, user_id: int, booking_id: int) -> tuple[bool, str]:
    """Отменить свою запись из бота. → (получилось, что сказать человеку).

    Правила те же, что на сайте: отменить можно любую активную запись,
    временного окна нет. Разные правила в разных каналах путают людей, а
    вводить окно — решение про политику салона, а не про бота.
    """
    from sqlalchemy import select

    from app.models.models import Booking, BookingStatus

    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )).scalar_one_or_none()
    if booking is None:
        return False, "Запись не найдена."
    if booking.client_id != user_id:
        # Чужую запись не отменяем и не подтверждаем сам факт её наличия.
        return False, "Запись не найдена."
    if booking.status == BookingStatus.CANCELLED:
        return False, "Эта запись уже отменена."
    if booking.status == BookingStatus.COMPLETED:
        return False, "Визит уже состоялся — отменить нельзя."

    booking.status = BookingStatus.CANCELLED
    await db.commit()

    try:
        from app.services.notifications import notify_booking_cancelled

        # refresh_card=False: карточку правит сам бот, на месте и сразу
        # (решение 0021) — второй правкой из очереди её только трясло бы.
        await notify_booking_cancelled(db, booking, refresh_card=False)
    except Exception:
        logger.exception("bot: салон не уведомлён об отмене записи %s", booking_id)

    return True, "Запись отменена. Салон получил уведомление."


async def _own_active_booking(db, user_id: int, booking_id: int):
    """Активная запись этого человека → (запись, что сказать вместо неё).

    Чужую запись не ищем по-особому: ответ тот же, что у несуществующей —
    иначе бот подтверждал бы сам факт её наличия (как в cancel_booking).
    """
    from sqlalchemy import select

    from app.models.models import Booking, BookingStatus

    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )).scalar_one_or_none()
    if booking is None or booking.client_id != user_id:
        return None, "Запись не найдена."
    if booking.status == BookingStatus.CANCELLED:
        return None, "Эта запись уже отменена."
    if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
        return None, "Визит уже состоялся."
    return booking, ""


async def confirm_booking(db, user_id: int, booking_id: int) -> tuple[bool, str]:
    """«Буду» из напоминания. → (подтвердили только что, что сказать человеку).

    Пишем ТОЛЬКО client_confirmed_at. Статус CONFIRMED не трогаем ни при
    каких условиях: его ставит салон, и он уже считается выручкой
    (PAID_BOOKING_STATUSES) — тап клиента сдвинул бы деньги в аналитике,
    зарплатах и обзоре (решение 0020, п. 7).

    Повторный тап идемпотентен: время не переписываем и салон второй раз не
    дёргаем — человек мог нажать дважды просто потому, что не увидел ответа.
    """
    booking, refusal = await _own_active_booking(db, user_id, booking_id)
    if booking is None:
        return False, refusal
    if booking.client_confirmed_at is not None:
        return False, "Вы уже подтвердили эту запись — спасибо!"

    booking.client_confirmed_at = datetime.now(timezone.utc)
    await db.commit()

    try:
        from app.services.notifications import notify_booking_confirmed_by_client

        await notify_booking_confirmed_by_client(db, booking, refresh_card=False)
    except Exception:
        logger.exception("bot: салон не уведомлён о подтверждении записи %s", booking_id)

    return True, "Спасибо, ждём вас! Мастер предупреждён."


_DAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _slot_label(slot: datetime, today) -> str:
    """Подпись окна на кнопке: «сегодня 15:00», «завтра 10:30», «сб 12:00».

    Дальше недели двух суббот подряд не различить, поэтому там — дата.
    """
    delta = (slot.date() - today).days
    if delta == 0:
        return f"сегодня {slot:%H:%M}"
    if delta == 1:
        return f"завтра {slot:%H:%M}"
    if delta < 7:
        return f"{_DAYS_SHORT[slot.weekday()]} {slot:%H:%M}"
    return f"{slot:%d.%m} {slot:%H:%M}"


def site_url(path: str) -> str:
    from app.core.config import settings

    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"


async def reschedule_options(db, user_id: int, booking_id: int) -> tuple[str, list[BotButton]]:
    """Ближайшие свободные окна для переноса → (текст, кнопки).

    Окна считает booking_service.reschedule_slots — ровно тот же счёт, что у
    листа переноса на сайте. Второй дорогой (catalog_slots.nearest_slots)
    было бы короче ходить по дням, но она собирает окна из подготовленного
    каталогом словаря мастера и не знает про исключение самой переносимой
    записи — бот показывал бы человеку время, которого нет на сайте, или
    прятал бы доступное. Поэтому идём по дням и останавливаемся, как только
    набрали шесть: у работающего мастера это первый-второй день.
    """
    from app.services.booking_service import RescheduleError, reschedule_slots
    from app.utils.timezone import get_salon_time

    booking, refusal = await _own_active_booking(db, user_id, booking_id)
    if booking is None:
        return refusal, []

    salon = await _booking_salon(db, booking)
    today = get_salon_time(getattr(salon, "timezone", None)).date()

    found: list[BotButton] = []
    for offset in range(RESCHEDULE_DAYS):
        day = today + timedelta(days=offset)
        try:
            result = await reschedule_slots(db, booking, day.isoformat())
        except RescheduleError as exc:
            return str(exc), []
        for iso in result.get("slots") or []:
            slot = datetime.fromisoformat(iso)
            found.append(BotButton(_slot_label(slot, today),
                                   f"{CMD_RESCHEDULE}{booking.id}:{iso}"))
            if len(found) >= RESCHEDULE_SLOTS:
                break
        if len(found) >= RESCHEDULE_SLOTS:
            break

    other = BotButton("Другое время", url=site_url("/bookings"))
    if not found:
        return ("Свободных окон у мастера на ближайшие дни нет. "
                "Можно посмотреть дальше на сайте или отменить запись.", [other])
    return "Выберите новое время:", found + [other]


async def reschedule_to(db, user_id: int, booking_id: int, iso: str) -> tuple[bool, str]:
    """Перенос на выбранное окно. → (получилось, что сказать человеку).

    Занятое окно — не тупик: вызывающий бот по False показывает свежий
    список (окно могли занять, пока человек выбирал).
    """
    from app.services.booking_service import RescheduleError, reschedule_booking

    booking, refusal = await _own_active_booking(db, user_id, booking_id)
    if booking is None:
        return False, refusal
    try:
        new_start = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return False, "Не удалось разобрать время."

    try:
        old_start = await reschedule_booking(db, booking, new_start)
    except RescheduleError as exc:
        return False, str(exc)

    try:
        from app.services.notifications import notify_booking_rescheduled

        await notify_booking_rescheduled(db, booking, old_start, refresh_card=False)
    except Exception:
        logger.exception("bot: салон не уведомлён о переносе записи %s", booking_id)

    return True, (f"Готово: запись перенесена на "
                  f"{booking.start_time:%d.%m в %H:%M}. Салон предупреждён.")


async def _booking_salon(db, booking):
    from sqlalchemy import select

    from app.models.models import Master, Salon

    master = (await db.execute(
        select(Master).where(Master.id == booking.master_id)
    )).scalar_one_or_none()
    if master is None:
        return None
    return (await db.execute(
        select(Salon).where(Salon.id == master.salon_id)
    )).scalar_one_or_none()


async def schedule_review_request(booking_id: int) -> None:
    """Поставить отложенный вопрос об отзыве после отметки «Пришёл».

    _job_id по booking_id: повторная отметка не должна слать второй вопрос.
    Сбой планировщика не должен ронять саму отметку посещения.
    """
    try:
        from app.core.worker import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job(
            "ask_for_review", booking_id,
            _job_id=f"review-request:{booking_id}",
            _defer_by=REVIEW_DELAY,
        )
    except Exception:
        logger.exception("bot: не поставлен вопрос об отзыве по записи %s", booking_id)


async def review_already_left(db, user_id: int, booking_id: int) -> bool:
    """Отзыв по этой записи уже есть — повторно не спрашиваем."""
    from sqlalchemy import select

    from app.models.models import Review

    return (await db.execute(
        select(Review.id).where(
            Review.booking_id == booking_id, Review.client_id == user_id,
        )
    )).scalars().first() is not None


async def save_review(db, *, user_id: int, booking_id: int, rating: int,
                      comment: str = "") -> tuple[bool, str]:
    """Отзыв из бота. Идёт через ReviewService — он сам проверит визит,
    проставит is_verified и пересчитает рейтинги салона и мастера."""
    from sqlalchemy import select

    from app.models.models import Booking, Master, ReviewTargetType
    from app.services.review_service import ReviewError, ReviewService

    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )).scalar_one_or_none()
    if booking is None or booking.client_id != user_id:
        return False, "Запись не найдена."

    master = (await db.execute(
        select(Master).where(Master.id == booking.master_id)
    )).scalar_one_or_none()
    if master is None:
        return False, "Мастер больше не работает в салоне — отзыв не сохранить."

    try:
        await ReviewService.create_review(
            db, client_id=user_id, salon_id=master.salon_id,
            target_type=ReviewTargetType.MASTER, rating=rating,
            comment=comment, master_id=master.id, booking_id=booking_id,
        )
    except ReviewError as exc:
        return False, str(exc)

    return True, "Спасибо! Отзыв опубликован."
