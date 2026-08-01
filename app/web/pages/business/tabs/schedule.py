# app/web/pages/business/tabs/schedule.py
from collections import OrderedDict
from datetime import datetime, timedelta, date as date_type
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Booking, Master, Service, User as UserModel, BookingStatus, ScheduleClosure, Schedule
from app.services.schedule_utils import get_salon_work_hours, MAX_BOOKING_DAYS_AHEAD
from app.services.schedule_service import ScheduleService
from app.services.booking_service import can_mark_completed_now
from app.web.components.hint import hint as _hint
from app.web.components.icons import (
    ICON_CHECK_SMALL,
    ICON_X,
    ICON_PLUS_SMALL,
    ICON_LOCK_SMALL,
    ICON_CALENDAR_SMALL,
    ICON_ARROW_LEFT,
    ICON_ARROW_RIGHT,
)

MONTH_NAMES_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
WEEKDAY_NAMES_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAY_NAMES_FULL_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


async def render_schedule_tab(
    db: AsyncSession, salon, masters, can_manage_schedule: bool = False,
    schedule_master_id: int = None, can_close_dates: bool = None,
    viewer_master_id: int = None, schedule_date: date_type = None,
    evening_deal_html: str = "",
) -> str:
    """
    Вкладка «Расписание»:
    - Десктоп: календарная сетка на неделю (Пн–Вс) с возможностью переключения недель.
    - Мобильный: список записей на выбранный день с навигацией (без перезагрузки).
    """
    if can_close_dates is None:
        can_close_dates = can_manage_schedule

    if not masters:
        return ('<div id="tab-schedule" class="tab-content"><div class="card" '
                'style="padding:2rem;text-align:center;color:var(--color-muted)">В салоне пока нет мастеров</div></div>')

    # --- Определяем мастера ---
    master_by_id = {m.id: m for m in masters}
    selected_master = master_by_id.get(schedule_master_id) or masters[0]

    master_names = {}
    for m in masters:
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        master_names[m.id] = mu.full_name if mu else "—"

    today = datetime.now().date()

    # --- Для мобильного списка: дата (по умолчанию сегодня) ---
    if schedule_date is None:
        schedule_date = today
    # Ограничим окно, чтобы не уйти слишком далеко
    if schedule_date < today - timedelta(days=30):
        schedule_date = today - timedelta(days=30)
    elif schedule_date > today + timedelta(days=MAX_BOOKING_DAYS_AHEAD):
        schedule_date = today + timedelta(days=MAX_BOOKING_DAYS_AHEAD)

    # --- Десктопная календарная сетка (всегда 7 дней, Пн–Вс) ---
    base_date = schedule_date if schedule_date else today
    start_of_week = base_date - timedelta(days=base_date.weekday())  # Пн
    week_days = [start_of_week + timedelta(days=i) for i in range(7)]

    window_start = datetime.combine(start_of_week, datetime.min.time())
    window_end = window_start + timedelta(days=7)

    closures_result = await db.execute(
        select(ScheduleClosure).where(
            ScheduleClosure.salon_id == salon.id,
            ScheduleClosure.date >= start_of_week,
            ScheduleClosure.date < start_of_week + timedelta(days=7),
            (ScheduleClosure.master_id.is_(None)) | (ScheduleClosure.master_id == selected_master.id),
        )
    )
    closures_by_date = {c.date: c for c in closures_result.scalars().all()}

    bookings_result = await db.execute(
        select(Booking).where(
            Booking.master_id == selected_master.id,
            Booking.start_time >= window_start,
            Booking.start_time < window_end,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        ).order_by(Booking.start_time)
    )
    bookings = bookings_result.scalars().all()
    bookings_by_date = {}
    for b in bookings:
        bookings_by_date.setdefault(b.start_time.date(), []).append(b)

    service_ids = {b.service_id for b in bookings}
    client_ids = {b.client_id for b in bookings}
    services_by_id = {s.id: s for s in (
        (await db.execute(select(Service).where(Service.id.in_(service_ids)))).scalars().all() if service_ids else []
    )}
    clients_by_id = {u.id: u for u in (
        (await db.execute(select(UserModel).where(UserModel.id.in_(client_ids)))).scalars().all() if client_ids else []
    )}

    # Определяем рабочие часы для каждого дня недели (по графику салона)
    weekly_hours_cache = {}
    day_hours = {}
    min_hour = max_hour = None
    for d in week_days:
        weekday = d.weekday()
        if weekday not in weekly_hours_cache:
            weekly_hours_cache[weekday] = get_salon_work_hours(salon.working_hours, datetime.combine(d, datetime.min.time()))
        hours = None if d in closures_by_date else weekly_hours_cache[weekday]
        day_hours[d] = hours
        if hours:
            s, e = hours
            min_hour = s.hour if min_hour is None else min(min_hour, s.hour)
            eh = e.hour + (1 if e.minute else 0)
            max_hour = eh if max_hour is None else max(max_hour, eh)

    row_hours = list(range(min_hour, max_hour)) if min_hour is not None else []

    def booking_cell_html(b, day) -> str:
        svc = services_by_id.get(b.service_id)
        client = clients_by_id.get(b.client_id)
        status = "confirmed" if b.status == BookingStatus.CONFIRMED else "pending"
        svc_name = svc.name if svc else "—"
        client_name = client.full_name if client else "Клиент"
        client_phone = client.phone if client else "—"
        price = b.final_price if b.final_price is not None else (svc.price if svc else 0)
        price_str = f"{price:,}".replace(",", " ")
        status_label, _ = _status_label(b.status)
        time_str = f"{b.start_time.strftime('%H:%M')}-{b.end_time.strftime('%H:%M')}"

        seen_html = ""
        if viewer_master_id is not None and b.master_id == viewer_master_id:
            if b.master_seen_at is None:
                seen_html = (
                    f'<button onclick="event.stopPropagation();markSeen({b.id}, this)" '
                    f'title="Отметить, что видели эту запись" class="seen-btn">👁 Видел</button>'
                )
            else:
                seen_html = '<span class="seen-indicator" title="Вы отметили, что видели эту запись">👁 Видели</span>'
        elif viewer_master_id is None:
            seen_html = (
                _hint(f"Мастер видел плановую запись: {b.master_seen_at.strftime('%d.%m.%Y %H:%M')}")
                if b.master_seen_at else
                _hint("Мастер ещё не отмечал, что видел эту запись")
            )

        actions = ""
        if can_manage_schedule and b.status == BookingStatus.PENDING:
            # Запись ещё не подтверждена — салон/мастер принимает или отклоняет.
            actions = f"""
                <button onclick="event.stopPropagation();acceptBooking({b.id})"
                        title="Подтвердить запись" class="complete-btn">{ICON_CHECK_SMALL} Подтвердить</button>
                <button onclick="event.stopPropagation();rejectBooking({b.id})"
                        title="Отклонить запись" class="no-show-btn">{ICON_X} Отклонить</button>
            """
        elif can_manage_schedule and b.status == BookingStatus.CONFIRMED:
            # «Пришёл» доступна не раньше чем за час до начала записи.
            if can_mark_completed_now(b, salon.timezone):
                came_btn = (
                    f'<button onclick="event.stopPropagation();openCompleteModal({b.id}, {b.client_id})" '
                    f'title="Клиент пришёл" class="complete-btn">{ICON_CHECK_SMALL} Пришёл</button>'
                )
            else:
                came_btn = (
                    f'<button disabled title="Доступно за час до начала записи" '
                    f'class="complete-btn">{ICON_CHECK_SMALL} Пришёл</button>'
                )
            actions = f"""
                {came_btn}
                <button onclick="event.stopPropagation();markBooking({b.id}, 'no-show')"
                        title="Клиент не пришёл" class="no-show-btn">{ICON_X} Не пришёл</button>
            """

        is_past = day < today
        wrapper_status_class = "pending" if b.status == BookingStatus.PENDING else "confirmed"
        return f"""
        <div class="schedule-booking-wrapper {wrapper_status_class} {'past-day' if is_past else ''}" data-booking-id="{b.id}">
            <div class="schedule-booking-header">
                <span class="booking-time">{time_str}</span>
                <span class="booking-service">{svc_name}</span>
                <span class="booking-client">{client_name}</span>
                {seen_html}
                <span class="booking-arrow">▼</span>
            </div>
            <div class="schedule-booking-details">
                <div class="detail-row">
                    <span class="detail-label">Клиент:</span>
                    <span class="detail-value">{client_name}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Телефон:</span>
                    <span class="detail-value">{client_phone}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Услуга:</span>
                    <span class="detail-value">{svc_name}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Цена:</span>
                    <span class="detail-value">{price_str} ₽</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Статус:</span>
                    <span class="detail-value status-{status}">{status_label}</span>
                </div>
                {f'<div class="detail-actions">{actions}</div>' if actions else ''}
            </div>
        </div>
        """

    def build_week_grid() -> str:
        day_headers = ""
        day_cols = {h: "" for h in row_hours}
        for d in week_days:
            is_today = d == today
            header_style = "background:var(--color-accent-light)" if is_today else ""
            closure = closures_by_date.get(d)
            hours = day_hours[d]
            if closure:
                closed_label = f'<div class="closed-label">{ICON_LOCK_SMALL} закрыто' + ('' if closure.master_id is None else ' (личное)') + '</div>'
            elif hours is None:
                closed_label = '<div class="closed-label">выходной</div>'
            else:
                closed_label = ""
            day_headers += (
                f'<th style="text-align:center;font-size:0.75rem;padding:0.4rem;min-width:110px;{header_style}">'
                f'{WEEKDAY_NAMES_RU[d.weekday()]} {d.strftime("%d.%m")}{closed_label}</th>'
            )
            for h in row_hours:
                within_hours = bool(hours) and hours[0].hour <= h < (hours[1].hour + (1 if hours[1].minute else 0))
                slot_start = datetime.combine(d, datetime.min.time()).replace(hour=h)
                slot_end = slot_start + timedelta(hours=1)
                # Запись показываем ОДИН раз — в её стартовом часе (в ячейке видно полный интервал времени).
                content = "".join(
                    booking_cell_html(b, d) for b in bookings_by_date.get(d, [])
                    if b.start_time < slot_end and b.end_time > slot_start
                )
                is_past = d < today
                cell_class = "past-day-cell" if is_past else ""
                cell_bg = "" if within_hours else "background: repeating-linear-gradient(45deg, #f3f4f6, #f3f4f6 6px, #fafafa 6px, #fafafa 12px);"
                day_cols[h] += f'<td class="{cell_class}" style="padding:0.2rem;vertical-align:top;{cell_bg}">{content}</td>'

        rows_html = "".join(
            f'<tr><td class="time-label">{h}:00</td>{day_cols[h]}</tr>'
            for h in row_hours
        )
        return f'<div class="schedule-grid"><table><thead><tr><th></th>{day_headers}</tr></thead><tbody>{rows_html}</tbody></table></div>'

    # Навигация по неделям для десктопа
    def _week_url(offset_weeks: int) -> str:
        new_date = start_of_week + timedelta(weeks=offset_weeks)
        params = {
            "tab": "schedule",
            "salon_id": salon.id,
            "schedule_master_id": selected_master.id,
            "date": new_date.isoformat(),
        }
        return f"/business/dashboard?{ '&'.join(f'{k}={v}' for k,v in params.items()) }"

    week_nav_html = f"""
        <div class="schedule-week-nav">
            <a href="{_week_url(-1)}" class="schedule-nav-btn">{ICON_ARROW_LEFT}</a>
            <span class="schedule-week-label">Неделя {start_of_week.strftime('%d.%m')} – {(start_of_week + timedelta(days=6)).strftime('%d.%m')}</span>
            <a href="{_week_url(1)}" class="schedule-nav-btn">{ICON_ARROW_RIGHT}</a>
        </div>
    """

    # Собираем селект мастера
    master_select_options = "".join(
        f'<option value="{m.id}"{" selected" if m.id == selected_master.id else ""}>{master_names.get(m.id, "—")} — {m.specialization}</option>'
        for m in masters
    )
    master_select_html = f"""
    <div class="schedule-master-select">
        <select class="custom-select" onchange="window.location.href='/business/dashboard?tab=schedule&salon_id={salon.id}&schedule_master_id=' + this.value">
            {master_select_options}
        </select>
    </div>
    """

    if not row_hours:
        calendar_html = ('<div class="card" style="padding:2rem;text-align:center;color:var(--color-muted)">'
                          'У салона не задан рабочий график — нечего показывать</div>')
    else:
        calendar_html = f"""
        <div class="schedule-calendar">
            <div class="schedule-week-nav">
                {week_nav_html}
                {master_select_html}
            </div>
            {build_week_grid()}
        </div>"""

    # --- Блок закрытых дат ---
    closures_section = ""
    if can_close_dates:
        upcoming_closures = await ScheduleService.list_closures(db, salon.id, start_of_week)
        closures_html = ""
        for c in upcoming_closures:
            scope = master_names.get(c.master_id, f"Мастер #{c.master_id}") if c.master_id else "Весь салон"
            reason_html = f' — {c.reason}' if c.reason else ''
            closures_html += f"""
            <div class="closure-item">
                <span>{ICON_LOCK_SMALL} {c.date.strftime('%d.%m.%Y')} — {scope}{reason_html}</span>
                <button onclick="reopenClosure({c.id})" class="btn-outline">Открыть</button>
            </div>"""
        closure_master_options = "".join(f'<option value="{m.id}">{master_names.get(m.id, "—")}</option>' for m in masters)

        closures_section = f"""
        <div class="schedule-closures card">
            <div class="schedule-closures-header">
                <h3>{ICON_CALENDAR_SMALL} Закрытые даты</h3>
                <button class="btn-primary" onclick="document.getElementById('closeDateModal').classList.add('active')">{ICON_PLUS_SMALL} Закрыть дату</button>
            </div>
            <div class="schedule-closures-list">
                {closures_html or '<p class="text-muted">Ближайших закрытий нет</p>'}
            </div>
        </div>

        <div class="schedule-modal-overlay" id="closeDateModal">
            <div class="schedule-modal-box">
                <button class="schedule-modal-close" onclick="document.getElementById('closeDateModal').classList.remove('active')">&times;</button>
                <h2>Закрыть дату</h2>
                <div>
                    <label>Дата *</label>
                    <input type="date" id="closeDateInput" class="custom-date" required>
                </div>
                <div>
                    <label>Кто закрывается</label>
                    <select id="closeDateMaster" class="custom-select">
                        <option value="">Весь салон</option>
                        {closure_master_options}
                    </select>
                </div>
                <div>
                    <label>Причина</label>
                    <input type="text" id="closeDateReason" placeholder="Праздник, ремонт, отпуск…">
                </div>
                <button type="button" class="btn-primary" onclick="submitCloseDate()">Закрыть дату</button>
            </div>
        </div>"""

    # --- Формируем данные для JS (мобильная навигация) ---
    week_data = []
    for d in week_days:
        day_bookings = []
        for b in bookings_by_date.get(d, []):
            svc = services_by_id.get(b.service_id)
            client = clients_by_id.get(b.client_id)
            status_label, status_class = _status_label(b.status)
            day_bookings.append({
                "id": b.id,
                "time": b.start_time.strftime("%H:%M"),
                "client_name": client.full_name if client else "Клиент",
                "client_phone": client.phone if client else "",
                "service_name": svc.name if svc else "—",
                "price": b.final_price if b.final_price is not None else (svc.price if svc else 0),
                "status": b.status.value,
                "status_label": status_label,
                "status_class": status_class,
            })
        week_data.append({
            "date": d.isoformat(),
            "day_name": WEEKDAY_NAMES_RU[d.weekday()],
            "bookings": day_bookings,
        })

    week_data_json = json.dumps(week_data, ensure_ascii=False)
    week_days_json = json.dumps([d.isoformat() for d in week_days])

    # --- Мобильный блок ---
    month_ru = ["января", "февраля", "марта", "апреля", "мая", "июня",
                "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    date_label = f"{schedule_date.day} {month_ru[schedule_date.month-1]} {schedule_date.year}"

    js_data = f"""
    <script>
        window.scheduleMasterId = {selected_master.id};
        window.scheduleSalonId = {salon.id};
        window.currentDate = '{schedule_date.isoformat()}';
        window.canManageSchedule = {str(can_manage_schedule).lower()};
        window.weekData = {week_data_json};
        window.weekStart = '{start_of_week.isoformat()}';
        window.weekDays = {week_days_json};
    </script>
    """

    mobile_block = f"""
        <div class="schedule-mobile-container">
            <div class="schedule-mobile-nav">
                <button class="schedule-nav-btn" data-offset="-1" title="Предыдущий день">{ICON_ARROW_LEFT}</button>
                <span class="schedule-nav-date" id="mobile-date-label">{date_label}</span>
                <button class="schedule-nav-btn" data-offset="1" title="Следующий день">{ICON_ARROW_RIGHT}</button>
                <button class="schedule-nav-btn schedule-today-btn" data-offset="0" title="Сегодня">Сегодня</button>
            </div>
            <div class="schedule-mobile-list" id="schedule-mobile-list">
                <!-- Рендерится JS -->
            </div>
        </div>
        {js_data}
    """

    # --- Итоговый HTML ---
    return f"""
    <div id="tab-schedule" class="tab-content">
        {evening_deal_html}
        <!-- Мобильная версия -->
        {mobile_block}

        <!-- Десктопная версия -->
        <div class="schedule-desktop-container">
            {calendar_html}
            <div class="schedule-legend">
                <span><span class="dot confirmed"></span> Подтверждено</span>
                <span><span class="dot pending"></span> Ожидает</span>
                <span><span class="dot closed"></span> Вне графика/закрыто</span>
                <span><span class="dot past"></span> Прошедшие дни</span>
            </div>
            {closures_section}
        </div>


        <!-- Модалка завершения -->
        <div class="schedule-modal-overlay" id="completeBookingModal">
            <div class="schedule-modal-box">
                <button class="schedule-modal-close" onclick="document.getElementById('completeBookingModal').classList.remove('active')">&times;</button>
                <h2>Завершить запись</h2>
                <div id="completeModalBody">Загрузка…</div>
                <button type="button" class="btn-primary" onclick="submitCompleteWithDiscount()">Подтвердить</button>
            </div>
        </div>
    </div>
    """


def _status_label(status: BookingStatus):
    labels = {
        BookingStatus.PENDING: ("Ожидает", "pending"),
        BookingStatus.CONFIRMED: ("Подтверждена", "confirmed"),
        BookingStatus.COMPLETED: ("Завершена", "completed"),
        BookingStatus.CANCELLED: ("Отменена", "cancelled"),
        BookingStatus.NO_SHOW: ("Неявка", "no_show"),
    }
    return labels.get(status, (status.value, "cancelled"))