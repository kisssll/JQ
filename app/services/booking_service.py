# app/services/booking_service.py
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.models import Booking, Master, Service, Salon, BookingStatus
from app.services.schedule_utils import get_effective_work_intervals

class BookingService:
    
    # Время перерыва между записями (в минутах)
    DEFAULT_BREAK_MINUTES = 15
    
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
        
        slots = []
        for b in bookings:
            # Интервал: от начала записи до конца + перерыв
            end_with_break = b.end_time + timedelta(minutes=BookingService.DEFAULT_BREAK_MINUTES)
            slots.append((b.start_time, end_with_break))
        
        return slots
    
    @staticmethod
    async def is_slot_available(
        db: AsyncSession,
        master_id: int,
        start_time: datetime,
        duration_minutes: int
    ) -> bool:
        """
        Проверяет, свободен ли слот у мастера.
        Учитывает:
        - Длительность услуги (start_time → end_time)
        - Перерыв после занятых записей (end_time + 15 мин)
        - Наложения по времени
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        
        # Ищем ВСЕ записи, которые пересекаются с нашим слотом
        # Пересечение = наша запись начинается ДО конца существующей + перерыв
        # И наша запись заканчивается ПОСЛЕ начала существующей
        result = await db.execute(
            select(Booking).where(
                Booking.master_id == master_id,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
                # Условие пересечения
                Booking.start_time < end_time,
                Booking.end_time + timedelta(minutes=BookingService.DEFAULT_BREAK_MINUTES) > start_time
            )
        )
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