# app/web/pages/business/tabs/payroll.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models.models import MasterPayrollSettings, User as UserModel
from app.services.payroll_service import PayrollService


def _parse_period(period: str | None) -> datetime:
    if period:
        try:
            return datetime.strptime(period, "%Y-%m")
        except ValueError:
            pass
    return datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def render_payroll_tab(db: AsyncSession, salon, masters, master_ids, period_raw: str) -> str:
    """Вкладка «Зарплаты» — оклад + % от выручки + ручные бонусы/штрафы."""

    period = _parse_period(period_raw)
    period_str = period.strftime("%Y-%m")

    master_user_names = {}
    for m in masters:
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        master_user_names[m.id] = mu.full_name if mu else "—"

    rows_html = ""
    total_payroll = 0
    total_revenue = 0
    for m in masters:
        result = await PayrollService.calculate_payroll(db, master_id=m.id, period_month=period)
        total_payroll += result["total"]
        total_revenue += result["revenue"]

        adj_summary = ", ".join(
            f"{'+' if a.amount > 0 else ''}{a.amount} ₽ ({a.reason})" for a in result["adjustments"]
        ) or "—"

        salary_str = f"{result['base_salary']:,}".replace(",", " ")
        revenue_str = f"{result['revenue']:,}".replace(",", " ")
        commission_str = f"{result['commission']:,}".replace(",", " ")
        total_str = f"{result['total']:,}".replace(",", " ")

        rows_html += f"""
        <tr>
            <td><strong>{master_user_names.get(m.id, '—')}</strong></td>
            <td>{salary_str} ₽</td>
            <td>{result['commission_percent']:g}%</td>
            <td>{revenue_str} ₽</td>
            <td>{commission_str} ₽</td>
            <td style="max-width:220px;font-size:0.8rem" class="text-muted">{adj_summary}</td>
            <td><strong style="color:#22c55e">{total_str} ₽</strong></td>
            <td>
                <button class="btn-outline" style="padding:0.35rem 0.75rem;font-size:0.75rem" onclick="openRateModal({m.id}, {result['base_salary']}, {result['commission_percent']})">Ставка</button>
                <button class="btn-outline" style="padding:0.35rem 0.75rem;font-size:0.75rem" onclick="openAdjustmentModal({m.id})">Бонус/штраф</button>
            </td>
        </tr>"""

    master_options = "".join(f'<option value="{m.id}">{master_user_names.get(m.id, "—")}</option>' for m in masters)

    return f"""
    <div id="tab-payroll" class="tab-content">
        <form method="get" action="/business/dashboard" style="display:flex;gap:0.75rem;align-items:flex-end;margin-bottom:1.5rem">
            <input type="hidden" name="salon_id" value="{salon.id}">
            <input type="hidden" name="tab" value="payroll">
            <div>
                <label class="text-muted" style="display:block;font-size:0.75rem;margin-bottom:0.25rem">Период</label>
                <input type="month" name="period" class="custom-date" value="{period_str}" style="padding:0.5rem;border:1px solid var(--color-border);border-radius:0.5rem">
            </div>
            <button type="submit" class="btn-outline">Показать</button>
        </form>

        <div class="analytics-kpi">
            <div class="kpi-card"><div class="kpi-label">Выручка за период</div><div class="kpi-value" style="color:#22c55e">{f"{total_revenue:,}".replace(",", " ")} ₽</div></div>
            <div class="kpi-card"><div class="kpi-label">Фонд зарплаты</div><div class="kpi-value" style="color:#f59e0b">{f"{total_payroll:,}".replace(",", " ")} ₽</div></div>
        </div>

        <div class="card" style="overflow-x:auto">
            <table>
                <thead>
                    <tr><th>Мастер</th><th>Оклад</th><th>%</th><th>Выручка</th><th>Комиссия</th><th>Бонусы/штрафы</th><th>Итого</th><th></th></tr>
                </thead>
                <tbody>
                    {rows_html or '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--color-muted)">Мастеров пока нет</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>

    <div class="modal-overlay" id="rateModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100;align-items:center;justify-content:center">
        <div class="card" style="max-width:360px;width:90%">
            <h3 style="margin-bottom:1rem">Ставка мастера</h3>
            <form id="rateForm">
                <label class="text-muted" style="display:block;font-size:0.8rem;margin-bottom:0.25rem">Оклад за месяц, ₽</label>
                <input type="number" id="rateSalary" name="base_salary" required style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem;margin-bottom:0.75rem">
                <label class="text-muted" style="display:block;font-size:0.8rem;margin-bottom:0.25rem">% от выручки</label>
                <input type="number" step="0.1" id="rateCommission" name="commission_percent" required style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem;margin-bottom:1rem">
                <div style="display:flex;gap:0.5rem">
                    <button type="button" class="btn-outline" style="flex:1" onclick="closeModal('rateModal')">Отмена</button>
                    <button type="submit" class="btn-primary" style="flex:1">Сохранить</button>
                </div>
            </form>
        </div>
    </div>

    <div class="modal-overlay" id="adjustmentModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100;align-items:center;justify-content:center">
        <div class="card" style="max-width:360px;width:90%">
            <h3 style="margin-bottom:1rem">Бонус / штраф</h3>
            <form id="adjustmentForm">
                <label class="text-muted" style="display:block;font-size:0.8rem;margin-bottom:0.25rem">Сумма (отрицательная — штраф)</label>
                <input type="number" id="adjustmentAmount" name="amount" required style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem;margin-bottom:0.75rem">
                <label class="text-muted" style="display:block;font-size:0.8rem;margin-bottom:0.25rem">Причина</label>
                <input type="text" id="adjustmentReason" name="reason" required style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem;margin-bottom:1rem">
                <div style="display:flex;gap:0.5rem">
                    <button type="button" class="btn-outline" style="flex:1" onclick="closeModal('adjustmentModal')">Отмена</button>
                    <button type="submit" class="btn-primary" style="flex:1">Начислить</button>
                </div>
            </form>
        </div>
    </div>

    <script>
    (function() {{
        const salonId = {salon.id};
        const period = "{period_str}";
        let activeMasterId = null;

        window.openRateModal = function(masterId, salary, commission) {{
            activeMasterId = masterId;
            document.getElementById('rateSalary').value = salary;
            document.getElementById('rateCommission').value = commission;
            document.getElementById('rateModal').style.display = 'flex';
        }};
        window.openAdjustmentModal = function(masterId) {{
            activeMasterId = masterId;
            document.getElementById('adjustmentAmount').value = '';
            document.getElementById('adjustmentReason').value = '';
            document.getElementById('adjustmentModal').style.display = 'flex';
        }};
        window.closeModal = function(id) {{
            document.getElementById(id).style.display = 'none';
        }};

        document.getElementById('rateForm').addEventListener('submit', function(e) {{
            e.preventDefault();
            this.action = '/api/v1/payroll/master/' + activeMasterId + '/settings';
            this.method = 'post';
            this.submit();
        }});
        document.getElementById('adjustmentForm').addEventListener('submit', function(e) {{
            e.preventDefault();
            const form = this;
            const periodInput = document.createElement('input');
            periodInput.type = 'hidden'; periodInput.name = 'period_month'; periodInput.value = period;
            form.appendChild(periodInput);
            form.action = '/api/v1/payroll/master/' + activeMasterId + '/adjustment';
            form.method = 'post';
            form.submit();
        }});
    }})();
    </script>"""
