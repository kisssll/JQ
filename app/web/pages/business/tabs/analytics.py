# app/web/pages/business/tabs/analytics.py
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.web.components.hint import hint as _hint
from app.services.analytics_service import AnalyticsService
from app.web.components.icons import (
    ICON_TRENDING_UP,
    ICON_STAR_FILLED,
    ICON_X,
)


async def render_analytics_tab(db: AsyncSession, salon, master_ids) -> str:
    """Вкладка «Аналитика»: выручка/записи по дням/неделям/месяцам/годам за
    произвольный период — переключатель гранулярности и свой диапазон дат
    (как в банковских приложениях). Данные грузятся через JSON API
    GET /api/v1/business/my-salon/analytics (AnalyticsService) — первая
    отрисовка (по дням, последние 14 дней) считается сразу на сервере, чтобы
    не было пустого экрана до подгрузки JS."""

    granularity = "day"
    date_from, date_to = AnalyticsService.default_range(granularity)
    points = await AnalyticsService.revenue_series(db, master_ids, granularity, date_from, date_to)
    top_services = await AnalyticsService.top_services(db, master_ids, date_from, date_to)

    total_revenue = sum(p["revenue"] for p in points)
    total_bookings = sum(p["bookings_total"] for p in points)
    total_paid = sum(p["bookings_paid"] for p in points)

    initial_data = {
        "granularity": granularity,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "points": points,
        "summary": {
            "total_revenue": total_revenue,
            "total_bookings": total_bookings,
            "avg_check": (total_revenue // total_paid) if total_paid else 0,
        },
        "top_services": top_services,
        "salon_created_at": salon.created_at.date().isoformat(),
    }
    initial_json = json.dumps(initial_data, ensure_ascii=False)

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

    return f"""
    <div id="tab-analytics" class="tab-content" data-salon-id="{salon.id}">
        <div class="analytics-toolbar">
            <div class="analytics-granularity" id="analyticsGranularity">
                <button type="button" class="analytics-gran-btn active" data-granularity="day">По дням</button>
                <button type="button" class="analytics-gran-btn" data-granularity="week">По неделям</button>
                <button type="button" class="analytics-gran-btn" data-granularity="month">По месяцам</button>
                <button type="button" class="analytics-gran-btn" data-granularity="year">По годам</button>
            </div>
            <div class="analytics-daterange">
                <input type="date" id="analyticsDateFrom" class="custom-date" value="{date_from.isoformat()}">
                <span class="analytics-daterange-sep">—</span>
                <input type="date" id="analyticsDateTo" class="custom-date" value="{date_to.isoformat()}" title="Считается автоматически от даты начала — можно скорректировать вручную">
                <button type="button" class="btn-outline" id="analyticsApplyRange">Показать</button>
                <button type="button" class="btn-outline" id="analyticsAllTime">Весь период</button>
            </div>
        </div>
        <p class="analytics-daterange-hint text-muted">Выберите дату начала — конец периода (день/неделя/месяц/год) подставится автоматически по выбранной вкладке гранулярности выше, но его можно вручную сдвинуть на любую другую дату</p>

        <div class="analytics-kpi" id="analyticsKpi"></div>

        <div class="card" style="margin-bottom:1.5rem">
            <h3 style="margin-bottom:0.5rem">{ICON_TRENDING_UP} Выручка {_hint("Столбики — выручка по подтверждённым/завершённым записям за выбранный период и гранулярность. При группировке «по дням» можно нажать на столбец, чтобы увидеть список записей.")}</h3>
            <div class="chart-bar" id="analyticsChart"></div>
            <p style="font-size:0.75rem;color:var(--color-muted);text-align:center;margin-top:0.5rem" id="analyticsChartHint">Нажмите на столбец, чтобы увидеть детали дня</p>

            {accordion_html}
        </div>

        <div class="card">
            <h3 style="margin-bottom:1rem">{ICON_STAR_FILLED} Топ услуг по выручке {_hint("Топ-5 услуг за выбранный период (не за всё время) по сумме подтверждённых и завершённых записей.")}</h3>
            <table>
                <thead>
                    <tr><th>Услуга</th><th>Записей</th><th>Выручка</th></tr>
                </thead>
                <tbody id="analyticsTopServices"></tbody>
            </table>
        </div>
    </div>

    <script>
        window.analyticsInitial = {initial_json};
    </script>
    """