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
from app.web.components.escaping import e
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Payment, PaymentKind, PaymentStatus, Salon, SalonSubscriptionStatus
from app.services.subscription import (
    downgrade_available_at, has_access, suggested_downgrade,
)
from app.services.tariffs import TARIFF_CATALOG, compute_amount, resolve_plan_for_employee_count
from app.web.tariff_presentation import all_plans

# Статус читается цветом, а не только текстом. Цвета — из токенов: раньше тут
# стояли #f59e0b/#22c55e/#ef4444, мимо палитры продукта.
_STATUS_TONE = {
    SalonSubscriptionStatus.NONE: ("Тариф не выбран", "is-none"),
    SalonSubscriptionStatus.TRIALING: ("Пробный период", "is-trial"),
    SalonSubscriptionStatus.ACTIVE: ("Активна", "is-active"),
    SalonSubscriptionStatus.PAST_DUE: ("Платёж не прошёл", "is-failed"),
    SalonSubscriptionStatus.CANCELED: ("Отменена", "is-none"),
}
_DATE_FMT = "%d.%m.%Y"


def _money(value) -> str:
    return f"{int(round(float(value or 0))):,}".replace(",", " ")


def _tariff_cards(current_plan, suggested: str) -> str:
    """Карточки тарифов: название, размер салона, цена и состав.

    Раньше в карточке были только имя и цена — понять, чем «Лайт» отличается
    от «Бизнеса», можно было лишь уйдя на лендинг. Тексты берём из общего
    app.web.tariff_presentation, цену — из TARIFF_CATALOG, чтобы витрина не
    разошлась с суммой, которая реально спишется.

    «Индивидуальный» стоит в том же ряду: при штате >20 мастеров
    resolve_plan_for_employee_count возвращает 'custom', и раньше выбрать его
    было негде — владелец упирался в тупик.
    """
    cards = ""
    for view in all_plans():
        plan = view["plan"]
        is_current = plan == current_plan
        is_checked = plan == (current_plan or suggested)
        features = "".join(f"<li>{f}</li>" for f in view["features"][:4])
        badge = '<span class="billing-plan-badge">Ваш тариф</span>' if is_current else (
            '<span class="billing-plan-badge is-suggested">Подходит по штату</span>'
            if plan == suggested and not current_plan else ""
        )
        # custom оплачивается не сам — по нему оставляют заявку
        period = f'<span class="billing-plan-period">{view["period"]}</span>' if view["period"] else ""
        cards += f"""
        <label class="billing-plan{' is-current' if is_current else ''}" data-plan="{plan}">
            <input type="radio" name="billing-plan" value="{plan}"{' checked' if is_checked else ''}>
            <span class="billing-plan-head">
                <span class="billing-plan-name">{e(view["name"])}</span>
                {badge}
            </span>
            <span class="billing-plan-size">{view["size"]}</span>
            <span class="billing-plan-price">{view["price"]}{period}</span>
            <ul class="billing-plan-features">{features}</ul>
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
        return '<p class="billing-muted">Платежей пока не было.</p>'

    status_labels = {
        PaymentStatus.SUCCEEDED: ("оплачен", "is-active"),
        PaymentStatus.PENDING: ("в обработке", "is-trial"),
        PaymentStatus.FAILED: ("отклонён", "is-failed"),
        PaymentStatus.REFUNDED: ("возвращён", "is-none"),
    }
    items = ""
    for p in rows:
        label, tone = status_labels.get(p.status, ("—", "is-none"))
        when = (p.paid_at or p.created_at)
        tariff = TARIFF_CATALOG.get(p.plan)
        items += f"""
        <tr>
            <td>{when.strftime(_DATE_FMT) if when else '—'}</td>
            <td>{e(tariff.name if tariff else p.plan)}</td>
            <td><strong>{_money(p.amount)} ₽</strong></td>
            <td><span class="billing-status {tone}">{label}</span></td>
        </tr>"""
    return f"""
    <div class="billing-history-scroll">
        <table class="billing-history">
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
        <section class="card billing-card">
            <h3 class="billing-card-title">{'Выберите тариф' if first_time else 'Тариф'}</h3>
            <p class="billing-muted">{masters_note}</p>
            <div class="billing-plan-grid">{cards}</div>
            <button id="billingSelectPlanBtn" class="btn-primary billing-btn" data-salon-id="{salon.id}"
                    data-active-masters="{active_masters}" data-mode="{'init' if first_time else 'change'}"
                    {'disabled' if not editable else ''}>{button_label}</button>
            <p class="checkout-note billing-note" id="billing-note">{note}</p>
        </section>"""


async def render_billing_tab(
    db: AsyncSession, salon: Salon, can_manage: bool, active_masters: int = 0
) -> str:
    """Две колонки: слева выбор тарифа и история, справа липкая сводка.

    До этого все блоки шли столбиком и были зажаты в 34rem при колонке панели
    в 1360px — справа простаивало больше половины экрана, а прокрутка выходила
    на 1300px. Сводка со статусом и суммой теперь всегда перед глазами."""
    if not can_manage:
        return '<div id="tab-billing" class="tab-content"></div>'

    status = salon.subscription_status
    first_time = status == SalonSubscriptionStatus.NONE
    selector = _selector_html(salon, active_masters, editable=True)

    # Тариф ещё не выбран — показывать нечего, кроме самого выбора.
    if first_time:
        return f'<div id="tab-billing" class="tab-content">{selector}</div>'

    label, tone = _STATUS_TONE.get(status, ("—", "is-none"))
    lines = [f'<span class="billing-status {tone}">{label}</span>']
    if status == SalonSubscriptionStatus.TRIALING and salon.trial_ends_at:
        lines.append(f"бесплатно до {salon.trial_ends_at.strftime(_DATE_FMT)}")
    elif salon.subscription_expires_at:
        lines.append(f"оплачено до {salon.subscription_expires_at.strftime(_DATE_FMT)}")
    status_line = " · ".join(lines)

    # Доступ истёк — объясняем последствия прямо, без поиска причин
    access_banner = ""
    if not has_access(salon):
        access_banner = (
            '<div class="billing-banner">'
            '<strong>Салон скрыт из каталога.</strong> Подписка закончилась — карточка '
            'не показывается клиентам и новая запись закрыта. Уже созданные записи '
            'сохранены: оплатите тариф, и салон вернётся в ленту.</div>'
        )

    renew_line = ""
    if salon.auto_renew:
        card = f" · карта •• {salon.card_last4}" if salon.card_last4 else ""
        renew_line = f'<p class="billing-muted">Автопродление включено{card}</p>'
    elif settings.TKASSA_ENABLED:
        renew_line = ('<p class="billing-muted">Автопродление выключено — '
                      'продлевайте вручную кнопкой «Оплатить».</p>')

    # Подсказка о понижении живёт рядом с выбором тарифа, а не в сводке:
    # это действие про смену плана, а не про текущее состояние оплаты.
    downgrade_html = ""
    cheaper = suggested_downgrade(salon, active_masters)
    if cheaper:
        blocked_until = downgrade_available_at(salon)
        cheaper_name = TARIFF_CATALOG[cheaper].name
        if blocked_until:
            downgrade_html = (
                f'<p class="billing-hint">По числу мастеров вам подошёл бы тариф '
                f'«{cheaper_name}», но понижать можно раз в 3 месяца — '
                f'следующее понижение с {blocked_until.strftime(_DATE_FMT)}.</p>'
            )
        else:
            downgrade_html = (
                f'<div class="billing-hint is-action">'
                f'<p>У вас {active_masters} активных мастеров — можно перейти на '
                f'«{cheaper_name}» и платить меньше.</p>'
                f'<button id="billingDowngradeBtn" class="btn-outline billing-btn" '
                f'data-salon-id="{salon.id}" data-plan="{cheaper}">'
                f'Понизить до «{cheaper_name}»</button></div>'
            )

    if not settings.TKASSA_ENABLED:
        actions_html = '<p class="billing-muted">Оплата картой скоро появится.</p>'
    else:
        # Предоплата вперёд: раньше платить можно было только помесячно.
        # Срок выбирается рядом с кнопкой и уходит в manual-charge.
        months_options = "".join(
            f'<option value="{m}">{label}</option>'
            for m, label in (
                (1, "на 1 месяц"), (3, "на 3 месяца"), (6, "на 6 месяцев"),
                (12, "на год"), (24, "на 2 года"),
            )
        )
        buttons = [
            f'<select id="billingMonths" class="billing-months custom-select" aria-label="Срок оплаты">{months_options}</select>',
            f'<button id="billingPayBtn" class="btn-primary billing-btn" '
            f'data-salon-id="{salon.id}">Оплатить</button>',
        ]
        if salon.auto_renew:
            buttons.append(f'<button id="billingCancelBtn" class="btn-outline billing-btn" '
                           f'data-salon-id="{salon.id}">Отменить автопродление</button>')
            buttons.append(f'<button id="billingCardBtn" class="btn-outline billing-btn" '
                           f'data-salon-id="{salon.id}">Сменить карту</button>')
        else:
            buttons.append(f'<button id="billingEnableRenewBtn" class="btn-outline billing-btn" '
                           f'data-salon-id="{salon.id}">Включить автопродление</button>')
        if status != SalonSubscriptionStatus.CANCELED:
            buttons.append(f'<button id="billingCancelSubBtn" class="btn-outline billing-btn is-danger" '
                           f'data-salon-id="{salon.id}">Отменить подписку</button>')
        actions_html = (
            f'<div class="billing-actions">{"".join(buttons)}</div>'
            f'<p class="checkout-note billing-note" id="billing-note"></p>'
        )

    plan_name = (TARIFF_CATALOG.get(salon.business_tier).name
                 if salon.business_tier in TARIFF_CATALOG else (salon.business_tier or "не выбран"))
    history = await _payments_history(db, salon.id)

    return f"""
    <div id="tab-billing" class="tab-content">
        {access_banner}
        <div class="billing-layout">
            <div class="billing-main">
                {selector}
                {downgrade_html}
                <section class="card billing-card">
                    <h3 class="billing-card-title">История платежей</h3>
                    {history}
                </section>
            </div>

            <aside class="billing-side">
                <section class="card billing-card">
                    <h3 class="billing-card-title">Тариф «{plan_name}»</h3>
                    <p class="billing-status-line">{status_line}</p>
                    {renew_line}
                    {_next_charge_block(salon, active_masters)}
                    <p class="billing-muted">Активных мастеров: {active_masters}. При найме
                        разница доплачивается за оставшиеся дни месяца и попадает в
                        следующий счёт.</p>
                    {actions_html}
                </section>
            </aside>
        </div>
    </div>"""
