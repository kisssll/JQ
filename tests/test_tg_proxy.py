# tests/test_tg_proxy.py
"""Прокси для Telegram нужен в ДВУХ местах, и это легко забыть.

Опрос ведёт aiogram, а уведомления уходят мимо него — прямым вызовом Bot API
из воркера. Проксировать только бота значит получить живого бота, который
молчит: сообщения не доходят, а причина неочевидна.
"""
import inspect

import pytest

from app.core.config import settings


@pytest.mark.parametrize("raw,expected", [
    ("", None),
    ("   ", None),                                   # пробелы из .env — не адрес
    ("http://u:p@10.0.0.1:3128", "http://u:p@10.0.0.1:3128"),
    ("  http://u:p@10.0.0.1:3128  ", "http://u:p@10.0.0.1:3128"),
])
def test_proxy_decision_is_made_in_one_place(monkeypatch, raw, expected):
    monkeypatch.setattr(settings, "TG_PROXY_URL", raw)
    assert settings.tg_proxy == expected


def test_direct_by_default():
    """Прокси — лечение аварии, а не норма: пусто = ходим напрямую."""
    assert settings.TG_PROXY_URL == ""
    assert settings.tg_proxy is None


def test_proxy_dependency_is_installed():
    """aiogram строит ЛЮБОЙ прокси через aiohttp_socks, даже обычный HTTP.
    Без пакета бот падает на старте с RuntimeError — что и случилось на
    проде 11.09.2026, потому что зависимость забыли."""
    from aiogram.client.session.aiohttp import AiohttpSession

    session = AiohttpSession(proxy="http://user:pass@10.0.0.1:3128")
    assert session is not None


def test_bot_polling_uses_the_shared_decision():
    import app.tg_bot as tg_bot

    src = inspect.getsource(tg_bot)
    assert "AiohttpSession(proxy=settings.tg_proxy)" in src
    # И умеет без прокси: иначе на стенде бот вообще не поднимется.
    assert "else:\n        bot = Bot(token=settings.TG_BOT_TOKEN)" in src


def test_notifications_use_the_same_decision():
    """Главная ловушка: бот оживёт, а уведомления продолжат молчать."""
    import app.tasks as tasks

    src = inspect.getsource(tasks._send_via_telegram)
    assert "proxy=settings.tg_proxy" in src


def test_both_places_read_the_same_property():
    """Разъедутся — придётся искать, почему бот жив, а сообщений нет."""
    import app.tasks as tasks
    import app.tg_bot as tg_bot

    assert "settings.tg_proxy" in inspect.getsource(tasks._send_via_telegram)
    assert "settings.tg_proxy" in inspect.getsource(tg_bot)
    # Прямых обращений к сырой настройке в обход свойства быть не должно.
    assert "settings.TG_PROXY_URL" not in inspect.getsource(tg_bot)
    assert "settings.TG_PROXY_URL" not in inspect.getsource(tasks._send_via_telegram)
