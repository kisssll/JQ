"""Зарплата/себестоимость за ДИАПАЗОН месяцев (вкладки «Зарплаты»/«Себестоимость»).

Оклад = месячная ставка × число месяцев диапазона; % от выручки — за весь
диапазон; бонусы/штрафы — все, чей period_month попал в диапазон. Пропорций
внутри месяца нет (выбор Артёма — «диапазон месяцев»).
"""
from datetime import datetime, timedelta

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, Master, Service, Booking, BookingStatus,
    MasterPayrollSettings, PayrollAdjustment,
)
from app.services.payroll_service import PayrollService


async def _setup(db_session):
    async with db_session() as db:
        owner = User(phone="+79997770001", full_name="Owner",
                     hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        muser = User(phone="+79997770002", full_name="Master",
                     hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        client = User(phone="+79997770003", full_name="Client",
                      hashed_password=get_password_hash("Testpass1"), role=UserRole.CLIENT)
        db.add_all([owner, muser, client])
        await db.commit()
        for u in (owner, muser, client):
            await db.refresh(u)

        salon = Salon(name="S", address="a", phone="+70000000700",
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

        # ставка: оклад 10000/мес, 10% от выручки
        db.add(MasterPayrollSettings(master_id=master.id, base_salary=10000, commission_percent=10.0))
        # выручка: январь 1500 (CONFIRMED), февраль 2500 (COMPLETED)
        jan = datetime(2025, 1, 15, 12, 0)
        feb = datetime(2025, 2, 15, 12, 0)
        db.add_all([
            Booking(client_id=client.id, master_id=master.id, service_id=svc.id,
                    start_time=jan, end_time=jan + timedelta(hours=1),
                    status=BookingStatus.CONFIRMED, final_price=1500),
            Booking(client_id=client.id, master_id=master.id, service_id=svc.id,
                    start_time=feb, end_time=feb + timedelta(hours=1),
                    status=BookingStatus.COMPLETED, final_price=2500),
        ])
        # бонус +1000 за февраль
        db.add(PayrollAdjustment(master_id=master.id, period_month=datetime(2025, 2, 1),
                                 amount=1000, reason="премия", created_by_id=owner.id))
        await db.commit()
        return master.id


async def test_payroll_range_spans_two_months(db_session):
    master_id = await _setup(db_session)
    async with db_session() as db:
        r = await PayrollService.calculate_payroll_range(
            db, master_id=master_id,
            month_from=datetime(2025, 1, 1), month_to=datetime(2025, 2, 1),
        )
    assert r["num_months"] == 2
    assert r["revenue"] == 4000                 # 1500 + 2500 за оба месяца
    assert r["base_salary_monthly"] == 10000
    assert r["base_salary"] == 20000            # ставка × 2 месяца
    assert r["commission"] == 400               # 10% от 4000
    assert r["adjustments_sum"] == 1000         # февральский бонус попал в диапазон
    assert r["total"] == 21400                  # 20000 + 400 + 1000


async def test_range_single_month_matches_per_month(db_session):
    master_id = await _setup(db_session)
    async with db_session() as db:
        rng = await PayrollService.calculate_payroll_range(
            db, master_id=master_id,
            month_from=datetime(2025, 1, 1), month_to=datetime(2025, 1, 1),
        )
        one = await PayrollService.calculate_payroll(db, master_id=master_id, period_month=datetime(2025, 1, 1))
    # диапазон из одного месяца = помесячный расчёт
    assert rng["num_months"] == 1
    assert rng["revenue"] == one["revenue"] == 1500
    assert rng["total"] == one["total"] == 10150   # 10000 + 150, февральский бонус НЕ входит


async def test_range_swaps_reversed_bounds(db_session):
    master_id = await _setup(db_session)
    async with db_session() as db:
        # перепутанные from/to не должны ломать расчёт
        r = await PayrollService.calculate_payroll_range(
            db, master_id=master_id,
            month_from=datetime(2025, 2, 1), month_to=datetime(2025, 1, 1),
        )
    assert r["num_months"] == 2 and r["revenue"] == 4000
