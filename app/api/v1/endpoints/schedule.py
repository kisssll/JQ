# app/api/v1/endpoints/schedule.py
"""Закрытие календарных дат для записи (весь салон или один мастер) и
индивидуальный недельный график мастера (Schedule)."""
from datetime import date as date_type, datetime, time as time_type
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import User, Master, Schedule, Salon, Booking, BookingStatus
from app.api.deps import get_current_user, check_salon_permission
from app.services.schedule_service import ScheduleService, ScheduleError
from app.services.schedule_utils import (
    get_salon_work_hours, compute_effective_intervals, merge_intervals,
)

router = APIRouter()


@router.get("/salon/{salon_id}/closures")
async def list_closures(
    salon_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_schedule")
    closures = await ScheduleService.list_closures(db, salon_id)
    return [
        {
            "id": c.id, "date": c.date.isoformat(), "master_id": c.master_id,
            "reason": c.reason, "created_at": c.created_at.isoformat(),
        }
        for c in closures
    ]


class CloseDateRequest(BaseModel):
    date: date_type
    master_id: Optional[int] = None
    reason: Optional[str] = None


@router.post("/salon/{salon_id}/closures", status_code=status.HTTP_201_CREATED)
async def create_closure(
    salon_id: int,
    body: CloseDateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_schedule")
    try:
        closure = await ScheduleService.close_date(
            db, salon_id=salon_id, master_id=body.master_id, date=body.date,
            reason=body.reason, actor=current_user,
        )
    except ScheduleError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"id": closure.id, "date": closure.date.isoformat(), "master_id": closure.master_id}


@router.delete("/salon/{salon_id}/closures/{closure_id}")
async def delete_closure(
    salon_id: int,
    closure_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_schedule")
    try:
        await ScheduleService.reopen_date(db, closure_id=closure_id, salon_id=salon_id)
    except ScheduleError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"status": "reopened"}


# ========== Индивидуальный недельный график мастера ==========

class ShiftIn(BaseModel):
    day_of_week: int   # 0=Пн ... 6=Вс
    start: str         # "HH:MM"
    end: str           # "HH:MM"


class SaveScheduleIn(BaseModel):
    shifts: List[ShiftIn]


async def _load_master(db: AsyncSession, master_id: int) -> Master:
    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=404, detail="Мастер не найден")
    return master


async def _authorize_master_schedule(db: AsyncSession, user: User, master: Master) -> None:
    """Редактировать график может либо сам мастер (свой профиль), либо тот, у
    кого в салоне есть право manage_schedule (владелец/сотрудник)."""
    if master.user_id == user.id:
        return
    await check_salon_permission(db, user, master.salon_id, "manage_schedule")


def _parse_hhmm(value: str) -> time_type:
    try:
        h, m = map(int, value.split(":"))
        return time_type(hour=h, minute=m)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Некорректное время: «{value}» (ожидается ЧЧ:ММ)")


@router.get("/master/{master_id}/schedule")
async def get_master_schedule(
    master_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    master = await _load_master(db, master_id)
    await _authorize_master_schedule(db, current_user, master)
    rows = (await db.execute(
        select(Schedule).where(Schedule.master_id == master_id)
        .order_by(Schedule.day_of_week, Schedule.start_time)
    )).scalars().all()
    return {
        "master_id": master_id,
        "shifts": [
            {"day_of_week": r.day_of_week,
             "start": r.start_time.strftime("%H:%M"),
             "end": r.end_time.strftime("%H:%M")}
            for r in rows
        ],
    }


@router.put("/master/{master_id}/schedule")
async def save_master_schedule(
    master_id: int,
    body: SaveScheduleIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полная замена недельного графика мастера. Валидирует интервалы
    (начало<конец, без пересечений внутри дня) и предупреждает, если после
    сохранения остаются будущие брони вне графика (не удаляя их)."""
    master = await _load_master(db, master_id)
    await _authorize_master_schedule(db, current_user, master)

    # --- Разбор и валидация ---
    parsed: List[tuple] = []  # (day_of_week, time_start, time_end)
    for sh in body.shifts:
        if not 0 <= sh.day_of_week <= 6:
            raise HTTPException(status_code=400, detail="day_of_week вне диапазона 0..6")
        st, en = _parse_hhmm(sh.start), _parse_hhmm(sh.end)
        if en <= st:
            raise HTTPException(status_code=400, detail="Начало смены должно быть раньше конца")
        parsed.append((sh.day_of_week, st, en))

    # Пересечения внутри одного дня недели
    for day in range(7):
        intervals = sorted((st, en) for d, st, en in parsed if d == day)
        for i in range(1, len(intervals)):
            if intervals[i][0] < intervals[i - 1][1]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Смены пересекаются в один день (день {day})",
                )

    # --- Замена графика ---
    await db.execute(delete(Schedule).where(Schedule.master_id == master_id))
    for day, st, en in parsed:
        db.add(Schedule(master_id=master_id, day_of_week=day, start_time=st, end_time=en))
    await db.commit()

    # --- Предупреждение: будущие брони вне нового графика ---
    conflicts = await _count_bookings_outside_schedule(db, master, parsed)
    warning = None
    if conflicts:
        warning = (
            f"Сохранено, но у мастера {conflicts} будущих записей вне нового графика "
            f"— они остаются в силе, проверьте их вручную."
        )
    return {"saved": len(parsed), "conflicts": conflicts, "warning": warning}


async def _count_bookings_outside_schedule(db: AsyncSession, master: Master, parsed: List[tuple]) -> int:
    """Сколько будущих активных броней мастера не попадают в новый график
    (пересечение смен с часами салона). Закрытия дат тут не учитываем —
    это лишь предупреждение."""
    salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
    if salon is None:
        return 0
    now = datetime.now()
    future = (await db.execute(
        select(Booking).where(
            Booking.master_id == master.id,
            Booking.start_time >= now,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
    )).scalars().all()

    has_any = len(parsed) > 0
    conflicts = 0
    for b in future:
        weekday = b.start_time.weekday()
        day_intervals = merge_intervals([
            (b.start_time.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0),
             b.start_time.replace(hour=en.hour, minute=en.minute, second=0, microsecond=0))
            for d, st, en in parsed if d == weekday
        ])
        salon_hours = get_salon_work_hours(salon.working_hours, b.start_time)
        eff = compute_effective_intervals(salon_hours, has_any, day_intervals)
        if not any(ws <= b.start_time and b.end_time <= we for ws, we in eff):
            conflicts += 1
    return conflicts
