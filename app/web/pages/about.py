# app/web/pages/about.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_CIRCLE_CHECK, ICON_ARROW_RIGHT
from app.web.pages.business.tbank_partner import TBANK_LINK, TBANK_CONDITION_LINKS

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
        <section class="section-py news-tbank">
            <div class="section-container">
                <div class="card news-tbank-card">
                    <span class="tb-badge"><span class="tb-badge-letter">Т</span> Новость · Партнёрство с Т-Банком</span>
                    <h2>Мы стали партнёрами Т-Банка</h2>
                    <p class="tb-intro">{_TBANK_NEWS_INTRO}</p>

                    <h3 class="news-tbank-subhead">Вот какие продукты можно подключить с нашей помощью</h3>
                    <ul class="tb-bullets">{products_html}</ul>

                    <h3 class="news-tbank-subhead">Какие ещё инструменты доступны в Т-Банке</h3>
                    <ul class="news-tbank-dash-list">{tools_html}</ul>

                    <p class="tb-note">{_TBANK_NEWS_TRUST}</p>

                    <p class="news-tbank-cta-lead">Чтобы открыть счёт, свяжитесь с нами или перейдите по ссылке.</p>
                    <a class="tb-cta" href="{TBANK_LINK}" target="_blank" rel="noopener noreferrer">
                        Оставить заявку {ICON_ARROW_RIGHT}
                    </a>

                    <div class="tb-conditions">
                        <h3>Условия использования продуктов</h3>
                        <ul>{conditions_html}</ul>
                    </div>
                </div>
            </div>
        </section>"""


def render_about_page(user=None) -> str:
    """Страница «Манифест»."""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Манифест | руми.</title>
    <meta name="description" content="Мы убрали из красоты всё лишнее. Остались вы и мастер.">
    {get_base_styles()}
    <style>
        .tb-badge {{ display:inline-flex; align-items:center; gap:0.5rem; background:color-mix(in srgb, var(--color-primary, #c081b8) 12%, transparent);
            color:var(--color-primary, #c081b8); font-weight:600; font-size:0.8rem; padding:0.4rem 0.9rem; border-radius:9999px; margin-bottom:1rem }}
        .tb-badge-letter {{ display:inline-flex; align-items:center; justify-content:center; width:1.25rem; height:1.25rem;
            border-radius:50%; background:var(--color-primary, #c081b8); color:#fff; font-weight:700; font-size:0.75rem }}
        .tb-intro {{ color:var(--color-muted); font-size:1rem; line-height:1.6; margin:0 0 1.5rem }}
        .tb-bullets {{ list-style:none; margin:0 0 1.75rem; padding:0; display:flex; flex-direction:column; gap:0.85rem }}
        .tb-bullet {{ display:flex; align-items:flex-start; gap:0.65rem; line-height:1.55 }}
        .tb-bullet svg {{ flex-shrink:0; margin-top:0.15rem; color:var(--color-primary, #c081b8) }}
        .tb-note {{ background:var(--color-surface-alt, #f6f5f8); border-radius:0.75rem; padding:1rem 1.25rem; font-size:0.9rem; color:var(--color-muted); margin:0 0 1.5rem }}
        .tb-cta {{ display:inline-flex; align-items:center; gap:0.5rem; background:linear-gradient(135deg, var(--color-primary, #c081b8), var(--color-accent-hover, #a566a0));
            color:#fff !important; padding:0.85rem 1.75rem; border-radius:9999px; text-decoration:none; font-weight:600 }}
        .tb-cta:hover {{ opacity:0.92 }}
        .tb-conditions {{ margin-top:2rem; padding-top:1.5rem; border-top:1px solid var(--color-border) }}
        .tb-conditions h3 {{ font-size:0.9rem; color:var(--color-muted); font-weight:600; margin:0 0 0.6rem }}
        .tb-conditions ul {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:0.4rem }}
        .tb-condition-link {{ font-size:0.85rem; color:var(--color-muted); text-decoration:underline }}
        .tb-condition-link:hover {{ color:var(--color-primary, #c081b8) }}

        .news-tbank-card {{ max-width:820px; margin:0 auto; padding:2rem }}
        .news-tbank-subhead {{ font-size:1.05rem; margin:0 0 0.85rem }}
        .news-tbank-dash-list {{ list-style:none; margin:0 0 1.75rem; padding:0; display:flex; flex-direction:column; gap:0.6rem; color:var(--color-muted); line-height:1.55 }}
        .news-tbank-dash-list li {{ padding-left:1.1rem; position:relative }}
        .news-tbank-dash-list li::before {{ content:"—"; position:absolute; left:0; color:var(--color-primary, #c081b8) }}
        .news-tbank-cta-lead {{ margin:0 0 1rem; font-weight:500 }}
    </style>
</head>
<body>
    {render_header("manifest")}
    {render_sidebar("manifest", user)}

    <main class="home-main">
        <section class="about-hero">
            <div class="section-container">
                <p class="about-label">Манифест</p>
                <h1 class="about-title">Мы убрали из красоты всё лишнее. Остались вы и мастер<span class="about-dot">.</span></h1>
    
                <div class="about-grid">
                    <div class="about-text">
                        <p class="about-text-p">Раньше, чтобы записаться к парикмахеру, нужно было найти мастера и номер, дозвониться, объяснить, кто вы и что хотите, и запомнить время записи.</p>
                        <p class="about-text-p">Теперь — четыре клика. Салон. Услуга. Время. Готово. Всё остальное мы оставили на своей стороне: расписание, напоминания, оплату, общение с мастером, аналитику для салона.</p>
                    </div>
                    <div class="about-list">
                        <p class="about-list-label">Что мы убрали</p>
                        <ul class="about-list-items">
                            <li><span class="about-list-bullet"></span>Звонки в салон</li>
                            <li><span class="about-list-bullet"></span>Голосовая почта</li>
                            <li><span class="about-list-bullet"></span>Ожидание на линии</li>
                            <li><span class="about-list-bullet"></span>Уточнения по СМС</li>
                            <li><span class="about-list-bullet"></span>Десять полей в форме</li>
                            <li><span class="about-list-bullet"></span>Регистрации, которые ни на что не влияют</li>
                        </ul>
                    </div>
                </div>

                <div class="about-footer">
                    <p class="about-footer-text">Для клиентов — 4 клика до записи. Для салонов — всё для управления в одном окне.</p>
                    <div class="about-footer-buttons">
                        <a href="/salons" class="about-btn-primary">Найти салон</a>
                    </div>
                </div>
            </div>
        </section>

        {_render_tbank_news()}

        {render_footer(user)}
    </main>
</body>
</html>"""
    return html