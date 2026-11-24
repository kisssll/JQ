from datetime import datetime, date, time, timedelta
from typing import List, Optional
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.sport import (
    SportBooking,
    SportCoach,
    SportCoachSchedule,
    SportScheduleClosure,
    SportService,
)


class SportSlotTakenError(Exception):
    """Слот уже занят другой записью."""
    pass


class SportBookingService:
    @staticmethod
    async def get_coach_available_slots(
        db: AsyncSession,
        coach_id: int,
        target_date: date,
        duration_minutes: int = 60,
    ) -> List[str]:
        """
        Вычисляет свободные слоты тренера на target_date.
        Тренер сам определяет статичные окна (SportCoachSchedule) по дням недели.
        """
        # 1. Проверяем закрытия (отпуск/больничный тренера или закрытие клуба)
        closure = (
            await db.execute(
                select(SportScheduleClosure.id).where(
                    SportScheduleClosure.date == target_date,
                    or_(
                        SportScheduleClosure.coach_id == coach_id,
                        SportScheduleClosure.coach_id.is_(None),
                    ),
                )
            )
        ).scalar_one_or_none()
        if closure is not None:
            return []

        weekday = target_date.weekday()  # 0=Monday ... 6=Sunday
        schedules = (
            await db.execute(
                select(SportCoachSchedule).where(
                    SportCoachSchedule.coach_id == coach_id,
                    SportCoachSchedule.day_of_week == weekday,
                    SportCoachSchedule.is_active.is_(True),
                )
            )
        ).scalars().all()

        if not schedules:
            return []

        # Загружаем существующие активные брони на этот день у тренера
        day_start = datetime.combine(target_date, time.min)
        day_end = datetime.combine(target_date, time.max)

        existing_bookings = (
            await db.execute(
                select(SportBooking).where(
                    SportBooking.coach_id == coach_id,
                    SportBooking.status.in_(["pending", "confirmed"]),
                    SportBooking.start_time.is_not(None),
                    SportBooking.start_time >= day_start,
                    SportBooking.start_time <= day_end,
                )
            )
        ).scalars().all()

        slots: List[str] = []
        now = datetime.now()

        for sched in schedules:
            current_dt = datetime.combine(target_date, sched.start_time)
            end_dt = datetime.combine(target_date, sched.end_time)
            slot_step = timedelta(minutes=sched.slot_duration_minutes)
            break_step = timedelta(minutes=sched.break_minutes)
            needed_dur = timedelta(minutes=duration_minutes)

            while current_dt + needed_dur <= end_dt:
                slot_end = current_dt + needed_dur

                # Пропускаем слоты в прошлом
                if current_dt > now:
                    # Проверяем пересечение с существующими записями
                    has_conflict = False
                    for b in existing_bookings:
                        if b.start_time and b.end_time:
                            # Пересечение интервалов: max(start1, start2) < min(end1, end2)
                            if max(current_dt, b.start_time) < min(slot_end, b.end_time):
                                has_conflict = True
                                break
                    if not has_conflict:
                        slots.append(current_dt.strftime("%H:%M"))

                # Шаг следующего слота = длительность + перерыв тренера
                current_dt += slot_step + break_step

        return sorted(list(set(slots)))

    @staticmethod
    async def is_slot_available(
        db: AsyncSession,
        coach_id: int,
        start_time: datetime,
        duration_minutes: int,
        exclude_booking_id: Optional[int] = None,
    ) -> bool:
        """Проверяет, свободен ли конкретный слот у тренера."""
        target_date = start_time.date()

        # 0. Проверяем закрытия
        closure = (
            await db.execute(
                select(SportScheduleClosure.id).where(
                    SportScheduleClosure.date == target_date,
                    or_(
                        SportScheduleClosure.coach_id == coach_id,
                        SportScheduleClosure.coach_id.is_(None),
                    ),
                )
            )
        ).scalar_one_or_none()
        if closure is not None:
            return False

        weekday = target_date.weekday()
        slot_time = start_time.time()
        end_time = start_time + timedelta(minutes=duration_minutes)
        slot_end_time = end_time.time()

        # 1. Проверяем, что попадает в график тренера
        schedules = (
            await db.execute(
                select(SportCoachSchedule).where(
                    SportCoachSchedule.coach_id == coach_id,
                    SportCoachSchedule.day_of_week == weekday,
                    SportCoachSchedule.is_active.is_(True),
                )
            )
        ).scalars().all()

        within_schedule = False
        for sched in schedules:
            if sched.start_time <= slot_time and slot_end_time <= sched.end_time:
                within_schedule = True
                break

        if not within_schedule:
            return False

        # 2. Проверяем пересечения с другими бронями
        query = select(SportBooking).where(
            SportBooking.coach_id == coach_id,
            SportBooking.status.in_(["pending", "confirmed"]),
            SportBooking.start_time.is_not(None),
            SportBooking.end_time.is_not(None),
            # Пересечение: max(start, b.start) < min(end, b.end) <=> (b.start < end) AND (b.end > start)
            SportBooking.start_time < end_time,
            SportBooking.end_time > start_time,
        )
        if exclude_booking_id:
            query = query.where(SportBooking.id != exclude_booking_id)

        conflict = (await db.execute(query)).scalar_one_or_none()
        return conflict is None


async def commit_sport_booking(db: AsyncSession, booking: SportBooking) -> None:
    """Атомарная фиксация брони в спортзале с обработкой конфликтов."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise SportSlotTakenError("Это время только что заняли — выберите другое.")
    await db.refresh(booking)
