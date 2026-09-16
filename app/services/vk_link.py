# app/services/vk_link.py
"""Привязка ВКонтакте к аккаунту Руми.

Подтвердить номер в ВК-боте нельзя: у клавиатуры ВК нет кнопки «поделиться
номером». Поэтому привязка идёт двумя путями, и оба опираются на то, что
человек уже доказал нам, кто он:

1. Вошёл через VK ID — ВК сам сказал нам его vk_user_id (remember_vk_user).
   Написал сообществу — узнаём по from_id и привязываем без вопросов.
2. Вошёл по телефону — в профиле берёт одноразовую ссылку vk.me/…?ref=КОД.
   Код живёт 15 минут, выдаётся только вошедшему и сгорает при первом
   использовании. ВК передаёт ref в первом сообщении после перехода.

Остаточный риск второго пути: переслал ссылку в течение 15 минут — привяжется
чужой ВК. Закрыт тем, что на сайте видно имя привязанного аккаунта и есть
«Отвязать», но не устранён.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from sqlalchemy import select, update

from app.models.models import NotifyChannel, User

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 15 * 60
# Метка ссылки «Написать во ВКонтакте» из подвала: сразу к выбору темы.
REF_SUPPORT = "support"
_CODE_PREFIX = "l"


def _code_key(code: str) -> str:
    return f"vk:link:{code}"


async def create_code(user_id: int) -> str:
    """Одноразовый код привязки для ссылки vk.me/…?ref=КОД."""
    from app.core.limiter import get_redis

    code = _CODE_PREFIX + secrets.token_hex(10)
    await get_redis().set(_code_key(code), user_id, ex=CODE_TTL_SECONDS)
    return code


async def pop_code(code: str) -> Optional[int]:
    """user_id по коду, код при этом сгорает. None — нет, истёк или уже использован."""
    from app.core.limiter import get_redis

    if not code or not code.startswith(_CODE_PREFIX):
        return None
    # GETDEL атомарен: два одновременных сообщения с одним кодом не
    # привяжут его дважды.
    value = await get_redis().getdel(_code_key(code))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def linked_user(db, peer_id: int) -> Optional[User]:
    return (await db.execute(
        select(User).where(User.vk_peer_id == peer_id).order_by(User.id)
    )).scalars().first()


async def user_by_vk_id(db, vk_user_id: int) -> Optional[User]:
    return (await db.execute(
        select(User).where(User.vk_user_id == vk_user_id).order_by(User.id)
    )).scalars().first()


def needs_channel_question(user: User) -> bool:
    """Был рабочий мессенджер — не перебиваем его выбор молча, а спрашиваем."""
    from app.services.notify_channel import is_broken

    current = user.notify_channel or NotifyChannel.NONE
    address = {NotifyChannel.TG: user.tg_chat_id, NotifyChannel.MAX: user.max_chat_id}.get(current)
    return bool(address) and not is_broken(user, current)


async def link(db, user: User, peer_id: int, name: str = "") -> bool:
    """Привязать диалог ВК к аккаунту. → нужно ли спросить про канал.

    Один диалог ВК — один аккаунт: у прежнего владельца привязка снимается,
    иначе уведомления двух людей сыпались бы в один чат.

    Канал: не было или была почта — становится ВК. Был Telegram или MAX —
    оставляем, бот спросит кнопкой.
    """
    await db.execute(
        update(User)
        .where(User.vk_peer_id == peer_id, User.id != user.id)
        .values(vk_peer_id=None, vk_name=None, vk_broken_at=None)
    )
    user.vk_peer_id = peer_id
    if user.vk_user_id is None:
        user.vk_user_id = peer_id   # в личном диалоге peer_id и есть id человека
    user.vk_name = (name or "")[:200] or None
    user.vk_broken_at = None

    ask = needs_channel_question(user)
    if not ask:
        user.notify_channel = NotifyChannel.VK
    await db.commit()
    logger.info("vk: привязан user=%s peer=%s (спросить про канал: %s)", user.id, peer_id, ask)
    return ask


async def unlink(db, user: User) -> None:
    user.vk_peer_id = None
    user.vk_name = None
    user.vk_broken_at = None
    await db.commit()


async def remember_vk_user(db, user: User, vk_user_id) -> None:
    """Запомнить, кто этот человек во ВК, — при входе через VK ID.

    Писать ему бот пока не может: сообщество не пишет первым. Но когда он
    напишет, бот узнает его и привяжет сам. vk_user_id у одного аккаунта:
    вошёл тем же ВК в другой аккаунт — отметка переезжает.
    """
    try:
        vk_user_id = int(vk_user_id)
    except (TypeError, ValueError):
        return
    if user.vk_user_id == vk_user_id:
        return
    await db.execute(
        update(User)
        .where(User.vk_user_id == vk_user_id, User.id != user.id)
        .values(vk_user_id=None)
    )
    user.vk_user_id = vk_user_id
    await db.commit()
