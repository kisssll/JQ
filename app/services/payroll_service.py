# app/services/payroll_service.py
"""Зарплата мастера: оклад + % от выручки + ручные бонусы/штрафы.
Себестоимость (COGS) — из журнала складских списаний (InventoryMovement)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Booking, MasterPayrollSettings, PayrollAdjustment,
    InventoryMovement, InventoryMovementType, InventoryItem, PAID_BOOKING_STATUSES,
)


class PayrollError(Exception):
    """Бизнес-ошибка зарплатного модуля. message — текст для пользователя, status — HTTP-код."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _month_bounds(period_month: datetime) -> tuple[datetime, datetime]:
    start = period_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1))
    return start, end


def _range_bounds(month_from: datetime, month_to: datetime) -> tuple[datetime, datetime, int]:
    """Границы [start, end) по диапазону месяцев ВКЛЮЧИТЕЛЬНО + число месяцев.
    from > to — молча меняем местами (устойчиво к перепутанным полям формы)."""
    a = month_from.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    b = month_to.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if a > b:
        a, b = b, a
    start = a
    end = _month_bounds(b)[1]
    num_months = (b.year - a.year) * 12 + (b.month - a.month) + 1
    return start, end, num_months


class PayrollService:
    @staticmethod
    async def calculate_payroll(db: AsyncSession, *, master_id: int, period_month: datetime) -> dict:
        """Итоговый расчёт зарплаты мастера за месяц: оклад + % от выручки + бонусы/штрафы."""
        start, end = _month_bounds(period_month)

        settings = (await db.execute(
            select(MasterPayrollSettings).where(MasterPayrollSettings.master_id == master_id)
        )).scalar_one_or_none()
        base_salary = settings.base_salary if settings else 0
        commission_percent = settings.commission_percent if settings else 0.0

        revenue_result = await db.execute(
            select(func.coalesce(func.sum(Booking.final_price), 0)).where(
                Booking.master_id == master_id,
                Booking.start_time >= start, Booking.start_time < end,
                Booking.status.in_(PAID_BOOKING_STATUSES),
            )
        )
        revenue = revenue_result.scalar() or 0
        commission = int(revenue * commission_percent / 100)

        adjustments = (await db.execute(
            select(PayrollAdjustment).where(
                PayrollAdjustment.master_id == master_id,
                PayrollAdjustment.period_month == start,
            ).order_by(PayrollAdjustment.created_at.desc())
        )).scalars().all()
        adjustments_sum = sum(a.amount for a in adjustments)

        return {
            "master_id": master_id,
            "period_month": start,
            "revenue": revenue,
            "base_salary": base_salary,
            "commission_percent": commission_percent,
            "commission": commission,
            "adjustments": adjustments,
            "adjustments_sum": adjustments_sum,
            "total": base_salary + commission + adjustments_sum,
        }

    @staticmethod
    async def calculate_payroll_range(
        db: AsyncSession, *, master_id: int, month_from: datetime, month_to: datetime,
    ) -> dict:
        """Расчёт зарплаты за ДИАПАЗОН месяцев (включительно). Оклад = месячная
        ставка × число месяцев; % от выручки за весь диапазон; бонусы/штрафы —
        все, чей period_month попадает в диапазон. Пропорций внутри месяца нет."""
        start, end, num_months = _range_bounds(month_from, month_to)

        settings = (await db.execute(
            select(MasterPayrollSettings).where(MasterPayrollSettings.master_id == master_id)
        )).scalar_one_or_none()
        base_salary_monthly = settings.base_salary if settings else 0
        commission_percent = settings.commission_percent if settings else 0.0

        revenue = (await db.execute(
            select(func.coalesce(func.sum(Booking.final_price), 0)).where(
                Booking.master_id == master_id,
                Booking.start_time >= start, Booking.start_time < end,
                Booking.status.in_(PAID_BOOKING_STATUSES),
            )
        )).scalar() or 0
        commission = int(revenue * commission_percent / 100)

        adjustments = (await db.execute(
            select(PayrollAdjustment).where(
                PayrollAdjustment.master_id == master_id,
                PayrollAdjustment.period_month >= start,
                PayrollAdjustment.period_month < end,
            ).order_by(PayrollAdjustment.created_at.desc())
        )).scalars().all()
        adjustments_sum = sum(a.amount for a in adjustments)

        base_salary = base_salary_monthly * num_months
        return {
            "master_id": master_id,
            "month_from": start,
            "num_months": num_months,
            "revenue": revenue,
            "base_salary": base_salary,            # оклад за весь диапазон
            "base_salary_monthly": base_salary_monthly,  # месячная ставка (для модалки «Ставка»)
            "commission_percent": commission_percent,
            "commission": commission,
            "adjustments": adjustments,
            "adjustments_sum": adjustments_sum,
            "total": base_salary + commission + adjustments_sum,
        }

    @staticmethod
    async def set_settings(db: AsyncSession, *, master_id: int, base_salary: int, commission_percent: float) -> MasterPayrollSettings:
        """Создаёт/обновляет ставку мастера (оклад + %)."""
        if base_salary < 0 or commission_percent < 0:
            raise PayrollError("Оклад и процент не могут быть отрицательными")

        settings = (await db.execute(
            select(MasterPayrollSettings).where(MasterPayrollSettings.master_id == master_id)
        )).scalar_one_or_none()
        if settings:
            settings.base_salary = base_salary
            settings.commission_percent = commission_percent
        else:
            settings = MasterPayrollSettings(
                master_id=master_id, base_salary=base_salary, commission_percent=commission_percent,
            )
            db.add(settings)
        await db.commit()
        await db.refresh(settings)
        return settings

    @staticmethod
    async def add_adjustment(
        db: AsyncSession, *, master_id: int, amount: int, reason: str, period_month: datetime, actor,
    ) -> PayrollAdjustment:
        """Ручное начисление: amount > 0 — бонус, amount < 0 — штраф. reason обязателен."""
        if amount == 0:
            raise PayrollError("Сумма начисления не может быть нулевой")
        if not reason or not reason.strip():
            raise PayrollError("Укажите причину начисления")

        start, _end = _month_bounds(period_month)
        adjustment = PayrollAdjustment(
            master_id=master_id, period_month=start, amount=amount,
            reason=reason.strip(), created_by_id=actor.id,
        )
        db.add(adjustment)
        await db.commit()
        await db.refresh(adjustment)
        return adjustment

    @staticmethod
    async def calculate_cogs(
        db: AsyncSession, *, booking_id: Optional[int] = None,
        master_id: Optional[int] = None, period_month: Optional[datetime] = None,
    ) -> int:
        """Себестоимость (COGS): сумма фактически списанных расходников.
        Либо по одной брони (booking_id), либо по мастеру за месяц (master_id + period_month)."""
        if booking_id is not None:
            result = await db.execute(
                select(func.coalesce(func.sum(InventoryMovement.delta * InventoryMovement.unit_cost_snapshot), 0))
                .where(InventoryMovement.booking_id == booking_id, InventoryMovement.type == InventoryMovementType.CONSUMPTION)
            )
            return abs(int(result.scalar() or 0))

        if master_id is not None and period_month is not None:
            start, end = _month_bounds(period_month)
            result = await db.execute(
                select(func.coalesce(func.sum(InventoryMovement.delta * InventoryMovement.unit_cost_snapshot), 0))
                .join(InventoryItem, InventoryItem.id == InventoryMovement.item_id)
                .where(
                    InventoryItem.master_id == master_id,
                    InventoryMovement.type == InventoryMovementType.CONSUMPTION,
                    InventoryMovement.created_at >= start, InventoryMovement.created_at < end,
                )
            )
            return abs(int(result.scalar() or 0))

        raise PayrollError("Укажите booking_id либо master_id+period_month")

    @staticmethod
    async def calculate_cogs_range(
        db: AsyncSession, *, master_id: int, month_from: datetime, month_to: datetime,
    ) -> int:
        """Себестоимость расходников мастера за ДИАПАЗОН месяцев (включительно)."""
        start, end, _ = _range_bounds(month_from, month_to)
        result = await db.execute(
            select(func.coalesce(func.sum(InventoryMovement.delta * InventoryMovement.unit_cost_snapshot), 0))
            .join(InventoryItem, InventoryItem.id == InventoryMovement.item_id)
            .where(
                InventoryItem.master_id == master_id,
                InventoryMovement.type == InventoryMovementType.CONSUMPTION,
                InventoryMovement.created_at >= start, InventoryMovement.created_at < end,
            )
        )
        return abs(int(result.scalar() or 0))
