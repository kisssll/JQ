# app/web/pages/business/tabs/records.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta

from app.models.models import Booking, BookingStatus, Service as ServiceModel, User as UserModel
from app.services.schedule_utils import MAX_BOOKING_DAYS_AHEAD
from app.web.components.icons import (
    ICON_CALENDAR_DAYS,
    ICON_USER_CHECK,
    ICON_FILTER,
    ICON_CHEVRON_DOWN,
    ICON_CHEVRON_UP,
)

STATUS_LABELS = {
    BookingStatus.PENDING: ("Ожидает", "pending"),
    BookingStatus.CONFIRMED: ("Подтверждена", "confirmed"),
    BookingStatus.COMPLETED: ("Завершена", "completed"),
    BookingStatus.CANCELLED: ("Отменена", "cancelled"),
    BookingStatus.NO_SHOW: ("Неявка", "no_show"),
}


async def render_records_tab(db: AsyncSession, salon, masters, master_ids, filters: dict, can_manage_schedule: bool = False) -> str:
    """Вкладка «Записи» — полный список броней салона с фильтрами."""

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    default_from = today - timedelta(days=30)
    default_to = today + timedelta(days=MAX_BOOKING_DAYS_AHEAD + 1)

    def parse_date(value, fallback):
        if not value:
            return fallback
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return fallback

    date_from = parse_date(filters.get("date_from"), default_from)
    date_to = parse_date(filters.get("date_to"), default_to - timedelta(days=1)) + timedelta(days=1)
    filter_master_id = filters.get("master_id") or ""
    filter_status = filters.get("status") or ""

    rows_data = []
    if master_ids:
        query = (
            select(Booking, ServiceModel)
            .join(ServiceModel, ServiceModel.id == Booking.service_id)
            .where(
                Booking.master_id.in_(master_ids),
                Booking.start_time >= date_from,
                Booking.start_time < date_to,
            )
        )
        if filter_master_id.isdigit():
            query = query.where(Booking.master_id == int(filter_master_id))
        if filter_status:
            try:
                query = query.where(Booking.status == BookingStatus(filter_status))
            except ValueError:
                pass
        result = await db.execute(query.order_by(Booking.start_time.desc()).limit(200))
        rows_data = result.all()

    master_user_names = {}
    for m in masters:
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        master_user_names[m.id] = mu.full_name if mu else "—"

    clients_by_id = {}
    for b, s in rows_data:
        if b.client_id not in clients_by_id:
            cu = (await db.execute(select(UserModel).where(UserModel.id == b.client_id))).scalar_one_or_none()
            clients_by_id[b.client_id] = cu.full_name or cu.phone if cu else "—"

    # --- Десктопная таблица ---
    rows_html = ""
    for b, s in rows_data:
        label, status_class = STATUS_LABELS.get(b.status, (b.status.value, "cancelled"))
        price = f"{(b.final_price or s.price):,}".replace(",", " ")
        needs_badge = b.status == BookingStatus.COMPLETED and not b.consumption_reported
        badge = f'<span class="not-reported-badge">не списано</span>' if needs_badge else ""
        actions = ""
        if can_manage_schedule and b.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            actions = f"""
            <button class="btn-action btn-action-success" onclick="recordMarkBooking({b.id}, 'complete', this)">Пришёл</button>
            <button class="btn-action btn-action-danger" onclick="recordMarkBooking({b.id}, 'no-show', this)">Не пришёл</button>
            """
        rows_html += f"""
        <tr>
            <td>{b.start_time.strftime('%d.%m.%Y %H:%M')}</td>
            <td>{clients_by_id.get(b.client_id, '—')}</td>
            <td>{master_user_names.get(b.master_id, '—')}</td>
            <td>{s.name}</td>
            <td><span class="status-badge {status_class}">{label}</span>{badge}</td>
            <td>{price} ₽</td>
            <td class="records-actions">{actions}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="7" class="records-empty">Записей за период нет</td></tr>'

    # --- Мобильные карточки (новая структура) ---
    cards_html = ""
    for b, s in rows_data:
        label, status_class = STATUS_LABELS.get(b.status, (b.status.value, "cancelled"))
        price = f"{(b.final_price or s.price):,}".replace(",", " ")
        needs_badge = b.status == BookingStatus.COMPLETED and not b.consumption_reported
        badge = f'<span class="not-reported-badge">не списано</span>' if needs_badge else ""
        actions = ""
        if can_manage_schedule and b.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            actions = f"""
            <button class="btn-action btn-action-success" onclick="recordMarkBooking({b.id}, 'complete', this)">Пришёл</button>
            <button class="btn-action btn-action-danger" onclick="recordMarkBooking({b.id}, 'no-show', this)">Не пришёл</button>
            """
        cards_html += f"""
        <div class="record-card" data-booking-id="{b.id}">
            <div class="record-card-header" onclick="toggleRecordCard(this)">
                <div class="record-card-main">
                    <div class="record-card-top">
                        <span class="record-card-date">{b.start_time.strftime('%d.%m.%Y %H:%M')}</span>
                        <span class="record-card-status-wrapper">
                            <span class="status-badge {status_class}">{label}</span>
                            {badge}
                        </span>
                    </div>
                    <div class="record-card-bottom">
                        <span class="record-card-client">{clients_by_id.get(b.client_id, '—')}</span>
                        <span class="record-card-chevron">{ICON_CHEVRON_DOWN}</span>
                    </div>
                </div>
            </div>
            <div class="record-card-body" style="display:none;">
                <div class="record-card-row"><span class="record-card-label">Мастер:</span> {master_user_names.get(b.master_id, '—')}</div>
                <div class="record-card-row"><span class="record-card-label">Услуга:</span> {s.name}</div>
                <div class="record-card-row"><span class="record-card-label">Сумма:</span> {price} ₽</div>
                <div class="record-card-actions">{actions}</div>
            </div>
        </div>"""

    if not cards_html:
        cards_html = '<div class="records-empty">Записей за период нет</div>'

    # --- Фильтры ---
    master_options = "".join(
        f'<option value="{m.id}"{" selected" if filter_master_id == str(m.id) else ""}>{master_user_names.get(m.id, "—")}</option>'
        for m in masters
    )
    status_options = "".join(
        f'<option value="{st.value}"{" selected" if filter_status == st.value else ""}>{label}</option>'
        for st, (label, _color) in STATUS_LABELS.items()
    )

    filters_form = f"""
    <form method="get" action="/business/dashboard" class="records-filters">
        <input type="hidden" name="salon_id" value="{salon.id}">
        <input type="hidden" name="tab" value="records">

        <div class="filter-group">
            <label for="date_from">С даты</label>
            <input type="date" id="date_from" name="date_from" value="{date_from.strftime('%Y-%m-%d')}">
        </div>
        <div class="filter-group">
            <label for="date_to">По дату</label>
            <input type="date" id="date_to" name="date_to" value="{(date_to - timedelta(days=1)).strftime('%Y-%m-%d')}">
        </div>
        <div class="filter-group">
            <label for="master_id">Мастер</label>
            <select id="master_id" name="master_id">
                <option value="">Все мастера</option>
                {master_options}
            </select>
        </div>
        <div class="filter-group">
            <label for="status">Статус</label>
            <select id="status" name="status">
                <option value="">Все статусы</option>
                {status_options}
            </select>
        </div>
        <button type="submit" class="btn-outline records-apply-btn">{ICON_FILTER} Применить</button>
    </form>
    """

    # --- Аккордеон для мобильных фильтров ---
    filters_mobile = f"""
    <div class="records-filters-mobile">
        <button class="records-filters-toggle" onclick="toggleFiltersMobile()">
            {ICON_FILTER} Фильтры <span class="filters-toggle-chevron">{ICON_CHEVRON_DOWN}</span>
        </button>
        <div class="records-filters-collapse" style="display:none;">
            {filters_form}
        </div>
    </div>
    """

    # Итоговый HTML
    return f"""
    <div id="tab-records" class="tab-content records-tab">
        <!-- Десктопные фильтры -->
        <div class="records-filters-desktop">
            {filters_form}
        </div>

        <!-- Мобильные фильтры (аккордеон) -->
        {filters_mobile}

        <!-- Десктопная таблица -->
        <div class="records-table-desktop">
            <div class="card records-table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>{ICON_CALENDAR_DAYS} Дата</th>
                            <th>{ICON_USER_CHECK} Клиент</th>
                            <th>Мастер</th>
                            <th>Услуга</th>
                            <th>Статус</th>
                            <th>Сумма</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Мобильные карточки -->
        <div class="records-mobile">
            {cards_html}
        </div>
    </div>

    <script>
        function recordMarkBooking(bookingId, action, btn) {{
            const label = action === 'complete' ? 'что клиент пришёл' : 'неявку клиента';
            if (!confirm(`Отметить ${{label}}?`)) return;
            fetch(`/api/v1/bookings/${{bookingId}}/${{action}}`, {{ method: 'POST' }})
                .then(r => {{
                    if (r.ok) location.reload();
                    else r.json().then(d => alert(d.detail || 'Ошибка'));
                }});
        }}

        function toggleRecordCard(header) {{
            const body = header.nextElementSibling;
            const chevron = header.querySelector('.record-card-chevron');
            if (body.style.display === 'none') {{
                body.style.display = 'block';
                chevron.innerHTML = `{ICON_CHEVRON_UP}`;
            }} else {{
                body.style.display = 'none';
                chevron.innerHTML = `{ICON_CHEVRON_DOWN}`;
            }}
        }}

        function toggleFiltersMobile() {{
            const collapse = document.querySelector('.records-filters-collapse');
            const chevron = document.querySelector('.filters-toggle-chevron');
            if (collapse.style.display === 'none') {{
                collapse.style.display = 'block';
                chevron.innerHTML = `{ICON_CHEVRON_UP}`;
            }} else {{
                collapse.style.display = 'none';
                chevron.innerHTML = `{ICON_CHEVRON_DOWN}`;
            }}
        }}
    </script>
    """