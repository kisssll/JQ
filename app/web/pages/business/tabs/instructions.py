# app/web/pages/business/tabs/instructions.py
"""Вкладка «Инструкция» — справочник по панели (решение 0009, п. 7, заход 5).

Что здесь изменилось и почему. Раньше это был аккордеон из пятнадцати ящиков:
чтобы охватить картину целиком, его надо было раскрыть пятнадцать раз, а текст
внутри был устроен как справка к программе («за что отвечает / как
пользоваться»). Вкладку открывали два раза за двадцать пять дней.

Теперь это страница по образцу лендинга: короткое оглавление сверху и открытые
секции под ним, четырьмя группами по целям. У каждой секции свой якорь —
ссылкой на конкретный пункт можно ответить в поддержке, вставить её в письмо
или отдать из бота. Внутри секции порядок один и тот же: зачем это вам → что
здесь сделать → где это, живой ссылкой в сам раздел панели.

После захода 3 первое обучение берёт на себя тур, поэтому здесь не учебник, а
справочник: сюда приходят на третьем месяце с вопросом «как закрыть дату».
Порядок секций совпадает с порядком тура намеренно — человек ищет раздел там,
где его запомнил.

Тексты живут не здесь, а в app/services/panel_guide.py: тот же реестр читает
тур (решение 0008, п. 7), и два описания одного раздела не должны со временем
разойтись. Названия разделов приходят из panel_sections.label по режиму —
зашитое строкой название отправило бы человека искать вкладку, которой у него
нет.

Картинок здесь нет намеренно (решение 0009, п. 7–8): через неделю-две
начинается переделка фронта целиком, и любая картинка умрёт вместе с ним, а
текст переживёт. Схемы пути с /tariffs не переиспользованы по другой причине —
они говорят «салон», а в соло-режиме салона у человека нет.
"""
from typing import Iterable, Optional

from app.models.models import SalonPanelMode
from app.services import panel_guide, panel_sections
from app.web.components.escaping import e
from app.web.components.panel_tour import render_restart_link


def _tab_href(salon_id: int, slug: str, anchor: Optional[str] = None,
              tour_on: bool = False) -> str:
    """Ссылка в раздел панели.

    Пока идёт знакомство, к ссылке подклеивается tour=on — тем же приёмом, что
    в самой панели (dashboard._tab_href): человек вправе уйти из справочника в
    раздел прямо посреди шага, и полоса тура не должна от этого исчезнуть.
    """
    tail = "&tour=on" if tour_on else ""
    hash_part = f"#{anchor}" if anchor else ""
    return f"/business/dashboard?salon_id={salon_id}&tab={slug}{tail}{hash_part}"


def _where_html(section, salon_id: int, tour_on: bool) -> str:
    """«Где это» — живые ссылки в раздел панели.

    Ссылок больше одной там, где раздел состоит из групп и описание говорит про
    обе: в соло «Моя карточка мастера» вобрала настройки салона, и вести в
    начало длинного раздела, когда речь про нижнюю половину, бессмысленно.
    """
    links = " · ".join(
        f'<a class="instructions-where-link" '
        f'href="{_tab_href(salon_id, t.tab, t.anchor, tour_on)}">{e(t.caption)}</a>'
        for t in section.targets
    )
    return f'<p class="instructions-where"><span>Где это:</span> {links}</p>'


def _start_html(mode: SalonPanelMode, salon_id: int, visible: frozenset,
                tour_on: bool) -> str:
    """«С чего начать» — порядок заполнения текстом, с живыми ссылками.

    Живого чек-листа здесь нет намеренно: тот считает состояние из базы и это
    отдельная задача (решение 0009, «Нумерация»). Половина чек-листа — галочки,
    которые ничего не знают, — хуже честного текста.
    """
    steps_html = ""
    for title, keys, text in panel_guide.start_steps(mode):
        where = _where_links(keys, mode, salon_id, visible, tour_on)
        where_html = f' <span class="text-muted">({where})</span>' if where else ""
        steps_html += f"""
        <li>
            <strong>{e(title)}</strong>{where_html}
            — {e(text)}
        </li>"""
    return f"""
    <section class="my-salon-card instructions-section" id="manual-start">
        <h2 class="my-salon-card-title">С чего начать</h2>
        <p class="instructions-why">Пока не сделан каждый из этих шагов, записаться
            к вам нельзя — ни по ссылке, ни из общей ленты.</p>
        <ol class="instructions-guide-steps">
            {steps_html}
        </ol>
    </section>"""


def _where_links(keys, mode: SalonPanelMode, salon_id: int, visible: frozenset,
                 tour_on: bool) -> str:
    """«Где искать» для шага гайда: названия разделов живыми ссылками.

    ``settings`` — не раздел, а роль: в команде это «Редактировать салон», в
    соло — «Моя карточка мастера» (panel_sections.settings_key). Раздел, которого
    у человека нет, ссылкой не становится: такая ссылка молча вернула бы его в
    «Обзор».
    """
    if not keys:
        return ""
    if keys == panel_guide.SAME_PLACE:
        return "там же"
    out = []
    for key in keys:
        slug = panel_sections.settings_key(mode) if key == "settings" else key
        name = e(panel_sections.label(slug, mode))
        if slug in visible:
            out.append(
                f'<a class="instructions-where-link" '
                f'href="{_tab_href(salon_id, slug, None, tour_on)}">«{name}»</a>'
            )
        else:
            out.append(f"«{name}»")
    word = "вкладка" if len(out) == 1 else "вкладки"
    return word + " " + " и ".join(out)


def _toc_html(groups) -> str:
    """Оглавление: группы с вложенными ссылками на секции.

    Нужно не для красоты. Открытых секций на странице полтора десятка, и без
    оглавления человек, который пришёл с одним вопросом, скроллит весь
    справочник. Заголовок группы — тоже ссылка: им делятся, когда речь про
    целую цель, а не про один раздел.
    """
    blocks = ""
    for group in groups:
        items = "".join(
            f'<li><a href="#{s.slug}">{e(s.label)}</a></li>' for s in group.sections
        )
        blocks += f"""
        <div class="instructions-toc-group">
            <a class="instructions-toc-title" href="#{group.slug}">{e(group.title)}</a>
            <ul>{items}</ul>
        </div>"""
    # «С чего начать» стоит над сеткой, а не в ней: это один пункт, и в колонке
    # рядом с группами из четырёх ссылок он оставлял бы пустую клетку в треть
    # ширины.
    return f"""
    <nav class="instructions-toc" aria-label="Содержание справочника">
        <a class="instructions-toc-first" href="#manual-start">С чего начать</a>
        <div class="instructions-toc-grid">{blocks}</div>
    </nav>"""


def render_instructions_tab(
    *,
    salon_id: int = 0,
    mode: SalonPanelMode = SalonPanelMode.TEAM,
    can_tour: bool = False,
    visible_keys: Optional[Iterable[str]] = None,
    tour_on: bool = False,
) -> str:
    """Справочник по тем разделам, которые у человека есть.

    visible_keys — итоговая видимость разделов из панели (режим, переключатели
    владельца и права), тот же список, по которому строятся меню и тур. Без
    него справочник описывал бы «Склад» человеку, у которого «Склада» в меню
    нет, и ссылка «где это» вернула бы его в «Обзор».
    """
    visible = frozenset(visible_keys) if visible_keys is not None else None
    groups = panel_guide.manual_groups(mode, visible)
    present = visible if visible is not None else panel_sections.available_keys(mode)

    body = ""
    for group in groups:
        sections = ""
        for section in group.sections:
            sections += f"""
            <section class="my-salon-card instructions-section" id="{section.slug}">
                <h3 class="my-salon-card-title">{e(section.label)}</h3>
                <p class="instructions-why">{e(section.why)}</p>
                <div class="instructions-body">{section.body}</div>
                {_where_html(section, salon_id, tour_on)}
            </section>"""
        body += f"""
        <div class="instructions-group">
            <h2 class="instructions-group-title" id="{group.slug}">{e(group.title)}</h2>
            <p class="instructions-group-lead">{e(group.lead)}</p>
            {sections}
        </div>"""

    # Ссылка на тур — тому, кто его в принципе увидит (см. panel_tour.decide):
    # участнику без права менять салон она ничего бы не открыла.
    restart_html = render_restart_link(salon_id=salon_id) if (can_tour and salon_id) else ""
    return f"""
    <div id="tab-instructions" class="tab-content">
        {restart_html}

        <section class="my-salon-card">
            <h2 class="my-salon-card-title">Справочник по панели</h2>
            <p class="my-salon-card-hint">Здесь описан каждый раздел, который у вас
                есть: зачем он нужен, что в нём сделать и куда для этого идти. На
                любой пункт можно дать ссылку — адрес с решёткой ведёт прямо к
                нему.</p>
            {_toc_html(groups)}
        </section>

        {_start_html(mode, salon_id, present, tour_on)}

        {body}
    </div>"""
