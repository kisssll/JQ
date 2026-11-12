# app/web/components/booking_marks.py
"""Отметки у записи в панели салона (решение 0020): перенесена, подтверждена.

Лежат отдельно от reschedule.py: там диалог переноса для клиента, а здесь —
то, что видит о записи салон. Обе отметки рисуются рядом в расписании и в
записях, поэтому и живут в одном месте: разведи их — и они разойдутся
оформлением.
"""
from app.web.components import ui
from app.web.components.icons import ICON_CHECK_SMALL


def rescheduled_mark(booking) -> str:
    """Плашка «Перенесена» у записи в панели салона — пусто, если запись не
    двигали. Салону важно видеть, что время у записи не то, на которое
    клиент записывался изначально (решение 0020, п. 8)."""
    if not getattr(booking, "rescheduled_count", 0):
        return ""
    return ui.status("Перенесена", "accent")


def rescheduled_note(booking, salon_timezone: str | None) -> str:
    """«2 раза, последний — 12.11 в 15:00» в часах салона; пусто, если
    запись не двигали. Момент хранится в UTC — показываем по зоне салона,
    как и само время записи."""
    from app.utils.timezone import get_salon_time
    from app.web.components.cabinet import plural

    count = getattr(booking, "rescheduled_count", 0) or 0
    if not count:
        return ""
    text = f"{count} {plural(count, 'раз', 'раза', 'раз')}"
    at = getattr(booking, "rescheduled_at", None)
    if at is not None:
        local = at.astimezone(get_salon_time(salon_timezone).tzinfo)
        text += f", последний — {local:%d.%m в %H:%M}"
    return text


def confirmed_mark(booking) -> str:
    """Галочка «Клиент подтвердил» — клиент нажал «Буду» в напоминании.

    Статус записи это не меняет (его ставит салон и он считается выручкой),
    поэтому отметка отдельная: мастеру она говорит, что человек придёт.
    """
    if getattr(booking, "client_confirmed_at", None) is None:
        return ""
    return ui.status("Клиент подтвердил", "success", icon=ICON_CHECK_SMALL)
