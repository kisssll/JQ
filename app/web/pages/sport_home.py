import json

from app.core.config import settings
from app.web.components import ui
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import ICON_ARROW_RIGHT, ICON_SEARCH
from app.web.components.styles import get_base_styles


_FEATURES = (
    (
        "Найдите свой клуб",
        "Ищите спортивные организации по названию и городу, "
        "а затем переходите на страницу клуба.",
    ),
    (
        "Выберите занятия",
        "Посмотрите направления, расписание и доступные абонементы "
        "в профиле организации.",
    ),
    (
        "Запишитесь онлайн",
        "Оставьте заявку на тренировку прямо на странице клуба.",
    ),
)

_STEPS = (
    ("Найдите", "Выберите клуб или секцию в каталоге."),
    ("Выберите", "Откройте страницу клуба и посмотрите занятия."),
    ("Запишитесь", "Отправьте заявку и дождитесь подтверждения клуба."),
)

_FAQ = (
    (
        "Как найти клуб?",
        'Откройте <a href="/sport/clubs">каталог клубов</a> и '
        "используйте поиск по названию или фильтр по городу.",
    ),
    (
        "Как записаться на тренировку?",
        "На странице клуба выберите занятие и отправьте заявку. "
        "Дальнейшие детали согласуйте с клубом.",
    ),
    (
        "Где посмотреть стоимость занятий?",
        'Условия абонементов публикуют сами клубы. Перейдите в раздел '
        '<a href="/sport/tariffs">тарифов</a> или откройте страницу организации.',
    ),
)


def _render_sport_home_schema() -> str:
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    page = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "@id": f"{base_url}/sport/#webpage",
        "url": f"{base_url}/sport/",
        "name": "Руми Спорт — клубы, тренировки и запись",
        "description": (
            "Найдите спортивный клуб, посмотрите расписание и абонементы, "
            "запишитесь на тренировку онлайн."
        ),
        "inLanguage": "ru-RU",
        "isPartOf": {"@id": f"{base_url}/#website"},
    }
    body = json.dumps(page, ensure_ascii=False, separators=(",", ":"))
    body = body.replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'


def render_sport_home_page(user=None) -> str:
    features = "".join(
        f"""<article class="sport-home__feature">
            <span class="sport-home__number">{index:02}</span>
            <h3>{title}</h3>
            <p>{text}</p>
        </article>"""
        for index, (title, text) in enumerate(_FEATURES, start=1)
    )
    steps = "".join(
        f"""<li class="sport-home__step">
            <span>{index:02}</span>
            <div><h3>{title}</h3><p>{text}</p></div>
        </li>"""
        for index, (title, text) in enumerate(_STEPS, start=1)
    )
    faq = "".join(
        f"<details><summary>{question}</summary><p>{answer}</p></details>"
        for question, answer in _FAQ
    )
    schema = _render_sport_home_schema()

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Руми Спорт — клубы, тренировки и запись</title>
    <meta name="description" content="Найдите спортивный клуб, посмотрите расписание и абонементы, запишитесь на тренировку онлайн.">
    {schema}
    {get_base_styles()}
</head>
<body class="sport-directory sport-home">
    {render_header("sport", user)}
    <main id="main" class="sport-home__main">
        <section class="sport-home__hero">
            <div class="section-container sport-home__hero-grid">
                <div class="sport-home__intro">
                    <p class="sport-home__eyebrow">Клубы и тренировки на Руми</p>
                    <h1 class="r-display sport-home__title">Найдите свой клуб.<br><em>Начните тренироваться.</em></h1>
                    <p class="r-text r-muted sport-home__lead">
                        Выберите спортивную организацию, изучите занятия и абонементы,
                        а затем отправьте заявку на тренировку.
                    </p>
                    <form class="catalog-search sport-home__search" action="/sport/clubs" method="get" role="search">
                        <span class="catalog-search__icon" aria-hidden="true">{ICON_SEARCH}</span>
                        <input type="search" name="q" class="search-input"
                               placeholder="Название клуба или направление"
                               aria-label="Поиск спортивного клуба" enterkeyhint="search">
                        {ui.button("Найти клуб", type_="submit", small=True)}
                    </form>
                    <div class="sport-home__actions">
                        {ui.button("Все клубы", href="/sport/clubs", icon=ICON_ARROW_RIGHT)}
                        <a class="sport-home__business-link" href="/sport/business">Для спортивных клубов</a>
                    </div>
                </div>
                <div class="sport-home__art" aria-hidden="true">
                    <span class="sport-home__art-label">РУМИ<br>СПОРТ</span>
                    <span class="sport-home__art-caption">Клубы · занятия · запись</span>
                </div>
            </div>
        </section>

        <section class="sport-home__features" id="how">
            <div class="section-container">
                <div class="sport-home__section-head">
                    <p class="sport-home__eyebrow">От поиска до тренировки</p>
                    <h2 class="r-title">Начать заниматься —<br><em>просто.</em></h2>
                </div>
                <div class="sport-home__feature-grid">{features}</div>
                <ol class="sport-home__steps">{steps}</ol>
            </div>
        </section>

        <section class="sport-home__for-clubs" id="for-clubs">
            <div class="section-container sport-home__clubs-layout">
                <div>
                    <p class="sport-home__eyebrow">Для владельцев и команд</p>
                    <h2 class="r-title">Расскажите о своём клубе<br>на <em>Руми Спорт.</em></h2>
                    <p>Подайте заявку на подключение. После проверки клуб сможет представить
                       направления, расписание и абонементы в каталоге.</p>
                </div>
                <div class="sport-home__clubs-actions">
                    {ui.button("Подключить клуб", href="/sport/business", icon=ICON_ARROW_RIGHT)}
                    <a href="/sport/tariffs">Посмотреть тарифы клубов</a>
                </div>
            </div>
        </section>

        <section class="sport-home__faq">
            <div class="section-container sport-home__faq-layout">
                <div class="sport-home__section-head">
                    <p class="sport-home__eyebrow">Подскажем с чего начать</p>
                    <h2 class="r-title">Частые<br><em>вопросы.</em></h2>
                </div>
                <div class="sport-home__faq-list">{faq}</div>
            </div>
        </section>
    </main>
    {render_footer(user, sport=True)}
</body>
</html>"""
