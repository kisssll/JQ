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
_MENU_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=MENU_BTN_PREFS)]],
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

    # Пункты в кнопке «Меню» (≡) рядом с полем ввода — тапнуть, а не печатать.
    await bot.set_my_commands([
        BotCommand(command="settings", description="⚙️ Мои уведомления"),
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
