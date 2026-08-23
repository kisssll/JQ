# app/web/components/evening_deal.py
"""Секция «Вечерние окна со скидкой» для бизнес-панели.

Один и тот же блок вставляется во вкладки «Расписание» и «Акции» (панель
рендерит только активную вкладку, поэтому дублирования id в DOM нет).

Раньше здесь жили инлайновые <style> и <script>: собственная модалка мимо
общего диалога, системный confirm(), хардкод-цвета (#dc2626, #ddd,
rgba(0,0,0,.45)) и семь чекбоксов дней в одну строку. Оформление переехало в
static/src/css/business/evening-deal.css, поведение — в
static/src/js/business/evening-deal.js.
"""
import html
import json

from app.web.components.icons import ICON_MOON

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def render_evening_deal_section(salon, services, deal: dict) -> str:
    enabled = bool(deal.get("enabled"))
    disc = deal.get("discount_percent", 0)
    ev_from = deal.get("evening_from", "17:00")
    ev_to = deal.get("evening_to", "21:00")

    if enabled:
        status = (
            f'<span class="ed-status is-on">Включено</span>'
            f'<span class="ed-status-detail">скидка {disc}% на окна {ev_from}–{ev_to}</span>'
        )
        actions = (
            '<button type="button" class="btn-outline ed-btn" data-ed-open>Изменить</button>'
            '<button type="button" class="btn-outline ed-btn is-danger" data-ed-disable>Выключить</button>'
        )
    else:
        status = (
            '<span class="ed-status is-off">Выключено</span>'
            '<span class="ed-status-detail">салон не участвует в подборке вечерних окон</span>'
        )
        actions = '<button type="button" class="btn-primary ed-btn" data-ed-open>Включить</button>'

    # Дни — чипы-переключатели, а не семь чекбоксов в строку: так видно,
    # что выбрано, и попасть по ним можно пальцем.
    weekday_chips = "".join(
        f'<label class="ed-day"><input type="checkbox" class="ed-weekday" value="{i}">'
        f'<span>{name}</span></label>'
        for i, name in enumerate(WEEKDAYS_RU)
    )
    if services:
        service_boxes = "".join(
            f'<label class="ed-service-item">'
            f'<input type="checkbox" class="ed-service" value="{s.id}">'
            f'<span>{html.escape(s.name)}</span></label>'
            for s in services
        )
    else:
        service_boxes = '<p class="ed-empty">В салоне пока нет услуг</p>'

    deal_json = html.escape(json.dumps(deal, ensure_ascii=True), quote=True)

    return f"""
    <section class="my-salon-card evening-deal-block" data-salon-id="{salon.id}" data-deal="{deal_json}">
        <h2 class="my-salon-card-title">{ICON_MOON} Вечерние окна со скидкой</h2>
        <p class="my-salon-card-hint">
            Свободные вечерние слоты на сегодня попадут в публичную подборку со скидкой,
            а клиентам уйдёт напоминание. Скидка применится автоматически при записи.
        </p>
        <div class="ed-summary" id="eveningDealStatus">{status}</div>
        <div class="ed-actions">{actions}</div>

        <div id="eveningDealModal" class="ed-modal" hidden>
            <div class="ed-modal-box" role="dialog" aria-modal="true" aria-labelledby="edModalTitle">
                <h3 class="ed-modal-title" id="edModalTitle">Настройка вечерних скидок</h3>
                <p class="ed-modal-sub">Пустые поля «дни» и «услуги» означают «все».</p>

                <div class="ed-grid">
                    <label class="ed-field">
                        <span class="ed-label">Размер скидки</span>
                        <span class="ed-input-suffix">
                            <input type="number" id="edDiscount" min="1" max="99" value="{disc or 15}">
                            <span class="ed-suffix">%</span>
                        </span>
                    </label>

                    <div class="ed-field">
                        <span class="ed-label">Вечернее время</span>
                        <span class="ed-time-range">
                            <input type="time" id="edFrom" value="{ev_from}" aria-label="Начало вечера">
                            <span class="ed-dash">—</span>
                            <input type="time" id="edTo" value="{ev_to}" aria-label="Конец вечера">
                        </span>
                    </div>
                </div>

                <div class="ed-field">
                    <span class="ed-label">Дни недели</span>
                    <div class="ed-days">{weekday_chips}</div>
                </div>

                <div class="ed-field">
                    <span class="ed-label">Услуги со скидкой</span>
                    <div class="ed-service-list">{service_boxes}</div>
                </div>

                <p id="edError" class="ed-error" hidden></p>

                <div class="ed-modal-actions">
                    <button type="button" class="btn-outline ed-btn" data-ed-close>Отмена</button>
                    <button type="button" class="btn-primary ed-btn" data-ed-save>Сохранить</button>
                </div>
            </div>
        </div>
    </section>
    """
