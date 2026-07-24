# app/web/pages/business/tabs/overview.py

import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from app.models.models import Booking, BookingStatus, User, Review
from app.web.components.hint import hint as _hint
from app.web.components.icons import (
    ICON_USERS_SMALL,
    ICON_CALENDAR_DAYS_SMALL,
    ICON_TRENDING_UP,
    ICON_STAR_FILLED,
    ICON_ARROW_UP_RIGHT,
    ICON_USER_CHECK,
    ICON_CLOCK,
    ICON_X,
    ICON_RUBLE_SIGN,
    ICON_CREDIT_CARD_SMALL,
)


async def render_overview_tab(
    db: AsyncSession,
    salon,
    masters,
    master_ids,
    services_count,
    promotions,
    today_bookings,
    today_bookings_list,
    revenue_data,
    prev_revenue_data,
    total_revenue,
    revenue_diff,
    revenue_trend,
    revenue_color,
    week_operations,
    days,
) -> str:
    """Вкладка Обзор со статистикой, выручкой и сегодняшними записями."""
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    # --- Количество уникальных клиентов салона (всего и неделю назад) ---
    clients_count = 0
    clients_count_prev = 0
    if master_ids:
        clients_result = await db.execute(
            select(func.count(func.distinct(Booking.client_id)))
            .where(Booking.master_id.in_(master_ids))
        )
        clients_count = clients_result.scalar() or 0

        clients_prev_result = await db.execute(
            select(func.count(func.distinct(Booking.client_id)))
            .where(Booking.master_id.in_(master_ids), Booking.start_time < week_ago)
        )
        clients_count_prev = clients_prev_result.scalar() or 0

    # --- Записи: сегодня vs вчера ---
    bookings_yesterday = 0
    if master_ids:
        by_result = await db.execute(
            select(func.count(Booking.id))
            .where(Booking.master_id.in_(master_ids), Booking.start_time >= yesterday, Booking.start_time < today)
        )
        bookings_yesterday = by_result.scalar() or 0

    # --- Рейтинг: текущий vs средний по отзывам недельной давности ---
    rating_prev_result = await db.execute(
        select(func.avg(Review.rating)).where(Review.salon_id == salon.id, Review.created_at < week_ago)
    )
    rating_prev_raw = rating_prev_result.scalar()
    rating_prev = float(rating_prev_raw) if rating_prev_raw is not None else None

    def pct_trend(current: float, previous: float) -> tuple[str, str]:
        """Текст и css-класс (up/down/flat) для процентного изменения current относительно previous."""
        if previous <= 0:
            return ("0%", "flat") if current <= 0 else ("+100%", "up")
        pct = (current - previous) / previous * 100
        if pct > 0.05:
            return f"+{pct:.0f}%", "up"
        if pct < -0.05:
            return f"{pct:.0f}%", "down"
        return "0%", "flat"

    def trend_badge(text: str, css_class: str) -> str:
        if css_class == "up":
            icon = ICON_ARROW_UP_RIGHT
        elif css_class == "down":
            icon = f'<span style="display:inline-flex;transform:rotate(90deg)">{ICON_ARROW_UP_RIGHT}</span>'
        else:
            icon = ""
        return f'<span class="stat-trend {css_class}">{icon}{text}</span>'

    clients_trend = trend_badge(*pct_trend(clients_count, clients_count_prev))
    records_trend = trend_badge(*pct_trend(today_bookings, bookings_yesterday))
    revenue_trend_pct = trend_badge(*pct_trend(total_revenue, sum(prev_revenue_data.values())))

    current_rating = salon.rating or 0.0
    if rating_prev is None:
        rating_trend = trend_badge("—", "flat")
    else:
        rating_diff = current_rating - rating_prev
        if rating_diff > 0.05:
            rating_trend = trend_badge(f"+{rating_diff:.1f}", "up")
        elif rating_diff < -0.05:
            rating_trend = trend_badge(f"{rating_diff:.1f}", "down")
        else:
            rating_trend = trend_badge("0.0", "flat")

    # --- Данные для JS (аккордеон) ---
    week_ops_serialized = []
    total_bookings_week = 0
    for i in range(7):
        day_ops = []
        for booking, service, client in week_operations[i]:
            day_ops.append({
                "id": booking.id,
                "start_time": booking.start_time.isoformat(),
                "final_price": booking.final_price,
                "status": booking.status.value,
                "payment_method": getattr(booking, "payment_method", "Карта"),
                "service": {"name": service.name, "price": service.price},
                "client": {"full_name": client.full_name, "phone": client.phone}
            })
        week_ops_serialized.append(day_ops)
        total_bookings_week += len(day_ops)
    
    week_operations_json = json.dumps(week_ops_serialized, ensure_ascii=False)
    days_json = json.dumps(days, ensure_ascii=False)
    
    # Средний чек за неделю
    avg_check = total_revenue // max(total_bookings_week, 1) if total_bookings_week > 0 else 0
    
    # --- 1. КАРТОЧКИ СТАТИСТИКИ (4 карточки как в образце) ---
    stats_cards = f"""
    <div class="stats-grid-4">
        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_USERS_SMALL}</div>
                {clients_trend}
            </div>
            <p class="stat-value">{clients_count}</p>
            <p class="stat-label">Клиентов {_hint("Все уникальные клиенты, когда-либо записывавшиеся к мастерам салона. Процент — рост их числа за последнюю неделю.")}</p>
        </div>

        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_CALENDAR_DAYS_SMALL}</div>
                {records_trend}
            </div>
            <p class="stat-value">{today_bookings}</p>
            <p class="stat-label">Записей {_hint("Записи на сегодня (кроме отменённых). Процент — по сравнению со вчера.")}</p>
        </div>

        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_TRENDING_UP}</div>
                {revenue_trend_pct}
            </div>
            <p class="stat-value">{f"{total_revenue:,}".replace(",", " ")} ₽</p>
            <p class="stat-label">Выручка {_hint("Сумма подтверждённых и завершённых записей за текущую неделю (Пн—Вс). Процент — по сравнению с прошлой неделей.")}</p>
        </div>

        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_STAR_FILLED}</div>
                {rating_trend}
            </div>
            <p class="stat-value">{current_rating:.1f}</p>
            <p class="stat-label">Рейтинг {_hint("Средний рейтинг салона по всем отзывам. Число рядом — изменение по сравнению со средним рейтингом отзывов недельной давности.")}</p>
        </div>
    </div>
    """

    # --- 2. ВЫРУЧКА ЗА НЕДЕЛЮ (график с аккордеоном) ---
    max_revenue = max(max(revenue_data.values()) if revenue_data else 1, 1)
    # Контейнер имеет высоту 150px, оставляем 12px на подписи и отступы
    chart_height = 80
    revenue_bars = ""
    for i in range(7):
        height = int(revenue_data[i] / max_revenue * chart_height) if max_revenue > 0 else 5
        # минимальная высота 8px, чтобы столбцы были видны
        height = max(height, 8)
        is_highest = revenue_data[i] == max(revenue_data.values()) if revenue_data else False
        rev_val = f"{revenue_data[i]}".replace(",", " ")
        bar_color = "#059669" if is_highest else "#34d399"
        bar_bg = f"background: linear-gradient(to top, {bar_color}, {bar_color}cc);"
        revenue_bars += f"""
        <div class="chart-column" data-day-index="{i}" onclick="toggleDayDetails({i}, '{days[i]}', {revenue_data[i]}, {prev_revenue_data[i]})" style="cursor:pointer">
            <div class="chart-value">{rev_val} ₽</div>
            <div class="chart-fill {'highest' if is_highest else ''}" style="height:{height}px; {bar_bg}"></div>
            <span class="chart-label">{days[i]}</span>
        </div>"""

    # Контейнер для аккордеона (детали дня)
    accordion_html = f"""
    <div class="day-accordion" id="dayAccordion" style="display:none;">
        <div class="day-accordion-header">
            <h4 id="accordionDayTitle">Операции за день</h4>
            <span id="accordionDaySummary" class="text-muted"></span>
            <button class="accordion-close">{ICON_X}</button>
        </div>
        <div id="accordionDayOperations" class="day-accordion-body"></div>
    </div>
    """

    revenue_html = f"""
    <div class="chart-wrapper">
        <div class="chart-header">
            <h3>{ICON_RUBLE_SIGN} Выручка за неделю</h3>
            <span class="chart-total">Общая: {total_revenue:,} ₽</span>
        </div>
        <div class="chart-bar">{revenue_bars}</div>
        <div class="kpi-row">
            <span><span class="kpi-label">Средний чек: </span><strong>{avg_check:,} ₽</strong></span>
            <span><span class="kpi-label">Динамика: </span><strong style="color:{revenue_color}">{revenue_trend} {abs(revenue_diff):,} ₽</strong></span>
        </div>
        <p style="font-size:0.7rem;color:var(--color-muted);text-align:center;margin-top:0.75rem">Нажмите на столбец, чтобы увидеть детали дня</p>
        
        {accordion_html}
    </div>
    """

    # --- 3. СЕГОДНЯ ---
    today_items = ""
    if today_bookings_list:
        for booking, service, client in today_bookings_list:
            status_label = "✓ Оплачено" if booking.status == BookingStatus.COMPLETED else "○ Ожидание"
            status_class = "status-paid" if booking.status == BookingStatus.COMPLETED else "status-waiting"
            initials = "".join([part[0].upper() for part in client.full_name.split()]) if client.full_name else "К"
            price_str = f"{booking.final_price or service.price:,}".replace(",", " ")
            time_str = booking.start_time.strftime("%H:%M")
            service_name = service.name
            today_items += f"""
            <div class="booking-item">
                <div class="avatar">{initials}</div>
                <div class="info">
                    <div class="name">{client.full_name or client.phone}</div>
                    <div class="desc">
                        {ICON_CLOCK} {time_str} • {service_name}
                    </div>
                </div>
                <div class="price">{price_str} ₽</div>
                <span class="status {status_class}">{status_label}</span>
            </div>
            """
    else:
        today_items = '<p class="text-muted" style="padding:1rem 0;text-align:center">На сегодня записей нет</p>'

    today_html = f"""
    <div class="card">
        <div class="chart-header">
            <h3 style="display:flex;align-items:center;gap:0.5rem">
                <span style="display:inline-flex;align-items:center;color:var(--color-primary)">{ICON_USER_CHECK}</span>
                Сегодня
            </h3>
            <span class="chart-total">{len(today_bookings_list)} клиентов</span>
        </div>
        <div class="space-y-3">
            {today_items}
        </div>
    </div>
    """

    # --- 4. Собираем всё ---
    return f"""
    <div id="tab-overview" class="tab-content">
        {stats_cards}
        
        <div class="overview-grid-2-1">
            {revenue_html}
            {today_html}
        </div>
    </div>

    <script>
        (function() {{
            const weekOperations = {week_operations_json};
            const days = {days_json};
            let currentOpenDay = null;

            function closeDayDetails() {{
                const accordion = document.getElementById('dayAccordion');
                if (accordion) accordion.style.display = 'none';
                currentOpenDay = null;
            }}

            function toggleDayDetails(index, dayName, revenue, prevRevenue) {{
                const accordion = document.getElementById('dayAccordion');
                const title = document.getElementById('accordionDayTitle');
                const summary = document.getElementById('accordionDaySummary');
                const container = document.getElementById('accordionDayOperations');
                
                if (currentOpenDay === index && accordion.style.display !== 'none') {{
                    closeDayDetails();
                    return;
                }}
                
                const ops = weekOperations[index] || [];
                title.textContent = `Операции за ${{dayName}}`;
                const totalOps = ops.length;
                const paidCount = ops.filter(o => o.status === 'completed').length;
                summary.textContent = `${{totalOps}} операций • ${{revenue.toLocaleString()}} ₽ • Оплачено: ${{paidCount}}/${{totalOps}}`;
                
                container.innerHTML = '';
                if (totalOps === 0) {{
                    container.innerHTML = '<p class="text-muted">Нет операций за этот день</p>';
                }} else {{
                    ops.forEach(op => {{
                        const time = new Date(op.start_time).toLocaleTimeString('ru-RU', {{hour:'2-digit', minute:'2-digit'}});
                        const price = (op.final_price || op.service.price).toLocaleString();
                        const statusLabel = op.status === 'completed' ? '✓' : '○';
                        const statusClass = op.status === 'completed' ? 'status-paid' : 'status-waiting';
                        const initials = op.client.full_name ? op.client.full_name.split(' ').map(n => n[0]).join('') : 'К';
                        const method = op.payment_method || 'Карта';
                        
                        const item = document.createElement('div');
                        item.className = 'booking-item';
                        item.innerHTML = `
                            <div class="avatar">${{initials}}</div>
                            <div class="info">
                                <div class="name">${{op.client.full_name || op.client.phone}}</div>
                                <div class="desc">
                                    {ICON_CLOCK} ${{time}} • ${{op.service.name}}
                                </div>
                            </div>
                            <div class="price">${{price}} ₽</div>
                            <div style="display:flex;align-items:center;gap:0.5rem;flex-shrink:0">
                                <span style="font-size:0.7rem;color:var(--color-muted)">${{method}}</span>
                                <span class="status ${{statusClass}}">${{statusLabel}}</span>
                            </div>
                        `;
                        container.appendChild(item);
                    }});
                }}
                
                accordion.style.display = 'block';
                accordion.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
                currentOpenDay = index;
            }}

            window.toggleDayDetails = toggleDayDetails;
            window.closeDayDetails = closeDayDetails;

            // Обработчик крестика через делегирование (работает надёжнее)
            document.addEventListener('click', function(e) {{
                const closeBtn = e.target.closest('.accordion-close');
                if (closeBtn) {{
                    e.preventDefault();
                    closeDayDetails();
                }}
            }});

            document.addEventListener('keydown', function(e) {{
                if (e.key === 'Escape') closeDayDetails();
            }});
        }})();
    </script>
    """