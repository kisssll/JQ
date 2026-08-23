# app/api/v1/endpoints/payments.py
"""Оплата бизнес-подписок через Т-Кассу (Т-Бизнес/Тинькофф).

Два «человеческих» эндпоинта готовят платёж (/business/init на чек-ауте,
/business/manual-charge из кабинета) и возвращают payment_url — на неё
достаточно перенаправить браузер, никакого JS-виджета не нужно. Сам платёж
всегда идёт на стороне Т-Кассы (номер карты сервер не видит). Источник
истины по факту оплаты — вебхук /tkassa/notify, а не то, куда вернулся
браузер (SuccessURL можно открыть и не оплатив — это просто UX-адрес).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_salon_permission, get_current_user
from app.core.config import settings
from app.core.worker import get_arq_pool
from app.db.session import get_db
from app.models.models import (
    Master, Payment, PaymentKind, PaymentStatus, Salon, SalonSubscriptionStatus,
    SubscriptionTier, User,
)
from app.services.tkassa import TKassaClient, TKassaError, verify_notification
from app.services.tariffs import (
    MODEL_TARIFF_CATALOG, TariffError, compute_amount, resolve_plan_for_employee_count,
)

logger = logging.getLogger(__name__)
router = APIRouter()

TRIAL_DAYS = 14
VERIFICATION_AMOUNT = Decimal("1.00")
# Потолок предоплаты — чисто инженерная страховка от абсурдных сроков
# (10 лет), продуктового ограничения тут нет.
MAX_PREPAY_MONTHS = 120

_SUCCESS_STATUSES = {"CONFIRMED"}
_FAILURE_STATUSES = {"REJECTED", "DEADLINE_EXPIRED", "CANCELED", "AUTH_FAIL"}


def _require_enabled() -> None:
    if not settings.TKASSA_ENABLED:
        raise HTTPException(status_code=503, detail="Оплата тарифов пока не подключена")


def _notify_urls(kind: str) -> tuple[str, str, str]:
    """kind: 'business' (владелец салона) | 'model' — разные адреса
    возврата после оплаты, вебхук на оба общий (/tkassa/notify)."""
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if kind == "business":
        return_url = f"{base}/business/dashboard?tab=billing&payment="
    else:
        return_url = f"{base}/model/join?payment="
    return (
        f"{base}/api/v1/payments/tkassa/notify",
        f"{return_url}success",
        f"{return_url}fail",
    )


class InitPaymentRequest(BaseModel):
    salon_id: int
    plan: str
    auto_renew: bool
    employee_count: Optional[int] = None


class ManualChargeRequest(BaseModel):
    salon_id: int
    # За сколько месяцев платим вперёд. 1 — обычная помесячная оплата;
    # больше — предоплата (доступ продлевается на весь оплаченный срок).
    months: int = 1


class CancelAutoRenewRequest(BaseModel):
    salon_id: int


@router.post("/business/init")
async def init_business_payment(
    body: InitPaymentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выбор тарифа сразу после /api/v1/business/apply.

    auto_renew=False — включает 14-дневный триал, в Т-Кассу не ходим вообще
    (списывать нечего, пока владелец сам не оплатит вручную в кабинете —
    см. /business/manual-charge).

    auto_renew=True — заводит верификационный платёж на 1₽ с Recurrent=Y:
    после успешной оплаты Т-Касса привязывает карту и присылает RebillId
    (см. app.tasks.finalize_tkassa_verification) — этот рубль сразу
    возвращается клиенту, а RebillId остаётся для будущих автосписаний
    (см. app.tasks.charge_due_subscriptions). Деньги в течение 14 дней
    не трогаем — само автосписание начнётся только после trial_ends_at.
    """
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")

    try:
        amount = compute_amount(body.plan, body.employee_count)
    except TariffError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from app.services.subscription import has_access, start_trial, trial_available

    # Живую подписку не трогаем: раньше повторный init затирал оплаченный
    # период датой триала — то есть портил уже купленный доступ.
    if has_access(salon):
        raise HTTPException(
            status_code=409,
            detail="Тариф уже подключён — сменить его можно во вкладке «Тариф»",
        )
    # Бесплатный период даётся один раз на салон; повторно — только руками
    # админа (см. админ-панель).
    if not trial_available(salon):
        raise HTTPException(
            status_code=409,
            detail="Бесплатный период уже использован — оплатите тариф в кабинете",
        )

    active_masters = (await db.execute(
        select(func.count(Master.id)).where(
            Master.salon_id == salon.id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0

    now = datetime.now(timezone.utc)
    salon.business_tier = body.plan
    salon.auto_renew = body.auto_renew
    salon.subscription_status = SalonSubscriptionStatus.TRIALING
    trial_ends_at = start_trial(salon, TRIAL_DAYS, now, active_masters=active_masters)

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
    await db.flush()

    notification_url, success_url, fail_url = _notify_urls("business")
    try:
        client = TKassaClient()
        result = await client.init(
            order_id=payment.invoice_id, amount_rub=VERIFICATION_AMOUNT,
            description=f"Верификация карты — тариф «{body.plan}» (Руми)",
            notification_url=notification_url, success_url=success_url, fail_url=fail_url,
            recurrent=True, customer_key=str(salon.id),
            client_ip=request.client.host if request.client else None,
        )
    except TKassaError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Не удалось создать платёж в Т-Кассе: {exc}")

    payment.provider_transaction_id = result.payment_id
    await db.commit()
    return {"requires_payment": True, "payment_url": result.payment_url}


@router.post("/business/manual-charge")
async def manual_business_charge(
    body: ManualChargeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Разовая ручная оплата тарифа (кнопка «Оплатить» в кабинете) — и для
    владельцев без автопродления каждый месяц, и как «оплатить досрочно» для
    остальных. RebillId не запрашиваем — обычный одноразовый платёж.

    Тариф на каждую оплату пересчитывается заново по фактическому числу
    активных мастеров (см. resolve_plan_for_employee_count) — салон стартует
    с выбранного вручную тарифа, а дальше сам «дорастает»/«сжимается» вместе
    со штатом, без ручного переключения."""
    _require_enabled()
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")
    if not salon.business_tier:
        raise HTTPException(status_code=400, detail="Сначала выберите тариф")

    active_masters = (await db.execute(
        select(func.count(Master.id)).where(Master.salon_id == salon.id, Master.is_active == True)  # noqa: E712
    )).scalar() or 0
    plan = resolve_plan_for_employee_count(active_masters)

    try:
        amount = compute_amount(plan, active_masters)
    except TariffError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    months = max(1, int(body.months or 1))
    if months > MAX_PREPAY_MONTHS:
        raise HTTPException(
            status_code=400,
            detail=f"Оплатить можно максимум на {MAX_PREPAY_MONTHS} месяцев вперёд",
        )

    salon.business_tier = plan
    # Тариф × срок предоплаты + доплата, накопленная за рост штата внутри уже
    # оплаченного месяца (register_headcount): в момент найма денег не берём,
    # они падают в следующий платёж.
    amount = (amount * months + Decimal(str(salon.pending_proration or 0))).quantize(Decimal("0.01"))
    payment = Payment(
        salon_id=salon.id, plan=plan, kind=PaymentKind.MANUAL,
        amount=float(amount), months=months, invoice_id=uuid.uuid4().hex,
    )
    db.add(payment)
    await db.flush()

    notification_url, success_url, fail_url = _notify_urls("business")
    try:
        client = TKassaClient()
        result = await client.init(
            order_id=payment.invoice_id, amount_rub=amount,
            description=f"Оплата тарифа «{salon.business_tier}» — Руми",
            notification_url=notification_url, success_url=success_url, fail_url=fail_url,
            client_ip=request.client.host if request.client else None,
        )
    except TKassaError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Не удалось создать платёж в Т-Кассе: {exc}")

    payment.provider_transaction_id = result.payment_id
    await db.commit()
    return {"payment_url": result.payment_url}


@router.post("/business/cancel-auto-renew")
async def cancel_auto_renew(
    body: CancelAutoRenewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отключает автопродление. У Т-Кассы нет объекта «подписка» на её
    стороне — отменять там нечего, просто перестаём сами вызывать Charge
    (см. app.tasks.charge_due_subscriptions). Доступ по уже оплаченному
    периоду не трогаем — сгорает сам по subscription_expires_at."""
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")
    salon.auto_renew = False
    salon.recurring_token = None
    await db.commit()
    return {"ok": True}



class ChangePlanRequest(BaseModel):
    salon_id: int
    plan: str


@router.post("/business/change-plan")
async def change_business_plan(
    body: ChangePlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смена тарифа владельцем в любой момент.

    Раньше выбор тарифа был доступен только при подключении (статус NONE), а
    дальше план молча пересчитывался по числу мастеров при каждой оплате.
    Теперь владелец меняет тариф сам: повышение — без ограничений, понижение —
    не чаще раза в 3 месяца (защита от игры «нанял-уволил»).

    Деньги сейчас не списываем: новый тариф вступает в силу со следующего
    счёта, а разница за остаток текущего месяца копится в pending_proration.
    """
    from app.services.subscription import (
        SubscriptionError, ensure_can_change_plan, is_downgrade, proration_for_growth,
    )

    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")

    try:
        ensure_can_change_plan(salon, body.plan)
    except SubscriptionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    active_masters = (await db.execute(
        select(func.count(Master.id)).where(
            Master.salon_id == salon.id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0

    previous = salon.business_tier
    if is_downgrade(previous, body.plan):
        salon.last_downgrade_at = datetime.now(timezone.utc)
    else:
        # Повышение: доплачиваем разницу за оставшиеся дни месяца.
        extra = proration_for_growth(previous, active_masters, body.plan, active_masters)
        if extra > 0:
            salon.pending_proration = float(
                Decimal(str(salon.pending_proration or 0)) + extra
            )
    salon.business_tier = body.plan
    await db.commit()
    return {
        "ok": True, "plan": salon.business_tier,
        "pending_proration": float(salon.pending_proration or 0),
    }


@router.post("/business/enable-auto-renew")
async def enable_auto_renew(
    body: CancelAutoRenewRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Включить автопродление обратно (и/или перепривязать карту).

    Раньше путь был односторонним: отменить автопродление можно, а вернуть —
    нет. Заводим верификационный платёж на 1₽ с Recurrent=Y, как при первом
    подключении: он вернётся, а RebillId останется для будущих списаний.
    """
    _require_enabled()
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")
    if not salon.business_tier:
        raise HTTPException(status_code=400, detail="Сначала выберите тариф")

    active_masters = (await db.execute(
        select(func.count(Master.id)).where(
            Master.salon_id == salon.id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0
    try:
        amount = compute_amount(salon.business_tier, active_masters)
    except TariffError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    payment = Payment(
        salon_id=salon.id, plan=salon.business_tier, kind=PaymentKind.VERIFICATION,
        amount=float(VERIFICATION_AMOUNT), target_amount=float(amount),
        invoice_id=uuid.uuid4().hex,
    )
    db.add(payment)
    await db.flush()

    notification_url, success_url, fail_url = _notify_urls("business")
    try:
        client = TKassaClient()
        result = await client.init(
            order_id=payment.invoice_id, amount_rub=VERIFICATION_AMOUNT,
            description=f"Привязка карты — тариф «{salon.business_tier}» (Руми)",
            notification_url=notification_url, success_url=success_url, fail_url=fail_url,
            recurrent=True, customer_key=str(salon.id),
            client_ip=request.client.host if request.client else None,
        )
    except TKassaError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Не удалось создать платёж в Т-Кассе: {exc}")

    payment.provider_transaction_id = result.payment_id
    salon.auto_renew = True
    await db.commit()
    return {"requires_payment": True, "payment_url": result.payment_url}


@router.post("/business/cancel-subscription")
async def cancel_subscription(
    body: CancelAutoRenewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полный отказ от подписки (в отличие от отмены автопродления).

    Доступ не отбираем задним числом: оплаченный период салон дорабатывает,
    после чего выпадает из ленты по access_until.
    """
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")
    salon.auto_renew = False
    salon.recurring_token = None
    salon.subscription_status = SalonSubscriptionStatus.CANCELED
    await db.commit()
    return {"ok": True, "access_until": salon.access_until.isoformat() if salon.access_until else None}


class CustomTariffRequest(BaseModel):
    salon_id: int
    comment: str = ""


@router.post("/business/custom-request")
async def request_custom_tariff(
    body: CustomTariffRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Заявка на индивидуальный тариф (>20 мастеров): самостоятельной оплаты
    для него нет, дальше решает продавец — шлём заявку админам."""
    await check_salon_permission(db, current_user, body.salon_id, "manage_tariff")
    salon = await db.get(Salon, body.salon_id)
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")

    active_masters = (await db.execute(
        select(func.count(Master.id)).where(
            Master.salon_id == salon.id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0
    try:
        from app.services.notifications import notify_admins
        await notify_admins(
            db, "Заявка на индивидуальный тариф",
            f"Салон «{salon.name}» (id={salon.id}), активных мастеров: {active_masters}, "
            f"телефон {salon.phone}. Комментарий: {body.comment.strip() or '—'}",
        )
    except Exception:
        logger.exception("request_custom_tariff(%s): заявка не отправлена", salon.id)
    return {"ok": True}


# ── Тарифы «модели» (/model#plans) ──────────────────────────────────────────
# Та же схема, что у бизнеса выше (см. init_business_payment) — но плательщик
# всегда current_user, отдельный salon_id не нужен.


class InitModelPaymentRequest(BaseModel):
    plan: str
    auto_renew: bool


@router.post("/model/init")
async def init_model_payment(
    body: InitModelPaymentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выбор тарифа при оформлении анкеты модели (/model/join) — зеркально
    init_business_payment, см. его докстринг."""
    try:
        amount = compute_amount(body.plan, catalog=MODEL_TARIFF_CATALOG)
    except TariffError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from app.services.subscription import (
        has_access as _has_access, start_trial as _start_trial,
        trial_available as _trial_available,
    )

    # Те же правила, что у салонов: живую подписку не затираем, бесплатный
    # период — один раз на пользователя.
    if _has_access(current_user):
        raise HTTPException(
            status_code=409, detail="Тариф уже подключён — сменить его можно в кабинете",
        )
    if not _trial_available(current_user):
        raise HTTPException(
            status_code=409,
            detail="Бесплатный период уже использован — оплатите тариф в кабинете",
        )

    now = datetime.now(timezone.utc)
    current_user.subscription_tier = SubscriptionTier(body.plan)
    current_user.auto_renew = body.auto_renew
    current_user.subscription_status = SalonSubscriptionStatus.TRIALING
    trial_ends_at = _start_trial(current_user, TRIAL_DAYS, now)

    if not body.auto_renew:
        await db.commit()
        return {"requires_payment": False, "redirect": "/model/dashboard?trial=1"}

    _require_enabled()
    payment = Payment(
        user_id=current_user.id, plan=body.plan, kind=PaymentKind.VERIFICATION,
        amount=float(VERIFICATION_AMOUNT), target_amount=float(amount),
        invoice_id=uuid.uuid4().hex,
    )
    db.add(payment)
    await db.flush()

    notification_url, success_url, fail_url = _notify_urls("model")
    try:
        client = TKassaClient()
        result = await client.init(
            order_id=payment.invoice_id, amount_rub=VERIFICATION_AMOUNT,
            description=f"Верификация карты — тариф «{body.plan}» (Руми)",
            notification_url=notification_url, success_url=success_url, fail_url=fail_url,
            recurrent=True, customer_key=f"user:{current_user.id}",
            client_ip=request.client.host if request.client else None,
        )
    except TKassaError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Не удалось создать платёж в Т-Кассе: {exc}")

    payment.provider_transaction_id = result.payment_id
    await db.commit()
    return {"requires_payment": True, "payment_url": result.payment_url}


@router.post("/model/manual-charge")
async def manual_model_charge(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    if not current_user.subscription_tier:
        raise HTTPException(status_code=400, detail="Сначала выберите тариф")
    plan = current_user.subscription_tier.value

    try:
        amount = compute_amount(plan, catalog=MODEL_TARIFF_CATALOG)
    except TariffError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    payment = Payment(
        user_id=current_user.id, plan=plan, kind=PaymentKind.MANUAL,
        amount=float(amount), invoice_id=uuid.uuid4().hex,
    )
    db.add(payment)
    await db.flush()

    notification_url, success_url, fail_url = _notify_urls("model")
    try:
        client = TKassaClient()
        result = await client.init(
            order_id=payment.invoice_id, amount_rub=amount,
            description=f"Оплата тарифа «{plan}» — Руми",
            notification_url=notification_url, success_url=success_url, fail_url=fail_url,
            client_ip=request.client.host if request.client else None,
        )
    except TKassaError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Не удалось создать платёж в Т-Кассе: {exc}")

    payment.provider_transaction_id = result.payment_id
    await db.commit()
    return {"payment_url": result.payment_url}


@router.post("/model/cancel-auto-renew")
async def cancel_model_auto_renew(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.auto_renew = False
    current_user.recurring_token = None
    await db.commit()
    return {"ok": True}


# ── Вебхук Т-Кассы ──────────────────────────────────────────────────────────


async def _target_for_payment(db: AsyncSession, payment: Payment):
    """Salon или User, на кого заведён платёж, + метка для текстов/редиректов.
    Оба типа несут одинаковый набор полей подписки (subscription_status,
    auto_renew, trial_ends_at, subscription_expires_at, recurring_token,
    subscription_amount, card_last4) — код ниже работает с любым из них."""
    if payment.salon_id:
        return await db.get(Salon, payment.salon_id), "business"
    return await db.get(User, payment.user_id), "model"


def _target_label(target, kind: str) -> str:
    if kind == "business":
        return f"Салон «{target.name}» (id={target.id}), тариф «{target.business_tier}»"
    plan = target.subscription_tier.value if target.subscription_tier else "?"
    return f"Модель {target.full_name or target.id} (id={target.id}), тариф «{plan}»"


@router.post("/tkassa/notify")
async def tkassa_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """Единственный урл уведомлений (в личном кабинете Т-Кассы указывается
    один адрес — в отличие от CloudPayments-подобных касс с урлом на каждый
    тип события, здесь тип события — это поле Status внутри одного и того же
    JSON). Обслуживает и оплату салонов, и оплату «модели» — платёж несёт
    ровно один из salon_id/user_id (см. Payment.__table_args__), остальное
    определяется по нему. Ответ — ровно текст "OK", иначе Т-Касса повторит
    доставку до 100 раз."""
    payload = await request.json()

    if not settings.TKASSA_ENABLED or payload.get("TerminalKey") != settings.TKASSA_TERMINAL_KEY:
        return PlainTextResponse("", status_code=401)
    if not verify_notification(payload):
        logger.error("tkassa/notify: неверная подпись Token: %r", payload)
        return PlainTextResponse("", status_code=401)

    order_id = payload.get("OrderId")
    payment_id = str(payload.get("PaymentId") or "")
    status = payload.get("Status") or ""
    success = bool(payload.get("Success"))

    payment = (
        await db.execute(select(Payment).where(Payment.invoice_id == order_id))
    ).scalar_one_or_none()
    if payment is None:
        logger.error("tkassa/notify: платёж с OrderId=%r не найден", order_id)
        return PlainTextResponse("OK")  # подтверждаем получение — ретраи не помогут

    if payment.status == PaymentStatus.SUCCEEDED and payment.provider_transaction_id == payment_id:
        return PlainTextResponse("OK")  # повторная доставка — идемпотентно

    target, kind = await _target_for_payment(db, payment)
    if target is None:
        return PlainTextResponse("OK")

    if success and status in _SUCCESS_STATUSES:
        payment.provider_transaction_id = payment_id
        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = datetime.now(timezone.utc)
        payment.raw_payload = payload

        pan = payload.get("Pan") or ""
        if pan:
            target.card_last4 = pan[-4:]

        if payment.kind == PaymentKind.VERIFICATION:
            rebill_id = payload.get("RebillId")
            if not rebill_id:
                logger.error(
                    "tkassa/notify: верификация без RebillId (OrderId=%s) — "
                    "проверьте, что метод Charge включён поддержкой Т-Кассы", order_id,
                )
                target.auto_renew = False
            else:
                await db.commit()
                pool = await get_arq_pool()
                await pool.enqueue_job(
                    "finalize_tkassa_verification",
                    payment.id, kind, target.id, str(rebill_id), payment.target_amount, payment_id,
                    _job_id=f"tkassa-verify:{payment_id}",
                )
                return PlainTextResponse("OK")
        else:
            now = datetime.now(timezone.utc)
            base = (
                target.subscription_expires_at
                if target.subscription_expires_at and target.subscription_expires_at > now
                else now
            )
            from app.services.subscription import apply_successful_payment
            # Предоплата вперёд: продлеваем на весь оплаченный срок, а не на месяц
            apply_successful_payment(target, base + timedelta(days=30 * max(1, payment.months or 1)))
            target.subscription_status = SalonSubscriptionStatus.ACTIVE
            if kind == "business" and target.hidden_reason == "billing":
                # Оплатили после того, как салон уже скрыли за неоплату
                # (см. app.tasks.expire_unpaid_salons) — возвращаем в каталог.
                target.is_hidden = False
                target.hidden_reason = None

        await db.commit()
        return PlainTextResponse("OK")

    if status in _FAILURE_STATUSES or not success:
        payment.status = PaymentStatus.FAILED
        payment.provider_transaction_id = payment_id
        payment.raw_payload = payload

        if payment.kind == PaymentKind.VERIFICATION:
            target.auto_renew = False
        else:
            target.subscription_status = SalonSubscriptionStatus.PAST_DUE
            try:
                from app.services.notifications import notify_admins
                await notify_admins(
                    db, "Не удалось списать оплату подписки",
                    f"{_target_label(target, kind)}: "
                    f"{payload.get('ErrorCode') or 'причина не указана'}",
                )
            except Exception:
                logger.exception("tkassa/notify: не удалось отправить алерт")

        await db.commit()
        return PlainTextResponse("OK")

    # Промежуточный статус (NEW/FORM_SHOWED/3DS_CHECKING и т.п.) — просто
    # подтверждаем получение, ждём терминального уведомления.
    return PlainTextResponse("OK")
