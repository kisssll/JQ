# app/vk_bot.py
"""ВК-бот сообщества Руми.

Запуск: python -m app.vk_bot — отдельный контейнер, Bots Long Poll API
(наружу портов нет). Паритет с tg- и max-ботами: главное меню, «Мои записи»
с отменой, «Мои уведомления», обращение в поддержку с фото, звёзды отзыва,
оценка сервиса, согласие на подборку вечерних окон.

Чем ВК отличается и как это учтено:
- номер телефона бот НЕ подтверждает — кнопки «поделиться номером» в ВК нет.
  Привязка — по VK ID-входу или одноразовой ссылке из профиля (vk_link.py);
- сообщество не может написать первым — человек пишет сам или жмёт «Начать»;
- нажатия callback-кнопок приходят отдельным событием message_event, на
  которое обязательно отвечать, иначе у кнопки бесконечно крутится индикатор.

Команды кнопок те же, что у двух других ботов (menu:*, cnl:, ntf:, sup:, rev:,
nps:, adc:yes), — правила живут в общих bot_actions.py и support.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

from app.core import config
from app.core.limiter import get_redis
from app.services import vk_api, vk_link

logger = logging.getLogger("vk_bot")

from app.services import bot_texts     # общие подписи и тексты трёх ботов

MENU_BOOKINGS = bot_texts.MENU_BOOKINGS
MENU_PREFS = bot_texts.MENU_PREFS
MENU_SUPPORT = bot_texts.MENU_SUPPORT

# Слова, на которые показываем меню. «Начать» — подпись кнопки ВК в пустом
# диалоге; её нажатие приходит обычным сообщением с payload {"command":"start"}.
START_WORDS = frozenset({"начать", "start", "/start", "меню", "menu"})

_SUPPORT_TTL = 1800
# Личные диалоги имеют peer_id < 2e9; всё, что выше, — беседы, где бот не работает.
_CHAT_PEER_BASE = 2_000_000_000

LONG_POLL_WAIT = 25


# ── отправка ────────────────────────────────────────────────────────────────

async def send(peer_id: int, text: str, keyboard: Optional[dict] = None) -> None:
    """Ответ в диалог. Ошибка отправки не должна ронять обработку события."""
    try:
        await vk_api.send_message(peer_id, text, keyboard)
    except Exception:
        logger.warning("vk peer=%s: ответ не отправлен", peer_id, exc_info=True)


def _menu_kb() -> dict:
    return vk_api.inline_keyboard([
        [vk_api.callback_button(MENU_BOOKINGS, "menu:bookings", "primary")],
        [vk_api.callback_button(MENU_PREFS, "menu:prefs")],
        [vk_api.callback_button(MENU_SUPPORT, "menu:support")],
    ])


def _connect_url() -> str:
    """Страница привязки: одна кнопка и возврат сюда же. Раньше вели на
    /profile, где нужный блок — седьмой экран вниз, и человек до него
    не доходил."""
    return f"{config.settings.PUBLIC_BASE_URL.rstrip('/')}/connect/vk"


def _unlinked_kb() -> dict:
    return vk_api.inline_keyboard([
        [vk_api.link_button(bot_texts.MENU_LINK, _connect_url())],
        [vk_api.callback_button(MENU_SUPPORT, "menu:support")],
    ])


UNLINKED_TEXT = (
    f"{bot_texts.LINK_OFFER}\n\n"
    "Привязка займёт минуту: откроется страница Руми, а оттуда вас вернёт сюда."
)


# ── состояние и пользователь ────────────────────────────────────────────────

async def _db():
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal()


async def current_user(db, peer_id: int):
    """Привязанный аккаунт или None. Вошедших через VK ID привязываем сразу."""
    user = await vk_link.linked_user(db, peer_id)
    if user is not None:
        return user, False
    user = await vk_link.user_by_vk_id(db, peer_id)
    if user is None:
        return None, False
    ask = await vk_link.link(db, user, peer_id, await vk_api.user_name(peer_id))
    await _announce_link(peer_id, user, ask)
    return user, True


async def _announce_link(peer_id: int, user, ask_channel: bool) -> None:
    from app.services.notify_channel import CHANNEL_LABELS

    if ask_channel:
        current = CHANNEL_LABELS[user.notify_channel]
        await send(
            peer_id,
            bot_texts.link_done(current),
            vk_api.inline_keyboard([
                [vk_api.callback_button("Да, присылать сюда", "chn:vk", "positive")],
                [vk_api.callback_button(f"Оставить {current}", "chn:keep")],
            ]),
        )
    else:
        await send(peer_id, bot_texts.link_done(), _menu_kb())


async def _revive(peer_id: int) -> None:
    """Человек пишет сообществу — значит, сообщения от него снова доходят."""
    from app.models.models import NotifyChannel
    from app.services.notify_channel import clear_broken

    try:
        async with await _db() as db:
            if await clear_broken(db, NotifyChannel.VK, peer_id):
                logger.info("vk peer=%s: доставка снова доступна", peer_id)
    except Exception:
        logger.exception("vk peer=%s: не удалось снять отметку отказа", peer_id)


def _draft_key(peer_id: int) -> str:
    return f"support:draft:vk:{peer_id}"


async def _draft_get(peer_id: int) -> Optional[dict]:
    raw = await get_redis().get(_draft_key(peer_id))
    if not raw:
        return None
    return json.loads(raw if isinstance(raw, str) else raw.decode())


async def _draft_set(peer_id: int, draft: dict) -> None:
    await get_redis().set(_draft_key(peer_id), json.dumps(draft), ex=_SUPPORT_TTL)


async def _draft_clear(peer_id: int) -> None:
    await get_redis().delete(_draft_key(peer_id))


# ── разделы ─────────────────────────────────────────────────────────────────

async def show_main_menu(peer_id: int, user) -> None:
    if user is None:
        # Два коротких сообщения: приветствие — всем, предложение привязать —
        # только непривязанным (так же в tg- и max-боте).
        await send(peer_id, bot_texts.GREETING)
        await send(peer_id, UNLINKED_TEXT, _unlinked_kb())
        return
    await send(
        peer_id,
        f"{bot_texts.hello(user)} Это бот Руми. Отсюда можно:\n\n{bot_texts.menu_hint()}",
        _menu_kb(),
    )


async def show_bookings(peer_id: int) -> None:
    from app.services.bot_actions import format_booking, upcoming_bookings

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        if user is None:
            await send(peer_id, UNLINKED_TEXT, _unlinked_kb())
            return
        rows = await upcoming_bookings(db, user.id)

    if not rows:
        await send(peer_id, "Ближайших записей нет.")
        return
    for booking, salon, service, master_name in rows:
        await send(
            peer_id, format_booking(booking, salon, service, master_name),
            vk_api.inline_keyboard([[vk_api.callback_button(
                "Отменить запись", f"cnl:{booking.id}", "negative")]]),
        )


async def cancel_from_bot(peer_id: int, booking_id: int) -> str:
    from app.services.bot_actions import cancel_booking

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        if user is None:
            return "ВКонтакте не привязан к аккаунту."
        _, text = await cancel_booking(db, user.id, booking_id)
    await send(peer_id, text)
    return ""


async def show_prefs(peer_id: int) -> None:
    from app.services.notifications import TOPIC_LABELS, wants
    from app.tg_bot import _available_topics  # общий список тем, без дубля

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        if user is None:
            await send(peer_id, UNLINKED_TEXT, _unlinked_kb())
            return
        topics = await _available_topics(db, user)
        rows = [
            [vk_api.callback_button(
                f"{'🔔' if wants(user, t) else '🔕'} {TOPIC_LABELS.get(t, t)}", f"ntf:{t}")]
            for t in topics[:6]   # предел ВК — 6 рядов в клавиатуре под сообщением
        ]
    await send(peer_id, "Что присылать вам во ВКонтакте? Нажмите, чтобы включить или выключить.",
               vk_api.inline_keyboard(rows))


async def toggle_topic(peer_id: int, topic: str) -> None:
    from app.services import ad_consent
    from app.services.notifications import OPT_IN_TOPICS, TOPIC_LABELS, wants

    if topic not in TOPIC_LABELS:
        return
    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        if user is None:
            return
        new_value = not wants(user, topic)
        if topic in OPT_IN_TOPICS:
            # Рекламная тема: включение — только с записью согласия в журнал
            # (ч. 1 ст. 18 закона «О рекламе»), как в tg- и max-ботах.
            if new_value:
                await ad_consent.grant(db, user_id=user.id, source="vk_prefs")
            else:
                await ad_consent.revoke(db, user_id=user.id)
        else:
            prefs = dict(user.tg_notify_prefs or {})
            prefs[topic] = new_value
            user.tg_notify_prefs = prefs
            await db.commit()

    await send(peer_id, f"{TOPIC_LABELS.get(topic, topic)}: {'включены' if new_value else 'выключены'}.")
    await show_prefs(peer_id)


async def show_topics(peer_id: int) -> None:
    from app.models.models import SupportTopic
    from app.services.support import TOPIC_LABELS as SUPPORT_LABELS

    await _draft_clear(peer_id)
    rows = [
        [vk_api.callback_button(SUPPORT_LABELS[t], f"sup:{t.value}")]
        for t in (SupportTopic.QUESTION, SupportTopic.BUG, SupportTopic.COMPLAINT, SupportTopic.IDEA)
    ]
    await send(peer_id, "О чём хотите написать? Выберите тему — так мы быстрее поймём, "
                        "кому передать обращение.", vk_api.inline_keyboard(rows))


async def start_support_topic(peer_id: int, value: str) -> None:
    from app.models.models import SupportTopic
    from app.services.support import MAX_PHOTOS, TOPIC_LABELS as SUPPORT_LABELS

    try:
        topic = SupportTopic(value)
    except ValueError:
        return
    if topic == SupportTopic.NPS:
        return
    await _draft_set(peer_id, {"topic": topic.value, "photos": []})
    await send(peer_id, f"Тема: {SUPPORT_LABELS[topic]}\n\n"
                        "Опишите, что случилось — одним сообщением. "
                        f"Можно приложить фото (до {MAX_PHOTOS}).\n\n"
                        "Отменить — напишите «отмена».")


def _photo_urls(message: dict) -> list[str]:
    """Ссылки на самый крупный размер каждой фотографии в сообщении."""
    urls = []
    for att in message.get("attachments") or []:
        if att.get("type") != "photo":
            continue
        sizes = (att.get("photo") or {}).get("sizes") or []
        if sizes:
            best = max(sizes, key=lambda s: (s.get("width") or 0) * (s.get("height") or 0))
            if best.get("url"):
                urls.append(best["url"])
    return urls


async def _download(url: str) -> Optional[bytes]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        logger.warning("support: фото из ВК не скачано", exc_info=True)
    return None


async def continue_support(peer_id: int, message: dict, draft: dict) -> None:
    from app.models.models import NotifyChannel, SupportTopic
    from app.services.support import (
        MAX_PHOTOS, RateLimited, check_rate_limit, create_request, store_photo, validate_text,
    )

    text = (message.get("text") or "").strip()
    if text.lower() in ("отмена", "/cancel"):
        await _draft_clear(peer_id)
        await send(peer_id, "Обращение отменено.")
        return

    urls = _photo_urls(message)
    for url in urls:
        if len(draft["photos"]) >= MAX_PHOTOS:
            break
        data = await _download(url)
        stored = store_photo(data) if data else None
        if stored:
            draft["photos"].append(stored)
    if urls:
        await _draft_set(peer_id, draft)
        if not text:
            await send(peer_id, f"Фото принято ({len(draft['photos'])}). Теперь опишите проблему текстом.")
            return

    error = validate_text(text)
    if error:
        await send(peer_id, error)
        return

    try:
        await check_rate_limit(NotifyChannel.VK, peer_id)
    except RateLimited:
        await _draft_clear(peer_id)
        await send(peer_id, "Вы уже отправили несколько обращений за последний час — "
                            "мы ответим на них в ближайшее время.")
        return

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        request = await create_request(
            db, topic=SupportTopic(draft["topic"]), text=text, channel=NotifyChannel.VK,
            chat_id=peer_id, user=user, photos=draft["photos"],
        )
    await _draft_clear(peer_id)
    await send(peer_id, f"Обращение №{request.id} принято — спасибо.\nОтветим сюда же, в этот чат.",
               _menu_kb() if user else None)


async def save_review_stars(peer_id: int, booking_id: int, rating: int) -> str:
    from app.services.bot_actions import save_review

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        if user is None:
            return "ВКонтакте не привязан к аккаунту."
        ok, text = await save_review(db, user_id=user.id, booking_id=booking_id, rating=rating)
    await send(peer_id, f"{'★' * rating}\n{text}")
    return "Спасибо!" if ok else ""


async def save_service_rating(peer_id: int, rating: int) -> None:
    from app.models.models import NotifyChannel, SupportTopic
    from app.services.support import create_request

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        await create_request(
            db, topic=SupportTopic.NPS, text=f"Оценка сервиса: {rating}/5",
            channel=NotifyChannel.VK, chat_id=peer_id, user=user, rating=rating,
        )
    await send(peer_id, f"Ваша оценка: {rating}/5. Спасибо!\n\n"
                        f"Если хотите добавить, чего не хватает — напишите нам через «{MENU_SUPPORT}».")


async def grant_promos(peer_id: int) -> None:
    from app.services import ad_consent

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        if user is None:
            await send(peer_id, "ВКонтакте не привязан к аккаунту Руми.")
            return
        await ad_consent.grant(db, user_id=user.id, source="vk_question")
    await send(peer_id, ad_consent.THANKS_TEXT)


async def choose_channel(peer_id: int, to_vk: bool) -> None:
    from app.models.models import NotifyChannel
    from app.services.notify_channel import CHANNEL_LABELS

    async with await _db() as db:
        user, _ = await current_user(db, peer_id)
        if user is None:
            return
        if to_vk:
            user.notify_channel = NotifyChannel.VK
            await db.commit()
            text = "Готово, уведомления будут приходить сюда, во ВКонтакте."
        else:
            text = f"Хорошо, уведомления по-прежнему приходят в {CHANNEL_LABELS[user.notify_channel]}."
    await send(peer_id, text + "\nСменить канал можно в профиле на сайте.", _menu_kb())


# ── события ─────────────────────────────────────────────────────────────────

def _message_payload(message: dict) -> dict:
    raw = message.get("payload")
    if not raw:
        return {}
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


async def _link_by_code(peer_id: int, code: str) -> bool:
    """Привязать аккаунт по коду (из ссылки или из сообщения). → получилось ли."""
    from app.models.models import User

    user_id = await vk_link.pop_code(code)
    if user_id is None:
        return False
    async with await _db() as db:
        user = await db.get(User, user_id)
        if user is None:
            return False
        ask = await vk_link.link(db, user, peer_id, await vk_api.user_name(peer_id))
        await _announce_link(peer_id, user, ask)
    return True


async def on_message_new(obj: dict) -> None:
    message = obj.get("message") or {}
    peer_id = int(message.get("peer_id") or 0)
    if peer_id <= 0 or peer_id >= _CHAT_PEER_BASE or message.get("out"):
        return

    await _revive(peer_id)
    ref = (message.get("ref") or "").strip()

    if ref == vk_link.REF_SUPPORT:
        # Ссылка «Написать во ВКонтакте» из подвала: сразу выбор темы.
        await show_topics(peer_id)
        return

    if ref:
        if await _link_by_code(peer_id, ref):
            return
        if vk_link.looks_like_code(ref):
            await send(peer_id, "Ссылка для привязки устарела или уже использована — "
                                "она живёт 15 минут. Откройте страницу привязки ещё раз.",
                       _unlinked_kb())
            return

    text_raw = (message.get("text") or "").strip()
    # Код со страницы привязки, присланный сообщением. Проверяем ДО черновика
    # обращения: человек, начавший писать в поддержку, мог параллельно
    # получить код, и привязка важнее незаконченного текста.
    if vk_link.looks_like_code(text_raw):
        if await _link_by_code(peer_id, text_raw):
            return
        await send(peer_id, "Такой код не подошёл: он живёт 15 минут и работает один раз. "
                            "Откройте страницу привязки и возьмите новый.", _unlinked_kb())
        return

    draft = await _draft_get(peer_id)
    if draft is not None:
        await continue_support(peer_id, message, draft)
        return

    async with await _db() as db:
        user, just_linked = await current_user(db, peer_id)
    if just_linked:
        return   # приветствие с меню уже отправлено при привязке

    text = (message.get("text") or "").strip().lower()
    if _message_payload(message).get("command") == "start" or text in START_WORDS:
        await show_main_menu(peer_id, user)
    else:
        await send(peer_id, "Чем помочь?", _menu_kb() if user else _unlinked_kb())


async def on_message_event(obj: dict) -> None:
    """Нажатие callback-кнопки. Отвечаем ВСЕГДА — иначе кнопка «висит»."""
    peer_id = int(obj.get("peer_id") or 0)
    user_id = int(obj.get("user_id") or 0)
    event_id = obj.get("event_id") or ""
    payload = obj.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    command = str(payload.get("c") or "") if isinstance(payload, dict) else ""

    snackbar: Optional[str] = None
    try:
        snackbar = await _dispatch_command(peer_id, command)
    except Exception:
        logger.exception("vk peer=%s: сбой обработки кнопки %s", peer_id, command)
    finally:
        try:
            await vk_api.answer_event(event_id, user_id, peer_id, snackbar or None)
        except Exception:
            logger.warning("vk peer=%s: нажатие не подтверждено", peer_id, exc_info=True)


async def _dispatch_command(peer_id: int, command: str) -> Optional[str]:
    if command == "menu:bookings":
        await show_bookings(peer_id)
    elif command == "menu:prefs":
        await show_prefs(peer_id)
    elif command == "menu:support":
        await show_topics(peer_id)
    elif command.startswith("cnl:"):
        try:
            return await cancel_from_bot(peer_id, int(command.split(":", 1)[1])) or None
        except ValueError:
            return None
    elif command.startswith("ntf:"):
        await toggle_topic(peer_id, command.split(":", 1)[1])
    elif command == "adc:yes":
        await grant_promos(peer_id)
    elif command.startswith("sup:"):
        await start_support_topic(peer_id, command.split(":", 1)[1])
    elif command.startswith("rev:"):
        parts = command.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit() and 1 <= int(parts[2]) <= 5:
            return await save_review_stars(peer_id, int(parts[1]), int(parts[2])) or None
    elif command.startswith("nps:"):
        value = command.split(":", 1)[1]
        if value.isdigit() and 1 <= int(value) <= 5:
            await save_service_rating(peer_id, int(value))
            return "Спасибо!"
    elif command in ("chn:vk", "chn:keep"):
        await choose_channel(peer_id, command == "chn:vk")
    return None


async def on_message_allow(obj: dict) -> None:
    peer_id = int(obj.get("user_id") or 0)
    if peer_id:
        await _revive(peer_id)


async def on_message_deny(obj: dict) -> None:
    """Человек запретил сообщения — дальше доставка пойдёт запасным каналом."""
    from app.models.models import NotifyChannel
    from app.services.notify_channel import mark_broken

    peer_id = int(obj.get("user_id") or 0)
    if not peer_id:
        return
    async with await _db() as db:
        if await mark_broken(db, NotifyChannel.VK, peer_id):
            logger.info("vk peer=%s: сообщения запрещены — канал помечен", peer_id)


HANDLERS = {
    "message_new": on_message_new,
    "message_event": on_message_event,
    "message_allow": on_message_allow,
    "message_deny": on_message_deny,
}


# ── Long Poll ───────────────────────────────────────────────────────────────

class Dispatcher:
    """События одного человека обрабатываем по очереди (фото, потом текст
    обращения — порядок важен), разных людей — параллельно."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()

    def _peer(self, update: dict) -> int:
        obj = update.get("object") or {}
        if "message" in obj:
            return int(obj["message"].get("peer_id") or 0)
        return int(obj.get("peer_id") or obj.get("user_id") or 0)

    async def _run(self, update: dict) -> None:
        handler = HANDLERS.get(update.get("type", ""))
        if handler is None:
            return
        lock = self._locks.setdefault(self._peer(update), asyncio.Lock())
        async with lock:
            try:
                await handler(update.get("object") or {})
            except Exception:
                logger.exception("vk: сбой обработки события %s", update.get("type"))

    def feed(self, update: dict) -> asyncio.Task:
        task = asyncio.create_task(self._run(update))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task


async def poll_forever(dispatcher: Optional[Dispatcher] = None) -> None:
    dispatcher = dispatcher or Dispatcher()
    server: Optional[dict[str, Any]] = None
    delay = 1
    async with httpx.AsyncClient(timeout=LONG_POLL_WAIT + 10) as client:
        while True:
            try:
                if server is None:
                    server = await vk_api.call("groups.getLongPollServer", group_id=config.settings.VK_GROUP_ID)
                resp = await client.get(server["server"], params={
                    "act": "a_check", "key": server["key"], "ts": server["ts"], "wait": LONG_POLL_WAIT,
                })
                body = resp.json()
                failed = body.get("failed")
                if failed == 1:
                    server["ts"] = body["ts"]      # история событий потерялась — идём дальше
                    continue
                if failed:
                    server = None                  # ключ истёк — берём новый
                    continue
                server["ts"] = body["ts"]
                for update in body.get("updates") or []:
                    dispatcher.feed(update)
                delay = 1
            except asyncio.CancelledError:
                raise
            except vk_api.VkApiError as exc:
                logger.error("vk: Long Poll недоступен: %s", exc)
                server = None
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
            except Exception:
                logger.warning("vk: сбой опроса, повторим через %s с", delay, exc_info=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)


async def main() -> None:
    if not config.settings.VK_BOT_TOKEN or not config.settings.VK_GROUP_ID:
        # Как tg- и max-боты: без ключа спим, а не крашлупим.
        logger.warning("VK_BOT_TOKEN/VK_GROUP_ID не заданы — бот в режиме ожидания.")
        await asyncio.Event().wait()
        return
    logger.info("ВК-бот сообщества %s запущен (Bots Long Poll)", config.settings.VK_GROUP_ID)
    await poll_forever()


if __name__ == "__main__":
    from app.core.observability import init_sentry, setup_logging

    setup_logging()
    # httpx пишет каждый запрос с полным адресом — для Long Poll это строка раз
    # в 25 секунд С КЛЮЧОМ опроса, по которому до его истечения можно читать
    # события сообщества. Ни шум, ни ключ в логах не нужны.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_sentry()
    asyncio.run(main())
