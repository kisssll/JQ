# app/services/booking_service.py
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.models import Booking, Master, Service, Salon, BookingStatus
from app.services.schedule_utils import (
    DEFAULT_BREAK_MINUTES, break_or_default, get_effective_work_intervals, window_is_busy,
)
from app.utils.timezone import get_salon_time

# «Пришёл» (COMPLETED) нельзя отметить раньше, чем за час до начала записи —
# защита от преждевременного закрытия визита. start_time хранится наивным в
# зоне салона (см. слот-генератор в bookings.py), поэтому сравниваем с наивным
# «сейчас» в той же зоне.
COMPLETE_MIN_LEAD = timedelta(hours=1)


def can_mark_completed_now(booking: Booking, salon_timezone: Optional[str]) -> bool:
    """Наступило ли окно, когда запись можно отметить «Пришёл» (за час до начала
    и позже). Используется и серверным гейтом, и рендером кнопки в панели."""
    now_local = get_salon_time(salon_timezone).replace(tzinfo=None)
    return now_local >= booking.start_time - COMPLETE_MIN_LEAD


def can_mark_no_show_now(booking: Booking, salon_timezone: Optional[str]) -> bool:
    """Наступило ли время записи — только тогда клиента можно считать неявившимся.

    Раньше гейта не было вовсе: неявку разрешалось отметить за сутки до визита,
    когда клиент физически ещё не мог не прийти (и слот при этом освобождался).
    В отличие от «Пришёл», запаса в час здесь нет — до начала записи опоздания
    не существует.
    """
    now_local = get_salon_time(salon_timezone).replace(tzinfo=None)
    return now_local >= booking.start_time


class SlotTakenError(Exception):
    """Слот заняли между проверкой и вставкой (гонка). Ловится уникальным
    индексом uq_booking_master_slot_active — см. миграцию d7b4c1e05a92."""


async def commit_booking(db, booking) -> None:
    """Зафиксировать бронь, честно отработав гонку за слот.

    is_slot_available() и вставка не атомарны: при одновременных запросах обе
    проверки проходили, и на один слот вставали две записи. Уникальный
    частичный индекс делает вторую вставку невозможной — здесь превращаем
    ошибку БД в доменную, чтобы наверх ушёл понятный 409, а не 500.
    """
    from sqlalchemy.exc import IntegrityError

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise SlotTakenError()
    await db.refresh(booking)


class BookingService:
    
    # Значение живёт в schedule_utils (его берёт и каталог); здесь — прежнее имя.
    DEFAULT_BREAK_MINUTES = DEFAULT_BREAK_MINUTES

    @staticmethod
    async def _break_minutes(db: AsyncSession, master_id: int) -> int:
        """Перерыв мастера после записи. Одно место на проверку записи и на
        генераторы окон (/available, вечерние окна); каталог берёт ту же
        колонку из своего общего запроса через break_or_default."""
        value = await db.scalar(
            select(Master.break_minutes).where(Master.id == master_id)
        )
        return break_or_default(value)
    
    @staticmethod
    async def get_booked_slots(
        db: AsyncSession,
        master_id: int,
        date: datetime
    ) -> list[tuple[datetime, datetime]]:
        """
        Возвращает список занятых интервалов (start, end) для мастера на конкретный день.
        Каждый интервал включает время услуги + перерыв после неё.
        """
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        result = await db.execute(
            select(Booking).where(
                Booking.master_id == master_id,
                Booking.start_time >= start_of_day,
                Booking.start_time < end_of_day,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
            ).order_by(Booking.start_time)
        )
        bookings = result.scalars().all()

        gap = await BookingService._break_minutes(db, master_id)
        slots = []
        for b in bookings:
            # Интервал: от начала записи до конца + перерыв МАСТЕРА. Константу
            # здесь использовать нельзя: сетку свободных окон генератор строит
            # по masters.break_minutes, и при перерыве короче 15 минут проверка
            # отбивала окно, которое сама же система и показала.
            end_with_break = b.end_time + timedelta(minutes=gap)
            slots.append((b.start_time, end_with_break))

        return slots
    
    @staticmethod
    async def is_slot_available(
        db: AsyncSession,
        master_id: int,
        start_time: datetime,
        duration_minutes: int,
        exclude_booking_id: Optional[int] = None,
    ) -> bool:
        """
        Проверяет, свободен ли слот у мастера.
        Учитывает:
        - Длительность услуги (start_time → end_time)
        - Перерыв после занятых записей (end_time + перерыв мастера)
        - Наложения по времени

        Перерыв берём у мастера, а не из константы: по тому же
        masters.break_minutes строит сетку генератор свободных окон
        (BookingService.free_slots), и расхождение означало бы,
        что человек видит окно, на которое не может записаться.

        exclude_booking_id — запись, которую переносят: её нынешнее время
        освобождается вместе с переносом, и без исключения перенос на час
        вперёд при двухчасовой услуге упирался бы в саму себя.
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        gap = await BookingService._break_minutes(db, master_id)
        
        # Ищем ВСЕ записи, которые пересекаются с нашим слотом
        # Пересечение = наша запись начинается ДО конца существующей + перерыв
        # И наша запись заканчивается ПОСЛЕ начала существующей
        query = select(Booking).where(
            Booking.master_id == master_id,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
            # Условие пересечения
            Booking.start_time < end_time,
            Booking.end_time + timedelta(minutes=gap) > start_time
        )
        if exclude_booking_id is not None:
            query = query.where(Booking.id != exclude_booking_id)
        result = await db.execute(query)
        existing = result.scalars().all()
        
        # Если есть пересекающиеся записи — слот занят
        if len(existing) > 0:
            return False

        # Проверяем: реальные рабочие часы салона, окно записи (2 месяца) и
        # закрытые даты (весь салон / этот мастер) — всё через одну точку
        # правды, чтобы список слотов и создание записи не расходились.
        master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
        if master is None:
            return False
        salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
        if salon is None:
            return False
        intervals = await get_effective_work_intervals(db, salon, master_id, start_time)
        if not intervals:
            return False

        # Слот должен целиком помещаться в один из рабочих интервалов мастера
        # (при сплит-сменах их несколько — например 09–13 и 16–20).
        if not any(ws <= start_time and end_time <= we for ws, we in intervals):
            return False

        return True
    
    @staticmethod
    async def free_slots(
        db: AsyncSession,
        master_id: int,
        service: Service,
        salon: Salon,
        target_date: datetime,
        *,
        intervals: Optional[list] = None,
        exclude_booking_id: Optional[int] = None,
    ) -> tuple[list[str], int, int]:
        """Свободные окна мастера на день: (окна «ГГГГ-ММ-ДДTЧЧ:ММ», перерыв, шаг).

        Одна механика на экран записи у салона и на перенос: если бы перенос
        считал окна по-своему, человек видел бы при переносе время, которого
        нет при записи, или наоборот. exclude_booking_id — переносимая запись:
        её нынешнее время для неё самой не занято (см. is_slot_available).
        """
        if intervals is None:
            intervals = await get_effective_work_intervals(db, salon, master_id, target_date)
        # Перерыв той же дорогой, что у проверки записи: показ и проверка обязаны
        # считать одно и то же, иначе человек видит окно и получает отказ.
        gap = await BookingService._break_minutes(db, master_id)
        #: Перерыв нужен МЕЖДУ клиентами, а не после последнего за день (решение
        #: владельца 31.10.2026). Отсюда три разных числа, и путать их нельзя:
        #:   step — шаг сетки, с перерывом: соседние показанные окна не налезают
        #:          на отдых между ними;
        #:   busy_span — сколько окно держит мастера при сравнении с ЧУЖИМИ
        #:          записями: услуга плюс перерыв, иначе покажем окно встык к
        #:          следующему клиенту и мастер останется без передышки;
        #:   fit_span — сколько нужно до конца смены: только услуга. Раньше здесь
        #:          требовался и перерыв, и запись в конец смены пряталась, хотя
        #:          проверка (BookingService.is_slot_available) её принимает.
        step = service.duration_minutes + gap
        busy_span = service.duration_minutes + gap
        fit_span = service.duration_minutes
        if not intervals:
            return [], gap, step

        # Занятые интервалы берём за весь день — они могут попадать в любой из
        # рабочих окон мастера (при сплит-сменах их несколько).
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        query = select(Booking).where(
            Booking.master_id == master_id,
            Booking.start_time >= day_start,
            Booking.start_time < day_end,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
        ).order_by(Booking.start_time)
        if exclude_booking_id is not None:
            query = query.where(Booking.id != exclude_booking_id)
        busy = [
            (b.start_time.replace(tzinfo=None), b.end_time.replace(tzinfo=None))
            for b in (await db.execute(query)).scalars().all()
        ]

        now = get_salon_time(salon.timezone).replace(tzinfo=None)

        slots = []
        for work_start, work_end in intervals:
            current = work_start
            while current + timedelta(minutes=fit_span) <= work_end:
                slot_end = current + timedelta(minutes=busy_span)

                if current < now:
                    current += timedelta(minutes=step)
                    continue

                # Раньше перерыв после чужой записи здесь не вычитался: окно сразу
                # после записи «не по сетке» показывалось, а проверка его отбивала
                # (решение 0017, п. 1). Конец окна — с собственным перерывом: так
                # сетка считалась и раньше, менять это — отдельное решение.
                if not window_is_busy(current, slot_end, busy, gap):
                    slots.append(current.strftime("%Y-%m-%dT%H:%M"))

                current += timedelta(minutes=step)

        return slots, gap, step

    @staticmethod
    async def complete_booking(db: AsyncSession, booking: Booking) -> Booking:
        """Отмечает запись выполненной («клиент пришёл») — из PENDING или
        CONFIRMED. Дальше сумма (final_price) учитывается в статистике."""
        if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            raise ValueError("Отметить выполненной можно только ожидающую или подтверждённую запись")
        booking.status = BookingStatus.COMPLETED
        if booking.final_price is None:
            service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
            booking.final_price = service.price if service else 0
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def mark_no_show(db: AsyncSession, booking: Booking) -> Booking:
        """Отмечает неявку клиента — из PENDING или CONFIRMED."""
        if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            raise ValueError("Отметить неявкой можно только ожидающую или подтверждённую запись")
        booking.status = BookingStatus.NO_SHOW
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def mark_seen_by_master(db: AsyncSession, booking: Booking) -> Booking:
        """Мастер подтверждает, что видел плановую запись в своём расписании —
        чисто информационная метка, не меняет status записи."""
        booking.master_seen_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def calculate_price(user: 'User', service: 'Service') -> int:
        """Рассчитывает цену с учётом подписки модели"""
        base_price = service.price
        discount = 0
        
        if user.subscription_tier and user.subscription_expires_at:
            # subscription_expires_at — timestamptz (tz-aware); сравнивать с
            # tz-aware UTC, иначе naive datetime.now() даёт TypeError.
            if user.subscription_expires_at > datetime.now(timezone.utc):
                discount_map = {
                    'start': 30,
                    'pro': 50,
                    'premium': 70
                }
                tier = user.subscription_tier
                if hasattr(tier, 'value'):
                    tier = tier.value
                discount_percent = discount_map.get(tier, 0)
                discount = int(base_price * discount_percent / 100)
        
        return base_price - discount

# ── Перенос записи клиентом (решение 0020) ──────────────────────────────────

#: Что можно перенести. Выполненную, отменённую и неявку — нельзя: это уже
#: история, а не план, и сдвиг времени переписал бы факт.
RESCHEDULABLE_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)

_NOT_RESCHEDULABLE = {
    BookingStatus.CANCELLED: "Запись отменена — перенести её нельзя. Запишитесь заново.",
    BookingStatus.COMPLETED: "Визит уже состоялся — переносить нечего.",
    BookingStatus.NO_SHOW: "Запись закрыта как неявка — перенести её нельзя.",
}


class RescheduleError(Exception):
    """Перенос невозможен по правилам. status_code — код ответа API: 400 на
    неподходящую запись или время, 409 на занятое окно."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class RescheduleQuote:
    """Что получится после переноса — показывается человеку ДО подтверждения
    (цена могла измениться из-за вечерней скидки, п. 9 решения 0020)."""
    start_time: datetime
    end_time: datetime
    discount_percent: int
    final_price: Optional[int]
    old_price: Optional[int]

    @property
    def price_changed(self) -> bool:
        return self.final_price != self.old_price


async def quote_reschedule(db: AsyncSession, booking: Booking, new_start: datetime) -> RescheduleQuote:
    """Проверить перенос и посчитать его итог, ничего не меняя.

    Порядок проверок — от дешёвых к дорогим. Свободность окна здесь
    предварительная: последнее слово за ограничением в базе при коммите
    (см. reschedule_booking).
    """
    if booking.status not in RESCHEDULABLE_STATUSES:
        raise RescheduleError(_NOT_RESCHEDULABLE.get(booking.status, "Эту запись перенести нельзя."))

    new_start = new_start.replace(tzinfo=None, second=0, microsecond=0)
    if new_start == booking.start_time:
        raise RescheduleError("Запись и так на это время — выберите другое.")

    service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
    master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
    salon = (
        await db.execute(select(Salon).where(Salon.id == master.salon_id))
    ).scalar_one_or_none() if master else None
    if service is None or master is None or salon is None:
        raise RescheduleError("Запись больше нельзя перенести: мастера или услуги уже нет.")
    # Мастер ушёл или салон удалён — новое время некому принять. Подписку
    # салона здесь не смотрим: она закрывает новые записи, а перенос — та же
    # уже принятая запись, и обязательство салона перед клиентом не кончилось.
    if not master.is_active or salon.is_deleted:
        raise RescheduleError("Салон сейчас не принимает записи — перенести не получится.")

    # start_time хранится наивным в зоне салона, поэтому и «сейчас» — салонное.
    # С datetime.now() сервера проверка разошлась бы с показанными окнами у
    # всех салонов не в UTC (так же, как в create_booking).
    if new_start < get_salon_time(salon.timezone).replace(tzinfo=None):
        raise RescheduleError("Нельзя перенести запись на прошедшее время.")

    if not await BookingService.is_slot_available(
        db, booking.master_id, new_start, service.duration_minutes,
        exclude_booking_id=booking.id,
    ):
        raise RescheduleError("Это время уже занято — выберите другое.", status_code=409)

    discount, price = await _rescheduled_price(db, booking, service, salon, new_start)
    return RescheduleQuote(
        start_time=new_start,
        end_time=new_start + timedelta(minutes=service.duration_minutes),
        discount_percent=discount,
        final_price=price,
        old_price=booking.final_price,
    )


async def _rescheduled_price(
    db: AsyncSession, booking: Booking, service: Service, salon: Salon, new_start: datetime,
) -> tuple[int, Optional[int]]:
    """Скидка и цена на новом времени.

    Скидка вечернего окна достаётся пустому вечеру, а не человеку: переехав
    в дневное время, запись её теряет. Обратный переезд новой скидки не даёт —
    иначе скидка стала бы способом взять прайм-тайм дешевле за счёт салона
    (записался днём, перенёс на вечер, получил вечернюю цену). Вечер → вечер
    сохраняет меньшую из двух скидок.

    Если скидка не меняется, цену не трогаем вовсе: перенос — не повод
    переписывать цену по прайсу, который салон мог поднять после записи.
    """
    from app.services.evening_deals_service import discounted_price, evening_deal_discount

    old_discount = booking.discount_percent or 0
    new_discount = 0
    if old_discount > 0:
        evening = await evening_deal_discount(db, salon, new_start, service.id)
        if evening > 0:
            new_discount = min(old_discount, evening)
    if new_discount == old_discount:
        return old_discount, booking.final_price

    from app.models.models import User
    client = (await db.execute(select(User).where(User.id == booking.client_id))).scalar_one_or_none()
    base = await BookingService.calculate_price(client, service) if client else service.price
    return new_discount, (discounted_price(base, new_discount) if new_discount else base)


async def reschedule_booking(db: AsyncSession, booking: Booking, new_start: datetime) -> datetime:
    """Перенести запись на новое время. Возвращает прежнее начало (для
    уведомлений «с … на …»).

    Это та же запись: двигаются start_time/end_time, номер, клиент, история
    и оплата остаются. Строку берём под блокировку: двойной тап по
    «Перенести» иначе прошёл бы проверки дважды и насчитал два переноса.
    """
    locked = (await db.execute(
        select(Booking).where(Booking.id == booking.id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one()

    quote = await quote_reschedule(db, locked, new_start)
    old_start = locked.start_time

    locked.start_time = quote.start_time
    locked.end_time = quote.end_time
    locked.discount_percent = quote.discount_percent
    locked.final_price = quote.final_price
    locked.rescheduled_count = (locked.rescheduled_count or 0) + 1
    locked.rescheduled_at = datetime.now(timezone.utc)
    try:
        # Ограничение исключения в базе — последнее слово в гонке: между
        # проверкой и коммитом окно мог занять другой клиент.
        await commit_booking(db, locked)
    except SlotTakenError:
        raise RescheduleError("Это время только что заняли — выберите другое.", status_code=409)
    return old_start


async def reschedule_slots(db: AsyncSession, booking: Booking, date: str) -> dict:
    """Свободные окна для переноса этой записи на день date (ГГГГ-ММ-ДД).

    Механика та же, что у экрана записи (free_slots), только без самой
    переносимой записи среди занятых. Её нынешнее время в список не
    попадает: перенос на него ничего не меняет.
    """
    from app.services.schedule_utils import MAX_BOOKING_DAYS_AHEAD, is_within_booking_window

    if booking.status not in RESCHEDULABLE_STATUSES:
        raise RescheduleError(_NOT_RESCHEDULABLE.get(booking.status, "Эту запись перенести нельзя."))
    try:
        target_date = datetime.fromisoformat(date)
    except (ValueError, TypeError):
        raise RescheduleError("Не удалось разобрать дату.")
    if not is_within_booking_window(target_date):
        return {"date": date, "slots": [],
                "message": f"Запись открыта максимум на {MAX_BOOKING_DAYS_AHEAD} дней вперёд"}

    service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
    master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
    salon = (
        await db.execute(select(Salon).where(Salon.id == master.salon_id))
    ).scalar_one_or_none() if master else None
    if service is None or salon is None:
        return {"date": date, "slots": [], "message": "Мастера или услуги больше нет"}

    slots, _, _ = await BookingService.free_slots(
        db, booking.master_id, service, salon, target_date, exclude_booking_id=booking.id,
    )
    current = booking.start_time.strftime("%Y-%m-%dT%H:%M")
    slots = [s for s in slots if s != current]
    result = {"date": date, "slots": slots}
    if not slots:
        result["message"] = "В этот день свободного времени нет — выберите другой"
    return result
