# app/web/pages/business/master_dashboard.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from app.models.models import Master, Salon, Service, Promotion, Booking, BookingStatus
from app.services.inventory_service import InventoryService
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.pages.business.utils import get_masters_data, get_master_ids, get_overview_revenue_data
from app.web.pages.business.tabs.overview import render_overview_tab
from app.web.pages.business.tabs.schedule import render_schedule_tab
from app.web.components.icons import (
    ICON_ALERT_TRIANGLE,
    ICON_CALENDAR_DAYS,
    ICON_CHART_COLUMN,
    ICON_FLAG,
)


async def _render_master_overview(db: AsyncSession, salon: Salon, master: Master) -> str:
    """Обзор для мастера: общая картина салона (как у владельца) + отдельным
    блоком личная статистика — мастеру незачем видеть чужую выручку, но
    масштаб салона (сколько мастеров/акций/записей сегодня) полезен для
    контекста."""
    masters, _rows = await get_masters_data(db, salon.id)
    master_ids = get_master_ids(masters)

    services_count = 0
    if master_ids:
        svc = await db.execute(select(func.count(Service.id)).where(Service.master_id.in_(master_ids)))
        services_count = svc.scalar() or 0

    promotions = (await db.execute(select(Promotion).where(Promotion.salon_id == salon.id))).scalars().all()

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())

    overview_data = await get_overview_revenue_data(db, master_ids)

    my_today = (await db.execute(select(func.count(Booking.id)).where(
        Booking.master_id == master.id, Booking.start_time >= today, Booking.start_time < tomorrow,
    ))).scalar() or 0
    my_week = (await db.execute(select(func.count(Booking.id)).where(
        Booking.master_id == master.id, Booking.start_time >= week_start, Booking.start_time < week_start + timedelta(days=7),
    ))).scalar() or 0
    my_unreported = (await db.execute(select(func.count(Booking.id)).where(
        Booking.master_id == master.id, Booking.status == BookingStatus.COMPLETED, Booking.consumption_reported == False,
    ))).scalar() or 0

    overview_html = await render_overview_tab(
        db, salon, masters, master_ids, services_count, promotions, **overview_data,
    )
    personal_html = f"""
    <div class="card" style="margin-top:1.5rem">
        <h3 style="margin-bottom:1rem">Ваша статистика</h3>
        <div class="grid-3">
            <div class="stat-card"><div class="stat-value">{my_today}</div><div class="stat-label">Ваших записей сегодня</div></div>
            <div class="stat-card"><div class="stat-value">{my_week}</div><div class="stat-label">Ваших записей за неделю</div></div>
            <div class="stat-card"><div class="stat-value" style="color:#f59e0b">{my_unreported}</div><div class="stat-label">Не списано расходников</div></div>
        </div>
    </div>"""
    warehouse_html = await _render_master_warehouse_card(db, salon, master)
    return overview_html.replace("</div>\n    </div>", "</div>\n    </div>" + personal_html + warehouse_html, 1)


async def _render_master_warehouse_card(db: AsyncSession, salon: Salon, master: Master) -> str:
    """Мастер сигналит о проблемах склада: расходник заканчивается (без
    точного остатка) или техника салона сломалась. Заявка уходит в очередь
    на вкладке «Склад» у владельца/админа — без пуш-уведомления, они
    сознательно не строим сейчас."""
    from app.models.models import EquipmentStatus

    my_stock = await InventoryService.get_master_stock(db, master.id)
    equipment_list = await InventoryService.get_salon_equipment(db, salon.id)

    stock_rows = "".join(
        f'<div style="display:flex;justify-content:space-between;align-items:center;padding:0.5rem 0;'
        f'border-bottom:1px solid var(--color-border)">'
        f'<span>{i.name} <span class="text-muted" style="font-size:0.8rem">(остаток {i.quantity:g} {i.unit})</span></span>'
        f'<button class="btn-outline" style="font-size:0.75rem;padding:0.3rem 0.7rem" '
        f'onclick="reportWarehouseIssue(\'consumable_low\', {i.id}, null)">{ICON_FLAG} Заканчивается</button>'
        f'</div>'
        for i in my_stock
    )
    equipment_rows = "".join(
        f'<div style="display:flex;justify-content:space-between;align-items:center;padding:0.5rem 0;'
        f'border-bottom:1px solid var(--color-border)">'
        f'<span>{eq.name} <span class="text-muted" style="font-size:0.8rem">({eq.quantity} шт)</span></span>'
        f'<button class="btn-outline" style="font-size:0.75rem;padding:0.3rem 0.7rem" '
        f'onclick="reportWarehouseIssue(\'equipment_broken\', null, {eq.id})">{ICON_FLAG} Сломалось</button>'
        f'</div>'
        for eq in equipment_list if eq.status == EquipmentStatus.WORKING
    )

    return f"""
    <div class="card" style="margin-top:1.5rem">
        <h3 style="margin-bottom:1rem">Склад</h3>
        <div class="grid-2">
            <div>
                <h4 style="font-size:0.9rem;margin-bottom:0.5rem;color:var(--color-muted)">Ваши расходники</h4>
                {stock_rows or '<p class="text-muted" style="font-size:0.85rem">Пусто</p>'}
            </div>
            <div>
                <h4 style="font-size:0.9rem;margin-bottom:0.5rem;color:var(--color-muted)">Техника салона</h4>
                {equipment_rows or '<p class="text-muted" style="font-size:0.85rem">Пусто</p>'}
            </div>
        </div>
    </div>
    <script>
        async function reportWarehouseIssue(type, itemId, equipmentId) {{
            const comment = prompt(type === 'consumable_low' ? 'Что именно заканчивается? (необязательно)' : 'Что случилось с техникой? (необязательно)', '');
            if (comment === null) return;
            const body = new URLSearchParams({{ request_type: type, comment: comment || '' }});
            if (itemId) body.append('item_id', itemId);
            if (equipmentId) body.append('equipment_id', equipmentId);
            const res = await fetch('/api/v1/inventory/requests', {{ method: 'POST', body }});
            if (res.ok) alert('Заявка отправлена администратору'); else alert('Не удалось отправить заявку');
        }}
    </script>
    """


async def _render_master_schedule(db: AsyncSession, salon: Salon, master: Master) -> str:
    """Расписание для мастера: только свой календарь (без выбора мастера —
    список из одного), можно отмечать свои записи выполненными/неявкой (уже
    разрешено бэкендом), закрытие дат недоступно (нужен SalonMember)."""
    calendar_html = await render_schedule_tab(
        db, salon, [master], can_manage_schedule=True, schedule_master_id=master.id, can_close_dates=False,
        viewer_master_id=master.id,
    )

    unreported_result = await db.execute(
        select(Booking).where(
            Booking.master_id == master.id,
            Booking.status == BookingStatus.COMPLETED,
            Booking.consumption_reported == False,
        ).order_by(Booking.start_time.desc()).limit(20)
    )
    unreported = unreported_result.scalars().all()

    unreported_card = ""
    if unreported:
        rows = "".join(
            f'<tr><td>{b.start_time.strftime("%d.%m.%Y %H:%M")}</td>'
            f'<td><button class="btn-primary" style="padding:0.4rem 0.9rem;font-size:0.8rem" '
            f'onclick="openConsumptionModal({b.id})">Списать расходники</button></td></tr>'
            for b in unreported
        )
        unreported_card = f"""
        <div class="card" style="overflow-x:auto;margin-bottom:1.5rem;border:2px solid #f59e0b">
            <h3 style="margin-bottom:1rem">{ICON_ALERT_TRIANGLE} Требуют списания расходников</h3>
            <table><thead><tr><th>Дата</th><th></th></tr></thead><tbody>{rows}</tbody></table>
        </div>"""

    calendar_html = calendar_html.replace(
        '<div id="tab-schedule" class="tab-content">',
        f'<div id="tab-schedule" class="tab-content">{unreported_card}',
        1,
    )

    stock = await InventoryService.get_master_stock(db, master.id)
    stock_options = "".join(
        f'<div class="consumption-line" data-item-id="{i.id}" style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem">'
        f'<label style="flex:1;font-size:0.875rem">{i.name} <span class="text-muted">(остаток {i.quantity:g} {i.unit})</span></label>'
        f'<input type="number" step="0.01" min="0" class="consumption-qty" placeholder="0" style="width:6rem;padding:0.4rem;border:1px solid var(--color-border);border-radius:0.4rem">'
        f'<span class="text-muted" style="width:2.5rem">{i.unit}</span>'
        f'</div>' for i in stock
    )

    consumption_modal = f"""
    <div class="modal-overlay" id="consumptionModal">
        <div class="modal-box">
            <h3 style="margin-bottom:0.25rem">Списание расходников</h3>
            <p class="text-muted" style="margin-bottom:1rem;font-size:0.85rem">Укажите, сколько фактически потрачено. Пустые/нулевые позиции не списываются.</p>
            <div id="consumptionItems">{stock_options or '<p class="text-muted">На складе пока нет позиций — попросите администратора добавить номенклатуру.</p>'}</div>
            <div style="display:flex;gap:0.5rem;margin-top:1rem">
                <button class="btn-outline" style="flex:1" onclick="closeConsumptionModal()">Отмена</button>
                <button class="btn-primary" style="flex:1" onclick="submitConsumption()">Списать</button>
            </div>
        </div>
    </div>
    <style>
        .modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:100; align-items:center; justify-content:center }}
        .modal-overlay.open {{ display:flex }}
        .modal-box {{ background:var(--color-surface); border-radius:1rem; padding:1.5rem; max-width:480px; width:90%; max-height:80vh; overflow-y:auto }}
    </style>
    <script>
        let currentBookingId = null;
        function openConsumptionModal(bookingId) {{
            currentBookingId = bookingId;
            document.getElementById('consumptionModal').classList.add('open');
        }}
        function closeConsumptionModal() {{
            document.getElementById('consumptionModal').classList.remove('open');
            currentBookingId = null;
        }}
        async function submitConsumption() {{
            if (!currentBookingId) return;
            const items = [];
            document.querySelectorAll('.consumption-line').forEach(line => {{
                const qty = parseFloat(line.querySelector('.consumption-qty').value);
                if (qty > 0) {{
                    items.push({{ item_id: parseInt(line.dataset.itemId), quantity: qty }});
                }}
            }});
            if (items.length === 0) {{ alert('Укажите хотя бы одну потраченную позицию'); return; }}
            try {{
                const res = await fetch('/api/v1/inventory/my/consumption', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ booking_id: currentBookingId, items: items }})
                }});
                if (res.ok) {{ location.reload(); }}
                else {{ const data = await res.json().catch(() => ({{}})); alert(data.detail || 'Не удалось списать расходники'); }}
            }} catch (err) {{ alert('Ошибка соединения с сервером'); }}
        }}
    </script>"""

    return calendar_html + consumption_modal


async def render_master_business_dashboard(db: AsyncSession, user, salon: Salon, master: Master, query_params=None) -> str:
    """Урезанная «Панель бизнеса» для мастера: только «Обзор» и «Расписание».
    Мастер не состоит в SalonMember (сознательно — у него нет словаря прав
    владельца/админа), поэтому это отдельная функция рендера, а не ветка
    внутри render_business_dashboard с фиктивным membership."""

    query_params = query_params or {}
    active_tab = query_params.get("tab", "overview")
    if active_tab not in ("overview", "schedule"):
        active_tab = "overview"

    overview_html = await _render_master_overview(db, salon, master)
    schedule_html = await _render_master_schedule(db, salon, master)

    tab_buttons = [("overview", f"{ICON_CHART_COLUMN} Обзор"), ("schedule", f"{ICON_CALENDAR_DAYS} Расписание")]
    nav_buttons_html = "".join(
        f'<button class="tab-btn{" active" if slug == active_tab else ""}" onclick="switchTab(\'{slug}\')">{label}</button>'
        for slug, label in tab_buttons
    )
    tabs_body_html = (overview_html + schedule_html).replace(
        f'id="tab-{active_tab}" class="tab-content"',
        f'id="tab-{active_tab}" class="tab-content active"',
        1,
    )

    return f"""<!DOCTYPE html>
<html lang="ru" class="dashboard-page">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Панель бизнеса — {salon.name} — руми</title>
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
        table {{ width:100%; border-collapse:collapse }}
        th {{ text-align:left; padding:0.75rem; border-bottom:2px solid var(--color-border); font-weight:600; color:var(--color-heading); white-space:nowrap }}
        td {{ padding:0.75rem; border-bottom:1px solid var(--color-border) }}
        .chart-bar {{ height:200px; display:flex; align-items:flex-end; gap:1rem; padding:1rem 0 }}
        .chart-column {{ flex:1; display:flex; flex-direction:column; align-items:center; gap:0.25rem; min-width:40px }}
        .chart-fill {{ width:100%; max-width:3.5rem; border-radius:0.5rem 0.5rem 0 0; background:linear-gradient(to top,var(--color-primary),var(--color-accent)); transition:height 0.3s }}
        .chart-label {{ font-size:0.75rem; color:var(--color-muted) }}
        .chart-value {{ font-size:0.7rem; font-weight:600; color:var(--color-heading); white-space:nowrap }}
    </style>
</head>
<body>
    {render_header("business")}
    {render_sidebar("business_dashboard", user)}
    <main style="margin-right:16rem;padding-top:2rem">
        <div class="section-container">
            <div style="margin-bottom:1rem">
                <h1 class="text-display" style="font-size:2rem">{salon.name}</h1>
                <p class="text-muted">{master.specialization} · Панель мастера</p>
            </div>

            <div class="tab-nav">
                {nav_buttons_html}
            </div>

            {tabs_body_html}
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
    </script>
</body>
</html>"""
