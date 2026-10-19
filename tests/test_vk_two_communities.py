# tests/test_vk_two_communities.py
"""Два сообщества ВКонтакте: клиентское и бизнесовое (решение 0013).

Главный риск задачи — написать «не тем» сообществом. ВК ответит отказом 901,
наш код примет это за «человек закрыл сообщения» и пометит канал сломанным:
человек молча перестанет получать уведомления. Тесты закрепляют:

  * каждое сообщение уходит токеном СВОЕГО сообщества на адрес из СВОЕГО поля;
  * нет адреса в нужном сообществе — запасной канал, а не отметка «сломан»;
  * отказ одного сообщества не гасит второе;
  * привязка к одному сообществу переносится на второе без кода, а чужой
    человек без кода не привязывается;
  * у сообществ разные меню, тексты — из общего реестра;
  * бот без ключа спит, а не падает.

Адреса клиентского и бизнесового диалогов в большинстве тестов НАРОЧНО разные:
в жизни peer_id в обоих сообществах один и тот же, и тогда тест не отличил бы
«взяли не то поле». Там, где важно именно совпадение (отметка отказа), адрес
одинаковый — как в жизни.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

import app.core.config as config_mod
from app import tasks, vk_bot
from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, NotifyChannel, Salon, SalonMember, SalonRole, Service,
    SupportRequest, SupportStatus, SupportTopic, User, UserRole,
)
from app.services import bot_texts, notifications, vk_api, vk_community
from app.services.notify_channel import broken_channels, resolve

CLIENT_TOKEN = "vk1.client-test"
BUSINESS_TOKEN = "vk1.business-test"


@pytest.fixture()
def two_communities(monkeypatch):
    """Оба сообщества настроены, у каждого свой ключ и свой id."""
    import app.web.views as views_mod

    for target in {id(config_mod.settings): config_mod.settings,
                   id(views_mod.settings): views_mod.settings}.values():
        monkeypatch.setattr(target, "VK_BOT_TOKEN", BUSINESS_TOKEN)
        monkeypatch.setattr(target, "VK_GROUP_ID", 1001)
        monkeypatch.setattr(target, "VK_GROUP_SCREEN_NAME", "rumi_biz")
        monkeypatch.setattr(target, "VK_CLIENTS_BOT_TOKEN", CLIENT_TOKEN)
        monkeypatch.setattr(target, "VK_CLIENTS_GROUP_ID", 2002)
        monkeypatch.setattr(target, "VK_CLIENTS_GROUP_SCREEN_NAME", "rumi_clients")
        monkeypatch.setattr(target, "TG_NOTIFY_ENABLED", True)
    monkeypatch.setattr(notifications.settings, "TG_NOTIFY_ENABLED", True)


@pytest.fixture()
def role(monkeypatch, two_communities):
    """Сменить роль процесса бота: role("client") / role("business")."""
    def set_role(value: str) -> None:
        monkeypatch.setattr(config_mod.settings, "VK_BOT_ROLE", value)
    return set_role


@pytest.fixture()
def bot(monkeypatch, two_communities):
    """Ответы бота перехватываются вместе с ключом, которым они ушли бы."""
    sent, answered = [], []

    async def send_message(peer_id, text, keyboard=None, *, token):
        sent.append({"peer": peer_id, "text": text, "kb": keyboard, "token": token})

    async def answer_event(event_id, user_id, peer_id, snackbar=None, *, token):
        answered.append((event_id, token))

    async def user_name(user_id, *, token):
        return "Анна Клиентова"

    monkeypatch.setattr(vk_api, "send_message", send_message)
    monkeypatch.setattr(vk_api, "answer_event", answer_event)
    monkeypatch.setattr(vk_api, "user_name", user_name)
    return type("Bot", (), {"sent": sent, "answered": answered})


class _Pool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, fn, *args, **kwargs):
        self.jobs.append((fn, args, {k: v for k, v in kwargs.items() if not k.startswith("_")}))

    def vk(self):
        """(адрес, сообщество) всех поставленных сообщений во ВК."""
        return sorted((a[0], kw["community"]) for fn, a, kw in self.jobs if fn == "send_vk_message")


@pytest.fixture()
def pool(monkeypatch):
    p = _Pool()

    async def get_pool():
        return p

    monkeypatch.setattr(notifications, "get_arq_pool", get_pool)
    monkeypatch.setattr("app.core.worker.get_arq_pool", get_pool)
    return p


def _vk_fields(base: int) -> dict:
    """Клиентский диалог — base+1, бизнесовый — base+2."""
    return {"vk_client_peer_id": base + 1, "vk_business_peer_id": base + 2,
            "notify_channel": NotifyChannel.VK}


async def _user(db_session, phone, **kw) -> int:
    async with db_session() as db:
        user = User(phone=phone, full_name="Тест Тестов", role=kw.pop("role", UserRole.CLIENT),
                    hashed_password=get_password_hash("Testpass1"), **kw)
        db.add(user)
        await db.commit()
        return user.id


async def _get(db_session, user_id) -> User:
    async with db_session() as db:
        return await db.get(User, user_id)


async def _salon_with_booking(db_session, *, status=BookingStatus.PENDING, client_kw=None):
    """Владелец 100, мастер 200, клиент 300 — у всех оба диалога ВК."""
    async with db_session() as db:
        owner = User(phone="+79990013100", hashed_password="x", role=UserRole.BUSINESS,
                     full_name="Владелец", **_vk_fields(100))
        master_user = User(phone="+79990013200", hashed_password="x", role=UserRole.MASTER,
                           full_name="Мастер", **_vk_fields(200))
        client_user = User(phone="+79990013300", hashed_password="x", role=UserRole.CLIENT,
                           full_name="Клиент", **(client_kw or _vk_fields(300)))
        db.add_all([owner, master_user, client_user])
        await db.flush()
        salon = Salon(name="Два сообщества", address="ул. Тестовая, 1", timezone="Europe/Moscow",
                      creator_id=owner.id, latitude=55.75, longitude=37.62, phone="+79990013000")
        db.add(salon)
        await db.flush()
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, is_active=True, permissions={}))
        master = Master(user_id=master_user.id, salon_id=salon.id, specialization="стрижка")
        db.add(master)
        await db.flush()
        service = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
        db.add(service)
        await db.flush()
        booking = Booking(
            client_id=client_user.id, master_id=master.id, service_id=service.id,
            start_time=datetime.now() + timedelta(days=1),
            end_time=datetime.now() + timedelta(days=1, hours=1),
            status=status, final_price=1000,
        )
        db.add(booking)
        await db.commit()
        return booking.id, salon.id, client_user.id, owner.id


# ── отправка: каждый тип — своим сообществом ────────────────────────────────

async def test_new_booking_client_gets_client_community_salon_gets_business(
        client, db_session, two_communities, pool):
    booking_id, *_ = await _salon_with_booking(db_session)
    async with db_session() as db:
        await notifications.notify_booking_created(db, await db.get(Booking, booking_id))
    # клиент — «Вы записаны» клиентским; мастер и владелец — бизнесовым
    assert pool.vk() == sorted([(102, "business"), (202, "business"), (301, "client")])


async def test_cancellation_client_gets_client_community_salon_gets_business(
        client, db_session, two_communities, pool):
    booking_id, *_ = await _salon_with_booking(db_session)
    async with db_session() as db:
        await notifications.notify_booking_cancelled(db, await db.get(Booking, booking_id))
    assert pool.vk() == sorted([(102, "business"), (202, "business"), (301, "client")])


async def test_reminder_goes_through_client_community(client, db_session, two_communities,
                                                      monkeypatch):
    sent = []

    async def vk_send(peer_id, text, keyboard=None, *, community):
        sent.append((peer_id, community))
        return True

    monkeypatch.setattr(tasks, "_send_via_vk", vk_send)
    booking_id, *_ = await _salon_with_booking(db_session)
    assert await tasks.send_booking_reminder({"job_try": 1}, booking_id) == "sent"
    assert sent == [(301, "client")]


async def test_review_request_goes_through_client_community(client, db_session, pool):
    booking_id, *_ = await _salon_with_booking(db_session, status=BookingStatus.COMPLETED)
    assert await tasks.ask_for_review({"job_try": 1}, booking_id) == "asked"
    [(fn, args, kw)] = pool.jobs
    assert (fn, args[0], kw) == ("send_review_request_vk", 301, {"community": "client"})


async def test_evening_deals_go_through_client_community(client, db_session, two_communities,
                                                         pool, monkeypatch):
    import app.services.evening_deals_service as deals

    async def yes(db):
        return True

    monkeypatch.setattr(deals, "any_windows_today", yes)
    await _user(db_session, "+79990013400", tg_notify_prefs={"promos": True}, **_vk_fields(400))
    await tasks.send_evening_deals_blast({"job_try": 1})
    assert pool.vk() == [(401, "client")]


async def test_promo_question_goes_through_client_community(client, db_session, two_communities,
                                                            monkeypatch):
    sent = []

    async def vk_send(peer_id, text, keyboard=None, *, community):
        sent.append((peer_id, community))
        return True

    monkeypatch.setattr(tasks, "_send_via_vk", vk_send)
    user_id = await _user(db_session, "+79990013500", **_vk_fields(500))
    assert await tasks.ask_promo_consent({"job_try": 1}, user_id) == "asked:vk"
    assert sent == [(501, "client")]


async def test_tariff_goes_through_business_community(client, db_session, two_communities, pool):
    _, salon_id, _, _ = await _salon_with_booking(db_session)
    async with db_session() as db:
        await notifications.notify_subscription(db, await db.get(Salon, salon_id), "доступ до 01.11")
    assert pool.vk() == [(102, "business")]


async def test_model_tariff_goes_through_client_community(client, db_session, two_communities,
                                                          pool):
    """Тариф «модели» платит сам человек как клиент — решение отмечено в
    отчёте как спорное, владелец может перевернуть."""
    user_id = await _user(db_session, "+79990013600", **_vk_fields(600))
    async with db_session() as db:
        await notifications.notify_model_subscription(db, await db.get(User, user_id), "оплачено")
    assert pool.vk() == [(601, "client")]


async def test_admin_alert_goes_through_business_community(client, db_session, two_communities,
                                                           pool):
    await _user(db_session, "+79990013700", role=UserRole.ADMIN, **_vk_fields(700))
    async with db_session() as db:
        await notifications.notify_admins(db, "Новая заявка на подключение салона")
    assert pool.vk() == [(702, "business")]


async def test_new_review_goes_through_business_community(client, db_session, two_communities,
                                                          pool):
    from app.models.models import Review, ReviewTargetType

    _, salon_id, client_id, _ = await _salon_with_booking(db_session)
    async with db_session() as db:
        review = Review(salon_id=salon_id, client_id=client_id, rating=5,
                        target_type=ReviewTargetType.SALON)
        db.add(review)
        await db.commit()
        await notifications.notify_new_review(db, review)
    assert pool.vk() == [(102, "business")]


async def test_support_answer_to_business_request_goes_through_business_community(
        client, db_session, two_communities, pool):
    from app.services.support import send_answer

    user_id = await _user(db_session, "+79990013800", **_vk_fields(800))
    admin_id = await _user(db_session, "+79990013801", role=UserRole.ADMIN)
    async with db_session() as db:
        request = SupportRequest(topic=SupportTopic.QUESTION, text="вопрос", user_id=user_id,
                                 channel=NotifyChannel.VK, chat_id=802,
                                 vk_audience="business", status=SupportStatus.NEW)
        db.add(request)
        await db.commit()
        await send_answer(db, request, "ответ", await db.get(User, admin_id))
    assert pool.vk() == [(802, "business")]


async def test_support_answer_to_unlinked_business_chat_goes_through_business_community(
        client, db_session, two_communities, pool):
    from app.services.support import send_answer

    admin_id = await _user(db_session, "+79990013811", role=UserRole.ADMIN)
    async with db_session() as db:
        request = SupportRequest(topic=SupportTopic.QUESTION, text="вопрос", channel=NotifyChannel.VK,
                                 chat_id=8812, vk_audience="business", status=SupportStatus.NEW)
        db.add(request)
        await db.commit()
        await send_answer(db, request, "ответ", await db.get(User, admin_id))
    assert pool.vk() == [(8812, "business")]


# ── транспорт: токен выбирается по сообществу, а не по настройке ────────────

@pytest.fixture()
def vk_http(monkeypatch, two_communities):
    """Запросы к API ВК: какой ключ и какой адрес ушли."""
    calls = []

    async def fake_post(self, url, data=None):
        calls.append({"method": url.rsplit("/", 1)[-1], "token": data["access_token"],
                      "peer": data.get("peer_id")})
        return httpx.Response(200, request=httpx.Request("POST", url), json={"response": 1})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


@pytest.mark.parametrize("community, token", [("client", CLIENT_TOKEN), ("business", BUSINESS_TOKEN)])
async def test_message_goes_with_its_community_token(vk_http, community, token):
    assert await tasks.send_vk_message({"job_try": 1}, 42, "текст", community=community) == "sent"
    assert vk_http == [{"method": "messages.send", "token": token, "peer": 42}]


async def test_review_stars_go_with_client_token(vk_http):
    await tasks.send_review_request_vk({"job_try": 1}, 42, 7, "Как прошло?", community="client")
    assert [c["token"] for c in vk_http] == [CLIENT_TOKEN]


async def test_service_rating_goes_with_business_token(vk_http):
    await tasks.send_service_rating_vk({"job_try": 1}, 42)
    assert [c["token"] for c in vk_http] == [BUSINESS_TOKEN]


async def test_legacy_queued_job_without_community_is_business(vk_http):
    """Задачи, поставленные до разделения, адресованы старому сообществу —
    а оно стало бизнесовым."""
    await tasks.send_vk_message({"job_try": 1}, 42, "текст")
    assert [c["token"] for c in vk_http] == [BUSINESS_TOKEN]


async def test_vk_api_refuses_to_guess_the_token():
    """Забытый ключ — ошибка, а не письмо от сообщества «по умолчанию»."""
    with pytest.raises(ValueError):
        await vk_api.call("messages.send", token="", peer_id=1)


# ── нет адреса — не сломан ──────────────────────────────────────────────────

async def test_missing_client_address_falls_back_without_breaking_vk(
        client, db_session, two_communities, pool):
    """Человек выбрал ВК, но писал только бизнесовому сообществу. Клиентское
    сообщение уходит почтой, и ВК НЕ помечается сломанным: это не отказ."""
    user_id = await _user(db_session, "+79990013900", email="only-biz@example.com",
                          vk_business_peer_id=902, notify_channel=NotifyChannel.VK)
    user = await _get(db_session, user_id)
    assert await notifications.deliver(user, "Вы записаны", audience="client") is True
    assert pool.jobs == [("send_email", ("only-biz@example.com", "Руми", "Вы записаны"), {})]

    user = await _get(db_session, user_id)
    assert user.vk_business_broken_at is None and user.vk_client_broken_at is None
    assert broken_channels(user) == []
    # и бизнесовое по-прежнему идёт во ВК
    assert resolve(user, "business") == (NotifyChannel.VK, 902)


async def test_missing_client_address_reminder_goes_by_email(client, db_session, two_communities,
                                                             monkeypatch):
    """То же сквозь задачу напоминания: во ВК не ходим вовсе."""
    mails, vk = [], []

    async def smtp(to, subject, body, html=None):
        mails.append(to)
        return True

    async def vk_send(*a, **kw):
        vk.append(a)
        return True

    monkeypatch.setattr(tasks, "_send_via_smtp", smtp)
    monkeypatch.setattr(tasks, "_send_via_vk", vk_send)
    booking_id, _, client_id, _ = await _salon_with_booking(db_session, client_kw={
        "vk_business_peer_id": 302, "email": "c@example.com", "notify_channel": NotifyChannel.VK})
    assert await tasks.send_booking_reminder({"job_try": 1}, booking_id) == "sent"
    assert (mails, vk) == (["c@example.com"], [])
    client_user = await _get(db_session, client_id)
    assert client_user.vk_business_broken_at is None and client_user.vk_client_broken_at is None


async def test_missing_business_address_falls_back_without_breaking_vk(
        client, db_session, two_communities, pool):
    user_id = await _user(db_session, "+79990013910", email="only-cli@example.com",
                          vk_client_peer_id=911, notify_channel=NotifyChannel.VK)
    assert await notifications.deliver(await _get(db_session, user_id), "Тариф",
                                       audience="business") is True
    assert [j[0] for j in pool.jobs] == ["send_email"]
    assert broken_channels(await _get(db_session, user_id)) == []


# ── отказ одного сообщества не гасит второе ─────────────────────────────────

async def test_refusal_in_client_community_keeps_business(client, db_session, two_communities,
                                                          pool, monkeypatch):
    """Адрес в обоих сообществах один — как в жизни. Отказ клиентского метит
    только клиентское поле."""
    async def refuse(peer_id, text, keyboard=None, *, community):
        raise tasks.RecipientGone("901")

    monkeypatch.setattr(tasks, "_send_via_vk", refuse)
    user_id = await _user(db_session, "+79990013920", email="r@example.com",
                          vk_client_peer_id=920, vk_business_peer_id=920,
                          notify_channel=NotifyChannel.VK)

    result = await tasks.send_vk_message({"job_try": 1}, 920, "Напоминание", community="client")
    assert result == "gone:rerouted:1"
    user = await _get(db_session, user_id)
    assert user.vk_client_broken_at is not None
    assert user.vk_business_broken_at is None
    assert resolve(user, "business") == (NotifyChannel.VK, 920)
    # досылка — почтой, а не бизнесовым сообществом
    assert pool.jobs == [("send_email", ("r@example.com", "Руми", "Напоминание"), {})]


async def test_refusal_in_business_community_keeps_client(client, db_session, two_communities,
                                                          pool, monkeypatch):
    async def refuse(peer_id, text, keyboard=None, *, community):
        raise tasks.RecipientGone("901")

    monkeypatch.setattr(tasks, "_send_via_vk", refuse)
    user_id = await _user(db_session, "+79990013930", vk_client_peer_id=930,
                          vk_business_peer_id=930, notify_channel=NotifyChannel.VK)
    await tasks.send_vk_message({"job_try": 1}, 930, "Тариф", community="business")
    user = await _get(db_session, user_id)
    assert user.vk_business_broken_at is not None and user.vk_client_broken_at is None
    assert resolve(user, "client") == (NotifyChannel.VK, 930)


async def test_deny_in_one_bot_keeps_the_other(client, db_session, bot, role):
    user_id = await _user(db_session, "+79990013940", vk_client_peer_id=940,
                          vk_business_peer_id=940, notify_channel=NotifyChannel.VK)
    role("client")
    await vk_bot.on_message_deny({"user_id": 940})
    user = await _get(db_session, user_id)
    assert user.vk_client_broken_at is not None and user.vk_business_broken_at is None

    # «Начать» в бизнесовом сообществе клиентскую отметку не снимает
    role("business")
    await vk_bot.on_message_allow({"user_id": 940})
    assert (await _get(db_session, user_id)).vk_client_broken_at is not None
    role("client")
    await vk_bot.on_message_allow({"user_id": 940})
    assert (await _get(db_session, user_id)).vk_client_broken_at is None


async def test_telegram_refusal_reroutes_to_the_vk_community_person_has(
        client, db_session, two_communities, pool, monkeypatch):
    """Задачи Telegram тип сообщения не знают. Досылка во ВК должна идти тем
    сообществом, с которым у человека есть диалог, — иначе отказ и ложная
    отметка уже во ВК."""
    async def tg_refuse(chat_id, text, reply_markup=None):
        raise tasks.RecipientGone("blocked")

    monkeypatch.setattr(tasks, "_send_via_telegram", tg_refuse)
    await _user(db_session, "+79990013950", tg_chat_id=950, vk_business_peer_id=951,
                notify_channel=NotifyChannel.TG)
    await tasks.send_tg_message({"job_try": 1}, 950, "текст")
    assert pool.vk() == [(951, "business")]


# ── автопривязка между сообществами ─────────────────────────────────────────

async def test_business_linked_user_is_recognised_by_client_bot(client, db_session, bot, role):
    user_id = await _user(db_session, "+79990014000", vk_business_peer_id=1000,
                          notify_channel=NotifyChannel.VK)
    role("client")
    await vk_bot.on_message_new({"message": {"peer_id": 1000, "from_id": 1000, "text": "привет"}})

    user = await _get(db_session, user_id)
    assert user.vk_client_peer_id == 1000
    assert user.vk_business_peer_id == 1000
    assert len(bot.sent) == 1
    assert bot.sent[0]["text"].startswith("Узнали вас")
    assert bot.sent[0]["token"] == CLIENT_TOKEN


async def test_client_linked_user_is_recognised_by_business_bot(client, db_session, bot, role):
    user_id = await _user(db_session, "+79990014010", vk_client_peer_id=1010,
                          notify_channel=NotifyChannel.VK)
    role("business")
    await vk_bot.on_message_new({"message": {"peer_id": 1010, "from_id": 1010, "text": "привет"}})

    user = await _get(db_session, user_id)
    assert (user.vk_business_peer_id, user.vk_client_peer_id) == (1010, 1010)
    assert bot.sent[0]["text"].startswith("Узнали вас")
    assert bot.sent[0]["token"] == BUSINESS_TOKEN


async def test_stranger_is_not_linked_and_gets_code_invitation(client, db_session, bot, role):
    """Чужой человек: его id ВК нет ни в одном поле — привязки нет, есть
    обычное приглашение со страницей кода, ведущей обратно в это сообщество."""
    other_id = await _user(db_session, "+79990014020", vk_user_id=1021,
                           vk_client_peer_id=1022, vk_business_peer_id=1023)
    role("client")
    await vk_bot.on_message_new({"message": {"peer_id": 1020, "from_id": 1020, "text": "Начать",
                                             "payload": '{"command":"start"}'}})

    async with db_session() as db:
        linked = (await db.execute(select(User.id).where(
            (User.vk_client_peer_id == 1020) | (User.vk_business_peer_id == 1020)
        ))).scalars().all()
    assert linked == []
    other = await _get(db_session, other_id)
    assert (other.vk_client_peer_id, other.vk_business_peer_id) == (1022, 1023)

    invitation = bot.sent[-1]
    assert invitation["text"] == vk_bot._unlinked_text()
    assert bot_texts.vk_link_offer("client") in invitation["text"]
    links = [b["action"].get("link") for row in invitation["kb"]["buttons"] for b in row]
    assert any(link and link.endswith("/connect/vk?to=client") for link in links)


async def test_code_links_to_the_community_it_was_sent_to(client, db_session, bot, role):
    from app.services import vk_link

    user_id = await _user(db_session, "+79990014030")
    code = await vk_link.create_code(user_id)
    role("client")
    await vk_bot.on_message_new({"message": {"peer_id": 1030, "from_id": 1030, "text": code}})
    user = await _get(db_session, user_id)
    assert (user.vk_client_peer_id, user.vk_business_peer_id) == (1030, None)


# ── процесс бота ────────────────────────────────────────────────────────────

def _labels(keyboard) -> list[str]:
    return [b["action"]["label"] for row in keyboard["buttons"] for b in row]


def test_menus_differ_and_come_from_registry(role, monkeypatch):
    from app.services import contest

    monkeypatch.setattr(contest, "is_menu_visible", lambda today=None: False)
    role("client")
    client_menu = _labels(vk_bot._menu_kb())
    role("business")
    business_menu = _labels(vk_bot._menu_kb())

    assert client_menu == [bot_texts.MENU_BOOKINGS, bot_texts.MENU_PREFS, bot_texts.MENU_EVENING,
                           bot_texts.MENU_SUPPORT]
    assert business_menu == [bot_texts.MENU_PANEL, bot_texts.MENU_TARIFF,
                             bot_texts.MENU_SALON_SUPPORT]
    assert not set(client_menu) & set(business_menu)
    registry = {getattr(bot_texts, n) for n in dir(bot_texts) if n.startswith("MENU_")}
    assert set(client_menu) | set(business_menu) <= registry


def test_contest_button_only_in_business_menu(role, monkeypatch):
    from app.services import contest

    monkeypatch.setattr(contest, "is_menu_visible", lambda today=None: True)
    role("client")
    assert bot_texts.MENU_CONTEST not in _labels(vk_bot._menu_kb())
    role("business")
    assert bot_texts.MENU_CONTEST in _labels(vk_bot._menu_kb())


async def test_each_process_answers_with_its_own_token(client, db_session, bot, role):
    role("client")
    await vk_bot.on_message_new({"message": {"peer_id": 1050, "from_id": 1050, "text": "меню"}})
    role("business")
    await vk_bot.on_message_new({"message": {"peer_id": 1050, "from_id": 1050, "text": "меню"}})
    tokens = [m["token"] for m in bot.sent]
    assert CLIENT_TOKEN in tokens and BUSINESS_TOKEN in tokens
    assert tokens.index(BUSINESS_TOKEN) > tokens.index(CLIENT_TOKEN)
    assert set(tokens[:tokens.index(BUSINESS_TOKEN)]) == {CLIENT_TOKEN}


@pytest.mark.parametrize("bot_role, token_setting", [("client", "VK_CLIENTS_BOT_TOKEN"),
                                                     ("business", "VK_BOT_TOKEN")])
async def test_bot_without_token_waits_instead_of_crashing(role, monkeypatch, bot_role,
                                                           token_setting):
    calls = []

    async def call(*a, **kw):
        calls.append(a)
        raise AssertionError("без ключа ходить в ВК нельзя")

    monkeypatch.setattr(vk_api, "call", call)
    role(bot_role)
    monkeypatch.setattr(config_mod.settings, token_setting, "")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(vk_bot.main(), timeout=0.3)
    assert calls == []


async def test_unknown_role_fails_loudly(role):
    role("clients")
    with pytest.raises(ValueError):
        await asyncio.wait_for(vk_bot.main(), timeout=0.3)


async def test_long_poll_uses_own_community(role, monkeypatch):
    seen = []

    async def call(method, *, token, **params):
        seen.append((method, token, params.get("group_id")))
        raise asyncio.CancelledError

    monkeypatch.setattr(vk_api, "call", call)
    role("client")
    with pytest.raises(asyncio.CancelledError):
        await vk_bot.poll_forever()
    assert seen == [("groups.getLongPollServer", CLIENT_TOKEN, 2002)]


# ── сайт и выкат ────────────────────────────────────────────────────────────

async def test_connect_page_returns_to_the_community_it_came_from(client, db_session,
                                                                  two_communities):
    from tests.conftest import register_user

    data = await register_user(client, "+79990014060")
    client.cookies.set("access_token", data["access_token"])
    r = await client.get("/connect/vk?to=business")
    assert "vk.me/rumi_biz?ref=" in r.text
    r = await client.get("/connect/vk")   # по умолчанию — клиентское
    assert "vk.me/rumi_clients?ref=" in r.text
    client.cookies.clear()


@pytest.mark.parametrize("path", ["docker-compose.prod.yml", "docker-compose.staging.yml"])
def test_compose_runs_two_bots_each_with_one_token(path):
    """Два процесса, образ и команда одни; каждому оставлен только свой ключ."""
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    services = yaml.safe_load((root / path).read_text())["services"]
    biz, cli = services["vk-bot"], services["vk-client-bot"]
    assert biz["image"] == cli["image"] and biz["command"] == cli["command"]
    assert biz["environment"]["VK_BOT_ROLE"] == "business"
    assert biz["environment"]["VK_CLIENTS_BOT_TOKEN"] == ""
    assert cli["environment"]["VK_BOT_ROLE"] == "client"
    assert cli["environment"]["VK_BOT_TOKEN"] == ""


# ── поддержка в клиентском сообществе ───────────────────────────────────────

async def _requests(db_session, chat_id):
    async with db_session() as db:
        return (await db.execute(select(SupportRequest).where(
            SupportRequest.chat_id == chat_id))).scalars().all()


async def _write_support(peer, button_topic="sup:question", text="Не получается отменить запись"):
    await vk_bot.on_message_event({"peer_id": peer, "user_id": peer, "event_id": "m",
                                   "payload": {"c": "menu:support"}})
    await vk_bot.on_message_event({"peer_id": peer, "user_id": peer, "event_id": "t",
                                   "payload": {"c": button_topic}})
    await vk_bot.on_message_new({"message": {"peer_id": peer, "from_id": peer, "text": text}})


@pytest.mark.parametrize("bot_role, token", [("client", CLIENT_TOKEN), ("business", BUSINESS_TOKEN)])
async def test_support_request_remembers_its_community(client, db_session, bot, role, bot_role, token):
    role(bot_role)
    await _write_support(1100)
    [request] = await _requests(db_session, 1100)
    assert request.vk_audience == bot_role
    # весь диалог ведётся токеном своего сообщества
    assert bot.sent and {m["token"] for m in bot.sent} == {token}
    assert any("принято" in m["text"] for m in bot.sent)


async def test_client_menu_has_support_but_not_service_rating(client, db_session, bot, role):
    role("client")
    assert bot_texts.MENU_SUPPORT in _labels(vk_bot._menu_kb())
    assert bot_texts.MENU_SALON_SUPPORT not in _labels(vk_bot._menu_kb())
    await vk_bot.on_message_event({"peer_id": 1110, "user_id": 1110, "event_id": "m",
                                   "payload": {"c": "menu:support"}})
    topics = [b["action"]["label"] for row in bot.sent[-1]["kb"]["buttons"] for b in row]
    assert "Оценка сервиса" not in topics and len(topics) == 4
    # опрос владельцев клиентскому боту не принадлежит: оценка не сохраняется
    await vk_bot.on_message_event({"peer_id": 1110, "user_id": 1110, "event_id": "n",
                                   "payload": {"c": "nps:5"}})
    assert await _requests(db_session, 1110) == []


async def test_support_draft_does_not_leak_between_communities(client, db_session, bot, role):
    """peer_id и Redis общие: обращение, начатое в бизнесовом диалоге, нельзя
    дописать из клиентского — оно ушло бы в чужое сообщество."""
    role("business")
    await vk_bot.on_message_event({"peer_id": 1120, "user_id": 1120, "event_id": "a",
                                   "payload": {"c": "sup:question"}})
    role("client")
    await vk_bot.on_message_new({"message": {"peer_id": 1120, "from_id": 1120,
                                             "text": "Это уже другой разговор, не обращение"}})
    assert await _requests(db_session, 1120) == []
    role("business")
    await vk_bot.on_message_new({"message": {"peer_id": 1120, "from_id": 1120,
                                             "text": "А это продолжение в своём сообществе"}})
    [request] = await _requests(db_session, 1120)
    assert request.vk_audience == "business"


async def test_footer_ref_opens_topics_in_client_bot(client, db_session, bot, role):
    role("client")
    await vk_bot.on_message_new({"message": {"peer_id": 1130, "from_id": 1130, "ref": "support",
                                             "text": "Начать"}})
    assert any("О чём хотите написать" in m["text"] for m in bot.sent)


async def test_vk_request_without_community_is_refused(db_session):
    from app.services.support import create_request

    async with db_session() as db:
        with pytest.raises(ValueError):
            await create_request(db, topic=SupportTopic.QUESTION, text="вопрос без сообщества",
                                 channel=NotifyChannel.VK, chat_id=1140)


async def _answer(db_session, *, audience, chat_id, user_id=None):
    from app.services.support import send_answer

    admin_id = await _user(db_session, f"+7999001{chat_id}", role=UserRole.ADMIN)
    async with db_session() as db:
        request = SupportRequest(topic=SupportTopic.QUESTION, text="вопрос", user_id=user_id,
                                 channel=NotifyChannel.VK, chat_id=chat_id,
                                 vk_audience=audience, status=SupportStatus.NEW)
        db.add(request)
        await db.commit()
        await send_answer(db, request, "ответ", await db.get(User, admin_id))


async def test_support_answer_to_client_request_goes_through_client_community(
        client, db_session, two_communities, pool, vk_http):
    user_id = await _user(db_session, "+79990014800", **_vk_fields(1200))
    await _answer(db_session, audience="client", chat_id=1202, user_id=user_id)
    # адрес — клиентский диалог пользователя (1201), а не бизнесовый (1202)
    assert pool.vk() == [(1201, "client")]
    fn, args, kwargs = pool.jobs[-1]
    await tasks.send_vk_message({"job_try": 1}, *args, **kwargs)
    assert [(c["token"], c["peer"]) for c in vk_http] == [(CLIENT_TOKEN, 1201)]


async def test_support_answer_to_unlinked_client_chat_goes_through_client_community(
        client, db_session, two_communities, pool):
    await _answer(db_session, audience="client", chat_id=8821)
    assert pool.vk() == [(8821, "client")]


async def test_support_answer_failure_in_client_community_keeps_business(
        client, db_session, two_communities, pool, monkeypatch):
    async def refuse(peer_id, text, keyboard=None, *, community):
        raise tasks.RecipientGone("901")

    monkeypatch.setattr(tasks, "_send_via_vk", refuse)
    user_id = await _user(db_session, "+79990014830", email="s@example.com",
                          vk_client_peer_id=1230, vk_business_peer_id=1230,
                          notify_channel=NotifyChannel.VK)
    await _answer(db_session, audience="client", chat_id=1230, user_id=user_id)
    fn, args, kwargs = pool.jobs[-1]
    await tasks.send_vk_message({"job_try": 1}, *args, **kwargs)
    user = await _get(db_session, user_id)
    assert user.vk_client_broken_at is not None
    assert user.vk_business_broken_at is None


async def test_admin_alert_and_list_show_the_community(client, db_session, two_communities,
                                                       monkeypatch):
    from app.core.security import get_password_hash
    from app.services.support import create_request

    alerts = []

    async def capture(db, subject, body=""):
        alerts.append(body)

    monkeypatch.setattr("app.services.notifications.notify_admins", capture)
    async with db_session() as db:
        db.add(User(phone="+79990014900", full_name="Админ", role=UserRole.ADMIN, is_active=True,
                    is_senior_admin=True, hashed_password=get_password_hash("Adminpass1")))
        await db.commit()
        await create_request(db, topic=SupportTopic.QUESTION, text="Вопрос от клиента из ВК",
                             channel=NotifyChannel.VK, chat_id=1300, vk_audience="client")
        await create_request(db, topic=SupportTopic.QUESTION, text="Вопрос от салона из ВК",
                             channel=NotifyChannel.VK, chat_id=1301, vk_audience="business")
    assert "VK · клиенты" in alerts[0] and "VK · бизнес" in alerts[1]

    r = await client.post("/api/v1/auth/login",
                          json={"phone": "+79990014900", "password": "Adminpass1"})
    client.cookies.set("access_token", r.json()["access_token"])
    page = (await client.get("/admin")).text
    assert "VK · клиенты" in page and "VK · бизнес" in page


async def test_support_answer_to_a_legacy_request_goes_through_business(
        client, db_session, two_communities, pool):
    """Обращение, заведённое ДО разделения сообществ: поля сообщества нет.

    Такие строки заполняет миграция, но умолчание в коде всё равно должно быть
    бизнесовым: до разделения обращения во ВК принимало только старое
    сообщество, и оно стало бизнесовым. Ответь мы клиентским токеном — ВК
    отверг бы сообщение, наш код счёл бы получателя недоступным и пометил канал
    сломанным (решение 0002). Поэтому умолчание закреплено тестом, а не
    оставлено на усмотрение следующей правки.
    """
    from app.services.support import send_answer

    admin_id = await _user(db_session, "+79990014901", role=UserRole.ADMIN)
    async with db_session() as db:
        request = SupportRequest(topic=SupportTopic.QUESTION, text="старое обращение",
                                 channel=NotifyChannel.VK, chat_id=8901,
                                 vk_audience=None, status=SupportStatus.NEW)
        db.add(request)
        await db.commit()
        await send_answer(db, request, "ответ", await db.get(User, admin_id))

    assert pool.vk() == [(8901, "business")]
