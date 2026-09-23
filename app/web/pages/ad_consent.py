# app/web/pages/ad_consent.py
"""Страница согласия на подборку вечерних окон — для тех, кого спросили письмом.

Ссылка из письма открывает эту страницу, но согласия НЕ записывает. Согласие
записывает только нажатие кнопки (POST). Почтовые сканеры и превью ссылок
заранее открывают всё, что есть в письме, и если бы согласие давал сам
переход, в журнале лежало бы согласие, «данное» роботом за человека, — а
предъявлять его нам как доказательство.
"""
import html

from app.services import ad_consent
from app.web.components.styles import get_base_styles


def _shell(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex, nofollow">
    <title>{title} — руми</title>
    {get_base_styles()}
</head>
<body class="auth-page">
    <div class="auth-card">
        <div class="auth-logo">руми.</div>
        {body}
        <div class="auth-links"><a href="/">На главную</a></div>
    </div>
</body>
</html>"""


def render_question(token: str) -> str:
    question = html.escape(ad_consent.QUESTION_TEXT).replace("\n\n", "</p><p>")
    body = f"""
        <h1 class="auth-title">Подборка вечерних окон</h1>
        <p style="color:var(--color-body);font-size:0.9rem;line-height:1.55">{question}</p>
        <form method="post" action="/consent/promo" data-submit-lock>
            <input type="hidden" name="t" value="{html.escape(token, quote=True)}">
            <button type="submit" class="btn-primary auth-btn">{html.escape(ad_consent.OPT_IN_LABEL)}</button>
        </form>"""
    return _shell("Подборка вечерних окон", body)


def render_done() -> str:
    body = f"""
        <h1 class="auth-title">Готово</h1>
        <p style="color:var(--color-body);font-size:0.9rem;line-height:1.55">{html.escape(ad_consent.THANKS_TEXT)}</p>"""
    return _shell("Подборка вечерних окон", body)


def render_bad_link() -> str:
    body = """
        <h1 class="auth-title">Ссылка не подходит</h1>
        <p style="color:var(--color-muted);font-size:0.9rem;line-height:1.55">
            Ссылка устарела или повреждена. Ничего страшного: подборку можно
            включить в разделе «Мои уведомления» в Telegram или MAX.
        </p>"""
    return _shell("Ссылка не подходит", body)
