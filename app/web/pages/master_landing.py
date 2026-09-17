# app/web/pages/master_landing.py
"""Лендинг /dlya-masterov — реклама в Яндекс Директе для частных мастеров.

Отдельная страница, а не раздел сайта: без меню, каталога и ссылок «погулять».
Единственное целевое действие — подключиться (регистрация → пробный период
тарифа «Лайт» в режиме «для мастера»). Документы в подвале открываются в новой
вкладке и страницу не уводят.

Закрыта от поисковиков (noindex, в sitemap её нет): её задача — реклама, а не
спор в выдаче с основными страницами.

Все обещания здесь проверены по коду. Прежде чем что-то добавить, проверьте,
что это правда для частного мастера на «Лайте»: реклама с ложным обещанием —
это и нарушение закона о рекламе, и выброшенные деньги за клик.

Вопрос «нужен ли ИП или самозанятость» намеренно не отвечен: лицензионный
договор пока допускает только юрлиц и ИП. Ответ появится вместе с новой
редакцией договора — до неё рекламу на страницу не запускаем.
"""
from __future__ import annotations

from typing import Mapping
from urllib.parse import quote

from app.web.components.escaping import e
from app.web.components.icons import ICON_ARROW_RIGHT, ICON_CIRCLE_CHECK
from app.web.components.styles import get_base_styles

LANDING_SLUG = "dlya-masterov"
PRICE_RUB = 250
TRIAL_DAYS = 14

_IMG = "/static/images/landing/masters"


def cta_url(params: Mapping[str, str], logged_in: bool) -> str:
    """Куда ведёт кнопка. Метки рекламы едут дальше по ссылке — так
    подключение узнает, откуда человек пришёл, без cookie."""
    from app.services import ad_attribution

    labels = dict(ad_attribution.pick(params))
    labels.setdefault("landing", LANDING_SLUG)
    checkout = "/business/checkout?plan=lite&for=master&" + ad_attribution.query(labels)
    if logged_in:
        return checkout
    return f"/register?redirect={quote(checkout, safe='')}"


def _cta(href: str, label: str = f"Подключиться — {TRIAL_DAYS} дней бесплатно",
         short: str = "Попробовать бесплатно", note: bool = True) -> str:
    """Кнопка подключения.

    Две подписи: на экране уже 420px длинная переносилась на две строки, кнопка
    вырастала до 86px, а стрелка отрывалась от текста. Лишняя подпись скрыта
    через display:none — экранный диктор её тоже не читает.
    """
    note_html = (f'<p class="ml-cta-note">Дальше {PRICE_RUB} ₽ в месяц. Карта не нужна.</p>'
                 if note else "")
    return (f'<a class="ml-cta" href="{e(href)}">'
            f'<span class="ml-cta-long">{label}</span>'
            f'<span class="ml-cta-short">{short}</span>{ICON_ARROW_RIGHT}</a>{note_html}')


_PAINS = [
    ("Запись в переписке",
     "Ссылка и QR-код для записи. Клиент видит свободные окна и записывается сам — "
     "даже без регистрации."),
    ("Клиенты забывают о визите",
     "Вам — уведомление о каждой новой записи и отмене. Клиенту — напоминание "
     "перед визитом, если он подключил мессенджер или почту."),
    ("Путаница с окнами",
     "Расписание по вашим рабочим часам: занятое время закрывается само, "
     "двух клиентов на одно время не будет."),
]

_TOUR = [
    ("booking-link", "Клиент записывается сам по ссылке",
     "Ставите ссылку или QR-код в шапку соцсетей. Клиент выбирает услугу и "
     "свободное время — без звонков и переписки.", 780, 954),
    (None, "Напоминание перед визитом",
     "Приходит клиенту в Telegram, MAX, ВКонтакте или на почту — туда, где он "
     "подключил уведомления.", 0, 0),
    ("records", "Все записи — в одном списке",
     "Подтверждаете запись, отмечаете «Пришёл» или «Не пришёл». Удобно "
     "прямо с телефона.", 728, 1014),
    ("client-card", "Карточка клиента",
     "История визитов, сколько потратил и заметки. «Аллергия на акриловую "
     "пудру» больше не потеряется в переписке.", 780, 2044),
    ("overview", "Выручка и день на одном экране",
     "Сколько заработали за неделю и кто придёт сегодня.", 728, 1922),
]

_INCLUDED = [
    "Онлайн-запись по ссылке и QR-коду",
    "Расписание по вашим рабочим часам",
    "Карточки клиентов, история визитов и заметки",
    "Уведомления о новых записях и отменах",
    "Напоминания клиентам перед визитом",
    "Выручка и простая аналитика",
]

_STEPS = [
    ("Подключитесь", "Регистрация и подключение — пара минут."),
    ("Настройте запись", "Добавьте услуги, цены и рабочие часы. Мы проверим профиль и откроем запись."),
    ("Поставьте ссылку в соцсети", "Клиенты начнут записываться сами."),
]

_FAQ = [
    ("Клиенты останутся моими?",
     "Да. Контакты и история клиентов видны только вам — мы не передаём их "
     "другим мастерам и салонам."),
    (f"Что будет после {TRIAL_DAYS} дней?",
     f"Оплатите {PRICE_RUB} ₽ за месяц в кабинете, во вкладке «Тариф». Автоматических "
     "списаний нет. Не оплатили — через неделю запись по ссылке закроется, а все "
     "данные сохранятся, вернуться можно в любой момент."),
    ("Сколько времени занимает настройка?",
     "Обычно около 15 минут: услуги, цены и рабочие часы. После этого мы проверим "
     "профиль и откроем запись."),
    ("Можно пользоваться с телефона?",
     "Да. Кабинет работает в браузере телефона, приложение ставить не нужно."),
]


def _reminder_mock() -> str:
    """Иллюстрация, а не скриншот: так выглядит сообщение, которое уходит
    клиенту (текст из tasks.send_booking_reminder)."""
    return """
        <div class="ml-chat" role="img" aria-label="Пример напоминания клиенту в мессенджере">
            <div class="ml-chat-head"><span class="ml-chat-avatar">Р</span>Руми</div>
            <div class="ml-chat-bubble">⏰ Напоминаем: сегодня в 18:00 — Маникюр с покрытием в «Анна Смирнова — маникюр»<br>
                Адрес: Томск, пр. Ленина, 80</div>
            <p class="ml-chat-caption">Пример сообщения</p>
        </div>"""


def render_master_landing_page(params: Mapping[str, str], user=None) -> str:
    href = cta_url(params, logged_in=user is not None)

    pains = "".join(
        f'<div class="ml-card"><h3 class="ml-card-title">{e(title)}</h3>'
        f'<p class="ml-card-text">{e(text)}</p></div>'
        for title, text in _PAINS
    )

    tour_items = []
    for i, (img, title, text, w, h) in enumerate(_TOUR, start=1):
        if img:
            visual = (f'<img class="ml-shot" src="{_IMG}/{img}.webp" width="{w}" height="{h}" '
                      f'loading="lazy" decoding="async" alt="{e(title)} — скриншот кабинета Руми">')
        else:
            visual = _reminder_mock()
        tour_items.append(
            f'<li class="ml-tour-item"><div class="ml-tour-text">'
            f'<span class="ml-step-num">{i}</span><h3 class="ml-card-title">{e(title)}</h3>'
            f'<p class="ml-card-text">{e(text)}</p></div>'
            f'<div class="ml-tour-visual">{visual}</div></li>'
        )

    included = "".join(f'<li>{ICON_CIRCLE_CHECK}<span>{e(x)}</span></li>' for x in _INCLUDED)
    steps = "".join(
        f'<li class="ml-card"><span class="ml-step-num">{i}</span>'
        f'<h3 class="ml-card-title">{e(t)}</h3><p class="ml-card-text">{e(d)}</p></li>'
        for i, (t, d) in enumerate(_STEPS, start=1)
    )
    faq = "".join(
        f'<details class="ml-faq-item"><summary>{e(q)}</summary><p>{e(a)}</p></details>'
        for q, a in _FAQ
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Онлайн-запись для частных мастеров — Руми</title>
    <meta name="description" content="Руми ищет мастеров, которые работают на себя: запись по ссылке, расписание, напоминания клиентам. {TRIAL_DAYS} дней бесплатно, дальше {PRICE_RUB} ₽ в месяц.">
    <meta name="robots" content="noindex, nofollow">
    {get_base_styles()}
</head>
<body class="ml-body">
    <header class="ml-header">
        <div class="ml-container">
            <picture class="ml-logo">
                <source type="image/webp" srcset="/static/images/rumi-logo.webp">
                <img src="/static/images/rumi-logo.png" alt="Руми" width="480" height="312">
            </picture>
        </div>
    </header>

    <main>
        <section class="ml-hero">
            <div class="ml-container">
                <span class="ml-badge">Для частных мастеров</span>
                <h1 class="ml-title">Руми ищет мастеров, которые работают на себя</h1>
                <p class="ml-lead">Хватит вести запись в директе и заметках. Клиенты записываются сами
                    по ссылке, а у вас — расписание, напоминания и карточки клиентов.</p>
                {_cta(href)}
            </div>
        </section>

        <section class="ml-section">
            <div class="ml-container">
                <h2 class="ml-h2">Знакомо?</h2>
                <div class="ml-grid-3">{pains}</div>
            </div>
        </section>

        <section class="ml-section ml-section-alt">
            <div class="ml-container">
                <h2 class="ml-h2">Как это выглядит</h2>
                <p class="ml-sub">Настоящие экраны Руми на примере вымышленного мастера.</p>
                <ol class="ml-tour">{"".join(tour_items)}</ol>
                <div class="ml-mid-cta">{_cta(href)}</div>
            </div>
        </section>

        <section class="ml-section">
            <div class="ml-container ml-about">
                <h2 class="ml-h2">Кто мы</h2>
                <p class="ml-text">Руми — сервис онлайн-записи в салоны красоты и к частным мастерам.
                    Мы делаем его в Томске и отвечаем на вопросы сами, без колл-центра: пишите на
                    <a class="ml-link" href="mailto:hello@rrumi.ru">hello@rrumi.ru</a>.</p>
            </div>
        </section>

        <section class="ml-section ml-section-alt" id="price">
            <div class="ml-container">
                <h2 class="ml-h2">Сколько стоит</h2>
                <div class="ml-price">
                    <p class="ml-price-name">Тариф «Лайт» для частного мастера</p>
                    <p class="ml-price-amount">{PRICE_RUB} ₽ <span>в месяц</span></p>
                    <p class="ml-price-trial">Первые {TRIAL_DAYS} дней — бесплатно. Карта не нужна,
                        автоматических списаний нет.</p>
                    <ul class="ml-included">{included}</ul>
                    <p class="ml-price-note">Модели на отработку для пустых окон — пока только в Томске.</p>
                    <div class="ml-price-cta">{_cta(href, note=False)}</div>
                </div>
            </div>
        </section>

        <section class="ml-section">
            <div class="ml-container">
                <h2 class="ml-h2">Как подключиться</h2>
                <ol class="ml-grid-3 ml-steps">{steps}</ol>
            </div>
        </section>

        <section class="ml-section ml-section-alt">
            <div class="ml-container ml-faq">
                <h2 class="ml-h2">Частые вопросы</h2>
                {faq}
            </div>
        </section>

        <section class="ml-final">
            <div class="ml-container">
                <h2 class="ml-h2">Попробуйте {TRIAL_DAYS} дней бесплатно</h2>
                {_cta(href, label="Подключиться", short="Подключиться")}
            </div>
        </section>
    </main>

    <footer class="ml-footer">
        <div class="ml-container">
            <p>ООО «РУМИ» · ОГРН 1267000004370 · ИНН 7000036144</p>
            <p class="ml-footer-links">
                <a href="/license" target="_blank" rel="noopener">Лицензионный договор</a>
                <a href="/privacy" target="_blank" rel="noopener">Политика обработки персональных данных</a>
                <a href="/cookies" target="_blank" rel="noopener">Политика cookie</a>
            </p>
        </div>
    </footer>
</body>
</html>"""
