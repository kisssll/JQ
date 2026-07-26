# app/services/analytics_service.py
"""Гранулярная аналитика выручки/записей салона: агрегация SQL GROUP BY
date_trunc по произвольному периоду и гранулярности (день/неделя/месяц/год).

Используется JSON API (app/api/v1/endpoints/business.py: /my-salon/analytics)
и вкладкой «Аналитика» бизнес-панели (app/web/pages/business/tabs/analytics.py)
для первичной серверной отрисовки — оба потребителя дергают один и тот же код,
чтобы цифры никогда не расходились.
"""
from datetime import date as date_, datetime, time, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Booking, BookingStatus, Master, Service, User as UserModel, PAID_BOOKING_STATUSES

Granularity = Literal["day", "week", "month", "year"]

_PAID_STATUSES = PAID_BOOKING_STATUSES

# Верхняя граница числа точек в серии — страховка от неадекватно широкого
# диапазона (например «по дням за 10 лет» дал бы ~3650 баров).
MAX_POINTS = 400


def _shift_months(d: date_, months: int) -> date_:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    return date_(year, month + 1, 1)


class AnalyticsService:
    @staticmethod
    def default_range(granularity: Granularity) -> tuple[date_, date_]:
        """Разумный диапазон по умолчанию, если date_from/date_to не заданы —
        как в банковских приложениях: своя ширина окна под каждую гранулярность."""
        today = datetime.now().date()
        if granularity == "day":
            return today - timedelta(days=13), today  # последние 14 дней
        if granularity == "week":
            return today - timedelta(weeks=11), today  # последние 12 недель
        if granularity == "month":
            return _shift_months(today.replace(day=1), -11), today  # последние 12 месяцев
        return date_(today.year - 4, 1, 1), today  # последние 5 лет

    @staticmethod
    def _bucket_start(d: date_, granularity: Granularity) -> date_:
        if granularity == "day":
            return d
        if granularity == "week":
            return d - timedelta(days=d.weekday())
        if granularity == "month":
            return d.replace(day=1)
        return d.replace(month=1, day=1)

    @staticmethod
    def _next_bucket(d: date_, granularity: Granularity) -> date_:
        if granularity == "day":
            return d + timedelta(days=1)
        if granularity == "week":
            return d + timedelta(weeks=1)
        if granularity == "month":
            return _shift_months(d, 1)
        return d.replace(year=d.year + 1)

    @classmethod
    def _iter_buckets(cls, date_from: date_, date_to: date_, granularity: Granularity):
        cur = cls._bucket_start(date_from, granularity)
        end = cls._bucket_start(date_to, granularity)
        while cur <= end:
            yield cur
            cur = cls._next_bucket(cur, granularity)

    @classmethod
    async def revenue_series(
        cls,
        db: AsyncSession,
        master_ids: list[int],
        granularity: Granularity,
        date_from: date_,
        date_to: date_,
    ) -> list[dict]:
        """Выручка/записи по бакетам granularity в [date_from, date_to] включительно.
        Бакеты без записей включены с нулями, чтобы график не рвал ось."""
        if date_from > date_to:
            raise ValueError("date_from должна быть не позже date_to")

        buckets = list(cls._iter_buckets(date_from, date_to, granularity))
        if len(buckets) > MAX_POINTS:
            raise ValueError(
                f"Слишком широкий диапазон для группировки «{granularity}» ({len(buckets)} точек, "
                f"максимум {MAX_POINTS}) — выберите более крупную гранулярность или короче период."
            )

        points = {b: {"revenue": 0, "bookings_total": 0, "bookings_paid": 0} for b in buckets}
        if not master_ids:
            return [{"period_start": b.isoformat(), **points[b]} for b in buckets]

        range_start = datetime.combine(date_from, time.min)
        range_end = datetime.combine(cls._next_bucket(cls._bucket_start(date_to, granularity), granularity), time.min)

        trunc = func.date_trunc(granularity, Booking.start_time)
        rows = (
            await db.execute(
                select(
                    trunc.label("bucket"),
                    func.sum(func.coalesce(Booking.final_price, 0)).filter(
                        Booking.status.in_(_PAID_STATUSES)
                    ).label("revenue"),
                    func.count(Booking.id).label("total"),
                    func.count(Booking.id).filter(Booking.status.in_(_PAID_STATUSES)).label("paid"),
                )
                .where(
                    Booking.master_id.in_(master_ids),
                    Booking.start_time >= range_start,
                    Booking.start_time < range_end,
                )
                .group_by(trunc)
            )
        ).all()

        for bucket_dt, revenue, total, paid in rows:
            b = bucket_dt.date()
            if b in points:
                points[b] = {
                    "revenue": int(revenue or 0),
                    "bookings_total": int(total or 0),
                    "bookings_paid": int(paid or 0),
                }

        return [{"period_start": b.isoformat(), **points[b]} for b in buckets]

    @classmethod
    async def top_services(
        cls, db: AsyncSession, master_ids: list[int], date_from: date_, date_to: date_, limit: int = 5
    ) -> list[dict]:
        """Топ-N услуг по выручке за период (в отличие от старой версии вкладки,
        привязано к выбранному периоду, а не считается за всё время)."""
        if not master_ids:
            return []

        range_start = datetime.combine(date_from, time.min)
        range_end = datetime.combine(date_to + timedelta(days=1), time.min)

        rows = (
            await db.execute(
                select(
                    Service.name,
                    func.count(Booking.id),
                    func.coalesce(func.sum(Booking.final_price), 0),
                )
                .join(Booking, Booking.service_id == Service.id)
                .where(
                    Booking.master_id.in_(master_ids),
                    Booking.start_time >= range_start,
                    Booking.start_time < range_end,
                    Booking.status.in_(_PAID_STATUSES),
                )
                .group_by(Service.name)
                .order_by(func.sum(Booking.final_price).desc())
                .limit(limit)
            )
        ).all()
        return [{"name": name, "bookings": int(cnt), "revenue": int(total)} for name, cnt, total in rows]

    @classmethod
    async def day_operations(cls, db: AsyncSession, master_ids: list[int], day: date_) -> list[dict]:
        """Список операций за один конкретный день — для аккордеона «детали дня»
        при клике на столбец графика (доступно только при granularity=day)."""
        if not master_ids:
            return []

        day_start = datetime.combine(day, time.min)
        day_end = day_start + timedelta(days=1)

        rows = (
            await db.execute(
                select(Booking, Service, UserModel)
                .join(Service, Service.id == Booking.service_id)
                .join(UserModel, UserModel.id == Booking.client_id)
                .where(
                    Booking.master_id.in_(master_ids),
                    Booking.start_time >= day_start,
                    Booking.start_time < day_end,
                    Booking.status != BookingStatus.CANCELLED,
                )
                .order_by(Booking.start_time)
            )
        ).all()
        return [
            {
                "id": booking.id,
                "start_time": booking.start_time.isoformat(),
                "final_price": booking.final_price,
                "status": booking.status.value,
                "service": {"name": service.name, "price": service.price},
                "client": {"full_name": client.full_name, "phone": client.phone},
            }
            for booking, service, client in rows
        ]

    @classmethod
    async def master_ids_for_salon(cls, db: AsyncSession, salon_id: int) -> list[int]:
        return (await db.execute(select(Master.id).where(Master.salon_id == salon_id))).scalars().all()
