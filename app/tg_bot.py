# app/tg_bot.py
"""Telegram-бот подтверждения номера телефона (блок 18).

Запуск: python -m app.tg_bot — отдельный контейнер рядом с приложением.
Long polling, не webhook: боту не нужны ни порт, ни маршрут в Caddy,
только исходящие соединения к api.telegram.org и Redis.

Контракт с приложением — исключительно Redis-запись otp:{request_id}
(создаёт app/services/otp.py со status=pending): бот после проверки
контакта переводит её в confirmed, дальше работает обычный verify_code.

Ключевая проверка безопасности: принимается ТОЛЬКО собственный контакт
отправителя (contact.user_id == from_user.id) — пересланный чужой контакт
не подтверждает ничего.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.core.config import settings
from app.core.limiter import get_redis
from app.schemas.user import try_normalize_phone
from app.services.otp import (
    TG_STATUS_CONFIRMED,
    TG_STATUS_PENDING,
    _hash,
    _key,
    _mask_phone,
    save_tg_chat_id,
)

logger = logging.getLogger("tg_bot")

VERDICT_OK = "ok"
VERDICT_NOT_FOUND = "not_found"
VERDICT_FOREIGN_CONTACT = "foreign_contact"
VERDICT_PHONE_MISMATCH = "phone_mismatch"


def _pending_key(user_id: int) -> str:
    """Какой request_id сейчас подтверждает этот Telegram-пользователь.

    Храним в Redis, а не в памяти бота: состояние переживает рестарт
    контейнера и деплой. TTL тот же, что у самой верификации.
    """
    return f"otp:tg-pending:{user_id}"


def check_contact(
    record: dict,
    contact_user_id,
    sender_id: int,
    contact_phone: str,
) -> str:
    """Чистая проверка контакта против записи верификации (без aiogram — тестируемо).

    Порядок важен: сначала валидность записи, затем принадлежность контакта
    отправителю, затем совпадение номера.
    """
    if (
        not record
        or record.get("channel") != "telegram"
        or record.get("status") != TG_STATUS_PENDING
    ):
        return VERDICT_NOT_FOUND
    if contact_user_id is None or contact_user_id != sender_id:
        return VERDICT_FOREIGN_CONTACT
    phone = try_normalize_phone(contact_phone or "")
    if not phone or _hash(phone) != record.get("phone_hash"):
        return VERDICT_PHONE_MISMATCH
    return VERDICT_OK


_CONTACT_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Поделиться контактом", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

# Постоянная кнопка внизу у привязанного пользователя: открыть меню подписок,
# не набирая /settings. Ставится после привязки и держится в чате.
MENU_BTN_PREFS = "⚙️ Мои уведомления"
MENU_BTN_SUPPORT = "✉️ Написать нам"
_MENU_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=MENU_BTN_PREFS)], [KeyboardButton(text=MENU_BTN_SUPPORT)]],
    resize_keyboard=True,
)
# Непривязанному постоянное меню не ставится (он его просто не видел), но
# написать в поддержку он должен мочь — именно у него чаще всего и проблема
# со входом. Поэтому у обращения свой вход через /feedback и кнопку.
_SUPPORT_ONLY_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=MENU_BTN_SUPPORT)]],
    resize_keyboard=True,
)


LINK_MODE = "link"  # /start без токена: привязка Telegram к существующему аккаунту


# ── Личные подписки на уведомления (этап 2 разграничения) ────────────────────

async def _find_linked_user(db, chat_id: int):
    from sqlalchemy import select

    from app.models.models import User

    return (
        await db.execute(select(User).where(User.tg_chat_id == chat_id))
    ).scalar_one_or_none()


async def _available_topics(db, user) -> list[str]:
    """Темы, доступные человеку по его фактическим связям и правам.

    Право пропало — тема исчезает из меню сама (и отправка всё равно
    фильтруется правами, меню — только удобство).
    """
    from sqlalchemy import select

    from app.models.models import Master, SalonMember, UserRole
    from app.services.notifications import (
        TOPIC_BOOKINGS,
        TOPIC_REMINDERS,
        TOPIC_EVENING_DEALS,
        TOPIC_REPORTS,
        TOPIC_REVIEWS,
        TOPIC_WAREHOUSE,
    )

    # Клиентские — всем привязанным (вечерние скидки — opt-out, default вкл).
    topics = [TOPIC_BOOKINGS, TOPIC_REMINDERS, TOPIC_EVENING_DEALS]

    is_master = (
        await db.execute(select(Master.id).where(Master.user_id == user.id, Master.is_active == True))  # noqa: E712
    ).scalars().first() is not None

    memberships = (
        await db.execute(
            select(SalonMember).where(SalonMember.user_id == user.id, SalonMember.is_active == True)  # noqa: E712
        )
    ).scalars().all()

    def _has(perm: str) -> bool:
        return any(m.is_creator or bool((m.permissions or {}).get(perm)) for m in memberships)

    if is_master or _has("manage_inventory"):
        topics.append(TOPIC_WAREHOUSE)
    if is_master or _has("manage_reviews"):
        topics.append(TOPIC_REVIEWS)
    if _has("manage_reviews") or user.role == UserRole.ADMIN:
        topics.append(TOPIC_REPORTS)
    return topics


def _prefs_keyboard(user, topics: list[str]) -> InlineKeyboardMarkup:
    from app.services.notifications import TOPIC_LABELS, wants

    rows = [
        [InlineKeyboardButton(
            text=f"{'🔔' if wants(user, t) else '🔕'} {TOPIC_LABELS[t]}",
            callback_data=f"ntf:{t}",
        )]
        for t in topics
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_prefs_menu(message: Message) -> None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        user = await _find_linked_user(db, message.chat.id)
        if user is None:
            await message.answer(
                "Telegram ещё не привязан к аккаунту Руми. Нажмите кнопку ниже, "
                "чтобы привязать — и уведомления заработают.",
                reply_markup=_CONTACT_KB,
            )
            r = get_redis()
            await r.set(_pending_key(message.from_user.id), LINK_MODE,
                        ex=settings.OTP_TTL_MINUTES * 60)
            return
        topics = await _available_topics(db, user)
        await message.answer(
            "⚙️ Мои уведомления — нажмите, чтобы включить/выключить:",
            reply_markup=_prefs_keyboard(user, topics),
        )


async def on_prefs_toggle(callback: CallbackQuery) -> None:
    """Кнопка темы: перевернуть личную подписку и перерисовать меню."""
    from app.db.session import AsyncSessionLocal
    from app.services.notifications import TOPIC_LABELS, wants

    topic = (callback.data or "").split(":", 1)[-1]
    if topic not in TOPIC_LABELS:
        await callback.answer("Неизвестная тема")
        return

    async with AsyncSessionLocal() as db:
        user = await _find_linked_user(db, callback.message.chat.id)
        if user is None:
            await callback.answer("Telegram не привязан")
            return
        # JSON-колонку меняем пересозданием словаря — иначе SQLAlchemy
        # не заметит мутацию и ничего не сохранит
        prefs = dict(user.tg_notify_prefs or {})
        prefs[topic] = not wants(user, topic)
        user.tg_notify_prefs = prefs
        await db.commit()
        topics = await _available_topics(db, user)
        try:
            await callback.message.edit_reply_markup(
                reply_markup=_prefs_keyboard(user, topics)
            )
        except Exception:
            pass  # текст/markup не изменились — Telegram кидает ошибку, не страшно
    await callback.answer("Сохранено")


# ── Обращение в поддержку ────────────────────────────────────────────────────
# Состояние диалога держим в Redis, а не в памяти процесса: бот перезапускается
# вместе со стеком, и незаконченное обращение не должно ломаться от деплоя.
_SUPPORT_TTL = 1800  # 30 минут на то, чтобы дописать обращение


def _support_key(chat_id: int) -> str:
    return f"support:draft:tg:{chat_id}"


async def _support_draft(chat_id: int) -> dict | None:
    import json

    raw = await get_redis().get(_support_key(chat_id))
    if not raw:
        return None
    return json.loads(raw if isinstance(raw, str) else raw.decode())


async def _support_save(chat_id: int, draft: dict) -> None:
    import json

    await get_redis().set(_support_key(chat_id), json.dumps(draft), ex=_SUPPORT_TTL)


async def _support_clear(chat_id: int) -> None:
    await get_redis().delete(_support_key(chat_id))


def _topics_keyboard() -> InlineKeyboardMarkup:
    from app.models.models import SupportTopic
    from app.services.support import TOPIC_LABELS

    order = [SupportTopic.QUESTION, SupportTopic.BUG,
             SupportTopic.COMPLAINT, SupportTopic.IDEA]
    rows, pair = [], []
    for topic in order:
        pair.append(InlineKeyboardButton(
            text=TOPIC_LABELS[topic], callback_data=f"sup:{topic.value}",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def on_support_start(message: Message) -> None:
    """«Написать нам» — выбор темы. Доступно всем, даже без аккаунта."""
    await _support_clear(message.chat.id)
    await message.answer(
        "О чём хотите написать?\n\n"
        "Выберите тему — так мы быстрее поймём, кому передать обращение.",
        reply_markup=_topics_keyboard(),
    )


async def on_support_topic(callback: CallbackQuery) -> None:
    from app.models.models import SupportTopic
    from app.services.support import MAX_PHOTOS, TOPIC_LABELS

    value = (callback.data or "").split(":", 1)[1]
    try:
        topic = SupportTopic(value)
    except ValueError:
        await callback.answer()
        return

    await _support_save(callback.message.chat.id, {"topic": topic.value, "photos": []})
    await callback.message.edit_text(
        f"Тема: {TOPIC_LABELS[topic]}\n\n"
        "Опишите, что случилось — одним сообщением. "
        f"Можно приложить фото (до {MAX_PHOTOS}), если так понятнее.\n\n"
        "Отменить — /cancel"
    )
    await callback.answer()


async def on_support_cancel(message: Message) -> None:
    if await _support_draft(message.chat.id) is None:
        return
    await _support_clear(message.chat.id)
    await message.answer("Обращение отменено.")


async def _download_photo(message: Message) -> bytes | None:
    """Самый крупный вариант присланного фото → байты."""
    try:
        file = await message.bot.get_file(message.photo[-1].file_id)
        buf = await message.bot.download_file(file.file_path)
        return buf.read()
    except Exception:
        logger.exception("support: не удалось скачать фото")
        return None


async def on_support_message(message: Message) -> None:
    """Текст (и/или фото) для начатого обращения."""
    from app.db.session import AsyncSessionLocal
    from app.models.models import NotifyChannel, SupportTopic
    from app.services.support import (
        MAX_PHOTOS, RateLimited, check_rate_limit, create_request,
        store_photo, validate_text,
    )

    chat_id = message.chat.id
    draft = await _support_draft(chat_id)
    if draft is None:
        return  # обращение не начиналось — сообщение не наше

    # Фото без подписи: копим и ждём текст. Так человек может прислать
    # несколько снимков подряд, а описание дописать следом.
    caption = message.caption or message.text or ""
    if message.photo:
        if len(draft["photos"]) >= MAX_PHOTOS:
            await message.answer(f"Больше {MAX_PHOTOS} фото не приложить — опишите словами.")
            return
        data = await _download_photo(message)
        url = store_photo(data) if data else None
        if url:
            draft["photos"].append(url)
            await _support_save(chat_id, draft)
        if not caption:
            await message.answer(
                f"Фото принято ({len(draft['photos'])}). "
                "Теперь опишите проблему текстом — или пришлите ещё фото."
            )
            return

    error = validate_text(caption)
    if error:
        await message.answer(error)
        return

    try:
        await check_rate_limit(NotifyChannel.TG, chat_id)
    except RateLimited:
        await _support_clear(chat_id)
        await message.answer(
            "Вы уже отправили несколько обращений за последний час — "
            "мы ответим на них в ближайшее время."
        )
        return

    async with AsyncSessionLocal() as db:
        user = await _find_linked_user(db, chat_id)
        request = await create_request(
            db, topic=SupportTopic(draft["topic"]), text=caption,
            channel=NotifyChannel.TG, chat_id=chat_id, user=user,
            photos=draft["photos"],
        )

    await _support_clear(chat_id)
    await message.answer(
        f"Обращение №{request.id} принято — спасибо.\n"
        "Ответим сюда же, в этот чат.",
        reply_markup=_MENU_KB if user else _SUPPORT_ONLY_KB,
    )


async def on_start(message: Message, command: CommandObject) -> None:
    """/start <request_id> из deep link'а, или /start без аргумента — привязка."""
    token = (command.args or "").strip()
    r = get_redis()

    if not token:
        # Без deep link'а: привязанному — меню личных подписок, остальным —
        # предложение привязать аккаунт (внутри _show_prefs_menu).
        await _show_prefs_menu(message)
        return

    record = await r.hgetall(_key(token))
    if not record or record.get("channel") != "telegram":
        await message.answer(
            "Ссылка устарела или открыта без сайта. Вернитесь на страницу "
            "регистрации Руми и нажмите «Подтвердить в Telegram» ещё раз."
        )
        return

    await r.set(
        _pending_key(message.from_user.id),
        token,
        ex=settings.OTP_TTL_MINUTES * 60,
    )
    await message.answer(
        "Здравствуйте! Это подтверждение номера для Руми.\n\n"
        "Нажмите кнопку ниже — Telegram передаст нам ваш номер, и мы сверим "
        "его с указанным при регистрации. Ничего вводить не нужно.",
        reply_markup=_CONTACT_KB,
    )


async def _find_pending_register_token(r, phone: str) -> str | None:
    """request_id ожидающей TG-регистрации на этот номер, либо None.

    Нужно для спасения тех, кто открыл бота БЕЗ deep-link токена: Telegram не
    всегда пересылает ?start=<token> для уже существующего чата, и человек
    попадает в режим привязки, хотя реально подтверждает регистрацию. Скан по
    небольшому числу активных otp:{uuid}-записей (TTL 5 мин) — дёшево.
    """
    target = _hash(phone)
    try:
        async for key in r.scan_iter(match="otp:*", count=100):
            # исключаем служебные строки otp:tg-chat:* и otp:tg-pending:*
            if key.startswith("otp:tg-"):
                continue
            rec = await r.hgetall(key)
            if (
                rec.get("channel") == "telegram"
                and rec.get("status") == TG_STATUS_PENDING
                and rec.get("phone_hash") == target
            ):
                return key.split("otp:", 1)[1]
    except Exception:
        return None
    return None


async def _link_existing_account(message: Message) -> None:
    """LINK_MODE: подтверждаем ожидающую регистрацию по номеру (спасение без
    токена) либо привязываем chat_id к уже существующему аккаунту."""
    if message.contact.user_id != message.from_user.id:
        logger.info("link_foreign_contact: tg_user=%s", message.from_user.id)
        await message.answer(
            "Это чужой контакт — привязать можно только свой. "
            "Нажмите кнопку «Поделиться контактом».",
            reply_markup=_CONTACT_KB,
        )
        return

    phone = try_normalize_phone(message.contact.phone_number or "")
    if not phone:
        logger.info(
            "link_bad_phone: tg_user=%s raw=%r",
            message.from_user.id, message.contact.phone_number,
        )
        await message.answer(
            "Не удалось разобрать номер из контакта.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    r = get_redis()

    # Спасение: пришёл без deep-link токена, но на сайте есть ожидающая
    # регистрация-верификация на этот номер — подтверждаем её здесь.
    pending_token = await _find_pending_register_token(r, phone)
    if pending_token is not None:
        await r.hset(_key(pending_token), "status", TG_STATUS_CONFIRMED)
        await r.delete(_pending_key(message.from_user.id))
        await save_tg_chat_id(_hash(phone), message.chat.id)
        logger.info(
            "confirmed_via_link: tg_user=%s phone=%s",
            message.from_user.id, _mask_phone(phone),
        )
        await message.answer(
            "Номер подтверждён ✅\nВернитесь на сайт — регистрация продолжится сама.\n\n"
            "Кнопка «⚙️ Мои уведомления» внизу — управление подписками.",
            reply_markup=_MENU_KB,
        )
        return

    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.models import User

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.phone == phone))
        ).scalar_one_or_none()
        if user is None:
            logger.info(
                "link_not_registered: tg_user=%s phone=%s",
                message.from_user.id, _mask_phone(phone),
            )
            await message.answer(
                "Аккаунт с этим номером не найден. Сначала зарегистрируйтесь "
                "на сайте Руми — привязка произойдёт сама при подтверждении номера.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        user.tg_chat_id = message.chat.id
        await db.commit()

    await r.delete(_pending_key(message.from_user.id))
    logger.info(
        "linked: tg_user=%s phone=%s", message.from_user.id, _mask_phone(phone)
    )
    await message.answer(
        "Telegram привязан ✅ Теперь уведомления о записях будут приходить сюда.\n\n"
        "Кнопка «⚙️ Мои уведомления» внизу — управление подписками.",
        reply_markup=_MENU_KB,
    )


async def on_contact(message: Message) -> None:
    r = get_redis()
    token = await r.get(_pending_key(message.from_user.id))
    if not token:
        # Нет активного подтверждения у ЭТОГО tg-пользователя. Но человек мог
        # прийти без токена в процессе регистрации — пробуем спасти как привязку
        # (внутри — поиск ожидающей регистрации по номеру).
        logger.info("contact_no_pending: tg_user=%s", message.from_user.id)
        await _link_existing_account(message)
        return

    if token == LINK_MODE:
        await _link_existing_account(message)
        return

    record = await r.hgetall(_key(token))
    verdict = check_contact(
        record,
        message.contact.user_id,
        message.from_user.id,
        message.contact.phone_number,
    )

    if verdict == VERDICT_OK:
        await r.hset(_key(token), "status", TG_STATUS_CONFIRMED)
        await r.delete(_pending_key(message.from_user.id))
        # Запоминаем chat_id: после регистрации он переедет в users.tg_chat_id
        # (pop_tg_chat_id в register-эндпоинтах) — уведомления заработают сразу.
        await save_tg_chat_id(record["phone_hash"], message.chat.id)
        logger.info(
            "confirmed: tg_user=%s phone=%s",
            message.from_user.id,
            _mask_phone(try_normalize_phone(message.contact.phone_number) or ""),
        )
        await message.answer(
            "Номер подтверждён ✅\nВернитесь на сайт — регистрация продолжится сама.\n\n"
            "Кнопка «⚙️ Мои уведомления» внизу — управление подписками.",
            reply_markup=_MENU_KB,
        )
    elif verdict == VERDICT_FOREIGN_CONTACT:
        logger.info(
            "verify_foreign_contact: tg_user=%s contact_user=%s",
            message.from_user.id, message.contact.user_id,
        )
        await message.answer(
            "Это чужой контакт — так подтвердить номер нельзя. "
            "Нажмите кнопку «Поделиться контактом», чтобы отправить свой.",
            reply_markup=_CONTACT_KB,
        )
    elif verdict == VERDICT_PHONE_MISMATCH:
        logger.info(
            "verify_phone_mismatch: tg_user=%s tg_phone=%s",
            message.from_user.id,
            _mask_phone(try_normalize_phone(message.contact.phone_number) or "?"),
        )
        await message.answer(
            "Этот Telegram привязан к другому номеру — не к тому, что указан "
            "при регистрации. Проверьте номер на сайте или подтвердите его "
            "с Telegram-аккаунта на этом номере.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        logger.info("verify_expired: tg_user=%s", message.from_user.id)
        await message.answer(
            f"Подтверждение устарело (действует {settings.OTP_TTL_MINUTES} мин). "
            "Вернитесь на сайт и начните заново.",
            reply_markup=ReplyKeyboardRemove(),
        )


async def main() -> None:
    if not settings.TG_BOT_TOKEN:
        # Не падаем: контейнер в compose поднимается вместе со стеком и до
        # появления токена просто спит (иначе restart: unless-stopped
        # устроил бы crash-loop). Дали токен → пересоздать контейнер.
        logger.warning(
            "TG_BOT_TOKEN не задан — бот в режиме ожидания. Задайте токен "
            "в .env и пересоздайте контейнер (up -d --force-recreate tg-bot)."
        )
        await asyncio.Event().wait()
        return

    bot = Bot(token=settings.TG_BOT_TOKEN)
    dp = Dispatcher()
    dp.message.register(on_start, CommandStart())
    dp.message.register(_show_prefs_menu, Command("settings"))
    # Нижняя кнопка-клавиатура: открыть меню подписок без набора /settings.
    dp.message.register(_show_prefs_menu, F.text == MENU_BTN_PREFS)
    dp.message.register(on_contact, F.contact)
    dp.callback_query.register(on_prefs_toggle, F.data.startswith("ntf:"))

    # Обращение в поддержку. Порядок важен: /cancel и кнопки регистрируем ДО
    # «свободного» обработчика, иначе он проглотит их как текст обращения.
    dp.message.register(on_support_start, Command("feedback"))
    dp.message.register(on_support_start, F.text == MENU_BTN_SUPPORT)
    dp.message.register(on_support_cancel, Command("cancel"))
    dp.callback_query.register(on_support_topic, F.data.startswith("sup:"))
    # Ловим только когда обращение начато — внутри проверяется черновик.
    dp.message.register(on_support_message, F.text | F.photo)

    # Пункты в кнопке «Меню» (≡) рядом с полем ввода — тапнуть, а не печатать.
    await bot.set_my_commands([
        BotCommand(command="settings", description="⚙️ Мои уведомления"),
        BotCommand(command="feedback", description="✉️ Написать нам"),
        BotCommand(command="start", description="Меню и привязка аккаунта"),
    ])

    logger.info("Бот подтверждения номера запущен (long polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Мониторинг и логи (блок 05): единые логи + трекинг ошибок бота.
    from app.core.observability import init_sentry, setup_logging

    setup_logging()
    init_sentry()
    asyncio.run(main())
