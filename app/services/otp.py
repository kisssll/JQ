# app/services/otp.py
"""Подтверждение телефона: кодом (SMS/flash-call) или через Telegram-бота.

Код и его состояние живут только в Redis (TTL) — «положили, сравнили,
стёрли», отдельная БД/сервис для этого не нужны. Ранее логика была вынесена
в отдельный микросервис (otp-service); при единственном потребителе (это
приложение) лишний контейнер/БД/секрет только добавляли точку отказа, без
выигрыша в изоляции — поэтому код вернулся внутрь.

Telegram-канал (блок 18): вместо кода запись со status=pending; бот
(app/tg_bot.py) после «Поделиться контактом» переводит её в confirmed —
verify_code для таких записей проверяет статус и совпадение номера,
код не участвует. Запись одноразовая, как и у SMS.
"""
import hashlib
import secrets
import uuid

from app.core.config import settings
from app.core.limiter import get_redis
from app.services.sms_provider import send_otp_code


class OTPError(Exception):
    """Хранилище кодов недоступно или код не удалось отправить."""


def _mask_phone(phone: str) -> str:
    return phone[:-4] + "**" + phone[-2:] if len(phone) > 6 else phone


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _key(request_id: str) -> str:
    return f"otp:{request_id}"


async def send_code(phone: str) -> dict:
    """Генерирует код, кладёт его хеш в Redis с TTL и отправляет через SMS-провайдер."""
    if not settings.OTP_ENABLED:
        # Временный обход (см. Settings.OTP_ENABLED) — провайдер ещё не подключён.
        return {
            "request_id": "otp-disabled",
            "masked_phone": _mask_phone(phone),
            "expires_in_seconds": settings.OTP_TTL_MINUTES * 60,
        }

    code = "".join(str(secrets.randbelow(10)) for _ in range(settings.OTP_LENGTH))
    request_id = str(uuid.uuid4())

    try:
        r = get_redis()
        key = _key(request_id)
        await r.hset(
            key,
            mapping={
                "phone_hash": _hash(phone),
                "code_hash": _hash(code + phone),
                "attempts": 0,
            },
        )
        await r.expire(key, settings.OTP_TTL_MINUTES * 60)
    except Exception as e:
        raise OTPError(f"Хранилище кодов недоступно: {e}") from e

    if not await send_otp_code(phone, code, settings.OTP_METHOD):
        raise OTPError("Не удалось отправить код")

    return {
        "request_id": request_id,
        "masked_phone": _mask_phone(phone),
        "expires_in_seconds": settings.OTP_TTL_MINUTES * 60,
        # Код в открытом виде — ТОЛЬКО в mock-режиме и НИКОГДА в production
        # (вторая линия к guard'у в config: иначе код на чужой номер получает
        # любой, кто его запросил). Для разработки/smoke-тестов.
        "dev_code": code
        if settings.SMS_MODE == "mock" and settings.ENVIRONMENT != "production"
        else None,
    }


TG_STATUS_PENDING = "pending"
TG_STATUS_CONFIRMED = "confirmed"

# Каналы-мессенджеры: у обоих одна механика — бот просит «Поделиться
# контактом», платформа отдаёт верифицированный номер, код не участвует.
MESSENGER_CHANNELS = ("telegram", "max")


def messenger_deep_link(channel: str, request_id: str) -> str:
    """Ссылка, открывающая бота канала с токеном верификации."""
    if channel == "telegram":
        return f"https://t.me/{settings.TG_BOT_USERNAME}?start={request_id}"
    return f"https://max.ru/{settings.MAX_BOT_USERNAME}?start={request_id}"


async def start_messenger_verification(phone: str, channel: str) -> dict:
    """Создаёт ожидающую запись для подтверждения через бота мессенджера.

    request_id (uuid4) — одновременно и токен deep link'а: энтропии больше,
    чем у SMS-кода, живёт OTP_TTL_MINUTES и одноразов.
    """
    if channel not in MESSENGER_CHANNELS:
        raise OTPError(f"Неизвестный канал подтверждения: {channel}")

    request_id = str(uuid.uuid4())
    try:
        r = get_redis()
        key = _key(request_id)
        await r.hset(
            key,
            mapping={
                "phone_hash": _hash(phone),
                "channel": channel,
                "status": TG_STATUS_PENDING,
                "attempts": 0,
            },
        )
        await r.expire(key, settings.OTP_TTL_MINUTES * 60)
    except Exception as e:
        raise OTPError(f"Хранилище кодов недоступно: {e}") from e

    return {
        "request_id": request_id,
        "deep_link": messenger_deep_link(channel, request_id),
        "masked_phone": _mask_phone(phone),
        "expires_in_seconds": settings.OTP_TTL_MINUTES * 60,
    }


async def start_tg_verification(phone: str) -> dict:
    """Совместимость: телеграмовский канал через общий механизм."""
    return await start_messenger_verification(phone, "telegram")


def _tg_chat_key(phone: str) -> str:
    return f"otp:tg-chat:{_hash(phone)}"


async def save_tg_chat_id(phone_hash: str, chat_id: int) -> None:
    """Бот запоминает chat_id подтвердившего номер (ключ по хешу телефона).

    Живёт 1 час: за это время пользователь должен успеть дорегистрироваться —
    тогда pop_tg_chat_id() перенесёт привязку в users.tg_chat_id.
    """
    try:
        r = get_redis()
        await r.set(f"otp:tg-chat:{phone_hash}", chat_id, ex=3600)
    except Exception as e:
        raise OTPError(f"Хранилище кодов недоступно: {e}") from e


async def pop_tg_chat_id(phone: str) -> int | None:
    """Забирает (одноразово) chat_id, сохранённый ботом при подтверждении.

    Ошибки Redis глотаем: привязка Telegram — приятный бонус, а не условие
    регистрации; не привязалось сейчас — привяжется через /start в боте.
    """
    try:
        r = get_redis()
        key = _tg_chat_key(phone)
        value = await r.get(key)
        if value is None:
            return None
        await r.delete(key)
        return int(value)
    except Exception:
        return None


def _max_chat_key(phone: str) -> str:
    return f"otp:max-chat:{_hash(phone)}"


async def save_max_chat_id(phone_hash: str, chat_id: int) -> None:
    """Зеркало save_tg_chat_id для MAX: бот запоминает chat_id подтвердившего
    номер, регистрация переносит его в users.max_chat_id (pop_max_chat_id)."""
    try:
        r = get_redis()
        await r.set(f"otp:max-chat:{phone_hash}", chat_id, ex=3600)
    except Exception as e:
        raise OTPError(f"Хранилище кодов недоступно: {e}") from e


async def pop_max_chat_id(phone: str) -> int | None:
    """Зеркало pop_tg_chat_id для MAX. Ошибки Redis глотаем — привязка бонус,
    а не условие регистрации."""
    try:
        r = get_redis()
        key = _max_chat_key(phone)
        value = await r.get(key)
        if value is None:
            return None
        await r.delete(key)
        return int(value)
    except Exception:
        return None


async def get_tg_status(request_id: str) -> str:
    """pending | confirmed | not_found (нет записи, истекла или не мессенджер).

    Имя историческое (первый канал был Telegram) — обслуживает оба канала.
    """
    try:
        r = get_redis()
        record = await r.hgetall(_key(request_id))
    except Exception as e:
        raise OTPError(f"Хранилище кодов недоступно: {e}") from e

    if not record or record.get("channel") not in MESSENGER_CHANNELS:
        return "not_found"
    return record.get("status", TG_STATUS_PENDING)


async def verify_code(request_id: str, code: str, phone: str) -> bool:
    """True, если подтверждение валидно: верный код (SMS) либо confirmed (TG).

    Успешная проверка одноразовая — запись сразу удаляется из Redis.
    """
    if not settings.OTP_ENABLED:
        return True

    try:
        r = get_redis()
        key = _key(request_id)
        record = await r.hgetall(key)
    except Exception as e:
        raise OTPError(f"Хранилище кодов недоступно: {e}") from e

    if not record or record.get("phone_hash") != _hash(phone):
        return False  # не найден, истёк по TTL или не тот номер

    if record.get("channel") in MESSENGER_CHANNELS:
        # Подтверждение делает бот (контакт принадлежит отправителю и номер
        # совпал) — здесь достаточно статуса; код в этих каналах не участвует.
        if record.get("status") == TG_STATUS_CONFIRMED:
            await r.delete(key)
            return True
        return False

    if int(record.get("attempts", 0)) >= settings.MAX_VERIFY_ATTEMPTS:
        await r.delete(key)
        return False

    if record.get("code_hash") == _hash(code + phone):
        await r.delete(key)
        return True

    await r.hincrby(key, "attempts", 1)
    return False
