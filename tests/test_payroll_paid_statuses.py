# tests/test_payroll_paid_statuses.py
"""Зарплата мастера должна учитывать выручку по CONFIRMED-броням, не только
по отмеченным «Пришёл» (COMPLETED) — иначе цифры в «Обзоре»/«Аналитике»
(CONFIRMED+COMPLETED) и в «Зарплатах»/«Себестоимости» расходятся за один и
тот же период (см. app/models/models.py: PAID_BOOKING_STATUSES)."""
from datetime import datetime, timedelta

from app.core.security import get_password_hash
from app.models.models import User, UserRole, Salon, Master, Service, Booking, BookingStatus
from app.services.payroll_service import PayrollService


async def test_payroll_revenue_counts_confirmed_not_only_completed(db_session):
    async with db_session() as db:
        owner = User(phone="+79998880001", full_name="Owner",
                    hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        muser = User(phone="+79998880002", full_name="Master",
                    hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        client_user = User(phone="+79998880003", full_name="Client",
                    hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        db.add_all([owner, muser, client_user])
        await db.commit()
        await db.refresh(owner)
        await db.refresh(muser)
        await db.refresh(client_user)

        salon = Salon(name="S", address="a", phone="+70000000600",
                      latitude=1.0, longitude=1.0, timezone="Europe/Moscow", creator_id=owner.id)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        master = Master(salon_id=salon.id, user_id=muser.id, specialization="Барбер")
        db.add(master)
        await db.commit()
        await db.refresh(master)

        svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(svc)
        await db.commit()
        await db.refresh(svc)

        this_month = datetime.now().replace(day=15, hour=12, minute=0, second=0, microsecond=0)
        db.add_all([
            Booking(client_id=client_user.id, master_id=master.id, service_id=svc.id,
                    start_time=this_month, end_time=this_month + timedelta(minutes=60),
                    status=BookingStatus.CONFIRMED, final_price=1500),
            Booking(client_id=client_user.id, master_id=master.id, service_id=svc.id,
                    start_time=this_month + timedelta(hours=1), end_time=this_month + timedelta(hours=2),
                    status=BookingStatus.COMPLETED, final_price=2000),
            Booking(client_id=client_user.id, master_id=master.id, service_id=svc.id,
                    start_time=this_month + timedelta(hours=3), end_time=this_month + timedelta(hours=4),
                    status=BookingStatus.PENDING, final_price=3000),
            Booking(client_id=client_user.id, master_id=master.id, service_id=svc.id,
                    start_time=this_month + timedelta(hours=5), end_time=this_month + timedelta(hours=6),
                    status=BookingStatus.CANCELLED, final_price=4000),
        ])
        await db.commit()

        result = await PayrollService.calculate_payroll(db, master_id=master.id, period_month=this_month)
        # CONFIRMED (1500) + COMPLETED (2000) = 3500; PENDING и CANCELLED не считаются
        assert result["revenue"] == 3500
