"""Решение 0017: три находки фаззинга, где расходился смысл, а не ввод.

1. Перерыв мастера: показ окон (/available, «ближайшие окна» каталога,
   вечерние окна) обязан вычитать перерыв после чужой записи — так же, как
   проверка записи BookingService.is_slot_available.
2. Заметки, ручная лояльность и карточка — только клиенту этого салона
   (правило вкладки «Клиенты»: завершённая запись у мастера салона). Иначе 404.
3. Возврат по уже истёкшей подписке не сдвигает конец периода вперёд.

Свойства в tests_fuzz/ гейт не держат, поэтому каждая правка закрыта здесь.
"""
import json
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from app.core.security import create_access_token, get_password_hash
from app.models.models import (
    Booking, BookingStatus, ClientLoyalty, ClientNote, Master, Salon, SalonEveningDeal,
    SalonMember, SalonModerationStatus, SalonRole, SalonSubscriptionStatus, Service,
    User, UserRole,
)
from app.services.booking_service import BookingService
from app.services.subscription import has_access, revoke_paid_period
from app.utils.timezone import get_salon_time

TZ = "Asia/Tomsk"
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ── 1. Перерыв мастера ────────────────────────────────────────────────────────

async def _slot_world(db_session, *, phone: str, wh: dict, brk: int = 15, duration: int = 15,
                      booking_at: datetime = None, booking_minutes: int = 15):
    """Салон, мастер с перерывом, одна услуга и одна чужая запись «не по сетке»."""
    async with db_session() as db:
        owner = User(phone=phone, full_name="Мастер", role=UserRole.BUSINESS,
                     hashed_password=get_password_hash("x"))
        db.add(owner)
        await db.flush()
        salon = Salon(name="Стенд 0017", address="Томск", city="Томск", creator_id=owner.id,
                      is_active=True, moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      access_until=datetime.now(timezone.utc) + timedelta(days=30),
                      working_hours=json.dumps(wh), timezone=TZ,
                      latitude=56.5, longitude=85.0, phone="+73822000017")
        db.add(salon)
        await db.flush()
        master = Master(user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
                        experience_years=1, rating=0.0, break_minutes=brk, is_active=True)
        db.add(master)
        await db.flush()
        service = Service(master_id=master.id, name="Маникюр", price=1000,
                          duration_minutes=duration, is_active=True)
        db.add(service)
        await db.flush()
        if booking_at is not None:
            db.add(Booking(client_id=owner.id, master_id=master.id, service_id=service.id,
                           start_time=booking_at,
                           end_time=booking_at + timedelta(minutes=booking_minutes),
                           status=BookingStatus.CONFIRMED))
        await db.commit()
        return salon.id, master.id, service.id


def _tomorrow():
    return (get_salon_time(TZ).replace(tzinfo=None) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)


async def test_available_hides_the_window_inside_the_break_and_offers_only_acceptable(
        client, db_session):
    """Пример из docs/fuzz-findings.md#F2: 08–22, перерыв 15, услуга 15 (шаг 30),
    чужая запись 09:15–09:30. Окно 09:30 раньше показывалось и не принималось."""
    day = _tomorrow()
    _, mid, sid = await _slot_world(
        db_session, phone="+79990170001", wh={d: "08:00-22:00" for d in _DAYS},
        booking_at=day.replace(hour=9, minute=15))
    r = await client.get(f"/api/v1/bookings/available/{mid}",
                         params={"date": day.strftime("%Y-%m-%d"), "service_id": sid})
    assert r.status_code == 200, r.text
    slots = r.json()["slots"]
    assert r.json()["break"] == 15
    assert day.replace(hour=9, minute=30).strftime("%Y-%m-%dT%H:%M") not in slots
    assert day.replace(hour=10).strftime("%Y-%m-%dT%H:%M") in slots
    async with db_session() as db:
        rejected = [s for s in slots if not await BookingService.is_slot_available(
            db, mid, datetime.fromisoformat(s), 15)]
    assert not rejected, f"показаны, но не принимаются: {rejected}"


async def test_catalog_nearest_windows_respect_the_break(client, db_session):
    """«Ближайшие окна» в карточке каталога: работает только завтрашний день,
    чужая запись 08:15–08:30. 08:00 занято самой записью, 08:30 — перерывом
    после неё; первые три окна — 09:00, 09:30, 10:00, и все они принимаются."""
    from app.services.catalog_slots import load_card_extras

    day = _tomorrow()
    wh = {d: "выходной" for d in _DAYS}
    wh[_DAYS[day.weekday()]] = "08:00-22:00"
    salon_id, mid, _ = await _slot_world(
        db_session, phone="+79990170002", wh=wh, booking_at=day.replace(hour=8, minute=15))
    async with db_session() as db:
        extras = (await load_card_extras(db, [salon_id]))[salon_id]
    got = [s.start for s in extras.slots]
    assert got == [day.replace(hour=9), day.replace(hour=9, minute=30), day.replace(hour=10)]
    async with db_session() as db:
        for start in got:
            assert await BookingService.is_slot_available(db, mid, start, 15), start


async def test_evening_windows_start_after_the_break(client, db_session, monkeypatch):
    """Вечерние окна: чужая запись 17:00–18:00, перерыв 15. Окно начинается
    в 18:15, а не в 18:00, — на 18:00 запись не проходит."""
    import app.services.evening_deals_service as ev

    day = _tomorrow()
    # «Сегодня» для вечерних окон — завтрашний полдень: тест не зависит от часа запуска.
    monkeypatch.setattr(ev, "get_salon_time", lambda tz=None: day.replace(hour=12))
    salon_id, mid, _ = await _slot_world(
        db_session, phone="+79990170003", wh={d: "08:00-22:00" for d in _DAYS},
        booking_at=day.replace(hour=17), booking_minutes=60)
    async with db_session() as db:
        salon = await db.get(Salon, salon_id)
        deal = SalonEveningDeal(salon_id=salon_id, enabled=True, discount_percent=20,
                                evening_from=time(17), evening_to=time(21), weekdays=[])
        free = await ev.free_evening_intervals(db, salon, mid, deal)
        assert free and free[0][0] == day.replace(hour=18, minute=15), free
        assert await BookingService.is_slot_available(db, mid, free[0][0], 15)
        assert not await BookingService.is_slot_available(db, mid, day.replace(hour=18), 15)


# ── 2. Клиент салона ──────────────────────────────────────────────────────────

async def _salon_with_people(db_session):
    """Салон с владельцем и мастером; второй салон; три человека:
    свой клиент (завершённая запись здесь), чужой (завершённая запись только
    во втором салоне) и записанный (только ожидающая запись здесь)."""
    pw = get_password_hash("x")
    async with db_session() as db:
        owner = User(phone="+79990171001", full_name="Владелец", role=UserRole.BUSINESS,
                     hashed_password=pw)
        other_owner = User(phone="+79990171002", full_name="Сосед", role=UserRole.BUSINESS,
                           hashed_password=pw)
        mine = User(phone="+79990171003", full_name="Свой", role=UserRole.CLIENT, hashed_password=pw)
        stranger = User(phone="+79990171004", full_name="Чужой", role=UserRole.CLIENT,
                        hashed_password=pw)
        booked = User(phone="+79990171005", full_name="Записан", role=UserRole.CLIENT,
                      hashed_password=pw)
        db.add_all([owner, other_owner, mine, stranger, booked])
        await db.flush()
        salons = []
        for o in (owner, other_owner):
            s = Salon(name=f"Салон {o.full_name}", address="Томск", city="Томск",
                      creator_id=o.id, is_active=True,
                      moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      access_until=datetime.now(timezone.utc) + timedelta(days=30),
                      latitude=56.5, longitude=85.0, phone="+73822000018")
            db.add(s)
            await db.flush()
            db.add(SalonMember(salon_id=s.id, user_id=o.id, role=SalonRole.OWNER, is_creator=True,
                               permissions={"manage_salon": True}, is_active=True))
            m = Master(user_id=o.id, salon_id=s.id, specialization="м", experience_years=1,
                       rating=0.0, is_active=True)
            db.add(m)
            await db.flush()
            sv = Service(master_id=m.id, name="У", price=1000, duration_minutes=60, is_active=True)
            db.add(sv)
            await db.flush()
            salons.append((s, m, sv))
        (here, m1, sv1), (there, m2, sv2) = salons
        past = datetime.now().replace(microsecond=0) - timedelta(days=3)
        db.add_all([
            Booking(client_id=mine.id, master_id=m1.id, service_id=sv1.id, start_time=past,
                    end_time=past + timedelta(hours=1), status=BookingStatus.COMPLETED,
                    final_price=1000),
            Booking(client_id=stranger.id, master_id=m2.id, service_id=sv2.id, start_time=past,
                    end_time=past + timedelta(hours=1), status=BookingStatus.COMPLETED,
                    final_price=1000),
            Booking(client_id=booked.id, master_id=m1.id, service_id=sv1.id,
                    start_time=past + timedelta(days=10), end_time=past + timedelta(days=10, hours=1),
                    status=BookingStatus.PENDING),
        ])
        await db.commit()
        return SimpleNamespace(
            headers={"Authorization": f"Bearer {create_access_token(owner.id)}"},
            token=create_access_token(owner.id), salon_id=here.id,
            mine=mine.id, stranger=stranger.id, booked=booked.id)


async def _rows(db_session, model, salon_id, client_id) -> int:
    async with db_session() as db:
        return await db.scalar(select(func.count()).select_from(model).where(
            model.salon_id == salon_id, model.client_id == client_id))


async def _write_everything(client, w, client_id):
    base = f"/api/v1/loyalty/salon/{w.salon_id}/client/{client_id}"
    return [
        await client.post(f"/api/v1/business/my-salon/clients/{client_id}/notes",
                          params={"salon_id": w.salon_id}, headers=w.headers,
                          json={"text": "аллергия на лак"}),
        await client.post(f"{base}/status", headers=w.headers, json={"is_regular": True}),
        await client.post(f"{base}/personal-discount", headers=w.headers,
                          json={"discount_percent": 10}),
        await client.post(f"{base}/points", headers=w.headers, json={"amount": 50, "comment": ""}),
    ]


async def test_own_client_gets_notes_and_loyalty(client, db_session):
    w = await _salon_with_people(db_session)
    codes = [r.status_code for r in await _write_everything(client, w, w.mine)]
    assert codes == [201, 200, 200, 200], codes
    assert await _rows(db_session, ClientNote, w.salon_id, w.mine) == 1
    assert await _rows(db_session, ClientLoyalty, w.salon_id, w.mine) == 1


async def test_stranger_gets_404_and_no_rows(client, db_session):
    """Человек с визитом в ДРУГОМ салоне: для этого салона он никто."""
    w = await _salon_with_people(db_session)
    responses = await _write_everything(client, w, w.stranger)
    assert [r.status_code for r in responses] == [404] * 4, [r.text for r in responses]
    assert await _rows(db_session, ClientNote, w.salon_id, w.stranger) == 0
    assert await _rows(db_session, ClientLoyalty, w.salon_id, w.stranger) == 0


async def test_unknown_id_and_stranger_are_indistinguishable(client, db_session):
    w = await _salon_with_people(db_session)
    a = (await _write_everything(client, w, w.stranger))
    b = (await _write_everything(client, w, 10 ** 8))
    assert [(r.status_code, r.json()) for r in a] == [(r.status_code, r.json()) for r in b]


async def test_only_pending_booking_is_not_yet_a_client(client, db_session):
    """Правило вкладки «Клиенты»: клиент — после состоявшегося визита. Человек
    с одной ожидающей записью в списке не виден — и писать на него нельзя."""
    w = await _salon_with_people(db_session)
    codes = [r.status_code for r in await _write_everything(client, w, w.booked)]
    assert codes == [404] * 4, codes


async def test_client_card_shows_only_own_clients(client, db_session):
    w = await _salon_with_people(db_session)
    client.cookies.set("access_token", w.token)
    own = await client.get(f"/business/clients/{w.mine}", params={"salon_id": w.salon_id})
    assert own.status_code == 200 and "+79990171003" in own.text
    other = await client.get(f"/business/clients/{w.stranger}", params={"salon_id": w.salon_id})
    assert other.status_code == 404
    assert "+79990171004" not in other.text and "Чужой" not in other.text


async def test_clients_tab_lists_by_the_same_rule(client, db_session):
    from app.crm.tabs.clients import render_crm_tab

    w = await _salon_with_people(db_session)
    async with db_session() as db:
        salon = await db.get(Salon, w.salon_id)
        master_ids = list((await db.scalars(select(Master.id).where(Master.salon_id == salon.id))).all())
        html = await render_crm_tab(db, salon, [], master_ids)
    assert "+79990171003" in html
    assert "+79990171004" not in html and "+79990171005" not in html


# ── 3. Возврат по истёкшей подписке ──────────────────────────────────────────

def test_refund_after_expiry_does_not_move_the_end_forward():
    """Пример F1: подписка кончилась 31.12.2025, возврат 01.01.2026."""
    current = datetime(2025, 12, 31, tzinfo=timezone.utc)
    t = SimpleNamespace(subscription_expires_at=current, access_until=current)
    new = revoke_paid_period(t, months=1, at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert new <= current
    assert t.subscription_expires_at == t.access_until == new
    assert not has_access(t)


def test_refund_on_live_subscription_still_closes_access_at_once():
    """Обычный случай: подписка ещё действует, а вычтенный срок уже в прошлом —
    доступ обязан закрыться сразу, как и до правки."""
    now = datetime.now(timezone.utc)
    t = SimpleNamespace(subscription_expires_at=now + timedelta(days=1),
                        access_until=now + timedelta(days=1))
    new = revoke_paid_period(t, months=12)
    assert new < now
    assert not has_access(t)


def test_refund_on_live_subscription_keeps_the_rest():
    """И наоборот: если после вычета срок ещё впереди, он остаётся ровно таким."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = now + timedelta(days=100)
    t = SimpleNamespace(subscription_expires_at=end, access_until=end)
    assert revoke_paid_period(t, months=1, at=now) == end - timedelta(days=30)


async def test_refund_message_says_closed_instead_of_a_past_date(monkeypatch):
    """Срок после отката в прошлом: «доступ до <прошлая дата>» читалось бы как
    ошибка, поэтому уведомление говорит прямо, что доступ закрыт."""
    import app.services.notifications as notifications
    from app.models.models import PaymentKind, PaymentStatus
    from app.services.refunds import apply_refund

    sent = []

    async def fake_notify(db, target, text):
        sent.append(text)

    monkeypatch.setattr(notifications, "notify_subscription", fake_notify)
    now = datetime.now(timezone.utc)
    target = SimpleNamespace(subscription_expires_at=now - timedelta(days=5),
                             access_until=now - timedelta(days=5),
                             subscription_status=None, auto_renew=True, recurring_token="t")
    payment = SimpleNamespace(id=1, status=PaymentStatus.SUCCEEDED, kind=PaymentKind.RECURRENT,
                              months=1, amount=1500, raw_payload=None)
    text = await apply_refund(None, payment, target, "business")
    assert target.subscription_expires_at <= now - timedelta(days=5)
    assert "доступ по тарифу закрыт" in text and "теперь до" not in text
    assert sent == [text]
