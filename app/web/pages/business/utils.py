# app/web/pages/business/utils.py
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.models import Master, Service, User as UserModel, Booking, BookingStatus, PAID_BOOKING_STATUSES


async def get_masters_data(db: AsyncSession, salon_id: int):
    """Загружает мастеров салона с явной загрузкой пользователей."""
    masters_result = await db.execute(select(Master).where(Master.salon_id == salon_id))
    masters = masters_result.scalars().all()
    
    masters_rows = ""
    for m in masters:
        user_result = await db.execute(select(UserModel).where(UserModel.id == m.user_id))
        master_user = user_result.scalar_one_or_none()
        user_name = master_user.full_name if master_user else "—"
        
        svc_result = await db.execute(select(func.count(Service.id)).where(Service.master_id == m.id))
        svc_count = svc_result.scalar() or 0
        
        masters_rows += f"""
        <tr>
            <td>{user_name}</td>
            <td>{m.specialization}</td>
            <td>{m.experience_years} лет</td>
            <td>{svc_count}</td>
            <td>⭐ {m.rating}</td>
        </tr>
        """
    
    return masters, masters_rows


def get_master_ids(masters):
    """Возвращает список id мастеров."""
    return [m.id for m in masters]


async def get_overview_revenue_data(db: AsyncSession, master_ids: list) -> dict:
    """Данные для render_overview_tab (карточки статистики + график выручки за
    неделю + список записей на сегодня) — общие для owner/admin (dashboard.py)
    и мастера (master_dashboard.py), чтобы не разъезжаться при следующем
    изменении сигнатуры render_overview_tab."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)

    today_bookings = 0
    if master_ids:
        tb = await db.execute(select(func.count(Booking.id)).where(
            Booking.master_id.in_(master_ids),
            Booking.start_time >= today,
            Booking.start_time < tomorrow
        ))
        today_bookings = tb.scalar() or 0

    revenue_data = {}
    prev_revenue_data = {}
    week_operations = {}
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    for i in range(7):
        day = today - timedelta(days=today.weekday()) + timedelta(days=i)
        day_end = day + timedelta(days=1)

        if master_ids:
            rev = await db.execute(
                select(func.coalesce(func.sum(Booking.final_price), 0))
                .where(
                    Booking.master_id.in_(master_ids),
                    Booking.start_time >= day,
                    Booking.start_time < day_end,
                    Booking.status.in_(PAID_BOOKING_STATUSES)
                )
            )
            revenue_data[i] = rev.scalar() or 0
        else:
            revenue_data[i] = 0

        if master_ids:
            ops = await db.execute(
                select(Booking, Service, UserModel)
                .join(Service, Service.id == Booking.service_id)
                .join(UserModel, UserModel.id == Booking.client_id)
                .where(
                    Booking.master_id.in_(master_ids),
                    Booking.start_time >= day,
                    Booking.start_time < day_end,
                    Booking.status != BookingStatus.CANCELLED
                )
                .order_by(Booking.start_time)
            )
            week_operations[i] = ops.all()
        else:
            week_operations[i] = []

        prev_day = today - timedelta(days=today.weekday() + 7) + timedelta(days=i)
        prev_day_end = prev_day + timedelta(days=1)
        if master_ids:
            prev_rev = await db.execute(
                select(func.coalesce(func.sum(Booking.final_price), 0))
                .where(
                    Booking.master_id.in_(master_ids),
                    Booking.start_time >= prev_day,
                    Booking.start_time < prev_day_end,
                    Booking.status.in_(PAID_BOOKING_STATUSES)
                )
            )
            prev_revenue_data[i] = prev_rev.scalar() or 0
        else:
            prev_revenue_data[i] = 0

    total_revenue = sum(revenue_data.values())
    prev_total_revenue = sum(prev_revenue_data.values())
    revenue_diff = total_revenue - prev_total_revenue
    revenue_trend = "▲" if revenue_diff > 0 else "▼" if revenue_diff < 0 else "—"
    revenue_color = "#22c55e" if revenue_diff > 0 else "#ef4444" if revenue_diff < 0 else "var(--color-muted)"

    today_bookings_list = []
    if master_ids:
        bookings_today = await db.execute(
            select(Booking, Service, UserModel)
            .join(Service, Service.id == Booking.service_id)
            .join(UserModel, UserModel.id == Booking.client_id)
            .where(
                Booking.master_id.in_(master_ids),
                Booking.start_time >= today,
                Booking.start_time < tomorrow,
                Booking.status != BookingStatus.CANCELLED
            )
            .order_by(Booking.start_time)
        )
        today_bookings_list = bookings_today.all()

    return {
        "today_bookings": today_bookings,
        "today_bookings_list": today_bookings_list,
        "revenue_data": revenue_data,
        "prev_revenue_data": prev_revenue_data,
        "total_revenue": total_revenue,
        "revenue_diff": revenue_diff,
        "revenue_trend": revenue_trend,
        "revenue_color": revenue_color,
        "week_operations": week_operations,
        "days": days,
    }