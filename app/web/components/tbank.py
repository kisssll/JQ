# app/web/components/tbank.py
"""Партнёрство с Т‑Банком: баннер, плашка «официальный партнёр» и блок с
реферальной ссылкой.

Всё, что касается партнёрства, собрано здесь одним модулем: реферальная
ссылка встречается на нескольких страницах, и держать её копиями в разметке
опасно — при смене agentId переходы молча перестанут засчитываться.
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
# Т‑Банка. Нужна только под блоком продуктов — в баннерах-креативах она уже
# вшита в сам макет. Токен erid сюда не входит: его выдаёт рекламная система,
# и без него интернет-реклама не размечена по ст. 18.1 ФЗ «О рекламе».
TBANK_DISCLAIMER = "Подробнее на tbank.ru. АО «ТБанк», лицензия № 2673. Реклама."

# Токен маркировки. Когда ОРД его выдаст, достаточно вписать сюда: он сам
# уйдёт и в текст под блоком, и в саму реферальную ссылку — гайд Т‑Банка
# требует обоих мест. QR после этого пересобрать:
#     .venv/bin/python scripts/build_tbank_qr.py
TBANK_ERID = ""


def referral_url() -> str:
    """Реферальная ссылка, при наличии — с токеном маркировки."""
    return f"{TBANK_REFERRAL_URL}&erid={TBANK_ERID}" if TBANK_ERID else TBANK_REFERRAL_URL


def _erid_note() -> str:
    """Токен текстом. Формат `erid: XXXX` — рекомендация Роскомнадзора."""
    return f'<span class="tb-erid">erid: {TBANK_ERID}</span>' if TBANK_ERID else ""

# Официальные материалы Т‑Банка лежат в static/images/tbank. Исходники —
# PNG на 1–2 МБ каждый; браузеру отдаём сжатые производные (WebP + запасной
# JPEG/PNG), они и хранятся в репозитории. Сами исходники не коммитим: они
# тяжелее лимита pre-commit-хука и на сайте не нужны, см. .gitignore.
#
# Раньше щит и плашка были нарисованы мной вручную — фирменный блок так не
# собирают, теперь стоят официальные файлы.
_IMG = "/static/images/tbank"
BADGE_ALT = "Официальный партнёр Т‑Банк | Бизнес"
BANNER_ALT = "Официальный партнёр Т‑Банка"


def render_tbank_badge() -> str:
    """Плашка «Официальный партнёр Т‑Банк | Бизнес».

    Это статус, а не реклама: плашка ничего не предлагает и никуда не ведёт,
    поэтому маркировки рекламы при ней нет.
    """
    return (
        '<picture class="tb-badge">'
        f'<source type="image/webp" srcset="{_IMG}/partner-badge.webp">'
        f'<img src="{_IMG}/partner-badge.png" alt="{BADGE_ALT}" '
        'width="360" height="110" loading="lazy">'
        "</picture>"
    )


def render_tbank_partner_banner() -> str:
    """Баннер-креатив Т‑Банка со ссылкой на манифест.

    Ведёт внутрь сайта, а не в банк: подробности и сама реферальная ссылка
    живут на манифесте, чтобы не повторять их на каждой странице.

    Пропорции переключает <picture>: широкий креатив на телефоне ужал бы текст
    до нечитаемого, поэтому там квадратный вариант. Маркировка рекламы вшита
    в макет креатива, отдельной строки под баннером не нужно.

    Ширина ограничена в CSS: во всю колонку креатив занимал 428px по высоте
    плюс 8rem отступов секции — почти 560px под баннер посреди страницы.
    """
    return f"""
    <section class="tb-banner-section">
        <div class="section-container">
            <a class="tb-banner" href="/about" aria-label="{BANNER_ALT} — подробнее">
                <picture>
                    <!-- width/height у каждого source обязательны: без них
                         браузер резервирует место по атрибутам <img> (900x900)
                         и, выбрав широкий креатив, перестраивает вёрстку —
                         на десктопе это скачок в 244px. -->
                    <source media="(min-width: 700px)" type="image/webp"
                            srcset="{_IMG}/partner-banner-wide.webp"
                            width="2000" height="894">
                    <source media="(min-width: 700px)"
                            srcset="{_IMG}/partner-banner-wide.jpg"
                            width="2000" height="894">
                    <source type="image/webp" srcset="{_IMG}/partner-banner-square.webp"
                            width="900" height="900">
                    <img src="{_IMG}/partner-banner-square.jpg" alt="{BANNER_ALT}"
                         width="900" height="900" loading="lazy">
                </picture>
            </a>
        </div>
    </section>"""


def render_tbank_products_block() -> str:
    """Блок на манифесте: кнопка и QR — оба ведут по реферальной ссылке.

    QR собран из той же TBANK_REFERRAL_URL. По содержимому он совпадает с
    кодом, который выдал Т‑Банк (проверено декодированием его файла), но у
    нас вектор — он не мылится ни на каком экране.
    """
    erid = _erid_note()
    url = referral_url()
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
                <a class="tb-products-btn" href="{url}"
                   target="_blank" rel="noopener noreferrer">
                    Выбрать продукт {ICON_ARROW_RIGHT}
                </a>
            </div>

            <figure class="tb-qr">
                <a class="tb-qr-link" href="{url}"
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


def render_tbank_partner_strip() -> str:
    """Компактная отметка о партнёрстве — только плашка, ссылкой на манифест.

    Для страниц, где полноразмерный креатив был бы неуместен: занимает одну
    строку вместо блока в пол-экрана.
    """
    return f"""
    <div class="tb-strip">
        <a class="tb-strip-link" href="/about" aria-label="{BADGE_ALT} — подробнее">
            {render_tbank_badge()}
        </a>
    </div>"""
