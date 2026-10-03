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
разойтись. Названия разделов приходят из panel_sections.label по режиму (их
подставляет сам реестр) — зашитое строкой название отправило бы человека искать
вкладку, которой у него нет.

Шагов «С чего начать» текстом здесь больше нет (решение 0010, п. 6): тот же
путь считается из базы и живёт блоком в «Обзоре», а здесь от него осталась
врезка со ссылкой. Текст, который не знает, что половина уже сделана, — второй
источник правды, и он разошёлся бы с блоком при первой же правке.

Картинок здесь нет намеренно (решение 0009, п. 7–8): через неделю-две
начинается переделка фронта целиком, и любая картинка умрёт вместе с ним, а
текст переживёт. Схемы пути с /tariffs не переиспользованы по другой причине —
они говорят «салон», а в соло-режиме салона у человека нет.
"""
from typing import Iterable, Optional

from app.models.models import SalonPanelMode
from app.services import panel_guide
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


def _path_promo_html(mode: SalonPanelMode, salon_id: int, tour_on: bool) -> str:
    """Врезка на месте прежнего гайда «С чего начать» (решение 0010, п. 6).

    Шагов текстом здесь больше нет. Они жили рядом с живым блоком в «Обзоре»,
    который считает то же самое из базы, и это были два источника правды о том,
    что человеку осталось сделать: текст не знал, что половина уже сделана, и
    через месяц правок разошёлся бы с блоком.

    Убирать пункт совсем тоже нельзя: человек, читающий справочник сверху вниз,
    потерял бы единственное место, где виден весь путь, — поэтому остаётся
    врезка со ссылкой. Якорь прежний (#manual-start): на него уже могли дать
    ссылку в поддержке.
    """
    href = _tab_href(salon_id, "overview", None, tour_on)
    return f"""
    <section class="my-salon-card instructions-section instructions-path" id="manual-start">
        <h2 class="my-salon-card-title">{e(panel_guide.CHECKLIST_TITLE)}</h2>
        <p class="instructions-why">{e(panel_guide.check_promo_text(
            solo=mode is SalonPanelMode.SOLO))}</p>
        <p class="instructions-where">
            <a class="instructions-where-link" href="{href}">{e(
                panel_guide.CHECK_PROMO_ACTION)}</a>
        </p>
    </section>"""


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
        <a class="instructions-toc-first" href="#manual-start">{e(panel_guide.CHECKLIST_TITLE)}</a>
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

        {_path_promo_html(mode, salon_id, tour_on)}

        {body}
    </div>"""
