"""Обращения в поддержку из ботов.

Один модуль на оба мессенджера: Telegram и MAX отличаются только тем, как
достать текст и скачать фото, а правила приёма, лимиты и уведомления у них
общие. Разъехавшиеся правила в двух ботах — это когда в одном спам ловится,
а в другом нет.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from app.models.models import (
    NotifyChannel, SupportRequest, SupportStatus, SupportTopic, User,
)

logger = logging.getLogger(__name__)

# Сколько обращений с одного чата принимаем в час. Канал открыт всем и берёт
# файлы — без потолка это приглашение залить нам хранилище.
RATE_LIMIT_PER_HOUR = 3
_RATE_WINDOW_SEC = 3600

# «привет» тикетом быть не должен, но и придираться к «не могу войти» нельзя.
MIN_TEXT_LEN = 10
MAX_TEXT_LEN = 4000
MAX_PHOTOS = 5

TOPIC_LABELS: dict[SupportTopic, str] = {
    SupportTopic.QUESTION: "Вопрос",
    SupportTopic.BUG: "Не работает",
    SupportTopic.COMPLAINT: "Жалоба на салон",
    SupportTopic.IDEA: "Предложение",
    SupportTopic.NPS: "Оценка сервиса",
}

STATUS_LABELS: dict[SupportStatus, str] = {
    SupportStatus.NEW: "Новое",
    SupportStatus.IN_PROGRESS: "В работе",
    SupportStatus.CLOSED: "Закрыто",
}


class RateLimited(Exception):
    """Лимит обращений исчерпан — вызывающий показывает вежливый отказ."""


def _rate_key(channel: NotifyChannel, chat_id: int) -> str:
    return f"support:rate:{channel.value}:{chat_id}"


async def check_rate_limit(channel: NotifyChannel, chat_id: int) -> None:
    """Считает обращения в скользящем часе. Redis недоступен — пропускаем:
    потерять обращение хуже, чем пропустить лишнее (fail-open, как и в
    локауте по логину)."""
    from app.core.limiter import get_redis

    try:
        r = get_redis()
        key = _rate_key(channel, chat_id)
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, _RATE_WINDOW_SEC)
        if count > RATE_LIMIT_PER_HOUR:
            raise RateLimited
    except RateLimited:
        raise
    except Exception:
        logger.warning("support: лимит не проверен (Redis недоступен)")


def validate_text(text: str) -> Optional[str]:
    """None — годится, иначе текст ошибки для человека."""
    cleaned = (text or "").strip()
    if len(cleaned) < MIN_TEXT_LEN:
        return (f"Опишите, пожалуйста, подробнее — хотя бы {MIN_TEXT_LEN} символов. "
                "Так мы поймём, чем помочь.")
    if len(cleaned) > MAX_TEXT_LEN:
        return f"Слишком длинно: уместите в {MAX_TEXT_LEN} символов."
    return None


def store_photo(data: bytes) -> Optional[str]:
    """Картинка из бота → наше хранилище. None, если не вышло.

    Гоняем через тот же process_image, что и загрузки с сайта: он же
    обрезает размер и вычищает метаданные, а на не-картинке бросит ошибку —
    то есть заодно проверяет, что нам прислали именно изображение.
    """
    from app.services.uploads import _store, process_image

    try:
        return _store(process_image(data, "support"), "support")
    except Exception:
        logger.exception("support: не удалось сохранить фото")
        return None


async def create_request(
    db, *, topic: SupportTopic, text: str, channel: NotifyChannel,
    chat_id: Optional[int] = None, user: Optional[User] = None,
    photos: Optional[Sequence[str]] = None, rating: Optional[int] = None,
    notify: bool = True,
) -> SupportRequest:
    """Сохранить обращение и позвать админов."""
    request = SupportRequest(
        topic=topic, text=(text or "").strip(), channel=channel,
        chat_id=chat_id, user_id=user.id if user else None,
        photos=list(photos) if photos else None, rating=rating,
        status=SupportStatus.NEW,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)

    if notify:
        await _alert_admins(db, request, user)
    return request


async def _alert_admins(db, request: SupportRequest, user: Optional[User]) -> None:
    """Алерт не должен ронять приём обращения: человек своё уже отправил."""
    try:
        from app.services.notifications import notify_admins

        who = "не авторизован"
        if user:
            who = f"{user.full_name or 'без имени'} ({user.phone})"
        preview = request.text[:300] + ("…" if len(request.text) > 300 else "")
        extra = f"\nФото: {len(request.photos)}" if request.photos else ""
        await notify_admins(
            db, f"Обращение №{request.id}: {TOPIC_LABELS[request.topic]}",
            f"От: {who} · из {request.channel.value.upper()}{extra}\n\n{preview}",
        )
    except Exception:
        logger.exception("support: алерт админам не отправлен (обращение %s)", request.id)


async def send_answer(db, request: SupportRequest, answer: str, admin: User) -> bool:
    """Ответ админа → человеку его же каналом. True, если доставили.

    Привязанному отвечаем через deliver() — он сам выберет TG/MAX/почту.
    Непривязанному писать больше некуда, кроме исходного чата, поэтому шлём
    прямо в него.
    """
    from datetime import datetime, timezone

    text = f"Ответ поддержки Руми:\n\n{answer.strip()}"
    delivered = False

    # Только через db.get: обращение к request.user дёрнуло бы ленивую связь
    # синхронно и упало бы с MissingGreenlet — объект приходит из другой сессии.
    author = await db.get(User, request.user_id) if request.user_id else None
    if author is not None:
        from app.services.notifications import deliver

        await deliver(author, f"💬 {text}", subject="Ответ поддержки — Руми")
        delivered = True
    elif request.chat_id:
        delivered = await _send_to_chat(request.channel, request.chat_id, text)

    request.answer = answer.strip()
    request.answered_by_id = admin.id
    request.answered_at = datetime.now(timezone.utc)
    request.status = SupportStatus.CLOSED
    await db.commit()
    return delivered


async def _send_to_chat(channel: NotifyChannel, chat_id: int, text: str) -> bool:
    """Сообщение в чат мессенджера мимо аккаунта — для непривязанных."""
    try:
        from app.core.worker import get_arq_pool

        pool = await get_arq_pool()
        task = "send_tg_message" if channel == NotifyChannel.TG else "send_max_message"
        await pool.enqueue_job(task, chat_id, text)
        return True
    except Exception:
        logger.exception("support: не удалось ответить в чат %s", chat_id)
        return False
