# app/max_bot.py
"""MAX-бот подтверждения номера телефона (блок 18, этап 2).

Запуск: python -m app.max_bot — отдельный контейнер, long polling
(наружу портов нет). Зеркало app/tg_bot.py: контракт с приложением — та же
Redis-запись otp:{request_id} (channel=max), бот переводит pending → confirmed.

Проверки контакта:
- контакт принадлежит отправителю (payload.max_info.user_id == sender_id) —
  пересланный чужой контакт не проходит;
- у собственного контакта из кнопки request_contact платформа проставляет
  hash (подпись) — контакты без него не принимаем;
- номер из vcf совпадает с ожидаемым в записи верификации.
"""
import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.filters.command import CommandStart
from maxapi.filters.contact import Contact as ContactFilter
from maxapi.types.attachments.buttons.request_contact import RequestContactButton
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from app.core.config import settings
from app.core.limiter import get_redis
from app.schemas.user import try_normalize_phone
from app.services.otp import (
    TG_STATUS_CONFIRMED,
    TG_STATUS_PENDING,
    _hash,
    _key,
    _mask_phone,
    save_max_chat_id,
)

logger = logging.getLogger("max_bot")

VERDICT_OK = "ok"
VERDICT_NOT_FOUND = "not_found"
VERDICT_FOREIGN_CONTACT = "foreign_contact"
VERDICT_PHONE_MISMATCH = "phone_mismatch"

_GREETING = (
    "Здравствуйте! Это подтверждение номера для Руми.\n\n"
    "Нажмите кнопку ниже — MAX передаст нам ваш номер, и мы сверим его "
    "с указанным при регистрации. Ничего вводить не нужно."
)


def _pending_key(user_id: int) -> str:
    """Какой request_id сейчас подтверждает этот MAX-пользователь (в Redis —
    состояние переживает рестарт контейнера, TTL как у верификации)."""
    return f"otp:max-pending:{user_id}"


def check_max_contact(
    record: dict,
    contact_user_id,
    sender_id: int,
    contact_phone: str,
    has_hash: bool,
) -> str:
    """Чистая проверка контакта против записи верификации (без SDK — тестируемо)."""
    if (
        not record
        or record.get("channel") != "max"
        or record.get("status") != TG_STATUS_PENDING
    ):
        return VERDICT_NOT_FOUND
    if contact_user_id is None or contact_user_id != sender_id or not has_hash:
        return VERDICT_FOREIGN_CONTACT
    phone = try_normalize_phone(contact_phone or "")
    if not phone or _hash(phone) != record.get("phone_hash"):
        return VERDICT_PHONE_MISMATCH
    return VERDICT_OK


def _contact_kb() -> list:
    kb = InlineKeyboardBuilder()
    kb.row(RequestContactButton(text="📱 Поделиться контактом"))
    return [kb.as_markup()]


async def on_bot_started(event: BotStarted) -> None:
    """Первое открытие бота по deep link'у max.ru/<бот>?start=<request_id>."""
    token = (event.payload or "").strip()
    await _begin(event.bot, event.chat_id, event.user.user_id, token)


async def on_start_command(event: MessageCreated) -> None:
    """/start <request_id> текстом (повторное открытие бота)."""
    body_text = (event.message.body.text or "") if event.message.body else ""
    parts = body_text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else ""
    chat_id, user_id = event.get_ids()
    await _begin(event.bot, chat_id, user_id, token)


async def _begin(bot: Bot, chat_id: int, user_id: int, token: str) -> None:
    r = get_redis()
    record = await r.hgetall(_key(token)) if token else {}
    if not record or record.get("channel") != "max":
        await bot.send_message(
            chat_id=chat_id,
            text="Ссылка устарела или открыта без сайта. Вернитесь на страницу "
                 "регистрации Руми и нажмите «Подтвердить в MAX» ещё раз.",
        )
        return

    await r.set(_pending_key(user_id), token, ex=settings.OTP_TTL_MINUTES * 60)
    await bot.send_message(chat_id=chat_id, text=_GREETING, attachments=_contact_kb())


async def on_contact(event: MessageCreated, contact) -> None:
    chat_id, user_id = event.get_ids()
    r = get_redis()
    token = await r.get(_pending_key(user_id))
    if not token:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Не вижу активного подтверждения. Вернитесь на сайт Руми и "
                 "нажмите «Подтвердить в MAX», затем поделитесь контактом.",
        )
        return

    payload = getattr(contact, "payload", None)
    max_info = getattr(payload, "max_info", None)
    contact_user_id = getattr(max_info, "user_id", None)
    vcf = getattr(payload, "vcf", None)
    contact_phone = getattr(vcf, "phone", None) or ""
    has_hash = bool(getattr(payload, "hash", None))

    record = await r.hgetall(_key(token))
    verdict = check_max_contact(record, contact_user_id, user_id, contact_phone, has_hash)

    if verdict == VERDICT_OK:
        await r.hset(_key(token), "status", TG_STATUS_CONFIRMED)
        await r.delete(_pending_key(user_id))
        # Запоминаем chat_id: регистрация перенесёт его в users.max_chat_id
        # (pop_max_chat_id), и уведомления в MAX заработают сразу. Сбой записи
        # не должен ломать подтверждение номера — привязку можно повторить.
        try:
            await save_max_chat_id(record["phone_hash"], chat_id)
        except Exception:
            logger.warning("max_user=%s: chat_id не сохранён", user_id, exc_info=True)
        logger.info(
            "confirmed: max_user=%s phone=%s",
            user_id, _mask_phone(try_normalize_phone(contact_phone) or ""),
        )
        await event.bot.send_message(
            chat_id=chat_id,
            text="Номер подтверждён ✅\nВернитесь на сайт — регистрация продолжится сама.",
        )
    elif verdict == VERDICT_FOREIGN_CONTACT:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Это чужой контакт — так подтвердить номер нельзя. "
                 "Нажмите кнопку «Поделиться контактом», чтобы отправить свой.",
            attachments=_contact_kb(),
        )
    elif verdict == VERDICT_PHONE_MISMATCH:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Этот MAX привязан к другому номеру — не к тому, что указан "
                 "при регистрации. Проверьте номер на сайте.",
        )
    else:
        await event.bot.send_message(
            chat_id=chat_id,
            text=f"Подтверждение устарело (действует {settings.OTP_TTL_MINUTES} мин). "
                 "Вернитесь на сайт и начните заново.",
        )


async def main() -> None:
    if not settings.MAX_BOT_TOKEN:
        # Как и tg-бот: без токена спим, а не крашлупим (restart: unless-stopped)
        logger.warning(
            "MAX_BOT_TOKEN не задан — бот в режиме ожидания. Задайте токен "
            "в .env и пересоздайте контейнер (up -d --force-recreate max-bot)."
        )
        await asyncio.Event().wait()
        return

    bot = Bot(token=settings.MAX_BOT_TOKEN)
    dp = Dispatcher()
    # Регистрация в стиле maxapi: Event-объект — это фабрика декораторов
    dp.bot_started()(on_bot_started)
    dp.message_created(ContactFilter())(on_contact)
    dp.message_created(CommandStart())(on_start_command)

    logger.info("MAX-бот подтверждения номера запущен (long polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Мониторинг и логи (блок 05): единые логи + трекинг ошибок бота.
    from app.core.observability import init_sentry, setup_logging

    setup_logging()
    init_sentry()
    asyncio.run(main())
