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
from app.services import vk_community

# Задачи arq, доставляющие сообщение в конкретный канал.
_TASK_BY_CHANNEL = {
    NotifyChannel.TG: "send_tg_message",
    NotifyChannel.MAX: "send_max_message",
    NotifyChannel.VK: "send_vk_message",
}

CHANNEL_LABELS = {
    NotifyChannel.NONE: "не подключён",
    NotifyChannel.TG: "Telegram",
    NotifyChannel.MAX: "MAX",
    NotifyChannel.EMAIL: "почта",
    NotifyChannel.VK: "ВКонтакте",
}


# Колонка отметки «отказал насовсем» для каждого мессенджера. У почты её нет:
# это последний запасной канал, и уводить с неё некуда. У ВК колонок две — по
# одной на сообщество (vk_community), поэтому его здесь нет: его поля зависят
# от типа сообщения.
_BROKEN_FIELD = {
    NotifyChannel.TG: "tg_broken_at",
    NotifyChannel.MAX: "max_broken_at",
}
_ADDRESS_FIELD = {
    NotifyChannel.TG: "tg_chat_id",
    NotifyChannel.MAX: "max_chat_id",
}
_MESSENGERS = (NotifyChannel.TG, NotifyChannel.MAX, NotifyChannel.VK)


def _fields(channel: NotifyChannel, audience) -> tuple[Optional[str], Optional[str]]:
    """(поле адреса, поле отметки отказа) канала для сообщения этого типа."""
    if channel == NotifyChannel.VK:
        if audience is None:
            # Отметить или снять отказ «во ВК вообще» нельзя: отказало
            # конкретное сообщество, и второе из-за него гасить нельзя.
            raise ValueError("ВК: не указано, какое сообщество (клиентское или бизнесовое)")
        community = vk_community.get(audience)
        return community.peer_field, community.broken_field
    return _ADDRESS_FIELD.get(channel), _BROKEN_FIELD.get(channel)


def _linked_vk(user: User) -> list:
    """Сообщества, с которыми у человека есть диалог."""
    return [c for c in vk_community.ALL if getattr(user, c.peer_field, None)]


def is_broken(user: Optional[User], channel: NotifyChannel, audience=None) -> bool:
    """Отказал ли канал. Для ВК без audience — отказало ли хоть одно из
    привязанных сообществ: это вопрос интерфейса («есть ли что чинить»), а
    доставка всегда спрашивает про своё сообщество."""
    if user is None:
        return False
    if channel == NotifyChannel.VK and audience is None:
        return any(getattr(user, c.broken_field, None) for c in _linked_vk(user))
    _, field = _fields(channel, audience)
    return bool(field and getattr(user, field, None))


def broken_vk_communities(user: Optional[User]) -> list:
    """Привязанные сообщества ВК, которые отказали, — куда звать «Начать»."""
    if user is None:
        return []
    return [c for c in _linked_vk(user) if getattr(user, c.broken_field, None)]


def broken_channels(user: Optional[User]) -> list[NotifyChannel]:
    """Привязанные мессенджеры, которые отказали в доставке, — для плашки."""
    return [
        channel for channel in _MESSENGERS
        if _address(user, channel, None) and is_broken(user, channel)
    ] if user is not None else []


def _address(user: User, channel: NotifyChannel, audience):
    if channel == NotifyChannel.TG:
        return user.tg_chat_id
    if channel == NotifyChannel.MAX:
        return user.max_chat_id
    if channel == NotifyChannel.VK:
        if audience is None:
            linked = _linked_vk(user)
            return getattr(user, linked[0].peer_field) if linked else None
        return getattr(user, vk_community.get(audience).peer_field, None)
    if channel == NotifyChannel.EMAIL:
        return (user.email or "").strip() or None
    return None


def _resolve(user: Optional[User], audience) -> tuple[NotifyChannel, Optional[object]]:
    if user is None:
        return NotifyChannel.NONE, None

    preferred = user.notify_channel or NotifyChannel.NONE
    for channel in (preferred, NotifyChannel.TG, NotifyChannel.MAX, NotifyChannel.VK,
                    NotifyChannel.EMAIL):
        if channel == NotifyChannel.NONE:
            continue
        if channel == NotifyChannel.VK and audience is None:
            # Для профиля ВК рабочий, пока отвечает хоть одно сообщество.
            address = next((getattr(user, c.peer_field) for c in _linked_vk(user)
                            if not getattr(user, c.broken_field, None)), None)
            if address:
                return channel, address
            continue
        address = _address(user, channel, audience)
        if address and not is_broken(user, channel, audience):
            return channel, address
    return NotifyChannel.NONE, None


def resolve(user: Optional[User], audience) -> tuple[NotifyChannel, Optional[object]]:
    """(канал, адрес) для доставки сообщения типа audience (vk_community).

    Выбранный канал уважаем, но если адреса в нём нет (отвязали бота, стёрли
    почту, человек не писал НУЖНОМУ сообществу ВК) или мессенджер отказал
    насовсем — деградируем: мессенджеры → email. Отсутствие адреса в нужном
    сообществе — НЕ отказ: канал просто пропускается, отметок не ставим.
    Возвращает (NONE, None), если достучаться некуда.
    """
    return _resolve(user, vk_community.Audience(audience))


def display_channel(user: Optional[User]) -> tuple[NotifyChannel, Optional[object]]:
    """Канал «в целом» — для профиля, а не для отправки: ВК считается
    подключённым, если есть диалог хоть с одним сообществом. Отправлять по
    этому адресу нельзя — неизвестно, каким токеном."""
    return _resolve(user, None)


def resolve_any(user: Optional[User]) -> tuple[NotifyChannel, Optional[object], object]:
    """(канал, адрес, сообщество) для досылки сообщения НЕИЗВЕСТНОГО типа —
    отказал Telegram или MAX, а их задачи тип не знают. ВК берём тем
    сообществом, с которым у человека рабочий диалог: адрес и токен совпадут,
    и ложного отказа не будет."""
    channel, address = display_channel(user)
    if channel == NotifyChannel.VK:
        for community in _linked_vk(user):
            if getattr(user, community.peer_field) == address:
                return channel, address, community.audience
    return channel, address, vk_community.Audience.CLIENT


def has_channel(user: Optional[User], audience=None) -> bool:
    """Есть ли рабочий канал доставки. audience=None — для мягких промптов в
    интерфейсе; перед отправкой спрашивайте про тип сообщения."""
    if audience is None:
        return display_channel(user)[0] != NotifyChannel.NONE
    return resolve(user, audience)[0] != NotifyChannel.NONE


def has_channel_clause(audience):
    """SQL-условие «до пользователя реально можно достучаться сообщением типа
    audience».

    Пришло на смену `User.tg_chat_id.isnot(None)` в выборках получателей:
    иначе адресаты с MAX/почтой молча выпадали из рассылок.
    """
    community = vk_community.get(audience)
    return or_(
        and_(User.tg_chat_id.isnot(None), User.tg_broken_at.is_(None)),
        and_(User.max_chat_id.isnot(None), User.max_broken_at.is_(None)),
        and_(getattr(User, community.peer_field).isnot(None),
             getattr(User, community.broken_field).is_(None)),
        User.email.isnot(None),
    )


async def mark_broken(db, channel: NotifyChannel, address, audience=None) -> list[User]:
    """Пометить мессенджер сломанным у всех, кто привязан к этому чату.

    Отказ приходит на адрес, а не на человека: задачи отправки знают только
    chat_id. Возвращает затронутых пользователей — им нужно дослать
    недошедшее уведомление запасным каналом. Отметку, поставленную раньше, не
    двигаем: дата первого отказа полезнее последней. Для ВК audience
    обязателен: отказало одно сообщество, второе остаётся рабочим.
    """
    address_field, field = _fields(channel, audience)
    if field is None or address is None:
        return []
    users = (await db.execute(
        select(User).where(getattr(User, address_field) == address)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for user in users:
        if getattr(user, field) is None:
            setattr(user, field, now)
    if users:
        await db.commit()
    return list(users)


async def clear_broken(db, channel: NotifyChannel, address, audience=None) -> int:
    """Человек снова написал боту — значит, бот больше не заблокирован."""
    address_field, field = _fields(channel, audience)
    if field is None or address is None:
        return 0
    result = await db.execute(
        update(User)
        .where(getattr(User, address_field) == address,
               getattr(User, field).isnot(None))
        .values({field: None})
    )
    await db.commit()
    return result.rowcount or 0


async def enqueue_message(pool, channel: NotifyChannel, address, text: str, *,
                          audience, subject: str = "Руми", **kwargs) -> None:
    """Поставить в очередь сообщение в уже выбранный канал.

    Единственное место, где тип сообщения превращается в задачу очереди: для
    ВК задача получает сообщество явно, и токен выбирается по нему, а не по
    глобальной настройке.
    """
    if channel == NotifyChannel.EMAIL:
        await pool.enqueue_job("send_email", address, subject, text, **kwargs)
    elif channel == NotifyChannel.VK:
        await pool.enqueue_job("send_vk_message", address, text,
                               community=vk_community.Audience(audience).value)
    else:
        await pool.enqueue_job(task_for(channel), address, text, **kwargs)


def task_for(channel: NotifyChannel) -> Optional[str]:
    """Имя arq-задачи для мессенджер-канала (email уходит своей задачей —
    у неё другая сигнатура: тема + тело). ВК сюда не ходит: ему нужно ещё и
    сообщество, ставьте через enqueue_message."""
    if channel == NotifyChannel.VK:
        raise ValueError("ВК ставится через enqueue_message: нужно сообщество")
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
