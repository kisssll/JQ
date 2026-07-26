# app/services/schedule_utils.py
import json
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

Interval = Tuple[datetime, datetime]

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES_SHORT_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_CLOSED_VALUES = ("выходной", "closed", "day off", "")

# Запись открыта на 2 месяца вперёд от сегодняшнего дня.
MAX_BOOKING_DAYS_AHEAD = 60


def format_working_hours_summary(working_hours_json: Optional[str]) -> str:
    """Человекочитаемая сводка режима работы салона из JSON вида
    {"mon": "10:00-20:00", ..., "sun": "closed"} — соседние дни с
    одинаковым режимом группируются («Пн–Пт 10:00–20:00, Сб–Вс выходной»).
    Пустой/битый JSON → нейтральный дефолт (как было раньше)."""
    default = "Пн–Вс: 10:00 — 21:00"
    if not working_hours_json:
        return default
    try:
        hours = json.loads(working_hours_json)
    except (ValueError, TypeError):
        return default
    if not isinstance(hours, dict):
        return default

    day_values = []
    for day in DAY_NAMES:
        raw = (hours.get(day) or "").strip().lower()
        day_values.append("выходной" if raw in _CLOSED_VALUES else raw.replace("-", "–"))

    groups: list[tuple[int, int, str]] = []  # (start_idx, end_idx, value)
    for i, value in enumerate(day_values):
        if groups and groups[-1][2] == value:
            groups[-1] = (groups[-1][0], i, value)
        else:
            groups.append((i, i, value))

    parts = []
    for start, end, value in groups:
        if start == end:
            days_label = DAY_NAMES_SHORT_RU[start]
        else:
            days_label = f"{DAY_NAMES_SHORT_RU[start]}–{DAY_NAMES_SHORT_RU[end]}"
        parts.append(f"{days_label} {value}")

    return ", ".join(parts) if parts else default


def get_salon_work_hours(
    working_hours_json: Optional[str], target_date: datetime
) -> Optional[Tuple[datetime, datetime]]:
    """
    Парсит Salon.working_hours (JSON вида {"mon": "09:00-21:00", "tue": "выходной", ...})
    и возвращает (work_start, work_end) для дня target_date, либо None — если
    график не задан/повреждён или салон в этот день не работает.
    """
    if not working_hours_json:
        return None
    try:
        working_hours = json.loads(working_hours_json)
    except (ValueError, TypeError):
        return None

    day_name = DAY_NAMES[target_date.weekday()]
    time_range = working_hours.get(day_name)
    if not time_range or time_range in ("выходной", "closed", "day off"):
        return None

    try:
        start_str, end_str = time_range.split("-")
        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))
    except (ValueError, AttributeError):
        return None

    work_start = target_date.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    work_end = target_date.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return work_start, work_end


def is_within_booking_window(target_date: datetime) -> bool:
    """Дата не дальше MAX_BOOKING_DAYS_AHEAD дней от сегодня."""
    horizon = datetime.now().date() + timedelta(days=MAX_BOOKING_DAYS_AHEAD)
    return target_date.date() <= horizon


# ---------------------------------------------------------------------------
# Чистые (без БД) хелперы для пересечения смен мастера с часами салона.
# Вынесены отдельно, чтобы покрыть логику доступности юнит-тестами.
# ---------------------------------------------------------------------------

def merge_intervals(intervals: List[Interval]) -> List[Interval]:
    """Сортирует и склеивает пересекающиеся/смежные интервалы одного дня."""
    valid = sorted((s, e) for s, e in intervals if e > s)
    merged: List[Interval] = []
    for s, e in valid:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def intersect_intervals(intervals: List[Interval], window: Interval) -> List[Interval]:
    """Пересекает список интервалов с окном (часами салона). Что вне окна —
    отбрасывается; пустые пересечения не попадают в результат."""
    ws, we = window
    out: List[Interval] = []
    for s, e in intervals:
        cs, ce = max(s, ws), min(e, we)
        if ce > cs:
            out.append((cs, ce))
    return merge_intervals(out)


def build_day_intervals(schedule_rows, target_date: datetime) -> List[Interval]:
    """Строит datetime-интервалы на target_date из строк Schedule (start_time/
    end_time — time-объекты). Некорректные (end<=start) пропускаются."""
    out: List[Interval] = []
    for r in schedule_rows:
        s = target_date.replace(hour=r.start_time.hour, minute=r.start_time.minute, second=0, microsecond=0)
        e = target_date.replace(hour=r.end_time.hour, minute=r.end_time.minute, second=0, microsecond=0)
        if e > s:
            out.append((s, e))
    return merge_intervals(out)


def compute_effective_intervals(
    salon_hours: Optional[Interval],
    has_any_master_schedule: bool,
    master_day_intervals: List[Interval],
) -> List[Interval]:
    """Итоговые рабочие интервалы мастера на день (чистая функция):
    - салон в этот день закрыт (salon_hours=None) → [] ;
    - у мастера НЕТ индивидуального графика вообще → работает по часам салона
      (обратная совместимость) → [salon_hours] ;
    - у мастера ЕСТЬ график, но не на этот день недели → выходной → [] ;
    - иначе — смены мастера, обрезанные часами салона."""
    if salon_hours is None:
        return []
    if not has_any_master_schedule:
        return [salon_hours]
    if not master_day_intervals:
        return []
    return intersect_intervals(master_day_intervals, salon_hours)


async def get_effective_work_intervals(
    db: AsyncSession, salon, master_id: int, target_date: datetime
) -> List[Interval]:
    """Единая точка правды о доступности дня для записи. Сочетает окно в 2
    месяца, недельный график салона, индивидуальный график мастера (Schedule)
    и закрытые даты (ScheduleClosure — на весь салон или на мастера).
    Возвращает список рабочих интервалов (несколько — при сплит-сменах);
    пустой список — записаться нельзя ни по какой из причин."""
    from app.models.models import ScheduleClosure, Schedule  # локальный импорт — без цикла с models.py

    if not is_within_booking_window(target_date):
        return []

    salon_hours = get_salon_work_hours(salon.working_hours, target_date)
    if salon_hours is None:
        return []

    closed = await db.execute(
        select(ScheduleClosure.id).where(
            ScheduleClosure.salon_id == salon.id,
            ScheduleClosure.date == target_date.date(),
            (ScheduleClosure.master_id.is_(None)) | (ScheduleClosure.master_id == master_id),
        )
    )
    if closed.first() is not None:
        return []

    # Индивидуальный график мастера. Пусто совсем → fallback на часы салона.
    all_rows = (await db.execute(
        select(Schedule).where(Schedule.master_id == master_id)
    )).scalars().all()
    has_any = len(all_rows) > 0
    day_intervals = build_day_intervals(
        [r for r in all_rows if r.day_of_week == target_date.weekday()], target_date
    )
    return compute_effective_intervals(salon_hours, has_any, day_intervals)
