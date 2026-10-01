"""Полоса знакомства снизу панели и приглашение пройти его (решение 0008, п. 3).

Форма выбрана намеренно скромная: полоса внизу, подсветка кнопки раздела в
меню — и всё. Ни затемнения, ни выреза вокруг элементов:

  * панель во время тура живая, человек может прямо на шаге заполнить поле и
    сохранить (решение 0008, п. 8), а затемнение этому мешает физически;
  * вырез пришлось бы пересчитывать после каждой подгрузки вкладки и каждого
    скролла и завязать тур на разметку всех шестнадцати разделов (п. 3).

Кнопки — ссылки, а не обработчики: вкладки панели и так открываются полной
навигацией, поэтому шаг — это обычный переход с ?tour=<ключ>. Отсюда три
следствия: тур работает без JS, перезагрузка поднимает его на том же месте, и
«Назад» браузера ведёт себя предсказуемо.

Цвета — только токенами: тёмная тема обязана работать, а своих цветов у полосы
нет (static/src/css/business/panel-tour.css).
"""
from typing import Optional, Sequence

from app.services import panel_tour as tour_service
from app.web.components.escaping import e
from app.web.components.icons import ICON_X


def _href(base: str, value: str) -> str:
    """Адрес шага: тот же адрес панели + ?tab= нужного раздела + ?tour=.

    base приходит готовым («/business/dashboard?salon_id=N»), раздел берётся из
    самого шага — тур переключает вкладку сам (решение 0008, п. 3).
    """
    return f"{base}&tour={value}"


def _step_href(base: str, steps: Sequence, key: Optional[str]) -> str:
    """Адрес конкретного шага вместе с его разделом.

    У шага может быть якорь: когда на один раздел приходится больше одного шага
    (в соло «Моя карточка мастера» рассказывается двумя), ссылка обязана вести
    к нужной группе, а не к началу длинного раздела.
    """
    step = next((s for s in steps if s.key == key), None)
    if step is None:
        return _href(base, tour_service.REQUEST_ON)
    tab = f"&tab={step.tab}" if step.tab else ""
    anchor = f"#{step.anchor}" if getattr(step, "anchor", None) else ""
    return f"{base}{tab}&tour={step.key}{anchor}"


def render_tour_bar(
    *,
    salon_id: int,
    steps: Sequence,
    step,
    current_tab: str,
) -> str:
    """Полоса на текущем шаге.

    current_tab нужен одной кнопке — «Выйти»: человек остаётся там, где стоял, а
    не улетает в «Обзор». Остальные кнопки ведут каждая в свой раздел.
    """
    base = f"/business/dashboard?salon_id={salon_id}"
    total = len(steps)
    number = next((i + 1 for i, s in enumerate(steps) if s.key == step.key), 1)

    prev_k = tour_service.prev_key(steps, step.key)
    next_k = tour_service.next_key(steps, step.key)
    skip_k = tour_service.skip_act_key(steps, step.key)

    back_html = (
        f'<a class="panel-tour-btn" href="{_step_href(base, steps, prev_k)}">Назад</a>'
        if prev_k else
        '<span class="panel-tour-btn is-off" aria-hidden="true">Назад</span>'
    )
    # На последнем шаге «Дальше» становится «Готово»: оно и ставит отметку
    # «прошёл до конца», по которой потом считают дошедших (решение 0008, п. 6).
    if next_k:
        forward_html = (
            f'<a class="panel-tour-btn is-primary" href="{_step_href(base, steps, next_k)}">'
            'Дальше</a>'
        )
    else:
        forward_html = (
            f'<a class="panel-tour-btn is-primary" '
            f'href="{base}&tab={current_tab}&tour={tour_service.REQUEST_DONE}">Готово</a>'
        )
    # «Пропустить» — про акт целиком, а не про шаг, и из тура не выбрасывает
    # (решение 0008, п. 4). На последнем акте пропускать нечего.
    skip_html = (
        f'<a class="panel-tour-skip" href="{_step_href(base, steps, skip_k)}">'
        f'Пропустить: {e(step.act_title)}</a>'
        if skip_k else ""
    )
    exit_href = f"{base}&tab={current_tab}&tour={tour_service.REQUEST_OFF}"

    percent = round(number / total * 100) if total else 0

    return f"""
    <div class="panel-tour" id="panelTour" data-salon-id="{salon_id}"
         data-step="{e(step.key)}"
         data-tour-tab="{e(step.tab or '')}"
         role="region" aria-label="Знакомство с панелью">
        <div class="panel-tour-progress" aria-hidden="true">
            <span style="width:{percent}%"></span>
        </div>
        <div class="panel-tour-inner">
            <div class="panel-tour-head">
                <p class="panel-tour-meta" role="status" aria-live="polite">
                    Шаг {number} из {total} — {e(step.act_title)}
                </p>
                <a class="panel-tour-exit" href="{exit_href}"
                   title="Выйти из знакомства">{ICON_X}<span>Выйти</span></a>
            </div>
            <p class="panel-tour-text">{e(step.text)}</p>
            <div class="panel-tour-actions">
                {back_html}
                {forward_html}
                {skip_html}
            </div>
        </div>
    </div>"""


def render_tour_invite(*, salon_id: int, steps: Sequence, step) -> str:
    """Скромное приглашение: одна строка над содержимым вкладки.

    Показывается двоим: тому, кто однажды вышел из тура (зовём продолжить с его
    шага — «вернуться на том же»), и тому, у кого салон уже работает и записи
    есть, — такому тур сам не всплывает (решение 0008, п. 5).

    Крестик убирает строку до конца этой вкладки браузера (sessionStorage, см.
    panel-tour.js): отказ «сейчас не надо» — это про текущий заход, и столбца
    в базе он не заслуживает.
    """
    base = f"/business/dashboard?salon_id={salon_id}"
    started = any(s.key == step.key for s in steps) and step.key != steps[0].key
    number = next((i + 1 for i, s in enumerate(steps) if s.key == step.key), 1)
    if started:
        text = "Знакомство с панелью осталось незаконченным."
        label = f"Продолжить с шага {number}"
    else:
        text = ("Знакомство с панелью: что делает вас заметнее в ленте и чем "
                "можно выделиться.")
        label = "Пройти знакомство"
    return f"""
    <div class="panel-tour-invite" id="panelTourInvite" data-salon-id="{salon_id}">
        <p class="panel-tour-invite-text">{text}</p>
        <a class="panel-tour-invite-btn" href="{_step_href(base, steps, step.key)}">{label}</a>
        <button type="button" class="panel-tour-invite-close" id="panelTourInviteClose"
                aria-label="Скрыть приглашение">{ICON_X}</button>
    </div>"""


def render_restart_link(*, salon_id: int) -> str:
    """Ссылка «Пройти знакомство заново» для вкладки «Инструкция».

    Сбрасывает тур на первый шаг и снимает отметку «прошёл до конца»;
    «запустили впервые» не трогаем — иначе по ней нельзя было бы посчитать,
    сколько людей тур вообще видели.
    """
    href = (f"/business/dashboard?salon_id={salon_id}&tab=overview"
            f"&tour={tour_service.REQUEST_RESTART}")
    return f"""
    <p class="instructions-restart">
        <a class="instructions-restart-link" href="{href}">Пройти знакомство заново</a>
        — платформа ещё раз проведёт по вашим разделам и расскажет, что в них делать.
    </p>"""
