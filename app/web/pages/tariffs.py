# app/web/pages/tariffs.py
"""«Тарифы и информация» — единая страница: все платные тарифы платформы
(салоны + модели), документы и краткие инструкции по сайту. Три под-вкладки
переключаются на клиенте без перезагрузки (см. static/src/js/tariffs.js).

Тарифы салонов берём из business_checkout.TARIFFS (единственный источник
витринных текстов для бизнеса) — суммы для оплаты по-прежнему считает
app.services.tariffs (не трогаем). Тарифы моделей здесь свои (витринных
текстов моделей отдельным словарём в проекте не было, только внутри
model_landing.py) — цены синхронны с app.services.tariffs.MODEL_TARIFF_CATALOG.
"""
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_CIRCLE_CHECK, ICON_ARROW_RIGHT, ICON_CHEVRON_DOWN
from app.web.pages.business_checkout import TARIFFS as BUSINESS_TARIFFS

MODEL_TARIFFS = {
    "start": {
        "name": "Старт", "description": "Для тех, кто хочет попробовать",
        "price": "490 ₽", "period": "/мес",
        "features": [
            "До 3 записей в месяц", "Скидка 30% на услуги мастеров",
            "Доступ к начинающим мастерам", "Базовое портфолио",
        ],
    },
    "pro": {
        "name": "Про", "description": "Самый популярный выбор", "popular": True,
        "price": "990 ₽", "period": "/мес",
        "features": [
            "До 8 записей в месяц", "Скидка 50% на все услуги",
            "Приоритетная запись", "Доступ к топ-мастерам",
            "Расширенное портфолио", "Эксклюзивные процедуры",
        ],
    },
    "premium": {
        "name": "Премиум", "description": "Максимум возможностей",
        "price": "1 990 ₽", "period": "/мес",
        "features": [
            "Безлимитные записи", "Скидка до 70% на услуги",
            "VIP приоритет на запись", "Доступ ко всем мастерам",
            "Персональный менеджер", "Фотосессии для портфолио",
            "Ранний доступ к новым салонам",
        ],
    },
}

# Документы платформы — тексты/страницы появятся отдельно, здесь пока только
# список с описанием, о чём каждый документ.
_DOCUMENTS = [
    ("Политика конфиденциальности", "Как мы обрабатываем и храним ваши персональные данные."),
    ("Условия использования (публичная оферта)", "Правила пользования платформой для клиентов и бизнеса."),
    ("Согласие на обработку персональных данных", "Что именно вы подтверждаете при регистрации и записи."),
    ("Политика использования cookie", "Зачем сайту cookie и как их отключить в браузере."),
]

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
    features_html = "".join(f'<li>{ICON_CIRCLE_CHECK}<span>{f}</span></li>' for f in plan["features"])
    popular_badge = '<div class="popular-badge">Популярный</div>' if plan.get("popular") else ""
    popular_class = " popular" if plan.get("popular") else ""
    return f"""
    <div class="plan-card{popular_class}">
        {popular_badge}
        <div class="plan-header">
            <h3 class="plan-name">{plan['name']}</h3>
            <p class="plan-desc">{plan['description']}</p>
        </div>
        <div class="plan-price">
            <span class="amount">{plan['price']}</span>
            <span class="period">{plan['period']}</span>
        </div>
        <ul class="plan-features">{features_html}</ul>
        <a href="{cta_href}" class="plan-btn">{cta_label} {ICON_ARROW_RIGHT}</a>
    </div>"""


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
            "Обсудить условия" if key == "custom" else "Подключить салон",
        )
        for key, t in BUSINESS_TARIFFS.items()
    )
    model_cards = "".join(
        _plan_card_html(t, "/model/join", "Оформить подписку")
        for t in MODEL_TARIFFS.values()
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
                    <div class="plans-grid">{business_cards}</div>

                    <h2 class="tariffs-group-title">Для моделей</h2>
                    <div class="plans-grid">{model_cards}</div>
                </div>

                <div id="tab-documents" class="tab-content">
                    <div class="settings-accordion">{_accordion_html(_DOCUMENTS)}</div>
                </div>

                <div id="tab-guides" class="tab-content">
                    <div class="settings-accordion">{_accordion_html(_SITE_INSTRUCTIONS)}</div>
                </div>
            </div>
        </section>

        {render_footer(user)}
    </main>
</body>
</html>"""
