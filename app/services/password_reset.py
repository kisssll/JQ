# app/services/password_reset.py
"""Сброс пароля (блок 08) — по доступным каналам: Telegram и email.

Токен: secrets.token_urlsafe(32) в Redis, TTL 30 минут, одноразовый;
у пользователя живёт максимум один активный токен (новый запрос гасит
старый). Существование аккаунта не раскрывается: ответ эндпоинта одинаков
для любого номера, отправка (или её отсутствие) — молча.

Доставка — через очередь ARQ: в Telegram привязанным (tg_chat_id),
письмом при наличии email (EMAIL_MODE=live; в mock уходит в лог).
"""
import logging
import secrets

from app.core.config import settings
from app.core.limiter import get_redis
from app.core.worker import get_arq_pool
from app.models.models import User

logger = logging.getLogger(__name__)

RESET_TTL_SECONDS = 30 * 60


def _token_key(token: str) -> str:
    return f"pwreset:{token}"


def _user_key(user_id: int) -> str:
    return f"pwreset:user:{user_id}"


async def issue_token(user: User) -> str:
    """Выпускает одноразовый токен, отзывая предыдущий активный."""
    r = get_redis()
    old = await r.get(_user_key(user.id))
    if old:
        await r.delete(_token_key(old))

    token = secrets.token_urlsafe(32)
    await r.set(_token_key(token), user.id, ex=RESET_TTL_SECONDS)
    await r.set(_user_key(user.id), token, ex=RESET_TTL_SECONDS)
    return token


async def consume_token(token: str) -> int | None:
    """user_id по токену; токен сжигается независимо от дальнейшего успеха."""
    if not token:
        return None
    r = get_redis()
    raw = await r.get(_token_key(token))
    if raw is None:
        return None
    await r.delete(_token_key(token))
    user_id = int(raw)
    await r.delete(_user_key(user_id))
    return user_id


async def deliver(user: User, token: str, host: str) -> None:
    """Ставит доставку ссылки в очередь по всем каналам пользователя.

    Ошибки глотаются с логом (как у уведомлений): ручка «забыли пароль»
    не должна падать из-за недоступной очереди.
    """
    link = f"https://{host}/reset-password?token={token}"
    try:
        pool = await get_arq_pool()
        # Сломанный Telegram пропускаем: ссылка и так уйдёт письмом, а отказ
        # переслал бы её на почту второй раз.
        if user.tg_chat_id and not user.tg_broken_at:
            await pool.enqueue_job(
                "send_tg_message",
                user.tg_chat_id,
                "🔑 Сброс пароля Руми\n"
                f"Перейдите по ссылке (действует 30 минут):\n{link}\n\n"
                "Если это были не вы — просто проигнорируйте сообщение.",
            )
        if user.email:
            await pool.enqueue_job(
                "send_email",
                user.email,
                "Сброс пароля — Руми",
                "Вы (или кто-то другой) запросили сброс пароля на rrumi.ru.\n\n"
                f"Ссылка для смены пароля (действует 30 минут):\n{link}\n\n"
                "Если это были не вы — просто проигнорируйте это письмо, "
                "пароль останется прежним.",
            )
        if not user.tg_chat_id and not user.email:
            logger.info("pwreset: у user=%s нет каналов доставки", user.id)
    except Exception:
        logger.exception("pwreset: не удалось поставить доставку для user=%s", user.id)


async def notify_changed(user: User) -> None:
    """Security-уведомление после успешной смены пароля."""
    try:
        pool = await get_arq_pool()
        if user.tg_chat_id:
            await pool.enqueue_job(
                "send_tg_message", user.tg_chat_id,
                "✅ Пароль вашего аккаунта Руми изменён.\n"
                "Если это были не вы — срочно запросите сброс пароля.",
            )
    except Exception:
        logger.exception("pwreset: notify_changed user=%s", user.id)
