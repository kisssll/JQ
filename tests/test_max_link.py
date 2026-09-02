"""Привязка MAX к уже существующему аккаунту.

Живой случай: подключить MAX можно было только в момент регистрации. Кнопка
«Подключить» в профиле вела на голую ссылку бота, тот не находил активного
подтверждения и упирался в тупик — привязать было нечем. В tg-боте режим
привязки был с самого начала, в MAX его не существовало.
"""
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import NotifyChannel, User, UserRole


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, attachments=None):
        self.sent.append(text)


class _FakeEvent:
    def __init__(self):
        self.bot = _FakeBot()


async def _user(db, phone: str, **kw):
    base = dict(full_name="К", hashed_password=get_password_hash("Testpass1"),
                role=UserRole.CLIENT, is_active=True)
    base.update(kw)
    u = User(phone=phone, **base)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def test_links_max_to_existing_account(db_session):
    from app.max_bot import _link_existing_account

    async with db_session() as db:
        user = await _user(db, "+79990003001")
        uid = user.id

    event = _FakeEvent()
    await _link_existing_account(event, chat_id=880001, user_id=555,
                                 contact_user_id=555,
                                 contact_phone="+79990003001")

    assert any("привязан" in t for t in event.bot.sent), event.bot.sent
    async with db_session() as db:
        again = await db.get(User, uid)
        assert again.max_chat_id == 880001
        assert again.notify_channel == NotifyChannel.MAX


async def test_foreign_contact_is_refused(db_session):
    """Иначе достаточно переслать боту чужой контакт, чтобы увести чужие
    уведомления к себе."""
    from app.max_bot import _link_existing_account

    async with db_session() as db:
        user = await _user(db, "+79990003002")
        uid = user.id

    event = _FakeEvent()
    await _link_existing_account(event, chat_id=880002, user_id=555,
                                 contact_user_id=999,  # чужой
                                 contact_phone="+79990003002")

    assert any("чужой контакт" in t for t in event.bot.sent), event.bot.sent
    async with db_session() as db:
        again = await db.get(User, uid)
        assert again.max_chat_id is None


async def test_unknown_phone_links_nothing(db_session):
    from app.max_bot import _link_existing_account

    event = _FakeEvent()
    await _link_existing_account(event, chat_id=880003, user_id=555,
                                 contact_user_id=555,
                                 contact_phone="+79990009876")

    assert any("не найден" in t for t in event.bot.sent), event.bot.sent


async def test_existing_channel_is_not_overwritten(db_session):
    """Человек мог осознанно выбрать Telegram — привязка MAX не должна
    молча переключать доставку на себя."""
    from app.max_bot import _link_existing_account

    async with db_session() as db:
        user = await _user(db, "+79990003003", tg_chat_id=770003,
                           notify_channel=NotifyChannel.TG)
        uid = user.id

    event = _FakeEvent()
    await _link_existing_account(event, chat_id=880004, user_id=555,
                                 contact_user_id=555,
                                 contact_phone="+79990003003")

    async with db_session() as db:
        again = await db.get(User, uid)
        assert again.max_chat_id == 880004      # привязали
        assert again.notify_channel == NotifyChannel.TG   # но канал не тронули


async def test_unparsable_phone_is_reported(db_session):
    from app.max_bot import _link_existing_account

    event = _FakeEvent()
    await _link_existing_account(event, chat_id=880005, user_id=555,
                                 contact_user_id=555, contact_phone="не номер")
    assert any("разобрать номер" in t for t in event.bot.sent), event.bot.sent
