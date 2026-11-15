# app/services/tg_widget.py
"""Карточка записи виджетом Telegram (Bot API 10.4, решение 0021, сессия 2).

Устройство, которое нельзя менять не подумав:

- HTML ОДИН и статический (app/assets/tg_widget_booking.html). После отправки
  заменить его нельзя ни одним методом, а данные записи в разметку не
  подставляются вовсе: названия вводит салон, виджет исполняет JS, и размер
  шаблона (≤32768 байт, после zlib-9 ≤4096) проверяется один раз, а не зависит
  от чужого названия.
- Всё, что меняется, живёт в chat_data (≤1024 байта UTF-8): экран, время,
  услуга, мастер, цена, окна переноса. Виджет читает его сам и слушает
  chatDataChanged; мы правим его editMessageWidgetData.
- Кнопки у виджета обычные, снаружи (reply_markup); allow_queries не
  передаём, виджет ботов не дёргает.
- Подпись — полный текст карточки. Клиент без поддержки виджетов покажет
  сообщение вложением с подписью, и человек всё равно всё прочтёт.
"""
from __future__ import annotations

import json
from pathlib import Path

CHAT_DATA_LIMIT = 1024   # байт, UTF-8 (Bot API)
CAPTION_LIMIT = 1024     # символов
HEIGHT = 170             # пикселей; прокрутки внутри виджета нет

SCREEN_CARD, SCREEN_OK, SCREEN_MOVED = "card", "ok", "moved"
SCREEN_OFF, SCREEN_PAST = "off", "past"
SCREEN_SLOTS, SCREEN_BUSY = "slots", "busy"

_FIELD_LIMITS = {"sv": 40, "m": 28, "p": 22}   # усечение полей из ввода салона
_SLOT_LABEL = 16
_MAX_SLOTS = 6

WIDGET_HTML = (Path(__file__).resolve().parent.parent / "assets"
               / "tg_widget_booking.html").read_text(encoding="utf-8")


def enabled_for(chat_id) -> bool:
    """Виджет включён только тем, чей chat_id в TG_WIDGET_CHAT_IDS."""
    from app.core.config import settings

    try:
        return int(chat_id) in settings.tg_widget_chat_ids
    except (TypeError, ValueError):
        return False


def _cut(value, limit: int) -> str:
    value = " ".join(str(value or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def build_chat_data(screen: str, *, date: str = "", time: str = "", service: str = "",
                    master: str = "", price: str = "", slots: list[str] | None = None,
                    start_epoch: int | None = None) -> str:
    """JSON для chat_data. Всегда укладывается в 1024 байта.

    Сначала усекаем текстовые поля, потом режем окна с хвоста, и только в
    крайнем случае (невозможном при этих пределах, но граница — Bot API, а не
    наше мнение) оставляем один скелет: лучше карточка без услуги, чем 400 и
    карточка, которая не обновится.
    """
    data: dict = {"s": screen, "d": date, "t": time,
                  "sv": _cut(service, _FIELD_LIMITS["sv"]),
                  "m": _cut(master, _FIELD_LIMITS["m"]),
                  "p": _cut(price, _FIELD_LIMITS["p"])}
    if start_epoch is not None:
        data["e"] = int(start_epoch)
    labels = [_cut(x, _SLOT_LABEL) for x in (slots or [])][:_MAX_SLOTS]
    if labels:
        data["sl"] = labels
    out = _dump(data)
    while len(out.encode("utf-8")) > CHAT_DATA_LIMIT and data.get("sl"):
        data["sl"].pop()
        if not data["sl"]:
            del data["sl"]
        out = _dump(data)
    if len(out.encode("utf-8")) > CHAT_DATA_LIMIT:
        out = _dump({"s": screen, "d": date, "t": time})
    return out


def fit_caption(text: str) -> str:
    """Подпись ≤1024 символов: Bot API иначе вернёт 400, и карточка не уйдёт."""
    return text if len(text) <= CAPTION_LIMIT else text[: CAPTION_LIMIT - 1].rstrip() + "…"


def slot_labels(buttons: list | None) -> list[str]:
    """Подписи окон переноса из кнопок: у окна команда «rsc:ID:время»."""
    from app.services.bot_actions import CMD_RESCHEDULE

    out = []
    for b in buttons or []:
        cmd = getattr(b, "command", "") or ""
        if cmd.startswith(CMD_RESCHEDULE) and cmd.count(":") >= 2:
            out.append(b.label)
    return out


def _screen_for(booking, note: str) -> str:
    from app.models.models import BookingStatus
    from app.services import booking_card

    if booking.status == BookingStatus.CANCELLED:
        return SCREEN_OFF
    if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
        return SCREEN_PAST
    if note == booking_card.NOTE_RESCHEDULED:
        return SCREEN_MOVED
    if booking.client_confirmed_at is not None:
        return SCREEN_OK
    return SCREEN_CARD


async def widget_state(db, booking_id: int, *, owner_id: int | None = None,
                       note: str = "", screen: str | None = None,
                       buttons: list | None = None) -> str | None:
    """chat_data карточки записи сейчас; None — записи нет или она чужая.

    screen задаёт вызывающий, когда состояние записи его не определяет
    (список окон, «окно заняли»); иначе экран выводится из самой записи.
    """
    from app.services import booking_card
    from app.services.price import format_service_price
    from app.utils.timezone import localize_time

    ctx = await booking_card._context(db, booking_id)
    if ctx is None:
        return None
    booking, salon, service, master_name = ctx
    if owner_id is not None and booking.client_id != owner_id:
        return None
    start = booking.start_time
    return build_chat_data(
        screen or _screen_for(booking, note),
        date=f"{start:%d.%m}", time=f"{start:%H:%M}",
        service=service.name,
        master=master_name or "",
        price=format_service_price(service.price, service.price_max),
        slots=slot_labels(buttons) if (screen in (SCREEN_SLOTS, SCREEN_BUSY)) else None,
        start_epoch=int(localize_time(start, getattr(salon, "timezone", None)).timestamp()),
    )
