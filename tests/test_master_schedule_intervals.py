"""Юнит-тесты чистой логики доступности мастера (без БД):
пересечение смен с часами салона, сплит-смены, fallback и выходные.
См. app/services/schedule_utils."""
from datetime import datetime, time

from app.services.schedule_utils import (
    merge_intervals,
    intersect_intervals,
    build_day_intervals,
    compute_effective_intervals,
)

D = datetime(2026, 7, 27)  # понедельник


def dt(h, m=0):
    return D.replace(hour=h, minute=m, second=0, microsecond=0)


class _Row:
    """Мимикрия под ORM Schedule: нужны только start_time/end_time (time)."""
    def __init__(self, sh, sm, eh, em, day=0):
        self.start_time = time(sh, sm)
        self.end_time = time(eh, em)
        self.day_of_week = day


# ---------- merge_intervals ----------

def test_merge_sorts_and_joins_overlapping():
    assert merge_intervals([(dt(16), dt(20)), (dt(9), dt(13)), (dt(12), dt(14))]) == [
        (dt(9), dt(14)), (dt(16), dt(20)),
    ]


def test_merge_drops_empty_and_inverted():
    assert merge_intervals([(dt(10), dt(10)), (dt(12), dt(11))]) == []


# ---------- intersect_intervals ----------

def test_intersect_clips_to_salon_window():
    # смена 08–22, салон 10–18 → 10–18
    assert intersect_intervals([(dt(8), dt(22))], (dt(10), dt(18))) == [(dt(10), dt(18))]


def test_intersect_split_shift_partially_outside():
    # сплит 09–13 и 16–20, салон 12–18 → 12–13 и 16–18
    got = intersect_intervals([(dt(9), dt(13)), (dt(16), dt(20))], (dt(12), dt(18)))
    assert got == [(dt(12), dt(13)), (dt(16), dt(18))]


def test_intersect_fully_outside_gives_empty():
    assert intersect_intervals([(dt(6), dt(8))], (dt(10), dt(18))) == []


# ---------- build_day_intervals ----------

def test_build_from_rows_merges():
    rows = [_Row(9, 0, 13, 0), _Row(16, 0, 20, 0)]
    assert build_day_intervals(rows, D) == [(dt(9), dt(13)), (dt(16), dt(20))]


# ---------- compute_effective_intervals (главная логика) ----------

def test_salon_closed_is_empty():
    assert compute_effective_intervals(None, True, [(dt(9), dt(18))]) == []


def test_no_master_schedule_falls_back_to_salon_hours():
    # у мастера нет графика вообще → часы салона
    assert compute_effective_intervals((dt(10), dt(18)), False, []) == [(dt(10), dt(18))]


def test_has_schedule_but_empty_day_is_day_off():
    # график задан, но на этот день интервалов нет → выходной
    assert compute_effective_intervals((dt(10), dt(18)), True, []) == []


def test_shift_intersected_with_salon_hours():
    # смена 12–16 внутри салона 09–21 → 12–16
    assert compute_effective_intervals((dt(9), dt(21)), True, [(dt(12), dt(16))]) == [(dt(12), dt(16))]


def test_split_shift_clipped_by_salon():
    got = compute_effective_intervals((dt(11), dt(19)), True, [(dt(9), dt(13)), (dt(16), dt(20))])
    assert got == [(dt(11), dt(13)), (dt(16), dt(19))]
