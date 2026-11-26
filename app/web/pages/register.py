# app/web/register.py
from app.web.components.escaping import e
import html
from urllib.parse import quote
from fastapi import Request
from app.core.config import settings
from app.web.components.styles import get_base_styles
from app.web.components.consent import render_consent_block
from app.services.auth_redirect import safe_sport_redirect
from app.web.components.icons import (
    ICON_X,
)


def _alert(msg: str) -> str:
    if not msg:
        return ""
    return (
        '<div class="r-notice r-notice--danger auth-alert" role="alert">'
        f'{msg}</div>'
    )


def _sms_code_block() -> str:
    """Блок ввода кода из СМС. Рендерится, только когда СМС-канал реально
    доступен (live-провайдер, либо mock вне production для разработки)."""
    return """
            <div class="form-group" id="codeGroup" style="display:none">
                <label for="code">Код из SMS / звонка</label>
                <input type="text" id="code" name="code" placeholder="1234" inputmode="numeric" autocomplete="one-time-code">
                <p id="codeHint" style="font-size:0.75rem;color:var(--color-muted);margin-top:0.375rem"></p>
            </div>"""


def _messenger_verify_block(tg: bool, max_: bool) -> str:
    """Кнопки подтверждения через ботов (блок 18): Telegram и/или MAX.
    Бот просит «Поделиться контактом», страница поллит статус
    (verify-messenger.js — один скрипт на оба канала)."""
    buttons = ""
    if tg:
        buttons += """
                <button type="button" class="btn-primary msgr-verify-btn" style="flex:1"
                    data-channel="Telegram" data-start-url="/api/v1/auth/register/tg-start">Подтвердить в Telegram</button>"""
    if max_:
        buttons += """
                <button type="button" class="btn-primary msgr-verify-btn" style="flex:1"
                    data-channel="MAX" data-start-url="/api/v1/auth/register/max-start">Подтвердить в MAX</button>"""
    return f"""
            <div class="form-group" id="msgrVerifyGroup">
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap">{buttons}
                </div>
                <p id="msgrHint" style="font-size:0.75rem;color:var(--color-muted);margin-top:0.375rem">Откроется наш бот — нажмите в нём «Поделиться контактом», код вводить не нужно</p>
            </div>"""


def render_register_page(request: Request) -> str:
    """Страница регистрации."""
    q = request.query_params
    phone = html.escape(q.get("phone") or "+7", quote=True)
    full_name = html.escape(q.get("full_name", ""), quote=True)
    # Адрес возврата после регистрации (страница подключения тарифа и т.п.).
    # Проверка на open redirect — на сервере, здесь только переносим значение.
    sport_route = request.url.path == "/sport/register"
    redirect_raw = q.get("redirect", "")
    sport_flow = (
        sport_route
        or redirect_raw == "/sport"
        or redirect_raw.startswith("/sport/")
    )
    redirect_target = safe_sport_redirect(redirect_raw) if sport_flow else redirect_raw
    body_class = "auth-page sport-directory rumi-sport" if sport_flow else "auth-page"
    page_title = "Регистрация в Руми Спорт" if sport_flow else "Регистрация"
    home_href = "/sport" if sport_flow else "/"
    redirect_field = (
        f'<input type="hidden" name="redirect" value="{html.escape(redirect_target, quote=True)}">'
        if redirect_target else ""
    )
    login_path = "/sport/login" if sport_flow else "/login"
    forgot_path = "/sport/forgot-password" if sport_flow else "/forgot-password"
    login_href = (
        f"{login_path}?redirect={html.escape(quote(redirect_target, safe=''), quote=True)}"
        if redirect_target else login_path
    )
    errors = {
        "phone_exists": "Пользователь с таким телефоном уже зарегистрирован",
        "weak_password": "Пароль не отвечает требованиям сложности",
        "bad_phone": "Неверный формат телефона. Пример: +7 (999) 123-45-67",
        "no_code": "Подтвердите телефон перед регистрацией",
        "no_consent": "Отметьте согласие на обработку персональных данных",
        "bad_code": "Подтверждение не прошло или истекло — попробуйте ещё раз",
        "otp_unavailable": "Сервис подтверждения временно недоступен, попробуйте позже",
        "yandex_no_phone": "Яндекс не поделился вашим номером — зарегистрируйтесь по телефону, это пара минут",
        "vk_no_phone": "VK не поделился вашим номером — зарегистрируйтесь по телефону, это пара минут",
    }
    error_code = q.get("error", "")
    if error_code == "phone_exists":
        # Чаще всего это не «номер занял кто-то чужой», а повторная отправка
        # своей же формы: первый запрос успел создать аккаунт, второй увидел
        # номер занятым (инцидент 04.09.2026). Поэтому не тупик, а выходы.
        back = html.escape(quote(q.get("phone") or "", safe=""), quote=True)
        redirect_suffix = (
            f"&redirect={html.escape(quote(redirect_target, safe=''), quote=True)}"
            if redirect_target else ""
        )
        link = 'color:var(--color-danger);font-weight:600;text-decoration:underline'
        banner = _alert(
            "Пользователь с таким телефоном уже зарегистрирован. "
            f'<a href="{login_path}?phone={back}{redirect_suffix}" style="{link}">Войти</a> · '
            f'<a href="{forgot_path}?phone={back}{redirect_suffix}" style="{link}">Забыли пароль?</a>'
            '<div style="margin-top:0.375rem;font-size:0.8125rem">Если вы только что '
            'заполняли эту форму — аккаунт уже создан, войдите с тем паролем, '
            'который придумали.</div>'
        )
    else:
        banner = _alert(errors.get(error_code, ""))

    otp_enabled = settings.OTP_ENABLED
    # Каналы подтверждения. СМС в production с mock-провайдером — не канал
    # (эндпоинт send-code такое отбивает), поэтому и кнопку не рисуем.
    sms_available = otp_enabled and (
        settings.SMS_MODE == "live" or settings.ENVIRONMENT != "production"
    )
    tg_available = otp_enabled and settings.TG_VERIFY_ENABLED
    max_available = otp_enabled and settings.MAX_VERIFY_ENABLED

    # Кнопка «Получить код» рядом с телефоном — только при доступном СМС-канале
    phone_input = f'<input type="tel" id="phone" name="phone" value="{phone}" placeholder="+7 (___) ___-__-__" class="phone-input" required>'
    if sms_available:
        phone_group = f"""
            <div class="form-group">
                <label for="phone">Телефон</label>
                <div style="display:flex;gap:0.5rem">
                    <div style="flex:1">{phone_input}</div>
                    <button type="button" id="sendCodeBtn" class="btn-primary" style="white-space:nowrap;padding:0 1rem;font-size:0.8rem">Получить код</button>
                </div>
            </div>"""
    else:
        phone_group = f"""
            <div class="form-group">
                <label for="phone">Телефон</label>
                {phone_input}
            </div>"""

    # request_id общий для всех каналов (его заполняет otp-code.js либо
    # verify-messenger.js), поэтому hidden-поле рендерится при любом OTP
    verify_blocks = ""
    if otp_enabled:
        verify_blocks = '<input type="hidden" id="request_id" name="request_id" value="">'
        if tg_available or max_available:
            verify_blocks = _messenger_verify_block(tg_available, max_available) + verify_blocks
        if sms_available:
            verify_blocks = _sms_code_block() + verify_blocks

    # Все скрипты приходят из общего vite-бандла (get_base_styles → dist/main.js)
    # и сами проверяют наличие своих элементов. Отдельные <script src=...> здесь
    # НЕ добавлять: второй тег = двойные обработчики = двойные запросы.
    scripts = ""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{page_title} — Руми</title>
    {get_base_styles()}
</head>
<body class="{body_class}">
    <div class="auth-card">
        <div class="auth-logo">руми.</div>
        {'<p class="auth-context">Руми Спорт</p>' if sport_flow else ''}
        <h1 class="auth-title">Регистрация</h1>
        {banner}
        <form action="/api/v1/auth/register-web" method="post" data-submit-lock>
            {redirect_field}
            {'<input type="hidden" name="auth_variant" value="sport">' if sport_flow else ''}
            <div class="form-group">
                <label for="full_name">Имя</label>
                <input type="text" id="full_name" name="full_name" value="{e(full_name)}" placeholder="Ваше имя">
            </div>{phone_group}{verify_blocks}
            <div class="form-group">
                <label for="password">Пароль</label>
                <input type="password" id="pw" name="password" required minlength="8">
                <ul class="password-rules">
                    <li data-rule="len"><span class="mark">{ICON_X}</span> Минимум 8 символов</li>
                    <li data-rule="lower"><span class="mark">{ICON_X}</span> Строчная буква</li>
                    <li data-rule="upper"><span class="mark">{ICON_X}</span> Заглавная буква</li>
                    <li data-rule="digit"><span class="mark">{ICON_X}</span> Цифра</li>
                </ul>
            </div>
            {render_consent_block(action="Регистрируясь")}
            <button type="submit" id="submitBtn" class="btn-primary auth-btn" disabled>Зарегистрироваться</button>
        </form>
        <div class="auth-links">
            <a href="{login_href}">Вход</a> · <a href="{home_href}">На главную</a>
        </div>
    </div>
    {scripts}
</body>
</html>"""
