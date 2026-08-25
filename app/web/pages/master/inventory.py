# app/web/pages/master/inventory.py
from app.web.components.escaping import e
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Master, InventoryItem, InventoryMovement, InventoryMovementType
from app.services.inventory_service import InventoryService
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles

MOVEMENT_LABELS = {
    InventoryMovementType.RECEIPT: ("Приход", "#22c55e"),
    InventoryMovementType.CONSUMPTION: ("Списание", "#ef4444"),
    InventoryMovementType.ADJUSTMENT: ("Корректировка", "#3b82f6"),
}


async def render_master_inventory(db: AsyncSession, user) -> str:
    """Мой склад: остатки + история движений."""

    master = (await db.execute(select(Master).where(Master.user_id == user.id))).scalar_one_or_none()
    if not master:
        return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">{get_base_styles()}</head>
        <body>{render_header("master", user)}{render_sidebar("master", user)}
        <main style="margin-right:16rem;padding-top:3rem"><div class="section-container">
        <h1>Профиль мастера не найден</h1>
        </div></main>{render_footer(user)}</body></html>"""

    stock = await InventoryService.get_master_stock(db, master.id)
    stock_rows = "".join(f"""
        <tr>
            <td>{e(i.name)}</td>
            <td><strong style="{'color:#ef4444' if i.quantity <= i.min_quantity else ''}">{i.quantity:g}</strong> {i.unit}</td>
            <td>{i.min_quantity:g} {i.unit}</td>
        </tr>""" for i in stock)

    item_ids = [i.id for i in stock]
    movements = []
    if item_ids:
        result = await db.execute(
            select(InventoryMovement, InventoryItem)
            .join(InventoryItem, InventoryItem.id == InventoryMovement.item_id)
            .where(InventoryItem.master_id == master.id)
            .order_by(InventoryMovement.created_at.desc())
            .limit(50)
        )
        movements = result.all()

    movement_rows = ""
    for mv, item in movements:
        label, color = MOVEMENT_LABELS.get(mv.type, (mv.type.value, "#9ca3af"))
        sign = "+" if mv.delta > 0 else ""
        movement_rows += f"""
        <tr>
            <td>{mv.created_at.strftime('%d.%m.%Y %H:%M')}</td>
            <td>{e(item.name)}</td>
            <td><span style="color:{color};font-weight:600">{label}</span></td>
            <td>{sign}{mv.delta:g} {item.unit}</td>
            <td class="text-muted">{e(mv.comment or '—')}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Мой склад — руми</title>
    {get_base_styles()}
    <style>
        table {{ width:100%; border-collapse:collapse }}
        th {{ text-align:left; padding:0.75rem; border-bottom:2px solid var(--color-border); font-weight:600; color:var(--color-heading); white-space:nowrap }}
        td {{ padding:0.75rem; border-bottom:1px solid var(--color-border) }}
    </style>
</head>
<body>
    {render_header("master", user)}
    {render_sidebar("master", user)}

    <main style="margin-right:16rem;padding-top:2rem">
        <div class="section-container">
            <a href="/master/dashboard" class="text-muted" style="font-size:0.875rem">← Кабинет мастера</a>
            <h1 class="text-display" style="font-size:2rem;margin:0.5rem 0 1.5rem">Мой склад</h1>

            <div class="card" style="overflow-x:auto;margin-bottom:1.5rem">
                <h3 style="margin-bottom:1rem">Остатки</h3>
                <table>
                    <thead><tr><th>Позиция</th><th>Остаток</th><th>Мин. остаток</th></tr></thead>
                    <tbody>{stock_rows or '<tr><td colspan="3" style="text-align:center;padding:2rem;color:var(--color-muted)">Номенклатура пуста</td></tr>'}</tbody>
                </table>
            </div>

            <div class="card" style="overflow-x:auto">
                <h3 style="margin-bottom:1rem">История движений</h3>
                <table>
                    <thead><tr><th>Дата</th><th>Позиция</th><th>Тип</th><th>Изменение</th><th>Комментарий</th></tr></thead>
                    <tbody>{movement_rows or '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-muted)">Движений пока нет</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </main>

    {render_footer(user)}
</body>
</html>"""
