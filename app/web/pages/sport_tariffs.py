# app/web/pages/sport_tariffs.py
"""«Тарифы платформы Руми Спорт» — калькулятор стоимости для клубов и тренеров,
карточки тарифов, документы и инструкции.

Расценки:
- Для отдельного тренера: 399 ₽/мес (как для одиночного мастера в бьюти).
- Для одного спортзала: 3 500 ₽/мес.
- Для 2 и более залов: 3 500 ₽ + 2 500 ₽ за каждый последующий зал
  (2 зала = 6 000 ₽, 3 зала = 8 500 ₽, N залов = 3 500 + (N-1)*2 500 ₽/мес).
- Индивидуальные предложения (custom offer): закрепляются администратором
  через модератор-панель и имеют приоритет перед алгоритмом расчёта.
"""
import html
import json
from app.services.sport_tariffs import (
    SPORT_COACH_MONTHLY_PRICE,
    SPORT_GYM_BASE_MONTHLY_PRICE,
    SPORT_ADDITIONAL_VENUE_PRICE,
    get_sport_calculator_pricing_table,
)
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import (
    ICON_ARROW_RIGHT,
    ICON_CHEVRON_DOWN,
    ICON_CIRCLE_CHECK,
    ICON_FILE_TEXT,
)
from app.web.components.styles import get_base_styles
from app.web.pages.legal import LEGAL_VERSION_HUMAN


_SPORT_DOCUMENTS = [
    {
        "slug": "sport/legal/license",
        "title": "Условия использования платформы для спортивных клубов",
        "description": "Лицензионный договор-оферта на предоставление сервиса Руми Спорт клубам и залам.",
    },
    {
        "slug": "sport/legal/consent",
        "title": "Согласие на обработку персональных данных",
        "description": "Условия обработки данных клиентов, тренеров и сотрудников спортивных клубов.",
    },
    {
        "slug": "sport/legal/terms",
        "title": "Пользовательское соглашение сервиса Руми",
        "description": "Общие условия использования онлайн-сервиса Руми для физических и юридических лиц.",
    },
    {
        "slug": "sport/legal/privacy",
        "title": "Политика конфиденциальности",
        "description": "Порядок сбора, хранения и защиты конфиденциальной информации и файлов cookie.",
    },
]

_SPORT_INSTRUCTIONS = [
    (
        "Как подключить спортивный клуб к платформе",
        'Откройте раздел «<a class="text-link" href="/sport/business/register-gym">Для бизнеса → Добавить клуб</a>» '
        'и заполните анкету (название, город, адрес основного зала, телефон). '
        'После отправки сразу откроется панель управления залом, где можно загрузить фото, '
        'добавить тренеров, настроить направления и абонементы. Первые 14 дней — бесплатно.',
    ),
    (
        "Как работает индивидуальная запись к тренерам",
        'Тренер в своём личном кабинете настраивает статичные окна расписания на дни недели '
        '(например, пн/ср/пт 10:00–18:00) и длительность сессий. Клиент на странице клуба или '
        'тренера выбирает дату, свободный интервал и записывается в 2 клика.',
    ),
    (
        "Как добавить несколько залов (сеть спортзалов)",
        'В панели управления клубом во вкладке «Залы» нажмите «Добавить филиал» и укажите '
        'название и адрес второго зала. Расписание тренировок и тренеров можно разделять по филиалам, '
        'а клиенты смогут фильтровать тренировки по нужному адресу.',
    ),
    (
        "Как закрыть дату на ремонт или отпуск тренера",
        'В панели управления доступен календарь закрытий (Closures). Вы можете установить дату '
        'или диапазон закрытия конкретного зала (например, на санитарный день) или отдельного тренера '
        '(отпуск/больничный). Все окна расписания на этот период автоматически снимутся с записи.',
    ),
    (
        "Как закрепляются индивидуальные предложения по тарифу",
        'Для крупных спортивных сетей, франшиз или партнёрских клубов администраторы платформы '
        'через модератор-панель могут закрепить персональную стоимость абонентской платы в месяц '
        '(например, фиксированные спецусловия вместо стандартного подсчёта 3500 + 2500 ₽ за зал). '
        'Закреплённое предложение отобразится в кабинете клуба.',
    ),
]

TABS = {
    "plans": "Тарифы и калькулятор",
    "documents": "Документы",
    "guides": "Инструкции",
}


def _sport_accordion_html(items: list[tuple[str, str]]) -> str:
    return "".join(
        f"""
        <div class="accordion-item" style="border:1px solid var(--color-border);border-radius:var(--radius-16);margin-bottom:0.75rem;background:var(--color-surface);overflow:hidden;">
            <button class="accordion-header" style="width:100%;display:flex;align-items:center;justify-content:space-between;padding:1rem 1.25rem;background:none;border:none;cursor:pointer;font-weight:600;font-size:1.05rem;color:var(--color-heading);text-align:left;">
                <span class="accordion-label">{title}</span>
                <span class="accordion-chevron" style="transition:transform 0.2s ease;">{ICON_CHEVRON_DOWN}</span>
            </button>
            <div class="accordion-body" style="padding:0 1.25rem 1.25rem;color:var(--color-text);line-height:1.6;font-size:0.95rem;">
                <p style="margin:0;">{text}</p>
            </div>
        </div>"""
        for title, text in items
    )


def _sport_documents_html() -> str:
    cards = "".join(
        f"""
        <a class="doc-card" href="/{d['slug']}" style="display:flex;align-items:center;gap:1rem;padding:1rem 1.25rem;background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-16);margin-bottom:0.75rem;text-decoration:none;color:inherit;transition:transform 0.15s, border-color 0.15s;">
            <span class="doc-card-icon" style="flex-shrink:0;color:var(--color-accent-text);">{ICON_FILE_TEXT}</span>
            <span class="doc-card-text" style="flex:1;">
                <span class="doc-card-title" style="display:block;font-weight:600;font-size:1rem;color:var(--color-heading);margin-bottom:0.25rem;">{html.escape(d['title'])}</span>
                <span class="doc-card-desc" style="display:block;font-size:0.85rem;color:var(--color-muted);margin-bottom:0.25rem;">{html.escape(d['description'])}</span>
                <span class="doc-card-date" style="display:block;font-size:0.75rem;color:var(--color-muted);">Действующая редакция · {html.escape(LEGAL_VERSION_HUMAN)}</span>
            </span>
            <span class="doc-card-arrow" style="color:var(--color-muted);">{ICON_ARROW_RIGHT}</span>
        </a>"""
        for d in _SPORT_DOCUMENTS
    )
    return f"""
        <div style="max-width:800px;margin:0 auto;">
            <p style="margin-bottom:1.5rem;color:var(--color-muted);">Официальные документы сервиса Руми Спорт. Регулируют предоставление платформенных услуг, права и ответственность сторон.</p>
            <div class="doc-list">{cards}</div>
        </div>"""


def render_sport_tariffs_page(user=None, tab: str = "plans", plans=None) -> str:
    pricing_table = get_sport_calculator_pricing_table(15)
    pricing_json = json.dumps(pricing_table)

    active = tab if tab in TABS else "plans"

    def tab_link(key: str) -> str:
        on = key == active
        href = "/sport/tariffs" if key == "plans" else f"/sport/tariffs?tab={key}"
        active_style = "background:var(--color-primary);color:var(--color-btn-text);" if on else "background:var(--color-surface);color:var(--color-text);"
        return (
            f'<a class="sport-tab-link" role="tab" '
            f'id="tabbtn-{key}" aria-controls="tab-{key}" '
            f'aria-selected="{"true" if on else "false"}" '
            f'data-tab="{key}" href="{href}" '
            f'style="padding:0.6rem 1.25rem;border-radius:var(--radius-pill);text-decoration:none;font-weight:600;font-size:0.95rem;border:1px solid var(--color-border);{active_style}">'
            f'{TABS[key]}</a>'
        )

    def pane(key: str, body: str) -> str:
        display = "block" if key == active else "none"
        return f'<div id="tab-{key}" class="sport-tab-pane" role="tabpanel" aria-labelledby="tabbtn-{key}" style="display:{display};">{body}</div>'

    calculator_section = f"""
    <section class="sport-calc-section" style="max-width:960px;margin:0 auto 3.5rem;">
        <div class="sport-calc-card" data-sport-calculator data-pricing='{pricing_json}' style="background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-28);padding:2rem 2.5rem;box-shadow:0 8px 30px rgba(0, 0, 0, 0.04);">
            <div style="text-align:center;margin-bottom:2rem;">
                <span style="display:inline-block;padding:0.25rem 0.75rem;border-radius:var(--radius-pill);background:var(--color-accent-light);color:var(--color-accent-text);font-size:0.85rem;font-weight:600;margin-bottom:0.5rem;">Калькулятор тарифа</span>
                <h2 style="font-size:1.85rem;margin:0 0 0.5rem;color:var(--color-heading);">Сколько стоит Руми Спорт для вас?</h2>
                <p style="margin:0;color:var(--color-muted);font-size:1rem;">Выберите формат работы: частный тренер или спортивный клуб с залами.</p>
            </div>

            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:2rem;align-items:start;">
                <!-- Контролы -->
                <div class="sport-calc-controls">
                    <fieldset style="border:none;padding:0;margin:0 0 1.5rem;">
                        <legend style="font-weight:600;margin-bottom:0.75rem;color:var(--color-heading);font-size:0.95rem;">Формат работы</legend>
                        <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
                            <label style="display:flex;align-items:center;gap:0.5rem;padding:0.75rem 1rem;border:1px solid var(--color-border);border-radius:var(--radius-16);cursor:pointer;flex:1;min-width:140px;background:var(--color-surface-alt);">
                                <input type="radio" name="sport-role" value="coach">
                                <span style="font-weight:500;">Я отдельный тренер</span>
                            </label>
                            <label style="display:flex;align-items:center;gap:0.5rem;padding:0.75rem 1rem;border:2px solid var(--color-primary);border-radius:var(--radius-16);cursor:pointer;flex:1;min-width:140px;background:var(--color-surface);" class="is-selected">
                                <input type="radio" name="sport-role" value="gym" checked>
                                <span style="font-weight:600;color:var(--color-heading);">Спортзал / сеть</span>
                            </label>
                        </div>
                    </fieldset>

                    <div id="sport-venue-wrap" style="margin-bottom:1.5rem;">
                        <label for="sport-venues-count" style="display:block;font-weight:600;margin-bottom:0.5rem;color:var(--color-heading);font-size:0.95rem;">
                            Сколько залов или филиалов у вас?
                        </label>
                        <div style="display:flex;align-items:center;gap:0.5rem;">
                            <button type="button" data-venue-step="-1" style="width:44px;height:44px;border-radius:var(--radius-16);border:1px solid var(--color-border);background:var(--color-surface);font-size:1.3rem;cursor:pointer;font-weight:600;display:flex;align-items:center;justify-content:center;color:var(--color-heading);">−</button>
                            <input id="sport-venues-count" type="number" min="1" max="100" value="1" inputmode="numeric" style="width:90px;height:44px;text-align:center;font-size:1.15rem;font-weight:700;border:1px solid var(--color-border);border-radius:var(--radius-16);background:var(--color-surface);color:var(--color-heading);">
                            <button type="button" data-venue-step="1" style="width:44px;height:44px;border-radius:var(--radius-16);border:1px solid var(--color-border);background:var(--color-surface);font-size:1.3rem;cursor:pointer;font-weight:600;display:flex;align-items:center;justify-content:center;color:var(--color-heading);">+</button>
                            <span style="font-size:0.9rem;color:var(--color-muted);margin-left:0.5rem;">филиалов</span>
                        </div>
                        <p style="margin:0.5rem 0 0;font-size:0.85rem;color:var(--color-muted);">
                            1 зал — {SPORT_GYM_BASE_MONTHLY_PRICE:,} ₽/мес, каждый следующий зал — +{SPORT_ADDITIONAL_VENUE_PRICE:,} ₽/мес.
                        </p>
                    </div>

                    <div style="background:var(--color-surface-alt);border-radius:var(--radius-16);padding:1rem 1.25rem;font-size:0.9rem;color:var(--color-text);line-height:1.5;">
                        <p style="margin:0 0 0.5rem;font-weight:600;color:var(--color-heading);">Что включено в сервис:</p>
                        <ul style="margin:0;padding-left:1.25rem;">
                            <li>Онлайн-расписание и запись клиентов</li>
                            <li>Команда тренеров и индивидуальные слоты</li>
                            <li>Учёт абонементов и платежей клиентов</li>
                            <li>Календарь закрытий и отпусков</li>
                            <li>Расчёт зарплат и комиссий тренеров</li>
                            <li>Первые 14 дней бесплатно для всех</li>
                        </ul>
                    </div>
                </div>

                <!-- Результат расчёта -->
                <div class="sport-calc-result" style="background:var(--color-surface-alt);border:1px solid var(--color-border);border-radius:var(--radius-28);padding:2rem;text-align:center;">
                    <span style="font-size:0.9rem;text-transform:uppercase;letter-spacing:0.05em;color:var(--color-muted);display:block;margin-bottom:0.25rem;">Стоимость платформы</span>
                    <div style="margin:0.5rem 0;">
                        <span id="sport-calc-price" style="font-size:2.5rem;font-weight:800;color:var(--color-heading);line-height:1;">3 500 ₽</span>
                        <span id="sport-calc-period" style="font-size:1.1rem;color:var(--color-muted);font-weight:500;">/мес</span>
                    </div>
                    <p id="sport-calc-desc" style="font-size:0.95rem;color:var(--color-text);margin:0.75rem 0 1.5rem;min-height:2.6em;">
                        1 спортзал со всей командой тренеров и расписанием.
                    </p>

                    <a id="sport-calc-cta" href="/sport/business/register-gym" class="btn-primary" style="display:block;width:100%;padding:0.9rem 1.25rem;text-align:center;border-radius:var(--radius-16);text-decoration:none;font-weight:700;font-size:1.05rem;background:var(--color-primary);color:var(--color-btn-text);">
                        Подключить клуб {ICON_ARROW_RIGHT}
                    </a>

                    <div id="sport-custom-box" style="display:none;margin-top:1.5rem;padding-top:1.25rem;border-top:1px dashed var(--color-border);text-align:left;">
                        <p style="font-weight:600;font-size:0.95rem;color:var(--color-heading);margin:0 0 0.5rem;">Крупная сеть или спецусловия?</p>
                        <p style="font-size:0.85rem;color:var(--color-muted);margin:0 0 1rem;">Мы можем закрепить за вашей сетью персональный фиксированный тариф через модератор-панель.</p>
                        <a href="/sport/business" style="display:inline-block;padding:0.5rem 1rem;border:1px solid var(--color-border);border-radius:var(--radius-16);background:var(--color-surface);font-size:0.85rem;font-weight:600;text-decoration:none;color:var(--color-heading);">Запросить спецусловия →</a>
                    </div>
                </div>
            </div>
        </div>
    </section>
    """.replace("{SPORT_GYM_BASE_MONTHLY_PRICE:,}", f"{SPORT_GYM_BASE_MONTHLY_PRICE:,}".replace(",", " ")).replace("{SPORT_ADDITIONAL_VENUE_PRICE:,}", f"{SPORT_ADDITIONAL_VENUE_PRICE:,}".replace(",", " "))

    plans_cards = f"""
    <div style="max-width:1100px;margin:0 auto 3rem;">
        <div style="text-align:center;margin-bottom:2rem;">
            <h2 style="font-size:1.75rem;margin:0 0 0.5rem;color:var(--color-heading);">Тарифные планы платформы</h2>
            <p style="margin:0;color:var(--color-muted);">Прозрачные условия без скрытых комиссий с оплат тренировок.</p>
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(240px, 1fr));gap:1.5rem;align-items:stretch;">
            <!-- Тренер -->
            <article style="background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-28);padding:1.75rem;display:flex;flex-direction:column;justify-content:space-between;">
                <div>
                    <h3 style="font-size:1.25rem;margin:0 0 0.25rem;color:var(--color-heading);">Тренер</h3>
                    <p style="font-size:0.85rem;color:var(--color-muted);margin:0 0 1rem;">Для частных и персональных инструкторов</p>
                    <div style="margin-bottom:1.25rem;">
                        <span style="font-size:2rem;font-weight:800;color:var(--color-heading);">{SPORT_COACH_MONTHLY_PRICE} ₽</span>
                        <span style="color:var(--color-muted);font-size:0.9rem;">/мес</span>
                    </div>
                    <ul style="list-style:none;padding:0;margin:0 0 1.5rem;font-size:0.9rem;line-height:1.7;color:var(--color-text);">
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>1 персональный профиль</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Индивидуальные слоты и окна</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Календарь отпусков и закрытий</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Отзывы и клиентский рейтинг</span></li>
                    </ul>
                </div>
                <a href="/sport/business/register-gym" style="display:block;text-align:center;padding:0.75rem;border-radius:var(--radius-16);border:1px solid var(--color-border);text-decoration:none;font-weight:600;color:var(--color-heading);">Подключить</a>
            </article>

            <!-- Спортивный клуб -->
            <article style="background:var(--color-surface);border:2px solid var(--color-primary);border-radius:var(--radius-28);padding:1.75rem;display:flex;flex-direction:column;justify-content:space-between;position:relative;">
                <span style="position:absolute;top:-12px;right:20px;background:var(--color-primary);color:var(--color-btn-text);font-size:0.75rem;font-weight:700;padding:0.25rem 0.65rem;border-radius:var(--radius-pill);text-transform:uppercase;">Популярный</span>
                <div>
                    <h3 style="font-size:1.25rem;margin:0 0 0.25rem;color:var(--color-heading);">Спортивный клуб</h3>
                    <p style="font-size:0.85rem;color:var(--color-muted);margin:0 0 1rem;">1 зал и вся команда тренеров</p>
                    <div style="margin-bottom:1.25rem;">
                        <span style="font-size:2rem;font-weight:800;color:var(--color-heading);">{f"{SPORT_GYM_BASE_MONTHLY_PRICE:,}".replace(",", " ")} ₽</span>
                        <span style="color:var(--color-muted);font-size:0.9rem;">/мес</span>
                    </div>
                    <ul style="list-style:none;padding:0;margin:0 0 1.5rem;font-size:0.9rem;line-height:1.7;color:var(--color-text);">
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>1 основной зал/филиал</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Неограниченно тренеров</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Групповые и персональные тренировки</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Абонементы и аналитика выручки</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Расчёт зарплат и комиссий</span></li>
                    </ul>
                </div>
                <a href="/sport/business/register-gym" style="display:block;text-align:center;padding:0.75rem;border-radius:var(--radius-16);background:var(--color-primary);color:var(--color-btn-text);text-decoration:none;font-weight:600;">Подключить клуб</a>
            </article>

            <!-- Спортивная сеть -->
            <article style="background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-28);padding:1.75rem;display:flex;flex-direction:column;justify-content:space-between;">
                <div>
                    <h3 style="font-size:1.25rem;margin:0 0 0.25rem;color:var(--color-heading);">Спортивная сеть</h3>
                    <p style="font-size:0.85rem;color:var(--color-muted);margin:0 0 1rem;">От 2 залов и филиалов</p>
                    <div style="margin-bottom:1.25rem;">
                        <span style="font-size:2rem;font-weight:800;color:var(--color-heading);">от 6 000 ₽</span>
                        <span style="color:var(--color-muted);font-size:0.9rem;">/мес</span>
                    </div>
                    <ul style="list-style:none;padding:0;margin:0 0 1.5rem;font-size:0.9rem;line-height:1.7;color:var(--color-text);">
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>3 500 ₽ + 2 500 ₽ за каждый доп. зал</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Мульти-залы и филиалы бренда</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Роль управляющего (manager)</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Сводная отчётность по сети</span></li>
                    </ul>
                </div>
                <a href="/sport/business/register-gym" style="display:block;text-align:center;padding:0.75rem;border-radius:var(--radius-16);border:1px solid var(--color-border);text-decoration:none;font-weight:600;color:var(--color-heading);">Подключить сеть</a>
            </article>

            <!-- Индивидуальный -->
            <article style="background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-28);padding:1.75rem;display:flex;flex-direction:column;justify-content:space-between;">
                <div>
                    <h3 style="font-size:1.25rem;margin:0 0 0.25rem;color:var(--color-heading);">Индивидуальный</h3>
                    <p style="font-size:0.85rem;color:var(--color-muted);margin:0 0 1rem;">Для крупных клубов и франшиз</p>
                    <div style="margin-bottom:1.25rem;">
                        <span style="font-size:1.7rem;font-weight:800;color:var(--color-heading);">По запросу</span>
                    </div>
                    <ul style="list-style:none;padding:0;margin:0 0 1.5rem;font-size:0.9rem;line-height:1.7;color:var(--color-text);">
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Закрепление фиксированного тарифа</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Индивидуальный расчёт модератором</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Персональный менеджер и SLA</span></li>
                        <li style="display:flex;align-items:center;gap:0.5rem;">{ICON_CIRCLE_CHECK} <span>Интеграции со СКУД и кассами</span></li>
                    </ul>
                </div>
                <a href="/sport/business" style="display:block;text-align:center;padding:0.75rem;border-radius:var(--radius-16);border:1px solid var(--color-border);text-decoration:none;font-weight:600;color:var(--color-heading);">Запросить условия</a>
            </article>
        </div>
    </div>
    """

    plans_body = f"{calculator_section}\n{plans_cards}"
    guides_body = f'<div style="max-width:800px;margin:0 auto;"><div class="settings-accordion">{_sport_accordion_html(_SPORT_INSTRUCTIONS)}</div></div>'

    client_script = """
    <script>
    (function() {
        const card = document.querySelector('[data-sport-calculator]');
        if (!card) return;
        const pricing = JSON.parse(card.dataset.pricing || '{}');
        const roleInputs = card.querySelectorAll('input[name="sport-role"]');
        const venueWrap = document.getElementById('sport-venue-wrap');
        const countInput = document.getElementById('sport-venues-count');
        const priceEl = document.getElementById('sport-calc-price');
        const periodEl = document.getElementById('sport-calc-period');
        const descEl = document.getElementById('sport-calc-desc');
        const ctaEl = document.getElementById('sport-calc-cta');
        const customBox = document.getElementById('sport-custom-box');

        function formatMoney(n) {
            return n.toLocaleString('ru-RU') + ' ₽';
        }

        function update() {
            const role = card.querySelector('input[name="sport-role"]:checked').value;
            const count = Math.max(1, parseInt(countInput.value, 10) || 1);

            roleInputs.forEach(r => {
                const label = r.closest('label');
                if (r.checked) {
                    label.style.borderColor = 'var(--color-primary)';
                    label.style.borderWidth = '2px';
                    label.style.background = 'var(--color-surface)';
                } else {
                    label.style.borderColor = 'var(--color-border)';
                    label.style.borderWidth = '1px';
                    label.style.background = 'var(--color-surface-alt)';
                }
            });

            if (role === 'coach') {
                venueWrap.style.display = 'none';
                priceEl.textContent = formatMoney(399);
                periodEl.textContent = '/мес';
                descEl.textContent = 'Тариф для отдельного тренера: личный профиль, расписание индивидуальных тренировок и приём записей.';
                ctaEl.textContent = 'Подключиться как тренер →';
                ctaEl.href = '/sport/business/register-gym';
                if (customBox) customBox.style.display = 'none';
            } else {
                venueWrap.style.display = 'block';
                if (count >= 15) {
                    priceEl.textContent = 'Индивидуально';
                    periodEl.textContent = '';
                    descEl.textContent = 'Для крупных сетей от 15 залов мы предлагаем индивидуальные договорные условия и интеграции.';
                    ctaEl.textContent = 'Запросить условия →';
                    ctaEl.href = '/sport/business';
                    if (customBox) customBox.style.display = 'block';
                } else {
                    const basePrice = 3500;
                    const addPrice = 2500;
                    const total = count === 1 ? basePrice : basePrice + (count - 1) * addPrice;
                    priceEl.textContent = formatMoney(total);
                    periodEl.textContent = '/мес';
                    if (count === 1) {
                        descEl.textContent = '1 спортзал со всей командой тренеров, групповыми занятиями и расписанием.';
                    } else {
                        descEl.textContent = 'Сеть из ' + count + ' залов: 3 500 ₽ за основной зал + ' + (count - 1) + ' × 2 500 ₽ за филиалы.';
                    }
                    ctaEl.textContent = count === 1 ? 'Подключить клуб →' : 'Подключить сеть (' + count + ' залов) →';
                    ctaEl.href = '/sport/business/register-gym';
                    if (customBox) customBox.style.display = count >= 5 ? 'block' : 'none';
                }
            }
        }

        roleInputs.forEach(input => input.addEventListener('change', update));
        if (countInput) {
            countInput.addEventListener('input', update);
            countInput.addEventListener('change', function() {
                const val = parseInt(this.value, 10);
                this.value = (Number.isInteger(val) && val >= 1) ? val : 1;
                update();
            });
        }
        card.querySelectorAll('[data-venue-step]').forEach(btn => {
            btn.addEventListener('click', function() {
                const step = parseInt(this.dataset.venueStep, 10);
                const cur = parseInt(countInput.value, 10) || 1;
                countInput.value = Math.max(1, Math.min(100, cur + step));
                update();
            });
        });

        // Tab switcher without full page reload if JS enabled
        document.querySelectorAll('.sport-tab-link').forEach(link => {
            link.addEventListener('click', function(e) {
                const tab = this.dataset.tab;
                if (!tab) return;
                e.preventDefault();
                history.pushState(null, '', this.getAttribute('href'));
                document.querySelectorAll('.sport-tab-link').forEach(l => {
                    l.style.background = 'var(--color-surface)';
                    l.style.color = 'var(--color-text)';
                    l.setAttribute('aria-selected', 'false');
                });
                this.style.background = 'var(--color-primary)';
                this.style.color = 'var(--color-btn-text)';
                this.setAttribute('aria-selected', 'true');
                document.querySelectorAll('.sport-tab-pane').forEach(p => p.style.display = 'none');
                const target = document.getElementById('tab-' + tab);
                if (target) target.style.display = 'block';
            });
        });

        // Accordion headers
        document.querySelectorAll('.accordion-header').forEach(btn => {
            btn.addEventListener('click', function() {
                const body = this.nextElementSibling;
                const chevron = this.querySelector('.accordion-chevron');
                if (!body) return;
                const isHidden = body.style.display === 'none';
                body.style.display = isHidden ? 'block' : 'none';
                if (chevron) chevron.style.transform = isHidden ? 'rotate(180deg)' : '';
            });
        });
    })();
    </script>
    """

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Тарифы платформы — Руми Спорт</title>
    <meta name="description" content="Тарифы для спортивных клубов, фитнес-центров и тренеров на Руми Спорт. Калькулятор стоимости, прозрачные условия без скрытых комиссий.">
    {get_base_styles()}
</head>
<body class="sport-directory rumi-sport">
    {render_header("sport_tariffs", user)}
    <main class="main-content" style="padding-top:5rem;">
        <div class="section-container">
            <header style="text-align:center;margin-bottom:2.5rem;">
                <p class="sport-page-eyebrow" style="color:var(--color-accent-text);font-weight:600;font-size:0.95rem;margin-bottom:0.5rem;">Руми Спорт · тарифы</p>
                <h1 style="font-size:2.25rem;font-weight:800;color:var(--color-heading);margin:0 0 0.75rem;">Тарифы и информация</h1>
                <p style="color:var(--color-muted);font-size:1.1rem;max-width:640px;margin:0 auto;">
                    Прозрачная стоимость сервиса для спортивных клубов, залов и персональных тренеров. Первые 14 дней бесплатно.
                </p>
            </header>

            <nav class="sport-tabs-nav" style="display:flex;justify-content:center;gap:0.75rem;margin-bottom:2.5rem;flex-wrap:wrap;">
                {tab_link("plans")}{tab_link("documents")}{tab_link("guides")}
            </nav>

            {pane("plans", plans_body)}
            {pane("documents", _sport_documents_html())}
            {pane("guides", guides_body)}
        </div>
    </main>
    {render_footer(user, sport=True)}
    {client_script}
</body>
</html>"""
