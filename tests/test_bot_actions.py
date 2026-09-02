"""Действия из ботов: свои записи, отмена, отзыв после визита.

Логика общая для Telegram и MAX, поэтому проверяем её на уровне сервиса —
иначе пришлось бы дублировать одни и те же проверки под два мессенджера.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Review, Salon, SalonModerationStatus,
    Service, User, UserRole,
)
from app.services.bot_actions import (
    cancel_booking, review_already_left, save_review, upcoming_bookings,
)

_TZ = "Asia/Novosibirsk"


async def _scene(db, suffix: str, *, start_in=timedelta(days=1),
                 status=BookingStatus.CONFIRMED):
    master_user = User(phone=f"+7999100{suffix}", full_name="Мастер",
                       hashed_password=get_password_hash("Testpass1"),
                       role=UserRole.MASTER, is_active=True)
    client = User(phone=f"+7988100{suffix}", full_name="Клиент",
                  hashed_password=get_password_hash("Testpass1"),
                  role=UserRole.CLIENT, is_active=True)
    db.add_all([master_user, client])
    await db.commit()
    await db.refresh(master_user)
    await db.refresh(client)

    salon = Salon(name=f"Салон {suffix}", address="Т", phone="+70000000800",
                  latitude=1.0, longitude=1.0, city="Томск", is_active=True,
                  moderation_status=SalonModerationStatus.APPROVED, timezone=_TZ)
    db.add(salon)
    await db.commit()
    await db.refresh(salon)

    master = Master(user_id=master_user.id, salon_id=salon.id, specialization="м")
    db.add(master)
    await db.commit()
    await db.refresh(master)

    svc = Service(master_id=master.id, name="Стрижка", price=1500, duration_minutes=60)
    db.add(svc)
    await db.commit()
    await db.refresh(svc)

    start = datetime.now(timezone.utc).replace(tzinfo=None) + start_in
    booking = Booking(client_id=client.id, master_id=master.id, service_id=svc.id,
                      start_time=start, end_time=start + timedelta(minutes=60),
                      status=status)
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return client, booking, salon, master


# ── Мои записи ───────────────────────────────────────────────────────────────

async def test_upcoming_shows_future_active_bookings(db_session):
    async with db_session() as db:
        client, booking, salon, _ = await _scene(db, "01")
        rows = await upcoming_bookings(db, client.id)

    assert len(rows) == 1
    got_booking, got_salon, got_service, _ = rows[0]
    assert got_booking.id == booking.id
    assert got_salon.name == salon.name
    assert got_service.name == "Стрижка"


async def test_past_and_cancelled_are_hidden(db_session):
    """Список нужен, чтобы понять «когда я иду», а не как архив."""
    async with db_session() as db:
        client, _, _, _ = await _scene(db, "02", start_in=timedelta(days=-2))
        rows = await upcoming_bookings(db, client.id)
        assert rows == []

    async with db_session() as db:
        client2, _, _, _ = await _scene(db, "03", status=BookingStatus.CANCELLED)
        assert await upcoming_bookings(db, client2.id) == []


# ── Отмена ───────────────────────────────────────────────────────────────────

async def test_client_cancels_own_booking(db_session, monkeypatch):
    async def _noop(db, booking):
        return None

    monkeypatch.setattr("app.services.notifications.notify_booking_cancelled", _noop)

    async with db_session() as db:
        client, booking, _, _ = await _scene(db, "04")
        ok, text = await cancel_booking(db, client.id, booking.id)
        assert ok, text

        again = (await db.execute(
            select(Booking).where(Booking.id == booking.id)
        )).scalar_one()
        assert again.status == BookingStatus.CANCELLED


async def test_cannot_cancel_someone_elses_booking(db_session, monkeypatch):
    """И не подтверждаем самим ответом, что такая запись существует."""
    monkeypatch.setattr("app.services.notifications.notify_booking_cancelled",
                        lambda db, b: None)

    async with db_session() as db:
        _, booking, _, _ = await _scene(db, "05")
        stranger = User(phone="+79881009999", full_name="Чужой",
                        hashed_password=get_password_hash("Testpass1"),
                        role=UserRole.CLIENT, is_active=True)
        db.add(stranger)
        await db.commit()
        await db.refresh(stranger)

        ok, text = await cancel_booking(db, stranger.id, booking.id)
        assert not ok
        assert text == "Запись не найдена."

        again = (await db.execute(
            select(Booking).where(Booking.id == booking.id)
        )).scalar_one()
        assert again.status == BookingStatus.CONFIRMED


async def test_completed_booking_cannot_be_cancelled(db_session):
    async with db_session() as db:
        client, booking, _, _ = await _scene(
            db, "06", start_in=timedelta(hours=-3), status=BookingStatus.COMPLETED,
        )
        ok, text = await cancel_booking(db, client.id, booking.id)
        assert not ok and "состоялся" in text


# ── Отзыв после визита ───────────────────────────────────────────────────────

async def test_review_from_bot_is_verified_and_lifts_rating(db_session):
    """Отзыв по факту визита обязан идти подтверждённым — иначе он не влияет
    на рейтинг и не отличается от анонимного."""
    async with db_session() as db:
        client, booking, salon, master = await _scene(
            db, "07", start_in=timedelta(hours=-3), status=BookingStatus.COMPLETED,
        )
        ok, text = await save_review(db, user_id=client.id, booking_id=booking.id,
                                     rating=5, comment="Всё понравилось")
        assert ok, text

        review = (await db.execute(
            select(Review).where(Review.booking_id == booking.id)
        )).scalar_one()
        assert review.is_verified is True
        assert review.rating == 5

        again = (await db.execute(select(Salon).where(Salon.id == salon.id))).scalar_one()
        assert again.rating == 5.0


async def test_review_is_asked_only_once(db_session):
    async with db_session() as db:
        client, booking, _, _ = await _scene(
            db, "08", start_in=timedelta(hours=-3), status=BookingStatus.COMPLETED,
        )
        assert await review_already_left(db, client.id, booking.id) is False
        await save_review(db, user_id=client.id, booking_id=booking.id, rating=4)
        assert await review_already_left(db, client.id, booking.id) is True


async def test_cannot_review_a_stranger_booking(db_session):
    async with db_session() as db:
        _, booking, _, _ = await _scene(
            db, "09", start_in=timedelta(hours=-3), status=BookingStatus.COMPLETED,
        )
        stranger = User(phone="+79881008888", full_name="Чужой",
                        hashed_password=get_password_hash("Testpass1"),
                        role=UserRole.CLIENT, is_active=True)
        db.add(stranger)
        await db.commit()
        await db.refresh(stranger)

        ok, _ = await save_review(db, user_id=stranger.id,
                                  booking_id=booking.id, rating=1)
        assert not ok


# ── Опрос об удобстве сервиса ────────────────────────────────────────────────

async def test_service_rating_asks_owner_once(db_session, monkeypatch):
    """Опрос разовый: признак «уже спрашивали» — наличие NPS-обращения."""
    from datetime import datetime, timedelta, timezone

    from app.models.models import (
        NotifyChannel, SupportTopic, SalonMember, SalonRole,
        OWNER_DEFAULT_PERMISSIONS,
    )
    from app.services.support import create_request
    from app.tasks import SERVICE_RATING_AFTER_DAYS, ask_service_rating

    jobs = []

    class _Pool:
        async def enqueue_job(self, name, *args, **kw):
            jobs.append((name, args))

    async def _pool():
        return _Pool()

    monkeypatch.setattr("app.core.worker.get_arq_pool", _pool)
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: None)

    async with db_session() as db:
        owner = User(phone="+79990002001", full_name="Владелец",
                     hashed_password=get_password_hash("Bizpass1"),
                     role=UserRole.BUSINESS, is_active=True, tg_chat_id=770001)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        old_enough = datetime.now(timezone.utc) - timedelta(
            days=SERVICE_RATING_AFTER_DAYS + 1)
        salon = Salon(name="Давний", address="Т", phone="+70000000801",
                      latitude=1.0, longitude=1.0, city="Томск", is_active=True,
                      creator_id=owner.id, published_at=old_enough,
                      moderation_status=SalonModerationStatus.APPROVED)
        db.add(salon)
        await db.commit()
        owner_id = owner.id

    assert "asked:1" in await ask_service_rating({})
    assert jobs and jobs[0][0] == "send_service_rating_tg"

    # Ответил — больше не спрашиваем
    jobs.clear()
    async with db_session() as db:
        owner = await db.get(User, owner_id)
        await create_request(
            db, topic=SupportTopic.NPS, text="Оценка сервиса: 5/5",
            channel=NotifyChannel.TG, chat_id=770001, user=owner, rating=5,
            notify=False,
        )

    assert "asked:0" in await ask_service_rating({})
    assert jobs == []


async def test_fresh_salon_is_not_asked_yet(db_session, monkeypatch):
    """Спрашивать в день подключения бессмысленно — человек ещё не работал."""
    from datetime import datetime, timezone

    from app.tasks import ask_service_rating

    jobs = []

    class _Pool:
        async def enqueue_job(self, name, *args, **kw):
            jobs.append(name)

    async def _pool():
        return _Pool()

    monkeypatch.setattr("app.core.worker.get_arq_pool", _pool)

    async with db_session() as db:
        owner = User(phone="+79990002002", full_name="Владелец",
                     hashed_password=get_password_hash("Bizpass1"),
                     role=UserRole.BUSINESS, is_active=True, tg_chat_id=770002)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        db.add(Salon(name="Свежий", address="Т", phone="+70000000802",
                     latitude=1.0, longitude=1.0, city="Томск", is_active=True,
                     creator_id=owner.id, published_at=datetime.now(timezone.utc),
                     moderation_status=SalonModerationStatus.APPROVED))
        await db.commit()

    assert "asked:0" in await ask_service_rating({})
    assert jobs == []
