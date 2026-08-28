# app/web/pages/business/tbank_partner.py
"""Партнёрские страницы Т-Банка: расчётный счёт (РКО), регистрация бизнеса,
кредиты для развития бизнеса. Публичные (доступны без входа), ссылки на них —
в подвале (см. app/web/components/footer.py) и, при желании, на /business.

TBANK_LINK — реферальная ссылка (CTA-кнопки), пока заглушка (#), появится
позже. TBANK_CONDITION_LINKS — официальные PDF/страницы с условиями продуктов
Т-Банка, реальные URL взяты из гиперссылок партнёрского текста; их же
переиспользует новость на странице «Манифест» (app/web/pages/about.py)."""
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_CIRCLE_CHECK, ICON_ARROW_RIGHT

# TODO: подставить реальную реферальную ссылку Т-Банка, когда она будет готова.
TBANK_LINK = "#"

TBANK_CONDITION_LINKS = {
    "rko_tariffs": ("Тарифы на обслуживание расчётного счёта в Т-Бизнесе",
                     "https://acdn.tinkoff.ru/static/documents/business-tariffs-all.pdf"),
    "rko_promo": ("Подробнее об акции «Бесплатное обслуживание за авансовую оплату»",
                  "https://acdn.tinkoff.ru/static/documents/promo-free-upfront-service.pdf"),
    "registration_conditions": ("Условия регистрации",
                                 "https://acdn.tinkoff.ru/static/documents/business-conditions-registration.pdf"),
    "registration_promo": ("Условия акции «Бесплатная онлайн-бухгалтерия»",
                            "https://acdn.tinkoff.ru/static/documents/promo-free-online-bookkeeping.pdf"),
    "credit_turnover": ("Оборотный кредит", "https://www.tinkoff.ru/business/turnover/tariffs/"),
    "credit_overdraft": ("Овердрафт", "https://www.tinkoff.ru/business/overdraft/tariffs/"),
    "credit_cash": ("Кредит на любые цели для ИП",
                     "https://acdn.tinkoff.ru/static/documents/loans-cashloan-tariff.pdf"),
}

_INTRO = (
    "Мы стали партнёрами Т-Банка — экосистемы банковских продуктов для предпринимателей "
    "и компаний. С нашей помощью вы можете зарегистрировать ИП или ООО, открыть расчётный "
    "счёт, подключить приём платежей и использовать другие инструменты для решения "
    "бизнес-задач."
)

PAGES = {
    "rko": {
        "title": "Расчётный счёт в Т-Банке",
        "meta": "Откройте расчётный счёт для ИП или ООО в Т-Банке — партнёре Руми. Бесплатное открытие за один день, без очередей.",
        "eyebrow": "Расчётный счёт",
        "heading": "Расчётный счёт в Т-Банке для ИП и компаний",
        "lead": "Открытие бесплатно за один день, без поездок в банк и очередей.",
        "bullets": [
            "Моментальная круглосуточная отправка платежей на счета в Т-Банк, на остальные счета — с 01:00 до 21:00 мск",
            "Вывод со счёта ИП на личные карты Т-Банка до 1 млн рублей без комиссии",
            "Персональный менеджер постоянно на связи — в чате и по телефону",
            "До 500 000 ₽ — скидки на сервисы партнёров",
        ],
        "note": (
            "Обслуживание первые 2 месяца бесплатно на любом тарифе, после — от 490 ₽ в "
            "месяц. Можно оплатить тариф на год по цене десяти месяцев — так вы сэкономите "
            "стоимость двух месяцев обслуживания."
        ),
        "cta_label": "Открыть счёт в Т-Банке",
        "conditions": ["rko_tariffs", "rko_promo"],
    },
    "registration": {
        "title": "Регистрация бизнеса через Т-Банк",
        "meta": "Зарегистрируйте ИП или ООО через Т-Банк — партнёра Руми. Без госпошлины и визита в налоговую.",
        "eyebrow": "Регистрация бизнеса",
        "heading": "Регистрация ИП или ООО с одним учредителем",
        "lead": (
            "Без уплаты госпошлины и скрытых платежей, без посещения налоговой. Т-Банк "
            "проверит документы перед отправкой, привезёт их вам на подпись в удобное "
            "место и время и сам отправит в налоговую."
        ),
        "bullets": [
            "Консультация по выбору кодов ОКВЭД и системы налогообложения",
            "Открытие счёта после регистрации за 0 ₽",
            "Бесплатная онлайн-бухгалтерия для ИП на УСН «Доходы» и бизнеса на АУСН",
        ],
        "note": None,
        "cta_label": "Зарегистрировать бизнес",
        "conditions": ["registration_conditions", "registration_promo"],
    },
    "credit": {
        "title": "Кредиты для развития бизнеса от Т-Банка",
        "meta": "Кредиты, овердрафт и оборотные средства для бизнеса от Т-Банка — партнёра Руми.",
        "eyebrow": "Кредиты для бизнеса",
        "heading": "Кредиты на открытие и развитие бизнеса",
        "lead": None,
        "bullets": [
            "Инвестиции и новый бизнес — кредит на любые цели без залога, до 5 млн рублей на срок до 5 лет",
            "Закрытие кассовых разрывов и срочные траты — овердрафт с лимитом до 10 млн рублей на срок до 45 дней",
            "Быстрые вложения — оборотный кредит до 10 млн рублей на срок до 6 месяцев",
        ],
        "note": "Особые условия для среднего и крупного бизнеса — лимит до 200 млн рублей, срок договора до 10 лет.",
        "cta_label": "Подать заявку на кредит",
        "conditions": ["credit_turnover", "credit_overdraft", "credit_cash"],
    },
}


def _render_tbank_page(slug: str, user=None) -> str:
    page = PAGES[slug]

    bullets_html = "".join(
        f'<li class="tb-bullet">{ICON_CIRCLE_CHECK}<span>{b}</span></li>'
        for b in page["bullets"]
    )
    lead_html = f'<p class="tb-lead">{page["lead"]}</p>' if page["lead"] else ""
    note_html = f'<p class="tb-note">{page["note"]}</p>' if page["note"] else ""
    conditions_html = "".join(
        f'<li><a class="tb-condition-link" href="{url}" target="_blank" rel="noopener noreferrer">{label}</a></li>'
        for label, url in (TBANK_CONDITION_LINKS[key] for key in page["conditions"])
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{page["title"]} | Руми</title>
    <meta name="description" content="{page["meta"]}">
    {get_base_styles()}
    <style>
        /* padding-top с запасом — на мобиле шапка с плашкой лого остаётся
           (там гамбургер — единственный вход в меню) и перекрывает верх
           контента, если отступа мало. */
        .tb-wrap {{ max-width:720px; padding:5.5rem 1.5rem 4rem }}
        @media (min-width: 1024px) {{
            .tb-wrap {{ padding-top:2.5rem }}
        }}
        .tb-badge {{ display:inline-flex; align-items:center; gap:0.5rem; background:color-mix(in srgb, var(--color-primary, #c081b8) 12%, transparent);
            color:var(--color-primary, #c081b8); font-weight:600; font-size:0.8rem; padding:0.4rem 0.9rem; border-radius:9999px; margin-bottom:1rem }}
        .tb-badge-letter {{ display:inline-flex; align-items:center; justify-content:center; width:1.25rem; height:1.25rem;
            border-radius:50%; background:var(--color-primary, #c081b8); color:#fff; font-weight:700; font-size:0.75rem }}
        .tb-intro {{ color:var(--color-muted); font-size:1rem; line-height:1.6; margin:0 0 2rem }}
        .tb-card {{ margin-bottom:1.5rem }}
        .tb-eyebrow {{ color:var(--color-primary, #c081b8); font-weight:600; font-size:0.85rem; text-transform:uppercase; letter-spacing:0.04em; margin:0 0 0.5rem }}
        .tb-card h2 {{ margin:0 0 0.75rem; font-size:1.4rem }}
        .tb-lead {{ color:var(--color-muted); margin:0 0 1.25rem; line-height:1.6 }}
        .tb-bullets {{ list-style:none; margin:0 0 1.25rem; padding:0; display:flex; flex-direction:column; gap:0.75rem }}
        .tb-bullet {{ display:flex; align-items:flex-start; gap:0.65rem; line-height:1.5 }}
        .tb-bullet svg {{ flex-shrink:0; margin-top:0.15rem; color:var(--color-primary, #c081b8) }}
        .tb-note {{ background:var(--color-surface-alt, #f6f5f8); border-radius:0.75rem; padding:1rem 1.25rem; font-size:0.9rem; color:var(--color-muted); margin:0 0 1.5rem }}
        .tb-cta {{ display:inline-flex; align-items:center; gap:0.5rem; background:linear-gradient(135deg, var(--color-primary, #c081b8), var(--color-accent-hover, #a566a0));
            color:#fff !important; padding:0.85rem 1.75rem; border-radius:9999px; text-decoration:none; font-weight:600; }}
        .tb-cta:hover {{ opacity:0.92 }}
        .tb-conditions {{ margin-top:2rem; padding-top:1.5rem; border-top:1px solid var(--color-border) }}
        .tb-conditions h3 {{ font-size:0.9rem; color:var(--color-muted); font-weight:600; margin:0 0 0.6rem }}
        .tb-conditions ul {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:0.4rem }}
        .tb-condition-link {{ font-size:0.85rem; color:var(--color-muted); text-decoration:underline }}
        .tb-condition-link:hover {{ color:var(--color-primary, #c081b8) }}

        /* См. app/web/pages/model_join.py — на десктопе сайдбар уже даёт
           навигацию, а плашка с лого из шапки просто перекрывает заголовок
           страницы (#main-header зафиксирован поверх контента). */
        @media (min-width: 1024px) {{
            #main-header {{ display: none; }}
        }}
    </style>
</head>
<body>
    {render_header("business")}
    {render_sidebar("business", user)}

    <main class="main-content">
        <div class="tb-wrap">
            <span class="tb-badge"><span class="tb-badge-letter">Т</span> Партнёрское предложение Т-Банка</span>
            <h1>{page["heading"]}</h1>
            <p class="tb-intro">{_INTRO}</p>

            <div class="card tb-card">
                <p class="tb-eyebrow">{page["eyebrow"]}</p>
                {lead_html}
                <ul class="tb-bullets">{bullets_html}</ul>
                {note_html}
                <a class="tb-cta" href="{TBANK_LINK}" target="_blank" rel="noopener noreferrer">
                    {page["cta_label"]} {ICON_ARROW_RIGHT}
                </a>
            </div>

            <div class="tb-conditions">
                <h3>Условия использования продуктов</h3>
                <ul>{conditions_html}</ul>
            </div>
        </div>
    </main>
    {render_footer(user)}
</body>
</html>"""


def render_tbank_rko_page(user=None) -> str:
    return _render_tbank_page("rko", user)


def render_tbank_registration_page(user=None) -> str:
    return _render_tbank_page("registration", user)


def render_tbank_credit_page(user=None) -> str:
    return _render_tbank_page("credit", user)
