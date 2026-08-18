# app/web/components/evening_deal.py
"""Секция «Вечерние окна со скидкой» для бизнес-панели.

Один и тот же блок вставляется во вкладки «Расписание» и «Акции» (панель рендерит
только активную вкладку, поэтому дублирования id в DOM нет). Тумблер/кнопка →
попап точной настройки (скидка, диапазон вечера, дни, услуги). Самодостаточно:
инлайновый скрипт ходит в /api/v1/business/my-salon/evening-deal (GET/POST)."""
import html
import json
from app.web.components.icons import (
    ICON_MOON,
)

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def render_evening_deal_section(salon, services, deal: dict) -> str:
    enabled = deal.get("enabled")
    disc = deal.get("discount_percent", 0)
    ev_from = deal.get("evening_from", "17:00")
    ev_to = deal.get("evening_to", "21:00")

    if enabled:
        summary = f"Скидка {disc}% на вечерние окна {ev_from}–{ev_to}"
        primary = f'<button type="button" class="btn-outline" onclick="openEveningDealModal()">Изменить</button>'
        off_btn = '<button type="button" class="btn-outline" onclick="disableEveningDeal()" style="color:#dc2626;border-color:#dc2626">Выключить</button>'
    else:
        summary = "Выключено — салон не участвует в подборке вечерних окон"
        primary = '<button type="button" class="btn-primary" onclick="openEveningDealModal()">Включить вечерние скидки</button>'
        off_btn = ""

    weekday_boxes = "".join(
        f'<label class="ed-day"><input type="checkbox" class="ed-weekday" value="{i}"> {name}</label>'
        for i, name in enumerate(WEEKDAYS_RU)
    )
    service_boxes = "".join(
        f'<label class="ed-svc-opt"><input type="checkbox" class="ed-service" value="{s.id}"> {html.escape(s.name)}</label>'
        for s in services
    ) or '<p class="text-muted" style="font-size:.85rem">В салоне пока нет услуг</p>'

    deal_json = html.escape(json.dumps(deal, ensure_ascii=True), quote=True)

    return f"""
    <div class="my-salon-card evening-deal-block" data-salon-id="{salon.id}" data-deal="{deal_json}">
        <h2 class="my-salon-card-title">{ICON_MOON} Вечерние окна со скидкой</h2>
        <p class="my-salon-card-hint">
            Свободные вечерние слоты на сегодня попадут в публичную подборку со скидкой,
            а клиентам уйдёт напоминание в Telegram. Скидка применится автоматически при записи.
        </p>
        <p id="eveningDealStatus" style="margin:.5rem 0;font-weight:600">{summary}</p>
        <div style="display:flex;gap:.6rem;flex-wrap:wrap">{primary}{off_btn}</div>

        <div id="eveningDealModal" class="ed-modal" style="display:none">
            <div class="ed-modal-inner">
                <h3 style="margin-top:0">Настройка вечерних скидок</h3>
                <label class="ed-field">Скидка, %
                    <input type="number" id="edDiscount" min="1" max="99" value="{disc or 15}">
                </label>
                <div class="ed-field-row">
                    <label class="ed-field">Вечер с
                        <input type="time" id="edFrom" value="{ev_from}">
                    </label>
                    <label class="ed-field">до
                        <input type="time" id="edTo" value="{ev_to}">
                    </label>
                </div>
                <div class="ed-field">
                    <span>Дни недели (пусто = все дни)</span>
                    <div class="ed-days">{weekday_boxes}</div>
                </div>
                <div class="ed-field">
                    <span>Услуги со скидкой (пусто = все)</span>
                    <div class="ed-svc-list">{service_boxes}</div>
                </div>
                <p id="edError" style="color:#dc2626;font-size:.85rem;display:none"></p>
                <div style="display:flex;gap:.6rem;justify-content:flex-end;margin-top:1rem">
                    <button type="button" class="btn-outline" onclick="closeEveningDealModal()">Отмена</button>
                    <button type="button" class="btn-primary" onclick="saveEveningDeal()">Сохранить</button>
                </div>
            </div>
        </div>
    </div>

    <style>
    .ed-modal{{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;display:flex;align-items:center;justify-content:center;padding:1rem}}
    .ed-modal-inner{{background:var(--color-surface,#fff);border-radius:1rem;padding:1.5rem;max-width:460px;width:100%;max-height:90vh;overflow:auto}}
    .ed-field{{display:block;margin:.7rem 0;font-weight:600}}
    .ed-field input[type=number],.ed-field input[type=time]{{display:block;margin-top:.3rem;padding:.4rem .6rem;border:1px solid var(--color-border,#ddd);border-radius:.5rem}}
    .ed-field-row{{display:flex;gap:1rem}}
    .ed-days{{display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.4rem;font-weight:400}}
    .ed-day{{display:flex;align-items:center;gap:.2rem}}
    .ed-svc-list{{display:flex;flex-direction:column;gap:.3rem;margin-top:.4rem;font-weight:400;max-height:180px;overflow:auto}}
    </style>

    <script>
    (function() {{
        var block = document.querySelector('.evening-deal-block');
        if (!block || block.dataset.edBound) return;
        block.dataset.edBound = '1';
        var salonId = block.dataset.salonId;

        window.openEveningDealModal = async function() {{
            try {{
                var res = await fetch('/api/v1/business/my-salon/evening-deal?salon_id=' + salonId);
                if (res.ok) {{
                    var d = await res.json();
                    document.getElementById('edDiscount').value = d.discount_percent || 15;
                    document.getElementById('edFrom').value = d.evening_from || '17:00';
                    document.getElementById('edTo').value = d.evening_to || '21:00';
                    document.querySelectorAll('.ed-weekday').forEach(function(cb) {{ cb.checked = (d.weekdays || []).indexOf(parseInt(cb.value)) >= 0; }});
                    document.querySelectorAll('.ed-service').forEach(function(cb) {{ cb.checked = (d.service_ids || []).indexOf(parseInt(cb.value)) >= 0; }});
                }}
            }} catch (e) {{}}
            document.getElementById('edError').style.display = 'none';
            document.getElementById('eveningDealModal').style.display = 'flex';
        }};
        window.closeEveningDealModal = function() {{
            document.getElementById('eveningDealModal').style.display = 'none';
        }};
        window.saveEveningDeal = async function() {{
            var body = {{
                enabled: true,
                discount_percent: parseInt(document.getElementById('edDiscount').value) || 0,
                evening_from: document.getElementById('edFrom').value,
                evening_to: document.getElementById('edTo').value,
                weekdays: Array.from(document.querySelectorAll('.ed-weekday:checked')).map(function(c){{return parseInt(c.value);}}),
                service_ids: Array.from(document.querySelectorAll('.ed-service:checked')).map(function(c){{return parseInt(c.value);}})
            }};
            try {{
                var res = await fetch('/api/v1/business/my-salon/evening-deal?salon_id=' + salonId, {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)
                }});
                if (res.ok) {{ window.location.reload(); return; }}
                var err = await res.json().catch(function(){{return {{}};}});
                var el = document.getElementById('edError');
                el.textContent = err.detail || 'Не удалось сохранить';
                el.style.display = 'block';
            }} catch (e) {{
                var el2 = document.getElementById('edError');
                el2.textContent = 'Ошибка сети, попробуйте ещё раз';
                el2.style.display = 'block';
            }}
        }};
        window.disableEveningDeal = async function() {{
            if (!confirm('Выключить вечерние скидки? Салон перестанет попадать в подборку.')) return;
            try {{
                var res = await fetch('/api/v1/business/my-salon/evening-deal?salon_id=' + salonId, {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{enabled: false, discount_percent: 0}})
                }});
                if (res.ok) window.location.reload();
            }} catch (e) {{}}
        }};
    }})();
    </script>
    """
