# app/web/pages/business/tabs/schedule.py
from collections import OrderedDict
from datetime import datetime, timedelta
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
    ICON_CHEVRON_LEFT,
    ICON_CHEVRON_RIGHT,
    ICON_CHEVRON_DOWN,
    ICON_EYE,
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
    viewer_master_id: int = None,
    evening_deal_html: str = "",
) -> str:
    """Вкладка «Расписание»: выбор мастера → неделя → сетка.
    На десктопе навигация по неделям через стрелки, на мобилке — по дням с карточками.
    Все недели отображаются полными (7 дней, Пн–Вс).
    """
    if can_close_dates is None:
        can_close_dates = can_manage_schedule

    if not masters:
        return ('<div id="tab-schedule" class="tab-content"><div class="card" '
                'style="padding:2rem;text-align:center;color:var(--color-muted)">В салоне пока нет мастеров</div></div>')

    master_by_id = {m.id: m for m in masters}
    selected_master = master_by_id.get(schedule_master_id) or masters[0]

    master_names = {}
    for m in masters:
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        master_names[m.id] = mu.full_name if mu else "—"

    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    end_date = start_of_week + timedelta(days=MAX_BOOKING_DAYS_AHEAD + 7)
    days = []
    d = start_of_week
    while d <= end_date:
        days.append(d)
        d += timedelta(days=1)

    window_start = datetime.combine(today, datetime.min.time())
    window_end = window_start + timedelta(days=MAX_BOOKING_DAYS_AHEAD)

    closures_result = await db.execute(
        select(ScheduleClosure).where(
            ScheduleClosure.salon_id == salon.id,
            ScheduleClosure.date >= today,
            ScheduleClosure.date <= end_date,
            (ScheduleClosure.master_id.is_(None)) | (ScheduleClosure.master_id == selected_master.id),
        )
    )
    closures_by_date = {}
    for c in closures_result.scalars().all():
        if c.date not in closures_by_date or c.master_id is not None:
            closures_by_date[c.date] = c

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

    weekly_hours_cache = {}
    day_hours = {}
    min_hour = max_hour = None
    for d in days:
        if d < today or d > today + timedelta(days=MAX_BOOKING_DAYS_AHEAD):
            day_hours[d] = None
            continue
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

    # ---------- ДЕСКТОПНАЯ КАРТОЧКА (с подсказкой, без статусного овала) ----------
    def booking_cell_html(b) -> str:
        svc = services_by_id.get(b.service_id)
        client = clients_by_id.get(b.client_id)
        status = "confirmed" if b.status == BookingStatus.CONFIRMED else "pending"
        svc_name = svc.name if svc else "—"
        client_name = client.full_name if client else "Клиент"
        client_phone = client.phone if client else "—"
        price = b.final_price if b.final_price is not None else (svc.price if svc else 0)
        price_str = f"{price:,}".replace(",", " ")
        status_label = "Подтверждена" if b.status == BookingStatus.CONFIRMED else "Ожидает"
        time_str = f"{b.start_time.strftime('%H:%M')}-{b.end_time.strftime('%H:%M')}"

        seen_html = ""
        if viewer_master_id is not None and b.master_id == viewer_master_id:
            if b.master_seen_at is None:
                seen_html = (
                    f'<button onclick="event.stopPropagation();markSeen({b.id}, this)" '
                    f'title="Отметить, что видели эту запись" class="seen-btn">{ICON_EYE} Видел</button>'
                )
            else:
                seen_html = f'<span class="seen-indicator" title="Вы отметили, что видели эту запись">{ICON_EYE} Видели</span>'
        elif viewer_master_id is None:
            seen_html = (
                _hint(f"Мастер видел плановую запись: {b.master_seen_at.strftime('%d.%m.%Y %H:%M')}")
                if b.master_seen_at else
                _hint("Мастер ещё не отмечал, что видел эту запись")
            )

        actions = ""
        if can_manage_schedule and b.status == BookingStatus.PENDING:
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
                <button onclick="event.stopPropagation();recordMarkBooking({b.id}, 'no-show', this)"
                        title="Клиент не пришёл" class="no-show-btn">{ICON_X} Не пришёл</button>
            """

        wrapper_status_class = "pending" if b.status == BookingStatus.PENDING else "confirmed"

        return f"""
        <div class="schedule-booking-wrapper {wrapper_status_class}" data-booking-id="{b.id}">
            <div class="schedule-booking-header" onclick="toggleDesktopCard(this)">
                <span class="booking-time">{time_str}</span>
                <span class="booking-hint">{seen_html}</span>
                <span class="booking-client" title="{client_name}">{client_name}</span>
                <span class="booking-arrow">{ICON_CHEVRON_DOWN}</span>
            </div>
            <div class="schedule-booking-details">
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

    # ---------- МОБИЛЬНАЯ КАРТОЧКА (белая, статусный овал, без подсказки) ----------
    def mobile_booking_cell_html(b) -> str:
        svc = services_by_id.get(b.service_id)
        client = clients_by_id.get(b.client_id)
        svc_name = svc.name if svc else "—"
        client_name = client.full_name if client else "Клиент"
        client_phone = client.phone if client else "—"
        price = b.final_price if b.final_price is not None else (svc.price if svc else 0)
        price_str = f"{price:,}".replace(",", " ")
        status_label, status_class = ("Подтверждена", "confirmed") if b.status == BookingStatus.CONFIRMED else ("Ожидает", "pending")
        time_str = f"{b.start_time.strftime('%H:%M')}"

        # Кнопки действий (если есть права)
        actions = ""
        if can_manage_schedule and b.status == BookingStatus.PENDING:
            actions = f"""
                <button class="btn-action btn-action-success" onclick="event.stopPropagation();acceptBooking({b.id})">Подтвердить</button>
                <button class="btn-action btn-action-danger" onclick="event.stopPropagation();rejectBooking({b.id})">Отклонить</button>
            """
        elif can_manage_schedule and b.status == BookingStatus.CONFIRMED:
            actions = f"""
                <button class="btn-action btn-action-success" onclick="event.stopPropagation();openCompleteModal({b.id}, {b.client_id})">Пришёл</button>
                <button class="btn-action btn-action-danger" onclick="event.stopPropagation();recordMarkBooking({b.id}, 'no-show', this)">Не пришёл</button>
            """

        return f"""
        <div class="record-card {status_class}" data-booking-id="{b.id}">
            <div class="record-card-header" onclick="toggleRecordCard(this)">
                <div class="record-card-main">
                    <div class="record-card-top">
                        <span class="record-card-date">{time_str}</span>
                        <span class="record-card-status-wrapper">
                            <span class="status-badge {status_class}">{status_label}</span>
                        </span>
                    </div>
                    <div class="record-card-bottom">
                        <span class="record-card-client">{client_name}</span>
                        <span class="record-card-chevron">{ICON_CHEVRON_DOWN}</span>
                    </div>
                </div>
            </div>
            <div class="record-card-body" style="display:none;">
                <div class="record-card-row"><span class="record-card-label">Телефон:</span> <span class="record-card-value">{client_phone}</span></div>
                <div class="record-card-row"><span class="record-card-label">Услуга:</span> <span class="record-card-value">{svc_name}</span></div>
                <div class="record-card-row"><span class="record-card-label">Цена:</span> <span class="record-card-value">{price_str} ₽</span></div>
                {f'<div class="record-card-actions">{actions}</div>' if actions else ''}
            </div>
        </div>
        """

    # ---------- Построение десктопных недель ----------
    def build_week_grid(week_days, week_index) -> str:
        day_headers = ""
        day_cols = {h: "" for h in row_hours}
        for d in week_days:
            is_today = d == today
            is_past = d < today
            is_outside = d > today + timedelta(days=MAX_BOOKING_DAYS_AHEAD)
            header_style = "background:var(--color-accent-light)" if is_today else ""
            closure = closures_by_date.get(d)
            hours = day_hours.get(d)
            if closure:
                closed_label = f'<div style="font-size:0.65rem;color:#ef4444">{ICON_LOCK_SMALL} закрыто' + ('' if closure.master_id is None else ' (личное)') + '</div>'
            elif is_past:
                closed_label = ""
            elif hours is None or is_outside:
                closed_label = '<div style="font-size:0.65rem;color:var(--color-muted)">выходной</div>'
            else:
                closed_label = ""
            day_headers += (
                f'<th style="text-align:center;font-size:0.75rem;padding:0.4rem;min-width:110px;{header_style}">'
                f'{WEEKDAY_NAMES_RU[d.weekday()]} {d.strftime("%d")}{closed_label}</th>'
            )
            for h in row_hours:
                within_hours = bool(hours) and hours[0].hour <= h < (hours[1].hour + (1 if hours[1].minute else 0))
                slot_start = datetime.combine(d, datetime.min.time()).replace(hour=h)
                slot_end = slot_start + timedelta(hours=1)
                content = "".join(
                    booking_cell_html(b) for b in bookings_by_date.get(d, [])
                    if b.start_time.hour == h
                )
                if not within_hours or is_outside:
                    cell_bg = "background:rgba(0,0,0,0.05);"
                else:
                    cell_bg = ""
                past_class = " past-day" if is_past else ""
                day_cols[h] += f'<td class="{past_class}" style="padding:0.2rem;vertical-align:top;{cell_bg}">{content}</td>'

        rows_html = "".join(
            f'<tr><td class="time-label">{h}:00</td>{day_cols[h]}</tr>'
            for h in row_hours
        )
        return f'<div class="schedule-week-panel" data-week-index="{week_index}"><div class="schedule-grid"><table><thead><tr><th></th>{day_headers}</tr></thead><tbody>{rows_html}</tbody></table></div></div>'

    # Группируем дни по неделям для десктопа
    weeks_data = []
    week_index = 0
    for i in range(0, len(days), 7):
        week_days = days[i:i+7]
        while len(week_days) < 7:
            last_day = week_days[-1] + timedelta(days=1)
            week_days.append(last_day)
        first_day = week_days[0]
        month_name = MONTH_NAMES_RU[first_day.month - 1]
        year_str = str(first_day.year)
        weeks_data.append({
            'index': week_index,
            'month_name': month_name,
            'year': year_str,
            'days': week_days,
        })
        week_index += 1

    active_index = 0
    for i, w in enumerate(weeks_data):
        if today in w['days']:
            active_index = i
            break

    weeks_panels_html = ""
    for w in weeks_data:
        panel = build_week_grid(w['days'], w['index'])
        active_class = " active" if w['index'] == active_index else ""
        weeks_panels_html += f'<div class="schedule-week-panel-wrapper{active_class}" data-week-index="{w["index"]}">{panel}</div>'

    # Десктопная навигация
    nav_desktop_html = f"""
    <div class="schedule-nav-desktop">
        <button class="schedule-nav-btn" id="schedulePrevWeek" title="Предыдущая неделя">{ICON_CHEVRON_LEFT}</button>
        <span class="schedule-current-month" id="scheduleCurrentMonth">{weeks_data[active_index]['month_name']} {weeks_data[active_index]['year']}</span>
        <button class="schedule-nav-btn" id="scheduleNextWeek" title="Следующая неделя">{ICON_CHEVRON_RIGHT}</button>
    </div>
    """

    # Селектор мастера (общий)
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

    # ---------- Подготовка мобильных данных ----------
    all_dates = sorted(set(d for d in days if d >= today))
    mobile_bookings_by_date = {}
    for date_obj in all_dates:
        date_str = date_obj.isoformat()
        bookings_list = bookings_by_date.get(date_obj, [])
        cards_html = ""
        for b in bookings_list:
            cards_html += mobile_booking_cell_html(b)
        mobile_bookings_by_date[date_str] = cards_html

    # Мобильный блок
    import json
    all_dates_json = json.dumps([d.isoformat() for d in all_dates])
    mobile_bookings_json = json.dumps(mobile_bookings_by_date)

    mobile_block_html = f"""
    <div class="schedule-mobile-block">
        <div class="schedule-mobile-master-select">
            <select class="custom-select" onchange="window.location.href='/business/dashboard?tab=schedule&salon_id={salon.id}&schedule_master_id=' + this.value">
                {master_select_options}
            </select>
        </div>
        <div class="schedule-mobile-nav">
            <button class="schedule-mobile-nav-btn" id="mobilePrevDay">{ICON_CHEVRON_LEFT}</button>
            <input type="date" id="mobileDatePicker" class="schedule-mobile-datepicker custom-date">
            <button class="schedule-mobile-nav-btn" id="mobileNextDay">{ICON_CHEVRON_RIGHT}</button>
        </div>
        <div class="schedule-mobile-bookings" id="mobileBookingsContainer">
            <!-- Карточки будут вставлены JS -->
        </div>
    </div>
    """

    # ---------- Остальные блоки (без изменений) ----------
    closures_section = ""
    if can_close_dates:
        upcoming_closures = await ScheduleService.list_closures(db, salon.id)
        closures_html = ""
        for c in upcoming_closures:
            scope = master_names.get(c.master_id, f"Мастер #{c.master_id}") if c.master_id else "Весь салон"
            reason_html = f' — {c.reason}' if c.reason else ''
            closures_html += f"""
            <div class="closure-item">
                <span>{ICON_LOCK_SMALL} {c.date.strftime('%d.%m.%Y')} — {scope}{reason_html}</span>
                <button onclick="reopenClosure({c.id})" class="btn-outline" style="font-size:0.75rem;padding:0.25rem 0.6rem">Открыть</button>
            </div>"""

        closure_master_options = "".join(f'<option value="{m.id}">{master_names.get(m.id, "—")}</option>' for m in masters)

        closures_section = f"""
        <div class="schedule-closures card">
            <div class="schedule-closures-header">
                <h3>{ICON_CALENDAR_SMALL} Закрытые даты</h3>
                <button class="btn-primary" style="font-size:0.85rem;padding:0.5rem 1rem" onclick="document.getElementById('closeDateModal').classList.add('active')">{ICON_PLUS_SMALL} Закрыть дату</button>
            </div>
            <div class="schedule-closures-list">
                {closures_html or '<p class="text-muted" style="font-size:0.85rem">Ближайших закрытий нет</p>'}
            </div>
        </div>

        <div class="schedule-modal-overlay" id="closeDateModal">
            <div class="schedule-modal-box">
                <button class="schedule-modal-close" onclick="document.getElementById('closeDateModal').classList.remove('active')">&times;</button>
                <h2 style="margin-bottom:1.5rem">Закрыть дату</h2>
                <div style="margin-bottom:1rem">
                    <label style="display:block;font-weight:500;margin-bottom:0.5rem">Дата *</label>
                    <input type="date" id="closeDateInput" required style="width:100%;padding:0.75rem;border:1px solid var(--color-border);border-radius:0.5rem">
                </div>
                <div style="margin-bottom:1rem">
                    <label style="display:block;font-weight:500;margin-bottom:0.5rem">Кто закрывается</label>
                    <select id="closeDateMaster" class="custom-select">
                        <option value="">Весь салон</option>
                        {closure_master_options}
                    </select>
                </div>
                <div style="margin-bottom:1rem">
                    <label style="display:block;font-weight:500;margin-bottom:0.5rem">Причина</label>
                    <input type="text" id="closeDateReason" placeholder="Праздник, ремонт, отпуск…" style="width:100%;padding:0.75rem;border:1px solid var(--color-border);border-radius:0.5rem">
                </div>
                <button type="button" class="btn-primary" style="width:100%" onclick="submitCloseDate()">Закрыть дату</button>
            </div>
        </div>"""

    # График работы мастера
    sched_rows = (await db.execute(
        select(Schedule).where(Schedule.master_id == selected_master.id)
        .order_by(Schedule.day_of_week, Schedule.start_time)
    )).scalars().all()
    by_day: dict[int, list] = {i: [] for i in range(7)}
    for r in sched_rows:
        by_day[r.day_of_week].append((r.start_time.strftime("%H:%M"), r.end_time.strftime("%H:%M")))
    has_custom_schedule = len(sched_rows) > 0
    can_edit_schedule = can_manage_schedule or (
        viewer_master_id is not None and viewer_master_id == selected_master.id
    )

    summary_rows = ""
    for d in range(7):
        if not has_custom_schedule:
            value = '<span class="text-muted">по часам салона</span>'
        elif by_day[d]:
            value = " · ".join(f"{s}–{e}" for s, e in by_day[d])
        else:
            value = '<span class="text-muted">выходной</span>'
        summary_rows += (
            f'<div class="mschedule-row"><span class="mschedule-day">{WEEKDAY_NAMES_RU[d]}</span>'
            f'<span class="mschedule-val">{value}</span></div>'
        )

    edit_btn = (
        f'<button class="btn-primary" style="font-size:0.85rem;padding:0.5rem 1rem" '
        f'onclick="openMasterScheduleModal()">{ICON_PLUS_SMALL} Изменить график</button>'
    ) if can_edit_schedule else ''

    schedule_work_section = f"""
        <div class="mschedule card">
            <div class="mschedule-header">
                <h3>{ICON_CALENDAR_SMALL} График работы — {master_names.get(selected_master.id, "—")}</h3>
                {edit_btn}
            </div>
            <div class="mschedule-list">{summary_rows}</div>
            <p class="text-muted" style="font-size:0.8rem;margin-top:0.75rem">
                Если график не задан — мастер работает по часам салона. Заданный график
                ограничивает время, доступное клиентам для записи (в пределах часов салона).
            </p>
        </div>"""

    master_schedule_modal = ""
    if can_edit_schedule:
        day_blocks = ""
        for d in range(7):
            intervals = by_day[d] if has_custom_schedule else []
            rows_html = "".join(
                f'<div class="mschedule-edit-row">'
                f'<input type="time" class="ms-start" value="{s}">'
                f'<span class="mschedule-edit-dash">–</span>'
                f'<input type="time" class="ms-end" value="{e}">'
                f'<button type="button" class="mschedule-edit-del" '
                f'onclick="this.closest(\'.mschedule-edit-row\').remove()">&times;</button>'
                f'</div>'
                for s, e in intervals
            )
            day_blocks += f"""
                <div class="mschedule-edit-day" data-day="{d}">
                    <div class="mschedule-edit-day-head">
                        <strong>{WEEKDAY_NAMES_FULL_RU[d]}</strong>
                        <button type="button" class="btn-outline" style="font-size:0.75rem;padding:0.2rem 0.55rem" onclick="msAddRow({d})">{ICON_PLUS_SMALL} интервал</button>
                    </div>
                    <div class="mschedule-edit-rows" id="msRows{d}">{rows_html}</div>
                </div>"""

        master_schedule_modal = f"""
        <div class="schedule-modal-overlay" id="masterScheduleModal">
            <div class="schedule-modal-box mschedule-edit-box">
                <button class="schedule-modal-close" onclick="document.getElementById('masterScheduleModal').classList.remove('active')">&times;</button>
                <h2 style="margin-bottom:0.5rem">График работы</h2>
                <p class="text-muted" style="font-size:0.8rem;margin-bottom:1rem">
                    Оставьте день пустым — это выходной. Несколько интервалов в дне —
                    сплит-смена (например 09:00–13:00 и 16:00–20:00).
                </p>
                <input type="hidden" id="msMasterId" value="{selected_master.id}">
                <div class="mschedule-edit-days">{day_blocks}</div>
                <button type="button" class="btn-primary" style="width:100%;margin-top:1rem" onclick="saveMasterSchedule()">Сохранить график</button>
            </div>
        </div>"""

    weeks_json = json.dumps([
        {
            'index': w['index'],
            'month_name': w['month_name'],
            'year': w['year'],
            'first_day': w['days'][0].strftime('%Y-%m-%d'),
        }
        for w in weeks_data
    ])

    # Итоговый HTML
    return f"""
    <div id="tab-schedule" class="tab-content">
        {evening_deal_html}
        <div class="schedule-desktop-block">
            <div class="schedule-calendar">
                <div class="schedule-nav-wrapper">
                    {nav_desktop_html}
                    {master_select_html}
                </div>
                <div class="schedule-weeks-container" id="scheduleWeeksContainer">
                    {weeks_panels_html}
                </div>
            </div>
        </div>

        {mobile_block_html}

        <div class="schedule-legend-wrapper">
            <div class="schedule-legend">
                <span><span class="dot confirmed"></span> Подтверждено</span>
                <span><span class="dot pending"></span> Ожидает</span>
                <span><span class="dot closed"></span> Вне графика/закрыто</span>
            </div>
        </div>

        {schedule_work_section}
        {closures_section}
    </div>

    {master_schedule_modal}

    <div class="schedule-modal-overlay" id="completeBookingModal">
        <div class="schedule-modal-box">
            <button class="schedule-modal-close" onclick="document.getElementById('completeBookingModal').classList.remove('active')">&times;</button>
            <h2 style="margin-bottom:1rem">Завершить запись</h2>
            <div id="completeModalBody" style="font-size:0.9rem">Загрузка…</div>
            <button type="button" class="btn-primary" style="width:100%;margin-top:1rem" onclick="submitCompleteWithDiscount()">Подтвердить</button>
        </div>
    </div>

    <script>
        window.weekData = {weeks_json};
        window.activeWeekIndex = {active_index};
        window.mobileAllDates = {all_dates_json};
        window.mobileBookingsByDate = {mobile_bookings_json};
        window.mobileToday = "{today.isoformat()}";
    </script>
    """