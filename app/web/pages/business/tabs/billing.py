# app/web/pages/business/tabs/billing.py
"""Вкладка «Тариф» — статус оплаты бизнес-подписки (Т-Касса), выбор тарифа
(если ещё не выбран) и две ручные кнопки, backend для которых уже есть в
app/api/v1/endpoints/payments.py: «Оплатить» (/business/manual-charge) и
«Отменить автопродление» (/business/cancel-auto-renew). Сама оплата —
редирект на страницу Т-Кассы, эта вкладка только готовит платёж и
показывает текущий статус.

Тариф не фиксирован раз и навсегда: салон стартует с выбранного здесь (или
на /business/checkout) тарифа, а дальше при каждой следующей оплате сервер
сам пересчитывает план по фактическому числу активных мастеров (см.
app.services.tariffs.resolve_plan_for_employee_count) — вырос штат сверх
границы тарифа, следующий платёж спишется уже по новому."""
from app.core.config import settings
from app.models.models import Salon, SalonSubscriptionStatus
from app.services.tariffs import TARIFF_CATALOG, resolve_plan_for_employee_count

_STATUS_LABELS = {
    SalonSubscriptionStatus.NONE: ("Тариф не выбран", "var(--color-muted)"),
    SalonSubscriptionStatus.TRIALING: ("Пробный период", "#f59e0b"),
    SalonSubscriptionStatus.ACTIVE: ("Активна", "#22c55e"),
    SalonSubscriptionStatus.PAST_DUE: ("Платёж не прошёл", "#ef4444"),
    SalonSubscriptionStatus.CANCELED: ("Отменена", "var(--color-muted)"),
}


def _tariff_selector_html(active_masters: int, salon_id: int) -> str:
    suggested = resolve_plan_for_employee_count(active_masters)
    cards = "".join(
        f"""
        <label class="model-tariff-card" data-plan="{t.plan}">
            <input type="radio" name="billing-plan" value="{t.plan}" {"checked" if t.plan == suggested else ""}>
            <span class="model-tariff-name">{t.name}</span>
            <span class="model-tariff-price">{
                f"{int(t.unit_price)} ₽/мастер" if t.billing == "per_employee" else f"{int(t.amount)} ₽"
            }<span class="model-tariff-period">/мес</span></span>
        </label>"""
        for t in TARIFF_CATALOG.values()
    )
    renewal_html = ""
    if settings.TKASSA_ENABLED:
        renewal_html = """
        <div style="margin-top:1rem">
            <label class="form-label">Продление подписки</label>
            <label class="checkbox-label">
                <input type="radio" name="billing-renewal-mode" value="auto" class="checkbox-input" checked>
                <span class="checkbox-text">Автоматически каждый месяц (можно отменить в любой момент)</span>
            </label>
            <label class="checkbox-label">
                <input type="radio" name="billing-renewal-mode" value="manual" class="checkbox-input">
                <span class="checkbox-text">Буду продлевать вручную</span>
            </label>
        </div>"""
    masters_note = (
        f"Сейчас у вас {active_masters} {'активный мастер' if active_masters == 1 else 'активных мастеров'} — "
        f"подсветили подходящий тариф, но можно выбрать любой." if active_masters else
        "Мастеров пока не добавлено — можно начать с любого тарифа."
    )
    note = (
        "Первые 14 дней — бесплатно. Дальше тариф сам подстраивается под "
        "количество мастеров при каждой следующей оплате."
        if settings.TKASSA_ENABLED else
        "Пока тариф активируется сразу на пробный период — оплата картой скоро появится."
    )
    return f"""
    <div id="tab-billing" class="tab-content">
        <div class="card" style="padding:1.75rem;max-width:34rem">
            <h3 style="margin:0 0 0.5rem">Выберите тариф</h3>
            <p class="text-muted" style="margin:0 0 1rem;font-size:0.85rem">{masters_note}</p>
            <div class="model-tariff-grid">{cards}</div>
            {renewal_html}
            <button id="billingSelectPlanBtn" class="btn-primary" data-salon-id="{salon_id}"
                    data-active-masters="{active_masters}"
                    style="margin-top:1.25rem;padding:0.65rem 1.4rem;border-radius:0.6rem">Продолжить</button>
            <p class="checkout-note" id="billing-note" style="margin-top:0.75rem;min-height:1.2em">{note}</p>
        </div>
    </div>"""


def render_billing_tab(salon: Salon, can_manage: bool, active_masters: int = 0) -> str:
    if not can_manage:
        return '<div id="tab-billing" class="tab-content"></div>'

    plan = salon.business_tier
    tariff = TARIFF_CATALOG.get(plan)
    plan_name = tariff.name if tariff else (plan or "не выбран")

    if salon.subscription_status == SalonSubscriptionStatus.NONE:
        return _tariff_selector_html(active_masters, salon.id)

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

    masters_note = (
        f'<p class="text-muted" style="margin:0.5rem 0 0;font-size:0.8rem">'
        f'Активных мастеров: {active_masters}. Тариф автоматически подстраивается под их '
        f'число при каждой следующей оплате.</p>'
    )

    if not settings.TKASSA_ENABLED:
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
            {masters_note}
            {actions_html}
        </div>
    </div>"""
