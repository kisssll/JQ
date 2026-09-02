"""Что показывает бот при /start.

Раньше /start вёл сразу в настройки подписок — тогда бот больше ничего и не
умел. После того как у него появились записи и обратная связь, такой вход
прячет два раздела из трёх.
"""
from app.core.security import get_password_hash
from app.models.models import User, UserRole


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _FakeFrom:
    def __init__(self, user_id):
        self.id = user_id


class _FakeMessage:
    """Минимум, который нужен обработчикам tg-бота."""

    def __init__(self, chat_id, user_id=None):
        self.chat = _FakeChat(chat_id)
        self.from_user = _FakeFrom(user_id or chat_id)
        self.answers = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


class _FakeMaxBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, attachments=None):
        self.sent.append(text)


async def _linked_user(db, phone, chat_id, *, tg=True):
    kw = {"tg_chat_id": chat_id} if tg else {"max_chat_id": chat_id}
    u = User(phone=phone, full_name="Егор Петров",
             hashed_password=get_password_hash("Testpass1"),
             role=UserRole.CLIENT, is_active=True, **kw)
    db.add(u)
    await db.commit()
    return u


# ── Telegram ─────────────────────────────────────────────────────────────────

async def test_start_shows_main_menu_not_notification_settings(db_session):
    from app.tg_bot import (
        MENU_BTN_BOOKINGS, MENU_BTN_PREFS, MENU_BTN_SUPPORT, _show_main_menu,
    )

    async with db_session() as db:
        await _linked_user(db, "+79990004001", 990001)

    msg = _FakeMessage(990001)
    await _show_main_menu(msg)

    assert msg.answers, "бот ничего не ответил"
    text, markup = msg.answers[0]
    # Все три раздела названы
    for label in (MENU_BTN_BOOKINGS, MENU_BTN_PREFS, MENU_BTN_SUPPORT):
        assert label in text, f"в меню нет раздела «{label}»"
    # И это приветствие, а не список тем уведомлений
    assert "Здравствуйте" in text
    assert "включить/выключить" not in text
    assert markup is not None


async def test_start_greets_by_name(db_session):
    from app.tg_bot import _show_main_menu

    async with db_session() as db:
        await _linked_user(db, "+79990004002", 990002)

    msg = _FakeMessage(990002)
    await _show_main_menu(msg)
    assert "Егор" in msg.answers[0][0]


async def test_start_offers_linking_when_not_linked(db_session):
    """Непривязанному меню бесполезно — ему нужна привязка."""
    from app.tg_bot import _show_main_menu

    msg = _FakeMessage(990003)
    await _show_main_menu(msg)

    text, _ = msg.answers[0]
    assert "не привязан" in text.lower()


# ── MAX ──────────────────────────────────────────────────────────────────────

async def test_max_start_shows_menu_to_linked_user(db_session):
    """Уже привязанному незачем снова слать контакт."""
    from app.max_bot import MENU_BOOKINGS, _begin

    async with db_session() as db:
        await _linked_user(db, "+79990004004", 990004, tg=False)

    bot = _FakeMaxBot()
    await _begin(bot, chat_id=990004, user_id=555, token="")

    assert bot.sent, "бот ничего не ответил"
    assert MENU_BOOKINGS in bot.sent[0]
    assert "поделит" not in bot.sent[0].lower()


async def test_max_start_offers_linking_when_not_linked(db_session):
    from app.max_bot import _begin

    bot = _FakeMaxBot()
    await _begin(bot, chat_id=990005, user_id=556, token="")

    assert bot.sent
    assert "привязать" in bot.sent[0].lower()
