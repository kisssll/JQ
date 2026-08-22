# app/web/pages/business/tabs/instructions.py
"""Вкладка «Инструкция» — краткие подсказки по каждому разделу бизнес-панели,
аккордеон (см. .settings-accordion/.accordion-item — общий компонент, JS уже
глобальный в static/src/js/profile.js, ничего дополнительно подключать не
нужно). Тексты — заглушки, наполняются по мере того, как их продиктуют."""
from app.web.components.icons import ICON_CHEVRON_DOWN

# (slug раздела как в tab_buttons, название для пользователя, текст инструкции)
_PLACEHOLDER = "Инструкция появится здесь."
_SECTIONS = [
    ("overview", "Обзор", _PLACEHOLDER),
    ("analytics", "Аналитика", _PLACEHOLDER),
    ("schedule", "Расписание", _PLACEHOLDER),
    ("employees", "Сотрудники", _PLACEHOLDER),
    ("services", "Услуги", _PLACEHOLDER),
    ("payroll", "Зарплаты", _PLACEHOLDER),
    ("cost", "Себестоимость", _PLACEHOLDER),
    ("records", "Записи", _PLACEHOLDER),
    ("warehouse", "Склад", _PLACEHOLDER),
    ("models", "Модели", _PLACEHOLDER),
    ("promos", "Акции", _PLACEHOLDER),
    ("reviews", "Отзывы", _PLACEHOLDER),
    ("crm", "Клиенты", _PLACEHOLDER),
    ("billing", "Тариф", _PLACEHOLDER),
    ("edit", "Редактировать салон", _PLACEHOLDER),
]


def render_instructions_tab() -> str:
    items_html = "".join(
        f"""
        <div class="accordion-item">
            <button class="accordion-header">
                <span class="accordion-label">{label}</span>
                <span class="accordion-chevron">{ICON_CHEVRON_DOWN}</span>
            </button>
            <div class="accordion-body"><p>{text}</p></div>
        </div>"""
        for _slug, label, text in _SECTIONS
    )
    return f"""
    <div id="tab-instructions" class="tab-content">
        <div class="my-salon-card">
            <h2 class="my-salon-card-title">Инструкция по бизнес-панели</h2>
            <p class="my-salon-card-hint">Короткие подсказки по каждому разделу — нажмите на название, чтобы развернуть.</p>
            <div class="settings-accordion">
                {items_html}
            </div>
        </div>
    </div>"""
