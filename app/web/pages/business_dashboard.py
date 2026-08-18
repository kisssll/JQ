# app/web/pages/business_dashboard.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from app.models.models import Salon, Master, Service, Promotion, Booking, Review, BookingStatus, User as UserModel
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_CALENDAR_DAYS,
    ICON_CHART_COLUMN,
    ICON_EDIT_PENCIL,
    ICON_MESSAGE_CIRCLE,
    ICON_MONEY,
    ICON_SPARKLES,
    ICON_STAR_EMPTY,
    ICON_STAR_FILLED,
    ICON_TRENDING_UP,
    ICON_TROPHY,
    ICON_USERS,
)


async def render_business_dashboard(db: AsyncSession, user, salon: Salon) -> str:
    """Улучшенная бизнес-панель с реальной аналитикой."""
    
    # === РЕАЛЬНАЯ СТАТИСТИКА ===
    
    # Мастера
    masters_result = await db.execute(select(Master).where(Master.salon_id == salon.id))
    masters = masters_result.scalars().all()
    master_ids = [m.id for m in masters]
    
    # Услуги
    services_count = 0
    if master_ids:
        svc = await db.execute(select(func.count(Service.id)).where(Service.master_id.in_(master_ids)))
        services_count = svc.scalar() or 0
    
    # Акции
    promos_result = await db.execute(select(Promotion).where(Promotion.salon_id == salon.id))
    promotions = promos_result.scalars().all()
    
    # Отзывы
    reviews_result = await db.execute(
        select(Review).where(Review.salon_id == salon.id).order_by(Review.created_at.desc())
    )
    reviews = reviews_result.scalars().all()
    
    # Записи за сегодня
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    today_bookings = 0
    if master_ids:
        tb = await db.execute(select(func.count(Booking.id)).where(Booking.master_id.in_(master_ids), Booking.start_time >= today, Booking.start_time < tomorrow))
        today_bookings = tb.scalar() or 0
    
    # Записи за неделю (для графика)
    week_data = {}
    for i in range(7):
        day = today - timedelta(days=today.weekday()) + timedelta(days=i)
        day_end = day + timedelta(days=1)
        if master_ids:
            count = await db.execute(select(func.count(Booking.id)).where(Booking.master_id.in_(master_ids), Booking.start_time >= day, Booking.start_time < day_end))
            week_data[i] = count.scalar() or 0
        else:
            week_data[i] = 0
    
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    max_val = max(week_data.values()) if week_data else 1
    chart_bars = ""
    for i in range(7):
        height = int(week_data[i] / max_val * 160) if max_val > 0 else 5
        chart_bars += f'<div class="chart-column"><div class="chart-value">{week_data[i]}</div><div class="chart-fill" style="height:{max(height, 5)}px"></div><div class="chart-label">{days[i]}</div></div>'
    
    # === ДАННЫЕ ДЛЯ АНАЛИТИКИ ===
    
    # Выручка по дням недели (текущая неделя)
    revenue_data = {}
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
                    Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED])
                )
            )
            revenue_data[i] = rev.scalar() or 0
        else:
            revenue_data[i] = 0
    
    # Выручка за прошлую неделю
    prev_revenue_data = {}
    for i in range(7):
        day = today - timedelta(days=today.weekday() + 7) + timedelta(days=i)
        day_end = day + timedelta(days=1)
        if master_ids:
            rev = await db.execute(
                select(func.coalesce(func.sum(Booking.final_price), 0))
                .where(
                    Booking.master_id.in_(master_ids),
                    Booking.start_time >= day,
                    Booking.start_time < day_end,
                    Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED])
                )
            )
            prev_revenue_data[i] = rev.scalar() or 0
        else:
            prev_revenue_data[i] = 0
    
    # График выручки (столбцы)
    max_revenue = max(max(revenue_data.values()) if revenue_data else 1, 1)
    revenue_bars = ""
    for i in range(7):
        height = int(revenue_data[i] / max_revenue * 160) if max_revenue > 0 else 5
        prev_height = int(prev_revenue_data[i] / max_revenue * 160) if max_revenue > 0 else 5
        is_highest = revenue_data[i] == max(revenue_data.values())
        rev_val = f"{revenue_data[i]}".replace(",", " ")
        prev_val = f"{prev_revenue_data[i]}".replace(",", " ")
        revenue_bars += f"""
        <div class="chart-column" onclick="showDayDetails({i}, '{days[i]}', {revenue_data[i]}, {prev_revenue_data[i]})" style="cursor:pointer">
            <div class="chart-value">{rev_val} ₽</div>
            <div class="chart-fill {'highest' if is_highest else ''}" style="height:{max(height, 5)}px"></div>
            <div class="chart-fill prev" style="height:{max(prev_height, 5)}px;opacity:0.4"></div>
            <div class="chart-label">{days[i]}</div>
        </div>
        """

    # Общая выручка за неделю
    total_revenue = sum(revenue_data.values())
    prev_total_revenue = sum(prev_revenue_data.values())
    revenue_diff = total_revenue - prev_total_revenue
    revenue_trend = "▲" if revenue_diff > 0 else "▼" if revenue_diff < 0 else "—"
    revenue_color = "#22c55e" if revenue_diff > 0 else "#ef4444" if revenue_diff < 0 else "var(--color-muted)"
    
    # Топ-услуги
    top_services = []
    if master_ids:
        top_svc = await db.execute(
            select(Service.name, func.count(Booking.id).label("cnt"), func.sum(Booking.final_price).label("total"))
            .join(Booking, Booking.service_id == Service.id)
            .where(Booking.master_id.in_(master_ids), Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED]))
            .group_by(Service.name)
            .order_by(func.sum(Booking.final_price).desc())
            .limit(5)
        )
        top_services = top_svc.all()
    
    top_services_rows = ""
    for name, cnt, total in top_services:
        total_val = f"{total or 0}".replace(",", " ")
        cnt_val = f"{cnt}".replace(",", " ")
        top_services_rows += f"""
        <tr>
            <td>{name}</td>
            <td>{cnt_val}</td>
            <td><strong>{total_val} ₽</strong></td>
        </tr>
        """
    
    # Таблица мастеров
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
            <td>{ICON_STAR_FILLED} {m.rating}</td>
        </tr>
        """
    
    # Таблица акций
    promos_rows = ""
    for p in promotions:
        promos_rows += f"""
        <tr>
            <td>{p.title}</td>
            <td><span class="promo-badge">{p.tag}</span></td>
            <td>{p.description or '—'}</td>
        </tr>
        """
    
    # Таблица отзывов
    reviews_rows = ""
    for r in reviews:
        client_result = await db.execute(select(UserModel).where(UserModel.id == r.client_id))
        client_user = client_result.scalar_one_or_none()
        client_name = client_user.full_name if client_user else "Клиент"
        
        master_result = await db.execute(select(Master).where(Master.id == r.master_id))
        master = master_result.scalar_one_or_none()
        master_name = "—"
        if master:
            master_user = await db.execute(select(UserModel).where(UserModel.id == master.user_id))
            mu = master_user.scalar_one_or_none()
            master_name = mu.full_name if mu else "Мастер"
        
        stars = f"{ICON_STAR_FILLED}" * r.rating + f"{ICON_STAR_EMPTY}" * (5 - r.rating)
        date_str = r.created_at.strftime("%d.%m.%Y") if r.created_at else ""
        
        reviews_rows += f"""
        <tr>
            <td><strong>{client_name}</strong></td>
            <td>{master_name}</td>
            <td>{stars}</td>
            <td style="max-width:300px">{r.comment or 'Без комментария'}</td>
            <td style="font-size:0.85rem;color:var(--color-muted)">{date_str}</td>
        </tr>
        """
    
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Бизнес-панель — {salon.name} — руми</title>
    {get_base_styles()}
    <style>
        .tab-nav {{ display:flex; gap:0.25rem; border-bottom:1px solid var(--color-border); margin-bottom:2rem; flex-wrap:wrap }}
        .tab-btn {{ padding:0.75rem 1.5rem; border:none; background:transparent; cursor:pointer; font-size:0.875rem; font-weight:500; color:var(--color-muted); border-bottom:2px solid transparent; transition:all 0.2s; white-space:nowrap }}
        .tab-btn.active {{ color:var(--color-primary); border-bottom-color:var(--color-primary) }}
        .tab-content {{ display:none }}
        .tab-content.active {{ display:block }}
        .stat-card {{ background:var(--color-surface); border:1px solid var(--color-border); border-radius:1rem; padding:1.5rem; text-align:center }}
        .stat-value {{ font-size:2rem; font-weight:700; color:var(--color-primary) }}
        .stat-label {{ font-size:0.85rem; color:var(--color-muted); margin-top:0.25rem }}
        .promo-badge {{ display:inline-block; border-radius:2rem; padding:0.125rem 0.5rem; font-size:0.625rem; font-weight:700; color:white; background:linear-gradient(135deg,var(--color-primary),var(--color-accent)) }}
        table {{ width:100%; border-collapse:collapse }}
        th {{ text-align:left; padding:0.75rem; border-bottom:2px solid var(--color-border); font-weight:600; color:var(--color-heading); white-space:nowrap }}
        td {{ padding:0.75rem; border-bottom:1px solid var(--color-border) }}
        .chart-bar {{ height:200px; display:flex; align-items:flex-end; gap:1rem; padding:1rem 0 }}
        .chart-column {{ flex:1; display:flex; flex-direction:column; align-items:center; gap:0.25rem; min-width:40px }}
        .chart-fill {{ width:100%; max-width:3.5rem; border-radius:0.5rem 0.5rem 0 0; background:linear-gradient(to top,var(--color-primary),var(--color-accent)); transition:height 0.3s }}
        .chart-fill.highest {{ background:linear-gradient(to top,#22c55e,#4ade80) }}
        .chart-fill.prev {{ background:var(--color-border) }}
        .chart-label {{ font-size:0.75rem; color:var(--color-muted) }}
        .chart-value {{ font-size:0.7rem; font-weight:600; color:var(--color-heading); white-space:nowrap }}
        .rating-summary {{ display:flex; gap:1rem; align-items:center; margin-bottom:1.5rem; flex-wrap:wrap }}
        .rating-big {{ font-size:3rem; font-weight:800; color:var(--color-primary); line-height:1 }}
        .analytics-kpi {{ display:flex; gap:1rem; margin-bottom:1.5rem; flex-wrap:wrap }}
        .kpi-card {{ background:var(--color-surface); border:1px solid var(--color-border); border-radius:1rem; padding:1.25rem 1.5rem; flex:1; min-width:150px }}
        .kpi-value {{ font-size:1.75rem; font-weight:700; color:var(--color-heading) }}
        .kpi-label {{ font-size:0.8rem; color:var(--color-muted) }}
        .kpi-trend {{ font-size:0.85rem; font-weight:600 }}
        .legend {{ display:flex; gap:1.5rem; align-items:center; margin-bottom:1rem; font-size:0.85rem }}
        .legend-dot {{ width:12px; height:12px; border-radius:3px; display:inline-block }}
    </style>
</head>
<body>
    {render_header("business")}
    {render_sidebar("business", user)}
    
    <main style="margin-right:16rem;padding-top:2rem">
        <div class="section-container">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
                <div>
                    <h1 class="text-display" style="font-size:2rem">{salon.name}</h1>
                    <p class="text-muted">Панель управления · {ICON_STAR_FILLED} {salon.rating} ({salon.reviews_count} отзывов)</p>
                </div>
                <a href="/business/my-salon" class="btn-outline">{ICON_EDIT_PENCIL} Редактировать салон</a>
            </div>
            
            <!-- Вкладки -->
            <div class="tab-nav">
                <button class="tab-btn active" onclick="switchTab('overview')">{ICON_CHART_COLUMN} Обзор</button>
                <button class="tab-btn" onclick="switchTab('analytics')">{ICON_TRENDING_UP} Аналитика</button>
                <button class="tab-btn" onclick="switchTab('schedule')">{ICON_CALENDAR_DAYS} Расписание</button>
                <button class="tab-btn" onclick="switchTab('masters')">{ICON_USERS} Мастера ({len(masters)})</button>
                <button class="tab-btn" onclick="switchTab('promos')">{ICON_SPARKLES} Акции ({len(promotions)})</button>
                <button class="tab-btn" onclick="switchTab('reviews')">{ICON_MESSAGE_CIRCLE} Отзывы ({len(reviews)})</button>
            </div>
            
            <!-- Обзор -->
            <div id="tab-overview" class="tab-content active">
                <div class="grid-3" style="margin-bottom:2rem">
                    <div class="stat-card"><div class="stat-value">{len(masters)}</div><div class="stat-label">Мастеров</div></div>
                    <div class="stat-card"><div class="stat-value">{services_count}</div><div class="stat-label">Услуг</div></div>
                    <div class="stat-card"><div class="stat-value">{today_bookings}</div><div class="stat-label">Записей сегодня</div></div>
                    <div class="stat-card"><div class="stat-value">{len(promotions)}</div><div class="stat-label">Акций</div></div>
                    <div class="stat-card"><div class="stat-value">{salon.rating}</div><div class="stat-label">Рейтинг</div></div>
                    <div class="stat-card"><div class="stat-value">{salon.reviews_count}</div><div class="stat-label">Отзывов</div></div>
                </div>
                
                <div class="card" style="margin-bottom:2rem">
                    <h3 style="margin-bottom:1rem">{ICON_CHART_COLUMN} Записи за неделю</h3>
                    <div class="chart-bar">{chart_bars}</div>
                </div>
            </div>
            
            <!-- Аналитика -->
            <div id="tab-analytics" class="tab-content">
                <!-- KPI -->
                <div class="analytics-kpi">
                    <div class="kpi-card">
                        <div class="kpi-label">Выручка за неделю</div>
                        <div class="kpi-value">{total_revenue:,} ₽</div>
                        <div class="kpi-trend" style="color:{revenue_color}">{revenue_trend} {abs(revenue_diff):,} ₽ vs прошлая</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Средний чек</div>
                        <div class="kpi-value">{total_revenue // max(sum(week_data.values()), 1):,} ₽</div>
                        <div class="kpi-trend" style="color:var(--color-muted)">за неделю</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Всего записей</div>
                        <div class="kpi-value">{sum(week_data.values())}</div>
                        <div class="kpi-trend" style="color:var(--color-muted)">за неделю</div>
                    </div>
                </div>
                
                <!-- График выручки -->
                <div class="card" style="margin-bottom:1.5rem">
                    <h3 style="margin-bottom:0.5rem">{ICON_MONEY} Выручка по дням</h3>
                    <div class="legend">
                        <span><span class="legend-dot" style="background:linear-gradient(to top,var(--color-primary),var(--color-accent))"></span> Эта неделя</span>
                        <span><span class="legend-dot" style="background:var(--color-border)"></span> Прошлая неделя</span>
                    </div>
                    <div class="chart-bar">{revenue_bars}</div>
                    <p style="font-size:0.75rem;color:var(--color-muted);text-align:center;margin-top:0.5rem">Нажмите на столбец, чтобы увидеть детали</p>
                </div>
                
                <!-- Топ услуг -->
                <div class="card">
                    <h3 style="margin-bottom:1rem">{ICON_TROPHY} Топ услуг по выручке</h3>
                    <table>
                        <thead>
                            <tr><th>Услуга</th><th>Записей</th><th>Выручка</th></tr>
                        </thead>
                        <tbody>
                            {top_services_rows or '<tr><td colspan="3" style="text-align:center;padding:2rem;color:var(--color-muted)">Нет данных</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- Расписание -->
            <div id="tab-schedule" class="tab-content">
                <div class="card" style="text-align:center;padding:3rem">
                    <h3>{ICON_CALENDAR_DAYS} Управление расписанием</h3>
                    <p class="text-muted">Здесь будет календарь с записями по дням и мастерам</p>
                    <p class="text-muted" style="font-size:0.8rem">Функционал в разработке</p>
                </div>
            </div>
            
            <!-- Мастера -->
            <div id="tab-masters" class="tab-content">
                <div class="card" style="overflow-x:auto">
                    <table>
                        <thead>
                            <tr><th>Имя</th><th>Специализация</th><th>Опыт</th><th>Услуг</th><th>Рейтинг</th></tr>
                        </thead>
                        <tbody>
                            {masters_rows or '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-muted)">Пока нет мастеров</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- Акции -->
            <div id="tab-promos" class="tab-content">
                <div class="card" style="overflow-x:auto">
                    <table>
                        <thead>
                            <tr><th>Название</th><th>Тег</th><th>Описание</th></tr>
                        </thead>
                        <tbody>
                            {promos_rows or '<tr><td colspan="3" style="text-align:center;padding:2rem;color:var(--color-muted)">Пока нет акций</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- Отзывы -->
            <div id="tab-reviews" class="tab-content">
                <div class="card" style="margin-bottom:1.5rem">
                    <div class="rating-summary">
                        <div>
                            <div class="rating-big">{salon.rating}</div>
                            <div class="rating-stars">{ICON_STAR_FILLED * int(salon.rating)}{ICON_STAR_EMPTY * (5 - int(salon.rating))}</div>
                            <div style="font-size:0.85rem;color:var(--color-muted)">{salon.reviews_count} отзывов</div>
                        </div>
                    </div>
                </div>
                
                <div class="card" style="overflow-x:auto">
                    <table>
                        <thead>
                            <tr><th>Клиент</th><th>Мастер</th><th>Оценка</th><th>Комментарий</th><th>Дата</th></tr>
                        </thead>
                        <tbody>
                            {reviews_rows or '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-muted)">Пока нет отзывов</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </main>
    
    {render_footer(user)}
    
    <script>
        function switchTab(tabName) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById('tab-' + tabName).classList.add('active');
            event.target.classList.add('active');
        }}
        
        function showDayDetails(index, dayName, revenue, prevRevenue) {{
            const diff = revenue - prevRevenue;
            const trend = diff > 0 ? '▲' : diff < 0 ? '▼' : '—';
            const color = diff > 0 ? '#22c55e' : diff < 0 ? '#ef4444' : 'gray';
            alert(`${{dayName}}\\nВыручка: ${{revenue.toLocaleString()}} ₽\\nПрошлая неделя: ${{prevRevenue.toLocaleString()}} ₽\\n${{trend}} ${{Math.abs(diff).toLocaleString()}} ₽`);
        }}
    </script>
</body>
</html>"""
    
    return html