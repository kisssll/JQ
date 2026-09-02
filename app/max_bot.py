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
from maxapi.types.attachments.buttons.callback_button import CallbackButton
from maxapi.types.attachments.buttons.request_contact import RequestContactButton
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.message_callback import MessageCallback
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

# /start без токена (или с протухшим): привязка MAX к уже существующему
# аккаунту. В tg-боте такой режим был с самого начала, а в MAX его не было —
# из-за чего кнопка «Подключить» в профиле вела в бота, который отвечал
# «не вижу активного подтверждения» и ничего привязать не мог.
LINK_MODE = "link"

_LINK_GREETING = (
    "Здравствуйте! Чтобы привязать MAX к аккаунту Руми, нажмите кнопку ниже — "
    "MAX передаст нам ваш номер, и мы найдём по нему ваш аккаунт.\n\n"
    "Если вы пришли сюда со страницы регистрации, ссылка устарела: вернитесь "
    "на сайт и нажмите «Подтвердить в MAX» ещё раз."
)

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
        # Уже привязанному незачем снова слать контакт — показываем меню.
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            linked = await _linked_user(db, chat_id)
        if linked is not None:
            await _show_main_menu(bot, chat_id, linked)
            return

        # Раньше здесь был тупик: бот сообщал об устаревшей ссылке и на этом
        # всё. Теперь предлагаем привязку по номеру — это единственный путь
        # подключить MAX к уже созданному аккаунту.
        await r.set(_pending_key(user_id), LINK_MODE,
                    ex=settings.OTP_TTL_MINUTES * 60)
        await bot.send_message(chat_id=chat_id, text=_LINK_GREETING,
                               attachments=_contact_kb())
        return

    await r.set(_pending_key(user_id), token, ex=settings.OTP_TTL_MINUTES * 60)
    await bot.send_message(chat_id=chat_id, text=_GREETING, attachments=_contact_kb())


async def _link_existing_account(event, chat_id: int, user_id: int,
                                 contact_user_id, contact_phone: str) -> None:
    """Привязать MAX к уже существующему аккаунту по номеру из контакта.

    Зеркало _link_existing_account из tg_bot.py. Чужой контакт не принимаем:
    иначе достаточно переслать боту чей-то контакт, чтобы увести чужие
    уведомления к себе.
    """
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.models import NotifyChannel, User

    if contact_user_id is not None and int(contact_user_id) != int(user_id):
        logger.info("link_foreign_contact: max_user=%s", user_id)
        await event.bot.send_message(
            chat_id=chat_id,
            text="Это чужой контакт — привязать можно только свой. "
                 "Нажмите кнопку «Поделиться контактом».",
            attachments=_contact_kb(),
        )
        return

    phone = try_normalize_phone(contact_phone)
    if not phone:
        logger.info("link_bad_phone: max_user=%s", user_id)
        await event.bot.send_message(
            chat_id=chat_id, text="Не удалось разобрать номер из контакта.",
        )
        return

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.phone == phone)
        )).scalar_one_or_none()
        if user is None:
            logger.info("link_not_registered: max_user=%s phone=%s",
                        user_id, _mask_phone(phone))
            await event.bot.send_message(
                chat_id=chat_id,
                text="Аккаунт с этим номером не найден. Сначала зарегистрируйтесь "
                     "на сайте Руми — привязка произойдёт сама при подтверждении номера.",
            )
            return

        user.max_chat_id = chat_id
        # Канала не было вовсе — пусть уведомления пойдут в MAX. Осознанно
        # выбранный ранее канал не перебиваем: человек его выбирал сам.
        if (user.notify_channel or NotifyChannel.NONE) == NotifyChannel.NONE:
            user.notify_channel = NotifyChannel.MAX
        await db.commit()

    await get_redis().delete(_pending_key(user_id))
    logger.info("linked: max_user=%s phone=%s", user_id, _mask_phone(phone))
    await event.bot.send_message(
        chat_id=chat_id,
        text="MAX привязан ✅ Теперь уведомления о записях будут приходить сюда.",
        attachments=_menu_kb(),
    )


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

    if token == LINK_MODE:
        await _link_existing_account(event, chat_id, user_id,
                                     contact_user_id, contact_phone)
        return

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


# ── Паритет с Telegram: меню уведомлений и обращение в поддержку ─────────────
# MAX долго умел только подтверждать номер: человек получал уведомления и не
# мог ими управлять — отписаться было буквально нечем. Здесь оба недостающих
# куска, логика та же, что в tg_bot.py, отличается лишь способ рисовать кнопки.

MENU_PREFS = "⚙️ Мои уведомления"
MENU_SUPPORT = "✉️ Написать нам"
MENU_BOOKINGS = "📅 Мои записи"
_SUPPORT_TTL = 1800


def _menu_kb() -> list:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text=MENU_BOOKINGS, payload="menu:bookings"))
    kb.row(CallbackButton(text=MENU_PREFS, payload="menu:prefs"))
    kb.row(CallbackButton(text=MENU_SUPPORT, payload="menu:support"))
    return [kb.as_markup()]


async def _show_bookings(bot: Bot, chat_id: int) -> None:
    """Ближайшие записи, у каждой — кнопка отмены."""
    from app.db.session import AsyncSessionLocal
    from app.services.bot_actions import format_booking, upcoming_bookings

    async with AsyncSessionLocal() as db:
        user = await _linked_user(db, chat_id)
        if user is None:
            await _offer_link(bot, chat_id, chat_id,
                              "Этот MAX пока не привязан к аккаунту Руми.")
            return
        rows = await upcoming_bookings(db, user.id)

    if not rows:
        await bot.send_message(chat_id=chat_id, text="Ближайших записей нет.")
        return

    for booking, salon, service, master_name in rows:
        kb = InlineKeyboardBuilder()
        kb.row(CallbackButton(text="Отменить запись", payload=f"cnl:{booking.id}"))
        await bot.send_message(
            chat_id=chat_id,
            text=format_booking(booking, salon, service, master_name),
            attachments=[kb.as_markup()],
        )


async def _cancel_from_bot(event: MessageCallback, booking_id: int) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.bot_actions import cancel_booking

    chat_id, _ = event.get_ids()
    async with AsyncSessionLocal() as db:
        user = await _linked_user(db, chat_id)
        if user is None:
            return
        _, text = await cancel_booking(db, user.id, booking_id)
    await event.bot.send_message(chat_id=chat_id, text=text)


async def _linked_user(db, chat_id: int):
    from sqlalchemy import select

    from app.models.models import User

    return (
        await db.execute(select(User).where(User.max_chat_id == chat_id))
    ).scalar_one_or_none()


# --- Темы уведомлений ---

async def _show_main_menu(bot: Bot, chat_id: int, user) -> None:
    """Что бот умеет — зеркало главного меню tg-бота."""
    name = (user.full_name or "").split()[0] if user.full_name else ""
    hello = f"Здравствуйте, {name}!" if name else "Здравствуйте!"
    await bot.send_message(
        chat_id=chat_id,
        text=f"{hello} Это бот Руми. Отсюда можно:\n\n"
             f"{MENU_BOOKINGS} — ближайшие записи, можно отменить\n"
             f"{MENU_PREFS} — какие уведомления присылать\n"
             f"{MENU_SUPPORT} — вопрос или проблема, ответим сюда же",
        attachments=_menu_kb(),
    )


async def _offer_link(bot: Bot, chat_id: int, user_id: int, reason: str) -> None:
    """Единая точка «MAX не привязан»: не просто сообщаем, а сразу предлагаем
    привязать. Раньше каждый такой тупик заканчивался ничем."""
    await get_redis().set(_pending_key(user_id), LINK_MODE,
                          ex=settings.OTP_TTL_MINUTES * 60)
    await bot.send_message(
        chat_id=chat_id,
        text=f"{reason}\n\nНажмите кнопку ниже — привяжем MAX к вашему аккаунту "
             "по номеру телефона.",
        attachments=_contact_kb(),
    )


async def _show_prefs(bot: Bot, chat_id: int) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.notifications import TOPIC_LABELS, wants

    async with AsyncSessionLocal() as db:
        user = await _linked_user(db, chat_id)
        if user is None:
            await _offer_link(bot, chat_id, chat_id,
                              "Этот MAX пока не привязан к аккаунту Руми.")
            return
        from app.tg_bot import _available_topics  # общий список тем, без дубля

        topics = await _available_topics(db, user)
        kb = InlineKeyboardBuilder()
        for topic in topics:
            mark = "✅" if wants(user, topic) else "☐"
            kb.row(CallbackButton(
                text=f"{mark} {TOPIC_LABELS.get(topic, topic)}",
                payload=f"ntf:{topic}",
            ))
        await bot.send_message(
            chat_id=chat_id,
            text="Что присылать вам в MAX? Нажмите, чтобы включить или выключить.",
            attachments=[kb.as_markup()],
        )


async def _toggle_topic(event: MessageCallback, topic: str) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.notifications import TOPIC_LABELS, wants

    if topic not in TOPIC_LABELS:
        return

    chat_id, _ = event.get_ids()
    async with AsyncSessionLocal() as db:
        user = await _linked_user(db, chat_id)
        if user is None:
            return
        # JSON-колонку меняем пересозданием словаря: мутацию на месте
        # SQLAlchemy не заметит и ничего не сохранит (как в tg_bot.py).
        prefs = dict(user.tg_notify_prefs or {})
        new_value = not wants(user, topic)
        prefs[topic] = new_value
        user.tg_notify_prefs = prefs
        await db.commit()

    state = "включены" if new_value else "выключены"
    await event.bot.send_message(
        chat_id=chat_id,
        text=f"{TOPIC_LABELS.get(topic, topic)}: {state}.",
    )
    await _show_prefs(event.bot, chat_id)


# --- Обращение в поддержку ---

def _support_key(chat_id: int) -> str:
    return f"support:draft:max:{chat_id}"


async def _draft_get(chat_id: int) -> dict | None:
    import json

    raw = await get_redis().get(_support_key(chat_id))
    if not raw:
        return None
    return json.loads(raw if isinstance(raw, str) else raw.decode())


async def _draft_set(chat_id: int, draft: dict) -> None:
    import json

    await get_redis().set(_support_key(chat_id), json.dumps(draft), ex=_SUPPORT_TTL)


async def _draft_clear(chat_id: int) -> None:
    await get_redis().delete(_support_key(chat_id))


async def _show_topics(bot: Bot, chat_id: int) -> None:
    from app.models.models import SupportTopic
    from app.services.support import TOPIC_LABELS as SUPPORT_LABELS

    await _draft_clear(chat_id)
    kb = InlineKeyboardBuilder()
    for topic in (SupportTopic.QUESTION, SupportTopic.BUG,
                  SupportTopic.COMPLAINT, SupportTopic.IDEA):
        kb.row(CallbackButton(text=SUPPORT_LABELS[topic], payload=f"sup:{topic.value}"))
    await bot.send_message(
        chat_id=chat_id,
        text="О чём хотите написать? Выберите тему — так мы быстрее поймём, "
             "кому передать обращение.",
        attachments=[kb.as_markup()],
    )


async def on_callback(event: MessageCallback) -> None:
    """Один вход на все кнопки: меню, темы уведомлений, темы обращения."""
    from app.models.models import SupportTopic
    from app.services.support import MAX_PHOTOS, TOPIC_LABELS as SUPPORT_LABELS

    chat_id, _ = event.get_ids()
    payload = (getattr(event.callback, "payload", "") or "").strip()

    if payload == "menu:bookings":
        await _show_bookings(event.bot, chat_id)
    elif payload.startswith("cnl:"):
        try:
            await _cancel_from_bot(event, int(payload.split(":", 1)[1]))
        except ValueError:
            return
    elif payload == "menu:prefs":
        await _show_prefs(event.bot, chat_id)
    elif payload == "menu:support":
        await _show_topics(event.bot, chat_id)
    elif payload.startswith("ntf:"):
        await _toggle_topic(event, payload.split(":", 1)[1])
    elif payload.startswith("sup:"):
        try:
            topic = SupportTopic(payload.split(":", 1)[1])
        except ValueError:
            return
        await _draft_set(chat_id, {"topic": topic.value, "photos": []})
        await event.bot.send_message(
            chat_id=chat_id,
            text=f"Тема: {SUPPORT_LABELS[topic]}\n\n"
                 "Опишите, что случилось — одним сообщением. "
                 f"Можно приложить фото (до {MAX_PHOTOS}).\n\n"
                 "Отменить — напишите «отмена».",
        )


async def _photo_bytes(event: MessageCreated) -> bytes | None:
    """Первое изображение из вложений сообщения → байты."""
    import httpx

    try:
        for att in (event.message.body.attachments or []):
            url = getattr(getattr(att, "payload", None), "url", None)
            if not url:
                continue
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                return resp.content
    except Exception:
        logger.warning("support: фото из MAX не скачано", exc_info=True)
    return None


async def on_free_message(event: MessageCreated) -> None:
    """Текст вне сценариев: либо продолжение обращения, либо показ меню."""
    from app.db.session import AsyncSessionLocal
    from app.models.models import NotifyChannel, SupportTopic
    from app.services.support import (
        MAX_PHOTOS, RateLimited, check_rate_limit, create_request,
        store_photo, validate_text,
    )

    chat_id, _ = event.get_ids()
    text = (getattr(event.message.body, "text", None) or "").strip()

    draft = await _draft_get(chat_id)
    if draft is None:
        # Не в сценарии — показываем, что бот вообще умеет.
        if text:
            await event.bot.send_message(
                chat_id=chat_id,
                text="Чем помочь?", attachments=_menu_kb(),
            )
        return

    if text.lower() in ("отмена", "/cancel"):
        await _draft_clear(chat_id)
        await event.bot.send_message(chat_id=chat_id, text="Обращение отменено.")
        return

    has_photo = bool(getattr(event.message.body, "attachments", None))
    if has_photo and len(draft["photos"]) < MAX_PHOTOS:
        data = await _photo_bytes(event)
        url = store_photo(data) if data else None
        if url:
            draft["photos"].append(url)
            await _draft_set(chat_id, draft)
        if not text:
            await event.bot.send_message(
                chat_id=chat_id,
                text=f"Фото принято ({len(draft['photos'])}). "
                     "Теперь опишите проблему текстом.",
            )
            return

    error = validate_text(text)
    if error:
        await event.bot.send_message(chat_id=chat_id, text=error)
        return

    try:
        await check_rate_limit(NotifyChannel.MAX, chat_id)
    except RateLimited:
        await _draft_clear(chat_id)
        await event.bot.send_message(
            chat_id=chat_id,
            text="Вы уже отправили несколько обращений за последний час — "
                 "мы ответим на них в ближайшее время.",
        )
        return

    async with AsyncSessionLocal() as db:
        user = await _linked_user(db, chat_id)
        request = await create_request(
            db, topic=SupportTopic(draft["topic"]), text=text,
            channel=NotifyChannel.MAX, chat_id=chat_id, user=user,
            photos=draft["photos"],
        )

    await _draft_clear(chat_id)
    await event.bot.send_message(
        chat_id=chat_id,
        text=f"Обращение №{request.id} принято — спасибо.\n"
             "Ответим сюда же, в этот чат.",
        attachments=_menu_kb(),
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
    # Кнопки меню, тем уведомлений и обращения — один обработчик по payload.
    dp.message_callback()(on_callback)
    # Свободный текст регистрируем ПОСЛЕДНИМ: иначе он перехватил бы /start.
    dp.message_created()(on_free_message)

    logger.info("MAX-бот подтверждения номера запущен (long polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Мониторинг и логи (блок 05): единые логи + трекинг ошибок бота.
    from app.core.observability import init_sentry, setup_logging

    setup_logging()
    init_sentry()
    asyncio.run(main())
