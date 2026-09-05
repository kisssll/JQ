# tests/test_metrika_consent.py
"""Яндекс.Метрика и согласие на аналитические cookie.

П. 2.3 Политики использования файлов cookie разрешает аналитические cookie
только после согласия. Здесь закреплено главное: сам тег счётчика в разметку
не попадает никогда, страница отдаёт лишь номер, а решение принимает
cookie-notice.js. И пока номер не задан — CSP остаётся узким.
"""
import pathlib

import pytest

from app.core.config import settings

JS = (pathlib.Path(__file__).resolve().parents[1]
      / "static" / "src" / "js" / "cookie-notice.js").read_text(encoding="utf-8")


def _rendered(monkeypatch, counter: str) -> str:
    monkeypatch.setattr(settings, "YANDEX_METRIKA_ID", counter)
    import app.web.components.styles as styles
    return styles.get_base_styles()


def test_counter_absent_by_default(monkeypatch):
    """Без номера счётчика на странице нет ни тега, ни meta."""
    html = _rendered(monkeypatch, "")
    assert "ym-counter" not in html
    assert "mc.yandex.ru" not in html


def test_counter_id_travels_as_meta_not_as_script(monkeypatch):
    """Номер отдаём meta-тегом. Сам счётчик грузит JS и только по согласию —
    будь тег в разметке, он бы сработал до всякого выбора."""
    html = _rendered(monkeypatch, "99887766")
    assert '<meta name="ym-counter" content="99887766">' in html
    assert "mc.yandex.ru" not in html
    assert "tag.js" not in html


@pytest.mark.parametrize("counter", ['"><script>alert(1)</script>', "12<b>34"])
def test_counter_id_is_escaped(monkeypatch, counter):
    """Номер приходит из окружения — в атрибут кладём экранированным."""
    html = _rendered(monkeypatch, counter)
    assert "<script>alert(1)</script>" not in html
    assert "<b>" not in html


def test_csp_stays_narrow_without_counter(monkeypatch):
    """Пока счётчика нет, политика прежняя, узкая — включая ту, что реально
    отдаётся (она считается один раз при импорте)."""
    import app.core.middleware as mw
    monkeypatch.setattr(settings, "YANDEX_METRIKA_ID", "")
    assert "mc.yandex.ru" not in mw._csp()
    assert "connect-src 'self';" in mw._csp()
    assert "mc.yandex.ru" not in mw._CSP


def test_csp_opens_metrika_hosts_with_counter(monkeypatch):
    """connect-src обязателен отдельной директивой: без него он наследует
    default-src 'self', и отчёты счётчика молча блокировались бы."""
    import app.core.middleware as mw
    monkeypatch.setattr(settings, "YANDEX_METRIKA_ID", "99887766")
    csp = mw._csp()
    for directive in ("script-src", "img-src", "connect-src"):
        part = [p for p in csp.split("; ") if p.startswith(directive)][0]
        assert "https://mc.yandex.ru" in part, directive


async def test_response_carries_csp_header(client):
    r = await client.get("/login")
    assert "Content-Security-Policy" in r.headers
    assert "connect-src" in r.headers["Content-Security-Policy"]


# ── правила согласия, зафиксированные в cookie-notice.js ────────────────────

def test_metrika_loads_only_on_explicit_accept():
    """Загрузчик вызывается лишь в ветке «Принять»."""
    assert "if (choice === ACCEPT_ALL) loadMetrika(id)" in JS
    assert "if (value === ACCEPT_ALL) loadMetrika(id)" in JS
    # Других точек вызова быть не должно — только эти две и само объявление.
    calls = [ln.strip() for ln in JS.splitlines()
             if "loadMetrika(" in ln and not ln.strip().startswith("function ")]
    assert len(calls) == 2, calls


def test_old_dismissal_is_not_treated_as_consent():
    """Старое «Понятно» закрывало уведомление, а не разрешало аналитику:
    как согласие оно не засчитывается, вопрос задаётся заново."""
    assert "readConsent" in JS
    assert "v === ACCEPT_ALL || v === NECESSARY_ONLY" in JS


def test_webvisor_stays_off():
    """Вебвизор пишет сессию целиком — для счёта посещений это лишние ПДн."""
    assert "webvisor: false" in JS


def test_banner_offers_a_real_choice():
    assert "Только необходимые" in JS
    assert "Принять" in JS


# ── Политика cookie должна описывать то, что сайт делает на самом деле ──────

COOKIES_DOC = (pathlib.Path(__file__).resolve().parents[1]
               / "app" / "web" / "legal" / "cookies.html").read_text(encoding="utf-8")


def test_policy_no_longer_denies_analytics():
    """Прежняя редакция в трёх местах заявляла, что аналитики нет. Включить
    счётчик, не тронув документ, значило бы опубликовать неправду."""
    for stale in (
        "Аналитические и рекламные файлы cookie на дату настоящей редакции на Сайте не применяются",
        "Аналитические и рекламные файлы cookie на Сайте не устанавливаются",
        "не установлено сторонних сервисов",
    ):
        assert stale not in COOKIES_DOC, stale


def test_policy_names_metrika_and_its_cookies():
    assert "Яндекс.Метрика" in COOKIES_DOC
    assert "yandex.ru/legal/confidential" in COOKIES_DOC
    for name in ("_ym_uid", "_ym_d", "_ym_isad"):
        assert name in COOKIES_DOC, name
    assert "Вебвизор) не ведётся" in COOKIES_DOC


def test_policy_matches_the_storage_keys_we_actually_use():
    """Таблица раздела 3 называет ключи хранения — они менялись вместе
    с баннером, и разойтись с кодом не должны."""
    assert "cookieConsent" in COOKIES_DOC and "cookieNoticeAccepted" in COOKIES_DOC
    assert "cookieConsent" in JS and "cookieNoticeAccepted" in JS


async def test_cookies_page_has_its_own_edition_date(client):
    """У Политики cookie своя дата: общую LEGAL_VERSION не двигаем, она уходит
    в журнал согласий, а текст Согласия не менялся."""
    from app.web.pages.legal import LEGAL_VERSION, LEGAL_VERSION_HUMAN
    r = await client.get("/cookies")
    assert r.status_code == 200
    assert "Редакция от 5 сентября 2026" in r.text
    assert LEGAL_VERSION == "2026-08-18"

    other = await client.get("/privacy")
    assert f"Редакция от {LEGAL_VERSION_HUMAN}" in other.text


async def test_consent_can_be_withdrawn_from_the_policy_page(client):
    """П. 5.3 обещает кнопку «Изменить выбор» — она должна быть на странице,
    и только на ней."""
    r = await client.get("/cookies")
    assert 'id="cookieResetChoice"' in r.text
    assert "Изменить выбор" in r.text
    assert "cookieResetChoice" in JS

    other = await client.get("/terms")
    assert "cookieResetChoice" not in other.text
