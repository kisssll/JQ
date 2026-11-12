# app/web/components/reschedule.py
"""Перенос записи клиентом (решение 0020): кнопка и лист выбора нового времени.

Один лист на «Мои записи» и на гостевую страницу по токену: различаются они
только адресом API, и держать две копии одного диалога значило бы рано или
поздно получить два разных переноса. Поведение — static/src/js/reschedule.js.
"""
from app.services.schedule_utils import MAX_BOOKING_DAYS_AHEAD
from app.web.components import ui

SHEET_ID = "rescheduleSheet"


def reschedule_button(*, api: str, done: str, what: str, current: str, small: bool = False,
                      block: bool = False) -> str:
    """Кнопка «Перенести».

    api — корень API переноса этой записи (…/reschedule): к нему лист
    добавляет /slots и /quote. done — куда вести после успеха: страница сама
    скажет, что вышло. current — нынешнее начало «ГГГГ-ММ-ДДTЧЧ:ММ»: с его дня
    лист и открывается, человек чаще двигает запись на соседний час.
    """
    return ui.button(
        "Перенести", kind="secondary", small=small, block=block,
        classes="js-reschedule-btn",
        data={"reschedule-api": api, "reschedule-done": done,
              "reschedule-what": what, "reschedule-current": current},
    )


def reschedule_sheet() -> str:
    """Лист выбора нового времени. Дни и окна — та же разметка, что у записи
    на странице салона (.days / .r-slots): человек узнаёт экран, а не учит новый."""
    return ui.sheet(
        '<p class="r-text" id="rescheduleWhat"></p>'
        f'<div class="days" id="rescheduleDays" role="group" aria-label="Новая дата"'
        f' data-max-days="{MAX_BOOKING_DAYS_AHEAD}"></div>'
        '<div class="r-slots" id="rescheduleSlots" aria-live="polite"></div>'
        '<div class="reschedule-summary" id="rescheduleSummary" aria-live="polite" hidden>'
        '<p class="r-text" id="rescheduleWhen"></p>'
        '<p class="r-text r-muted" id="reschedulePrice" hidden></p>'
        '</div>'
        '<div class="sheet-actions">'
        + ui.button("Перенести", block=True, disabled=True, element_id="rescheduleConfirm")
        + ui.button("Не переносить", kind="secondary", block=True, data={"sheet-close": "1"})
        + '</div>',
        element_id=SHEET_ID, title="Перенести запись",
    )
