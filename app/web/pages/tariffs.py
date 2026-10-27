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
from app.web.components.escaping import e
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_ARROW_RIGHT,
    ICON_CHEVRON_DOWN,
    ICON_CIRCLE_CHECK,
    ICON_FILE_TEXT,
)
from app.web.components.guide_diagrams import BOOKING_FLOW, SALON_FLOW
from app.web.components.tbank import render_tbank_partner_strip
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
        '«Инструкция» бизнес-панели). Заявку проверит модератор платформы. После '
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
    """Единая карточка тарифа. Выделенная (её .plan.hot) залита ягодным — как у
    дизайнера; выделение одно на блок, и ставит его только код тарифов
    (``popular`` в tariff_presentation), не вёрстка."""
    features_html = "".join(
        f'<li>{ICON_CIRCLE_CHECK}<span>{f}</span></li>' for f in plan["features"]
    )
    popular = plan.get("popular")
    badge = '<span class="plan-badge">Популярный</span>' if popular else ""
    return f"""
    <article class="plan-card{' is-popular' if popular else ''}">
        <header class="plan-header">
            <div class="plan-name-row">
                <h3 class="plan-name">{e(plan['name'])}</h3>
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
                <span class="doc-card-title">{e(d['title'])}</span>
                <span class="doc-card-desc">{e(d['description'])}</span>
                <span class="doc-card-date">Редакция от {e(d.get('version_human', LEGAL_VERSION_HUMAN))}</span>
            </span>
            <span class="doc-card-arrow">{ICON_ARROW_RIGHT}</span>
        </a>""" for d in DOCUMENTS.values())
    return f"""
        <p class="tariffs-group-hint">Шесть документов сервиса: у каждого указана действующая редакция.</p>
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


#: Вкладки страницы: ключ в адресе (?tab=) и подпись. Без JS вкладка выбирается
#: ссылкой и рисуется сервером, поэтому раздел можно открыть и отправить по адресу.
TABS = {"plans": "Тарифы", "documents": "Документы", "guides": "Инструкции"}


def render_tariffs_page(user=None, tab: str = "plans") -> str:
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

    active = tab if tab in TABS else "plans"

    def tab_link(key: str) -> str:
        on = key == active
        href = "/tariffs" if key == "plans" else f"/tariffs?tab={key}"
        return (f'<a class="tariffs-tab{" active" if on else ""}" role="tab" '
                f'id="tabbtn-{key}" aria-controls="tab-{key}" '
                f'aria-selected="{"true" if on else "false"}" '
                f'data-tab="{key}" href="{href}">{TABS[key]}</a>')

    def pane(key: str, body: str) -> str:
        return (f'<div id="tab-{key}" class="tab-content{" active" if key == active else ""}" '
                f'role="tabpanel" aria-labelledby="tabbtn-{key}">{body}</div>')

    plans_body = f"""
                    <h2 class="tariffs-group-title">Для владельцев салонов</h2>
                    <p class="tariffs-group-hint">Тариф подстраивается под число мастеров при каждой следующей оплате. Первые 14 дней — бесплатно.</p>
                    <div class="plans-grid cols-4">{business_cards}</div>

                    <h2 class="tariffs-group-title">Для моделей</h2>
                    <p class="tariffs-group-hint">Подписка модели даёт доступ к записям на отработку техник со скидкой.</p>
                    <div class="plans-grid cols-3">{model_cards}</div>"""
    guides_body = f"""
                    {BOOKING_FLOW}
                    {SALON_FLOW}
                    <div class="settings-accordion">{_accordion_html(_SITE_INSTRUCTIONS)}</div>"""

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
    {render_header("tariffs", user)}

    <main class="main-content">
        <section class="tariffs-hero">
            <div class="section-container">
                <h1 class="tariffs-title">Тарифы <em>и информация</em></h1>
                <p class="tariffs-lead">Все тарифы платформы, документы и подсказки по работе с сайтом — в одном месте.</p>
            </div>
        </section>

        <section class="tariffs-body">
            <div class="section-container">
                <div class="tariffs-tabs" id="tariffsTabs" role="tablist" aria-label="Разделы страницы">
                    {tab_link("plans")}{tab_link("documents")}{tab_link("guides")}
                </div>

                {pane("plans", plans_body)}
                {pane("documents", _documents_html())}
                {pane("guides", guides_body)}

                {render_tbank_partner_strip()}
            </div>
        </section>

        {render_footer(user, "business")}
    </main>
</body>
</html>"""
