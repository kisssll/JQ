# app/web/pages/tariffs.py
"""«Тарифы и информация» — единая страница: все платные тарифы платформы
(салоны + модели), документы и краткие инструкции по сайту. Три под-вкладки
переключаются на клиенте без перезагрузки (см. static/src/js/tariffs.js).

Витринные тексты и цены тарифов — из app.web.tariff_presentation, который
считает суммы из тех же каталогов, что и биллинг: раньше цены на этой странице
лежали отдельным словарём строками и могли разойтись с тем, что спишут.
Список документов берём из app.web.pages.legal.DOCUMENTS — тоже раньше был
скопирован сюда руками, с другими названиями и с четвёртым документом
(«Политика использования cookie»), которого не существует: cookie описаны
внутри Политики.
"""
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_ARROW_RIGHT,
    ICON_CHEVRON_DOWN,
    ICON_CIRCLE_CHECK,
    ICON_FILE_TEXT,
)
from app.web.components.guide_diagrams import BOOKING_FLOW, SALON_FLOW
from app.web.pages.legal import DOCUMENTS, LEGAL_VERSION_HUMAN
from app.web.tariff_presentation import all_model_plans, all_plans

_SITE_INSTRUCTIONS = [
    (
        "Как записаться на процедуру",
        'Откройте раздел «<a class="text-link" href="/salons">Салоны</a>», выберите салон, мастера и услугу, затем '
        'удобное время. На последнем шаге нажмите «Записаться» — запись появится у вас в '
        '«<a class="text-link" href="/bookings">Мои записи</a>».',
    ),
    (
        "Как подать заявку на создание салона",
        'В боковом меню нажмите «<a class="text-link" href="/business">Для бизнеса</a>» → «Добавить салон» и заполните '
        'название, адрес и контакты. Сразу после отправки откроется бизнес-панель — можно сразу '
        'начать заполнять информацию о салоне (подробности по каждому разделу — во вкладке '
        '«Инструкция» бизнес-панели). Заявку проверит модератор, обычно 1–2 рабочих дня. После '
        'одобрения выберите тариф (первые 14 дней бесплатно) и опубликуйте салон.',
    ),
    (
        "Как стать моделью",
        'В боковом меню нажмите «<a class="text-link" href="/model">Стать моделью</a>», заполните анкету (фото, город, '
        'о себе) и выберите тариф — первые 14 дней бесплатно. После этого вы сможете сами смотреть '
        'и откликаться на предложения мастеров, которые ищут модели для отработки, а также '
        'принимать или отклонять приглашения, которые пришлют вам салоны.',
    ),
    (
        "Как оставить отзыв о салоне",
        'Отзыв можно оставить только после завершённой записи. Откройте «<a class="text-link" href="/bookings">Мои '
        'записи</a>» → вкладку «Завершённые», найдите запись и нажмите «Оставить отзыв» — поставьте '
        'оценку, напишите комментарий и при желании добавьте до 5 фото.',
    ),
    (
        "Как отменить запись",
        'Откройте «<a class="text-link" href="/bookings">Мои записи</a>» → вкладку «Предстоящие», найдите запись и '
        'нажмите «Отменить». Перенести время записи нельзя — если нужно на другое время, отмените '
        'текущую запись и запишитесь заново.',
    ),
]


def _plan_card_html(plan: dict, cta_href: str, cta_label: str) -> str:
    """Единая карточка тарифа. Раньше блоки салонов и моделей рисовались одним
    шаблоном, но выглядели по-разному: у моделей средний план заливался
    сплошным розовым, у салонов выделенного не было вовсе. Теперь выделение
    одно на всю страницу — рамка и бейдж, без заливки."""
    features_html = "".join(
        f'<li>{ICON_CIRCLE_CHECK}<span>{f}</span></li>' for f in plan["features"]
    )
    popular = plan.get("popular")
    badge = '<span class="plan-badge">Популярный</span>' if popular else ""
    return f"""
    <article class="plan-card{' is-popular' if popular else ''}">
        <header class="plan-header">
            <div class="plan-name-row">
                <h3 class="plan-name">{plan['name']}</h3>
                {badge}
            </div>
            <p class="plan-desc">{plan.get('size') or plan.get('description', '')}</p>
        </header>
        <p class="plan-price">
            <span class="amount">{plan['price']}</span>
            <span class="period">{plan['period']}</span>
        </p>
        <ul class="plan-features">{features_html}</ul>
        <a href="{cta_href}" class="plan-btn">{cta_label} {ICON_ARROW_RIGHT}</a>
    </article>"""


def _documents_html() -> str:
    """Карточки-ссылки на сами документы. Раньше это был аккордеон, который
    раскрывался в одну строку описания и никуда не вёл: вкладка «Документы»
    документов не давала."""
    cards = "".join(f"""
        <a class="doc-card" href="/{d['slug']}">
            <span class="doc-card-icon">{ICON_FILE_TEXT}</span>
            <span class="doc-card-text">
                <span class="doc-card-title">{d['title']}</span>
                <span class="doc-card-desc">{d['description']}</span>
            </span>
            <span class="doc-card-arrow">{ICON_ARROW_RIGHT}</span>
        </a>""" for d in DOCUMENTS.values())
    return f"""
        <p class="tariffs-group-hint">Действующая редакция от {LEGAL_VERSION_HUMAN}.
        Использование cookie описано в Политике обработки персональных данных.</p>
        <div class="doc-list">{cards}</div>"""


def _accordion_html(items: list[tuple[str, str]]) -> str:
    return "".join(f"""
        <div class="accordion-item">
            <button class="accordion-header">
                <span class="accordion-label">{title}</span>
                <span class="accordion-chevron">{ICON_CHEVRON_DOWN}</span>
            </button>
            <div class="accordion-body"><p>{text}</p></div>
        </div>""" for title, text in items)


def render_tariffs_page(user=None) -> str:
    business_cards = "".join(
        _plan_card_html(
            t, "/business/register-salon",
            "Обсудить условия" if t["plan"] == "custom" else "Подключить салон",
        )
        for t in all_plans()
    )
    model_cards = "".join(
        _plan_card_html(t, "/model/join", "Оформить подписку")
        for t in all_model_plans()
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Тарифы и информация — руми</title>
    <meta name="description" content="Все тарифы платформы, документы и инструкции по использованию сайта.">
    {get_base_styles()}
</head>
<body class="tariffs-page">
    {render_header("tariffs")}
    {render_sidebar("tariffs", user)}

    <main class="main-content">
        <section class="section-py bg-surface-alt">
            <div class="section-container">
                <h1 class="text-display">Тарифы и информация</h1>
                <p class="text-body-lg">Все тарифы платформы, документы и подсказки по работе с сайтом — в одном месте.</p>
            </div>
        </section>

        <section class="section-py">
            <div class="section-container">
                <div class="tariffs-tabs" id="tariffsTabs">
                    <button class="tab-btn active" data-tab="plans">Тарифы</button>
                    <button class="tab-btn" data-tab="documents">Документы</button>
                    <button class="tab-btn" data-tab="guides">Инструкции</button>
                </div>

                <div id="tab-plans" class="tab-content active">
                    <h2 class="tariffs-group-title">Для владельцев салонов</h2>
                    <p class="tariffs-group-hint">Тариф подстраивается под число мастеров при каждой следующей оплате. Первые 14 дней — бесплатно.</p>
                    <div class="plans-grid cols-4">{business_cards}</div>

                    <h2 class="tariffs-group-title">Для моделей</h2>
                    <p class="tariffs-group-hint">Подписка модели даёт доступ к записям на отработку техник со скидкой.</p>
                    <div class="plans-grid cols-3">{model_cards}</div>
                </div>

                <div id="tab-documents" class="tab-content">
                    {_documents_html()}
                </div>

                <div id="tab-guides" class="tab-content">
                    {BOOKING_FLOW}
                    {SALON_FLOW}
                    <div class="settings-accordion">{_accordion_html(_SITE_INSTRUCTIONS)}</div>
                </div>
            </div>
        </section>

        {render_footer(user)}
    </main>
</body>
</html>"""
