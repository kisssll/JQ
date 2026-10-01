# app/web/pages/business/tabs/instructions.py
"""Вкладка «Инструкция» — краткий пошаговый гайд «с чего начать» (сверху,
всегда виден) + аккордеон «за что отвечает / как пользоваться» по каждому
разделу панели (см. .settings-accordion/.accordion-item — общий компонент,
JS уже глобальный в static/src/js/profile.js, ничего дополнительно
подключать не нужно).

Тексты разделов живут не здесь, а в app/services/panel_guide.py: тот же реестр
читает тур по панели (решение 0008, п. 7), и два описания одного раздела не
должны со временем разойтись. Саму вкладку в заходе 3 не переписывали — она
только начала брать текст оттуда и получила ссылку «пройти знакомство заново».
"""
from app.models.models import SalonPanelMode
from app.services import panel_guide, panel_sections
from app.web.components.escaping import e
from app.web.components.icons import ICON_CHEVRON_DOWN
from app.web.components.panel_tour import render_restart_link


# Пошаговый гайд «с чего начать» — всегда виден сверху вкладки, отдельно от
# аккордеона: (заголовок шага, где искать, текст шага).
#
# «Где искать» — это НЕ строка с названием вкладки, а ключи разделов (или
# SAME_PLACE — «там же»). Название вкладки приходит из panel_sections.label по
# режиму: в соло «Редактировать салон» не существует вовсе, а настройки живут в
# «Моей карточке мастера» (решение 0009, п. 2). Зашитое строкой название стало
# бы прямой ложью — отправило бы человека искать вкладку, которой у него нет.
# Саму вкладку целиком переписывает заход 5; здесь исправлено только это.
SAME_PLACE = ("same",)

_GUIDE_STEPS = [
    ("Основная информация", ("settings",),
     "Укажите название, город, адрес, телефон, почту и описание, добавьте хотя бы одно "
     "фото. Без фото и адреса заявка не пройдёт модерацию."),
    ("Часы работы", SAME_PLACE,
     "Настройте, когда вы принимаете клиентов — от этого зависит, какое время будет доступно "
     "для записи."),
    ("Мастера и услуги", ("employees", "services"),
     "Добавьте мастеров и услуги, которые они оказывают, с ценами и длительностью."),
    ("Расписание", None,
     "Задайте график работы каждого мастера."),
    ("Модерация", None,
     "Заявку проверит платформа, обычно 1–2 рабочих дня. Пока ждёте, можно продолжать "
     "заполнять карточку — это не мешает."),
    ("Тариф", ("billing",),
     "После одобрения выберите тариф. Первые 14 дней бесплатно."),
    ("Публикация", None,
     "Нажмите кнопку публикации в шапке панели — после этого вас увидят в общем каталоге "
     "платформы, и клиенты смогут записываться."),
]


def _where_text(keys, mode: SalonPanelMode) -> str:
    """«Где искать» по ключам разделов и режиму.

    ``settings`` — не раздел, а роль: в команде это «Редактировать салон», в
    соло — «Моя карточка мастера» (panel_sections.settings_key)."""
    if not keys:
        return ""
    if keys == SAME_PLACE:
        return "там же"
    names = [
        panel_sections.label(
            panel_sections.settings_key(mode) if k == "settings" else k, mode,
        )
        for k in keys
    ]
    word = "вкладка" if len(names) == 1 else "вкладки"
    return word + " " + " и ".join(f"«{e(n)}»" for n in names)


def _guide_html(mode: SalonPanelMode) -> str:
    steps_html = ""
    for title, keys, text in _GUIDE_STEPS:
        where = _where_text(keys, mode)
        where_html = f' <span class="text-muted">({where})</span>' if where else ""
        steps_html += f"""
        <li>
            <strong>{title}</strong>{where_html}
            — {text}
        </li>"""
    return f"""
    <div class="my-salon-card">
        <h2 class="my-salon-card-title">С чего начать</h2>
        <ol class="instructions-guide-steps">
            {steps_html}
        </ol>
    </div>"""


def render_instructions_tab(
    *,
    salon_id: int = 0,
    mode: SalonPanelMode = SalonPanelMode.TEAM,
    can_tour: bool = False,
) -> str:
    """Подписи и описания разделов берём из реестра: в соло-режиме первый
    раздел называется «Моя карточка мастера», и справочник обязан называть его
    так же, как панель."""
    items_html = "".join(
        f"""
        <div class="accordion-item">
            <button class="accordion-header">
                <span class="accordion-label">{e(label)}</span>
                <span class="accordion-chevron">{ICON_CHEVRON_DOWN}</span>
            </button>
            <div class="accordion-body">{text}</div>
        </div>"""
        for _slug, label, text in panel_guide.manual_sections(mode)
    )
    # Ссылка на тур — тому, кто его в принципе увидит (см. panel_tour.decide):
    # участнику без права менять салон она ничего бы не открыла.
    restart_html = render_restart_link(salon_id=salon_id) if (can_tour and salon_id) else ""
    return f"""
    <div id="tab-instructions" class="tab-content">
        {restart_html}
        {_guide_html(mode)}

        <div class="my-salon-card">
            <h2 class="my-salon-card-title">Инструкция по разделам панели</h2>
            <p class="my-salon-card-hint">Короткие подсказки по каждому разделу — нажмите на название, чтобы развернуть.</p>
            <div class="settings-accordion">
                {items_html}
            </div>
        </div>
    </div>"""
