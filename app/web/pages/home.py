# app/web/pages/home.py
"""Главная — вход в каталог (решение 0011, п. 12).

Порядок экранов: крупный поиск, сразу под ним ЖИВЫЕ карточки салонов, ниже
«как записаться», в конце приглашение стать моделью. Партнёрский блок Т‑Банка и
блок для бизнеса стоят после клиентской части: они адресованы не клиенту, и у
бизнесового мира свой заход.

Карточки — ТОТ ЖЕ компонент, что в каталоге (``salons.render_cards``), с тем же
порядком (победители конкурса → платные → рейтинг). Второй похожий список на
главной через месяц разошёлся бы с каталогом и по виду, и по подъёму.

Сколько карточек: шесть и ссылка «смотреть все». Салонов на проде девять —
сетка на тридцать мест с четырьмя заполненными выглядела бы сломанной, а шесть
карточек в поток по 300px честны и при девяти салонах, и при девятистах.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.components import ui
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.structured_data import render_site_schema
from app.web.components.icons import ICON_SEARCH, ICON_ARROW_RIGHT
from app.web.components.tbank import render_tbank_partner_banner

#: Сколько карточек показываем на главной.
HOME_CARDS = 6

#: Как записаться. Нумерация здесь оправдана: последовательность и есть смысл
#: блока. Это список шагов, а не четыре одинаковые карточки «иконка + заголовок
#: + текст» — такой структуры страницы мы не делаем (docs/design.md).
_STEPS = [
    ("Мастер", "Выберите мастера или салон — цены и свободные окна видны в списке."),
    ("Услуга", "Отметьте, что нужно сделать."),
    ("Время", "Возьмите свободное окно."),
    ("Готово", "Приходите. Заявку подтвердят."),
]

#: Что даёт подписка модели. Утверждения проверяемые: скидка задаётся салоном в
#: услуге для отработки, окна и фото — часть того же сценария. Обещаний объёма
#: клиентов и выручки здесь нет и быть не может (ч. 7 ст. 5 «О рекламе»).
_MODEL_POINTS = [
    "Услуги мастеров со скидкой — цену назначает сам мастер",
    "Новые процедуры и техники раньше остальных",
    "Фотографии работы после визита",
]


async def render_home_page(db: AsyncSession, user=None) -> str:
    """Главная страница Руми."""
    # Карточки берём той же функцией, что каталог: один компонент, один порядок,
    # одна цена в запросах (выборка + содержимое карточек).
    try:
        from app.web.pages.salons import SalonQuery, render_cards
        cards, _has_more = await render_cards(db, SalonQuery(limit=HOME_CARDS))
    except Exception as exc:
        # имя exc, а не e: e — экранировщик HTML в остальных модулях страниц
        print(f"Ошибка загрузки салонов: {exc}")
        cards = ""

    if cards:
        catalog_block = f"""
                {ui.section_head(
                    "Кто принимает сейчас",
                    text="Цены и ближайшие свободные окна — сразу в карточке.",
                    link_label="Смотреть все", link_href="/salons")}
                <div class="salons-grid">{cards}</div>"""
    else:
        # Пусто бывает не только «пока»: так же выглядит страница, если упала
        # выборка. Поэтому приглашение, а не сообщение об отсутствии данных.
        catalog_block = ui.empty_state(
            "Здесь появятся мастера и салоны",
            text="Пока никого нет рядом. Если вы мастер — заведите страницу, "
                 "и вас начнут находить.",
            action_label="Подключиться", action_href="/business",
        )

    steps_html = "".join(
        f'<li class="home-step"><h3 class="home-step__name">{title}</h3>'
        f'<p class="home-step__text">{text}</p></li>'
        for title, text in _STEPS
    )

    model_points = "".join(f"<li>{point}</li>" for point in _MODEL_POINTS)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Руми — мастера и салоны красоты рядом</title>
    <meta name="description" content="Руми — онлайн-запись в салоны красоты и к частным мастерам без звонков. Найдите мастера рядом, выберите время и получите напоминание.">
    {render_site_schema()}
    {get_base_styles()}
</head>
<body>
    {render_header("home")}
    {render_sidebar("home", user)}

    <main class="home-main">
        <section class="home-hero">
            <div class="section-container">
                <h1 class="r-display home-hero__title">Запись к мастеру<br>без звонков</h1>
                <p class="r-text r-muted home-hero__text">Услуги, цены и свободные окна
                    видно сразу — выберите время и приходите.</p>
                <form class="home-search" action="/salons" method="get" role="search">
                    <span class="home-search__icon" aria-hidden="true">{ICON_SEARCH}</span>
                    <input type="search" name="q" class="home-search__input"
                           placeholder="Маникюр, стрижка, имя мастера"
                           aria-label="Что нужно сделать" enterkeyhint="search">
                    {ui.button("Найти", type_="submit")}
                </form>
            </div>
        </section>

        <section class="home-catalog">
            <div class="section-container">{catalog_block}</div>
        </section>

        <section class="home-how">
            <div class="section-container">
                {ui.section_head("Как записаться")}
                <ol class="home-steps">{steps_html}</ol>
            </div>
        </section>

        <section class="home-model" id="become-model">
            <div class="section-container">
                <div class="home-model__grid">
                    <div>
                        {ui.section_head("Стать моделью",
                                         text="Мастерам нужна практика, вам — работа мастера "
                                              "дешевле. Подписка открывает такие записи.")}
                        {ui.button("Оформить подписку", href="/model", icon=ICON_ARROW_RIGHT)}
                    </div>
                    <ul class="home-model__list">{model_points}</ul>
                </div>
            </div>
        </section>

        {render_tbank_partner_banner()}

        <section class="home-business" id="for-business">
            <div class="section-container">
                {ui.section_head("Веду записи сам",
                                 text="Расписание, клиенты, оплата и аналитика — в одном окне. "
                                      "Первые 14 дней бесплатно.")}
                {ui.button("Подробнее", kind="secondary", href="/business",
                           icon=ICON_ARROW_RIGHT)}
            </div>
        </section>

        {render_footer(user)}
    </main>
</body>
</html>"""
