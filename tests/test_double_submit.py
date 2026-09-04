# tests/test_double_submit.py
"""Защита от двойной отправки форм авторизации.

Инцидент 04.09.2026: регистрация отвечала ~1,5 с при активной кнопке, человек
нажал второй раз — первый запрос создал аккаунт, второй вернул «телефон уже
зарегистрирован» на только что созданный номер. Здесь закреплены три части
починки: замок на кнопке, выходы из ошибки и лимит на эндпоинт.
"""
import pathlib
import re

import pytest

JS_DIR = pathlib.Path(__file__).resolve().parents[1] / "static" / "src" / "js"

LOCKED_PAGES = [
    "/register",
    "/login",
    "/forgot-password",
    "/reset-password?token=whatever",
]


@pytest.mark.parametrize("path", LOCKED_PAGES)
async def test_auth_forms_are_locked_against_double_submit(client, path):
    """Каждая форма авторизации помечена для submit-lock.js."""
    r = await client.get(path)
    assert r.status_code == 200
    assert "data-submit-lock" in r.text, f"{path}: форма без замка"


async def test_locked_forms_have_submit_button(client):
    """Замок вешается на кнопку сабмита — без неё гасить нечего."""
    for path in LOCKED_PAGES:
        html = (await client.get(path)).text
        for form in re.findall(r"<form[^>]*data-submit-lock.*?</form>", html, re.S):
            assert 'type="submit"' in form, f"{path}: в форме нет кнопки сабмита"


def test_submit_lock_is_in_the_bundle():
    """Модуль подключён к общему бандлу: иначе атрибут в разметке — пустышка."""
    main_js = (JS_DIR / "main.js").read_text(encoding="utf-8")
    assert "./submit-lock.js" in main_js


def test_submit_lock_respects_prevented_submit():
    """Отменённый сабмит (диалог подтверждения) замок не ставит — запрос ещё
    не ушёл, иначе кнопка залипла бы навсегда."""
    src = (JS_DIR / "submit-lock.js").read_text(encoding="utf-8")
    assert "defaultPrevented" in src
    # Возврат «назад» из bfcache отдаёт страницу с погашенной кнопкой.
    assert "pageshow" in src


async def test_phone_exists_offers_login_and_password_reset(client):
    """Ошибка «номер занят» — не тупик: даёт вход и сброс пароля с номером."""
    r = await client.get("/register?error=phone_exists&phone=%2B79993169620")
    assert r.status_code == 200
    assert "/login?phone=%2B79993169620" in r.text
    assert "/forgot-password?phone=%2B79993169620" in r.text
    # Подсказка про собственную повторную отправку — главная причина ошибки.
    assert "аккаунт уже создан" in r.text


async def test_forgot_password_prefills_phone_from_link(client):
    """Номер приезжает по ссылке с регистрации/входа — перенабирать не надо."""
    r = await client.get("/forgot-password?phone=%2B79993169620")
    assert r.status_code == 200
    assert 'value="+79993169620"' in r.text


async def test_forgot_password_without_phone_keeps_default(client):
    r = await client.get("/forgot-password")
    assert r.status_code == 200
    assert 'value="+7"' in r.text


async def test_register_web_is_rate_limited(client):
    """У формы регистрации не было лимита вовсе — дубль обрабатывался дважды
    в полную силу. Порог 10/минуту по IP."""
    form = {
        "phone": "+79990001122",
        "password": "Testpass1",
        "full_name": "Тест",
        "pd_consent": "1",
        "consent_version": "2026-08-18",
    }
    last = None
    for _ in range(11):
        last = await client.post("/api/v1/auth/register-web", data=form)
    assert last.status_code == 429
