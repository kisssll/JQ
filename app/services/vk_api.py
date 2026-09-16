# app/services/vk_api.py
"""Тонкий клиент API ВКонтакте для бота сообщества.

Почему не vkbottle. Боту нужны пять методов (отправить сообщение, ответить на
нажатие кнопки, узнать имя, получить адрес Long Poll, опросить его), а
библиотека тянет свой рантайм, свои модели и свою версию aiohttp рядом с
aiogram и maxapi. На httpx это сотня строк, которые проверяются подменой
транспорта в тестах — так же, как отправка в Telegram в tasks.py.

Классификация ошибок — та же, что у Telegram и MAX (см. tasks.RecipientGone):
«получатель недоступен» отдельно от «сломались мы» и от «попробуйте позже».
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.vk.ru/method/"
API_VERSION = "5.199"

# 900 — человек в чёрном списке сообщества / заблокировал его;
# 901 — не разрешал сообщения от сообщества (или запретил);
# 902 — закрыл сообщения настройками приватности.
# Повтор не поможет, пока человек сам не передумает.
RECIPIENT_GONE_CODES = frozenset({900, 901, 902})
# 1 — неизвестная ошибка, 6 — слишком часто, 9 — флуд-контроль,
# 10 — внутренняя ошибка ВК. Стоит повторить позже.
TRANSIENT_CODES = frozenset({1, 6, 9, 10})

# Ограничения клавиатуры ВК: подпись кнопки до 40 символов, payload до 255.
LABEL_MAX = 40


class VkApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"VK {code}: {message}")
        self.code = code
        self.message = message


async def call(method: str, *, token: Optional[str] = None, timeout: float = 15,
               **params: Any) -> Any:
    """Вызов метода API. Ошибка ВК → VkApiError; сетевая — httpx.HTTPError."""
    from app.core.config import settings   # при вызове: тесты перезагружают конфиг

    data = {k: v for k, v in params.items() if v is not None}
    data["access_token"] = token or settings.VK_BOT_TOKEN
    data["v"] = API_VERSION
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(API_URL + method, data=data)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        err = body["error"]
        raise VkApiError(int(err.get("error_code", 0)), str(err.get("error_msg", "")))
    return body.get("response")


def random_id() -> int:
    """messages.send требует random_id: по нему ВК отбрасывает повторы."""
    return secrets.randbelow(2**31 - 1) + 1


async def send_message(peer_id: int, text: str, keyboard: Optional[dict] = None) -> Any:
    return await call(
        "messages.send", peer_id=peer_id, message=text, random_id=random_id(),
        keyboard=json.dumps(keyboard, ensure_ascii=False) if keyboard else None,
        dont_parse_links=0,
    )


async def answer_event(event_id: str, user_id: int, peer_id: int,
                       snackbar: Optional[str] = None) -> None:
    """Ответ на нажатие callback-кнопки. Без него у кнопки крутится индикатор."""
    event_data = (json.dumps({"type": "show_snackbar", "text": snackbar[:90]},
                             ensure_ascii=False) if snackbar else None)
    await call("messages.sendMessageEventAnswer", event_id=event_id,
               user_id=user_id, peer_id=peer_id, event_data=event_data)


async def user_name(user_id: int) -> str:
    """«Имя Фамилия» пользователя ВК; пустая строка, если узнать не вышло."""
    try:
        users = await call("users.get", user_ids=user_id)
        if users:
            return f"{users[0].get('first_name', '')} {users[0].get('last_name', '')}".strip()
    except Exception:
        logger.warning("vk: имя пользователя %s не получено", user_id, exc_info=True)
    return ""


# ── клавиатуры ──────────────────────────────────────────────────────────────

def callback_button(label: str, command: str, color: str = "secondary") -> dict:
    """Кнопка, нажатие которой приходит событием message_event.

    payload — объект {"c": команда}; команды те же, что у Telegram и MAX
    (menu:bookings, cnl:ID, ntf:тема, sup:тема, rev:ID:N, nps:N, edc:yes).
    """
    return {
        "action": {"type": "callback", "label": label[:LABEL_MAX],
                   "payload": json.dumps({"c": command}, ensure_ascii=False)},
        "color": color,
    }


def link_button(label: str, url: str) -> dict:
    return {"action": {"type": "open_link", "label": label[:LABEL_MAX], "link": url}}


def inline_keyboard(rows: list[list[dict]]) -> dict:
    """Клавиатура под сообщением. У ВК предел — 6 рядов и 10 кнопок."""
    return {"inline": True, "buttons": rows}


def vk_me_url(ref: Optional[str] = None) -> str:
    """Ссылка на диалог с сообществом. ref ВК вернёт в первом сообщении человека."""
    from app.core.config import settings

    address = settings.vk_bot_address
    if not address:
        return ""
    return f"https://vk.me/{address}" + (f"?ref={ref}" if ref else "")
