# app/web/pages/business/tabs/schedule.py
from collections import OrderedDict
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Booking, Master, Service, User as UserModel, BookingStatus, ScheduleClosure, Schedule
from app.services.schedule_utils import get_salon_work_hours, MAX_BOOKING_DAYS_AHEAD
from app.services.schedule_service import ScheduleService
from app.web.components.hint import hint as _hint
from app.web.components.icons import (
    ICON_CHECK_SMALL,
    ICON_X,
    ICON_PLUS_SMALL,
    ICON_LOCK_SMALL,
    ICON_CALENDAR_SMALL,
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
) -> str:
    """Вкладка «Расписание»: выбор мастера → месяц → неделя → сетка

    дни×часы на MAX_BOOKING_DAYS_AHEAD (2 месяца) вперёд, плюс закрытие дат.

    can_manage_schedule — можно отмечать записи выполненными/неявкой (владелец/
    админ салона, либо сам мастер — на своих записях это уже разрешено бэкендом
    независимо от SalonMember). can_close_dates по умолчанию равен
    can_manage_schedule (владелец/админ), но у мастера, просматривающего только
    свой календарь, эти права разные: закрытие дат требует SalonMember,
    которого у мастера нет, поэтому вызывающий код передаёт False явно.

    viewer_master_id — id профиля Master текущего пользователя, если он сам
    мастер (просматривает свой календарь): тогда у его записей показывается
    кнопка «Видел». Для владельца/админа (viewer_master_id=None) вместо кнопки
    показывается только индикатор с подсказкой — сам он это отметить не может,
    это личное подтверждение мастера."""

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
    days = [today + timedelta(days=i) for i in range(MAX_BOOKING_DAYS_AHEAD)]
    window_start = datetime.combine(today, datetime.min.time())
    window_end = window_start + timedelta(days=MAX_BOOKING_DAYS_AHEAD)

    closures_result = await db.execute(
        select(ScheduleClosure).where(
            ScheduleClosure.salon_id == salon.id,
            ScheduleClosure.date >= today,
            ScheduleClosure.date < today + timedelta(days=MAX_BOOKING_DAYS_AHEAD),
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
            # Сам мастер смотрит свою запись — может отметить «Видел», если ещё не отметил.
            if b.master_seen_at is None:
                seen_html = (
                    f'<button onclick="event.stopPropagation();markSeen({b.id}, this)" '
                    f'title="Отметить, что видели эту запись" class="seen-btn">👁 Видел</button>'
                )
            else:
                seen_html = '<span class="seen-indicator" title="Вы отметили, что видели эту запись">👁 Видели</span>'
        elif viewer_master_id is None:
            # Владелец/админ — только индикатор, отметить за мастера нельзя.
            seen_html = (
                _hint(f"Мастер видел плановую запись: {b.master_seen_at.strftime('%d.%m.%Y %H:%M')}")
                if b.master_seen_at else
                _hint("Мастер ещё не отмечал, что видел эту запись")
            )

        actions = ""
        if can_manage_schedule and b.status == BookingStatus.CONFIRMED:
            actions = f"""
                <button onclick="event.stopPropagation();openCompleteModal({b.id}, {b.client_id})"
                        title="Выполнено" class="complete-btn">{ICON_CHECK_SMALL} Выполнено</button>
                <button onclick="event.stopPropagation();markBooking({b.id}, 'no-show')"
                        title="Неявка" class="no-show-btn">{ICON_X} Неявка</button>
            """

        return f"""
        <div class="schedule-booking-wrapper" data-booking-id="{b.id}">
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

    def build_week_grid(week_days) -> str:
        day_headers = ""
        day_cols = {h: "" for h in row_hours}
        for d in week_days:
            is_today = d == today
            header_style = "background:var(--color-accent-light)" if is_today else ""
            closure = closures_by_date.get(d)
            hours = day_hours[d]
            if closure:
                closed_label = f'<div style="font-size:0.65rem;color:#ef4444">{ICON_LOCK_SMALL} закрыто' + ('' if closure.master_id is None else ' (личное)') + '</div>'
            elif hours is None:
                closed_label = '<div style="font-size:0.65rem;color:var(--color-muted)">выходной</div>'
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
                content = "".join(
                    booking_cell_html(b) for b in bookings_by_date.get(d, [])
                    if b.start_time < slot_end and b.end_time > slot_start
                )
                cell_bg = "" if within_hours else "background:repeating-linear-gradient(45deg,#f3f4f6,#f3f4f6 6px,#fafafa 6px,#fafafa 12px)"
                day_cols[h] += f'<td style="padding:0.2rem;vertical-align:top;{cell_bg}">{content}</td>'

        rows_html = "".join(
            f'<tr><td class="time-label">{h}:00</td>{day_cols[h]}</tr>'
            for h in row_hours
        )
        return f'<div class="schedule-grid"><table><thead><tr><th></th>{day_headers}</tr></thead><tbody>{rows_html}</tbody></table></div>'

    months = OrderedDict()
    for d in days:
        months.setdefault((d.year, d.month), []).append(d)

    def split_weeks(month_days):
        weeks, cur = [], []
        for d in month_days:
            if cur and d.weekday() == 0:
                weeks.append(cur)
                cur = []
            cur.append(d)
        if cur:
            weeks.append(cur)
        return weeks

    # Строим селект мастера
    master_select_options = "".join(
        f'<option value="{m.id}"{" selected" if m.id == selected_master.id else ""}>{master_names.get(m.id, "—")} — {m.specialization}</option>'
        for m in masters
    )
    master_select_html = f"""
    <div class="schedule-master-select">
        <select onchange="window.location.href='/business/dashboard?tab=schedule&salon_id={salon.id}&schedule_master_id=' + this.value">
            {master_select_options}
        </select>
    </div>
    """

    if not row_hours:
        calendar_html = ('<div class="card" style="padding:2rem;text-align:center;color:var(--color-muted)">'
                          'У салона не задан рабочий график — нечего показывать</div>')
    else:
        month_tabs = ""
        month_panels = ""
        for mi, ((year, month), month_days) in enumerate(months.items()):
            month_key = f"{year}-{month:02d}"
            weeks = split_weeks(month_days)

            week_tabs = ""
            week_panels = ""
            for wi, week_days in enumerate(weeks):
                week_id = f"{month_key}-w{wi}"
                label = f"{week_days[0].strftime('%d.%m')}–{week_days[-1].strftime('%d.%m')}"
                active_week = " active" if wi == 0 else ""
                week_tabs += (
                    f'<button class="schedule-week-btn{active_week}" data-month="{month_key}" data-week="{week_id}" '
                    f'onclick="showWeek(\'{month_key}\',\'{week_id}\')">{label}</button>'
                )
                active_panel = " active" if wi == 0 else ""
                week_panels += (
                    f'<div class="schedule-week-panel{active_panel}" id="week-{week_id}" data-month="{month_key}">'
                    f'{build_week_grid(week_days)}</div>'
                )

            active_month = " active" if mi == 0 else ""
            month_tabs += f'<button class="schedule-month-btn{active_month}" data-month="{month_key}" onclick="showMonth(\'{month_key}\')">{MONTH_NAMES_RU[month - 1]} {year}</button>'
            month_panels += f"""
            <div class="schedule-month-panel{active_month}" id="month-{month_key}">
                <div class="schedule-week-tabs">{week_tabs}</div>
                {week_panels}
            </div>"""

        calendar_html = f"""
        <div class="schedule-calendar">
            <div class="schedule-month-nav">
                <div class="schedule-month-buttons">
                    {month_tabs}
                </div>
                {master_select_html}
            </div>
            {month_panels}
        </div>"""


    master_select_options = "".join(
        f'<option value="{m.id}"{" selected" if m.id == selected_master.id else ""}>{master_names.get(m.id, "—")} — {m.specialization}</option>'
        for m in masters
    )


    # Закрытие дат — отдельное право от отметки записей (см. docstring)
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
                    <select id="closeDateMaster" style="width:100%;padding:0.75rem;border:1px solid var(--color-border);border-radius:0.5rem">
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

    # --- Индивидуальный недельный график выбранного мастера ---
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

    # Модалка редактора графика — только тем, кто может править
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

    return f"""
    <div id="tab-schedule" class="tab-content">
        {calendar_html}

        <div class="schedule-legend">
            <span><span class="dot confirmed"></span> Подтверждено</span>
            <span><span class="dot pending"></span> Ожидает</span>
            <span><span class="dot closed"></span> Вне графика/закрыто</span>
        </div>

        {schedule_work_section}

        {closures_section}
    </div>

    {master_schedule_modal}

    <!-- Модалка завершения записи -->
    <div class="schedule-modal-overlay" id="completeBookingModal">
        <div class="schedule-modal-box">
            <button class="schedule-modal-close" onclick="document.getElementById('completeBookingModal').classList.remove('active')">&times;</button>
            <h2 style="margin-bottom:1rem">Завершить запись</h2>
            <div id="completeModalBody" style="font-size:0.9rem">Загрузка…</div>
            <button type="button" class="btn-primary" style="width:100%;margin-top:1rem" onclick="submitCompleteWithDiscount()">Подтвердить</button>
        </div>
    </div>
    """