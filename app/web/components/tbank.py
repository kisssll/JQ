# app/web/components/tbank.py
"""Партнёрство с Т‑Банком: баннер, плашка «официальный партнёр» и блок с
реферальной ссылкой.

Всё, что касается партнёрства, собрано здесь одним модулем: реферальная
ссылка встречается на нескольких страницах, и держать её копиями в разметке
опасно — при смене agentId переходы молча перестанут засчитываться.

Логотип — временная отрисовка, см. TBANK_LOGO ниже.
"""

from app.web.components.icons import ICON_ARROW_RIGHT

# Реферальная ссылка партнёра. Метки agentId/agentSsoId/partnerId выданы
# Т‑Банком именно нам — по ним засчитываются переходы, поэтому ссылка живёт
# в одном месте и не дублируется по страницам.
TBANK_REFERRAL_URL = (
    "https://www.tbank.ru/business/partnership/all-products"
    "?utm_medium=ptr.act&utm_campaign=sme.partners&utm_source=partner_rko_a_sme"
    "&agentId=7-3L2465X0B&agentSsoId=0e0d6690-578d-4878-8045-a2922670ed26"
    "&partnerId=8-101809YZA"
)

# Обязательная маркировка рекламы: реквизиты рекламодателя из материалов
# Т‑Банка для партнёров. Токен erid сюда не входит — его выдаёт рекламная
# система, и без него интернет-реклама не размечена по ст. 18.1 ФЗ «О
# рекламе». Если Т‑Банк его пришлёт, добавить в TBANK_ERID ниже.
TBANK_DISCLAIMER = "Подробнее на tbank.ru. АО «ТБанк», лицензия № 2673. Реклама."
TBANK_ERID = ""

# ВРЕМЕННАЯ ОТРИСОВКА ЛОГОТИПА.
# Официальные исходники лежат в Figma «Материалы для партнёров». Забрать их
# оттуда нельзя: анонимному зрителю Figma даёт только смотреть и двигать
# холст, а выделение слоя (без него нет ни инспектора, ни экспорта) требует
# регистрации; сам холст рисуется на WebGL, файлов в разметке страницы нет.
# Поэтому щит нарисован по снимку официальной плашки: белый щит с тёмной «Т»,
# скруглённый верх, низ сходится в острие. Когда придёт экспорт из Figma —
# заменить содержимое этой константы, больше нигде править не нужно.
TBANK_SHIELD_WHITE = "#ffffff"
TBANK_LETTER_DARK = "#2b2b2b"

TBANK_LOGO = (
    '<svg class="tb-logo" viewBox="0 0 26 26" xmlns="http://www.w3.org/2000/svg" '
    'aria-hidden="true" focusable="false">'
    # Щит: прямые бока, скруглённая верхняя кромка, острие снизу по центру.
    f'<path fill="{TBANK_SHIELD_WHITE}" '
    'd="M2,0 H24 A2,2 0 0 1 26,2 V19.6 L13,26 L0,19.6 V2 A2,2 0 0 1 2,0 Z"/>'
    # «Т» с лёгким расширением ножки книзу — как в фирменном знаке.
    f'<path fill="{TBANK_LETTER_DARK}" '
    'd="M6.2,6 H19.8 V10.4 H15 V16.6 L15.5,17.5 H10.5 L11,16.6 V10.4 H6.2 Z"/>'
    "</svg>"
)

_YELLOW_BADGE_TEXT = "Официальный партнёр"
_YELLOW_BADGE_SUB = "Т‑Банк | Бизнес"


def render_tbank_badge() -> str:
    """Жёлтая плашка «Официальный партнёр Т‑Банк | Бизнес».

    Это статус, а не реклама: она ничего не предлагает и никуда не ведёт,
    поэтому маркировки рекламы при ней нет.
    """
    return (
        '<div class="tb-badge">'
        f'<span class="tb-badge-logo">{TBANK_LOGO}</span>'
        '<span class="tb-badge-text">'
        f'<span class="tb-badge-title">{_YELLOW_BADGE_TEXT}</span>'
        f'<span class="tb-badge-sub">{_YELLOW_BADGE_SUB}</span>'
        "</span>"
        "</div>"
    )


# Подпись под заголовком баннера зависит от того, кто читает страницу:
# на лендинге моделей «касса для салона» адресована не тем людям.
BANNER_DESC_DEFAULT = "Продукты Т‑Банка для бизнеса — на условиях партнёра."
BANNER_DESC_SALON = "Расчётный счёт, эквайринг и касса для салона — на условиях партнёра."


def render_tbank_partner_banner(desc: str = BANNER_DESC_DEFAULT) -> str:
    """Баннер «Мы стали партнёрами Т‑Банка» со ссылкой на манифест.

    Ведёт внутрь сайта, а не в банк: подробности и сама реферальная ссылка
    живут на манифесте, чтобы не повторять их на каждой странице.
    """
    return f"""
    <section class="section-py tb-banner-section">
        <div class="section-container">
            <a class="tb-banner" href="/about">
                <span class="tb-banner-logo">{TBANK_LOGO}</span>
                <span class="tb-banner-body">
                    <span class="tb-banner-title">Мы стали партнёрами Т‑Банка</span>
                    <span class="tb-banner-desc">{desc}</span>
                </span>
                <span class="tb-banner-arrow">{ICON_ARROW_RIGHT}</span>
            </a>
        </div>
    </section>"""


def render_tbank_products_block() -> str:
    """Блок на манифесте: кнопка и QR — оба ведут по реферальной ссылке.

    QR лежит отдельным файлом (static/images/tbank-qr.svg) и сгенерирован из
    той же TBANK_REFERRAL_URL, см. комментарий в модуле.
    """
    erid = f'<span class="tb-erid">{TBANK_ERID}</span>' if TBANK_ERID else ""
    return f"""
    <section class="tb-products">
        <div class="tb-products-inner">
            <div class="tb-products-text">
                {render_tbank_badge()}
                <h2 class="tb-products-title">Продукты Т‑Банка для бизнеса</h2>
                <p class="tb-products-desc">
                    Расчётный счёт, эквайринг, онлайн-касса и зарплатный проект.
                    Открыть можно по нашей партнёрской ссылке.
                </p>
                <a class="tb-products-btn" href="{TBANK_REFERRAL_URL}"
                   target="_blank" rel="noopener noreferrer">
                    Выбрать продукт {ICON_ARROW_RIGHT}
                </a>
            </div>

            <figure class="tb-qr">
                <a class="tb-qr-link" href="{TBANK_REFERRAL_URL}"
                   target="_blank" rel="noopener noreferrer"
                   aria-label="Открыть страницу продуктов Т‑Банка">
                    <img src="/static/images/tbank-qr.svg" alt="QR-код на страницу продуктов Т‑Банка"
                         width="230" height="230" loading="lazy">
                </a>
                <figcaption class="tb-qr-caption">Наведите камеру телефона</figcaption>
            </figure>
        </div>
        <p class="tb-disclaimer">{TBANK_DISCLAIMER}{erid}</p>
    </section>"""
