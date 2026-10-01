# app/web/pages/business/tabs/overview.py

from app.web.components.escaping import e
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from app.models.models import Booking, BookingStatus, User, Review
from app.web.components.booking_link import render_booking_link_block
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
    ICON_CHECK,
    ICON_CIRCLE_CHECK,
    ICON_CIRCLE_X,
    ICON_ALERT_TRIANGLE,
    ICON_HEART,
    ICON_ARROW_RIGHT,
)


def _tab_url(salon_id: int, target: str) -> str:
    """Адрес действия из строки «что мешает». Якорь (#…) ведёт на ту же
    страницу — плашка статуса салона в шапке панели: кнопка «Опубликовать»
    живёт только там, и дублировать её здесь нельзя (обработчик висит на id)."""
    if target.startswith("#"):
        return target
    return f"/business/dashboard?salon_id={salon_id}&tab={target}"


def _render_readiness(salon, readiness, solo: bool) -> str:
    """«Можно ли к вам записаться» — вердикт и список того, что мешает.

    Условия считает app/services/booking_readiness.py, здесь только показ:
    иначе правила разъехались бы с кодом записи, из которого они выписаны.
    Пользовательских данных в строках нет (тексты — литералы сервиса), поэтому
    экранировать нечего; если в строку когда-нибудь попадёт причина отказа
    модерации или имя салона — её придётся пропустить через e().
    """
    who = "к вам" if solo else "в ваш салон"
    if not readiness.issues:
        state, mark = "ok", ICON_CIRCLE_CHECK
        verdict = f"Записаться {who} можно"
        sub = "Ссылка, QR и каталог работают — клиент выберет услугу и время сам."
    elif readiness.can_book:
        # Блокировок нет, но один из двух путей записи закрыт.
        state, mark = "warn", ICON_ALERT_TRIANGLE
        verdict = f"Записаться {who} можно, но не всеми способами"
        sub = ""
    else:
        state, mark = "bad", ICON_CIRCLE_X
        verdict = f"Записаться {who} сейчас нельзя"
        sub = "Пока это не исправлено, заявок не будет — даже по ссылке."

    rows = ""
    for issue in readiness.issues:
        action = (
            f'<a class="readiness-action" href="{_tab_url(salon.id, issue.target)}">'
            f'{issue.action} {ICON_ARROW_RIGHT}</a>'
        ) if issue.target else ""
        rows += (
            f'<li class="readiness-row readiness-row-{"bad" if issue.blocking else "warn"}">'
            f'<span class="readiness-text">{issue.text}</span>{action}</li>'
        )
    rows_html = f'<ul class="readiness-list">{rows}</ul>' if rows else ""
    sub_html = f'<p class="readiness-sub">{sub}</p>' if sub else ""

    return f"""
    <section class="readiness readiness-{state}" aria-label="Готовность к записи">
        <p class="readiness-verdict"><span class="readiness-mark">{mark}</span>{verdict}</p>
        {sub_html}
        {rows_html}
    </section>
    """


def _render_models_invite(salon_id: int) -> str:
    """Приглашение в раздел «Модели» — его за 25 дней открыли один раз, и это
    при том, что он включён в обоих режимах (решение 0007, п. 2).

    Каждое утверждение здесь сверено с app/web/pages/business/tabs/promo_models.py
    и app/services/model_matching_service.py: публикуется поиск на КОНКРЕТНУЮ
    услугу со своей ценой и длительностью, обычным клиентам она не видна
    (is_model_practice), квота закрывает набор, а откликнувшаяся модель сама
    выбирает свободное окно в расписании мастера — отдельного шага «оффер» нет.
    Ничего сверх этого обещать нельзя.
    """
    return f"""
    <section class="models-invite" aria-label="Раздел «Модели»">
        <span class="models-invite-mark">{ICON_HEART}</span>
        <div class="models-invite-body">
            <h3 class="models-invite-title">Ищете моделей на отработку?</h3>
            <p class="models-invite-text">
                Опубликуйте поиск на отдельную услугу — со своей ценой, длительностью,
                желаемой датой и числом моделей, которое нужно набрать. Обычным клиентам
                такая услуга не показывается. Кто откликнулся, сам выбирает свободное
                окно в вашем расписании, а когда набор закончен, поиск закрывается.
            </p>
            <a class="models-invite-link" href="/business/dashboard?salon_id={salon_id}&tab=models">
                Открыть «Модели» {ICON_ARROW_RIGHT}</a>
        </div>
    </section>
    """


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
    *,
    solo: bool = False,
    readiness=None,
    show_booking_link: bool = False,
    show_models_invite: bool = False,
    has_any_booking: bool = True,
    extra_html: str = "",
) -> str:
    """Вкладка «Обзор» — главный экран панели.

    Собирается из блоков, и порядок у режимов разный (решение 0007, п. 6):

      соло: можно ли записаться → ссылка и QR → сегодня → «Модели» → выручка;
      команда: можно ли записаться (только если есть проблемы) → привычные
      счётчики, график и «сегодня» → ссылка и QR.

    Соло-мастеру деньги показываем, только когда записи вообще существуют:
    пустой график и четыре нуля — не информация, а шум на первом экране.

    Новые аргументы — именованные и со значениями по умолчанию: тот же рендер
    зовёт панель мастера (master_dashboard.py), где ни блока готовности, ни
    ссылки быть не должно — там человек наёмный, а разделы, куда ведут
    действия, ему не принадлежат.

      solo             — режим салона «работаю один» (panel_sections.is_solo);
      readiness        — Readiness из services/booking_readiness.py или None,
                         если блок показывать не нужно;
      show_booking_link — рисовать ли ссылку и QR;
      show_models_invite — приглашать ли в «Модели». Раздел владелец может
                         выключить в самой панели, и звать в выключенный
                         раздел нельзя: ссылка вернула бы человека в «Обзор»;
      has_any_booking  — есть ли у салона хоть одна запись за всё время;
      extra_html       — что дописать в конец вкладки. Нужен панели мастера:
                         она добавляет свои карточки и раньше вклеивала их
                         поиском подстроки «</div>\n    </div>» в готовой
                         разметке. Любая перестановка блоков здесь молча
                         уводила их в середину экрана.
    """
    
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
        # Базы для процента нет: и «0%», и «+100%» тут вымышленные. Пустой текст
        # — чип не рисуется вовсе, вместо шума на всех плитках нового салона.
        if previous <= 0:
            return "", "flat"
        pct = (current - previous) / previous * 100
        if pct > 0.05:
            return f"+{pct:.0f}%", "up"
        if pct < -0.05:
            return f"{pct:.0f}%", "down"
        return "0%", "flat"

    def trend_badge(text: str, css_class: str) -> str:
        if not text:
            return ""
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
    # Чип рисуем только когда оценка реально сдвинулась. Раньше здесь стояли «—»
    # (сравнивать не с чем) и «0.0» (не менялась) — рядом со значением «5.0»
    # такой чип читается как вторая оценка, а не как отсутствие изменений.
    rating_trend = ""
    if rating_prev is not None:
        rating_diff = current_rating - rating_prev
        if rating_diff > 0.05:
            rating_trend = trend_badge(f"+{rating_diff:.1f}", "up")
        elif rating_diff < -0.05:
            rating_trend = trend_badge(f"{rating_diff:.1f}", "down")

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
    
    # --- 1. КАРТОЧКИ СТАТИСТИКИ ---
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
    chart_height = 80
    revenue_bars = ""
    for i in range(7):
        height = int(revenue_data[i] / max_revenue * chart_height) if max_revenue > 0 else 5
        # Пустой день — тонкая нейтральная засечка, а не зелёный столбик на 8px:
        # при нулевой неделе график рисовал семь зелёных полосок, и это читалось
        # как «выручка есть», хотя над каждой стояло «0 ₽».
        if revenue_data[i] > 0:
            height = max(height, 8)
            bar_bg = ("background: linear-gradient(to top, var(--color-success), "
                      "color-mix(in srgb, var(--color-success) 80%, transparent));")
        else:
            height = 2
            bar_bg = "background: var(--color-border);"
        rev_val = f"{revenue_data[i]}".replace(",", " ")
        revenue_bars += f"""
        <div class="chart-column" data-day-index="{i}" style="cursor:pointer">
            <div class="chart-value">{rev_val} ₽</div>
            <div class="chart-fill" style="height:{height}px; {bar_bg}"></div>
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
        <div class="chart-bar" id="overviewChartBar">{revenue_bars}</div>
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
            status_label = f"{ICON_CHECK} Оплачено" if booking.status == BookingStatus.COMPLETED else "○ Ожидание"
            status_class = "status-paid" if booking.status == BookingStatus.COMPLETED else "status-waiting"
            initials = "".join([part[0].upper() for part in client.full_name.split()]) if client.full_name else "К"
            price_str = f"{booking.final_price or service.price:,}".replace(",", " ")
            time_str = booking.start_time.strftime("%H:%M")
            service_name = service.name
            today_items += f"""
            <div class="booking-item">
                <div class="avatar">{initials}</div>
                <div class="info">
                    <div class="name">{e(client.full_name or client.phone)}</div>
                    <div class="desc">
                        {ICON_CLOCK} {time_str} • {e(service_name)}
                    </div>
                </div>
                <div class="price">{price_str} ₽</div>
                <span class="status {status_class}">{status_label}</span>
            </div>
            """
    else:
        # Пустая таблица ничего не сообщает. Про ссылку говорим только там, где
        # она тут же на экране, и без «выше/ниже»: порядок блоков у режимов разный.
        empty_text = (
            "Записей на сегодня нет — раздайте клиентам ссылку для записи."
            if show_booking_link and solo else "Записей на сегодня нет."
        )
        today_items = (
            f'<p class="today-empty">{empty_text}</p>'
        )

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
    # Блок готовности: соло-мастеру отвечаем всегда (он за этим и зашёл —
    # «можно ли ко мне записаться»), команде — только когда есть что исправлять:
    # у салона с командой первый экран и так занят делом.
    readiness_html = ""
    if readiness is not None and (solo or readiness.issues):
        readiness_html = _render_readiness(salon, readiness, solo)

    booking_link_html = ""
    if show_booking_link:
        # enabled — ровно про тумблер «запись без регистрации», потому что
        # приписка под заголовком объясняет именно его. Передавать сюда
        # readiness.link_works нельзя: он False и когда салон не опубликован,
        # и человек прочитал бы, что выключил тумблер, которого не трогал.
        # Остальные причины уже перечислены блоком готовности выше — второй
        # раз, да ещё и неверно, их называть незачем.
        booking_link_html = render_booking_link_block(
            salon.id, enabled=bool(salon.guest_booking_enabled),
        )

    if solo:
        # Деньги — последним и только когда записи существуют. Пока их нет,
        # счётчики и график показывали четыре нуля и семь засечек.
        money_html = f"""
        {stats_cards}
        {revenue_html}
        """ if has_any_booking else ""
        body = f"""
        {readiness_html}
        {booking_link_html}
        {today_html}
        {_render_models_invite(salon.id) if show_models_invite else ""}
        {money_html}
        """
    else:
        body = f"""
        {readiness_html}
        {stats_cards}
        <div class="overview-grid-2-1">
            {revenue_html}
            {today_html}
        </div>
        {booking_link_html}
        """

    return f"""
    <div id="tab-overview" class="tab-content">
        {body}
        {extra_html}
    </div>

    <script>
        window.weekOperations = {week_operations_json};
        window.days = {days_json};
    </script>
    """