# app/web/pages/login.py
import html
from fastapi import Request
from app.core.config import settings
from app.web.components.styles import get_base_styles

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
                  background:#000;color:#fff;border-radius:0.5rem;padding:0.75rem;text-decoration:none;font-weight:600">
            <span style="background:#FC3F1D;color:#fff;border-radius:50%;width:1.4rem;height:1.4rem;
                         display:inline-flex;align-items:center;justify-content:center;font-weight:700">Я</span>
            Войти с Яндекс ID
        </a>"""

# Кнопка «Войти с VK ID» — фирменный синий VK, рендер по флагу
VK_BUTTON = """
        <a href="/api/v1/auth/vk/start" class="auth-btn"
           style="display:flex;align-items:center;justify-content:center;gap:0.5rem;width:100%;
                  background:#0077FF;color:#fff;border-radius:0.5rem;padding:0.75rem;text-decoration:none;font-weight:600;margin-top:0.5rem">
            <span style="background:#fff;color:#0077FF;border-radius:0.35rem;width:1.4rem;height:1.4rem;
                         display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:0.7rem">VK</span>
            Войти с VK ID
        </a>"""


def _alert(msg: str) -> str:
    """Баннер-уведомление об ошибке."""
    if not msg:
        return ""
    return (
        '<div style="background:#FEE2E2;color:#991B1B;border:1px solid #FCA5A5;'
        'border-radius:0.5rem;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.875rem">'
        f'{msg}</div>'
    )


def render_login_page(request: Request) -> str:
    """Страница входа."""
    q = request.query_params
    redirect = html.escape(q.get("redirect", "/"), quote=True)
    phone = html.escape(q.get("phone") or "+7", quote=True)
    errors = {
        "1": "Неверный телефон или пароль",
        "locked": "Слишком много попыток входа. Попробуйте через 15 минут.",
        "yandex": "Не получилось войти через Яндекс — попробуйте ещё раз или войдите по телефону",
        "vk": "Не получилось войти через VK — попробуйте ещё раз или войдите по телефону",
    }
    success = ""
    if q.get("reset"):
        success = (
        '<div style="background:#DCFCE7;color:#166534;border:1px solid #86EFAC;'
        'border-radius:0.5rem;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.875rem">'
        'Пароль изменён — войдите с новым</div>'
        )
    banner = _alert(errors.get(q.get("error", ""), ""))
    oauth_buttons = ""
    if settings.YANDEX_OAUTH_ENABLED:
        oauth_buttons += YANDEX_BUTTON
    if settings.VK_OAUTH_ENABLED:
        oauth_buttons += VK_BUTTON
    yandex_block = (OAUTH_DIVIDER + oauth_buttons) if oauth_buttons else ""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Вход — руми</title>
    {get_base_styles()}
</head>
<body class="auth-page">
    <div class="auth-card">
        <div class="auth-logo">руми.</div>
        <h1 class="auth-title">Вход</h1>
        {banner}{success}
        <form action="/api/v1/auth/login-web" method="post">
            <input type="hidden" name="redirect" value="{redirect}">
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

        <!-- Кнопка регистрации (белая с розовой надписью) -->
        <button type="button" class="auth-btn-outline" onclick="window.location.href='/register'">Регистрация</button>

        {yandex_block}
        <div class="auth-links">
            <a href="/forgot-password">Забыли пароль?</a> · <a href="/">На главную</a>
        </div>
    </div>
</body>
</html>"""