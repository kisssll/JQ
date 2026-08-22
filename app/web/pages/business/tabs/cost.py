# app/web/pages/business/tabs/cost.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models.models import User as UserModel
from app.services.payroll_service import PayrollService
from app.web.components.hint import hint as _hint


def _parse_period(period: str | None) -> datetime:
    if period:
        try:
            return datetime.strptime(period, "%Y-%m")
        except ValueError:
            pass
    return datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def render_cost_tab(db: AsyncSession, salon, masters, master_ids, period_raw: str) -> str:
    """Вкладка «Себестоимость» — реальная прибыль с учётом расходников и зарплат."""

    period = _parse_period(period_raw)
    period_str = period.strftime("%Y-%m")

    master_user_names = {}
    for m in masters:
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        master_user_names[m.id] = mu.full_name if mu else "—"

    rows_html = ""
    total_revenue = total_cogs = total_payroll = 0
    for m in masters:
        payroll = await PayrollService.calculate_payroll(db, master_id=m.id, period_month=period)
        cogs = await PayrollService.calculate_cogs(db, master_id=m.id, period_month=period)
        revenue = payroll["revenue"]
        margin = revenue - cogs - payroll["total"]

        total_revenue += revenue
        total_cogs += cogs
        total_payroll += payroll["total"]

        revenue_str = f"{revenue:,}".replace(",", " ")
        cogs_str = f"{cogs:,}".replace(",", " ")
        payroll_str = f"{payroll['total']:,}".replace(",", " ")
        margin_str = f"{margin:,}".replace(",", " ")
        margin_color = "#22c55e" if margin >= 0 else "#ef4444"

        rows_html += f"""
        <tr>
            <td><strong>{master_user_names.get(m.id, '—')}</strong></td>
            <td>{revenue_str} ₽</td>
            <td style="color:#ef4444">{cogs_str} ₽</td>
            <td style="color:#f59e0b">{payroll_str} ₽</td>
            <td><strong style="color:{margin_color}">{margin_str} ₽</strong></td>
        </tr>"""

    total_profit = total_revenue - total_cogs - total_payroll
    profit_color = "#22c55e" if total_profit >= 0 else "#ef4444"

    if masters and total_revenue == 0 and total_cogs == 0 and total_payroll == 0:
        rows_html = '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-muted)">Данных за этот период нет</td></tr>'

    return f"""
    <div id="tab-cost" class="tab-content">
        <form method="get" action="/business/dashboard" style="display:flex;gap:0.75rem;align-items:flex-end;margin-bottom:1.5rem">
            <input type="hidden" name="salon_id" value="{salon.id}">
            <input type="hidden" name="tab" value="cost">
            <div>
                <label class="text-muted" style="display:block;font-size:0.75rem;margin-bottom:0.25rem">Период</label>
                <input type="month" name="period" class="custom-date" value="{period_str}" style="padding:0.5rem;border:1px solid var(--color-border);border-radius:0.5rem">
            </div>
            <button type="submit" class="btn-outline">Показать</button>
        </form>

        <div class="analytics-kpi">
            <div class="kpi-card"><div class="kpi-label">Выручка</div><div class="kpi-value" style="color:#22c55e">{f"{total_revenue:,}".replace(",", " ")} ₽</div></div>
            <div class="kpi-card"><div class="kpi-label">Себестоимость расходников {_hint("Сумма реально списанных расходников по цене на момент списания — берётся из складских форм мастеров, а не из плановых норм расхода.")}</div><div class="kpi-value" style="color:#ef4444">{f"{total_cogs:,}".replace(",", " ")} ₽</div></div>
            <div class="kpi-card"><div class="kpi-label">Зарплаты {_hint("Начисления мастерам за период: ставка/процент от выручки плюс ручные бонусы, минус штрафы — как настроено во вкладке «Зарплаты».")}</div><div class="kpi-value" style="color:#f59e0b">{f"{total_payroll:,}".replace(",", " ")} ₽</div></div>
            <div class="kpi-card"><div class="kpi-label">Прибыль салона {_hint("Выручка минус себестоимость расходников минус зарплаты мастеров — то, что реально остаётся салону за период.")}</div><div class="kpi-value" style="color:{profit_color}">{f"{total_profit:,}".replace(",", " ")} ₽</div></div>
        </div>

        <div class="card" style="overflow-x:auto">
            <table>
                <thead><tr><th>Мастер</th><th>Выручка</th><th>Себестоимость</th><th>Зарплата</th><th>Маржа {_hint("Выручка минус себестоимость расходников минус зарплата этого мастера.")}</th></tr></thead>
                <tbody>{rows_html or '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-muted)">Мастеров пока нет</td></tr>'}</tbody>
            </table>
        </div>
        <p class="text-muted" style="font-size:0.8rem;margin-top:0.75rem">Себестоимость считается по фактическим складским списаниям (форма мастера после клиента), а не по нормам — это сумма реально потраченных расходников по цене на момент списания.</p>
    </div>"""
