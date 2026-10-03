# app/web/pages/guest_booking.py
"""Публичные страницы записи без регистрации: /book/{salon_id} и /guest-booking/{token}.

Показательный экран подложки (заход 03.10.2026): страница короткая, её видит
клиент, и она единственная, что приносит деньги. Собрана на слое
app/web/components/ui.py + static/src/css/ui.css — это и есть проверка, что
набора хватает на настоящий экран.

Поведение не менялось: те же четыре шага, те же проверки, те же отказы и те
же тексты. Изменилась только форма. Стили переехали из инлайнового <style>
в static/src/css/guest-booking.css.
"""
from app.web.components.escaping import e, ejson

from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.models.models import (
    Salon, Master, Service, User, Booking,
    SalonModerationStatus, BookingStatus,
)
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_ARROW_LEFT, ICON_CHECK
from app.web.components import ui
from app.web.pages.legal import LEGAL_VERSION


# Подписи шагов. Порядок здесь задаёт и номера в полосе прогресса, и подписи
# «Шаг N из 4» — чтобы счётчик нельзя было рассинхронизировать с шагами.
_STEPS = [
    ("master", "Выберите мастера"),
    ("service", "Услуга"),
    ("slot", "Дата и время"),
    ("details", "Ваши данные"),
]
_TOTAL = len(_STEPS)


def _shell(title: str, inner: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>{title} — руми</title>
    {get_base_styles()}
</head>
<body class="gb-body" data-legal-version="{LEGAL_VERSION}">
    <header class="gb-header">
        <a href="/" id="header-logo">руми.</a>
        <a href="/login" class="gb-login">Войти</a>
    </header>
    <main class="gb-wrap">
        {inner}
    </main>
</body>
</html>"""


def _notice(title: str, text: str) -> str:
    """Отказ — это тоже экран, а не сообщение об ошибке: он называет причину
    и даёт следующий шаг."""
    return _shell(title, ui.empty_state(
        title, text=text, action_label="На главную руми", action_href="/",
    ))


def _progress(index: int) -> str:
    """Полоса прогресса и подпись «Шаг N из 4».

    Нумерация здесь остаётся, потому что последовательность несёт смысл:
    человеку надо знать, сколько ещё до «Записаться». Но несёт её полоса и
    подпись, а не кружок с цифрой перед каждым заголовком — кружки повторяли
    то, что и так видно, и забирали строку у самого заголовка.

    Смысл не передаётся одним цветом: рядом с полосой всегда есть текст.
    """
    cells = "".join(
        f'<span class="{"is-done" if i <= index else ""}"></span>'
        for i in range(_TOTAL)
    )
    return (
        f'<div class="gb-progress" role="presentation">{cells}</div>'
        f'<p class="gb-step-count">Шаг {index + 1} из {_TOTAL}</p>'
    )


def _step(index: int, *, back_to: str = "", back_label: str = "", body: str = "") -> str:
    key, title = _STEPS[index]
    back = ""
    if back_to:
        back = (
            f'<button class="gb-back" type="button" data-to="{back_to}">'
            f'{ICON_ARROW_LEFT}{e(back_label)}</button>'
        )
    # hidden, а не style="display:none": атрибут читается скринридером как
    # «этого сейчас нет», инлайновый стиль — нет.
    hidden = "" if index == 0 else " hidden"
    return f"""
        <section class="gb-step" data-step="{key}" data-index="{index}"{hidden}>
            {back}
            {_progress(index)}
            <h2>{e(title)}</h2>
            {body}
        </section>"""


async def render_guest_booking_page(db, salon_id: int) -> str:
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if (
        not salon
        or not salon.is_active
        or salon.moderation_status != SalonModerationStatus.APPROVED
        or salon.published_at is None
        or not salon.guest_booking_enabled
    ):
        return _notice("Запись недоступна", "Этот салон сейчас не принимает записи без регистрации.")

    masters = (await db.execute(
        select(Master).where(Master.salon_id == salon_id, Master.is_active == True)
    )).scalars().all()

    # Частный мастер — «салон» из одного человека, который сам им владеет.
    # Ему «салон подтвердит запись» звучит странно: клиент идёт к мастеру.
    solo = len(masters) == 1 and masters[0].user_id == salon.creator_id
    confirmer = "мастер" if solo else "салон"
    title = f"Запись к «{e(salon.name)}»" if solo else f"Запись в «{e(salon.name)}»"

    data = []
    for m in masters:
        muser = (await db.execute(select(User).where(User.id == m.user_id))).scalar_one_or_none()
        services = (await db.execute(
            select(Service).options(selectinload(Service.photos)).where(
                or_(
                    Service.master_id == m.id,
                    Service.assigned_masters.any(Master.id == m.id),
                ),
                Service.is_active == True, Service.is_model_practice == False,
            ).order_by(Service.price)
        )).scalars().all()
        if not services:
            continue
        data.append({
            "id": m.id,
            "name": (muser.full_name if muser else None) or "Мастер",
            "spec": m.specialization or "",
            "services": [
                {
                    "id": s.id, "name": s.name, "price": s.price, "price_max": s.price_max,
                    "duration": s.duration_minutes, "photos": [photo.url for photo in s.photos],
                }
                for s in services
            ],
        })

    if not data:
        return _notice("Пока нельзя записаться", "У салона нет доступных мастеров или услуг.")

    masters_json = ejson(data)

    details = (
        '<div id="gb-summary" class="gb-summary"></div>'
        + ui.field("Имя", element_id="gb-name", type_="text",
                   autocomplete="name", required=True)
        + ui.field("Телефон", element_id="gb-phone", type_="tel",
                   value="+7", placeholder="+7 (___) ___-__-__",
                   autocomplete="tel", inputmode="tel", required=True,
                   input_classes="phone-input")
        + ui.field("Email", element_id="gb-email", type_="email",
                   autocomplete="email", placeholder="example@mail.ru",
                   hint="Для уведомлений, необязательно")
        + """
                <div class="consent-block gb-consent">
                    <label class="consent-check">
                        <input type="checkbox" id="gb-consent" class="consent-check-input" required>
                        <span class="consent-check-text">Я даю согласие на обработку персональных данных на условиях
                            <a href="/consent" target="_blank" rel="noopener">Согласия</a>.</span>
                    </label>
                    <p class="consent-note">Записываясь, вы принимаете
                        <a href="/terms" target="_blank" rel="noopener">Пользовательское соглашение</a>
                        и подтверждаете, что ознакомились с
                        <a href="/privacy" target="_blank" rel="noopener">Политикой обработки персональных данных</a>.</p>
                </div>
                <p id="gb-error" class="gb-error" role="alert"></p>
        """
        + ui.button("Записаться", element_id="gb-submit", block=True)
    )

    done = f"""
            <div class="gb-done">
                <div class="gb-done-check" aria-hidden="true">{ICON_CHECK}</div>
                <h2 class="r-subtitle">Заявка отправлена</h2>
                <p class="gb-done-text">Салон подтвердит запись.
                    Сохраните ссылку — по ней можно посмотреть или отменить бронь:</p>
                <a id="gb-manage-link" class="gb-manage-link" href="#"></a>
            </div>"""

    inner = f"""
        <div class="gb-intro">
            <h1 class="r-display">{title}</h1>
            <p>Без регистрации — оставьте имя и телефон, {confirmer} подтвердит запись.</p>
        </div>

        <div id="guest-book" data-salon-id="{salon.id}" data-masters='{masters_json}'>
            {_step(0, body='<div id="gb-masters" class="gb-list"></div>')}
            {_step(1, back_to="master", back_label="Назад к мастерам",
                   body='<div id="gb-services" class="gb-list"></div>')}
            {_step(2, back_to="service", back_label="Назад к услугам",
                   body='<input type="date" id="gb-date" class="r-input gb-date" aria-label="Дата записи">'
                        '<div id="gb-slots" class="gb-slots"></div>')}
            {_step(3, back_to="slot", back_label="Назад ко времени", body=details)}

            <section class="gb-step" data-step="done" data-index="{_TOTAL}" hidden>{done}</section>
        </div>
    """
    return _shell(f"Запись в {e(salon.name)}", inner)


async def render_guest_manage_page(db, token: str) -> str:
    booking = (await db.execute(
        select(Booking).where(Booking.guest_manage_token == token)
    )).scalar_one_or_none()
    if not booking:
        return _notice("Бронь не найдена", "Ссылка недействительна или устарела.")

    service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
    master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
    muser = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none() if master else None
    salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none() if master else None

    # Статус — плашка слоя ui: слово плюс тон. Раньше тут был инлайновый
    # color по словарю, и цвета не совпадали ни с токенами, ни между собой
    # (#27ae60 против --color-success), а в тёмной теме не читались вовсе.
    status_ru = {
        BookingStatus.PENDING: ("Ожидает подтверждения салона", "warning"),
        BookingStatus.CONFIRMED: ("Подтверждена", "success"),
        BookingStatus.COMPLETED: ("Выполнена", "neutral"),
        BookingStatus.CANCELLED: ("Отменена", "danger"),
        BookingStatus.NO_SHOW: ("Неявка", "danger"),
    }.get(booking.status, (str(booking.status), "neutral"))

    when = booking.start_time.strftime("%d.%m.%Y в %H:%M") if booking.start_time else ""
    can_cancel = booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
    cancel_btn = ui.button(
        "Отменить запись", kind="danger", element_id="gb-cancel",
        block=True, data={"token": token},
    ) if can_cancel else ""

    letter = e(((muser.full_name if muser else "М") or "М")[0])
    rows = (
        f'<div class="gb-manage-row"><dt>Когда</dt><dd class="tabular-nums">{e(when)}</dd></div>'
        f'<div class="gb-manage-row"><dt>Статус</dt>'
        f'<dd>{ui.status(status_ru[0], status_ru[1])}</dd></div>'
    )

    inner = f"""
        <div class="gb-intro">
            <h1 class="r-display">Ваша запись</h1>
            <p>«{e(salon.name if salon else "")}»</p>
        </div>
        <div class="r-card">
            <div class="gb-manage-who">
                <div class="gb-ava" aria-hidden="true">{letter}</div>
                <div class="gb-card-body">
                    <strong>{e((muser.full_name if muser else "") or "Мастер")}</strong>
                    <small>{e(service.name if service else "")}</small>
                </div>
            </div>
            <dl class="gb-manage-list">{rows}</dl>
            {f'<div class="gb-manage-act">{cancel_btn}</div>' if cancel_btn else ""}
            <p id="gb-cancel-msg" class="gb-manage-msg" role="status"></p>
        </div>
        <p class="gb-foot"><a href="/">На главную руми</a></p>
    """
    return _shell("Ваша запись", inner)
