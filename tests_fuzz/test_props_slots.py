"""Свойства записи и слотов.

Часть 1 — чистая выдача каталога (catalog_slots.nearest_slots).
Часть 2 — сквозное: слот из /api/v1/bookings/available обязан приниматься
BookingService.is_slot_available, занятое — не приниматься, в любом поясе салона.
"""
import json
from datetime import datetime, time, timedelta

import httpx
from hypothesis import given, seed, strategies as st

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Salon, SalonModerationStatus,
    SalonSubscriptionStatus, Schedule, Service, User, UserRole,
)
from app.services.booking_service import BookingService
from app.services.catalog_slots import CardService, nearest_slots
from app.services.schedule_utils import DAY_NAMES
from app.utils.timezone import get_salon_time
from tests_fuzz.conftest import wipe_all_tables
from tests_fuzz.profile import SEED, props

# Пояса, где «сегодня» у салона и у сервера может различаться, плюс переход через полночь.
ZONES = ["Europe/Moscow", "Asia/Tomsk", "Asia/Vladivostok", "Pacific/Kiritimati",
         "Pacific/Pago_Pago", "UTC"]

hm = st.tuples(st.integers(0, 23), st.sampled_from([0, 15, 30, 45]))


def _fmt(t):
    return f"{t[0]:02d}:{t[1]:02d}"


@st.composite
def hours(draw):
    """Часы салона на неделю. Конец раньше начала («22:00-02:00») допустим как мусор:
    свойство — что выдача при этом пустая, а не упавшая."""
    start, end = draw(hm), draw(hm)
    return {d: f"{_fmt(start)}-{_fmt(end)}" for d in DAY_NAMES}


# ── Часть 1: nearest_slots ────────────────────────────────────────────────────
@seed(SEED)
@props()
@given(wh=hours(), tz=st.sampled_from(ZONES), duration=st.integers(5, 240),
       brk=st.integers(0, 60), busy=st.lists(st.tuples(st.integers(0, 3), hm, st.integers(5, 240)), max_size=4),
       sch=st.lists(st.tuples(st.integers(0, 6), hm, hm), max_size=4))
def test_card_slots_fit_hours_duration_break_and_busy(wh, tz, duration, brk, busy, sch):
    now0 = get_salon_time(tz).replace(tzinfo=None)
    bk = []
    for off, (h, m), mins in busy:
        s = (now0 + timedelta(days=off)).replace(hour=h, minute=m, second=0, microsecond=0)
        bk.append({"s": s.strftime("%Y-%m-%d %H:%M"), "e": (s + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M")})
    master = {"id": 1, "brk": brk, "bk": bk,
              "sch": [{"d": d, "s": _fmt(a), "e": _fmt(b)} for d, a, b in sch]}
    slots = nearest_slots(working_hours=json.dumps(wh), tz=tz, master=master,
                          service=CardService(1, "Услуга", 1000, None, duration, 1), closures=[], limit=50)
    step = duration + brk
    for sl in slots:
        start, end = sl.start, sl.start + timedelta(minutes=step)
        assert start >= now0 - timedelta(minutes=1), "слот в прошлом"
        # Чужая запись держит мастера до конца + перерыв (решение 0017, п. 1).
        assert not any(start < datetime.strptime(b["e"], "%Y-%m-%d %H:%M") + timedelta(minutes=brk)
                       and end > datetime.strptime(b["s"], "%Y-%m-%d %H:%M") for b in bk), \
            "слот поверх занятого или внутри перерыва после него"
        assert start.date() == end.date() or (end.hour, end.minute) == (0, 0), "слот перешёл через полночь"
    starts = [s.start for s in slots]
    assert starts == sorted(starts)
    for a, b in zip(starts, starts[1:]):
        if a.date() == b.date():
            assert (b - a) >= timedelta(minutes=step), "слоты ближе, чем услуга + перерыв"


# ── Часть 2: выданный слот принимается ────────────────────────────────────────
async def _world(db_session, *, wh, tz, brk, durations, split, preexisting):
    """Свежий мир на один пример. Возвращает (master_id, service_ids, day)."""
    await wipe_all_tables()
    pw = get_password_hash("Fuzzpass1")
    day = (get_salon_time(tz).replace(tzinfo=None) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    async with db_session() as db:
        owner = User(phone="+79990000001", full_name="В", hashed_password=pw, role=UserRole.BUSINESS)
        muser = User(phone="+79990000002", full_name="М", hashed_password=pw, role=UserRole.MASTER)
        client = User(phone="+79990000003", full_name="К", hashed_password=pw, role=UserRole.CLIENT)
        db.add_all([owner, muser, client])
        await db.commit()
        salon = Salon(name="С", description="", address="а", latitude=56.5, longitude=84.9,
                      phone="+79990001111", city="Томск", is_active=True, creator_id=owner.id,
                      moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      working_hours=json.dumps(wh), timezone=tz)
        db.add(salon)
        await db.commit()
        master = Master(user_id=muser.id, salon_id=salon.id, specialization="м", is_active=True,
                        break_minutes=brk)
        db.add(master)
        await db.commit()
        if split:
            for d in range(7):
                db.add_all([Schedule(master_id=master.id, day_of_week=d, start_time=time(9), end_time=time(13)),
                            Schedule(master_id=master.id, day_of_week=d, start_time=time(16), end_time=time(20))])
        svcs = []
        for i, dur in enumerate(durations):
            sv = Service(master_id=master.id, name=f"У{i}", price=1000, duration_minutes=dur, is_active=True)
            db.add(sv)
            svcs.append(sv)
        await db.commit()
        for sv in svcs:
            await db.refresh(sv)
        if preexisting:
            off, dur = preexisting
            start = day.replace(hour=0) + timedelta(minutes=off)
            db.add(Booking(client_id=client.id, master_id=master.id, service_id=svcs[0].id,
                           start_time=start, end_time=start + timedelta(minutes=dur),
                           status=BookingStatus.CONFIRMED))
            await db.commit()
        return master.id, [s.id for s in svcs], day, client.id


async def _offered_vs_accepted(db_session, master_id, service_id, duration, day):
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        r = await c.get(f"/api/v1/bookings/available/{master_id}",
                        params={"date": day.strftime("%Y-%m-%d"), "service_id": service_id})
    assert r.status_code == 200, r.text
    rejected = []
    async with db_session() as db:
        for s in r.json()["slots"]:
            if not await BookingService.is_slot_available(db, master_id, datetime.fromisoformat(s), duration):
                rejected.append(s)
    return r.json()["slots"], rejected


_world_args = dict(
    wh=hours(), tz=st.sampled_from(ZONES), brk=st.sampled_from([0, 5, 10, 15, 30]),
    split=st.booleans(),
)


@seed(SEED)
@props(examples=25)
@given(duration=st.sampled_from([15, 30, 45, 60, 90]), **_world_args)
def test_every_offered_slot_is_accepted(run, db_session, wh, tz, brk, split, duration):
    """Нет других записей: что показали, на то и можно записаться."""
    mid, (sid,), day, _ = run(_world(db_session, wh=wh, tz=tz, brk=brk, durations=[duration],
                                     split=split, preexisting=None))
    offered, rejected = run(_offered_vs_accepted(db_session, mid, sid, duration, day))
    assert not rejected, f"показаны, но не принимаются: {rejected} из {offered}"


@seed(SEED)
@props(examples=60)
@given(duration=st.sampled_from([15, 30, 45, 60]), other_dur=st.sampled_from([15, 30, 45, 60]),
       other_off=st.integers(9 * 12, 18 * 12).map(lambda k: k * 5),
       tz=st.sampled_from(ZONES), brk=st.sampled_from([5, 10, 15, 30]))
def test_offered_slot_is_accepted_next_to_an_existing_booking(
        run, db_session, tz, brk, duration, other_dur, other_off):
    """Салон 08:00–22:00, одна чужая запись в произвольную пятиминутку."""
    wh = {d: "08:00-22:00" for d in DAY_NAMES}
    mid, (sid,), day, _ = run(_world(db_session, wh=wh, tz=tz, brk=brk, durations=[duration],
                                     split=False, preexisting=(other_off, other_dur)))
    offered, rejected = run(_offered_vs_accepted(db_session, mid, sid, duration, day))
    assert not rejected, f"показаны, но не принимаются: {rejected} (запись с {other_off} мин на {other_dur})"


@seed(SEED)
@props(examples=25)
@given(duration=st.sampled_from([15, 30, 60]), delta=st.integers(-59, 59),
       off=st.integers(9 * 60, 18 * 60).map(lambda m: m - m % 5),
       tz=st.sampled_from(ZONES), brk=st.sampled_from([0, 15, 30]))
def test_a_taken_slot_is_not_accepted_twice(run, db_session, duration, delta, off, tz, brk):
    """Занятое время — и любое пересекающееся — не принимается повторно."""
    wh = {d: "08:00-22:00" for d in DAY_NAMES}
    mid, (sid,), day, _ = run(_world(db_session, wh=wh, tz=tz, brk=brk, durations=[duration],
                                     split=False, preexisting=(off, duration)))

    async def probe():
        async with db_session() as db:
            start = day + timedelta(minutes=off + delta)
            return await BookingService.is_slot_available(db, mid, start, duration)

    overlaps = abs(delta) < duration + (brk if delta > 0 else 0)
    ok = run(probe())
    if overlaps:
        assert not ok, f"пересекающееся время принято (сдвиг {delta} мин, перерыв {brk})"
