# tests/test_account_departure.py
"""Удаление аккаунта и удаление карточки мастера (решение 0016, п. 1).

Воспроизведено 27.10 на стенде: «Удалить аккаунт» ставил users.is_active=False
и больше ничего — карточка мастера и салон оставались в каталоге, к ушедшему
человеку можно было записаться. Здесь проверяется вся цепочка: каталог,
страница мастера, запись, отмена будущих записей с уведомлением клиенту,
админка; и отдельно — проверка в выборках, которая держит, даже если цепочка
не отработала (старые записи в базе).

Телефоны стендов — с префиксом +7955016…, чтобы ни с чем не пересечься.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.services.notifications as notif
from app.core.security import get_password_hash
from app.models.models import (
    AdminAudit, Booking, BookingStatus, Master, Salon, SalonMember, SalonModerationStatus,
    SalonPanelMode, SalonRole, SalonSubscriptionStatus, Service, User, UserRole,
    OWNER_DEFAULT_PERMISSIONS,
)
from app.utils.timezone import get_salon_time

PW = "Bizpass1"
TZ = "Asia/Tomsk"
_ALL_DAY = '{"mon":"00:00-23:59","tue":"00:00-23:59","wed":"00:00-23:59",' \
           '"thu":"00:00-23:59","fri":"00:00-23:59","sat":"00:00-23:59","sun":"00:00-23:59"}'


@pytest.fixture()
def sent(monkeypatch):
    """Перехват очереди уведомлений: [(задача, аргументы)]."""
    queued: list[tuple] = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            queued.append((fn, args))

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr(notif, "get_arq_pool", fake_pool)
    monkeypatch.setattr(notif.settings, "TG_NOTIFY_ENABLED", True)
    return queued


def _tg_to(sent, chat_id) -> list[str]:
    return [args[1] for fn, args in sent if fn == "send_tg_message" and args[0] == chat_id]


async def _stand(db_session, *, phone: str, name: str, co_owner_phone: str | None = None):
    """Соло-мастер: владелец салона сам себе мастер. Салон опубликован и
    оплачен — к нему реально можно записаться. Возвращает словарь id."""
    async with db_session() as db:
        owner = User(phone=phone, full_name="Уходящая", hashed_password=get_password_hash(PW),
                     role=UserRole.BUSINESS, tg_chat_id=int(phone[-6:]))
        client = User(phone=phone[:-1] + "9", full_name="Клиентка",
                      hashed_password=get_password_hash(PW), role=UserRole.CLIENT,
                      tg_chat_id=int(phone[-6:]) + 7)
        db.add_all([owner, client])
        await db.flush()
        salon = Salon(
            name=name, address="Томск, ул. Ленина, 1", city="Томск", phone="+73822016000",
            latitude=56.5, longitude=84.9, timezone=TZ, working_hours=_ALL_DAY,
            creator_id=owner.id, is_active=True, panel_mode=SalonPanelMode.SOLO,
            moderation_status=SalonModerationStatus.APPROVED,
            subscription_status=SalonSubscriptionStatus.ACTIVE, business_tier="lite",
            auto_renew=True, recurring_token="rebill-016",
            access_until=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(salon)
        await db.flush()
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS),
                           is_active=True))
        ids = {}
        if co_owner_phone:
            co = User(phone=co_owner_phone, full_name="Совладелица",
                      hashed_password=get_password_hash(PW), role=UserRole.BUSINESS,
                      tg_chat_id=int(co_owner_phone[-6:]))
            db.add(co)
            await db.flush()
            db.add(SalonMember(salon_id=salon.id, user_id=co.id, role=SalonRole.OWNER,
                               is_creator=False, permissions=dict(OWNER_DEFAULT_PERMISSIONS),
                               is_active=True))
            ids["co_owner"] = co.id
        master = Master(user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
                        is_active=True)
        db.add(master)
        await db.flush()
        service = Service(master_id=master.id, name="Маникюр", price=1500,
                          duration_minutes=60, is_active=True)
        db.add(service)
        await db.commit()
        ids.update(owner=owner.id, client=client.id, salon=salon.id, master=master.id,
                   service=service.id, owner_chat=owner.tg_chat_id,
                   client_chat=client.tg_chat_id, owner_phone=owner.phone,
                   client_phone=client.phone)
        return ids


async def _login(client, phone):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": PW})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])


def _slot(days_ahead: int = 2) -> datetime:
    """Полдень через несколько дней по часам салона — заведомо рабочее время."""
    return (get_salon_time(TZ).replace(tzinfo=None) + timedelta(days=days_ahead)).replace(
        hour=12, minute=0, second=0, microsecond=0)


async def _try_book(client, ids, start: datetime):
    await _login(client, ids["client_phone"])
    return await client.post("/api/v1/bookings", json={
        "master_id": ids["master"], "service_id": ids["service"],
        "start_time": start.isoformat(),
    })


async def _add_booking(db_session, ids, start: datetime, status=BookingStatus.CONFIRMED) -> int:
    async with db_session() as db:
        b = Booking(client_id=ids["client"], master_id=ids["master"], service_id=ids["service"],
                    start_time=start, end_time=start + timedelta(hours=1), status=status,
                    final_price=1500)
        db.add(b)
        await db.commit()
        return b.id


async def _status(db_session, booking_id) -> BookingStatus:
    async with db_session() as db:
        return (await db.get(Booking, booking_id)).status


# ── 1. Удаление аккаунта уводит цепочку ─────────────────────────────────────

async def test_deleting_account_takes_solo_master_out_of_catalog_and_booking(
    client, db_session, sent,
):
    ids = await _stand(db_session, phone="+79550160001", name="Студия Ухода016")

    # Контроль: до удаления всё живое — иначе проверки ниже ничего не доказывают.
    assert "Студия Ухода016" in (await client.get("/salons")).text
    assert (await client.get(f"/masters/{ids['master']}")).status_code == 200
    created = await _try_book(client, ids, _slot())
    assert created.status_code == 201, created.text
    booking_id = created.json()["id"]
    sent.clear()

    await _login(client, ids["owner_phone"])
    r = await client.post("/api/v1/users/me/delete-form", data={"password": PW})
    assert r.status_code == 302 and "account_deleted=1" in r.headers["location"]

    # Каталог, страница мастера, страница салона
    assert "Студия Ухода016" not in (await client.get("/salons")).text
    assert (await client.get(f"/masters/{ids['master']}")).status_code == 404
    assert "не найден" in (await client.get(f"/salons/{ids['salon']}")).text.lower()

    # Запись: ни API, ни список свободных окон
    refused = await _try_book(client, ids, _slot(3))
    assert refused.status_code == 403, refused.text
    slots = await client.get(f"/api/v1/bookings/available/{ids['master']}",
                             params={"date": _slot(3).date().isoformat(),
                                     "service_id": ids["service"]})
    assert slots.json().get("slots") == []

    # Будущая запись отменена, клиент уведомлён с причиной, ушедшему — ничего
    assert await _status(db_session, booking_id) == BookingStatus.CANCELLED
    to_client = _tg_to(sent, ids["client_chat"])
    assert len(to_client) == 1 and "больше не принимает" in to_client[0]
    assert _tg_to(sent, ids["owner_chat"]) == []

    # Всё мягко: строки на месте, флаги погашены, автопродление выключено, аудит есть
    async with db_session() as db:
        owner = await db.get(User, ids["owner"])
        salon = await db.get(Salon, ids["salon"])
        master = await db.get(Master, ids["master"])
        assert owner is not None and owner.is_active is False
        assert salon is not None and salon.is_active is False and salon.is_deleted is True
        assert salon.auto_renew is False and salon.recurring_token is None
        assert salon.access_until is not None  # оплаченный период не тронут
        assert master is not None and master.is_active is False
        actions = set((await db.execute(
            select(AdminAudit.action).where(AdminAudit.actor_id == ids["owner"])
        )).scalars().all())
        assert {"delete_own_account", "account_deleted_salon_closed"} <= actions


async def test_visit_in_progress_stays_upcoming_today_is_cancelled(client, db_session, sent):
    """Идущий визит не трогаем; не начавшиеся — отменяем, сегодняшние тоже."""
    ids = await _stand(db_session, phone="+79550160002", name="Студия Сегодня016")
    now = get_salon_time(TZ).replace(tzinfo=None, second=0, microsecond=0)
    in_progress = await _add_booking(db_session, ids, now - timedelta(minutes=30))
    later = await _add_booking(db_session, ids, now + timedelta(minutes=90),
                               status=BookingStatus.PENDING)
    done = await _add_booking(db_session, ids, now - timedelta(days=2),
                              status=BookingStatus.COMPLETED)

    await _login(client, ids["owner_phone"])
    await client.post("/api/v1/users/me/delete-form", data={"password": PW})

    assert await _status(db_session, in_progress) == BookingStatus.CONFIRMED
    assert await _status(db_session, later) == BookingStatus.CANCELLED
    assert await _status(db_session, done) == BookingStatus.COMPLETED


async def test_co_owned_salon_keeps_working_when_creator_leaves(client, db_session, sent):
    """Салон с живым совладельцем остаётся; уходит карточка ушедшего, его
    записи и автопродление с его карты. Совладелица узнаёт про тариф."""
    ids = await _stand(db_session, phone="+79550160003", name="Студия Вдвоём016",
                       co_owner_phone="+79550160013")
    booking_id = await _add_booking(db_session, ids, _slot())

    await _login(client, ids["owner_phone"])
    await client.post("/api/v1/users/me/delete-form", data={"password": PW})

    async with db_session() as db:
        salon = await db.get(Salon, ids["salon"])
        assert salon.is_active is True and salon.is_deleted is False
        assert salon.auto_renew is False
        assert (await db.get(Master, ids["master"])).is_active is False
    assert await _status(db_session, booking_id) == BookingStatus.CANCELLED
    co_msgs = [m for m in _tg_to(sent, 160013) if "автопродление" in m]
    assert len(co_msgs) == 1


# ── 3. Проверка в выборках: старые данные с отключённым аккаунтом ─────────────

async def test_disabled_account_is_hidden_even_if_card_and_salon_flags_are_active(
    client, db_session,
):
    """Цепочка не отработала (или человека отключил модератор): карточка и
    салон в базе «активны», аккаунт — нет. Клиент всё равно не видит и не
    записывается — условие стоит в выборках."""
    ids = await _stand(db_session, phone="+79550160004", name="Студия Старая016")
    assert "Студия Старая016" in (await client.get("/salons")).text  # контроль

    async with db_session() as db:
        (await db.get(User, ids["owner"])).is_active = False
        await db.commit()

    assert "Студия Старая016" not in (await client.get("/salons")).text
    assert (await client.get(f"/masters/{ids['master']}")).status_code == 404
    assert "не найден" in (await client.get(f"/salons/{ids['salon']}")).text.lower()
    refused = await _try_book(client, ids, _slot())
    assert refused.status_code == 403, refused.text
    slots = await client.get(f"/api/v1/bookings/available/{ids['master']}",
                             params={"date": _slot().date().isoformat(),
                                     "service_id": ids["service"]})
    assert slots.json().get("slots") == []


# ── 2. «Удалить карточку мастера» ────────────────────────────────────────────

async def test_deleting_master_card_keeps_account_and_card_can_be_recreated(
    client, db_session, sent,
):
    ids = await _stand(db_session, phone="+79550160005", name="Студия Карточки016")
    booking_id = await _add_booking(db_session, ids, _slot())
    await _login(client, ids["owner_phone"])

    panel = f"/business/dashboard?salon_id={ids['salon']}&tab=employees"
    page = (await client.get(panel)).text
    assert "Удалить карточку мастера" in page and "отменятся будущие записи к вам: 1" in page.lower()

    r = await client.post("/api/v1/business/my-salon/master-card/delete",
                          data={"salon_id": ids["salon"], "confirm": "1"})
    assert r.status_code == 302 and "card_deleted=1" in r.headers["location"]

    # Карточки нет для клиентов, запись отменена с уведомлением
    async with db_session() as db:
        assert (await db.get(Master, ids["master"])).is_active is False
        assert (await db.get(User, ids["owner"])).is_active is True
        assert (await db.get(Salon, ids["salon"])).is_active is True
    assert await _status(db_session, booking_id) == BookingStatus.CANCELLED
    assert any("больше не принимает" in m for m in _tg_to(sent, ids["client_chat"]))
    assert (await client.get(f"/masters/{ids['master']}")).status_code == 404

    # Аккаунт рабочий: та же сессия открывает панель, и там снова «создать»
    page = (await client.get(panel)).text
    assert "Создать мою карточку мастера" in page
    assert "Удалить карточку мастера" not in page

    r = await client.post("/api/v1/business/my-salon/master-card",
                          data={"salon_id": ids["salon"], "specialization": "Педикюр"})
    assert r.status_code == 302
    async with db_session() as db:
        cards = (await db.execute(
            select(Master).where(Master.user_id == ids["owner"])
        )).scalars().all()
        assert [(c.id, c.is_active, c.specialization) for c in cards] == [
            (ids["master"], True, "Педикюр")]
    assert (await client.get(f"/masters/{ids['master']}")).status_code == 200


async def test_deleting_master_card_requires_confirmation(client, db_session, sent):
    ids = await _stand(db_session, phone="+79550160006", name="Студия Галочки016")
    booking_id = await _add_booking(db_session, ids, _slot())
    await _login(client, ids["owner_phone"])

    r = await client.post("/api/v1/business/my-salon/master-card/delete",
                          data={"salon_id": ids["salon"]})
    assert "card_delete_unconfirmed" in r.headers["location"]
    async with db_session() as db:
        assert (await db.get(Master, ids["master"])).is_active is True
    assert await _status(db_session, booking_id) == BookingStatus.CONFIRMED


# ── 4. Админка ───────────────────────────────────────────────────────────────

async def test_admin_panel_does_not_show_disabled_person_as_active(client, db_session):
    """Отключённый человек: салон не в «Действующих», карточка «не принимает».
    Проверяем на старых данных (флаги салона и карточки «активны») — это и
    было расхождение, которое видел владелец."""
    ids = await _stand(db_session, phone="+79550160007", name="Студия Админки016")
    async with db_session() as db:
        (await db.get(User, ids["owner"])).is_active = False
        db.add(User(phone="+79550160077", full_name="Модератор",
                    hashed_password=get_password_hash(PW), role=UserRole.ADMIN,
                    is_senior_admin=True))
        await db.commit()
    await _login(client, "+79550160077")

    html = (await client.get("/admin?tab=salons")).text
    assert "Действующие (0)" in html
    assert "владелец отключён" in html
    assert "карточка: не принимает" in html
    assert "карточка: принимает" not in html
