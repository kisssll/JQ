# tests/test_vk_bot.py
"""ВК-бот сообщества: привязка, доставка, кнопки, сайт.

ВК не подтверждает номер, поэтому главный риск здесь — привязать не тот
аккаунт. Тесты закрепляют: код одноразовый и выдаётся только вошедшему,
диалог принадлежит одному аккаунту, у человека с Telegram канал не
перебивается молча, а отказ ВК ведёт себя так же, как отказ Telegram.
"""
import json

import httpx
import pytest
from sqlalchemy import select

from app import tasks, vk_bot
import app.core.config as config_mod
from app.core.security import get_password_hash
from app.models.models import NotifyChannel, SupportRequest, User, UserRole
from app.services import vk_api, vk_link
from app.services.notify_channel import has_channel_clause, resolve, task_for


async def _user(db_session, phone="+79998880001", **kw) -> int:
    async with db_session() as db:
        user = User(phone=phone, full_name="Анна Клиентова", role=UserRole.CLIENT,
                    hashed_password=get_password_hash("Testpass1"), **kw)
        db.add(user)
        await db.commit()
        return user.id


async def _get(db_session, user_id):
    async with db_session() as db:
        return await db.get(User, user_id)


@pytest.fixture()
def vk(monkeypatch):
    """Бот включён, отправка и ответы на кнопки перехватываются."""
    # Соседние тесты пересоздают модуль конфига reload'ом, и объект настроек
    # у веб-страниц может оказаться ДРУГИМ, чем config_mod.settings. Патчим оба,
    # иначе /connect/vk видит пустой адрес сообщества и уводит в профиль.
    import app.web.views as views_mod
    for target in {id(config_mod.settings): config_mod.settings,
                   id(views_mod.settings): views_mod.settings}.values():
        monkeypatch.setattr(target, "VK_GROUP_ID", 241543992)
        monkeypatch.setattr(target, "VK_GROUP_SCREEN_NAME", "rumi_test")
    sent, answered = [], []

    async def send_message(peer_id, text, keyboard=None):
        sent.append({"peer": peer_id, "text": text, "kb": keyboard})

    async def answer_event(event_id, user_id, peer_id, snackbar=None):
        answered.append((event_id, snackbar))

    async def user_name(user_id):
        return "Анна Клиентова"

    monkeypatch.setattr(vk_api, "send_message", send_message)
    monkeypatch.setattr(vk_api, "answer_event", answer_event)
    monkeypatch.setattr(vk_api, "user_name", user_name)
    return type("VK", (), {"sent": sent, "answered": answered})


def _commands(keyboard) -> list[str]:
    out = []
    for row in (keyboard or {}).get("buttons", []):
        for button in row:
            payload = button["action"].get("payload")
            if payload:
                out.append(json.loads(payload)["c"])
    return out


def _msg(peer_id, text="", **extra):
    return {"message": {"peer_id": peer_id, "from_id": peer_id, "text": text, **extra}}


# ── клавиатура ──────────────────────────────────────────────────────────────

def test_callback_button_fits_vk_limits():
    button = vk_api.callback_button("х" * 60, "menu:bookings")
    assert len(button["action"]["label"]) == vk_api.LABEL_MAX
    assert json.loads(button["action"]["payload"]) == {"c": "menu:bookings"}
    assert len(button["action"]["payload"]) <= 255


# ── доставка ────────────────────────────────────────────────────────────────

def test_vk_is_a_channel():
    user = User(phone="+7", vk_peer_id=777, notify_channel=NotifyChannel.VK)
    assert resolve(user) == (NotifyChannel.VK, 777)
    assert task_for(NotifyChannel.VK) == "send_vk_message"


async def test_vk_only_user_is_reachable(client, db_session):
    user_id = await _user(db_session, vk_peer_id=701, notify_channel=NotifyChannel.VK)
    async with db_session() as db:
        ids = set((await db.execute(select(User.id).where(has_channel_clause()))).scalars())
    assert user_id in ids


@pytest.fixture()
def vk_api_answers(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "VK_BOT_TOKEN", "vk1.a.test")

    def answer(body):
        async def fake_post(self, url, data=None):
            return httpx.Response(200, request=httpx.Request("POST", url), json=body)
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    return answer


@pytest.mark.parametrize("code", [900, 901, 902])
async def test_vk_recipient_gone(vk_api_answers, code):
    vk_api_answers({"error": {"error_code": code, "error_msg": "нельзя"}})
    with pytest.raises(tasks.RecipientGone):
        await tasks._send_via_vk(1, "hi")


@pytest.mark.parametrize("code", [6, 9, 10])
async def test_vk_transient(vk_api_answers, code):
    vk_api_answers({"error": {"error_code": code, "error_msg": "позже"}})
    with pytest.raises(tasks.TransientTaskError):
        await tasks._send_via_vk(1, "hi")


async def test_vk_our_fault_does_not_blame_recipient(vk_api_answers):
    vk_api_answers({"error": {"error_code": 5, "error_msg": "User authorization failed"}})
    assert await tasks._send_via_vk(1, "hi") is False


async def test_vk_delivered(vk_api_answers):
    vk_api_answers({"response": 123})
    assert await tasks._send_via_vk(1, "hi") is True


async def test_reminder_goes_to_vk_not_telegram(monkeypatch):
    """Регрессия: _deliver слал всё, что не почта и не MAX, в Telegram —
    ВК-адрес ушёл бы в Telegram-чат с тем же номером."""
    calls = []

    async def vk_send(peer_id, text, keyboard=None):
        calls.append(("vk", peer_id))
        return True

    async def tg_send(*a, **kw):
        raise AssertionError("ушло в Telegram")

    monkeypatch.setattr(tasks, "_send_via_vk", vk_send)
    monkeypatch.setattr(tasks, "_send_via_telegram", tg_send)
    await tasks._deliver(NotifyChannel.VK, 42, "⏰")
    assert calls == [("vk", 42)]


async def test_vk_refusal_reroutes(client, db_session, monkeypatch):
    jobs = []

    class Pool:
        async def enqueue_job(self, name, *args, **kw):
            jobs.append((name, *args))

    async def get_pool():
        return Pool()

    async def refuse(peer_id, text, keyboard=None):
        raise tasks.RecipientGone("901")

    monkeypatch.setattr("app.core.worker.get_arq_pool", get_pool)
    monkeypatch.setattr(tasks, "_send_via_vk", refuse)
    user_id = await _user(db_session, vk_peer_id=702, email="v@example.com",
                          notify_channel=NotifyChannel.VK)

    assert await tasks.send_vk_message({"job_try": 1}, 702, "текст") == "gone:rerouted:1"
    assert jobs == [("send_email", "v@example.com", "Руми", "текст")]
    assert (await _get(db_session, user_id)).vk_broken_at is not None


# ── привязка ────────────────────────────────────────────────────────────────

async def test_link_code_is_one_time(client):
    code = await vk_link.create_code(5)
    assert await vk_link.pop_code(code) == 5
    assert await vk_link.pop_code(code) is None
    assert await vk_link.pop_code("support") is None


async def test_link_makes_vk_the_channel_when_there_was_none(client, db_session):
    user_id = await _user(db_session, email="a@example.com", notify_channel=NotifyChannel.EMAIL)
    async with db_session() as db:
        user = await db.get(User, user_id)
        assert await vk_link.link(db, user, 703, "Анна") is False
    user = await _get(db_session, user_id)
    assert (user.vk_peer_id, user.vk_name, user.notify_channel) == (703, "Анна", NotifyChannel.VK)


async def test_link_does_not_silently_override_telegram(client, db_session):
    user_id = await _user(db_session, tg_chat_id=1, notify_channel=NotifyChannel.TG)
    async with db_session() as db:
        user = await db.get(User, user_id)
        assert await vk_link.link(db, user, 704) is True
    assert (await _get(db_session, user_id)).notify_channel == NotifyChannel.TG


async def test_one_vk_dialog_belongs_to_one_account(client, db_session):
    old = await _user(db_session, vk_peer_id=705, vk_name="Старый")
    new = await _user(db_session, phone="+79998880002")
    async with db_session() as db:
        await vk_link.link(db, await db.get(User, new), 705)
    assert (await _get(db_session, old)).vk_peer_id is None
    assert (await _get(db_session, new)).vk_peer_id == 705


async def test_vk_id_login_remembers_vk_user(client, db_session, monkeypatch):
    from app.api.v1.endpoints import auth_vk

    monkeypatch.setattr(config_mod.settings, "VK_OAUTH_ENABLED", True)

    async def exchange(*a, **kw):
        return "token"

    async def profile(token):
        return {"user_id": "706", "phone": "79998880003", "first_name": "Иван"}

    monkeypatch.setattr(auth_vk, "_exchange_code", exchange)
    monkeypatch.setattr(auth_vk, "_fetch_profile", profile)
    r = await client.get("/api/v1/auth/vk/start", follow_redirects=False)
    state = dict(p.split("=", 1) for p in r.headers["location"].split("?", 1)[1].split("&"))["state"]
    await client.get("/api/v1/auth/vk/callback", params={"code": "c", "state": state, "device_id": "d"})

    async with db_session() as db:
        user = (await db.execute(select(User).where(User.phone == "+79998880003"))).scalar_one()
    assert user.vk_user_id == 706
    assert user.vk_peer_id is None   # писать ему бот ещё не может


# ── бот: сообщения ──────────────────────────────────────────────────────────

async def test_profile_link_binds_account(client, db_session, vk):
    user_id = await _user(db_session)
    code = await vk_link.create_code(user_id)

    await vk_bot.on_message_new(_msg(707, "Начать", ref=code))

    assert (await _get(db_session, user_id)).vk_peer_id == 707
    assert "привязан" in vk.sent[-1]["text"]


async def test_stale_link_is_explained(client, db_session, vk):
    """Код живёт 15 минут и сгорает при первом использовании — истёкший
    не должен молча приводить в меню."""
    await vk_bot.on_message_new(_msg(708, "Начать", ref="RUMI-AB23C"))
    assert "устарела" in vk.sent[-1]["text"]


async def test_code_sent_as_message_links_account(client, db_session, vk):
    """Кнопки «Начать» в непустом диалоге нет (жалоба 17.09.2026), поэтому
    код со страницы привязки можно просто отправить сообщением."""
    user_id = await _user(db_session, phone="+79998880031")
    code = await vk_link.create_code(user_id)
    await vk_bot.on_message_new(_msg(731, f"  {code.lower()} "))
    assert (await _get(db_session, user_id)).vk_peer_id == 731
    assert "привязан" in vk.sent[-1]["text"]


async def test_wrong_code_sent_as_message_is_explained(client, db_session, vk):
    await vk_bot.on_message_new(_msg(732, "RUMI-AB23C"))
    assert "не подошёл" in vk.sent[-1]["text"]


async def test_vk_id_user_is_recognised_without_code(client, db_session, vk):
    user_id = await _user(db_session, vk_user_id=709)
    await vk_bot.on_message_new(_msg(709, "привет"))
    user = await _get(db_session, user_id)
    assert user.vk_peer_id == 709 and user.vk_name == "Анна Клиентова"
    assert len(vk.sent) == 1 and "привязан" in vk.sent[0]["text"]


async def test_stranger_gets_explanation_not_menu(client, db_session, vk):
    await vk_bot.on_message_new(_msg(710, "Начать", payload='{"command":"start"}'))
    assert vk.sent[-1]["text"] == vk_bot.UNLINKED_TEXT
    assert "menu:bookings" not in _commands(vk.sent[-1]["kb"])
    assert "menu:support" in _commands(vk.sent[-1]["kb"])   # написать можно без привязки


async def test_linked_user_gets_menu(client, db_session, vk):
    await _user(db_session, vk_peer_id=711)
    await vk_bot.on_message_new(_msg(711, "Начать", payload='{"command":"start"}'))
    assert _commands(vk.sent[-1]["kb"]) == ["menu:bookings", "menu:prefs", "menu:support"]


async def test_footer_ref_opens_support_topics(client, db_session, vk):
    await vk_bot.on_message_new(_msg(712, "Начать", ref="support"))
    assert all(c.startswith("sup:") for c in _commands(vk.sent[-1]["kb"]))


async def test_group_chats_are_ignored(client, db_session, vk):
    await vk_bot.on_message_new(_msg(2_000_000_001, "Начать"))
    assert vk.sent == []


async def test_support_request_from_vk(client, db_session, vk):
    await vk_bot.on_message_event({"peer_id": 713, "user_id": 713, "event_id": "e1",
                                   "payload": {"c": "sup:question"}})
    await vk_bot.on_message_new(_msg(713, "Не могу найти салон на карте"))

    async with db_session() as db:
        request = (await db.execute(select(SupportRequest).where(SupportRequest.chat_id == 713))).scalar_one()
    assert request.channel == NotifyChannel.VK
    assert "принято" in vk.sent[-1]["text"]


# ── бот: кнопки ─────────────────────────────────────────────────────────────

async def test_every_button_press_is_answered(client, db_session, vk):
    """Без ответа на message_event у кнопки бесконечно крутится индикатор —
    даже если команда незнакомая или обработка упала."""
    await vk_bot.on_message_event({"peer_id": 714, "user_id": 714, "event_id": "e2",
                                   "payload": {"c": "что-то-странное"}})
    await vk_bot.on_message_event({"peer_id": 714, "user_id": 714, "event_id": "e3",
                                   "payload": "не json"})
    assert [e for e, _ in vk.answered] == ["e2", "e3"]


async def test_choose_vk_channel_button(client, db_session, vk):
    user_id = await _user(db_session, tg_chat_id=2, vk_peer_id=715, notify_channel=NotifyChannel.TG)
    await vk_bot.on_message_event({"peer_id": 715, "user_id": 715, "event_id": "e4",
                                   "payload": {"c": "chn:vk"}})
    assert (await _get(db_session, user_id)).notify_channel == NotifyChannel.VK


async def test_advertising_topic_needs_consent_record(client, db_session, vk):
    from app.services.notifications import TOPIC_PROMOS, wants
    from app.models.models import ConsentDocument, UserConsent

    user_id = await _user(db_session, vk_peer_id=716)
    await vk_bot.on_message_event({"peer_id": 716, "user_id": 716, "event_id": "e5",
                                   "payload": {"c": f"ntf:{TOPIC_PROMOS}"}})
    assert wants(await _get(db_session, user_id), TOPIC_PROMOS) is True
    async with db_session() as db:
        proof = (await db.execute(select(UserConsent).where(
            UserConsent.user_id == user_id,
            UserConsent.document == ConsentDocument.ADS_PROMOS))).scalar_one()
    assert proof.source == "vk_prefs"


async def test_deny_and_allow_messages(client, db_session, vk):
    user_id = await _user(db_session, vk_peer_id=717, email="d@example.com",
                          notify_channel=NotifyChannel.VK)
    await vk_bot.on_message_deny({"user_id": 717})
    assert resolve(await _get(db_session, user_id))[0] == NotifyChannel.EMAIL
    await vk_bot.on_message_allow({"user_id": 717})
    assert resolve(await _get(db_session, user_id))[0] == NotifyChannel.VK


# ── Long Poll ───────────────────────────────────────────────────────────────

async def test_long_poll_refreshes_key_and_feeds_updates(monkeypatch):
    import asyncio

    servers = []

    async def call(method, **params):
        servers.append(method)
        return {"server": "https://lp.vk.test/x", "key": f"k{len(servers)}", "ts": "1"}

    answers = iter([
        {"failed": 2},                                        # ключ истёк
        {"ts": "2", "updates": [{"type": "message_new", "object": {}}]},
    ])

    async def fake_get(self, url, params=None):
        try:
            body = next(answers)
        except StopIteration:
            raise asyncio.CancelledError
        return httpx.Response(200, request=httpx.Request("GET", url), json=body)

    fed = []

    class Feed:
        def feed(self, update):
            fed.append(update)

    monkeypatch.setattr(vk_api, "call", call)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(asyncio.CancelledError):
        await vk_bot.poll_forever(Feed())
    assert servers == ["groups.getLongPollServer", "groups.getLongPollServer"]
    assert fed == [{"type": "message_new", "object": {}}]


# ── сайт ────────────────────────────────────────────────────────────────────

async def _login(client, phone):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": "Testpass1"})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])


async def test_connect_button_issues_code_for_this_account(client, db_session, vk):
    user_id = await _user(db_session, phone="+79998880010")
    await _login(client, "+79998880010")

    r = await client.post("/api/v1/users/me/vk-connect", follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("https://vk.me/rumi_test?ref=RUMI-")
    assert await vk_link.pop_code(location.split("ref=", 1)[1]) == user_id


async def test_connect_requires_login(client, vk):
    r = await client.post("/api/v1/users/me/vk-connect", follow_redirects=False)
    assert r.headers["location"] == "/login"


async def test_disconnect_vk(client, db_session, vk):
    user_id = await _user(db_session, phone="+79998880011", vk_peer_id=718, vk_name="Анна",
                          email="x@example.com", notify_channel=NotifyChannel.VK)
    await _login(client, "+79998880011")
    r = await client.post("/api/v1/users/me/disconnect-channel", data={"channel": "vk"},
                          follow_redirects=False)
    assert "notify_channel_disconnected" in r.headers["location"]
    user = await _get(db_session, user_id)
    assert user.vk_peer_id is None and user.notify_channel == NotifyChannel.EMAIL


def test_profile_shows_whose_vk_is_linked(vk):
    from app.web.pages.profile import _notify_channel_block

    user = User(phone="+7", vk_peer_id=1, vk_name="Анна <b>Клиентова</b>",
                notify_channel=NotifyChannel.VK)
    html = _notify_channel_block(user)
    assert "подключён: Анна &lt;b&gt;Клиентова&lt;/b&gt;" in html   # имя видно и экранировано
    assert 'name="channel" value="vk"' in html


def test_footer_offers_vk(vk, monkeypatch):
    from app.web.components import footer
    from app.web.components.footer import render_footer

    # Подвал держит ссылку на настройки со времени импорта — подменяем в ней.
    monkeypatch.setattr(footer.settings, "VK_GROUP_ID", 241543992)
    monkeypatch.setattr(footer.settings, "VK_GROUP_SCREEN_NAME", "rumi_test")
    assert "https://vk.me/rumi_test?ref=support" in render_footer()


def test_reminder_step_offers_channel_without_blocking(vk):
    from app.web.pages.salon_detail import _reminder_channel_hint

    assert "Подключить ВКонтакте" in _reminder_channel_hint(User(phone="+7"))
    assert "код" in _reminder_channel_hint(User(phone="+7"))
    assert _reminder_channel_hint(User(phone="+7", vk_peer_id=1)) == ""
    assert _reminder_channel_hint(None) == ""


def test_connect_explains_missing_start_button(vk):
    """ВК показывает «Начать» только в пустом диалоге. Кто уже писал сообществу,
    кнопки не увидит — 16.09 и 17.09 на этом застряли двое. Выход — код со
    страницы привязки, и о нём должно быть сказано до перехода во ВКонтакте."""
    from app.web.pages.profile import _notify_channel_block

    html = _notify_channel_block(User(phone="+7", email="a@b.ru", notify_channel=NotifyChannel.EMAIL))
    assert "код" in html and "/connect/vk" in html
    linked = _notify_channel_block(User(phone="+7", vk_peer_id=1, notify_channel=NotifyChannel.VK))
    assert "код" not in linked   # привязанному подсказка не нужна


async def test_typed_message_after_profile_link_binds(client, db_session, vk):
    """Кнопки «Начать» нет — человек пишет сам, ВК передаёт метку с этим сообщением."""
    user_id = await _user(db_session, phone="+79998880020")
    code = await vk_link.create_code(user_id)
    await vk_bot.on_message_new(_msg(719, "привет", ref=code))
    assert (await _get(db_session, user_id)).vk_peer_id == 719


# ── страница привязки /connect/vk ───────────────────────────────────────────

async def test_connect_page_requires_login_and_returns_back(client, vk):
    """Человек приходит сюда из бота: потерять его на входе нельзя."""
    r = await client.get("/connect/vk")
    assert r.status_code == 302
    assert r.headers["location"] == "/login?redirect=%2Fconnect%2Fvk"


async def test_connect_page_shows_link_and_code(client, db_session, vk):
    from tests.conftest import register_user

    data = await register_user(client, "+79998880041")
    client.cookies.set("access_token", data["access_token"])
    r = await client.get("/connect/vk")
    assert r.status_code == 200
    assert "https://vk.me/rumi_test?ref=RUMI-" in r.text
    # код виден на странице текстом: кнопки «Начать» в непустом диалоге нет,
    # и тогда человек отправляет код сообщением
    import re
    code = re.search(r"RUMI-[A-Z0-9]{5}", r.text).group(0)
    assert vk_link.looks_like_code(code)
    assert r.text.count(code) >= 2          # в ссылке и отдельной строкой
    assert await vk_link.pop_code(code) is not None
    client.cookies.clear()


async def test_connect_page_tells_when_already_linked(client, db_session, vk):
    """Привязанному показываем, К КАКОМУ аккаунту ВК он привязан: если ссылку
    успел открыть кто-то другой, видно чужое имя и есть «Отвязать»."""
    from sqlalchemy import update as _update
    from tests.conftest import register_user

    data = await register_user(client, "+79998880042")
    client.cookies.set("access_token", data["access_token"])
    async with db_session() as db:
        await db.execute(_update(User).where(User.phone == "+79998880042")
                         .values(vk_peer_id=742, vk_name="Диана Мальцева"))
        await db.commit()
    r = await client.get("/connect/vk")
    assert "уже подключён" in r.text and "Диана Мальцева" in r.text
    assert "Отвязать" in r.text
    client.cookies.clear()


# ── конкурс ─────────────────────────────────────────────────────────────────

async def test_contest_entry_through_the_bot(client, db_session, vk, monkeypatch):
    """Заявку подают прямо в боте: гугл-форма отпадает (152-ФЗ), а данные
    сразу попадают к нам вместе с записью согласия."""
    from app.models.models import ContestEntry
    from app.services import contest

    monkeypatch.setattr(contest, "accepts_entries", lambda today=None: True)
    monkeypatch.setattr(contest, "is_menu_visible", lambda today=None: True)
    user_id = await _user(db_session, phone="+79998880051", vk_peer_id=751)

    await vk_bot._dispatch_command(751, contest.CMD_START)
    assert "Хеллоуин" in vk.sent[-1]["text"]
    assert contest.CMD_APPLY in _commands(vk.sent[-1]["kb"])

    await vk_bot._dispatch_command(751, contest.CMD_APPLY)
    assert "Вопрос 1 из 4" in vk.sent[-1]["text"]
    for answer in ("Алина Агеева", "Томск", "https://vk.com/wall-1_1", "@alina"):
        await vk_bot.on_message_new(_msg(751, answer))
    assert contest.CMD_SEND in _commands(vk.sent[-1]["kb"])

    await vk_bot._dispatch_command(751, contest.CMD_SEND)
    async with db_session() as db:
        entry = (await db.execute(select(ContestEntry))).scalars().one()
    assert entry.user_id == user_id and entry.name == "Алина Агеева"
    assert "принята" in vk.sent[-1]["text"]


async def test_contest_answers_do_not_become_support_tickets(client, db_session, vk, monkeypatch):
    """Человек отвечает на вопрос анкеты, а не пишет в поддержку."""
    from app.services import contest

    monkeypatch.setattr(contest, "accepts_entries", lambda today=None: True)
    await vk_bot._dispatch_command(752, contest.CMD_APPLY)
    await vk_bot.on_message_new(_msg(752, "Алина Агеева"))
    async with db_session() as db:
        assert (await db.execute(select(SupportRequest))).scalars().first() is None
    assert "Вопрос 2 из 4" in vk.sent[-1]["text"]


def test_contest_button_hidden_outside_contest(monkeypatch):
    from app.services import contest

    monkeypatch.setattr(contest, "is_menu_visible", lambda today=None: False)
    assert all("contest" not in c for c in _commands(vk_bot._menu_kb()))
    monkeypatch.setattr(contest, "is_menu_visible", lambda today=None: True)
    assert contest.CMD_START in _commands(vk_bot._menu_kb())
