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
            if client is None or not client.tg_chat_id:
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
        chat_id = client.tg_chat_id
    except TransientTaskError:
        raise
    except Exception as exc:  # БД недоступна и т.п. — пробуем позже
        logger.warning("send_booking_reminder %s: сбой (попытка %d): %s",
                       booking_id, ctx["job_try"], exc)
        raise _retry(ctx, exc) from exc

    try:
        await _send_via_telegram(chat_id, text)
    except TransientTaskError as exc:
        raise _retry(ctx, exc) from exc
    return "sent"


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
        msg.add_alternative(html, subtype="html")

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
