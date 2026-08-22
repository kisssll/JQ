# app/tasks.py
"""Фоновые задачи (ARQ) — блок 06 роадмапа.

Выполняются arq-воркером вне HTTP-запроса:
    arq app.core.worker.WorkerSettings

Ретраи: на временных сбоях (сеть, 5xx провайдера, недоступность БД) задача
поднимает arq.worker.Retry с растущей задержкой; после WorkerSettings.max_tries
попыток job уходит в failed. Постоянные ошибки (кривой payload) не ретраим.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from arq.worker import Retry

logger = logging.getLogger(__name__)

# Задержка перед повтором = RETRY_BASE_DELAY * номер попытки (5с, 10с, 15с…)
RETRY_BASE_DELAY = 5


class TransientTaskError(Exception):
    """Временный сбой (сеть/провайдер/БД) — задачу нужно повторить."""


def _retry(ctx: dict[str, Any], exc: Exception) -> Retry:
    """Retry с линейным backoff по номеру текущей попытки."""
    return Retry(defer=RETRY_BASE_DELAY * ctx["job_try"])


def _mask_phone(phone: str) -> str:
    """Телефон в логах не светим целиком: +7999***99."""
    return f"{phone[:5]}***{phone[-2:]}" if len(phone) > 7 else "***"


# ── SMS / flash-call ─────────────────────────────────────────────


async def _send_via_provider(phone: str, message: str) -> None:
    """Единственная точка вызова SMS/flash-call-провайдера.

    Провайдер подключается в блоке 07 (OTP): здесь появится HTTP-вызов его
    API; сетевые ошибки и 5xx оборачивать в TransientTaskError, ошибки
    вида «невалидный номер» — пробрасывать как есть (ретрай не поможет).
    Пока провайдера нет — dev-заглушка, пишет сообщение в лог.
    """
    logger.info("[dev-заглушка SMS] %s: %s", _mask_phone(phone), message)


async def send_sms(ctx: dict[str, Any], phone: str, message: str) -> str:
    """Отправка SMS вне запроса (OTP-коды, уведомления о записи)."""
    try:
        await _send_via_provider(phone, message)
    except TransientTaskError as exc:
        logger.warning(
            "send_sms %s: временный сбой (попытка %d): %s",
            _mask_phone(phone), ctx["job_try"], exc,
        )
        raise _retry(ctx, exc) from exc
    logger.info("send_sms %s: отправлено (попытка %d)", _mask_phone(phone), ctx["job_try"])
    return "sent"


# ── Telegram-уведомления (бот @rumi_beauty_bot) ──────────────────


async def _send_via_telegram(chat_id: int, text: str) -> None:
    """Отправка сообщения ботом через Bot API (без aiogram: воркеру не нужен
    polling, достаточно одного HTTPS-вызова; конфликтов с процессом бота нет).

    Сетевые ошибки и 5xx/429 — TransientTaskError (ретрай); 403 «bot was
    blocked» и прочие 4xx — постоянные, не ретраим.
    """
    import httpx

    from app.core.config import settings

    if not settings.TG_BOT_TOKEN:
        logger.info("[dev-заглушка TG] chat=%s: %s", chat_id, text[:60])
        return

    url = f"https://api.telegram.org/bot{settings.TG_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text})
    except httpx.HTTPError as exc:
        raise TransientTaskError(f"сеть: {exc}") from exc

    if resp.status_code >= 500 or resp.status_code == 429:
        raise TransientTaskError(f"Bot API {resp.status_code}")
    if resp.status_code != 200:
        # 403 = пользователь заблокировал бота и т.п. — ретрай не поможет
        logger.warning("telegram chat=%s: постоянный отказ %s %s",
                       chat_id, resp.status_code, resp.text[:120])


async def _send_via_max(chat_id: int, text: str) -> None:
    """Отправка сообщения ботом MAX. В отличие от Telegram публичного HTTP-API
    под рукой нет — пользуемся клиентом maxapi (это разовый вызов, polling не
    поднимаем, конфликта с процессом бота нет).

    Сетевые сбои — TransientTaskError (ретрай); остальное считаем постоянным.
    """
    from app.core.config import settings

    if not settings.MAX_BOT_TOKEN:
        logger.info("[dev-заглушка MAX] chat=%s: %s", chat_id, text[:60])
        return

    from maxapi import Bot

    bot = Bot(settings.MAX_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:  # библиотека не разделяет сетевые/логические ошибки
        raise TransientTaskError(f"MAX: {exc}") from exc
    finally:
        try:
            await bot.close_session()
        except Exception:  # закрытие сессии не должно ронять задачу
            logger.debug("max chat=%s: сессия не закрылась", chat_id, exc_info=True)


async def _deliver(channel, address, text: str, subject: str = "Руми") -> None:
    """Отправка в уже отрезолвленный канал — общий транспорт для задач,
    которые шлют пользователю напрямую (напоминания). Канал резолвится
    вызывающим кодом через notify_channel.resolve()."""
    from app.models.models import NotifyChannel

    if address is None:
        return
    if channel == NotifyChannel.EMAIL:
        await _send_via_smtp(address, subject, text)
    elif channel == NotifyChannel.MAX:
        await _send_via_max(address, text)
    else:
        await _send_via_telegram(address, text)


async def send_max_message(ctx: dict[str, Any], chat_id: int, text: str) -> str:
    """Уведомление в MAX вне запроса — зеркало send_tg_message."""
    try:
        await _send_via_max(chat_id, text)
    except TransientTaskError as exc:
        logger.warning(
            "send_max_message chat=%s: временный сбой (попытка %d): %s",
            chat_id, ctx["job_try"], exc,
        )
        raise _retry(ctx, exc) from exc
    logger.info("send_max_message chat=%s: отправлено (попытка %d)", chat_id, ctx["job_try"])
    return "sent"


async def send_tg_message(ctx: dict[str, Any], chat_id: int, text: str) -> str:
    """Уведомление в Telegram вне запроса (записи, напоминания)."""
    try:
        await _send_via_telegram(chat_id, text)
    except TransientTaskError as exc:
        logger.warning(
            "send_tg_message chat=%s: временный сбой (попытка %d): %s",
            chat_id, ctx["job_try"], exc,
        )
        raise _retry(ctx, exc) from exc
    logger.info("send_tg_message chat=%s: отправлено (попытка %d)", chat_id, ctx["job_try"])
    return "sent"


async def send_booking_reminder(ctx: dict[str, Any], booking_id: int) -> str:
    """Напоминание клиенту за N часов до визита (ставится отложенно при
    создании записи, _job_id = booking-reminder:{id} — дубли не плодятся).

    Статус проверяем в момент отправки: запись могли отменить — тогда
    молчим. Ошибки БД — транзиентные (ретрай), «нет записи» — постоянная.
    """
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.models import Booking, BookingStatus, Master, Salon, Service, User

    try:
        async with AsyncSessionLocal() as db:
            booking = (
                await db.execute(select(Booking).where(Booking.id == booking_id))
            ).scalar_one_or_none()
            if booking is None:
                return "skipped:missing"
            if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
                return f"skipped:{booking.status.value}"

            client = (
                await db.execute(select(User).where(User.id == booking.client_id))
            ).scalar_one_or_none()
            from app.services.notify_channel import has_channel
            if client is None or not has_channel(client):
                return "skipped:no-chat"

            from app.services.notifications import TOPIC_REMINDERS, wants
            if not wants(client, TOPIC_REMINDERS):
                return "skipped:muted"  # клиент отключил напоминания в боте

            master = (
                await db.execute(select(Master).where(Master.id == booking.master_id))
            ).scalar_one()
            salon = (
                await db.execute(select(Salon).where(Salon.id == master.salon_id))
            ).scalar_one()
            service = (
                await db.execute(select(Service).where(Service.id == booking.service_id))
            ).scalar_one_or_none()

        text = (
            f"⏰ Напоминаем: сегодня в {booking.start_time.strftime('%H:%M')} — "
            f"{service.name if service else 'услуга'} в «{salon.name}»\n"
            f"Адрес: {salon.address or 'уточните у салона'}"
        )
        # Канал клиента резолвим здесь же — дальше объект пользователя не трогаем
        from app.services.notify_channel import resolve as _resolve_channel
        channel, address = _resolve_channel(client)
    except TransientTaskError:
        raise
    except Exception as exc:  # БД недоступна и т.п. — пробуем позже
        logger.warning("send_booking_reminder %s: сбой (попытка %d): %s",
                       booking_id, ctx["job_try"], exc)
        raise _retry(ctx, exc) from exc

    try:
        await _deliver(channel, address, text, subject="Напоминание о записи — Руми")
    except TransientTaskError as exc:
        raise _retry(ctx, exc) from exc
    return "sent"


async def send_evening_deals_blast(ctx: dict[str, Any]) -> str:
    """Ежедневная рассылка «вечерних окон со скидкой» (cron 18:00 по Томску =
    11:00 UTC, см. worker.WorkerSettings.cron_jobs).

    Шлём только если сегодня есть хоть одно свободное вечернее окно со скидкой.
    Аудитория — все привязавшие Telegram (не гости), не отключившие топик
    «Вечерние скидки» (opt-out, default вкл). Каждому — отдельный send_tg_message
    через очередь (ретраи/дедуп — на его стороне)."""
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.worker import get_arq_pool
    from app.db.session import AsyncSessionLocal
    from app.models.models import User
    from app.services.evening_deals_service import any_windows_today
    from app.services.notifications import TOPIC_EVENING_DEALS, wants

    try:
        async with AsyncSessionLocal() as db:
            if not await any_windows_today(db):
                return "skipped:no-windows"
            from app.services.notify_channel import has_channel_clause
            recipients = (await db.execute(
                select(User).where(
                    has_channel_clause(),
                    User.is_guest == False,  # noqa: E712
                )
            )).scalars().all()
    except Exception as exc:  # БД недоступна — повторим
        logger.warning("send_evening_deals_blast: сбой выборки (попытка %d): %s", ctx["job_try"], exc)
        raise _retry(ctx, exc) from exc

    link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/evening-deals"
    text = (
        "🌙 Подборка вечерних окон на сегодня со скидкой.\n"
        "Свободные вечерние слоты в салонах — успейте записаться дешевле:\n"
        f"{link}"
    )

    from app.services.notify_channel import resolve as _resolve_channel
    from app.models.models import NotifyChannel as _NC

    pool = await get_arq_pool()
    sent = 0
    for u in recipients:
        if not wants(u, TOPIC_EVENING_DEALS):
            continue
        channel, address = _resolve_channel(u)
        if address is None:
            continue
        if channel == _NC.EMAIL:
            await pool.enqueue_job("send_email", address, "Вечерние окна со скидкой — Руми", text)
        else:
            task = "send_max_message" if channel == _NC.MAX else "send_tg_message"
            await pool.enqueue_job(task, address, text)
        sent += 1
    logger.info("send_evening_deals_blast: поставлено %d сообщений", sent)
    return f"queued:{sent}"


# ── Email (noreply@rrumi.ru через SMTP Timeweb) ──────────────────


async def _send_via_smtp(to: str, subject: str, body: str, html: Optional[str] = None) -> None:
    """Единственная точка отправки писем. mock — в лог (dev/до кредов).

    body — текстовый вариант (fallback), html — опциональная HTML-версия
    (add_alternative: почтовые клиенты покажут HTML, но текст останется для
    тех, кто HTML не рендерит). Сетевые сбои и 4xx-коды SMTP (временные) —
    TransientTaskError; постоянные отказы (несуществующий ящик, 5xx) не ретраим.
    """
    from app.core.config import settings

    if settings.EMAIL_MODE == "mock" or not settings.SMTP_PASSWORD:
        logger.info("[dev-заглушка email] %s: %s", to, subject)
        return

    from email.message import EmailMessage

    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        # base64, а не quoted-printable по умолчанию: QP переносит длинные
        # строки на 76 символах мягким переносом (=\n) прямо посреди href, и
        # часть почтовых клиентов ломает на этом ссылки. base64 декодируется
        # байт-в-байт — URL остаются целыми.
        msg.add_alternative(html, subtype="html", cte="base64")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=True,  # 465 = implicit TLS
            timeout=15,
        )
    except aiosmtplib.SMTPResponseException as exc:
        if 400 <= exc.code < 500:
            raise TransientTaskError(f"SMTP {exc.code}") from exc
        logger.warning("email %s: постоянный отказ SMTP %s %s", to, exc.code, exc.message)
    except (aiosmtplib.SMTPException, OSError) as exc:
        raise TransientTaskError(f"SMTP: {exc}") from exc


async def send_email(ctx: dict[str, Any], to: str, subject: str, body: str, html: Optional[str] = None) -> str:
    """Отправка письма вне запроса (сброс пароля, сервисные письма).
    html — опциональная HTML-версия (для брендированных писем)."""
    try:
        await _send_via_smtp(to, subject, body, html)
    except TransientTaskError as exc:
        logger.warning("send_email %s: временный сбой (попытка %d): %s",
                       to, ctx["job_try"], exc)
        raise _retry(ctx, exc) from exc
    logger.info("send_email %s: отправлено (попытка %d)", to, ctx["job_try"])
    return "sent"


# ── Вебхуки оплаты (Т-Касса) ─────────────────────────────────────


async def _apply_payment_update(payload: dict[str, Any]) -> None:
    """Применение статуса платежа к БД (подписки, блок 09).

    Здесь появится: проверка Token (подпись Т-Кассы), поиск платежа по
    OrderId, идемпотентное обновление статуса подписки. Ошибки подключения
    к БД оборачивать в TransientTaskError. Пока блока 09 нет — заглушка.
    """
    logger.info(
        "[dev-заглушка payment] OrderId=%s Status=%s",
        payload.get("OrderId"), payload.get("Status"),
    )


async def process_payment_webhook(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Обработка вебхука оплаты вне запроса.

    Эндпоинт вебхука (блок 09) сразу отвечает Т-Кассе "OK" и кладёт payload
    в очередь. Дедупликация повторных доставок — на стороне enqueue через
    _job_id=f"tkassa:{OrderId}:{Status}" (arq не ставит дубль job_id).
    """
    if not payload.get("OrderId"):
        # Постоянная ошибка: без OrderId платёж не идентифицировать, ретрай бессмыслен
        logger.error("process_payment_webhook: payload без OrderId, отбрасываем: %r", payload)
        return "rejected"
    try:
        await _apply_payment_update(payload)
    except TransientTaskError as exc:
        logger.warning(
            "process_payment_webhook OrderId=%s: временный сбой (попытка %d): %s",
            payload["OrderId"], ctx["job_try"], exc,
        )
        raise _retry(ctx, exc) from exc
    logger.info("process_payment_webhook OrderId=%s: обработан", payload["OrderId"])
    return "processed"


# ── Оплата подписок (Т-Касса) ──────────────────────────────────────
#
# Отдельно от Т-Кассы-заглушки выше (process_payment_webhook/_apply_payment_update
# — задел под другой, ещё не выбранный сценарий, не трогаем). Вебхук
# /tkassa/notify (app/api/v1/endpoints/payments.py) сразу отвечает "OK" и
# синхронно проставляет статус платежа/подписки в БД — это быстро (одна
# транзакция). В очередь уходит только медленная часть после успешной
# ВЕРИФИКАЦИОННОЙ оплаты (1₽): возврат этого рубля — внешний HTTP-вызов к
# Т-Кассе, который не должен блокировать ответ на вебхук.


async def finalize_tkassa_verification(
    ctx: dict[str, Any],
    payment_id: int,
    kind: str,
    target_id: int,
    rebill_id: str,
    target_amount: float,
    provider_payment_id: str,
) -> str:
    """После успешного верификационного платежа (1₽, см. PaymentKind.VERIFICATION):
    вернуть эту сумму клиенту и сохранить RebillId + сумму месячного платежа
    на плательщике (салон при kind='business', пользователь-модель при
    kind='model') — у Т-Кассы нет объекта «подписка», регулярные списания
    дальше планирует и вызывает сама платформа (см. charge_due_subscriptions).

    Возврат 1₽ — best-effort: если он не удался, не блокируем сохранение
    RebillId (сумма минимальна, важнее не оставить плательщика без автопродления).
    """
    from decimal import Decimal

    from app.db.session import AsyncSessionLocal
    from app.models.models import Salon, User
    from app.services.tkassa import TKassaClient, TKassaError

    try:
        client = TKassaClient()
    except TKassaError as exc:
        logger.error("finalize_tkassa_verification(%s): клиент недоступен: %s", payment_id, exc)
        return "rejected"

    try:
        await client.cancel(payment_id=provider_payment_id, amount_rub=Decimal("1.00"))
    except TKassaError:
        logger.exception(
            "finalize_tkassa_verification(%s): возврат 1₽ не удался, продолжаем "
            "(сумма минимальна, сохранить RebillId важнее)", payment_id,
        )

    model = Salon if kind == "business" else User
    async with AsyncSessionLocal() as db:
        target = await db.get(model, target_id)
        if target is None:
            logger.error("finalize_tkassa_verification: %s %s не найден", kind, target_id)
            return "rejected"
        target.recurring_token = rebill_id
        target.subscription_amount = target_amount
        await db.commit()

    logger.info("finalize_tkassa_verification(%s): RebillId сохранён для %s %s", payment_id, kind, target_id)
    return "processed"


async def _charge_due(db, client, kind: str, targets: list, notification_url: str, return_url: str, now) -> int:
    """Общий проход по «должникам» одного вида (салоны ИЛИ модели) — см.
    charge_due_subscriptions. Возвращает число успешно продлённых.

    Для салонов (kind='business') тариф на КАЖДОЕ автосписание пересчитывается
    заново по фактическому числу активных мастеров (см.
    resolve_plan_for_employee_count в app/services/tariffs.py) — так тариф сам
    «дорастает»/«сжимается» вместе со штатом, без ручного переключения
    владельцем. У моделей такого пересчёта нет — там тариф не зависит от
    штата, берём как есть (subscription_amount, выставленный при выборе)."""
    import uuid
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from sqlalchemy import func, select

    from app.models.models import Master, Payment, PaymentKind, PaymentStatus, SalonSubscriptionStatus
    from app.services.tariffs import TariffError, compute_amount, resolve_plan_for_employee_count
    from app.services.tkassa import TKassaError

    processed = 0
    for target in targets:
        if kind == "business":
            active_masters = (await db.execute(
                select(func.count(Master.id)).where(
                    Master.salon_id == target.id, Master.is_active == True,  # noqa: E712
                )
            )).scalar() or 0
            plan = resolve_plan_for_employee_count(active_masters)
            try:
                amount = compute_amount(plan, active_masters)
            except TariffError as exc:
                logger.error(
                    "charge_due_subscriptions: salon %s — тариф не определить (%s), пропуск",
                    target.id, exc,
                )
                continue
            target.business_tier = plan
            # Доплата за рост штата внутри оплаченного месяца — в этот счёт
            amount = (amount + Decimal(str(target.pending_proration or 0))).quantize(Decimal("0.01"))
            target.subscription_amount = float(amount)
        else:
            amount = Decimal(str(target.subscription_amount or 0))
            if amount <= 0:
                logger.error("charge_due_subscriptions: %s %s без subscription_amount, пропуск", kind, target.id)
                continue
            plan = target.subscription_tier.value if target.subscription_tier else ""

        payment = Payment(
            plan=plan or "", kind=PaymentKind.RECURRENT, amount=float(amount),
            invoice_id=uuid.uuid4().hex,
            **({"salon_id": target.id} if kind == "business" else {"user_id": target.id}),
        )
        db.add(payment)
        await db.flush()

        try:
            init_result = await client.init(
                order_id=payment.invoice_id, amount_rub=amount,
                description=f"Автопродление тарифа «{plan}» — Руми",
                notification_url=notification_url, success_url=return_url, fail_url=return_url,
            )
            payment.provider_transaction_id = init_result.payment_id
            charge_result = await client.charge(
                payment_id=init_result.payment_id, rebill_id=target.recurring_token,
            )
        except TKassaError as exc:
            logger.error("charge_due_subscriptions: %s %s — списание не удалось: %s", kind, target.id, exc)
            payment.status = PaymentStatus.FAILED
            target.subscription_status = SalonSubscriptionStatus.PAST_DUE
            await db.commit()
            try:
                from app.services.notifications import notify_model_subscription, notify_subscription
                fail_text = (
                    "не удалось списать оплату по карте. Продлите тариф вручную в кабинете, "
                    "иначе доступ закончится и карточка пропадёт из каталога."
                )
                if kind == "business":
                    await notify_subscription(db, target, fail_text)
                else:
                    await notify_model_subscription(db, target, fail_text)
            except Exception:
                logger.exception("charge_due_subscriptions: владелец не уведомлён")
            try:
                from app.services.notifications import notify_admins
                label = f"Салон «{target.name}» (id={target.id})" if kind == "business" else f"Модель id={target.id}"
                await notify_admins(
                    db, "Не удалось списать автопродление подписки",
                    f"{label}, тариф «{plan}»: {exc}",
                )
            except Exception:
                logger.exception("charge_due_subscriptions: не удалось отправить алерт")
            continue

        if charge_result.status == "CONFIRMED":
            payment.status = PaymentStatus.SUCCEEDED
            payment.paid_at = datetime.now(timezone.utc)
            from app.services.subscription import apply_successful_payment
            apply_successful_payment(
                target, now + timedelta(days=30),
                active_masters=active_masters if kind == "business" else None,
            )
            target.subscription_status = SalonSubscriptionStatus.ACTIVE
            processed += 1
        # Иначе не подтверждён сразу — платёж остаётся PENDING, статус
        # финализирует вебхук /tkassa/notify терминальным уведомлением.
        await db.commit()
    return processed


async def charge_due_subscriptions(ctx: dict[str, Any]) -> str:
    """Плановые автосписания по автопродлению — раз в сутки (cron, см.
    app/core/worker.py). Обслуживает и салоны (бизнес-тариф), и моделей —
    у Т-Кассы нет своего планировщика подписок: плательщику с auto_renew=True
    и истёкшим subscription_expires_at заводим новый Init (свежий OrderId на
    сумму subscription_amount) и тут же Charge по сохранённому recurring_token
    (RebillId). Ошибка одного плательщика не должна прерывать обработку
    остальных — поэтому try/except внутри цикла (см. _charge_due), а не вокруг."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.config import settings
    from app.db.session import AsyncSessionLocal
    from app.models.models import Salon, SalonSubscriptionStatus, User
    from app.services.tkassa import TKassaClient, TKassaError

    now = datetime.now(timezone.utc)
    due_statuses = [
        SalonSubscriptionStatus.TRIALING, SalonSubscriptionStatus.ACTIVE, SalonSubscriptionStatus.PAST_DUE,
    ]

    async with AsyncSessionLocal() as db:
        due_salons = (await db.execute(
            select(Salon).where(
                Salon.auto_renew == True,  # noqa: E712
                Salon.recurring_token.isnot(None),
                Salon.subscription_status.in_(due_statuses),
                Salon.subscription_expires_at <= now,
            )
        )).scalars().all()
        due_models = (await db.execute(
            select(User).where(
                User.auto_renew == True,  # noqa: E712
                User.recurring_token.isnot(None),
                User.subscription_status.in_(due_statuses),
                User.subscription_expires_at <= now,
            )
        )).scalars().all()

        if not due_salons and not due_models:
            return "processed:0"

        try:
            client = TKassaClient()
        except TKassaError as exc:
            logger.error("charge_due_subscriptions: клиент недоступен: %s", exc)
            return "rejected"

        base = settings.PUBLIC_BASE_URL.rstrip("/")
        notification_url = f"{base}/api/v1/payments/tkassa/notify"

        processed = 0
        if due_salons:
            processed += await _charge_due(
                db, client, "business", due_salons, notification_url,
                f"{base}/business/dashboard?tab=billing", now,
            )
        if due_models:
            processed += await _charge_due(
                db, client, "model", due_models, notification_url,
                f"{base}/model/join", now,
            )

    logger.info(
        "charge_due_subscriptions: успешно продлено %d из %d",
        processed, len(due_salons) + len(due_models),
    )
    return f"processed:{processed}"


async def subscription_reminders(ctx: dict[str, Any]) -> str:
    """Ежедневные напоминания по подписке (крон).

    Жёсткое отключение по истечении срока честно только тогда, когда человека
    предупредили заранее — поэтому набор такой:
      * триал заканчивается: за 3 дня и в последний день;
      * автосписание: за 3 дня, с суммой;
      * БЕЗ автопродления (платит вручную): за 7, 3 и 1 день;
      * доступ истёк сегодня: салон скрыт из каталога.
    Задача идёт раз в сутки, поэтому дублей не будет и без отдельного журнала:
    условие срабатывает ровно в свой день.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.models import Salon, SalonSubscriptionStatus, User
    from app.services.notifications import notify_model_subscription, notify_subscription
    from app.services.subscription import _aware
    from app.services.tariffs import TARIFF_CATALOG

    now = datetime.now(timezone.utc)
    sent = 0

    def _days_until(value) -> Optional[int]:
        value = _aware(value)
        return (value.date() - now.date()).days if value else None

    async def _messages_for(target, is_salon: bool) -> list[str]:
        out: list[str] = []
        status = target.subscription_status
        trial_left = _days_until(getattr(target, "trial_ends_at", None))
        paid_left = _days_until(getattr(target, "subscription_expires_at", None))
        access_left = _days_until(getattr(target, "access_until", None))

        if status == SalonSubscriptionStatus.TRIALING and trial_left in (3, 0):
            plan = TARIFF_CATALOG.get(getattr(target, "business_tier", None))
            price = f", дальше тариф «{plan.name}»" if plan else ""
            out.append(
                "бесплатный период заканчивается сегодня" if trial_left == 0
                else "бесплатный период заканчивается через 3 дня"
                f"{price}. Оплатите, чтобы не пропасть из каталога."
            )
        elif status in (SalonSubscriptionStatus.ACTIVE, SalonSubscriptionStatus.PAST_DUE):
            amount = getattr(target, "subscription_amount", None)
            pending = float(getattr(target, "pending_proration", 0) or 0)
            total = (amount or 0) + pending
            if target.auto_renew and paid_left == 3:
                sum_str = f" {int(round(total))} ₽" if total else ""
                out.append(f"через 3 дня спишем{sum_str} за следующий месяц.")
            elif not target.auto_renew and paid_left in (7, 3, 1):
                out.append(
                    f"оплаченный период заканчивается через {paid_left} "
                    f"{'день' if paid_left == 1 else 'дня'} — продлите тариф в кабинете."
                )

        if access_left is not None and access_left == 0 and not (status == SalonSubscriptionStatus.TRIALING):
            out.append(
                "доступ по тарифу закончился — карточка скрыта из каталога, новая запись "
                "закрыта. Уже созданные записи сохранены."
                if is_salon else
                "доступ по тарифу закончился — анкета скрыта из поиска."
            )
        return out

    async with AsyncSessionLocal() as db:
        salons = (await db.execute(
            select(Salon).where(Salon.subscription_status != SalonSubscriptionStatus.NONE)
        )).scalars().all()
        for salon in salons:
            for text in await _messages_for(salon, True):
                await notify_subscription(db, salon, text)
                sent += 1

        models = (await db.execute(
            select(User).where(User.subscription_status != SalonSubscriptionStatus.NONE)
        )).scalars().all()
        for user in models:
            for text in await _messages_for(user, False):
                await notify_model_subscription(db, user, text)
                sent += 1

    logger.info("subscription_reminders: отправлено %d напоминаний", sent)
    return f"sent:{sent}"
