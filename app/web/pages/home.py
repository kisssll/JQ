# app/web/pages/home.py
"""Главная: вход в каталог (решение 0011, п. 12; композиция: решение 0014).

Порядок экранов: заголовок с поиском и аркой, сразу под ним ЖИВЫЕ карточки
салонов, ниже «как записаться», приглашение стать моделью, партнёрский блок
Т‑Банка и блок для бизнеса. Расположение блоков, ритм и подача поиска взяты из
макета дизайнера; данные и ограничения наши.

Карточки: ТОТ ЖЕ компонент, что в каталоге (``salons.render_cards``), с тем же
порядком (победители конкурса → платные → рейтинг). Второй похожий список на
главной через месяц разошёлся бы с каталогом и по виду, и по подъёму.

Сколько карточек: шесть и ссылка «смотреть все». Салонов на проде девять,
сетка на тридцать мест с четырьмя заполненными выглядела бы сломанной, а шесть
карточек в поток честны и при девяти салонах, и при девятистах.

Арка в первом экране занята знаком Руми, а не снимком: фотографий у нас почти
нет, а заглушка вместо снимка (градиент, пунктирная рамка, как в макете):
запрещённая бриф-ом декорация.

Тексты сведены из трёх источников (решение 0014, «Долг»): строка бренда и
заголовки блоков от Дианы/дизайнера; пункты, которые нельзя проверить по коду
(«в один клик», «за 15 минут»), заменены проверяемыми.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.web.components import ui
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.structured_data import render_site_schema
from app.web.components.icons import ICON_SEARCH, ICON_ARROW_RIGHT
from app.web.components.tbank import render_tbank_partner_banner

#: Сколько карточек показываем на главной.
HOME_CARDS = 6

#: Как записаться. Нумерация здесь оправдана: последовательность и есть смысл
#: блока. Формулировки из макета; «напоминание придёт само» проверено:
#: напоминания о записи шлёт крон (app/tasks.py).
_STEPS = [
    ("Салон", "Выберите подходящий салон с нужным мастером."),
    ("Услуга", "Выберите, что нужно сделать."),
    ("Время", "Возьмите свободное окно."),
    ("Готово", "Приходите. Напоминание придёт само."),
]

#: Что даёт подписка модели. Скидка «до 100%»: решение владельца (0011, п. 15),
#: не усиливаем и не показываем крупной цифрой, как в макете. Цену назначает
#: мастер, окна и фото часть того же сценария. Обещаний объёма клиентов и
#: выручки здесь нет и быть не может (ч. 7 ст. 5 «О рекламе»).
_MODEL_POINTS = [
    "Услуги мастеров со скидкой до 100%. Цену назначает сам мастер",
    "Новые процедуры и техники раньше остальных",
    "Фотографии работы после визита",
]

#: Что внутри панели. Каждая строка есть в панели салона: расписание, клиенты
#: (CRM), касса и отчёты, аналитика со складом и расчётом материалов.
_BUSINESS_TILES = [
    ("Расписание", "Записи мастеров в одном окне."),
    ("Клиенты", "История, заметки, повторные визиты."),
    ("Оплата", "Касса и отчёты внутри."),
    ("Аналитика", "Загрузка, выручка, расчёт материалов."),
]


async def render_home_page(db: AsyncSession, user=None) -> str:
    """Главная страница Руми."""
    # Карточки берём той же функцией, что каталог: один компонент, один порядок,
    # одна цена в запросах (выборка + содержимое карточек).
    try:
        from app.web.pages.salons import SalonQuery, render_cards
        cards, _has_more = await render_cards(db, SalonQuery(limit=HOME_CARDS))
    except Exception as exc:
        # имя exc, а не e: e это экранировщик HTML в остальных модулях страниц
        print(f"Ошибка загрузки салонов: {exc}")
        cards = ""

    if cards:
        catalog_block = f"""
                {ui.section_head(
                    "Лучшие салоны нашей платформы",
                    link_label="Смотреть все салоны", link_href="/salons")}
                <div class="salons-grid">{cards}</div>"""
    else:
        # Пусто бывает не только «пока»: так же выглядит страница, если упала
        # выборка. Поэтому приглашение, а не сообщение об отсутствии данных.
        catalog_block = ui.empty_state(
            "Здесь появятся мастера и салоны",
            text="Пока никого нет рядом. Если вы мастер, заведите страницу, "
                 "и вас начнут находить.",
            action_label="Подключиться", action_href="/business",
        )

    steps_html = "".join(
        f'<li class="home-step"><div><b class="home-step__name">{title}</b>'
        f'<p class="home-step__text">{text}</p></div></li>'
        for title, text in _STEPS
    )

    model_points = "".join(f"<li>{point}</li>" for point in _MODEL_POINTS)
    business_tiles = "".join(
        f'<div class="home-tile"><b>{title}</b><p>{text}</p></div>'
        for title, text in _BUSINESS_TILES
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Руми: мастера и салоны красоты рядом</title>
    <meta name="description" content="Руми: онлайн-запись в салоны красоты и к частным мастерам без звонков. Найдите мастера рядом, выберите время и получите напоминание.">
    {render_site_schema()}
    {get_base_styles()}
</head>
<body>
    {render_header("home", user)}

    <main class="home-main">
        <section class="home-hero">
            <div class="section-container home-hero__grid">
                <div class="home-hero__copy">
                    <p class="home-kicker">Мастера и салоны в одном приложении</p>
                    <h1 class="r-display home-hero__title">РУМИ. Твой доступ <em>к красоте</em></h1>
                    <p class="r-text r-muted home-hero__text">Подберём салон и услуги для вас.
                        Без лишних забот.</p>
                    <form class="home-search" action="/salons" method="get" role="search">
                        <span class="home-search__icon" aria-hidden="true">{ICON_SEARCH}</span>
                        <input type="search" name="q" class="home-search__input"
                               placeholder="Маникюр, стрижка, имя мастера"
                               aria-label="Что нужно сделать" enterkeyhint="search">
                        {ui.button("Найти", type_="submit")}
                    </form>
                    <p class="home-hero__micro">Четыре шага · без звонков</p>
                </div>
                <div class="home-hero__art r-arch" aria-hidden="true"></div>
            </div>
        </section>

        <section class="home-catalog">
            <div class="section-container">{catalog_block}</div>
        </section>

        <section class="home-how">
            <div class="section-container">
                <div class="home-how__card">
                    {ui.section_head("Как записаться", text="Подберём салон и услуги для вас. "
                                                           "Без лишних забот.")}
                    <ol class="home-steps">{steps_html}</ol>
                </div>
            </div>
        </section>

        <section class="home-model" id="become-model">
            <div class="section-container">
                <div class="home-feature home-feature--model">
                    <div>
                        <p class="home-kicker home-kicker--light">Для прекрасных и смелых, как ты!</p>
                        <h2 class="r-title">Стань моделью не через агентство, а <em>по подписке</em>.</h2>
                        <p class="home-feature__text">Найдите предложение от мастеров, которое
                            придется по душе.</p>
                        {ui.button("Оформить подписку", href="/model", icon=ICON_ARROW_RIGHT)}
                    </div>
                    <ul class="home-model__list">{model_points}</ul>
                </div>
            </div>
        </section>

        <p class="home-tbank-note">А также мы являемся официальными партнёрами Т‑Банка.</p>
        {render_tbank_partner_banner()}

        <section class="home-business" id="for-business">
            <div class="section-container">
                <div class="home-feature home-feature--biz">
                    <div>
                        <p class="home-kicker">Для бизнеса</p>
                        <h2 class="r-title">Управлять салоном с нами <em>проще</em>.</h2>
                        <p class="home-feature__text">Одно окно и всё под рукой. Первые 14 дней
                            бесплатно.</p>
                        {ui.button("Подробнее", href="/business", icon=ICON_ARROW_RIGHT)}
                    </div>
                    <div class="home-tiles">{business_tiles}</div>
                </div>
            </div>
        </section>

        {render_footer(user)}
    </main>
</body>
</html>"""
