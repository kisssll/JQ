# app/services/booking_card.py
"""Карточка записи в переписке с ботом: что на ней нарисовано и где она лежит.

Решение 0021. До него каждый тап по кнопке слал НОВОЕ сообщение, а исходная
карточка оставалась с прежним временем и живыми кнопками: после переноса на
13:00 она по-прежнему предлагала подтвердить визит на 10:00. Теперь карточка
перерисовывается на месте — одна переписка, одно сообщение на запись.

Два слоя:

- `render` — что должно быть на карточке сейчас (текст и кнопки) по состоянию
  записи в базе. Один счёт на все три канала, иначе «подтверждено» в MAX и в
  Telegram разъехались бы на первой же правке;
- `remember` / `enqueue_refresh` — адрес сообщения и просьба воркеру его
  переписать, когда запись изменили мимо карточки (отмена на сайте, отмена
  салоном, перенос с другого устройства).

Адрес храним один на запись: канал у человека один, и последняя нарисованная
карточка вытесняет прежнюю. Нарисованные раньше (например, список /bookings
до напоминания) так и останутся со старым текстом — чинить их все значило бы
хранить список сообщений ради случая, которого на проде почти не бывает.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Приписки под карточкой. Отдельной строкой, а не вместо текста: человек
#: должен видеть, ЧТО именно подтверждено или отменено, а не только исход.
NOTE_CONFIRMED = "✅ Вы подтвердили — ждём вас!"
NOTE_CANCELLED = "❌ Запись отменена."
NOTE_RESCHEDULED = "🔄 Запись перенесена. Салон предупреждён."
NOTE_PAST = "Визит состоялся."


async def _context(db, booking_id: int):
    """(запись, салон, услуга, имя мастера) — или None, если записи нет."""
    from sqlalchemy import select

    from app.models.models import Booking, Master, Salon, Service, User

    row = (await db.execute(
        select(Booking, Salon, Service, User.full_name)
        .join(Master, Booking.master_id == Master.id)
        .join(Salon, Master.salon_id == Salon.id)
        .join(Service, Booking.service_id == Service.id)
        .join(User, Master.user_id == User.id, isouter=True)
        .where(Booking.id == booking_id)
    )).first()
    return tuple(row) if row is not None else None


def card_text(booking, salon, service, master_name, note: str = "") -> str:
    """Текст карточки: та же шапка, что в /bookings, плюс адрес и приписка.

    Текст напоминания (tasks.reminder_text) этим НЕ подменяется: его слова
    выбрал владелец. Это то, во что карточка превращается после тапа — там
    уже нужны не уговоры «подтвердите пожалуйста», а состояние записи.
    """
    from app.services.bot_actions import format_booking

    lines = [format_booking(booking, salon, service, master_name)]
    address = getattr(salon, "address", "") or ""
    if address:
        lines.append(address)
    if note:
        lines.append("")
        lines.append(note)
    return "\n".join(lines)


async def render(db, booking_id: int, *, owner_id: int | None = None,
                 note: str = "") -> tuple[str, list]:
    """Что должно быть на карточке сейчас → (текст, кнопки).

    Кнопки живут только у активной записи: у отменённой нажимать нечего, и
    висящая «Буду» — ровно та ложь, ради которой затевалось решение 0021.

    owner_id — чья это карточка. Чужую и несуществующую запись не различаем
    и возвращаем пустой текст: иначе по номеру записи можно было бы вытащить
    время и салон чужого визита (то же правило, что в bot_actions).
    """
    from app.models.models import BookingStatus
    from app.services.bot_actions import booking_buttons

    ctx = await _context(db, booking_id)
    if ctx is None:
        return "", []
    booking, salon, service, master_name = ctx
    if owner_id is not None and booking.client_id != owner_id:
        return "", []

    active = booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
    if not note:
        if booking.status == BookingStatus.CANCELLED:
            note = NOTE_CANCELLED
        elif not active:
            note = NOTE_PAST
        elif booking.client_confirmed_at is not None:
            note = NOTE_CONFIRMED

    text = card_text(booking, salon, service, master_name, note)
    # Подтверждённую запись переносить и отменять всё ещё можно, но кнопка
    # «Буду» уже отработала: повторный тап отвечает «вы уже подтвердили».
    # Решение 0021, п. 1: «Буду» — карточка с галочкой и БЕЗ кнопок.
    if not active or booking.client_confirmed_at is not None:
        return text, []
    return text, booking_buttons(booking.id)


async def render_slots(db, user_id: int, booking_id: int, *,
                       prefix: str = "") -> tuple[str, list]:
    """Та же карточка, но вместо кнопок записи — свободные окна.

    Запись остаётся в тексте намеренно: без неё человек с двумя визитами в
    переписке не поймёт, какой из них двигает. prefix — то, что случилось
    перед показом (например, «это время уже занято»): отдельного экрана
    «что-то пошло не так» решение 0021 не предусматривает, свежий список
    приходит в той же карточке.
    """
    from app.services.bot_actions import reschedule_options

    options, buttons = await reschedule_options(db, user_id, booking_id)
    note = f"{prefix}\n\n{options}" if prefix else options
    text, _ = await render(db, booking_id, owner_id=user_id, note=note)
    return (text, buttons) if text else ("", [])


async def remember(db, booking_id: int, channel, chat_id, message_id) -> None:
    """Запомнить, где лежит карточка. Сбой не роняет саму отправку:
    без адреса карточка просто не обновится извне, а сообщение уже ушло."""
    from sqlalchemy import update

    from app.models.models import Booking

    if not message_id or chat_id is None:
        return
    try:
        await db.execute(
            update(Booking).where(Booking.id == booking_id).values(
                card_channel=channel, card_chat_id=int(chat_id),
                card_message_id=str(message_id),
            )
        )
        await db.commit()
    except Exception:
        logger.exception("карточка записи %s: адрес не сохранён", booking_id)


async def remember_in_new_session(booking_id: int, channel, chat_id, message_id) -> None:
    """То же, но своей сессией — для мест, где сессия уже закрыта
    (напоминание из воркера шлётся после выхода из `async with`)."""
    from app.db.session import AsyncSessionLocal

    if not message_id or chat_id is None:
        return
    try:
        async with AsyncSessionLocal() as db:
            await remember(db, booking_id, channel, chat_id, message_id)
    except Exception:
        logger.exception("карточка записи %s: адрес не сохранён", booking_id)


async def enqueue_refresh(booking_id: int, note: str = "") -> None:
    """Попросить воркер переписать карточку: запись изменили мимо неё.

    Побочное действие, а не часть операции: отмена и перенос не должны
    падать из-за недоступной очереди — так же, как из-за удалённого
    сообщения (см. tasks.refresh_booking_card).
    """
    try:
        from app.core.worker import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job("refresh_booking_card", booking_id, note)
    except Exception:
        logger.exception("карточка записи %s: обновление не поставлено", booking_id)
