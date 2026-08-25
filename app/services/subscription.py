# app/services/subscription.py
"""Правила подписки: срок доступа, доплата за рост штата, смена тарифа.

Раньше тариф почти ни на что не влиял — единственной проверкой был запрет
публикации без подписки, а видимость салона держалась на published_at. Здесь
собраны правила, которые делают тариф настоящим:

  * срок доступа (access_until) — единственное, что спрашивают каталог и
    запись; политика запаса (триал/после оплаты) живёт только тут;
  * доплата за рост штата — «планка» оплаченного штата + накопленная сумма;
  * ограничения смены тарифа — повышение свободно, понижение раз в 3 месяца.

Денежные величины — Decimal, как в tariffs.py (сумму платежа считает сервер).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.services.tariffs import (
    TARIFF_CATALOG, TariffError, compute_amount, resolve_plan_for_employee_count,
)

# Запас после бесплатного периода: новый салон не выпадает из ленты в ту же
# секунду, когда кончился триал (решение Артёма). После первой оплаты запаса
# нет — доступ строго до конца оплаченного периода.
TRIAL_GRACE_DAYS = 7
# Понизить тариф можно не чаще раза в этот срок (защита от «нанял-уволил»).
DOWNGRADE_COOLDOWN_DAYS = 90
# Делитель для доплаты за неполный месяц — фиксированные 30 дней, как в
# согласованной формуле (не длина конкретного месяца: проще и предсказуемее).
PRORATION_DIVISOR = 30


class SubscriptionError(ValueError):
    """Нарушение правил подписки — показываем текст пользователю."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """БД может отдать naive datetime — приводим к UTC, чтобы сравнения не
    падали на «offset-naive vs offset-aware»."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── Срок доступа ─────────────────────────────────────────────────────────────

def access_until_for_trial(trial_ends_at: datetime) -> datetime:
    """Докуда открыт доступ на бесплатном периоде (с запасом)."""
    return _aware(trial_ends_at) + timedelta(days=TRIAL_GRACE_DAYS)


def access_until_for_paid(expires_at: datetime) -> datetime:
    """Докуда открыт доступ после оплаты — ровно до конца оплаченного срока."""
    return _aware(expires_at)


def has_access(target) -> bool:
    """Открыт ли доступ сейчас (лента, новая запись, анкета модели)."""
    until = _aware(getattr(target, "access_until", None))
    return until is not None and until > _now()


def access_clause(model):
    """SQL-условие «доступ по тарифу открыт» для выборок каталога."""
    return model.access_until > _now()


# ── Доплата за рост штата ────────────────────────────────────────────────────

def days_left_in_month(at: Optional[datetime] = None) -> int:
    """Сколько дней месяца остаётся после указанного момента (включая текущий
    день). Считаем по календарю, а делим потом всегда на 30 — так и
    договорились в формуле."""
    at = _aware(at) or _now()
    if at.month == 12:
        next_month = at.replace(year=at.year + 1, month=1, day=1)
    else:
        next_month = at.replace(month=at.month + 1, day=1)
    next_month = next_month.replace(hour=0, minute=0, second=0, microsecond=0)
    return max((next_month - at).days, 0)


def proration_for_growth(
    plan_before: Optional[str], masters_before: int,
    plan_after: str, masters_after: int,
    at: Optional[datetime] = None,
) -> Decimal:
    """Доплата за оставшиеся дни месяца при росте штата — ПО РАЗНИЦЕ цен.

    Пример из спеки: было 4 мастера (1000 ₽), стал 5-й в середине 30-дневного
    месяца → (1250 − 1000)/30 × 15 = 125 ₽; они лягут в следующий счёт, а не
    спишутся сейчас. При переходе на другой тариф берётся разница тарифов
    (Лайт 1250 → Бизнес 3500 = 2250), а не полная цена нового.
    """
    try:
        after = compute_amount(plan_after, masters_after)
    except TariffError:
        return Decimal("0")
    try:
        before = compute_amount(plan_before, masters_before) if plan_before else Decimal("0")
    except TariffError:
        before = Decimal("0")

    delta = after - before
    if delta <= 0:
        return Decimal("0")  # понижение доплатой не сопровождается

    per_day = delta / Decimal(PRORATION_DIVISOR)
    amount = per_day * Decimal(days_left_in_month(at))
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def covered_plan(salon) -> Optional[str]:
    """Уровень тарифа, который уже покрыт оплатой/начисленной доплатой."""
    return getattr(salon, "billed_plan", None) or salon.business_tier


def monthly_overage(salon, masters: int) -> Decimal:
    """На сколько месячно дороже действующий уровень, чем уже ОПЛАЧЕННЫЙ.

    Уровень — это пара «тариф + штат»: подорожать можно и наймом, и ручным
    повышением плана. Ноль, если действующий уровень не дороже оплаченного.
    """
    baseline_plan = covered_plan(salon)
    baseline_masters = salon.billed_masters or 0
    effective_plan = salon.business_tier
    if not effective_plan:
        return Decimal("0")
    try:
        after = compute_amount(effective_plan, masters)
    except TariffError:
        return Decimal("0")
    try:
        before = compute_amount(baseline_plan, baseline_masters) if baseline_plan else Decimal("0")
    except TariffError:
        before = Decimal("0")
    return max(after - before, Decimal("0"))


def accrue_proration(salon, at: Optional[datetime] = None) -> Decimal:
    """Докапать доплату за отрезок, прошедший на текущем уровне превышения.

    Начисляем ПО ДНЯМ фактического превышения, а не одной суммой за весь
    остаток месяца: нанял и в тот же день уволил — платить не за что,
    проработал неделю — оплачивается неделя. Делитель тот же, 30.
    """
    from app.models.models import SalonSubscriptionStatus

    now = _aware(at) or _now()
    since = _aware(getattr(salon, "proration_from", None))
    salon.proration_from = now

    if since is None or now <= since:
        return Decimal("0")
    # Копим только с того, кто уже платит (см. register_headcount)
    if salon.subscription_status not in (
        SalonSubscriptionStatus.ACTIVE, SalonSubscriptionStatus.PAST_DUE,
    ):
        return Decimal("0")

    level = getattr(salon, "prorated_masters", 0) or 0
    rate = monthly_overage(salon, level)
    if rate <= 0:
        return Decimal("0")

    days = Decimal(str((now - since).total_seconds() / 86400))
    amount = (rate / Decimal(PRORATION_DIVISOR) * days).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if amount > 0:
        salon.pending_proration = float(Decimal(str(salon.pending_proration or 0)) + amount)
    return amount


def register_headcount(salon, active_masters: int, at: Optional[datetime] = None) -> Decimal:
    """Учесть текущий штат салона.

    Сначала закрываем прошедший отрезок по прежнему уровню, затем фиксируем
    новый. Уменьшение штата больше не «застревает»: с этого момента доплата
    капает по новому (меньшему) уровню, а если штат вернулся к оплаченному —
    не капает вовсе.
    """
    accrued = accrue_proration(salon, at)

    salon.prorated_masters = active_masters
    if active_masters > (salon.billed_masters or 0):
        plan_after = resolve_plan_for_employee_count(active_masters)
        if plan_after in TARIFF_CATALOG:
            salon.business_tier = plan_after
    return accrued


def settle_proration(salon, at: Optional[datetime] = None) -> float:
    """Досчитать доплату до момента выставления счёта и вернуть её сумму.

    Вызывается перед формированием платежа: иначе последний отрезок (с
    последнего изменения штата до оплаты) остался бы неоплаченным.
    """
    accrue_proration(salon, at)
    return float(salon.pending_proration or 0)


# ── Смена тарифа ─────────────────────────────────────────────────────────────

_PLAN_ORDER = ["lite", "business", "corporate"]


def plan_rank(plan: Optional[str]) -> int:
    """Порядок тарифов по «весу» — чтобы отличать повышение от понижения."""
    return _PLAN_ORDER.index(plan) if plan in _PLAN_ORDER else -1


def is_downgrade(current: Optional[str], target: str) -> bool:
    return plan_rank(target) < plan_rank(current)


def downgrade_available_at(salon) -> Optional[datetime]:
    """Когда станет доступно следующее понижение (None — доступно сейчас)."""
    last = _aware(getattr(salon, "last_downgrade_at", None))
    if last is None:
        return None
    available = last + timedelta(days=DOWNGRADE_COOLDOWN_DAYS)
    return available if available > _now() else None


def ensure_can_change_plan(salon, target_plan: str) -> None:
    """Проверка правил смены тарифа. Повышение — без ограничений; понижение —
    не чаще раза в DOWNGRADE_COOLDOWN_DAYS."""
    if target_plan not in TARIFF_CATALOG:
        raise SubscriptionError("Такого тарифа нет")
    if not is_downgrade(salon.business_tier, target_plan):
        return
    available_at = downgrade_available_at(salon)
    if available_at is not None:
        raise SubscriptionError(
            "Понижать тариф можно раз в 3 месяца — следующее понижение будет "
            f"доступно с {available_at.strftime('%d.%m.%Y')}"
        )


def register_plan_change(salon, target_plan: str, active_masters: int,
                         at: Optional[datetime] = None) -> Decimal:
    """Ручная смена тарифа: доплата только за превышение уже покрытого уровня.

    Сначала закрываем прошедший отрезок по прежнему уровню (иначе дни на старом
    тарифе потерялись бы), затем переключаем план. Возврат на ранее оплаченный
    тариф бесплатен — планка billed_plan не опускается до оплаты.
    """
    from app.models.models import SalonSubscriptionStatus

    accrue_proration(salon, at)
    covered = covered_plan(salon)
    salon.business_tier = target_plan
    salon.prorated_masters = active_masters

    # billed_plan — это «что оплачено», он двигается только в момент оплаты.
    # От повторного начисления при перещёлкивании защищает само посуточное
    # начисление: платим за время на уровне, а не за факт перехода.
    del covered
    return Decimal("0")


def suggested_downgrade(salon, active_masters: int) -> Optional[str]:
    """Тариф, на который салону выгодно перейти по текущему штату (или None).

    Нужен для подсказки в кабинете: понижение у нас ручное, поэтому о том,
    что можно платить меньше, салон должен узнать от нас, а не переплачивать
    молча.
    """
    fair = resolve_plan_for_employee_count(active_masters)
    if fair not in TARIFF_CATALOG:
        return None
    return fair if is_downgrade(salon.business_tier, fair) else None


# ── Применение оплаты ────────────────────────────────────────────────────────

def apply_successful_payment(target, expires_at: datetime, active_masters: Optional[int] = None) -> None:
    """Единая реакция на успешную оплату: продлить доступ и закрыть доплату.

    Вызывается и из вебхука, и из планового автосписания — чтобы правила
    доступа не разъезжались между двумя путями. После оплаты запаса нет:
    access_until = ровно конец оплаченного периода.
    """
    target.subscription_expires_at = expires_at
    target.access_until = access_until_for_paid(expires_at)
    # Доплата за рост штата вошла в этот платёж — обнуляем и фиксируем планку.
    if hasattr(target, "pending_proration"):
        target.pending_proration = 0.0
    if active_masters is not None and hasattr(target, "billed_masters"):
        target.billed_masters = active_masters
    # Оплата покрыла текущий тариф — планка едет за ним (в т.ч. вниз)
    if hasattr(target, "billed_plan"):
        target.billed_plan = getattr(target, "business_tier", None)
    # Новый период — отсчёт доплаты с нуля от текущего уровня
    if hasattr(target, "proration_from"):
        target.proration_from = _now()
        if active_masters is not None:
            target.prorated_masters = active_masters


def start_trial(target, trial_days: int, at: Optional[datetime] = None,
                active_masters: Optional[int] = None) -> datetime:
    """Включить бесплатный период: срок, отметка «триал использован» и доступ
    с запасом. Возвращает момент окончания триала."""
    now = _aware(at) or _now()
    trial_ends_at = now + timedelta(days=trial_days)
    target.trial_ends_at = trial_ends_at
    target.subscription_expires_at = trial_ends_at
    target.access_until = access_until_for_trial(trial_ends_at)
    target.trial_used_at = now
    # Бесплатный период — с чистого листа: всё, что могло накопиться до выбора
    # тарифа, обнуляем, иначе оно всплыло бы в первом же счёте.
    if hasattr(target, "pending_proration"):
        target.pending_proration = 0.0
    if active_masters is not None and hasattr(target, "billed_masters"):
        # Планка = штат на старте: за этих людей доплату не берём.
        target.billed_masters = active_masters
    return trial_ends_at


def trial_available(target) -> bool:
    """Можно ли выдать бесплатный период (один раз на салон/модель)."""
    return getattr(target, "trial_used_at", None) is None


# ── Возврат платежа ──────────────────────────────────────────────────────────

def revoke_paid_period(target, months: int, share: float = 1.0,
                       at: Optional[datetime] = None) -> datetime:
    """Откатить доступ, который дал возвращённый платёж.

    Деньги вернули (через банк или поддержку) — значит оплаченный период надо
    забрать, иначе сервисом пользуются бесплатно. Вычитаем ровно тот срок,
    который этот платёж выдал: 30 × months, для частичного возврата — его долю.

    Если после отката срок уже в прошлом, доступ закрывается сразу: салон
    уходит из каталога и перестаёт принимать новую запись (созданные брони
    остаются, как и при обычном истечении).
    """
    now = _aware(at) or _now()
    share = min(max(float(share), 0.0), 1.0)
    days = 30 * max(1, int(months or 1)) * share

    current = _aware(getattr(target, "subscription_expires_at", None)) or now
    new_expires = current - timedelta(days=days)
    if new_expires < now:
        new_expires = now

    target.subscription_expires_at = new_expires
    target.access_until = new_expires
    return new_expires
