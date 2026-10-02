import json

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Equipment, InventoryItem, Master, Service, User, WarehouseAssignment
from app.web.components.escaping import e


def _catalog_state(product, kind: str) -> tuple[str, str]:
    if not product.is_active:
        return "archived", "В архиве"
    if kind == "equipment":
        status = product.status.value
        if status == "broken":
            return "broken", f"Сломано: {product.quantity:g}"
        if status == "lost":
            return "lost", f"Утеряно: {product.quantity:g}"
        return "ok", "Всё в порядке"
    if product.quantity <= 0:
        return "empty", "Нет в наличии"
    if product.quantity <= product.min_quantity:
        return "low", "Нужно пополнить"
    return "ok", "В наличии"


async def render_warehouse_catalog(db: AsyncSession, salon, masters) -> str:
    items = list((await db.execute(
        select(InventoryItem).where(InventoryItem.salon_id == salon.id).order_by(InventoryItem.name)
    )).scalars().all())
    equipment = list((await db.execute(
        select(Equipment).where(Equipment.salon_id == salon.id).order_by(Equipment.name)
    )).scalars().all())

    masters_by_id = {master.id: master for master in masters}
    master_names = {}
    for master in masters:
        user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
        master_names[master.id] = user.full_name if user else f"Мастер #{master.id}"
    service_rows = (await db.execute(
        select(Service).where(
            or_(
                Service.master_id.in_(list(masters_by_id)),
                Service.assigned_masters.any(Master.id.in_(list(masters_by_id))),
            )
        ).order_by(Service.name)
    )).scalars().all() if masters_by_id else []
    services_by_id = {service.id: service for service in service_rows}
    active_services = [service for service in service_rows if service.is_active]

    item_ids = [item.id for item in items]
    equipment_ids = [row.id for row in equipment]
    assignment_filter = []
    if item_ids:
        assignment_filter.append(WarehouseAssignment.inventory_item_id.in_(item_ids))
    if equipment_ids:
        assignment_filter.append(WarehouseAssignment.equipment_id.in_(equipment_ids))
    assignments = (await db.execute(
        select(WarehouseAssignment).where(or_(*assignment_filter))
    )).scalars().all() if assignment_filter else []

    assignments_by_product: dict[tuple[str, int], list[WarehouseAssignment]] = {}
    for assignment in assignments:
        key = (
            ("consumable", assignment.inventory_item_id)
            if assignment.inventory_item_id is not None
            else ("equipment", assignment.equipment_id)
        )
        assignments_by_product.setdefault(key, []).append(assignment)

    def build_row(product, kind: str) -> str:
        product_assignments = assignments_by_product.get((kind, product.id), [])
        master_ids = [row.master_id for row in product_assignments if row.master_id is not None]
        service_ids = [row.service_id for row in product_assignments if row.service_id is not None]
        if master_ids:
            target_type = "master"
            target_label = "Мастера: " + ", ".join(
                master_names.get(master_id, f"Мастер #{master_id}") for master_id in master_ids
            )
        elif service_ids:
            target_type = "service"
            target_label = "Услуги: " + ", ".join(
                services_by_id[service_id].name
                for service_id in service_ids if service_id in services_by_id
            )
        else:
            target_type = "salon"
            target_label = "Общий склад салона"

        quantity = product.quantity
        min_quantity = product.min_quantity
        state, state_label = _catalog_state(product, kind)
        type_label = "Расходник" if kind == "consumable" else "Техника"
        data = {
            "id": product.id,
            "kind": kind,
            "name": product.name,
            "unit": product.unit,
            "quantity": quantity,
            "target_quantity": product.target_quantity,
            "min_quantity": min_quantity,
            "cost_per_unit": product.cost_per_unit or 0,
            "master_ids": master_ids,
            "service_ids": service_ids,
            "status": product.status.value if kind == "equipment" else "working",
            "purchased_at": product.purchased_at.isoformat() if kind == "equipment" and product.purchased_at else None,
            "service_life_months": product.service_life_months if kind == "equipment" else None,
            "is_active": product.is_active,
        }
        search_text = f"{product.name} {target_label}".casefold()
        escaped_data = e(json.dumps(data, ensure_ascii=False))
        badge_color = (
            "#ef4444" if state in ("empty", "low", "broken")
            else "#f59e0b" if state == "lost"
            else "#16a34a" if state == "ok"
            else "#64748b"
        )
        kind_attr = "equipment" if kind == "equipment" else "consumable"
        return f"""
        <tr class="warehouse-product-row" data-catalog-row data-kind="{kind_attr}" data-state="{state}"
            data-target="{target_type}" data-search="{e(search_text)}">
            <td class="warehouse-product-name">{e(product.name)}<div class="text-muted" style="font-size:.8rem">{type_label}</div></td>
            <td class="warehouse-product-target">{e(target_label)}</td>
            <td><strong>{quantity:g}</strong> {e(product.unit)}</td>
            <td>{f'{product.target_quantity:g} {e(product.unit)}' if product.target_quantity > 0 else '—'}</td>
            <td>{f'{min_quantity:g} {e(product.unit)}' if kind == 'consumable' else '—'}</td>
            <td>{product.cost_per_unit or 0} ₽/{e(product.unit)}</td>
            <td><span class="warehouse-stock-badge" style="--warehouse-badge-color:{badge_color}">{state_label}</span>
                </td>
            <td class="warehouse-product-actions">
                <button class="btn-outline warehouse-action-button" type="button" data-product="{escaped_data}"
                    onclick="openWarehouseProduct(this)">Изменить</button>
                <button class="btn-outline warehouse-action-button" type="button"
                    onclick="toggleWarehouseHistory(this, '{kind}', {product.id})">История</button>
            </td>
        </tr>"""

    rows = "".join(build_row(item, "consumable") for item in items)
    rows += "".join(build_row(row, "equipment") for row in equipment)
    master_options = "".join(
        f'<option value="{master.id}">{e(master_names.get(master.id, f"Мастер #{master.id}"))}</option>'
        for master in masters
    )
    service_options = "".join(
        f'<option value="{service.id}">{e(service.name)}</option>' for service in active_services
    )

    return f"""
    <section class="card warehouse-catalog" style="margin-bottom:1.5rem">
        <div class="warehouse-catalog-heading">
            <div>
                <h3 style="margin:0">Склад</h3>
                <p class="text-muted" style="margin:.35rem 0 0;font-size:.85rem">Остатки расходников, состояние техники и история операций.</p>
            </div>
            <button class="btn-primary warehouse-add-button" type="button" aria-label="Добавить товар"
                onclick="openWarehouseProduct()">＋</button>
        </div>
        <details class="warehouse-catalog-details" open>
            <summary>Учёт склада <span>{len(items) + len(equipment)} позиций</span></summary>
            <div class="warehouse-catalog-content">
                <div class="warehouse-catalog-filters">
                    <input class="warehouse-filter-control warehouse-search-control" id="warehouseSearch" type="search" placeholder="Поиск по названию или назначению">
                    <select class="warehouse-filter-control" id="warehouseKind"><option value="all">Все типы</option><option value="consumable">Расходники</option><option value="equipment">Техника</option></select>
                    <select class="warehouse-filter-control" id="warehouseState"><option value="all">Любой статус</option><option value="low">Нужно пополнить</option><option value="empty">Нет в наличии</option><option value="ok">В наличии / всё в порядке</option><option value="broken">Сломано</option><option value="lost">Утеряно</option><option value="archived">В архиве</option></select>
                    <select class="warehouse-filter-control" id="warehouseTarget"><option value="all">Любое назначение</option><option value="salon">Общий склад</option><option value="master">Мастерам</option><option value="service">Услугам</option></select>
                </div>
                <div class="warehouse-table-scroll">
                    <table class="warehouse-table">
                        <thead><tr><th>Наименование</th><th>Назначение</th><th>Количество</th><th>Нужно иметь</th><th>Мин. запас</th><th>Цена за ед.</th><th>Состояние</th><th>Действия</th></tr></thead>
                        <tbody id="warehouseCatalogRows">{rows or '<tr><td colspan="8" class="warehouse-empty-state">Пока нет товаров — добавьте первый через «＋».</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        </details>
    </section>

    <style>
        .warehouse-catalog-heading {{
            display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:1.25rem
        }}
        .warehouse-add-button {{width:3rem;height:3rem;justify-content:center;padding:0;font-size:1.35rem}}
        .warehouse-catalog-details {{
            overflow:hidden;border:1px solid color-mix(in srgb,var(--color-primary) 34%,var(--color-border));
            border-radius:1rem;background:color-mix(in srgb,var(--color-primary) 5%,var(--color-surface));
        }}
        .warehouse-catalog-details > summary {{
            display:flex;align-items:center;justify-content:space-between;gap:.75rem;
            padding:.9rem 1.1rem;color:var(--color-heading);font-weight:700;cursor:pointer;
            list-style:none;background:color-mix(in srgb,var(--color-primary) 15%,var(--color-surface));
        }}
        .warehouse-catalog-details > summary::-webkit-details-marker {{display:none}}
        .warehouse-catalog-details > summary::after {{
            content:"⌄";margin-left:auto;color:var(--color-primary);font-size:1.15rem;
            transition:transform .18s ease;
        }}
        .warehouse-catalog-details[open] > summary::after {{transform:rotate(180deg)}}
        .warehouse-catalog-details > summary span {{
            padding:.25rem .65rem;border-radius:9999px;
            background:color-mix(in srgb,var(--color-primary) 19%,var(--color-surface));
            color:var(--color-primary);font-size:.76rem;font-weight:700;white-space:nowrap;
        }}
        .warehouse-catalog-content {{padding:1rem;background:color-mix(in srgb,var(--color-primary) 4%,var(--color-surface))}}
        .warehouse-catalog-filters {{
            display:grid;grid-template-columns:minmax(220px,1.15fr) repeat(3,minmax(150px,1fr));
            gap:.65rem;margin-bottom:1rem
        }}
        .warehouse-filter-control {{
            box-sizing:border-box;width:100%;min-width:0;min-height:2.7rem;padding:.55rem .9rem;
            border:1px solid var(--color-border);border-radius:9999px;background:var(--color-surface);
            color:var(--color-heading);font:inherit;font-size:.875rem;outline:none;
            transition:border-color .18s ease,box-shadow .18s ease
        }}
        .warehouse-filter-control:focus {{
            border-color:var(--color-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--color-primary) 14%,transparent)
        }}
        .warehouse-search-control {{padding-left:1.15rem}}
        .warehouse-table-scroll {{
            overflow-x:auto;border:1px solid color-mix(in srgb,var(--color-primary) 25%,var(--color-border));
            border-radius:.8rem;background:var(--color-surface);
        }}
        .warehouse-table {{min-width:760px;width:100%;border-collapse:collapse}}
        .warehouse-table th {{
            padding:.9rem 1rem;border:1px solid color-mix(in srgb,var(--color-primary) 28%,var(--color-border));
            background:color-mix(in srgb,var(--color-primary) 16%,var(--color-surface));
            color:var(--color-heading);font-size:.88rem;text-align:left;
        }}
        .warehouse-table td {{
            padding:.9rem 1rem;border:1px solid color-mix(in srgb,var(--color-primary) 19%,var(--color-border));
            background:color-mix(in srgb,var(--color-primary) 3%,var(--color-surface));
        }}
        .warehouse-table tbody tr:nth-child(even) td {{
            background:color-mix(in srgb,var(--color-primary) 7%,var(--color-surface));
        }}
        .warehouse-product-row {{transition:background .16s ease}}
        .warehouse-product-row:hover td {{background:color-mix(in srgb,var(--color-primary) 17%,var(--color-surface))}}
        .warehouse-stock-badge {{
            display:inline-flex;align-items:center;padding:.25rem .65rem;border-radius:9999px;
            background:color-mix(in srgb,var(--warehouse-badge-color) 12%,var(--color-surface));
            color:var(--warehouse-badge-color);font-size:.76rem;font-weight:650;white-space:nowrap
        }}
        .warehouse-product-actions {{white-space:nowrap}}
        .warehouse-action-button {{padding:.4rem .7rem;font-size:.75rem}}
        .warehouse-empty-state {{padding:2.5rem 1rem!important;text-align:center;color:var(--color-muted)}}
        .warehouse-audit-card {{padding:1.75rem}}
        .warehouse-audit-launch-card {{
            border:1px solid color-mix(in srgb,var(--color-primary) 24%,var(--color-border));
            background:color-mix(in srgb,var(--color-primary) 4%,var(--color-surface));
            box-shadow:0 8px 24px color-mix(in srgb,var(--color-primary) 7%,transparent);
        }}
        .warehouse-audit-launch-card h3 {{color:var(--color-heading)}}
        .warehouse-audit-launch-card .warehouse-audit-description {{color:var(--color-muted)}}
        .warehouse-audit-launch-card .warehouse-audit-select {{
            border-color:color-mix(in srgb,var(--color-primary) 22%,var(--color-border));
            background:var(--color-surface);
        }}
        .warehouse-audit-launch-card .warehouse-audit-form .btn-outline {{
            border-color:color-mix(in srgb,var(--color-primary) 28%,var(--color-border));
            background:color-mix(in srgb,var(--color-primary) 9%,var(--color-surface));
            color:var(--color-heading);
        }}
        .warehouse-audit-launch-card .warehouse-audit-form .btn-outline:hover {{
            border-color:var(--color-primary);
            background:color-mix(in srgb,var(--color-primary) 15%,var(--color-surface));
        }}
        .warehouse-audit-description {{max-width:60rem;margin:0 0 1.25rem;color:var(--color-muted);line-height:1.6}}
        .warehouse-audit-form {{display:flex;align-items:center;gap:.7rem;max-width:34rem}}
        .warehouse-audit-select {{
            box-sizing:border-box;min-height:2.75rem;flex:1;padding:.6rem 1rem;
            border:1px solid var(--color-border);border-radius:9999px;background:var(--color-surface);
            color:var(--color-heading);font:inherit;outline:none
        }}
        .warehouse-audit-select:focus {{
            border-color:var(--color-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--color-primary) 14%,transparent)
        }}
        .warehouse-audit-form .btn-outline {{min-height:2.75rem;padding:.55rem 1.1rem;white-space:nowrap}}
        .warehouse-audit-table input {{
            box-sizing:border-box;min-height:2.5rem;width:8rem;padding:.5rem .7rem;
            border:1px solid var(--color-border);border-radius:.65rem;
            background:var(--color-surface-alt);color:var(--color-heading);font:inherit
        }}
        .warehouse-audit-confirm {{margin-top:1rem}}
        @media(max-width:900px) {{
            .warehouse-catalog-filters {{grid-template-columns:repeat(2,minmax(0,1fr))}}
            .warehouse-search-control {{grid-column:1/-1}}
        }}
        @media(max-width:560px) {{
            .warehouse-catalog-heading {{align-items:flex-start}}
            .warehouse-catalog-content {{padding:.65rem}}
            .warehouse-catalog-filters {{grid-template-columns:1fr}}
            .warehouse-search-control {{grid-column:auto}}
            .warehouse-audit-card {{padding:1.2rem}}
            .warehouse-audit-form {{align-items:stretch;flex-direction:column}}
            .warehouse-audit-form .btn-outline {{width:100%}}
        }}
        #warehouseProductModal {{
            position:fixed;inset:0;z-index:1000;display:none;align-items:center;justify-content:center;
            padding:1rem;background:rgba(22,12,18,.58);backdrop-filter:blur(5px)
        }}
        #warehouseProductModal .warehouse-modal-card {{
            width:min(640px,100%);max-height:90vh;overflow:auto;padding:1.75rem;
            border:1px solid var(--color-border);border-radius:1.25rem;
            background:var(--color-surface);box-shadow:0 24px 70px rgba(24,12,18,.24)
        }}
        #warehouseProductModal .warehouse-modal-heading {{
            display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;margin-bottom:1.35rem
        }}
        #warehouseProductModal .warehouse-modal-heading h3 {{
            margin:0;color:var(--color-heading);font-size:1.4rem;font-weight:700
        }}
        #warehouseProductModal .warehouse-modal-close {{
            display:grid;place-items:center;width:2.25rem;height:2.25rem;flex:none;
            border:1px solid var(--color-border);border-radius:50%;background:var(--color-surface);
            color:var(--color-muted);font-size:1.35rem;cursor:pointer;transition:.18s ease
        }}
        #warehouseProductModal .warehouse-modal-close:hover {{
            border-color:var(--color-primary);color:var(--color-primary);background:var(--color-surface-alt)
        }}
        #warehouseProductForm {{
            display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem
        }}
        #warehouseProductForm .warehouse-field {{
            display:flex;min-width:0;flex-direction:column;gap:.4rem;
            color:var(--color-heading);font-size:.88rem;font-weight:600
        }}
        #warehouseProductForm .warehouse-field-hint {{color:var(--color-muted);font-size:.75rem;font-weight:400;line-height:1.4}}
        #warehouseProductForm .warehouse-field-wide,
        #warehouseProductForm .warehouse-modal-actions,
        #warehouseProductForm .warehouse-error {{grid-column:1/-1}}
        #warehouseEquipmentFields {{
            grid-column:1/-1;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem
        }}
        #warehouseProductModal input:not([type=hidden]),
        #warehouseProductModal select {{
            box-sizing:border-box;width:100%;min-height:2.75rem;padding:.65rem .8rem;
            border:1px solid var(--color-border);border-radius:.7rem;
            background:var(--color-surface-alt);color:var(--color-heading);
            font:inherit;font-size:.92rem;outline:none;transition:border-color .18s ease,box-shadow .18s ease
        }}
        #warehouseProductModal input:focus,
        #warehouseProductModal select:focus {{
            border-color:var(--color-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--color-primary) 16%,transparent)
        }}
        #warehouseProductModal select[multiple] {{min-height:7rem}}
        #warehouseProductForm .warehouse-modal-actions {{
            display:flex;align-items:center;justify-content:flex-end;gap:.65rem;margin-top:.35rem
        }}
        #warehouseProductForm .warehouse-error {{margin:0;color:#dc3545;font-size:.88rem}}
        #warehouseProductModal .warehouse-modal-actions button {{
            min-height:2.8rem;padding:.65rem 1.2rem;border-radius:999px;font:inherit;font-weight:650;cursor:pointer
        }}
        @media(max-width:560px) {{
            #warehouseProductModal {{padding:.65rem}}
            #warehouseProductModal .warehouse-modal-card {{padding:1.2rem;border-radius:1rem}}
            #warehouseProductForm {{grid-template-columns:1fr;gap:.8rem}}
            #warehouseProductForm .warehouse-field-wide,
            #warehouseProductForm .warehouse-modal-actions,
            #warehouseProductForm .warehouse-error {{grid-column:auto}}
            #warehouseEquipmentFields {{grid-column:1/-1}}
            #warehouseProductForm .warehouse-modal-actions {{flex-wrap:wrap}}
            #warehouseArchiveButton {{margin-right:auto!important}}
        }}
    </style>
    <div id="warehouseProductModal" role="dialog" aria-modal="true" aria-labelledby="warehouseProductTitle">
        <div class="card warehouse-modal-card">
            <div class="warehouse-modal-heading">
                <h3 id="warehouseProductTitle">Добавить товар</h3>
                <button class="warehouse-modal-close" type="button" aria-label="Закрыть"
                    onclick="closeWarehouseProduct()">×</button>
            </div>
            <form id="warehouseProductForm">
                <input type="hidden" id="warehouseProductId">
                <label class="warehouse-field">Тип товара
                    <select id="warehouseProductKind" required><option value="consumable">Расходник</option><option value="equipment">Техника</option></select>
                </label>
                <label class="warehouse-field">Название
                    <input id="warehouseProductName" maxlength="100" required>
                </label>
                <label class="warehouse-field">Единица измерения
                    <input id="warehouseProductUnit" maxlength="20" placeholder="шт, мл, г, упаковка" required>
                </label>
                <label class="warehouse-field">Текущий остаток
                    <input id="warehouseProductQuantity" type="number" min="0" step="0.01" required>
                </label>
                <label class="warehouse-field">Нужно иметь на складе
                    <input id="warehouseProductTargetQuantity" type="number" min="0" step="0.01" value="0" required>
                    <small class="warehouse-field-hint">Целевой запас для планирования закупки; 0 — не задан.</small>
                </label>
                <label id="warehouseMinimumField" class="warehouse-field">Минимальный остаток
                    <input id="warehouseProductMinimum" type="number" min="0" step="0.01" required>
                </label>
                <label class="warehouse-field">Цена за единицу, ₽
                    <input id="warehouseProductPrice" type="number" min="0" step="1" required>
                </label>
                <label class="warehouse-field warehouse-field-wide">Назначить товар
                    <select id="warehouseProductTarget">
                        <option value="salon">Общий склад салона</option>
                        <option value="master">Одному или нескольким мастерам</option>
                        <option value="service">Одной или нескольким услугам</option>
                    </select>
                </label>
                <label id="warehouseMastersField" class="warehouse-field warehouse-field-wide" style="display:none">Мастера
                    <select id="warehouseProductMasters" multiple size="4">{master_options}</select>
                </label>
                <label id="warehouseServicesField" class="warehouse-field warehouse-field-wide" style="display:none">Услуги
                    <select id="warehouseProductServices" multiple size="4">{service_options}</select>
                </label>
                <div id="warehouseEquipmentFields" style="display:none">
                    <label class="warehouse-field warehouse-field-wide">Состояние техники
                        <select id="warehouseProductStatus"><option value="working">Всё в порядке</option><option value="broken">Сломано</option><option value="lost">Утеряно</option></select>
                    </label>
                    <label class="warehouse-field">Дата покупки
                        <input id="warehousePurchasedAt" type="date">
                    </label>
                    <label class="warehouse-field">Срок службы, месяцев
                        <input id="warehouseServiceLife" type="number" min="1">
                    </label>
                </div>
                <div class="warehouse-modal-actions">
                    <button id="warehouseArchiveButton" class="btn-outline" type="button" style="display:none;margin-right:auto" onclick="toggleWarehouseActive()">В архив</button>
                    <button class="btn-outline" type="button" onclick="closeWarehouseProduct()">Отмена</button>
                    <button class="btn-primary" type="submit">Сохранить</button>
                </div>
                <p id="warehouseProductError" class="warehouse-error" role="alert"></p>
            </form>
        </div>
    </div>

    <script>
    (function() {{
        const salonId = {salon.id};
        const modal = document.getElementById('warehouseProductModal');
        const form = document.getElementById('warehouseProductForm');
        const kind = document.getElementById('warehouseProductKind');
        const target = document.getElementById('warehouseProductTarget');

        function syncFields() {{
            const isEquipment = kind.value === 'equipment';
            document.getElementById('warehouseEquipmentFields').style.display = isEquipment ? 'grid' : 'none';
            document.getElementById('warehouseMinimumField').style.display = isEquipment ? 'none' : 'flex';
            document.getElementById('warehouseMastersField').style.display = target.value === 'master' ? 'block' : 'none';
            document.getElementById('warehouseServicesField').style.display = target.value === 'service' ? 'block' : 'none';
        }}
        kind.addEventListener('change', syncFields);
        target.addEventListener('change', syncFields);

        window.openWarehouseProduct = function(button) {{
            form.reset();
            kind.disabled = false;
            document.getElementById('warehouseProductId').value = '';
            document.getElementById('warehouseProductTitle').textContent = 'Добавить товар';
            document.getElementById('warehouseArchiveButton').style.display = 'none';
            document.getElementById('warehouseProductError').textContent = '';
            document.getElementById('warehouseProductQuantity').value = '0';
            document.getElementById('warehouseProductTargetQuantity').value = '0';
            document.getElementById('warehouseProductMinimum').value = '0';
            document.getElementById('warehouseProductPrice').value = '0';
            if (button && button.dataset.product) {{
                const data = JSON.parse(button.dataset.product);
                document.getElementById('warehouseProductId').value = data.id;
                document.getElementById('warehouseProductTitle').textContent = 'Редактировать товар';
                kind.value = data.kind;
                kind.disabled = true;
                document.getElementById('warehouseProductName').value = data.name;
                document.getElementById('warehouseProductUnit').value = data.unit;
                document.getElementById('warehouseProductQuantity').value = data.quantity;
                document.getElementById('warehouseProductTargetQuantity').value = data.target_quantity || 0;
                document.getElementById('warehouseProductMinimum').value = data.min_quantity;
                document.getElementById('warehouseProductPrice').value = data.cost_per_unit;
                document.getElementById('warehouseProductStatus').value = data.status;
                document.getElementById('warehousePurchasedAt').value = data.purchased_at || '';
                document.getElementById('warehouseServiceLife').value = data.service_life_months || '';
                target.value = data.master_ids.length ? 'master' : data.service_ids.length ? 'service' : 'salon';
                Array.from(document.getElementById('warehouseProductMasters').options).forEach(o => o.selected = data.master_ids.includes(Number(o.value)));
                Array.from(document.getElementById('warehouseProductServices').options).forEach(o => o.selected = data.service_ids.includes(Number(o.value)));
                const archiveButton = document.getElementById('warehouseArchiveButton');
                archiveButton.style.display = 'inline-block';
                archiveButton.textContent = data.is_active ? 'В архив' : 'Вернуть из архива';
                archiveButton.dataset.active = data.is_active ? 'true' : 'false';
            }} else {{
                kind.value = 'consumable';
                target.value = 'salon';
            }}
            syncFields();
            modal.style.display = 'flex';
        }};
        window.closeWarehouseProduct = function() {{ modal.style.display = 'none'; }};

        window.toggleWarehouseActive = async function() {{
            const id = document.getElementById('warehouseProductId').value;
            const response = await fetch(`/api/v1/inventory/salon/${{salonId}}/catalog/${{kind.value}}/${{id}}/toggle-active`, {{method:'POST'}});
            if (!response.ok) {{ document.getElementById('warehouseProductError').textContent = 'Не удалось изменить состояние товара'; return; }}
            window.location.reload();
        }};

        form.addEventListener('submit', async function(event) {{
            event.preventDefault();
            const productId = document.getElementById('warehouseProductId').value;
            const assignmentType = target.value;
            const body = {{
                kind: kind.value,
                assignment_type: assignmentType,
                name: document.getElementById('warehouseProductName').value.trim(),
                unit: document.getElementById('warehouseProductUnit').value.trim(),
                quantity: Number(document.getElementById('warehouseProductQuantity').value),
                target_quantity: Number(document.getElementById('warehouseProductTargetQuantity').value),
                min_quantity: kind.value === 'equipment' ? 0 : Number(document.getElementById('warehouseProductMinimum').value),
                cost_per_unit: Number(document.getElementById('warehouseProductPrice').value),
                master_ids: assignmentType === 'master' ? Array.from(document.getElementById('warehouseProductMasters').selectedOptions).map(o => Number(o.value)) : [],
                service_ids: assignmentType === 'service' ? Array.from(document.getElementById('warehouseProductServices').selectedOptions).map(o => Number(o.value)) : [],
                status: document.getElementById('warehouseProductStatus').value,
                purchased_at: document.getElementById('warehousePurchasedAt').value || null,
                service_life_months: document.getElementById('warehouseServiceLife').value ? Number(document.getElementById('warehouseServiceLife').value) : null
            }};
            const url = productId
                ? `/api/v1/inventory/salon/${{salonId}}/catalog/${{kind.value}}/${{productId}}`
                : `/api/v1/inventory/salon/${{salonId}}/catalog`;
            try {{
                const response = await fetch(url, {{
                    method: productId ? 'PUT' : 'POST',
                    headers: {{'Content-Type':'application/json'}},
                    body: JSON.stringify(body)
                }});
                if (!response.ok) {{
                    const result = await response.json().catch(() => ({{}}));
                    throw new Error(result.detail || 'Не удалось сохранить товар');
                }}
                window.location.reload();
            }} catch (error) {{
                document.getElementById('warehouseProductError').textContent = error.message || 'Ошибка соединения с сервером';
            }}
        }});

        window.toggleWarehouseHistory = async function(button, productKind, productId) {{
            const existing = button.closest('tr').nextElementSibling;
            if (existing && existing.dataset.history) {{ existing.remove(); return; }}
            const response = await fetch(`/api/v1/inventory/salon/${{salonId}}/catalog/${{productKind}}/${{productId}}/history`);
            if (!response.ok) {{ alert('Не удалось загрузить историю товара'); return; }}
            const movements = await response.json();
            const row = document.createElement('tr');
            row.dataset.history = 'true';
            const cell = document.createElement('td');
            cell.colSpan = 8;
            if (!movements.length) {{
                cell.textContent = 'История движений пока не накоплена.';
            }} else {{
                const list = document.createElement('ul');
                movements.forEach(movement => {{
                    const entry = document.createElement('li');
                    const sign = movement.delta > 0 ? '+' : '';
                    const typeLabels = {{receipt:'Приход', consumption:'Списание', adjustment:'Корректировка'}};
                    entry.textContent = `${{new Date(movement.date).toLocaleString()}} · ${{typeLabels[movement.type] || movement.type}} · ${{sign}}${{movement.delta}} ${{movement.unit}} · ${{movement.unit_cost}} ₽/ед. · ${{movement.comment || ''}}`;
                    list.appendChild(entry);
                }});
                cell.appendChild(list);
            }}
            row.appendChild(cell);
            button.closest('tr').after(row);
        }};

        function applyFilters() {{
            const search = document.getElementById('warehouseSearch').value.toLocaleLowerCase();
            const selectedKind = document.getElementById('warehouseKind').value;
            const selectedState = document.getElementById('warehouseState').value;
            const selectedTarget = document.getElementById('warehouseTarget').value;
            document.querySelectorAll('[data-catalog-row]').forEach(row => {{
                const stateMatches = selectedState === 'all' || row.dataset.state === selectedState ||
                    (selectedState === 'low' && row.dataset.state === 'empty');
                row.hidden = (selectedKind !== 'all' && row.dataset.kind !== selectedKind) ||
                    !stateMatches ||
                    (selectedTarget !== 'all' && row.dataset.target !== selectedTarget) ||
                    !row.dataset.search.includes(search);
            }});
        }}
        ['warehouseSearch','warehouseKind','warehouseState','warehouseTarget'].forEach(id =>
            document.getElementById(id).addEventListener('input', applyFilters)
        );
    }})();
    </script>"""
