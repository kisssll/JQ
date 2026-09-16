# app/services/notify_channel.py
"""Канал доставки уведомлений: куда слать конкретному пользователю.

До этого модуля доставка была прибита к Telegram: `users.tg_chat_id` был
единственным адресом, а подтвердившийся через MAX не получал уведомлений
вообще (его chat_id никуда не сохранялся). Здесь собрано всё, что отвечает
на три вопроса:

  * куда слать (resolve) — канал пользователя и адрес в нём;
  * есть ли вообще куда слать (has_channel / has_channel_clause) — чтобы
    выборки «кому уведомить» не тащили тех, до кого не достучаться;
  * как канал появляется (bind_after_verification) — чем подтвердил телефон,
    туда и шлём.

Правило деградации: нет мессенджера → пробуем email → иначе доставки нет
(вызывающий код это НЕ роняет, просто уведомление не уходит).

Правило отказа: мессенджер, который отказал насовсем (бот заблокирован, чат
удалён), помечается сломанным (mark_broken) и в resolve() пропускается —
доставка идёт следующим каналом. Привязка при этом остаётся: человек снова
написал боту (clear_broken) — и канал вернулся без повторного подключения.
"""
from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select, update

from app.models.models import NotifyChannel, User

# Задачи arq, доставляющие сообщение в конкретный канал.
_TASK_BY_CHANNEL = {
    NotifyChannel.TG: "send_tg_message",
    NotifyChannel.MAX: "send_max_message",
}

CHANNEL_LABELS = {
    NotifyChannel.NONE: "не подключён",
    NotifyChannel.TG: "Telegram",
    NotifyChannel.MAX: "MAX",
    NotifyChannel.EMAIL: "почта",
}


# Колонка отметки «отказал насовсем» для каждого мессенджера. У почты её нет:
# это последний запасной канал, и уводить с неё некуда.
_BROKEN_FIELD = {
    NotifyChannel.TG: "tg_broken_at",
    NotifyChannel.MAX: "max_broken_at",
}
_ADDRESS_FIELD = {
    NotifyChannel.TG: "tg_chat_id",
    NotifyChannel.MAX: "max_chat_id",
}


def is_broken(user: Optional[User], channel: NotifyChannel) -> bool:
    field = _BROKEN_FIELD.get(channel)
    return bool(user is not None and field and getattr(user, field, None))


def broken_channels(user: Optional[User]) -> list[NotifyChannel]:
    """Привязанные мессенджеры, которые отказали в доставке, — для плашки."""
    return [
        channel for channel in _BROKEN_FIELD
        if _address(user, channel) and is_broken(user, channel)
    ] if user is not None else []


def _address(user: User, channel: NotifyChannel):
    if channel == NotifyChannel.TG:
        return user.tg_chat_id
    if channel == NotifyChannel.MAX:
        return user.max_chat_id
    if channel == NotifyChannel.EMAIL:
        return (user.email or "").strip() or None
    return None


def resolve(user: Optional[User]) -> tuple[NotifyChannel, Optional[object]]:
    """(канал, адрес) для доставки. Выбранный канал уважаем, но если адрес в
    нём пропал (отвязали бота, стёрли почту) или мессенджер отказал насовсем —
    деградируем: мессенджеры → email. Возвращает (NONE, None), если
    достучаться некуда."""
    if user is None:
        return NotifyChannel.NONE, None

    preferred = user.notify_channel or NotifyChannel.NONE
    for channel in (preferred, NotifyChannel.TG, NotifyChannel.MAX, NotifyChannel.EMAIL):
        if channel == NotifyChannel.NONE:
            continue
        address = _address(user, channel)
        if address and not is_broken(user, channel):
            return channel, address
    return NotifyChannel.NONE, None


def has_channel(user: Optional[User]) -> bool:
    """Есть ли рабочий канал доставки — для мягких промптов в интерфейсе."""
    return resolve(user)[0] != NotifyChannel.NONE


def has_channel_clause():
    """SQL-условие «до пользователя реально можно достучаться».

    Пришло на смену `User.tg_chat_id.isnot(None)` в выборках получателей:
    иначе адресаты с MAX/почтой молча выпадали из рассылок.
    """
    return or_(
        and_(User.tg_chat_id.isnot(None), User.tg_broken_at.is_(None)),
        and_(User.max_chat_id.isnot(None), User.max_broken_at.is_(None)),
        User.email.isnot(None),
    )


async def mark_broken(db, channel: NotifyChannel, address) -> list[User]:
    """Пометить мессенджер сломанным у всех, кто привязан к этому чату.

    Отказ приходит на адрес, а не на человека: задачи отправки знают только
    chat_id. Возвращает затронутых пользователей — им нужно дослать
    недошедшее уведомление запасным каналом. Отметку, поставленную раньше, не
    двигаем: дата первого отказа полезнее последней.
    """
    field = _BROKEN_FIELD.get(channel)
    if field is None or address is None:
        return []
    users = (await db.execute(
        select(User).where(getattr(User, _ADDRESS_FIELD[channel]) == address)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for user in users:
        if getattr(user, field) is None:
            setattr(user, field, now)
    if users:
        await db.commit()
    return list(users)


async def clear_broken(db, channel: NotifyChannel, address) -> int:
    """Человек снова написал боту — значит, бот больше не заблокирован."""
    field = _BROKEN_FIELD.get(channel)
    if field is None or address is None:
        return 0
    result = await db.execute(
        update(User)
        .where(getattr(User, _ADDRESS_FIELD[channel]) == address,
               getattr(User, field).isnot(None))
        .values({field: None})
    )
    await db.commit()
    return result.rowcount or 0


def task_for(channel: NotifyChannel) -> Optional[str]:
    """Имя arq-задачи для мессенджер-канала (email уходит своей задачей —
    у неё другая сигнатура: тема + тело)."""
    return _TASK_BY_CHANNEL.get(channel)


async def bind_after_verification(db, user: User, phone: str) -> None:
    """Переносит привязку мессенджера, оставленную ботом при подтверждении
    телефона, в поля пользователя и выставляет канал уведомлений.

    Чем подтвердил — туда и шлём (решение по спеке). Если мессенджер не
    привязался, но есть почта — каналом становится она; иначе NONE, и
    интерфейс покажет мягкий промпт «подключите канал».
    """
    from app.services import otp

    tg_chat_id = await otp.pop_tg_chat_id(phone)
    max_chat_id = await otp.pop_max_chat_id(phone)

    changed = False
    if tg_chat_id:
        user.tg_chat_id = tg_chat_id
        user.tg_broken_at = None   # только что прошёл через бота — значит, доставляется
        user.notify_channel = NotifyChannel.TG
        changed = True
    elif max_chat_id:
        user.max_chat_id = max_chat_id
        user.max_broken_at = None
        user.notify_channel = NotifyChannel.MAX
        changed = True
    elif (user.notify_channel or NotifyChannel.NONE) == NotifyChannel.NONE:
        # Мессенджер не привязан — пусть хотя бы почта, если она есть.
        if (user.email or "").strip():
            user.notify_channel = NotifyChannel.EMAIL
            changed = True

    if changed:
        await db.commit()


async def adopt_oauth_email(db, user: User, email: Optional[str]) -> None:
    """Сохранить почту, полученную при входе через VK/Яндекс, и сделать её
    каналом уведомлений, если другого канала нет.

    Без этого OAuth-пользователь оставался вообще без связи: мессенджер он не
    подключал, а почту провайдер отдавал, но мы её не записывали — уведомления
    молча уходили в никуда. Чужую почту не занимаем: если адрес уже принадлежит
    другому аккаунту, просто пропускаем (email в модели уникален).
    """
    from sqlalchemy import select as _select

    email = (email or "").strip().lower()
    if not email or (user.email or "").strip().lower() == email:
        return

    taken = (await db.execute(
        _select(User.id).where(User.email == email, User.id != user.id)
    )).scalar_one_or_none()
    if taken:
        return

    user.email = email
    if (user.notify_channel or NotifyChannel.NONE) == NotifyChannel.NONE:
        user.notify_channel = NotifyChannel.EMAIL
    await db.commit()
