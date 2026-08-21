# app/web/pages/business/tabs/billing.py
"""Вкладка «Тариф» — статус оплаты бизнес-подписки (CloudPayments) и две
ручные кнопки, backend для которых уже есть в app/api/v1/endpoints/payments.py:
«Оплатить» (/business/manual-charge) и «Отменить автопродление»
(/business/cancel-auto-renew). Сама привязка/списание карты всегда идёт
через виджет CloudPayments в браузере — эта вкладка только готовит счёт и
показывает текущий статус."""
from app.core.config import settings
from app.models.models import Salon, SalonSubscriptionStatus
from app.services.tariffs import TARIFF_CATALOG

_STATUS_LABELS = {
    SalonSubscriptionStatus.NONE: ("Тариф не выбран", "var(--color-muted)"),
    SalonSubscriptionStatus.TRIALING: ("Пробный период", "#f59e0b"),
    SalonSubscriptionStatus.ACTIVE: ("Активна", "#22c55e"),
    SalonSubscriptionStatus.PAST_DUE: ("Платёж не прошёл", "#ef4444"),
    SalonSubscriptionStatus.CANCELED: ("Отменена", "var(--color-muted)"),
}


def render_billing_tab(salon: Salon, can_manage: bool) -> str:
    if not can_manage:
        return '<div id="tab-billing" class="tab-content"></div>'

    plan = salon.business_tier
    tariff = TARIFF_CATALOG.get(plan)
    plan_name = tariff.name if tariff else (plan or "не выбран")

    if not plan:
        return f"""
        <div id="tab-billing" class="tab-content">
            <div class="card" style="padding:1.75rem;max-width:34rem">
                <h3 style="margin:0 0 0.5rem">Тариф не выбран</h3>
                <p class="text-muted" style="margin:0">
                    Выберите тариф на <a href="/business#pricing" class="text-link">странице тарифов</a>.
                </p>
            </div>
        </div>"""

    status = salon.subscription_status
    label, color = _STATUS_LABELS.get(status, ("—", "var(--color-muted)"))

    date_fmt = "%d.%m.%Y"
    lines = [f'<span style="color:{color};font-weight:600">{label}</span>']
    if status == SalonSubscriptionStatus.TRIALING and salon.trial_ends_at:
        lines.append(f"до {salon.trial_ends_at.strftime(date_fmt)}")
    elif status in (SalonSubscriptionStatus.ACTIVE, SalonSubscriptionStatus.PAST_DUE, SalonSubscriptionStatus.CANCELED) and salon.subscription_expires_at:
        lines.append(f"доступ до {salon.subscription_expires_at.strftime(date_fmt)}")
    status_line = " · ".join(lines)

    renew_line = ""
    if salon.auto_renew:
        renew_line = '<p class="text-muted" style="margin:0.25rem 0 0;font-size:0.85rem">Автопродление включено'
        if salon.card_last4:
            renew_line += f" · карта •• {salon.card_last4}"
        renew_line += "</p>"
    elif tariff and tariff.billing == "per_employee":
        renew_line = ''

    employee_input = ""
    if tariff and tariff.billing == "per_employee":
        employee_input = f"""
        <div style="margin-top:1rem;max-width:12rem">
            <label class="form-label">Сотрудников (1–{tariff.max_employees})</label>
            <input type="number" id="billing-employee-count" min="{tariff.min_employees}"
                   max="{tariff.max_employees}" value="{tariff.min_employees}" class="form-input">
        </div>"""

    if not settings.CLOUDPAYMENTS_ENABLED:
        actions_html = '<p class="text-muted" style="margin-top:1rem;font-size:0.85rem">Оплата картой скоро появится.</p>'
    else:
        pay_btn = (
            f'<button id="billingPayBtn" class="btn-primary" data-salon-id="{salon.id}" '
            'style="padding:0.65rem 1.4rem;border-radius:0.6rem">Оплатить</button>'
        )
        cancel_btn = (
            f'<button id="billingCancelBtn" class="btn-outline" data-salon-id="{salon.id}" '
            'style="padding:0.65rem 1.4rem;border-radius:0.6rem">Отменить автопродление</button>'
            if salon.auto_renew else ""
        )
        actions_html = (
            f'<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.25rem">{pay_btn}{cancel_btn}</div>'
            f'<p class="checkout-note" id="billing-note" style="margin-top:0.75rem;min-height:1.2em"></p>'
        )

    return f"""
    <div id="tab-billing" class="tab-content">
        <div class="card" style="padding:1.75rem;max-width:34rem">
            <h3 style="margin:0 0 0.5rem">Тариф «{plan_name}»</h3>
            <p style="margin:0">{status_line}</p>
            {renew_line}
            {employee_input}
            {actions_html}
        </div>
    </div>"""
