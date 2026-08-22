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


def register_headcount(salon, active_masters: int, at: Optional[datetime] = None) -> Decimal:
    """Учесть текущий штат салона: если он превысил «планку» оплаченного,
    начислить доплату за остаток месяца и поднять планку.

    Возвращает начисленную сумму (0, если планка не превышена). Во время
    бесплатного периода доплаты не копятся — триал бесплатный целиком.
    Планка не опускается при сокращении штата: возвратов нет, а повторное
    включение того же мастера не должно начислять второй раз.
    """
    from app.models.models import SalonSubscriptionStatus

    billed = salon.billed_masters or 0
    if active_masters <= billed:
        return Decimal("0")

    # Доплату берём ТОЛЬКО с того, кто уже платит: внутри оплаченного месяца
    # штат вырос — доплачивает разницу. На бесплатном периоде, до выбора тарифа
    # (NONE) и после отказа от подписки (CANCELED) денег не берём — новый салон,
    # заводящий своих мастеров, ничего не должен. Планку при этом двигаем, чтобы
    # первый реальный счёт был ровно тарифом за текущий штат.
    if salon.subscription_status not in (
        SalonSubscriptionStatus.ACTIVE, SalonSubscriptionStatus.PAST_DUE,
    ):
        salon.billed_masters = active_masters
        return Decimal("0")

    plan_before = salon.business_tier
    plan_after = resolve_plan_for_employee_count(active_masters)
    amount = proration_for_growth(plan_before, billed, plan_after, active_masters, at)

    salon.billed_masters = active_masters
    if amount > 0:
        salon.pending_proration = float(Decimal(str(salon.pending_proration or 0)) + amount)
    if plan_after in TARIFF_CATALOG:
        salon.business_tier = plan_after
    return amount


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
