# app/services/bot_keyboards.py
"""Одно описание кнопок (bot_actions.BotButton) → клавиатура своего канала.

Кнопки под сообщением нужны и ботам (на нажатие отвечает процесс бота), и
очереди (напоминание шлёт воркер, бота там нет). Если бы каждый рисовал
сам, набор «Буду / Перенести / Не смогу» существовал бы в четырёх копиях и
разошёлся бы на первой же правке подписи — как когда-то разошлись тексты
(см. bot_texts).

Раскладка одна на все каналы: кнопки-команды по две в ряд, кнопка-ссылка —
отдельным рядом. Две в ряд, потому что у ВК предел шесть рядов, а шесть
окон переноса плюс ссылка в один столбец в него не влезают.
"""
from __future__ import annotations

#: Предел ВК: больше рядов сообщество отправить не может.
VK_MAX_ROWS = 6


def _rows(buttons: list, make_command, make_link) -> list[list]:
    rows: list[list] = []
    pair: list = []
    for b in buttons:
        if b.url:
            if pair:
                rows.append(pair)
                pair = []
            rows.append([make_link(b)])
            continue
        pair.append(make_command(b))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    return rows


def telegram(buttons: list) -> dict:
    """reply_markup для Bot API (и для aiogram: InlineKeyboardMarkup его ест)."""
    return {"inline_keyboard": _rows(
        buttons,
        lambda b: {"text": b.label, "callback_data": b.command},
        lambda b: {"text": b.label, "url": b.url},
    )}


def vk(buttons: list) -> dict:
    from app.services import vk_api

    rows = _rows(
        buttons,
        lambda b: vk_api.callback_button(b.label, b.command),
        lambda b: vk_api.link_button(b.label, b.url),
    )
    return vk_api.inline_keyboard(rows[:VK_MAX_ROWS])


def max_attachments(buttons: list) -> list:
    """Вложения сообщения MAX: клавиатура у него приходит именно так."""
    from maxapi.types.attachments.buttons.callback_button import CallbackButton
    from maxapi.types.attachments.buttons.link_button import LinkButton
    from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    for row in _rows(
        buttons,
        lambda b: CallbackButton(text=b.label, payload=b.command),
        lambda b: LinkButton(text=b.label, url=b.url),
    ):
        kb.row(*row)
    return [kb.as_markup()]


def email_tail(buttons: list) -> str:
    """Чем кнопки заменяются в письме: у почты их нет, а действие должно
    остаться доступным — ведём на «Мои записи»."""
    from app.services.bot_actions import site_url

    return f"\n\nПодтвердить, перенести или отменить: {site_url('/bookings')}"
