"""Уведомление об успешной оплате подписки.

До этого система молчала про успех: писала только про неудачное списание и
про приближающийся конец срока. Человек платил — и не получал ничего, а при
автосписании узнавал о деньгах из банковской выписки.

Адресатов двое, и это осознанно: письмо с расшифровкой уходит на почту
организации (её читает тот, кто ведёт бухгалтерию), а короткое сообщение —
в личный канал владельца, где он реально живёт. Совпали адреса — шлём один
раз.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.core.worker import get_arq_pool
from app.services.email_templates import payment_success_email

logger = logging.getLogger(__name__)


def _rub(value) -> str:
    """1250 → «1 250 ₽», 137.5 → «137,50 ₽» — копейки показываем только когда
    они есть, иначе сумма выглядит как ценник в супермаркете."""
    d = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    whole, frac = divmod(int(d * 100), 100)
    text = f"{whole:,}".replace(",", " ")
    return f"{text},{frac:02d} ₽" if frac else f"{text} ₽"


def build_lines(*, plan_title: str, monthly, months: int, total) -> list:
    """Расшифровка суммы: тариф × срок, а сверх того — доплата за рост штата."""
    lines = []
    monthly_d = Decimal(str(monthly or 0)).quantize(Decimal("0.01"))
    total_d = Decimal(str(total or 0)).quantize(Decimal("0.01"))
    months = max(1, int(months or 1))
    base = (monthly_d * months).quantize(Decimal("0.01"))

    if monthly_d > 0 and base <= total_d:
        label = f"Тариф «{plan_title}»" + (f", {months} мес." if months > 1 else ", 1 мес.")
        lines.append((label, _rub(base)))
        extra = total_d - base
        if extra > 0:
            lines.append(("Доплата за увеличение числа мастеров", _rub(extra)))
    else:
        lines.append((f"Тариф «{plan_title}»", _rub(total_d)))
    return lines


async def notify_payment_success(
    db, target, kind: str, *, plan_title: str, monthly, months: int, total,
    access_until: Optional[datetime], receipt_to: Optional[str] = None,
    salon_email: Optional[str] = None,
) -> None:
    """Разослать уведомление об оплате. Ошибка доставки не должна ронять
    обработку платежа — деньги уже приняты, доступ уже продлён."""
    try:
        lines = build_lines(plan_title=plan_title, monthly=monthly,
                            months=months, total=total)
        until = f"{access_until:%d.%m.%Y}" if access_until else "—"
        title = f"Оплата прошла — {_rub(total)}"

        # 1. Короткое сообщение в личный канал владельца (TG/MAX/почта)
        short = " · ".join(f"{lbl} {val}" for lbl, val in lines)
        text = f"оплата прошла на {_rub(total)} ({short}). Доступ до {until}."
        if receipt_to:
            text += f" Кассовый чек отправлен на {receipt_to}."

        from app.services.notifications import (
            notify_model_subscription, notify_subscription,
        )
        if kind == "business":
            await notify_subscription(db, target, text)
        else:
            await notify_model_subscription(db, target, text)

        # 2. Письмо с расшифровкой на почту организации. Если владелец получает
        # уведомления на тот же адрес, сообщение выше уже туда ушло — второе
        # письмо об одном и том же событии только раздражает.
        if not salon_email:
            return
        owner_email = await _owner_notify_email(db, target, kind)
        if owner_email and owner_email.lower() == salon_email.lower():
            return

        plain, html = payment_success_email(
            title=title, lines=lines, total=_rub(total),
            access_until=until, receipt_to=receipt_to,
        )
        pool = await get_arq_pool()
        await pool.enqueue_job("send_email", salon_email,
                               "Оплата подписки — Руми", plain, html)
    except Exception:
        logger.exception("notify_payment_success: не отправлено (%s %s)",
                         kind, getattr(target, "id", "?"))


async def _owner_notify_email(db, target, kind: str) -> Optional[str]:
    """Почта, на которую владельцу и так уходят уведомления (если его канал —
    именно почта). Нужна только чтобы не задвоить одно и то же письмо."""
    from app.models.models import NotifyChannel, User
    from app.services.notify_channel import resolve

    user = target
    if kind == "business":
        user = await db.get(User, target.creator_id) if target.creator_id else None
    if user is None:
        return None
    channel, address = resolve(user)
    return str(address) if channel == NotifyChannel.EMAIL and address else None
