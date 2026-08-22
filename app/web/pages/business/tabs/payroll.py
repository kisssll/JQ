# app/web/pages/business/tabs/payroll.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models.models import MasterPayrollSettings, User as UserModel
from app.services.payroll_service import PayrollService
from app.web.components.icons import ICON_CHEVRON_DOWN, ICON_CHEVRON_UP


def _parse_month(raw: str | None) -> datetime:
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m")
        except ValueError:
            pass
    return datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def render_payroll_tab(db: AsyncSession, salon, masters, master_ids, date_from_raw: str, date_to_raw: str) -> str:
    """Вкладка «Зарплаты» — оклад + % от выручки + ручные бонусы/штрафы за
    ДИАПАЗОН месяцев (с — по)."""

    month_from = _parse_month(date_from_raw)
    month_to = _parse_month(date_to_raw or date_from_raw)
    from_str = month_from.strftime("%Y-%m")
    to_str = month_to.strftime("%Y-%m")

    master_user_names = {}
    for m in masters:
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        master_user_names[m.id] = mu.full_name if mu else "—"

    rows_html = ""
    cards_html = ""
    total_payroll = 0
    total_revenue = 0

    for m in masters:
        result = await PayrollService.calculate_payroll_range(db, master_id=m.id, month_from=month_from, month_to=month_to)
        total_payroll += result["total"]
        total_revenue += result["revenue"]

        adj_summary = ", ".join(
            f"{'+' if a.amount > 0 else ''}{a.amount} ₽ ({a.reason})" for a in result["adjustments"]
        ) or "—"

        salary_str = f"{result['base_salary']:,}".replace(",", " ")
        revenue_str = f"{result['revenue']:,}".replace(",", " ")
        commission_str = f"{result['commission']:,}".replace(",", " ")
        total_str = f"{result['total']:,}".replace(",", " ")
        master_name = master_user_names.get(m.id, "—")

        rows_html += f"""
        <tr>
            <td><strong>{master_name}</strong></td>
            <td>{salary_str} ₽</td>
            <td>{result['commission_percent']:g}%</td>
            <td>{revenue_str} ₽</td>
            <td>{commission_str} ₽</td>
            <td class="adj-cell">{adj_summary}</td>
            <td class="total-cell">{total_str} ₽</td>
            <td class="actions-cell">
                <button class="btn-outline" onclick="openRateModal({m.id}, {result['base_salary_monthly']}, {result['commission_percent']})">Ставка</button>
                <button class="btn-outline" onclick="openAdjustmentModal({m.id})">Бонус/штраф</button>
            </td>
        </tr>"""

        cards_html += f"""
        <div class="payroll-card">
            <div class="payroll-card-header">
                <span class="payroll-card-name">{master_name}</span>
                <span class="payroll-card-chevron">{ICON_CHEVRON_DOWN}</span>
            </div>
            <div class="payroll-card-body">
                <div class="payroll-card-row">
                    <span class="payroll-card-label">Оклад</span>
                    <span>{salary_str} ₽</span>
                </div>
                <div class="payroll-card-row">
                    <span class="payroll-card-label">% от выручки</span>
                    <span>{result['commission_percent']:g}%</span>
                </div>
                <div class="payroll-card-row">
                    <span class="payroll-card-label">Выручка</span>
                    <span>{revenue_str} ₽</span>
                </div>
                <div class="payroll-card-row">
                    <span class="payroll-card-label">Комиссия</span>
                    <span>{commission_str} ₽</span>
                </div>
                <div class="payroll-card-row">
                    <span class="payroll-card-label">Бонусы/штрафы</span>
                    <span>{adj_summary}</span>
                </div>
                <div class="payroll-card-row">
                    <span class="payroll-card-label">Итого</span>
                    <span class="payroll-card-total">{total_str} ₽</span>
                </div>
                <div class="payroll-card-actions">
                    <button class="btn-outline" onclick="openRateModal({m.id}, {result['base_salary_monthly']}, {result['commission_percent']})">Ставка</button>
                    <button class="btn-outline" onclick="openAdjustmentModal({m.id})">Бонус/штраф</button>
                </div>
            </div>
        </div>"""

    if not rows_html:
        rows_html = '<tr><td colspan="8" class="empty-state">Мастеров пока нет</td></tr>'
        cards_html = '<div class="empty-state">Мастеров пока нет</div>'

    master_options = "".join(f'<option value="{m.id}">{master_user_names.get(m.id, "—")}</option>' for m in masters)

    return f"""
    <div id="tab-payroll" class="tab-content">
        <!-- Форма выбора периода -->
        <form method="get" action="/business/dashboard" class="payroll-period-form">
            <input type="hidden" name="salon_id" value="{salon.id}">
            <input type="hidden" name="tab" value="payroll">
            <div>
                <label class="period-label">Период: с</label>
                <input type="month" name="date_from" class="period-input custom-date" value="{from_str}" max="{to_str}">
            </div>
            <div>
                <label class="period-label">по</label>
                <input type="month" name="date_to" class="period-input custom-date" value="{to_str}" min="{from_str}">
            </div>
            <button type="submit" class="btn-outline period-submit">Показать</button>
        </form>

        <!-- KPI карточки -->
        <div class="payroll-kpi">
            <div class="kpi-card">
                <div class="kpi-label">Выручка за период</div>
                <div class="kpi-value" style="color:#22c55e">{f"{total_revenue:,}".replace(",", " ")} ₽</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Фонд зарплаты</div>
                <div class="kpi-value" style="color:#f59e0b">{f"{total_payroll:,}".replace(",", " ")} ₽</div>
            </div>
        </div>

        <!-- Заголовок таблицы -->
        <h3 class="payroll-section-title">Сотрудники</h3>

        <!-- Десктопная таблица -->
        <div class="card payroll-table-wrap">
            <table class="payroll-table">
                <thead>
                    <tr>
                        <th>Мастер</th>
                        <th>Оклад</th>
                        <th>%</th>
                        <th>Выручка</th>
                        <th>Комиссия</th>
                        <th>Бонусы/штрафы</th>
                        <th>Итого</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>

        <!-- Мобильные карточки -->
        <div class="payroll-mobile">
            {cards_html}
        </div>
    </div>

    <!-- Модалка ставки -->
    <div class="payroll-modal-overlay" id="rateModal">
        <div class="payroll-modal-box">
            <h3>Ставка мастера</h3>
            <form id="rateForm">
                <label class="modal-label">Оклад за месяц, ₽</label>
                <input type="number" id="rateSalary" name="base_salary" class="modal-input" required>
                <label class="modal-label">% от выручки</label>
                <input type="number" step="0.1" id="rateCommission" name="commission_percent" class="modal-input" required>
                <div class="payroll-modal-actions">
                    <button type="button" class="btn-outline" onclick="closeModal('rateModal')">Отмена</button>
                    <button type="submit" class="btn-primary">Сохранить</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Модалка бонуса/штрафа -->
    <div class="payroll-modal-overlay" id="adjustmentModal">
        <div class="payroll-modal-box">
            <h3>Бонус / штраф</h3>
            <form id="adjustmentForm">
                <label class="modal-label">Сумма (отрицательная — штраф)</label>
                <input type="number" id="adjustmentAmount" name="amount" class="modal-input" required>
                <label class="modal-label">Причина</label>
                <input type="text" id="adjustmentReason" name="reason" class="modal-input" required>
                <label class="modal-label">Месяц начисления</label>
                <input type="month" id="adjustmentMonth" name="period_month" class="modal-input" value="{to_str}" required>
                <div class="payroll-modal-actions">
                    <button type="button" class="btn-outline" onclick="closeModal('adjustmentModal')">Отмена</button>
                    <button type="submit" class="btn-primary">Начислить</button>
                </div>
            </form>
        </div>
    </div>

    """