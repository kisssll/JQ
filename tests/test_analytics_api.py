# tests/test_analytics_api.py
"""Гранулярная аналитика салона (день/неделя/месяц/год + свой период):
агрегация по бакетам, нулевые дни в графике, топ услуг за период, права
доступа (view_finances), защита от неадекватно широкого диапазона."""
from datetime import datetime, timedelta

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, Master, Service,
    Booking, BookingStatus,
)


async def _login(client, phone, password="Testpass1"):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": password})
    client.cookies.set("access_token", r.json()["access_token"])


async def _salon_owner_master_service(db_session, *, owner_phone, salon_phone, view_finances=True):
    async with db_session() as db:
        salon = Salon(name="S", address="a", phone=salon_phone,
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow")
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        owner = User(phone=owner_phone, full_name="Owner",
                     hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        muser = User(phone=salon_phone[:-1] + "1", full_name="Master",
                     hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        db.add_all([owner, muser])
        await db.commit()
        await db.refresh(owner)
        await db.refresh(muser)
        salon.creator_id = owner.id
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=False,
                           permissions={"manage_salon": True, "view_finances": view_finances},
                           is_active=True))
        master = Master(salon_id=salon.id, user_id=muser.id, specialization="Барбер")
        db.add(master)
        await db.commit()
        await db.refresh(master)
        svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)
        return salon.id, master.id, svc.id


async def _client_user(db_session, phone):
    async with db_session() as db:
        cu = User(phone=phone, full_name="Client",
                  hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        db.add(cu)
        await db.commit()
        await db.refresh(cu)
        return cu.id


async def test_requires_auth(client, db_session):
    salon_id, _, _ = await _salon_owner_master_service(
        db_session, owner_phone="+79994440001", salon_phone="+70000000101")
    r = await client.get(f"/api/v1/business/my-salon/analytics?salon_id={salon_id}")
    assert r.status_code == 401


async def test_requires_view_finances_permission(client, db_session):
    salon_id, _, _ = await _salon_owner_master_service(
        db_session, owner_phone="+79994440002", salon_phone="+70000000102", view_finances=False)
    await _login(client, "+79994440002")
    r = await client.get(f"/api/v1/business/my-salon/analytics?salon_id={salon_id}")
    assert r.status_code == 403


async def test_daily_series_aggregates_and_fills_gaps(client, db_session):
    """Два дня с бронями и один пустой день внутри диапазона — пустой день
    должен прийти нулём, а не выпасть из серии."""
    salon_id, master_id, svc_id = await _salon_owner_master_service(
        db_session, owner_phone="+79994440003", salon_phone="+70000000103")
    client_id = await _client_user(db_session, "+79994440004")

    today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    day0 = today - timedelta(days=2)  # будет с бронью
    day1 = today - timedelta(days=1)  # пустой день (проверяем нулевое заполнение)
    day2 = today  # с бронью + отменённая (не должна попасть в выручку)

    async with db_session() as db:
        db.add_all([
            Booking(client_id=client_id, master_id=master_id, service_id=svc_id,
                    start_time=day0, end_time=day0 + timedelta(minutes=60),
                    status=BookingStatus.COMPLETED, final_price=1000),
            Booking(client_id=client_id, master_id=master_id, service_id=svc_id,
                    start_time=day2, end_time=day2 + timedelta(minutes=60),
                    status=BookingStatus.CONFIRMED, final_price=2000),
            Booking(client_id=client_id, master_id=master_id, service_id=svc_id,
                    start_time=day2 + timedelta(hours=1), end_time=day2 + timedelta(hours=2),
                    status=BookingStatus.CANCELLED, final_price=5000),
        ])
        await db.commit()

    await _login(client, "+79994440003")
    r = await client.get(
        "/api/v1/business/my-salon/analytics",
        params={
            "salon_id": salon_id, "granularity": "day",
            "date_from": day0.date().isoformat(), "date_to": day2.date().isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["granularity"] == "day"
    points = {p["period_start"]: p for p in data["points"]}
    assert len(points) == 3  # day0, day1 (пустой), day2 — все включены

    assert points[day0.date().isoformat()]["revenue"] == 1000
    assert points[day1.date().isoformat()]["revenue"] == 0
    assert points[day1.date().isoformat()]["bookings_total"] == 0
    assert points[day2.date().isoformat()]["revenue"] == 2000  # отменённая бронь не в выручке
    assert points[day2.date().isoformat()]["bookings_total"] == 2  # но в счётчике всех броней — да

    assert data["summary"]["total_revenue"] == 3000
    assert data["summary"]["total_bookings"] == 3
    assert data["summary"]["avg_check"] == 3000 // 2  # только 2 оплачиваемые брони

    # Топ услуг за период — включает только оплачиваемые статусы
    assert data["top_services"][0]["name"] == "Стрижка"
    assert data["top_services"][0]["revenue"] == 3000


async def test_day_operations_excludes_cancelled(client, db_session):
    salon_id, master_id, svc_id = await _salon_owner_master_service(
        db_session, owner_phone="+79994440005", salon_phone="+70000000105")
    client_id = await _client_user(db_session, "+79994440006")

    day = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    async with db_session() as db:
        db.add_all([
            Booking(client_id=client_id, master_id=master_id, service_id=svc_id,
                    start_time=day, end_time=day + timedelta(minutes=60),
                    status=BookingStatus.COMPLETED, final_price=1500),
            Booking(client_id=client_id, master_id=master_id, service_id=svc_id,
                    start_time=day + timedelta(hours=2), end_time=day + timedelta(hours=3),
                    status=BookingStatus.CANCELLED, final_price=1500),
        ])
        await db.commit()

    await _login(client, "+79994440005")
    r = await client.get(
        "/api/v1/business/my-salon/analytics/day",
        params={"salon_id": salon_id, "date": day.date().isoformat()},
    )
    assert r.status_code == 200, r.text
    ops = r.json()["operations"]
    assert len(ops) == 1
    assert ops[0]["status"] == "completed"


async def test_range_too_wide_for_granularity_rejected(client, db_session):
    salon_id, _, _ = await _salon_owner_master_service(
        db_session, owner_phone="+79994440007", salon_phone="+70000000107")
    await _login(client, "+79994440007")

    today = datetime.now().date()
    r = await client.get(
        "/api/v1/business/my-salon/analytics",
        params={
            "salon_id": salon_id, "granularity": "day",
            "date_from": (today - timedelta(days=3 * 365)).isoformat(),
            "date_to": today.isoformat(),
        },
    )
    assert r.status_code == 400


async def test_default_range_used_when_not_provided(client, db_session):
    """Без date_from/date_to подставляется дефолт под гранулярность (не 500/пусто)."""
    salon_id, _, _ = await _salon_owner_master_service(
        db_session, owner_phone="+79994440008", salon_phone="+70000000108")
    await _login(client, "+79994440008")

    r = await client.get(
        "/api/v1/business/my-salon/analytics",
        params={"salon_id": salon_id, "granularity": "month"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["points"]) == 12  # последние 12 месяцев по дефолту
