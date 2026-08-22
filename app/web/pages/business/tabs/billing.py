# app/web/pages/business/tabs/billing.py
"""Вкладка «Тариф» — состояние подписки и всё управление ею.

Раньше вкладка умела мало: селектор тарифа показывался ТОЛЬКО пока тариф не
выбран (статус NONE), а дальше оставались две кнопки — «Оплатить» и «Отменить
автопродление». Сменить план вручную было нельзя (он молча пересчитывался по
числу мастеров при каждой оплате), вернуть автопродление — тоже, а истёкшая
подписка никак не объяснялась.

Теперь здесь: выбор/смена тарифа в любой момент, отдельная кнопка понижения
(с ограничением раз в 3 месяца), «Индивидуальный» с заявкой, расшифровка
ближайшего списания (тариф + накопленная доплата за рост штата), возврат
автопродления и смена карты, отмена подписки и история платежей.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Payment, PaymentKind, PaymentStatus, Salon, SalonSubscriptionStatus
from app.services.subscription import (
    downgrade_available_at, has_access, suggested_downgrade,
)
from app.services.tariffs import TARIFF_CATALOG, compute_amount, resolve_plan_for_employee_count

_STATUS_LABELS = {
    SalonSubscriptionStatus.NONE: ("Тариф не выбран", "var(--color-muted)"),
    SalonSubscriptionStatus.TRIALING: ("Пробный период", "#f59e0b"),
    SalonSubscriptionStatus.ACTIVE: ("Активна", "#22c55e"),
    SalonSubscriptionStatus.PAST_DUE: ("Платёж не прошёл", "#ef4444"),
    SalonSubscriptionStatus.CANCELED: ("Отменена", "var(--color-muted)"),
}
_DATE_FMT = "%d.%m.%Y"


def _money(value) -> str:
    return f"{int(round(float(value or 0))):,}".replace(",", " ")


def _tariff_cards(current_plan, suggested: str) -> str:
    """Карточки тарифов + «Индивидуальный» (для него оплаты нет — только заявка).

    Раньше карточки «Индивидуального» не было вовсе: при штате >20 мастеров
    resolve_plan_for_employee_count возвращает 'custom', а выбрать его было
    негде — владелец упирался в тупик.
    """
    cards = "".join(
        f"""
        <label class="model-tariff-card{' selected' if t.plan == current_plan else ''}" data-plan="{t.plan}">
            <input type="radio" name="billing-plan" value="{t.plan}" {"checked" if t.plan == (current_plan or suggested) else ""}>
            <span class="model-tariff-name">{t.name}</span>
            <span class="model-tariff-price">{
                f"{int(t.unit_price)} ₽/мастер" if t.billing == "per_employee" else f"{int(t.amount)} ₽"
            }<span class="model-tariff-period">/мес</span></span>
        </label>"""
        for t in TARIFF_CATALOG.values()
    )
    cards += """
        <label class="model-tariff-card" data-plan="custom">
            <input type="radio" name="billing-plan" value="custom">
            <span class="model-tariff-name">Индивидуальный</span>
            <span class="model-tariff-price">по запросу<span class="model-tariff-period"> · от 20 мастеров</span></span>
        </label>"""
    return cards


async def _payments_history(db: AsyncSession, salon_id: int) -> str:
    """Последние платежи салона. Верификационные списания на 1₽ не показываем —
    это техническая привязка карты, деньги возвращаются сразу."""
    rows = (await db.execute(
        select(Payment)
        .where(Payment.salon_id == salon_id, Payment.kind != PaymentKind.VERIFICATION)
        .order_by(Payment.created_at.desc()).limit(10)
    )).scalars().all()
    if not rows:
        return '<p class="text-muted" style="font-size:0.85rem;margin:0">Платежей пока не было.</p>'

    status_labels = {
        PaymentStatus.SUCCEEDED: ("оплачен", "#22c55e"),
        PaymentStatus.PENDING: ("в обработке", "#f59e0b"),
        PaymentStatus.FAILED: ("отклонён", "#ef4444"),
        PaymentStatus.REFUNDED: ("возвращён", "var(--color-muted)"),
    }
    items = ""
    for p in rows:
        label, color = status_labels.get(p.status, ("—", "var(--color-muted)"))
        when = (p.paid_at or p.created_at)
        tariff = TARIFF_CATALOG.get(p.plan)
        items += f"""
        <tr>
            <td>{when.strftime(_DATE_FMT) if when else '—'}</td>
            <td>{tariff.name if tariff else p.plan}</td>
            <td><strong>{_money(p.amount)} ₽</strong></td>
            <td style="color:{color}">{label}</td>
        </tr>"""
    return f"""
    <div style="overflow-x:auto">
        <table style="width:100%;font-size:0.85rem">
            <thead><tr><th>Дата</th><th>Тариф</th><th>Сумма</th><th>Статус</th></tr></thead>
            <tbody>{items}</tbody>
        </table>
    </div>"""


def _next_charge_block(salon: Salon, active_masters: int) -> str:
    """Сколько и когда спишется: тариф по текущему штату + накопленная доплата."""
    plan = salon.business_tier or resolve_plan_for_employee_count(active_masters)
    try:
        base = compute_amount(plan, active_masters)
    except Exception:
        return ""  # «Индивидуальный»: сумму считает продавец
    pending = float(salon.pending_proration or 0)
    total = float(base) + pending
    when = salon.subscription_expires_at
    when_str = f" · {when.strftime(_DATE_FMT)}" if when else ""
    pending_str = (
        f'<span class="text-muted"> (тариф {_money(base)} ₽ + доплата за новых мастеров {_money(pending)} ₽)</span>'
        if pending > 0 else ""
    )
    return (
        f'<p style="margin:0.5rem 0 0;font-size:0.9rem">Следующее списание: '
        f'<strong>{_money(total)} ₽</strong>{when_str}{pending_str}</p>'
    )


def _selector_html(salon: Salon, active_masters: int, editable: bool) -> str:
    suggested = resolve_plan_for_employee_count(active_masters)
    cards = _tariff_cards(salon.business_tier, suggested)
    renewal_html = ""
    if settings.TKASSA_ENABLED and salon.subscription_status == SalonSubscriptionStatus.NONE:
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

    first_time = salon.subscription_status == SalonSubscriptionStatus.NONE
    masters_note = (
        f"Сейчас у вас {active_masters} {'активный мастер' if active_masters == 1 else 'активных мастеров'} — "
        f"подсветили подходящий тариф, но можно выбрать любой." if active_masters else
        "Мастеров пока не добавлено — можно начать с любого тарифа."
    )
    note = (
        "Первые 14 дней — бесплатно. Дальше при росте штата разница доплачивается "
        "за оставшиеся дни месяца и попадает в следующий счёт."
        if first_time else
        "Повышение действует со следующего счёта (разница за остаток месяца — в него же). "
        "Понижение доступно раз в 3 месяца."
    )
    button_label = "Продолжить" if first_time else "Сменить тариф"
    return f"""
        <div class="card" style="padding:1.75rem;max-width:34rem">
            <h3 style="margin:0 0 0.5rem">{'Выберите тариф' if first_time else 'Тариф'}</h3>
            <p class="text-muted" style="margin:0 0 1rem;font-size:0.85rem">{masters_note}</p>
            <div class="model-tariff-grid">{cards}</div>
            {renewal_html}
            <button id="billingSelectPlanBtn" class="btn-primary" data-salon-id="{salon.id}"
                    data-active-masters="{active_masters}" data-mode="{'init' if first_time else 'change'}"
                    {'disabled' if not editable else ''}
                    style="margin-top:1.25rem;padding:0.65rem 1.4rem;border-radius:0.6rem">{button_label}</button>
            <p class="checkout-note" id="billing-note" style="margin-top:0.75rem;min-height:1.2em">{note}</p>
        </div>"""


async def render_billing_tab(
    db: AsyncSession, salon: Salon, can_manage: bool, active_masters: int = 0
) -> str:
    if not can_manage:
        return '<div id="tab-billing" class="tab-content"></div>'

    status = salon.subscription_status
    first_time = status == SalonSubscriptionStatus.NONE
    selector = _selector_html(salon, active_masters, editable=True)

    if first_time:
        return f'<div id="tab-billing" class="tab-content">{selector}</div>'

    label, color = _STATUS_LABELS.get(status, ("—", "var(--color-muted)"))
    lines = [f'<span style="color:{color};font-weight:600">{label}</span>']
    if status == SalonSubscriptionStatus.TRIALING and salon.trial_ends_at:
        lines.append(f"бесплатно до {salon.trial_ends_at.strftime(_DATE_FMT)}")
    elif salon.subscription_expires_at:
        lines.append(f"оплачено до {salon.subscription_expires_at.strftime(_DATE_FMT)}")
    status_line = " · ".join(lines)

    # Доступ истёк — объясняем последствия прямо, без поиска причин
    access_banner = ""
    if not has_access(salon):
        access_banner = (
            '<div class="alert alert-error" style="margin-bottom:1rem">'
            '<strong>Салон скрыт из каталога.</strong> Подписка закончилась — карточка '
            'не показывается клиентам и новая запись закрыта. Уже созданные записи '
            'сохранены: оплатите тариф, и салон вернётся в ленту.</div>'
        )

    renew_line = ""
    if salon.auto_renew:
        renew_line = '<p class="text-muted" style="margin:0.25rem 0 0;font-size:0.85rem">Автопродление включено'
        if salon.card_last4:
            renew_line += f" · карта •• {salon.card_last4}"
        renew_line += "</p>"
    elif settings.TKASSA_ENABLED:
        renew_line = ('<p class="text-muted" style="margin:0.25rem 0 0;font-size:0.85rem">'
                      'Автопродление выключено — продлевайте вручную кнопкой «Оплатить».</p>')

    # Подсказка о понижении: понижаем только вручную, поэтому о возможности
    # платить меньше салон должен узнать от нас, а не переплачивать молча.
    downgrade_html = ""
    cheaper = suggested_downgrade(salon, active_masters)
    if cheaper:
        blocked_until = downgrade_available_at(salon)
        cheaper_name = TARIFF_CATALOG[cheaper].name
        if blocked_until:
            downgrade_html = (
                f'<p class="text-muted" style="margin:0.5rem 0 0;font-size:0.85rem">'
                f'По числу мастеров вам подошёл бы тариф «{cheaper_name}», но понижать можно '
                f'раз в 3 месяца — следующее понижение с {blocked_until.strftime(_DATE_FMT)}.</p>'
            )
        else:
            downgrade_html = (
                f'<div style="margin-top:0.75rem"><p style="margin:0 0 0.4rem;font-size:0.85rem">'
                f'У вас {active_masters} активных мастеров — можно перейти на «{cheaper_name}» и платить меньше.</p>'
                f'<button id="billingDowngradeBtn" class="btn-outline" data-salon-id="{salon.id}" '
                f'data-plan="{cheaper}" style="padding:0.5rem 1.1rem;border-radius:0.6rem">'
                f'Понизить до «{cheaper_name}»</button></div>'
            )

    if not settings.TKASSA_ENABLED:
        actions_html = ('<p class="text-muted" style="margin-top:1rem;font-size:0.85rem">'
                        'Оплата картой скоро появится.</p>')
    else:
        buttons = [
            f'<button id="billingPayBtn" class="btn-primary" data-salon-id="{salon.id}" '
            'style="padding:0.65rem 1.4rem;border-radius:0.6rem">Оплатить</button>'
        ]
        if salon.auto_renew:
            buttons.append(
                f'<button id="billingCancelBtn" class="btn-outline" data-salon-id="{salon.id}" '
                'style="padding:0.65rem 1.4rem;border-radius:0.6rem">Отменить автопродление</button>'
            )
            buttons.append(
                f'<button id="billingCardBtn" class="btn-outline" data-salon-id="{salon.id}" '
                'style="padding:0.65rem 1.4rem;border-radius:0.6rem">Сменить карту</button>'
            )
        else:
            buttons.append(
                f'<button id="billingEnableRenewBtn" class="btn-outline" data-salon-id="{salon.id}" '
                'style="padding:0.65rem 1.4rem;border-radius:0.6rem">Включить автопродление</button>'
            )
        if status != SalonSubscriptionStatus.CANCELED:
            buttons.append(
                f'<button id="billingCancelSubBtn" class="btn-outline" data-salon-id="{salon.id}" '
                'style="padding:0.65rem 1.4rem;border-radius:0.6rem;color:#ef4444;border-color:#ef4444">'
                'Отменить подписку</button>'
            )
        actions_html = (
            f'<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.25rem">{"".join(buttons)}</div>'
            f'<p class="checkout-note" id="billing-note" style="margin-top:0.75rem;min-height:1.2em"></p>'
        )

    plan_name = (TARIFF_CATALOG.get(salon.business_tier).name
                 if salon.business_tier in TARIFF_CATALOG else (salon.business_tier or "не выбран"))
    history = await _payments_history(db, salon.id)

    return f"""
    <div id="tab-billing" class="tab-content">
        {access_banner}
        <div class="card" style="padding:1.75rem;max-width:34rem;margin-bottom:1.5rem">
            <h3 style="margin:0 0 0.5rem">Тариф «{plan_name}»</h3>
            <p style="margin:0">{status_line}</p>
            {renew_line}
            {_next_charge_block(salon, active_masters)}
            <p class="text-muted" style="margin:0.5rem 0 0;font-size:0.8rem">
                Активных мастеров: {active_masters}. При найме разница доплачивается
                за оставшиеся дни месяца и попадает в следующий счёт.</p>
            {downgrade_html}
            {actions_html}
        </div>

        {selector}

        <div class="card" style="padding:1.75rem;max-width:34rem;margin-top:1.5rem">
            <h3 style="margin:0 0 0.75rem">История платежей</h3>
            {history}
        </div>
    </div>"""
