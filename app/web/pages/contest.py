# app/web/pages/contest.py
"""Страница правил конкурса.

Обязательна по ст. 9 закона «О рекламе»: в сообщении о стимулирующем
мероприятии должны быть названы сроки, организатор, правила, порядок
определения победителей и выдачи призов. Бот и рассылка ссылаются сюда, а не
пересказывают условия своими словами — иначе версии разъедутся.

Чего здесь нет, того нет намеренно: партнёрские призы и площадка финала не
названы организатором, и придумывать их нельзя (см. services/contest.py).
"""
from __future__ import annotations

from app.core.config import settings
from app.services import contest
from app.web.components.escaping import e
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles


def _bot_links() -> str:
    """Куда идти подавать заявку — в тот бот, который у человека есть."""
    links = []
    vk = settings.vk_bot_address
    if vk:
        links.append((f"https://vk.me/{vk}", "ВКонтакте"))
    tg = (settings.TG_BOT_USERNAME or "").strip().lstrip("@")
    if tg:
        links.append((f"https://t.me/{tg}", "Telegram"))
    mx = (settings.MAX_BOT_USERNAME or "").strip().lstrip("@")
    if mx:
        links.append((f"https://max.ru/{mx}", "MAX"))
    return "".join(
        f'<a class="btn-outline" href="{e(url)}" target="_blank" rel="noopener">{label}</a>'
        for url, label in links
    )


def _rules_list() -> list[tuple[str, str]]:
    c = contest
    prize = (f"Победители ({c.WINNERS} человека) получают {c.PRIZE}, отметку "
             f"«Победитель конкурса Руми» в каталоге и место выше в выдаче "
             f"по умолчанию в течение 3 месяцев.")
    if c.PARTNER_PRIZES:
        prize += f" Призы партнёров: {c.PARTNER_PRIZES}."
    final = (f"{c.ru_date(c.FINAL_DATE)} — финал: участники создают образ "
             f"вживую, победителей определяют эксперты, приглашённые "
             f"организатором.")
    if c.FINAL_PLACE:
        final += f" Место проведения: {c.FINAL_PLACE}."
    return [
        ("Организатор", f"{c.ORGANIZER}. Связь: {c.CONTACT_EMAIL}."),
        ("Кто может участвовать",
         f"Визажисты города {c.CITY} в возрасте от {c.MIN_AGE} лет. "
         "Участие бесплатное, ничего покупать не нужно."),
        ("Сроки",
         f"Приём заявок: {c.ru_date(c.ENTRY_START)} — {c.ru_date(c.ENTRY_END)} 2026 года. "
         f"Голосование подписчиков: {c.ru_date(c.VOTING_START)} — {c.ru_date(c.VOTING_END)}. "
         f"Объявление участников финала: {c.ru_date(c.RESULTS_DATE)}. "
         f"Финал: {c.ru_date(c.FINAL_DATE)}."),
        ("Как участвовать",
         f"1. Выложите фото или видео образа в стиле Хеллоуина в свою соцсеть "
         f"с хэштегом {c.HASHTAG} и отметкой Руми. "
         f"2. Отправьте заявку в боте Руми: имя, город, ссылка на работу и контакт."),
        ("Как определяются победители",
         f"Первый этап — открытое голосование подписчиков в сообществе "
         f"{c.VK_GROUP_URL} и в Telegram-канале Руми. {final}"),
        ("Призы", prize),
        ("Данные участников",
         "Имя, город, ссылка на работу и контакт используются только для "
         "проведения конкурса: связаться с участником, объявить результаты и "
         "выдать приз. Хранятся в базе Руми в России. Отозвать согласие и "
         "удалить заявку можно письмом на " + c.CONTACT_EMAIL + "."),
    ]


def render_contest_page(user=None) -> str:
    rules = "".join(
        f'<section style="margin-bottom:1.5rem">'
        f'<h2 class="text-heading" style="font-size:1.15rem;margin-bottom:0.4rem">{e(title)}</h2>'
        f'<p class="text-body" style="margin:0">{e(text)}</p></section>'
        for title, text in _rules_list()
    )
    window = "" if contest.accepts_entries() else (
        f'<p class="text-body" style="margin-top:0.5rem"><strong>'
        f'{e(contest.entry_window_note())}</strong></p>')
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{e(contest.TITLE)}</title>
    <meta name="description" content="Конкурс визажистов от Руми: образ в стиле Хеллоуина, голосование подписчиков и финал вживую. Правила, сроки и призы.">
    {get_base_styles()}
</head>
<body>
    {render_header("contest")}
    {render_sidebar("contest", user)}
    <main class="main-content">
        <div class="section-container" style="max-width:44rem;padding-top:5.5rem;padding-bottom:3rem">
            <h1 class="text-display" style="margin-bottom:0.75rem">{e(contest.TITLE)}</h1>
            <p class="text-body">Задание — образ в стиле Хеллоуина. Заявка подаётся в боте Руми,
                там же мы ответим на вопросы.</p>
            {window}
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin:1.25rem 0 2rem">{_bot_links()}</div>
            {rules}
        </div>
    </main>
    {render_footer(user)}
</body>
</html>"""
