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
from app.services import panel_guide
from app.web.components.escaping import e
from app.web.components.icons import ICON_CHEVRON_DOWN
from app.web.components.panel_tour import render_restart_link


# Пошаговый гайд «с чего начать» — всегда виден сверху вкладки, отдельно от
# аккордеона: (заголовок шага, где искать — или None, если это не отдельная
# вкладка, текст шага).
_GUIDE_STEPS = [
    ("Основная информация", "вкладка «Редактировать салон»",
     "Укажите название, город, адрес, телефон, почту и описание салона, добавьте хотя бы одно "
     "фото. Без фото и адреса салон не пройдёт модерацию."),
    ("Часы работы", "там же",
     "Настройте, когда салон принимает клиентов — от этого зависит, какое время будет доступно "
     "для записи."),
    ("Мастера и услуги", "вкладки «Сотрудники» и «Услуги»",
     "Добавьте мастеров и услуги, которые они оказывают, с ценами и длительностью."),
    ("Расписание", None,
     "Задайте график работы каждого мастера."),
    ("Модерация", None,
     "Заявку проверит платформа, обычно 1–2 рабочих дня. Пока ждёте, можно продолжать заполнять "
     "салон — это не мешает."),
    ("Тариф", "вкладка «Тариф»",
     "После одобрения выберите тариф. Первые 14 дней бесплатно."),
    ("Публикация", None,
     "Нажмите «Опубликовать салон» в шапке панели. Салон появится в общем каталоге, и клиенты "
     "смогут записываться."),
]


def _guide_html() -> str:
    steps_html = "".join(
        f"""
        <li>
            <strong>{title}</strong>{f' <span class="text-muted">({where})</span>' if where else ''}
            — {text}
        </li>"""
        for title, where, text in _GUIDE_STEPS
    )
    return f"""
    <div class="my-salon-card">
        <h2 class="my-salon-card-title">С чего начать: как заполнить салон</h2>
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
        {_guide_html()}

        <div class="my-salon-card">
            <h2 class="my-salon-card-title">Инструкция по разделам панели</h2>
            <p class="my-salon-card-hint">Короткие подсказки по каждому разделу — нажмите на название, чтобы развернуть.</p>
            <div class="settings-accordion">
                {items_html}
            </div>
        </div>
    </div>"""
