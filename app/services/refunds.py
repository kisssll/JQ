"""Применение возврата платежа к подписке.

Возврат приходит двумя путями — уведомлением от кассы (основной,
app/api/v1/endpoints/payments.py) и ночной сверкой на случай, если
уведомление не дошло (app.tasks.reconcile_refunds). Правило одно, поэтому
и код один: разъехавшиеся ветки в деньгах — это баг, который замечают
поздно и по жалобе.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from app.models.models import (
    PaymentKind, PaymentStatus, SalonSubscriptionStatus,
)
from app.services.subscription import has_access, revoke_paid_period

logger = logging.getLogger(__name__)

# Статусы Т-Кассы, означающие, что деньги ушли обратно плательщику:
# REFUNDED — возврат после расчёта, REVERSED — отмена до него,
# PARTIAL_REFUNDED — частичный возврат.
REFUND_STATUSES = {"REFUNDED", "REVERSED", "PARTIAL_REFUNDED"}


def refunded_share(payment, refunded_amount: Optional[float]) -> float:
    """Какую долю платежа вернули. Ненадёжные данные считаем полным возвратом
    только для статусов полного возврата — вызывающий решает сам."""
    if refunded_amount is None:
        return 1.0
    try:
        refunded = Decimal(str(refunded_amount))
        paid = Decimal(str(payment.amount or 0))
        if 0 < refunded < paid:
            return float(refunded / paid)
    except Exception:
        logger.warning("возврат: не разобрали сумму по платежу id=%s", payment.id)
    return 1.0


async def apply_refund(db, payment, target, kind: str, share: float = 1.0,
                       raw: Optional[dict] = None) -> Optional[str]:
    """Пометить платёж возвращённым и забрать выданный им доступ.

    Возвращает текст для лога или None, если применять было нечего.
    Коммит остаётся на вызывающем — он знает, что ещё пишет в той же
    транзакции.
    """
    if payment.status == PaymentStatus.REFUNDED:
        return None  # уже применён (повторное уведомление или сверка после него)

    payment.status = PaymentStatus.REFUNDED
    if raw is not None:
        payment.raw_payload = raw

    # Верификационный рубль доступа не выдавал (и возвращаем мы его сами при
    # привязке карты) — откатывать нечего.
    if payment.kind == PaymentKind.VERIFICATION:
        return "верификационный платёж — доступ не менялся"

    until = revoke_paid_period(target, payment.months or 1, share)
    if not has_access(target):
        target.subscription_status = SalonSubscriptionStatus.CANCELED
    if share >= 1.0:
        # Деньги вернули полностью — списывать снова в следующем месяце нельзя
        target.auto_renew = False
        target.recurring_token = None

    returned = int(round(float(payment.amount or 0) * share))
    text = f"возврат платежа на {returned} ₽ — доступ по тарифу теперь до {until:%d.%m.%Y}."
    try:
        from app.services.notifications import (
            notify_model_subscription, notify_subscription,
        )
        if kind == "business":
            await notify_subscription(db, target, text)
        else:
            await notify_model_subscription(db, target, text)
    except Exception:
        logger.exception("возврат: уведомление не отправлено (платёж id=%s)", payment.id)

    return text
