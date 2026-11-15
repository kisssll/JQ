"""Блок 05: JSON-логи, маскирование ПДн, no-op Sentry без DSN."""
import json
import logging

from app.core import observability as obs


def test_mask_phones():
    assert obs._mask_phones("клиент +79991234567 записан") == "клиент +7********** записан"
    assert obs._mask_phones("нет номера") == "нет номера"
    assert obs._mask_phones(12345) == 12345  # не строка — как есть


def test_json_formatter_valid_and_masks():
    rec = logging.LogRecord("t", logging.INFO, __file__, 1,
                            "звонок +79990001122", None, None)
    line = obs.JsonLogFormatter().format(rec)
    data = json.loads(line)  # валидный JSON
    assert data["level"] == "INFO"
    assert data["logger"] == "t"
    assert data["msg"] == "звонок +7**********"
    assert "ts" in data


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom +79990001122")
    except ValueError:
        import sys
        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "упало", None,
                                sys.exc_info())
    data = json.loads(obs.JsonLogFormatter().format(rec))
    assert "exc" in data and "ValueError" in data["exc"]


def test_before_send_scrubs_pii():
    event = {
        "logentry": {"message": "сбой у +79991112233"},
        "exception": {"values": [{"value": "no user +79994445566"}]},
    }
    out = obs._before_send(event, None)
    assert out["logentry"]["message"] == "сбой у +7**********"
    assert out["exception"]["values"][0]["value"] == "no user +7**********"


def test_init_sentry_noop_without_dsn(monkeypatch):
    monkeypatch.setattr(obs.settings, "SENTRY_DSN", "")
    obs._sentry_inited = False
    obs.init_sentry()  # не должно бросать и не должно инициализировать
    assert obs._sentry_inited is False


# ── секреты в журнале (разбор 15.11.2026) ────────────────────────────────────
#
# Повод: httpx пишет на уровне INFO полный адрес запроса, а в адресе Bot API
# лежит токен бота. Так токен стейдж-бота оказался в журнале контейнера.
# Заглушка httpx до этого стояла только в ВК-боте, а трассировки не
# маскировались вовсе — ни от токенов, ни от телефонов.

FAKE_TOKEN = "1111122222:" + "X" * 35


def test_bot_token_is_masked():
    masked = obs.mask(f"POST https://api.telegram.org/bot{FAKE_TOKEN}/sendWidget 400")
    assert "X" * 35 not in masked
    assert "bot1111122222:***" in masked, "номер бота оставляем: по нему видно, чей запрос"


def test_query_secrets_are_masked():
    masked = obs.mask("https://api.vk.com/method/messages.send?access_token=vk1a" + "z" * 40 + "&v=5.199")
    assert "z" * 40 not in masked
    assert "access_token=***" in masked
    assert "v=5.199" in masked, "остальные параметры не трогаем"


def test_mask_passes_non_strings():
    assert obs.mask(12345) == 12345
    assert obs.mask(None) is None


def test_traceback_is_masked_too():
    """Трассировка уходит в тот же журнал. Раньше она не маскировалась, и
    телефон с токеном попадали в лог даже при чистом сообщении."""
    import sys

    try:
        raise ValueError(f"сбой у +79991234567, адрес /bot{FAKE_TOKEN}/sendMessage")
    except ValueError:
        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "упало", None,
                                sys.exc_info())
    data = json.loads(obs.JsonLogFormatter().format(rec))
    assert "+79991234567" not in data["exc"]
    assert "X" * 35 not in data["exc"]
    assert "ValueError" in data["exc"], "сама ошибка остаётся читаемой"


def test_httpx_logger_is_quiet_after_setup():
    """Маска срежет токен и так, но строки про каждый запрос в журнале не
    нужны вовсе — а заглушка стояла только в одном из пяти процессов."""
    obs._logging_configured = False
    try:
        obs.setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        obs._logging_configured = False
