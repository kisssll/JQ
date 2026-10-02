# app/web/pages/business/tabs/warehouse.py
from app.web.components.escaping import e
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import (
    InventoryItem, InventoryAudit, InventoryAuditItem, InventoryAuditStatus,
    Equipment, EquipmentStatus, User as UserModel, WarehouseRequestType,
)
from app.services.inventory_service import InventoryService
from app.web.components.hint import hint as _hint
from app.web.components.inventory_audit import render_inventory_audit_flow
from app.web.pages.business.tabs.warehouse_catalog import render_warehouse_catalog
from app.web.components.icons import (
    ICON_PACKAGE,
)

def _equipment_condition_counts(equipment_list) -> tuple[float, float]:
    active_equipment = [row for row in equipment_list if row.is_active]
    broken = sum(
        row.quantity for row in active_equipment if row.status == EquipmentStatus.BROKEN
    )
    lost = sum(
        row.quantity for row in active_equipment if row.status == EquipmentStatus.LOST
    )
    return broken, lost


async def render_warehouse_tab(db: AsyncSession, salon, masters, master_ids, warehouse_filters: dict, membership=None) -> str:
    """Вкладка «Склад» — мини-склады мастеров, приход, инвентаризация."""

    master_user_names = {}
    for m in masters:
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        master_user_names[m.id] = mu.full_name if mu else "—"

    stock_items = list((await db.execute(
        select(InventoryItem).where(InventoryItem.salon_id == salon.id, InventoryItem.is_active == True)
    )).scalars().all())
    low_stock_count = sum(item.quantity <= item.min_quantity for item in stock_items)
    stock_count = len(stock_items)

    master_options = "".join(f'<option value="{m.id}">{master_user_names.get(m.id, "—")}</option>' for m in masters)

    # Техника учитывается в каталоге, но запас пополнять нужно только по расходникам.
    equipment_list = list((await db.execute(
        select(Equipment).where(Equipment.salon_id == salon.id, Equipment.is_active == True)
    )).scalars().all())
    stock_count += len(equipment_list)
    broken_equipment_count, lost_equipment_count = _equipment_condition_counts(equipment_list)
    unavailable_equipment_count = broken_equipment_count + lost_equipment_count

    # Заявки мастеров: расходник заканчивается / техника сломалась
    pending_requests = await InventoryService.get_pending_requests(db, salon.id)
    request_rows = ""
    for req in pending_requests:
        author = (await db.execute(select(UserModel).where(UserModel.id == req.created_by_id))).scalar_one_or_none()
        if req.type == WarehouseRequestType.CONSUMABLE_LOW:
            type_label = f"{ICON_PACKAGE} Расходник заканчивается"
            target_name = req.item.name if req.item else "(позиция удалена)"
        else:
            type_label = f"{ICON_PACKAGE} Техника сломалась"
            target_name = req.equipment.name if req.equipment else "(позиция удалена)"
        request_rows += f"""
        <div class="card" style="display:flex;gap:1rem;align-items:center;padding:1rem;margin-bottom:0.75rem">
            <div style="flex:1">
                <p style="font-weight:600">{type_label}: {target_name}</p>
                <p style="font-size:0.85rem;color:var(--color-muted)">{author.full_name if author else 'Мастер'} · {e(req.comment or 'без комментария')}</p>
            </div>
            <button class="btn-primary" style="font-size:0.8rem;padding:0.4rem 0.9rem" onclick="resolveWarehouseRequest({req.id})">Решено</button>
            <button class="btn-outline" style="font-size:0.8rem;padding:0.4rem 0.9rem" onclick="dismissWarehouseRequest({req.id})">Отклонить</button>
        </div>"""

    # Открытая инвентаризация (?audit_id=...) в виде пошаговых карточек
    audit_html = ""
    audit_id_raw = warehouse_filters.get("audit_id")
    if audit_id_raw and audit_id_raw.isdigit():
        audit = (await db.execute(
            select(InventoryAudit).where(
                InventoryAudit.id == int(audit_id_raw),
                InventoryAudit.salon_id == salon.id,
            )
        )).scalar_one_or_none()
        if audit and audit.status == InventoryAuditStatus.DRAFT and (
            audit.master_id is None or audit.master_id in master_ids
        ):
            audit_items = (await db.execute(
                select(InventoryAuditItem, InventoryItem, Equipment)
                .outerjoin(InventoryItem, InventoryItem.id == InventoryAuditItem.item_id)
                .outerjoin(Equipment, Equipment.id == InventoryAuditItem.equipment_id)
                .where(InventoryAuditItem.audit_id == audit.id)
                .order_by(InventoryItem.name, Equipment.name)
            )).all()
            title = (
                "Инвентаризация — весь салон" if audit.master_id is None
                else f"Инвентаризация — {master_user_names.get(audit.master_id, 'мастер')}"
            )
            audit_html = render_inventory_audit_flow(
                audit,
                [(audit_item, item or equipment) for audit_item, item, equipment in audit_items],
                title=title,
                return_url=f"/business/dashboard?salon_id={salon.id}&tab=warehouse",
            )

    notify_toggle_html = ""
    if membership is not None:
        checked = "checked" if membership.notify_warehouse_requests else ""
        notify_toggle_html = f"""
        <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1.5rem;font-size:0.9rem;cursor:pointer">
            <input type="checkbox" id="notifyWarehouseToggle" {checked} onchange="toggleWarehouseNotify()">
            Присылать мне уведомления о низком остатке и заявках по складу
        </label>"""
    catalog_html = await render_warehouse_catalog(db, salon, masters)

    return f"""
    <div id="tab-warehouse" class="tab-content">
        <div class="analytics-kpi">
            <div class="kpi-card"><div class="kpi-label">Позиции в каталоге</div><div class="kpi-value">{stock_count}</div></div>
            <div class="kpi-card"><div class="kpi-label">Нужно пополнить</div><div class="kpi-value" style="color:#ef4444">{low_stock_count}</div></div>
            <div class="kpi-card"><div class="kpi-label">Сломано / утеряно</div><div class="kpi-value" style="color:{'#64748b' if unavailable_equipment_count == 0 else '#ef4444'}">{unavailable_equipment_count:g}</div><div class="kpi-label" style="margin-top:.25rem">Сломано: {broken_equipment_count:g} · утеряно: {lost_equipment_count:g}</div></div>
            <div class="kpi-card"><div class="kpi-label">Заявок в очереди</div><div class="kpi-value" style="color:#f59e0b">{len(pending_requests)}</div></div>
        </div>

        {notify_toggle_html}

        {f'<div style="margin-bottom:1.5rem"><h3 style="margin-bottom:0.75rem">Заявки от мастеров {_hint("Мастер сообщил через приложение, что расходник заканчивается или сломалась техника. Отметьте «Решено», когда разобрались, или «Отклонить», если заявка не по делу.")}</h3>{request_rows}</div>' if request_rows else ''}

        <div class="card warehouse-audit-card warehouse-audit-launch-card">
            <h3 style="margin-bottom:.5rem">Инвентаризация {_hint("Управляющий с правом управления складом может пересчитать весь салон или склад отдельного мастера. Мастер пересчитывает только назначенные ему позиции.")}</h3>
            <p class="warehouse-audit-description">Позиции откроются по одной. Для каждой можно подтвердить остаток, изменить количество или переместить позицию в архив.</p>
            <form method="post" id="startAuditForm" class="warehouse-audit-form">
                <select name="master_id_path" id="auditMaster" class="warehouse-audit-select" required>
                    <option value="">Выберите склад</option>
                    <option value="salon">Весь салон</option>{master_options}
                </select>
                <button type="submit" class="btn-outline">Начать инвентаризацию</button>
            </form>
        </div>

        {audit_html}

        {catalog_html}
    </div>

    <script>
    (function() {{
        const salonId = {salon.id};

        window.toggleWarehouseNotify = async function() {{
            const checkbox = document.getElementById('notifyWarehouseToggle');
            const res = await fetch('/api/v1/inventory/salon/' + salonId + '/notify-toggle', {{ method: 'POST' }});
            if (!res.ok) {{
                alert('Не удалось сохранить настройку');
                checkbox.checked = !checkbox.checked;  // откатываем визуально
            }}
        }};

        window.resolveWarehouseRequest = async function(requestId) {{
            const body = new URLSearchParams({{ salon_id: salonId }});
            const res = await fetch('/api/v1/inventory/requests/' + requestId + '/resolve', {{ method: 'POST', body }});
            if (res.ok) location.reload(); else alert('Не удалось обработать заявку');
        }};

        window.dismissWarehouseRequest = async function(requestId) {{
            const body = new URLSearchParams({{ salon_id: salonId }});
            const res = await fetch('/api/v1/inventory/requests/' + requestId + '/dismiss', {{ method: 'POST', body }});
            if (res.ok) location.reload(); else alert('Не удалось обработать заявку');
        }};

        const startAuditForm = document.getElementById('startAuditForm');
        if (startAuditForm) startAuditForm.addEventListener('submit', function(e) {{
            const targetId = this.master_id_path.value;
            if (!targetId) {{ e.preventDefault(); alert('Выберите склад'); return; }}
            this.action = targetId === 'salon'
                ? '/api/v1/inventory/salon/' + salonId + '/audit/start'
                : '/api/v1/inventory/master/' + targetId + '/audit/start';
        }});

    }})();
    </script>"""
