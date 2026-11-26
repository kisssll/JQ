# app/web/pages/login.py
import html
from fastapi import Request
from app.core.config import settings
from app.services.auth_redirect import safe_sport_redirect
from app.web.components.styles import get_base_styles
from app.web.components.ui import notice

# Разделитель «или» перед блоком соц-входов (показываем, если включён хоть один)
OAUTH_DIVIDER = """
        <div style="display:flex;align-items:center;gap:0.75rem;margin:1rem 0 0.5rem">
            <div style="flex:1;height:1px;background:var(--color-border)"></div>
            <span style="font-size:0.75rem;color:var(--color-muted)">или</span>
            <div style="flex:1;height:1px;background:var(--color-border)"></div>
        </div>"""

# Кнопка «Войти с Яндекс ID» — фирменные цвета Яндекса, рендер по флагу
YANDEX_BUTTON = """
        <a href="/api/v1/auth/yandex/start" class="auth-btn"
           style="display:flex;align-items:center;justify-content:center;gap:0.5rem;width:100%;
                  background:#000;color:var(--color-on-dark);border-radius:var(--radius-8);padding:0.75rem;text-decoration:none;font-weight:600">
            <span style="background:#FC3F1D;color:var(--color-on-dark);border-radius:50%;width:1.4rem;height:1.4rem;
                         display:inline-flex;align-items:center;justify-content:center;font-weight:700">Я</span>
            Войти с Яндекс ID
        </a>"""

# Кнопка «Войти с VK ID» — фирменный синий VK, рендер по флагу
VK_BUTTON = """
        <a href="/api/v1/auth/vk/start" class="auth-btn"
           style="display:flex;align-items:center;justify-content:center;gap:0.5rem;width:100%;
                  background:#0077FF;color:var(--color-on-dark);border-radius:var(--radius-8);padding:0.75rem;text-decoration:none;font-weight:600;margin-top:0.5rem">
            <span style="background:var(--color-surface);color:#0077FF;border-radius:var(--radius-8);width:1.4rem;height:1.4rem;
                         display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:0.7rem">VK</span>
            Войти с VK ID
        </a>"""


def _alert(msg: str) -> str:
    """Баннер-уведомление об ошибке."""
    return notice(msg, tone="danger") if msg else ""


def render_login_page(request: Request) -> str:
    """Страница входа."""
    q = request.query_params
    sport_route = request.url.path == "/sport/login"
    redirect_raw = q.get("redirect", "")
    sport_flow = (
        sport_route
        or redirect_raw == "/sport"
        or redirect_raw.startswith("/sport/")
    )
    redirect_target = safe_sport_redirect(redirect_raw) if sport_flow else redirect_raw
    redirect = html.escape(redirect_target or "/", quote=True)
    body_class = "auth-page sport-directory rumi-sport" if sport_flow else "auth-page"
    page_title = "Вход в Руми Спорт" if sport_flow else "Вход"
    home_href = "/sport" if sport_flow else "/"
    # Адрес возврата передаём дальше — на регистрацию и во вход через
    # Яндекс/VK, иначе он терялся на первом же переходе.
    from urllib.parse import quote as _quote
    redirect_qs = f"?redirect={_quote(redirect_target, safe='')}" if redirect_target else ""
    register_path = "/sport/register" if sport_flow else "/register"
    forgot_path = "/sport/forgot-password" if sport_flow else "/forgot-password"
    phone = html.escape(q.get("phone") or "+7", quote=True)
    errors = {
        "1": "Неверный телефон или пароль",
        "locked": "Слишком много попыток входа. Попробуйте через 15 минут.",
        "yandex": "Не получилось войти через Яндекс — попробуйте ещё раз или войдите по телефону",
        "vk": "Не получилось войти через VK — попробуйте ещё раз или войдите по телефону",
    }
    success = ""
    if q.get("reset"):
        success = notice("Пароль изменён — войдите с новым", tone="success")
    banner = _alert(errors.get(q.get("error", ""), ""))
    oauth_buttons = ""
    if settings.YANDEX_OAUTH_ENABLED:
        oauth_buttons += YANDEX_BUTTON.replace('/api/v1/auth/yandex/start"', f'/api/v1/auth/yandex/start{html.escape(redirect_qs, quote=True)}"')
    if settings.VK_OAUTH_ENABLED:
        oauth_buttons += VK_BUTTON.replace('/api/v1/auth/vk/start"', f'/api/v1/auth/vk/start{html.escape(redirect_qs, quote=True)}"')
    yandex_block = (OAUTH_DIVIDER + oauth_buttons) if oauth_buttons else ""

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
        <h1 class="auth-title">Вход</h1>
        {banner}{success}
        <form action="/api/v1/auth/login-web" method="post" data-submit-lock>
            <input type="hidden" name="redirect" value="{redirect}">
            {'<input type="hidden" name="auth_variant" value="sport">' if sport_flow else ''}
            <div class="form-group">
                <label for="phone">Телефон</label>
                <input type="tel" id="phone" name="phone" value="{phone}" placeholder="+7 (___) ___-__-__" class="phone-input" required>
            </div>
            <div class="form-group">
                <label for="password">Пароль</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit" class="btn-primary auth-btn">Войти</button>
        </form>

        <button type="button" class="auth-btn-outline" onclick="window.location.href='{register_path}{html.escape(redirect_qs, quote=True)}'">Регистрация</button>

        {yandex_block}
        <div class="auth-links">
            <a href="{forgot_path}{html.escape(redirect_qs, quote=True)}">Забыли пароль?</a> · <a href="{home_href}">На главную</a>
        </div>
    </div>
</body>
</html>"""
