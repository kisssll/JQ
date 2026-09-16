# tests/test_ad_consent.py
"""Согласие на рекламную подборку вечерних окон.

По ч. 1 ст. 18 закона «О рекламе» рекламу по сетям электросвязи можно слать
только с предварительного согласия, а доказывать его обязан рекламодатель.
Тесты закрепляют три вещи: без согласия подборка не приходит; согласие нельзя
получить в обход журнала; робот, открывший ссылку из письма, согласия не даёт.
"""
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import ConsentDocument, User, UserConsent, UserRole
from app.services import ad_consent
from app.services.notifications import TOPIC_EVENING_DEALS, TOPIC_REMINDERS, wants


async def _user(db_session, phone="+79996660001", **kw) -> int:
    async with db_session() as db:
        user = User(phone=phone, full_name="Клиент", role=UserRole.CLIENT,
                    hashed_password=get_password_hash("x"), **kw)
        db.add(user)
        await db.commit()
        return user.id


async def _consents(db_session, user_id):
    async with db_session() as db:
        return (await db.execute(select(UserConsent).where(
            UserConsent.user_id == user_id,
            UserConsent.document == ConsentDocument.ADS_EVENING_DEALS,
        ))).scalars().all()


# ── по умолчанию ────────────────────────────────────────────────────────────

def test_advertising_is_off_by_default_service_is_on():
    """Сервисное — «включено, пока не выключишь», рекламное — наоборот."""
    user = User(phone="+79990000000", tg_notify_prefs=None)
    assert wants(user, TOPIC_REMINDERS) is True
    assert wants(user, TOPIC_EVENING_DEALS) is False


# ── grant / revoke ───────────────────────────────────────────────────────────

async def test_grant_writes_proof_and_enables(client, db_session):
    user_id = await _user(db_session)
    async with db_session() as db:
        assert await ad_consent.grant(db, user_id=user_id, source="tg_question") is True

    records = await _consents(db_session, user_id)
    assert len(records) == 1
    assert records[0].source == "tg_question"
    assert records[0].version == ad_consent.VERSION
    async with db_session() as db:
        assert wants(await db.get(User, user_id), TOPIC_EVENING_DEALS) is True


async def test_second_press_does_not_duplicate_proof(client, db_session):
    user_id = await _user(db_session)
    async with db_session() as db:
        await ad_consent.grant(db, user_id=user_id, source="tg_question")
    async with db_session() as db:
        assert await ad_consent.grant(db, user_id=user_id, source="tg_question") is False
    assert len(await _consents(db_session, user_id)) == 1


async def test_no_proof_no_mailing(client, db_session, monkeypatch):
    """Не смогли записать согласие — рассылку НЕ включаем. Общий
    record_consents глотает ошибки, и для рекламы это было бы нарушением."""
    user_id = await _user(db_session)

    async def boom(self):
        raise RuntimeError("база недоступна")

    from sqlalchemy.ext.asyncio import AsyncSession
    monkeypatch.setattr(AsyncSession, "commit", boom)
    async with db_session() as db:
        try:
            await ad_consent.grant(db, user_id=user_id, source="tg_question")
            raise AssertionError("ошибка записи проглочена")
        except RuntimeError:
            pass
    monkeypatch.undo()

    async with db_session() as db:
        assert wants(await db.get(User, user_id), TOPIC_EVENING_DEALS) is False
    assert await _consents(db_session, user_id) == []


async def test_revoke_stops_mailing(client, db_session):
    user_id = await _user(db_session)
    async with db_session() as db:
        await ad_consent.grant(db, user_id=user_id, source="tg_prefs")
    async with db_session() as db:
        await ad_consent.revoke(db, user_id=user_id)
    async with db_session() as db:
        assert wants(await db.get(User, user_id), TOPIC_EVENING_DEALS) is False


# ── нейтральный вопрос ──────────────────────────────────────────────────────

def test_question_is_not_itself_an_ad():
    """«Хотите получать?» — не реклама. «Успейте на −30%, хотите ещё?» — уже
    реклама, и мы отправили бы её без согласия, которое пытаемся получить."""
    text = ad_consent.QUESTION_TEXT.lower()
    for forbidden in ("http", "rrumi.ru", "%", "успейте", "дешевле", "₽"):
        assert forbidden not in text, forbidden


# ── ссылка из письма ────────────────────────────────────────────────────────

def test_token_round_trip_and_tamper():
    token = ad_consent.make_token(42, now=1_000_000)
    assert ad_consent.read_token(token, now=1_000_001) == 42
    user, exp, sig = token.split(".")
    assert ad_consent.read_token(f"43.{exp}.{sig}", now=1_000_001) is None   # чужой id
    assert ad_consent.read_token("мусор", now=1_000_001) is None


def test_token_expires():
    token = ad_consent.make_token(42, now=1_000_000)
    late = 1_000_000 + ad_consent.TOKEN_TTL_SECONDS + 1
    assert ad_consent.read_token(token, now=late) is None


async def test_opening_the_link_does_not_consent(client, db_session):
    """Главный тест страницы. Почтовые сканеры открывают ссылки из писем
    сами — если бы переход записывал согласие, робот соглашался бы за человека."""
    user_id = await _user(db_session)
    token = ad_consent.make_token(user_id)
    r = await client.get(f"/consent/evening-deals?t={token}")
    assert r.status_code == 200
    assert ad_consent.OPT_IN_LABEL in r.text
    assert await _consents(db_session, user_id) == []
    async with db_session() as db:
        assert wants(await db.get(User, user_id), TOPIC_EVENING_DEALS) is False


async def test_pressing_the_button_consents(client, db_session):
    user_id = await _user(db_session)
    token = ad_consent.make_token(user_id)
    r = await client.post("/consent/evening-deals", data={"t": token})
    assert r.status_code == 200
    records = await _consents(db_session, user_id)
    assert len(records) == 1 and records[0].source == "email_question"


async def test_forged_link_grants_nothing(client, db_session):
    user_id = await _user(db_session)
    r = await client.post("/consent/evening-deals", data={"t": f"{user_id}.9999999999.подделка"})
    assert r.status_code == 400
    assert await _consents(db_session, user_id) == []


# ── разовый вопрос ──────────────────────────────────────────────────────────

async def test_question_is_asked_once(client, db_session, monkeypatch):
    from app import tasks

    sent = []

    async def fake_tg(chat_id, text, reply_markup=None):
        sent.append((chat_id, reply_markup))
        return True   # дошло: отправка теперь обязана это сообщать

    monkeypatch.setattr(tasks, "_send_via_telegram", fake_tg)
    from app.models.models import NotifyChannel

    user_id = await _user(db_session, tg_chat_id=555, notify_channel=NotifyChannel.TG)

    assert (await tasks.ask_evening_deals_consent({"job_try": 1}, user_id)) == "asked:tg"
    assert (await tasks.ask_evening_deals_consent({"job_try": 1}, user_id)) == "skipped:already-asked"
    assert len(sent) == 1
    # и кнопка ведёт именно на согласие
    button = sent[0][1]["inline_keyboard"][0][0]
    assert button["callback_data"] == "edc:yes"


async def test_transient_failure_allows_retry(client, db_session, monkeypatch):
    """Отметку ставим до отправки (чтобы не спросить дважды), но при временном
    сбое снимаем — иначе человек так и не получит вопрос."""
    from app import tasks
    from app.models.models import NotifyChannel

    async def flaky(chat_id, text, reply_markup=None):
        raise tasks.TransientTaskError("сеть")

    monkeypatch.setattr(tasks, "_send_via_telegram", flaky)
    user_id = await _user(db_session, tg_chat_id=556, notify_channel=NotifyChannel.TG)
    try:
        await tasks.ask_evening_deals_consent({"job_try": 1}, user_id)
    except Exception:
        pass
    async with db_session() as db:
        assert ad_consent.was_asked(await db.get(User, user_id)) is False


async def test_already_consented_is_not_asked(client, db_session, monkeypatch):
    from app import tasks
    from app.models.models import NotifyChannel

    async def fail(*a, **kw):
        raise AssertionError("согласившегося не спрашивают")

    monkeypatch.setattr(tasks, "_send_via_telegram", fail)
    user_id = await _user(db_session, tg_chat_id=557, notify_channel=NotifyChannel.TG)
    async with db_session() as db:
        await ad_consent.grant(db, user_id=user_id, source="tg_prefs")
    assert (await tasks.ask_evening_deals_consent({"job_try": 1}, user_id)) == "skipped:already-consented"


# ── в обход журнала включить нельзя ─────────────────────────────────────────

def test_bot_toggles_route_advertising_through_consent():
    """Переключатели «Мои уведомления» — единственные места, где пишутся
    настройки. Рекламная тема в них обязана идти через ad_consent.grant."""
    import inspect

    import app.max_bot as max_bot
    import app.tg_bot as tg_bot

    tg_src = inspect.getsource(tg_bot.on_prefs_toggle)
    assert "OPT_IN_TOPICS" in tg_src and "ad_consent.grant" in tg_src
    max_src = inspect.getsource(max_bot._toggle_topic)
    assert "OPT_IN_TOPICS" in max_src and "ad_consent.grant" in max_src


async def test_undelivered_question_is_not_marked_as_asked(client, db_session, monkeypatch):
    """Регрессия со стейджа 16.09.2026: Telegram ответил «chat not found», а
    задача отчиталась «спросили» и пометила человека. Вопрос не дошёл — и
    больше никогда не был бы задан."""
    from app import tasks
    from app.models.models import NotifyChannel

    async def refused(chat_id, text, reply_markup=None):
        return False   # постоянный отказ: chat not found, бот заблокирован

    monkeypatch.setattr(tasks, "_send_via_telegram", refused)
    user_id = await _user(db_session, tg_chat_id=558, notify_channel=NotifyChannel.TG)

    assert (await tasks.ask_evening_deals_consent({"job_try": 1}, user_id)) == "undelivered:tg"
    async with db_session() as db:
        assert ad_consent.was_asked(await db.get(User, user_id)) is False


async def test_telegram_sender_reports_permanent_refusal(monkeypatch):
    """Отправка обязана сказать, что не дошло, а не выйти молча."""
    import httpx

    from app import tasks
    from app.core.config import settings

    monkeypatch.setattr(settings, "TG_BOT_TOKEN", "123:ABC")
    real_init = httpx.AsyncClient.__init__

    def mocked(self, *a, **kw):
        kw.pop("proxy", None)
        kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(
            400, json={"ok": False, "description": "Bad Request: chat not found"}))
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", mocked)
    assert await tasks._send_via_telegram(1, "привет") is False
    monkeypatch.undo()
