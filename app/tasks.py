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

# Сверка возвратов (см. reconcile_refunds): за какой срок назад перепроверяем
# успешные платежи и сколько берём за один прогон. Месяца подписки с запасом
# хватает — возврат за более старый платёж уже не отбирает живой доступ.
RECONCILE_WINDOW_DAYS = 60
RECONCILE_MAX_PER_RUN = 200

# Сколько ждём фискальные реквизиты, прежде чем считать чек непробитым
# (см. check_pending_receipts): чек пробивается за секунды, час — с запасом.
RECEIPT_GRACE_HOURS = 1

# Через сколько дней после публикации салона спрашиваем владельца об удобстве
# сервиса (см. ask_service_rating): раньше человек ещё не успел поработать.
SERVICE_RATING_AFTER_DAYS = 14

# Задержка перед повтором = RETRY_BASE_DELAY * номер попытки (5с, 10с, 15с…)
RETRY_BASE_DELAY = 5


class TransientTaskError(Exception):
    """Временный сбой (сеть/провайдер/БД) — задачу нужно повторить."""


class RecipientGone(Exception):
    """Мессенджер отказал доставлять ЭТОМУ человеку насовсем: бот заблокирован,
    чат удалён, аккаунт удалён. Повтор не поможет, пока человек сам не
    вернётся к боту.

    Отдельно от «сообщение отклонено» (return False): слишком длинный текст или
    кривая разметка — наша ошибка, и уводить из-за неё человека с канала нельзя.
    Отдельно и от неверного токена бота — это сломались мы, а не он.
    """


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


async def _send_via_telegram(chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Отправка сообщения ботом через Bot API (без aiogram: воркеру не нужен
    polling, достаточно одного HTTPS-вызова; конфликтов с процессом бота нет).

    Сетевые ошибки и 5xx/429 — TransientTaskError (ретрай); 403 «bot was
    blocked» и прочие 4xx — постоянные, не ретраим.

    Возвращает, дошло ли сообщение. Раньше постоянный отказ уходил в журнал, а
    функция возвращалась как ни в чём не бывало — и вызывающий код принимал
    молчание за успех. Так на стейдже вопрос о согласии «спросил» человека,
    которому ничего не пришло (chat not found), и пометил его спрошенным.
    """
    import httpx

    from app.core.config import settings

    if not settings.TG_BOT_TOKEN:
        logger.info("[dev-заглушка TG] chat=%s: %s", chat_id, text[:60])
        return True

    url = f"https://api.telegram.org/bot{settings.TG_BOT_TOKEN}/sendMessage"
    # Тот же прокси, что у бота: уведомления идут мимо aiogram, и без этого
    # они молча не доходили бы даже при живом боте.
    try:
        async with httpx.AsyncClient(timeout=10, proxy=settings.tg_proxy) as client:
            payload = {"chat_id": chat_id, "text": text}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise TransientTaskError(f"сеть: {exc}") from exc

    if resp.status_code >= 500 or resp.status_code == 429:
        raise TransientTaskError(f"Bot API {resp.status_code}")
    if resp.status_code != 200:
        try:
            description = str(resp.json().get("description", ""))
        except ValueError:
            description = resp.text[:200]
        # 403 — бот заблокирован / аккаунт удалён; 400 «chat not found» — чата
        # с ботом нет. Это про человека. Остальные 400 (длина, разметка) и
        # 401/404 (токен) — про нас: канал человека не трогаем.
        if resp.status_code == 403 or (
            resp.status_code == 400 and "chat not found" in description.lower()
        ):
            logger.warning("telegram chat=%s: получатель недоступен: %s",
                           chat_id, description[:120])
            raise RecipientGone(description)
        logger.warning("telegram chat=%s: постоянный отказ %s %s",
                       chat_id, resp.status_code, description[:120])
        return False
    return True


async def _send_via_max(chat_id: int, text: str, attachments: list | None = None) -> bool:
    """Отправка сообщения ботом MAX. В отличие от Telegram публичного HTTP-API
    под рукой нет — пользуемся клиентом maxapi (это разовый вызов, polling не
    поднимаем, конфликта с процессом бота нет).

    Возвращает, дошло ли. 403/404 — получатель недоступен (RecipientGone);
    прочие 4xx — сообщение отклонено (False); сеть, 429, 5xx и всё
    нераспознанное — TransientTaskError (ретрай). Раньше ЛЮБАЯ ошибка считалась
    временной: заблокировавшему бота слали повторы до исчерпания попыток.
    """
    from app.core.config import settings

    if not settings.MAX_BOT_TOKEN:
        logger.info("[dev-заглушка MAX] chat=%s: %s", chat_id, text[:60])
        return True

    from maxapi import Bot
    from maxapi.exceptions.max import MaxApiError

    bot = Bot(settings.MAX_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=chat_id, text=text, attachments=attachments)
    except MaxApiError as exc:
        if exc.code in (403, 404):
            logger.warning("max chat=%s: получатель недоступен: %s", chat_id, exc.raw)
            raise RecipientGone(str(exc.raw)) from exc
        if exc.code == 429 or exc.code >= 500:
            raise TransientTaskError(f"MAX {exc.code}") from exc
        logger.warning("max chat=%s: постоянный отказ %s %s", chat_id, exc.code, exc.raw)
        return False
    except Exception as exc:  # сеть, неверный токен — не вина получателя
        raise TransientTaskError(f"MAX: {exc}") from exc
    finally:
        try:
            await bot.close_session()
        except Exception:  # закрытие сессии не должно ронять задачу
            logger.debug("max chat=%s: сессия не закрылась", chat_id, exc_info=True)
    return True


async def _send_via_vk(peer_id: int, text: str, keyboard: dict | None = None) -> bool:
    """Сообщение ботом сообщества ВК. Та же классификация, что у Telegram и MAX.

    900/901/902 — человек заблокировал сообщество или закрыл сообщения
    (RecipientGone); флуд-контроль, внутренние ошибки ВК и сеть — повтор
    (TransientTaskError); всё прочее — сообщение отклонено (False), в том
    числе неверный ключ: это сломались мы, а не получатель.
    """
    import httpx

    from app.core.config import settings
    from app.services import vk_api

    if not settings.VK_BOT_TOKEN:
        logger.info("[dev-заглушка VK] peer=%s: %s", peer_id, text[:60])
        return True

    try:
        await vk_api.send_message(peer_id, text, keyboard)
    except vk_api.VkApiError as exc:
        if exc.code in vk_api.RECIPIENT_GONE_CODES:
            logger.warning("vk peer=%s: получатель недоступен: %s", peer_id, exc)
            raise RecipientGone(str(exc)) from exc
        if exc.code in vk_api.TRANSIENT_CODES:
            raise TransientTaskError(str(exc)) from exc
        logger.warning("vk peer=%s: постоянный отказ: %s", peer_id, exc)
        return False
    except (httpx.HTTPError, ValueError) as exc:
        raise TransientTaskError(f"VK: {exc}") from exc
    return True


async def _deliver(channel, address, text: str, subject: str = "Руми") -> None:
    """Отправка в уже отрезолвленный канал — общий транспорт для задач,
    которые шлют пользователю напрямую (напоминания). Канал резолвится
    вызывающим кодом через notify_channel.resolve()."""
    from app.models.models import NotifyChannel

    if address is None:
        return
    try:
        if channel == NotifyChannel.EMAIL:
            await _send_via_smtp(address, subject, text)
        elif channel == NotifyChannel.MAX:
            await _send_via_max(address, text)
        elif channel == NotifyChannel.VK:
            await _send_via_vk(address, text)
        elif channel == NotifyChannel.TG:
            await _send_via_telegram(address, text)
        else:
            logger.warning("_deliver: неизвестный канал %s", channel)
    except RecipientGone:
        await _reroute_after_refusal(channel, address, text, subject)


async def _mark_channel_broken(channel_value: str, address) -> None:
    """Только отметка, без досылки — для сообщений, которым запасной канал
    не подходит (кнопки-звёзды, опрос). Сбой базы не роняем:
    сообщение всё равно не дойдёт, а отметку поставит следующий отказ."""
    from app.db.session import AsyncSessionLocal
    from app.models.models import NotifyChannel
    from app.services.notify_channel import mark_broken

    try:
        async with AsyncSessionLocal() as db:
            await mark_broken(db, NotifyChannel(channel_value), address)
    except Exception:
        logger.exception("%s chat=%s: не удалось пометить отказ", channel_value, address)


async def _reroute_after_refusal(channel, address, text: str, subject: str = "Руми") -> str:
    """Мессенджер отказал насовсем: пометить его сломанным у всех, кто к нему
    привязан, и сразу дослать ЭТО уведомление запасным каналом.

    Раньше отказ уходил в журнал, канал оставался прежним, и человек молча
    переставал получать напоминания — ни он, ни мы об этом не знали. Привязку не
    стираем: разблокирует бота — и доставка вернётся сама (clear_broken).

    Досылка идёт через очередь, а не напрямую: у запасного канала свои ретраи.
    Ошибка базы — TransientTaskError: повтор задачи снова получит отказ и
    снова попробует пометить, так что отказ не потеряется.
    """
    from app.core.worker import get_arq_pool
    from app.db.session import AsyncSessionLocal
    from app.models.models import NotifyChannel
    from app.services.notify_channel import mark_broken, resolve, task_for

    try:
        async with AsyncSessionLocal() as db:
            users = await mark_broken(db, channel, address)
            targets = [(u.id, *resolve(u)) for u in users]
    except Exception as exc:
        raise TransientTaskError(f"отметка отказа: {exc}") from exc

    if not targets:
        # Чат ни к кому не привязан (ответ поддержки в непривязанный чат) —
        # помечать и досылать некому.
        logger.info("%s chat=%s: отказ, но аккаунтов с этим чатом нет", channel.value, address)
        return "gone:unlinked"

    pool = await get_arq_pool()
    rerouted = 0
    for user_id, fallback, fallback_address in targets:
        if fallback_address is None:
            logger.warning("user=%s: %s отказал, запасного канала нет — уведомление потеряно",
                           user_id, channel.value)
            continue
        if fallback == NotifyChannel.EMAIL:
            await pool.enqueue_job("send_email", fallback_address, subject, text)
        else:
            await pool.enqueue_job(task_for(fallback), fallback_address, text)
        rerouted += 1
        logger.info("user=%s: %s отказал, уведомление ушло через %s",
                    user_id, channel.value, fallback.value)
    return f"gone:rerouted:{rerouted}"


async def ask_promo_consent(ctx: dict[str, Any], user_id: int) -> str:
    """Разовый вопрос: присылать ли дальше рекламную подборку вечерних окон.

    Отметка «спрашивали» означает «вопрос ДОШЁЛ», а не «пытались отправить».
    Ставим её до отправки — чтобы два параллельных запуска не спросили человека
    дважды, — и снимаем, если вопрос не дошёл: по временной причине или по
    постоянной. Недошедший вопрос повторить можно смело: назойливым может быть
    только то, что человек получил. А отметка у недошедшего навсегда исключила
    бы его из вопроса — на стейдже так и случилось (chat not found).
    """
    from app.db.session import AsyncSessionLocal
    from app.models.models import NotifyChannel, User
    from app.services import ad_consent
    from app.services.notify_channel import resolve

    async with AsyncSessionLocal() as db:
        # Блокируем строку пользователя до коммита отметки: две задачи для
        # одного человека, стартовавшие одновременно, иначе обе прочитали бы
        # «ещё не спрашивали» и обе отправили вопрос. Раньше от этого защищал
        # фиксированный _job_id в очереди — но очередь час хранит результат и
        # молча отбрасывала законный повтор после недошедшего вопроса.
        user = await db.get(User, user_id, with_for_update=True)
        if user is None or user.is_guest:
            return "skipped:no-user"
        if ad_consent.was_asked(user):
            return "skipped:already-asked"
        if ad_consent.is_consented(user):
            return "skipped:already-consented"
        channel, address = resolve(user)
        if address is None:
            return "skipped:no-channel"

        ad_consent.mark_asked(user)
        await db.commit()

        delivered = True
        try:
            if channel == NotifyChannel.TG:
                delivered = await _send_via_telegram(address, ad_consent.QUESTION_TEXT, reply_markup={
                    "inline_keyboard": [[{"text": ad_consent.OPT_IN_LABEL, "callback_data": "adc:yes"}]],
                })
            elif channel == NotifyChannel.MAX:
                from maxapi.types.attachments.buttons.callback_button import CallbackButton
                from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

                kb = InlineKeyboardBuilder()
                kb.row(CallbackButton(text=ad_consent.OPT_IN_LABEL, payload="adc:yes"))
                delivered = await _send_via_max(address, ad_consent.QUESTION_TEXT, attachments=[kb.as_markup()])
            elif channel == NotifyChannel.VK:
                from app.services import vk_api

                delivered = await _send_via_vk(address, ad_consent.QUESTION_TEXT, vk_api.inline_keyboard(
                    [[vk_api.callback_button(ad_consent.OPT_IN_LABEL, "adc:yes", "positive")]]))
            elif channel == NotifyChannel.EMAIL:
                from app.core.config import settings

                link = (f"{settings.PUBLIC_BASE_URL.rstrip('/')}/consent/promo"
                        f"?t={ad_consent.make_token(user.id)}")
                # Ссылка открывает страницу с кнопкой, а не записывает согласие
                # по переходу: почтовые сканеры открывают ссылки из писем сами.
                body = (f"{ad_consent.QUESTION_TEXT}\n\n"
                        f"Чтобы получать подборку, откройте страницу и нажмите кнопку:\n{link}")
                delivered = await _send_via_smtp(address, "Сообщения об акциях и конкурсах — Руми", body)
            else:
                return "skipped:unknown-channel"
        except TransientTaskError as exc:
            ad_consent.unmark_asked(user)
            await db.commit()
            logger.warning("ask_promo_consent user=%s: временный сбой: %s", user_id, exc)
            raise _retry(ctx, exc) from exc
        except RecipientGone:
            # Помечаем канал, но вопрос о рекламе запасным каналом НЕ дошлём:
            # это не уведомление, которое человек ждёт. Следующий запуск задачи
            # сам спросит через рабочий канал — отметку «спрашивали» снимаем.
            ad_consent.unmark_asked(user)
            await db.commit()
            from app.services.notify_channel import mark_broken

            await mark_broken(db, channel, address)
            logger.warning("ask_promo_consent user=%s: %s недоступен",
                           user_id, channel.value)
            return f"undelivered:{channel.value}"

        if not delivered:
            ad_consent.unmark_asked(user)
            await db.commit()
            logger.warning(
                "ask_promo_consent user=%s: НЕ ДОШЛО через %s — отметку сняли",
                user_id, channel.value,
            )
            return f"undelivered:{channel.value}"

    logger.info("ask_promo_consent user=%s: спросили через %s", user_id, channel.value)
    return f"asked:{channel.value}"


async def send_max_message(ctx: dict[str, Any], chat_id: int, text: str) -> str:
    """Уведомление в MAX вне запроса — зеркало send_tg_message."""
    from app.models.models import NotifyChannel

    try:
        await _send_via_max(chat_id, text)
    except RecipientGone:
        try:
            return await _reroute_after_refusal(NotifyChannel.MAX, chat_id, text)
        except TransientTaskError as exc:
            raise _retry(ctx, exc) from exc
    except TransientTaskError as exc:
        logger.warning(
            "send_max_message chat=%s: временный сбой (попытка %d): %s",
            chat_id, ctx["job_try"], exc,
        )
        raise _retry(ctx, exc) from exc
    logger.info("send_max_message chat=%s: отправлено (попытка %d)", chat_id, ctx["job_try"])
    return "sent"


async def send_vk_message(ctx: dict[str, Any], peer_id: int, text: str) -> str:
    """Уведомление во ВКонтакте вне запроса — зеркало send_tg_message."""
    from app.models.models import NotifyChannel

    try:
        await _send_via_vk(peer_id, text)
    except RecipientGone:
        try:
            return await _reroute_after_refusal(NotifyChannel.VK, peer_id, text)
        except TransientTaskError as exc:
            raise _retry(ctx, exc) from exc
    except TransientTaskError as exc:
        logger.warning("send_vk_message peer=%s: временный сбой (попытка %d): %s",
                       peer_id, ctx["job_try"], exc)
        raise _retry(ctx, exc) from exc
    logger.info("send_vk_message peer=%s: отправлено (попытка %d)", peer_id, ctx["job_try"])
    return "sent"


async def send_tg_message(ctx: dict[str, Any], chat_id: int, text: str) -> str:
    """Уведомление в Telegram вне запроса (записи, напоминания)."""
    from app.models.models import NotifyChannel

    try:
        await _send_via_telegram(chat_id, text)
    except RecipientGone:
        try:
            return await _reroute_after_refusal(NotifyChannel.TG, chat_id, text)
        except TransientTaskError as exc:
            raise _retry(ctx, exc) from exc
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
    from app.services.notifications import TOPIC_PROMOS, wants

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
        if not wants(u, TOPIC_PROMOS):
            continue
        channel, address = _resolve_channel(u)
        if address is None:
            continue
        if channel == _NC.EMAIL:
            await pool.enqueue_job("send_email", address, "Вечерние окна со скидкой — Руми", text)
        else:
            from app.services.notify_channel import task_for

            await pool.enqueue_job(task_for(channel), address, text)
        sent += 1
    logger.info("send_evening_deals_blast: поставлено %d сообщений", sent)
    return f"queued:{sent}"


# ── Email (noreply@rrumi.ru через SMTP Timeweb) ──────────────────


async def _send_via_smtp(to: str, subject: str, body: str, html: Optional[str] = None) -> bool:
    """Единственная точка отправки писем. mock — в лог (dev/до кредов).

    body — текстовый вариант (fallback), html — опциональная HTML-версия
    (add_alternative: почтовые клиенты покажут HTML, но текст останется для
    тех, кто HTML не рендерит). Сетевые сбои и 4xx-коды SMTP (временные) —
    TransientTaskError; постоянные отказы (несуществующий ящик, 5xx) не ретраим.
    """
    from app.core.config import settings

    if settings.EMAIL_MODE == "mock" or not settings.SMTP_PASSWORD:
        logger.info("[dev-заглушка email] %s: %s", to, subject)
        return True

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
        return False
    except (aiosmtplib.SMTPException, OSError) as exc:
        raise TransientTaskError(f"SMTP: {exc}") from exc
    return True


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

    from app.db.session import AsyncSessionLocal as _Sessions
    from app.services.receipts import verification_receipt

    async with _Sessions() as db:
        model_cls = Salon if kind == "business" else User
        tgt = await db.get(model_cls, target_id)
        from app.api.v1.endpoints.payments import _receipt_contacts
        r_email, r_phone = await _receipt_contacts(db, tgt, kind) if tgt else (None, None)

    try:
        await client.cancel(
            payment_id=provider_payment_id, amount_rub=Decimal("1.00"),
            # На фискализированном терминале касса должна пробить чек возврата
            receipt=verification_receipt(
                amount_rub=Decimal("1.00"), email=r_email, phone=r_phone,
            ),
        )
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
            from app.services.subscription import settle_proration
            monthly = amount  # до доплаты — отдельной строкой в чеке
            amount = (amount + Decimal(str(settle_proration(target)))).quantize(Decimal("0.01"))
            target.subscription_amount = float(amount)
        else:
            amount = Decimal(str(target.subscription_amount or 0))
            if amount <= 0:
                logger.error("charge_due_subscriptions: %s %s без subscription_amount, пропуск", kind, target.id)
                continue
            plan = target.subscription_tier.value if target.subscription_tier else ""
            monthly = amount

        payment = Payment(
            plan=plan or "", kind=PaymentKind.RECURRENT, amount=float(amount),
            invoice_id=uuid.uuid4().hex,
            **({"salon_id": target.id} if kind == "business" else {"user_id": target.id}),
        )
        db.add(payment)
        await db.flush()

        from app.api.v1.endpoints.payments import _plan_title, _receipt_contacts
        from app.services.receipts import subscription_receipt

        plan_title = _plan_title(plan)
        email, phone = await _receipt_contacts(db, target, kind)
        payment.receipt_status = "pending" if (email or phone) else "none"
        try:
            init_result = await client.init(
                order_id=payment.invoice_id, amount_rub=amount,
                description=f"Автопродление тарифа «{plan_title}» — Руми",
                notification_url=notification_url, success_url=return_url, fail_url=return_url,
                receipt=subscription_receipt(
                    total_rub=amount, monthly_rub=monthly, months=1,
                    plan_title=plan_title, email=email, phone=phone,
                ),
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
            if kind == "business" and target.hidden_reason == "billing":
                # Страховка на случай салонов, скрытых за неоплату старым
                # механизмом: доступ теперь держит access_until, поэтому просто
                # снимаем флаг, чтобы он не путал причину скрытия.
                target.is_hidden = False
                target.hidden_reason = None
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


async def check_pending_receipts(ctx: dict[str, Any]) -> str:
    """Кассовый чек пробит или нет — ночная проверка (крон).

    Оплата и фискализация — разные вещи: деньги могут списаться, а чек не
    пробиться (кончилась смена, недоступен ОФД, касса не приняла позицию).
    Отдельного уведомления «чек не удался» Т-Касса не шлёт, поэтому смотрим
    с другой стороны: платёж успешен давно, а фискальных реквизитов мы так и
    не увидели. Это наше нарушение 54-ФЗ, о котором иначе никто не узнает,
    пока не придёт проверка — поэтому зовём админов.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.models import Payment, PaymentStatus

    now = datetime.now(timezone.utc)
    # Час форы: чек пробивается за секунды, но уведомление может задержаться.
    stale_before = now - timedelta(hours=RECEIPT_GRACE_HOURS)

    async with AsyncSessionLocal() as db:
        stale = (await db.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.SUCCEEDED,
                Payment.receipt_status == "pending",
                Payment.paid_at.isnot(None),
                Payment.paid_at < stale_before,
                Payment.paid_at > now - timedelta(days=RECONCILE_WINDOW_DAYS),
            ).order_by(Payment.paid_at.desc()).limit(RECONCILE_MAX_PER_RUN)
        )).scalars().all()

        if not stale:
            return "stale:0"

        for payment in stale:
            payment.receipt_status = "failed"

        from app.services.notifications import notify_admins
        orders = ", ".join(str(p.invoice_id) for p in stale[:20])
        await notify_admins(
            db, f"Кассовый чек не пробит: {len(stale)} платеж(ей)",
            f"По этим платежам деньги приняты, но фискальных реквизитов от кассы "
            f"так и не пришло: {orders}. Проверьте в кабинете Т-Кассы состояние "
            f"кассы и ОФД — по 54-ФЗ чек обязателен.",
        )
        await db.commit()

    logger.error("check_pending_receipts: чек не пробит по %d платежам", len(stale))
    return f"stale:{len(stale)}"


async def send_review_request_tg(ctx: dict[str, Any], chat_id: int,
                                 booking_id: int, question: str) -> str:
    """Вопрос об отзыве со звёздами-кнопками. Нажатие ловит tg-бот (rev:*)."""
    stars = [
        {"text": "★" * n, "callback_data": f"rev:{booking_id}:{n}"}
        for n in range(1, 6)
    ]
    markup = {"inline_keyboard": [stars[:3], stars[3:]]}
    try:
        await _send_via_telegram(chat_id, f"⭐ {question}", reply_markup=markup)
    except RecipientGone:
        # Звёзды-кнопки есть только в Telegram, дослать их некуда — но канал
        # помечаем, чтобы следующие уведомления шли запасным.
        await _mark_channel_broken("tg", chat_id)
        return "gone"
    except TransientTaskError as exc:
        logger.warning("send_review_request_tg %s: временный сбой: %s", chat_id, exc)
        raise Retry(defer=ctx["job_try"] * 30)
    return "sent"


async def send_review_request_vk(ctx: dict[str, Any], peer_id: int,
                                 booking_id: int, question: str) -> str:
    """Вопрос об отзыве со звёздами во ВКонтакте. Нажатие ловит vk-бот (rev:*)."""
    from app.services import vk_api

    stars = [vk_api.callback_button("★" * n, f"rev:{booking_id}:{n}") for n in range(1, 6)]
    try:
        await _send_via_vk(peer_id, f"⭐ {question}", vk_api.inline_keyboard([stars[:3], stars[3:]]))
    except RecipientGone:
        await _mark_channel_broken("vk", peer_id)
        return "gone"
    except TransientTaskError as exc:
        logger.warning("send_review_request_vk %s: временный сбой: %s", peer_id, exc)
        raise Retry(defer=ctx["job_try"] * 30)
    return "sent"


SERVICE_RATING_TEXT = (
    "Вы уже пару недель с Руми. Насколько вам удобно работать в сервисе?\n"
    "1 — совсем неудобно, 5 — всё отлично. После оценки можно дописать, "
    "чего не хватает."
)


async def ask_service_rating(ctx: dict[str, Any]) -> str:
    """Раз в сутки спросить владельцев салонов, как им сам сервис.

    Спрашиваем один раз и не сразу: через SERVICE_RATING_AFTER_DAYS после
    подключения, когда человек уже успел поработать в панели. Повторно не
    беспокоим — признак «уже спрашивали» это наличие NPS-обращения от него.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.core.worker import get_arq_pool
    from app.db.session import AsyncSessionLocal
    from app.models.models import (
        NotifyChannel, Salon, SalonModerationStatus, SupportRequest, SupportTopic, User,
    )
    from app.services.notify_channel import resolve

    now = datetime.now(timezone.utc)
    ripe_before = now - timedelta(days=SERVICE_RATING_AFTER_DAYS)

    async with AsyncSessionLocal() as db:
        salons = (await db.execute(
            select(Salon).where(
                Salon.moderation_status == SalonModerationStatus.APPROVED,
                Salon.is_active == True,  # noqa: E712
                Salon.published_at.isnot(None),
                Salon.published_at <= ripe_before,
            )
        )).scalars().all()
        if not salons:
            return "asked:0"

        asked_ids = set((await db.execute(
            select(SupportRequest.user_id).where(SupportRequest.topic == SupportTopic.NPS)
        )).scalars().all())

        pool = await get_arq_pool()
        asked = 0
        seen: set[int] = set()
        for salon in salons:
            owner_id = salon.creator_id
            if not owner_id or owner_id in asked_ids or owner_id in seen:
                continue
            seen.add(owner_id)

            owner = await db.get(User, owner_id)
            if owner is None:
                continue
            channel, address = resolve(owner)
            task = {NotifyChannel.TG: "send_service_rating_tg",
                    NotifyChannel.VK: "send_service_rating_vk"}.get(channel)
            if task is None or not address:
                # Кнопки с оценкой умеют tg- и vk-боты. Остальным не пишем
                # вовсе: опрос без способа ответить — просто спам.
                continue

            await pool.enqueue_job(task, int(address), _job_id=f"nps:{owner_id}")
            asked += 1

    logger.info("ask_service_rating: опрошено владельцев %d", asked)
    return f"asked:{asked}"


async def send_service_rating_tg(ctx: dict[str, Any], chat_id: int) -> str:
    """Вопрос об оценке сервиса. Нажатие ловит tg-бот (nps:*)."""
    buttons = [
        {"text": str(n), "callback_data": f"nps:{n}"} for n in range(1, 6)
    ]
    markup = {"inline_keyboard": [buttons]}
    try:
        await _send_via_telegram(chat_id, SERVICE_RATING_TEXT, reply_markup=markup)
    except RecipientGone:
        await _mark_channel_broken("tg", chat_id)
        return "gone"
    except TransientTaskError as exc:
        logger.warning("send_service_rating_tg %s: временный сбой: %s", chat_id, exc)
        raise Retry(defer=ctx["job_try"] * 60)
    return "sent"


async def send_service_rating_vk(ctx: dict[str, Any], peer_id: int) -> str:
    """Вопрос об оценке сервиса во ВКонтакте. Нажатие ловит vk-бот (nps:*)."""
    from app.services import vk_api

    buttons = [vk_api.callback_button(str(n), f"nps:{n}") for n in range(1, 6)]
    try:
        await _send_via_vk(peer_id, SERVICE_RATING_TEXT, vk_api.inline_keyboard([buttons]))
    except RecipientGone:
        await _mark_channel_broken("vk", peer_id)
        return "gone"
    except TransientTaskError as exc:
        logger.warning("send_service_rating_vk %s: временный сбой: %s", peer_id, exc)
        raise Retry(defer=ctx["job_try"] * 60)
    return "sent"


async def ask_for_review(ctx: dict[str, Any], booking_id: int) -> str:
    """Через два часа после визита спросить у клиента отзыв.

    Отзывы у нас были, а просить их было некому — оттого у салонов и висело
    «0 отзывов». Спрашиваем только по факту отметки «Пришёл»: такой отзыв
    сразу идёт как подтверждённый визитом.

    Кнопки со звёздами понимают Telegram и ВКонтакте — в MAX и на почту уходит
    ссылка на страницу салона: рисовать там свой сценарий оценки ради одного
    вопроса не стоит.
    """
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.worker import get_arq_pool
    from app.db.session import AsyncSessionLocal
    from app.models.models import (
        Booking, BookingStatus, Master, NotifyChannel, Salon, User,
    )
    from app.services.bot_actions import review_already_left
    from app.services.notify_channel import resolve

    async with AsyncSessionLocal() as db:
        booking = (await db.execute(
            select(Booking).where(Booking.id == booking_id)
        )).scalar_one_or_none()
        if booking is None or booking.status != BookingStatus.COMPLETED:
            return "skipped"  # запись отменили или переотметили
        if await review_already_left(db, booking.client_id, booking_id):
            return "already"

        client = await db.get(User, booking.client_id)
        if client is None:
            return "skipped"

        master = (await db.execute(
            select(Master).where(Master.id == booking.master_id)
        )).scalar_one_or_none()
        salon = await db.get(Salon, master.salon_id) if master else None
        salon_name = salon.name if salon else "салоне"

        channel, address = resolve(client)
        if channel == NotifyChannel.NONE or not address:
            return "no_channel"

        question = f"Как всё прошло в «{salon_name}»? Оцените визит — это займёт секунду."

        pool = await get_arq_pool()
        if channel in (NotifyChannel.TG, NotifyChannel.VK):
            # Звёзды кнопками умеют tg- и vk-боты (нажатия ловит их polling).
            task = ("send_review_request_tg" if channel == NotifyChannel.TG
                    else "send_review_request_vk")
            await pool.enqueue_job(task, int(address), booking_id, question)
        else:
            base = settings.PUBLIC_BASE_URL.rstrip("/")
            link = f"{base}/salons/{salon.id}" if salon else base
            from app.services.notifications import deliver

            await deliver(
                client, f"⭐ {question}\nОставить отзыв: {link}",
                subject="Как прошёл визит? — Руми",
            )
        return "asked"


async def reconcile_refunds(ctx: dict[str, Any]) -> str:
    """Сверка возвратов с кассой — страховка на случай, если уведомление о
    возврате до нас не дошло (касса не прислала, вебхук лежал, приложение
    перезапускалось). Т-Касса ретраит доставку, но полагаться в деньгах
    только на неё нельзя: незамеченный возврат = бесплатный доступ.

    Раз в сутки берём недавние успешные платежи и спрашиваем GetState. Если
    касса говорит, что деньги вернули, применяем то же правило, что и вебхук
    (app/services/refunds.py) — повторно оно не сработает, платёж уже будет
    помечен REFUNDED.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.models import Payment, PaymentStatus
    from app.services.refunds import REFUND_STATUSES, apply_refund
    from app.services.tkassa import TKassaClient, TKassaError

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=RECONCILE_WINDOW_DAYS)

    async with AsyncSessionLocal() as db:
        payments = (await db.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.SUCCEEDED,
                Payment.provider_transaction_id.isnot(None),
                Payment.paid_at >= since,
            ).order_by(Payment.paid_at.desc()).limit(RECONCILE_MAX_PER_RUN)
        )).scalars().all()

        if not payments:
            return "checked:0"

        try:
            client = TKassaClient()
        except TKassaError as exc:
            logger.error("reconcile_refunds: клиент недоступен: %s", exc)
            return "rejected"

        from app.api.v1.endpoints.payments import _target_for_payment

        found = 0
        for payment in payments:
            # Один сбойный платёж не должен обрывать сверку остальных
            try:
                status = await client.get_state(
                    payment_id=str(payment.provider_transaction_id),
                )
            except TKassaError as exc:
                logger.warning("reconcile_refunds: GetState по платежу id=%s: %s",
                               payment.id, exc)
                continue

            if status not in REFUND_STATUSES:
                continue

            if status == "PARTIAL_REFUNDED":
                # GetState отдаёт только статус — сколько именно вернули, из
                # него не узнать, а угадывать долю в деньгах нельзя. Зовём
                # человека вместо того, чтобы списать наугад.
                logger.error(
                    "reconcile_refunds: частичный возврат по платежу id=%s "
                    "(OrderId=%s) — нужна ручная проверка",
                    payment.id, payment.invoice_id,
                )
                from app.services.notifications import notify_admins
                await notify_admins(
                    db, "Частичный возврат не применён",
                    f"Платёж #{payment.id} (OrderId {payment.invoice_id}) возвращён "
                    f"частично, уведомление от кассы не дошло. Сумму возврата "
                    f"надо посмотреть в кабинете Т-Кассы и поправить доступ вручную.",
                )
                continue

            target, kind = await _target_for_payment(db, payment)
            if target is None:
                continue

            applied = await apply_refund(db, payment, target, kind, 1.0)
            if applied:
                found += 1
                logger.warning(
                    "reconcile_refunds: возврат замечен только сверкой "
                    "(платёж id=%s, OrderId=%s): %s",
                    payment.id, payment.invoice_id, applied,
                )

        await db.commit()

    logger.info("reconcile_refunds: проверено %d, применено возвратов %d",
                len(payments), found)
    return f"checked:{len(payments)};refunded:{found}"


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
