# app/api/v1/endpoints/payments.py
"""Оплата бизнес-подписок через CloudPayments.

Два «человеческих» эндпоинта инициируют оплату (/business/init на чек-ауте,
/business/manual-charge из кабинета) — оба ничего не списывают сами, а
готовят Payment(status=PENDING) и отдают фронту конфиг для виджета
CloudPayments Checkout; сам платёж всегда идёт с браузера клиента напрямую в
CloudPayments (мы никогда не видим номер карты). Источник истины по факту
оплаты — вебхуки CloudPayments (/cloudpayments/*), а не то, что вернул виджет
клиенту (виджет можно закрыть/подделать, сервер-сервер — нет).

Урлы вебхуков прописываются в личном кабинете CloudPayments → Настройки →
HTTP-уведомления (см. .env.example). CSRFOriginMiddleware их не трогает —
триггерится только на запросах с cookie access_token, которых у
сервер-сервер вызовов CloudPayments нет.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_salon_permission, get_current_user
from app.core.config import settings
from app.core.worker import get_arq_pool
from app.db.session import get_db
from app.models.models import (
    Payment, PaymentKind, PaymentStatus, Salon, SalonSubscriptionStatus, User,
)
from app.services.cloudpayments import verify_signature
from app.services.tariffs import TariffError, compute_amount

logger = logging.getLogger(__name__)
router = APIRouter()

TRIAL_DAYS = 14
VERIFICATION_AMOUNT = Decimal("1.00")

CP_OK = {"code": 0}
CP_DECLINE = {"code": 5}


def _require_enabled() -> None:
    if not settings.CLOUDPAYMENTS_ENABLED:
        raise HTTPException(status_code=503, detail="Оплата тарифов пока не подключена")


class InitPaymentRequest(BaseModel):
    salon_id: int
    plan: str
    auto_renew: bool
    employee_count: Optional[int] = None


class ManualChargeRequest(BaseModel):
    salon_id: int
    employee_count: Optional[int] = None


class CancelAutoRenewRequest(BaseModel):
    salon_id: int


def _widget_payload(payment: Payment, salon: Salon, user: User, description: str) -> dict:
    return {
        "requires_payment": True,
        "public_id": settings.CLOUDPAYMENTS_PUBLIC_ID,
        "amount": payment.amount,
        "currency": payment.currency,
        "invoice_id": payment.invoice_id,
        "account_id": str(salon.id),
        "description": description,
        "email": salon.email or user.email or "",
    }


@router.post("/business/init")
async def init_business_payment(
    body: InitPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выбор тарифа сразу после /api/v1/business/apply.

    auto_renew=False — просто включает 14-дневный триал, в CloudPayments не
    ходим вообще (списывать нечего и незачем, пока владелец сам не оплатит
    вручную в кабинете — см. /business/manual-charge).

    auto_renew=True — заводит верификационный платёж на 1₽: из него
    (см. app.tasks.finalize_cloudpayments_verification) получаем токен карты
    и оформляем подписку CloudPayments со стартом первого СПИСАНИЯ по
    окончании триала — деньги в течение 14 дней не трогаем.
    """
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")

    try:
        amount = compute_amount(body.plan, body.employee_count)
    except TariffError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    now = datetime.now(timezone.utc)
    trial_ends_at = now + timedelta(days=TRIAL_DAYS)
    salon.business_tier = body.plan
    salon.auto_renew = body.auto_renew
    salon.subscription_status = SalonSubscriptionStatus.TRIALING
    salon.trial_ends_at = trial_ends_at
    salon.subscription_expires_at = trial_ends_at

    if not body.auto_renew:
        await db.commit()
        return {"requires_payment": False, "redirect": "/business/dashboard?trial=1"}

    _require_enabled()
    payment = Payment(
        salon_id=salon.id, plan=body.plan, kind=PaymentKind.VERIFICATION,
        amount=float(VERIFICATION_AMOUNT), target_amount=float(amount),
        invoice_id=uuid.uuid4().hex,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return _widget_payload(
        payment, salon, current_user,
        f"Верификация карты — тариф «{body.plan}» (Руми)",
    )


@router.post("/business/manual-charge")
async def manual_business_charge(
    body: ManualChargeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Разовая ручная оплата тарифа (кнопка «Оплатить» в кабинете) — и для
    владельцев без автопродления каждый месяц, и как «оплатить досрочно» для
    остальных. Подписку CloudPayments не создаёт — просто продлевает
    subscription_expires_at на 30 дней после успешной оплаты (вебхук pay)."""
    _require_enabled()
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")
    if not salon.business_tier:
        raise HTTPException(status_code=400, detail="Сначала выберите тариф")

    try:
        amount = compute_amount(salon.business_tier, body.employee_count)
    except TariffError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    payment = Payment(
        salon_id=salon.id, plan=salon.business_tier, kind=PaymentKind.MANUAL,
        amount=float(amount), invoice_id=uuid.uuid4().hex,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return _widget_payload(
        payment, salon, current_user,
        f"Оплата тарифа «{salon.business_tier}» — Руми",
    )


@router.post("/business/cancel-auto-renew")
async def cancel_auto_renew(
    body: CancelAutoRenewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отключает автопродление (кнопка «Отменить автопродление» в кабинете).
    Доступ по уже оплаченному периоду не трогаем — сгорает сам по
    subscription_expires_at, как у обычных подписок."""
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")

    if salon.cp_subscription_id:
        _require_enabled()
        from app.services.cloudpayments import CloudPaymentsClient, CloudPaymentsError
        try:
            client = CloudPaymentsClient()
            await client.cancel_subscription(salon.cp_subscription_id)
        except CloudPaymentsError as exc:
            raise HTTPException(
                status_code=502, detail=f"Не удалось отменить подписку в CloudPayments: {exc}"
            )

    salon.auto_renew = False
    salon.cp_subscription_id = None
    await db.commit()
    return {"ok": True}


# ── Вебхуки CloudPayments ──────────────────────────────────────────────────


async def _verified_form(request: Request) -> dict:
    """Сырое тело + проверка Content-HMAC. 401, если подпись не сошлась —
    в т.ч. если оплата вообще выключена (нечем проверять)."""
    raw_body = await request.body()
    signature = request.headers.get("Content-HMAC")
    if not settings.CLOUDPAYMENTS_ENABLED or not verify_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Неверная подпись")
    form = await request.form()
    return dict(form)


async def _resolve_payment_and_salon(
    db: AsyncSession, form: dict, default_kind: PaymentKind,
) -> tuple[Optional[Payment], Optional[Salon]]:
    """По InvoiceId — платёж, заведённый нами (init/manual-charge). Без
    InvoiceId — это плановое автосписание, инициированное самим CloudPayments
    по подписке: салон ищем по AccountId (= наш salon_id, см.
    init_business_payment → finalize_cloudpayments_verification →
    create_subscription), платёж заводим на лету."""
    invoice_id = form.get("InvoiceId")
    if invoice_id:
        payment = (
            await db.execute(select(Payment).where(Payment.invoice_id == invoice_id))
        ).scalar_one_or_none()
        salon = await db.get(Salon, payment.salon_id) if payment else None
        return payment, salon

    account_id = form.get("AccountId")
    if not account_id or not account_id.isdigit():
        return None, None
    salon = await db.get(Salon, int(account_id))
    if salon is None:
        return None, None
    payment = Payment(
        salon_id=salon.id, plan=salon.business_tier or "", kind=default_kind,
        amount=float(form.get("Amount") or 0),
    )
    db.add(payment)
    return payment, salon


@router.post("/cloudpayments/check")
async def cloudpayments_check(request: Request, db: AsyncSession = Depends(get_db)):
    """Перед КАЖДЫМ списанием (в т.ч. плановым автосписанием по подписке) —
    последний шанс отказать. Отклоняем только на явную нестыковку (счёт не
    найден/уже не PENDING, салон не найден, автопродление выключено/подписка
    отменена) — по умолчанию пропускаем: наша сторона не должна быть узким
    местом надёжности приёма платежей."""
    form = await _verified_form(request)
    invoice_id = form.get("InvoiceId")
    if invoice_id:
        payment = (
            await db.execute(select(Payment).where(Payment.invoice_id == invoice_id))
        ).scalar_one_or_none()
        if payment is None or payment.status != PaymentStatus.PENDING:
            return CP_DECLINE
        return CP_OK

    account_id = form.get("AccountId")
    if account_id and account_id.isdigit():
        salon = await db.get(Salon, int(account_id))
        if salon is None or not salon.auto_renew or salon.subscription_status == SalonSubscriptionStatus.CANCELED:
            return CP_DECLINE
    return CP_OK


@router.post("/cloudpayments/pay")
async def cloudpayments_pay(request: Request, db: AsyncSession = Depends(get_db)):
    form = await _verified_form(request)
    transaction_id = form.get("TransactionId")
    payment, salon = await _resolve_payment_and_salon(db, form, PaymentKind.SUBSCRIPTION_INITIAL)
    if payment is None or salon is None:
        logger.error("cloudpayments/pay: не удалось сопоставить платёж: %r", form)
        return CP_OK  # подтверждаем получение — без InvoiceId/AccountId ретраи не помогут

    if payment.status == PaymentStatus.SUCCEEDED and payment.cp_transaction_id == transaction_id:
        return CP_OK  # повторная доставка одного и того же уведомления — идемпотентно

    payment.cp_transaction_id = transaction_id
    payment.status = PaymentStatus.SUCCEEDED
    payment.paid_at = datetime.now(timezone.utc)
    payment.raw_payload = form

    card_last4 = form.get("CardLastFour")
    if card_last4:
        salon.card_last4 = card_last4

    if payment.kind == PaymentKind.VERIFICATION:
        token = form.get("Token")
        if not token:
            logger.error(
                "cloudpayments/pay: верификация без Token (InvoiceId=%s) — включите приём "
                "токенов в личном кабинете CloudPayments → Рекуррентные платежи",
                payment.invoice_id,
            )
            await db.commit()
            return CP_OK
        await db.commit()
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "finalize_cloudpayments_verification",
            payment.id, salon.id, payment.plan, payment.target_amount,
            token, salon.trial_ends_at.isoformat(), transaction_id,
            _job_id=f"cp-verify:{transaction_id}",
        )
        return CP_OK

    now = datetime.now(timezone.utc)
    base = (
        salon.subscription_expires_at
        if salon.subscription_expires_at and salon.subscription_expires_at > now
        else now
    )
    salon.subscription_expires_at = base + timedelta(days=30)
    salon.subscription_status = SalonSubscriptionStatus.ACTIVE

    await db.commit()
    return CP_OK


@router.post("/cloudpayments/recurrent")
async def cloudpayments_recurrent(request: Request, db: AsyncSession = Depends(get_db)):
    """Плановое автосписание по подписке — та же логика успеха, что и /pay
    (CloudPayments шлёт Recurrent для повторных платежей подписки, Pay — для
    первого; полагаться на то, какой именно вызвали, ненадёжно)."""
    return await cloudpayments_pay(request, db)


@router.post("/cloudpayments/fail")
async def cloudpayments_fail(request: Request, db: AsyncSession = Depends(get_db)):
    form = await _verified_form(request)
    payment, salon = await _resolve_payment_and_salon(db, form, PaymentKind.RECURRENT)
    if payment is None or salon is None:
        return CP_OK

    payment.status = PaymentStatus.FAILED
    payment.cp_transaction_id = form.get("TransactionId")
    payment.raw_payload = form

    if payment.kind == PaymentKind.VERIFICATION:
        # Не удалось привязать карту — откатываем «автопродление включено»,
        # чтобы кабинет не обещал того, чего нет; сам триал не трогаем.
        salon.auto_renew = False
    else:
        # Плановое автосписание не прошло — грейс: доступ жив до expires_at,
        # CloudPayments сам повторит попытку по расписанию подписки.
        salon.subscription_status = SalonSubscriptionStatus.PAST_DUE
        try:
            from app.services.notifications import notify_admins
            await notify_admins(
                db, "Не удалось списать оплату подписки",
                f"Салон «{salon.name}» (id={salon.id}), тариф «{salon.business_tier}»: "
                f"{form.get('Reason') or form.get('ReasonCode') or 'причина не указана'}",
            )
        except Exception:
            logger.exception("cloudpayments/fail: не удалось отправить алерт")

    await db.commit()
    return CP_OK


@router.post("/cloudpayments/cancel")
async def cloudpayments_cancel(request: Request, db: AsyncSession = Depends(get_db)):
    """CloudPayments сам отменил подписку (обычно — после серии неудачных
    автосписаний). Ищем салон по AccountId — тут это всегда id салона."""
    form = await _verified_form(request)
    account_id = form.get("AccountId")
    salon = await db.get(Salon, int(account_id)) if account_id and account_id.isdigit() else None
    if salon is None:
        return CP_OK
    salon.subscription_status = SalonSubscriptionStatus.CANCELED
    salon.auto_renew = False
    await db.commit()
    return CP_OK


@router.post("/cloudpayments/refund")
async def cloudpayments_refund(request: Request, db: AsyncSession = Depends(get_db)):
    """Информационное уведомление о возврате (в т.ч. наш собственный возврат
    верификационного 1₽ — см. app.tasks.finalize_cloudpayments_verification).
    Подписку не трогаем — просто фиксируем факт в истории платежей."""
    form = await _verified_form(request)
    transaction_id = form.get("TransactionId")
    payment = (
        await db.execute(select(Payment).where(Payment.cp_transaction_id == transaction_id))
    ).scalar_one_or_none()
    if payment is not None:
        payment.status = PaymentStatus.REFUNDED
        await db.commit()
    return CP_OK
