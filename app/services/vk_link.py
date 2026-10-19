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
#: Код короткий и читаемый вслух: его показывают на странице привязки как
#: запасной путь — кнопка «Начать» во ВКонтакте есть только в пустом диалоге,
#: а в непустом её нет, и человек упирается в тупик (жалоба 17.09.2026).
#: Алфавит без похожих символов (0/O, 1/I), чтобы код не набирали с ошибкой.
_CODE_PREFIX = "RUMI-"
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_CODE_LENGTH = 5


def _code_key(code: str) -> str:
    return f"vk:link:{normalize_code(code)}"


def normalize_code(code: str) -> str:
    """«rumi-ab12c», «RUMI AB12C», «ab12c» → «RUMI-AB12C».

    Человек присылает код сообщением и набирает его как получится.
    """
    raw = (code or "").strip().upper().replace(" ", "").replace("—", "-")
    if raw.startswith("RUMI"):
        raw = raw[4:]
    return _CODE_PREFIX + raw.lstrip("-")


def looks_like_code(text: str) -> bool:
    """Похоже ли сообщение на код привязки — чтобы не искать в Redis каждое слово."""
    raw = normalize_code(text)[len(_CODE_PREFIX):]
    return len(raw) == _CODE_LENGTH and all(c in _CODE_ALPHABET for c in raw)


async def create_code(user_id: int) -> str:
    """Одноразовый код привязки для ссылки vk.me/…?ref=КОД."""
    from app.core.limiter import get_redis

    code = _CODE_PREFIX + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    await get_redis().set(_code_key(code), user_id, ex=CODE_TTL_SECONDS)
    return code


async def pop_code(code: str) -> Optional[int]:
    """user_id по коду, код при этом сгорает. None — нет, истёк или уже использован."""
    from app.core.limiter import get_redis

    if not looks_like_code(code):
        return None
    # GETDEL атомарен: два одновременных сообщения с одним кодом не
    # привяжут его дважды.
    value = await get_redis().getdel(_code_key(code))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def linked_user(db, peer_id: int, community) -> Optional[User]:
    """Аккаунт, привязанный к диалогу с ЭТИМ сообществом."""
    return (await db.execute(
        select(User).where(getattr(User, community.peer_field) == peer_id).order_by(User.id)
    )).scalars().first()


async def user_by_vk_id(db, vk_user_id: int) -> Optional[User]:
    """Аккаунт, за которым этот человек ВК уже подтверждён — входом через
    VK ID или привязкой к любому из двух сообществ.

    На этом держится автопривязка ко второму сообществу (решение 0013, п. 5):
    в личном диалоге peer_id и есть id человека ВК, одинаковый в обоих
    сообществах, и приходит он от самого ВК — подделать его в сообщении нельзя.
    Повторный код здесь ничего не проверил бы: это тот же аккаунт ВК.

    Порядок важен, когда отметки разошлись по разным аккаунтам: сначала
    vk_user_id — его переносит на себя последний вход через VK ID, это самое
    свежее «я вот этот»; потом диалоги с сообществами.
    """
    from app.services import vk_community

    user = (await db.execute(
        select(User).where(User.vk_user_id == vk_user_id).order_by(User.id)
    )).scalars().first()
    if user is not None:
        return user
    for community in vk_community.ALL:
        user = await linked_user(db, vk_user_id, community)
        if user is not None:
            return user
    return None


def needs_channel_question(user: User) -> bool:
    """Был рабочий мессенджер — не перебиваем его выбор молча, а спрашиваем."""
    from app.services.notify_channel import is_broken

    current = user.notify_channel or NotifyChannel.NONE
    address = {NotifyChannel.TG: user.tg_chat_id, NotifyChannel.MAX: user.max_chat_id}.get(current)
    return bool(address) and not is_broken(user, current)


async def link(db, user: User, peer_id: int, name: str = "", *, community) -> bool:
    """Привязать диалог с сообществом ВК к аккаунту. → нужно ли спросить про канал.

    Один диалог ВК — один аккаунт: у прежнего владельца привязка к ЭТОМУ
    сообществу снимается, иначе уведомления двух людей сыпались бы в один чат.
    Диалог со вторым сообществом не трогаем — это отдельное разрешение.

    Канал: не было или была почта — становится ВК. Был Telegram или MAX —
    оставляем, бот спросит кнопкой.
    """
    await db.execute(
        update(User)
        .where(getattr(User, community.peer_field) == peer_id, User.id != user.id)
        .values({community.peer_field: None, community.broken_field: None})
    )
    setattr(user, community.peer_field, peer_id)
    if user.vk_user_id is None:
        user.vk_user_id = peer_id   # в личном диалоге peer_id и есть id человека
    user.vk_name = (name or "")[:200] or None
    setattr(user, community.broken_field, None)

    ask = needs_channel_question(user)
    if not ask:
        user.notify_channel = NotifyChannel.VK
    await db.commit()
    logger.info("vk: привязан user=%s peer=%s к сообществу %s (спросить про канал: %s)",
                user.id, peer_id, community.audience.value, ask)
    return ask


async def unlink(db, user: User) -> None:
    """«Отвязать ВКонтакте» на сайте — это один аккаунт ВК, поэтому оба
    сообщества разом."""
    from app.services import vk_community

    for community in vk_community.ALL:
        setattr(user, community.peer_field, None)
        setattr(user, community.broken_field, None)
    user.vk_name = None
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
