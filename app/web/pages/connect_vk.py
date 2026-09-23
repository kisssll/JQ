# app/web/pages/connect_vk.py
"""Страница привязки ВКонтакте — один экран, одна кнопка.

Зачем отдельная страница. Из бота кнопка «Привязать аккаунт» вела на /profile,
где нужный блок — примерно седьмой экран вниз. 17.09.2026 человек до него не
дошёл и решил, что привязка не работает (она работала). Здесь нет ничего,
кроме самой привязки.

Два пути к боту, потому что первый срабатывает не всегда:
  * кнопка открывает диалог с сообществом, и ВКонтакте передаёт боту код
    вместе с первым сообщением человека;
  * если в диалоге уже была переписка, кнопки «Начать» там нет — тогда
    работает код, показанный на этой же странице: его можно отправить боту
    сообщением.
"""
from __future__ import annotations

from app.core.config import settings
from app.web.components.escaping import e
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.styles import get_base_styles


def _page(title: str, body: str, user=None) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{e(title)} | Руми</title>
    <meta name="robots" content="noindex">
    {get_base_styles()}
</head>
<body>
    {render_header("profile")}
    <main class="main-content">
        <div class="section-container" style="max-width:34rem;padding-top:2rem;padding-bottom:3rem">
            {body}
        </div>
    </main>
    {render_footer(user)}
</body>
</html>"""


def render_already_linked(user) -> str:
    """ВК уже привязан: показываем к какому аккаунту — если ссылку успел
    открыть кто-то другой, человек увидит чужое имя и сможет отвязать."""
    who = e(getattr(user, "vk_name", None) or "")
    return _page("ВКонтакте подключён", f"""
            <h1 class="text-display" style="margin-bottom:0.75rem">ВКонтакте уже подключён ✅</h1>
            <p class="text-body">Аккаунт: <strong>{who or 'ваш профиль ВКонтакте'}</strong>.
                Уведомления Руми могут приходить в этот чат.</p>
            <div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.5rem">
                <a class="btn-primary" href="/profile">В профиль</a>
                <form method="post" action="/api/v1/users/me/disconnect-channel">
                    <input type="hidden" name="channel" value="vk">
                    <button class="btn-outline" type="submit">Отвязать</button>
                </form>
            </div>""", user)


def render_connect_vk(user, code: str) -> str:
    link = f"https://vk.me/{settings.vk_bot_address}?ref={e(code)}"
    return _page("Привязать ВКонтакте", f"""
            <h1 class="text-display" style="margin-bottom:0.75rem">Привязать ВКонтакте</h1>
            <p class="text-body">Нажмите кнопку — откроется диалог с сообществом Руми.
                Дальше бот узнает вас сам, и уведомления о записях смогут приходить туда.</p>
            <a class="btn-primary" href="{link}" style="display:inline-flex;margin:1.25rem 0 0.5rem"
               target="_blank" rel="noopener">Открыть ВКонтакте</a>
            <div style="border:1px solid var(--color-border);border-radius:0.9rem;padding:1rem;margin-top:1.5rem">
                <p class="settings-card-hint" style="margin:0 0 0.5rem">
                    Если бот не ответил — отправьте ему этот код сообщением:</p>
                <p style="font-size:1.6rem;font-weight:700;letter-spacing:0.08em;margin:0;
                          color:var(--color-heading)">{e(code)}</p>
                <p class="settings-card-hint" style="margin:0.5rem 0 0">
                    Код действует 15 минут и работает один раз. Кнопки «Начать» в диалоге
                    может не быть — это нормально, достаточно кода или любого сообщения.</p>
            </div>
            <p class="settings-card-hint" style="margin-top:1.25rem">
                Передумали? <a href="/profile">Вернуться в профиль</a>.</p>""", user)
