# app/web/pages/password_reset.py
"""Страницы сброса пароля: запрос ссылки и установка нового пароля."""
import html

from fastapi import Request

from app.web.components.styles import get_base_styles


def _shell(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — руми</title>
    {get_base_styles()}
</head>
<body class="auth-page">
    <div class="auth-card">
        <div class="auth-logo">руми.</div>
        {body}
        <div class="auth-links">
            <a href="/login">Вход</a> · <a href="/">На главную</a>
        </div>
    </div>
</body>
</html>"""


def render_forgot_password_page(request: Request) -> str:
    q = request.query_params
    if q.get("sent"):
        body = """
        <h1 class="auth-title">Проверьте сообщения</h1>
        <p style="color:var(--color-muted);font-size:0.9rem;line-height:1.5">
            Если аккаунт с этим номером существует и к нему привязан Telegram
            или почта — мы отправили ссылку для смены пароля (действует 30 минут).
        </p>"""
        return _shell("Сброс пароля", body)

    body = """
        <h1 class="auth-title">Забыли пароль?</h1>
        <p style="color:var(--color-muted);font-size:0.9rem;margin-bottom:1rem">
            Укажите телефон аккаунта — пришлём ссылку для смены пароля
            в привязанный Telegram и на почту.
        </p>
        <form action="/api/v1/auth/forgot-password" method="post">
            <div class="form-group">
                <label for="phone">Телефон</label>
                <input type="tel" id="phone" name="phone" value="+7" placeholder="+7 (___) ___-__-__" class="phone-input" required>
            </div>
            <button type="submit" class="btn-primary auth-btn">Отправить ссылку</button>
        </form>"""
    return _shell("Сброс пароля", body)


def render_reset_password_page(request: Request) -> str:
    q = request.query_params
    token = html.escape(q.get("token", ""), quote=True)
    error = q.get("error", "")

    if error == "bad_token" or not token:
        body = """
        <h1 class="auth-title">Ссылка не подходит</h1>
        <p style="color:var(--color-muted);font-size:0.9rem;line-height:1.5">
            Ссылка устарела (действует 30 минут) или уже использована.
            Запросите новую на странице <a href="/forgot-password">сброса пароля</a>.
        </p>"""
        return _shell("Сброс пароля", body)

    banner = ""
    if error == "weak_password":
        banner = (
            '<div style="background:#FEE2E2;color:#991B1B;border:1px solid #FCA5A5;'
            'border-radius:0.5rem;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.875rem">'
            "Пароль не отвечает требованиям сложности</div>"
        )

    body = f"""
        <h1 class="auth-title">Новый пароль</h1>
        {banner}
        <form action="/api/v1/auth/reset-password" method="post">
            <input type="hidden" name="token" value="{token}">
            <div class="form-group">
                <label for="password">Придумайте новый пароль</label>
                <input type="password" id="pw" name="password" required minlength="8">
                <ul class="password-rules">
                    <li data-rule="len"><span class="mark">✗</span> Минимум 8 символов</li>
                    <li data-rule="lower"><span class="mark">✗</span> Строчная буква</li>
                    <li data-rule="upper"><span class="mark">✗</span> Заглавная буква</li>
                    <li data-rule="digit"><span class="mark">✗</span> Цифра</li>
                </ul>
            </div>
            <button type="submit" id="submitBtn" class="btn-primary auth-btn" disabled>Сменить пароль</button>
        </form>"""
    return _shell("Новый пароль", body)
