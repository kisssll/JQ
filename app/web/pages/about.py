# app/web/pages/about.py
from app.web.components import ui
from app.web.components.escaping import e
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.tbank import render_tbank_products_block
from app.web.components.icons import ICON_CIRCLE_CHECK
from app.web.pages.business.tbank_partner import TBANK_CONDITION_LINKS

# Новость о партнёрстве с Т-Банком — полная версия текста (см. также короткие
# версии на отдельных страницах app/web/pages/business/tbank_partner.py).
_TBANK_NEWS_INTRO = (
    "Мы стали партнёрами Т-Банка — экосистемы банковских продуктов для предпринимателей "
    "и компаний. Поможем зарегистрировать ИП или ООО, открыть расчётный счёт, подключить "
    "приём платежей и использовать другие инструменты для решения бизнес-задач."
)

_TBANK_NEWS_PRODUCTS = [
    "Регистрация ИП или ООО с одним учредителем — без уплаты госпошлины и скрытых "
    "платежей, без посещения налоговой. Можно получить консультацию по выбору кодов "
    "ОКВЭД и системы налогообложения.",

    "Расчётный счёт в Т-Банке для ИП и компаний — чтобы принимать и отправлять платежи "
    "и рассчитываться с контрагентами. Открытие бесплатно за один день, без поездок в "
    "банк и очередей. Обслуживание первые 2 месяца бесплатно с любым тарифом, после — "
    "от 490 ₽ в месяц; можно оплатить тариф на год по цене десяти месяцев и сэкономить "
    "ещё два месяца обслуживания.",

    "Зарплатный проект и выплаты самозанятым — для расчётов с сотрудниками.",
    "Торговый эквайринг — для приёма безналичных платежей в точках продаж.",
    "Интернет-эквайринг — для приёма онлайн-платежей от покупателей на сайте, в "
    "приложении или по ссылке в мессенджере.",
    "Счета в иностранной валюте — чтобы получать деньги от контрагентов из-за рубежа "
    "и оплачивать поставки.",
    "Кредиты для бизнеса — чтобы пополнить оборотные средства, вложиться в развитие "
    "бизнеса, закрыть кассовый разрыв.",
    "Кредитование покупателей и сервис «Долями» — чтобы повысить средний чек и "
    "количество продаж: товары и услуги смогут купить клиенты, у которых нет сразу "
    "всей суммы.",
    "Сервис аналитики продаж на маркетплейсах «Селлер» — чтобы анализировать продажи "
    "и управлять товарами на Ozon и Wildberries.",
    "Брокерский счёт для юридических лиц — чтобы увеличить доход от размещения "
    "свободных денег и сократить расходы на обмен валюты.",
]

_TBANK_NEWS_TOOLS = [
    "Бесплатная онлайн-бухгалтерия для ИП на УСН «Доходы» и бизнеса на АУСН — для "
    "сдачи деклараций, расчёта и уплаты налогов и взносов",
    "Бухгалтерское обслуживание — для ведения всей бухгалтерии на аутсорсе",
    "Банковские гарантии, спецсчёт, поисковик тендеров и другие продукты — для "
    "участия в госзакупках по 44-ФЗ и 223-ФЗ",
    "Бесплатные сервисы «Репутация» и по проверке контрагентов — для безопасной "
    "работы в соответствии со 115-ФЗ",
    "Бесплатный конструктор сайтов, чтобы создать и запустить сайт самостоятельно "
    "за пару часов",
    "Овернайт, депозиты и бизнес-копилка, чтобы заработать на свободных деньгах или "
    "накопить на бизнес-цели",
]

_TBANK_NEWS_TRUST = (
    "Т-Банк — надёжный банк для бизнеса. Центробанк включил Т-Банк в список 13 "
    "системно значимых банков. В экосистеме Т-Банка свыше 40 млн клиентов, из них "
    "более 1 млн — предприниматели и компании."
)

_TBANK_NEWS_CONDITIONS = ["rko_promo", "rko_tariffs", "registration_conditions", "registration_promo"]


def _render_tbank_news() -> str:
    products_html = "".join(
        f'<li class="tb-bullet">{ICON_CIRCLE_CHECK}<span>{p}</span></li>'
        for p in _TBANK_NEWS_PRODUCTS
    )
    tools_html = "".join(f"<li>{t}</li>" for t in _TBANK_NEWS_TOOLS)
    conditions_html = "".join(
        f'<li><a class="tb-condition-link" href="{url}" target="_blank" rel="noopener noreferrer">{label}</a></li>'
        for label, url in (TBANK_CONDITION_LINKS[key] for key in _TBANK_NEWS_CONDITIONS)
    )

    return f"""
        <section class="news-tbank">
            <div class="section-container">
                <div class="card news-tbank-card">
                    <span class="tb-badge"><span class="tb-badge-letter">Т</span> Новость · Партнёрство с Т-Банком</span>
                    <h2>Мы стали партнёрами Т-Банка</h2>
                    <p class="tb-intro">{_TBANK_NEWS_INTRO}</p>

                    <details class="news-tbank-more">
                        <summary>Какие продукты можно подключить</summary>
                        <h3 class="news-tbank-subhead">Вот какие продукты можно подключить с нашей помощью</h3>
                        <ul class="tb-bullets">{products_html}</ul>

                        <h3 class="news-tbank-subhead">Какие ещё инструменты доступны в Т-Банке</h3>
                        <ul class="news-tbank-dash-list">{tools_html}</ul>

                        <p class="tb-note">{_TBANK_NEWS_TRUST}</p>
                    </details>

                    <p class="news-tbank-cta-lead">Чтобы открыть счёт, свяжитесь с нами или перейдите по ссылке.</p>
                    {render_tbank_products_block()}

                    <div class="tb-conditions">
                        <h3>Условия использования продуктов</h3>
                        <ul>{conditions_html}</ul>
                    </div>
                </div>
            </div>
        </section>"""


#: Шесть «убранных» вещей. Список выведен в константу, чтобы тест видел его
#: целиком и не зависел от вёрстки.
REMOVED = [
    "Звонки в салон",
    "Голосовая почта",
    "Ожидание на линии",
    "Уточнения по СМС",
    "Десять полей в форме",
    "Регистрации, которые ни на что не влияют",
]


def render_about_page(user=None) -> str:
    """Страница «Манифест»."""
    removed = "".join(f"<li>{e(r)}</li>" for r in REMOVED)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Манифест | руми.</title>
    <meta name="description" content="Мы убрали из красоты всё лишнее. Остались вы и мастер.">
    {get_base_styles()}
</head>
<body>
    {render_header("manifest", user)}

    <main class="about-main">
        <section class="about-hero">
            <div class="section-container">
                <span class="about-kicker">Манифест</span>
                <h1 class="about-title">Мы убрали из красоты всё лишнее. Остались <em>вы и мастер</em>.</h1>
            </div>
        </section>

        <section class="about-body">
            <div class="section-container">
                <div class="about-cols">
                    <p class="about-drop">Раньше, чтобы записаться к парикмахеру, нужно было найти мастера и номер, дозвониться, объяснить, кто вы и что хотите, и запомнить время записи.</p>
                    <p>Теперь — четыре клика. <b>Салон. Услуга. Время. Готово.</b> Всё остальное мы оставили на своей стороне: расписание, напоминания, оплату, общение с мастером, аналитику для салона.</p>
                </div>

                <h2 class="about-removed-title">Что мы <em>убрали</em></h2>
                <ul class="about-removed">{removed}</ul>

                <blockquote class="about-quote">Для клиентов — 4 клика до записи. Для салонов — всё для управления в одном окне.</blockquote>
                <div class="about-cta">{ui.button("Найти салон", href="/salons")}</div>
            </div>
        </section>

        {_render_tbank_news()}

        {render_footer(user)}
    </main>
</body>
</html>"""
