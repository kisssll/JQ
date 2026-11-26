# app/web/pages/bookings.py
"""«Мои записи» — что со мной будет и что уже было.

Экран устроен вокруг ОДНОГО вопроса: что с этой записью делать дальше.
Поэтому сверху «Предстоящие» (их можно отменить), ниже «Прошедшие» (на них
можно оставить отзыв), а состояние каждой записи названо словом в плашке —
цветом одним оно не передаётся.

Трёх вкладок с счётчиками больше нет. Отменённая запись — это прошедшая, и
отдельная вкладка под неё заставляла человека угадывать, в какой из трёх
лежит то, что он ищет. Память активной вкладки в localStorage уехала вместе
со вкладками.

Запросов — постоянное число, не зависящее от количества записей: прежняя
версия ходила в базу за мастером, его пользователем, салоном, услугой и
отзывом НА КАЖДУЮ запись (пять запросов на карточку), и человек с двумя
десятками визитов открывал страницу секунды.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Booking,
    BookingStatus,
    Master,
    Review,
    ReviewTargetType,
    Salon,
    Service,
    User,
)
from app.services.public_words import dative, first_name, solo_from_facts
from app.web.components import ui
from app.web.components.escaping import e
from app.web.components.footer import render_footer
from app.web.components.cabinet import plural, render_cabinet
from app.web.components.header import render_header
from app.web.components.reschedule import reschedule_button, reschedule_sheet
from app.web.components.icons import (
    ICON_EDIT_PENCIL,
    ICON_STAR_EMPTY,
    ICON_STAR_FILLED,
)
from app.web.components.styles import get_base_styles

#: Состояние записи словом и тоном плашки. NO_SHOW попал сюда не сразу: он
#: появился вместе с отметкой «Пришёл», и записи с ним показывали клиенту
#: прочерк вместо состояния.
_STATUS = {
    BookingStatus.PENDING: ("Ждёт подтверждения", "warning"),
    BookingStatus.CONFIRMED: ("Подтверждена", "success"),
    BookingStatus.COMPLETED: ("Завершена", "success"),
    BookingStatus.CANCELLED: ("Отменена", "neutral"),
    BookingStatus.NO_SHOW: ("Пропущена", "warning"),
}

_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
               "июля", "августа", "сентября", "октября", "ноября", "декабря"]

#: Сообщения по итогам действия. Приходят параметром в адресе: отмена и отзыв
#: перезагружают страницу, и без строки на экране человек не знает, прошло ли
#: действие. Раньше отмена говорила об успехе через alert(), а «отзыв сохранён»
#: (редирект /bookings?reviewed=1) не говорил вообще ничего.
_NOTICES = {
    "cancelled": ("Запись отменена. Время освободилось.", "neutral"),
    "rescheduled": ("Запись перенесена на новое время.", "success"),
    "reviewed": ("Спасибо, отзыв сохранён.", "success"),
}


def _when(start: datetime) -> str:
    """«5 октября, 15:00». Время записи — местное время салона, как его задал
    сам салон при создании брони; своего пояса страница не навязывает."""
    return f"{start.day} {_MONTHS_GEN[start.month - 1]}, {start:%H:%M}"


async def _load(db: AsyncSession, user) -> tuple[list, dict]:
    """Записи человека и всё, что нужно их карточкам. Постоянное число
    запросов: сначала записи, потом — пачкой — услуги, мастера, их имена,
    салоны, число мастеров в салоне и отзывы этого клиента.

    Отзывы берём ВСЕ, что оставил человек, а не по booking_id: право оставить
    отзыв проверяет ``ReviewService`` по ЦЕЛИ (мастер или салон), а не по
    записи, — см. ``_can_review``.
    """
    bookings = (await db.execute(
        select(Booking).where(Booking.client_id == user.id)
        .order_by(Booking.start_time.desc())
    )).scalars().all()
    if not bookings:
        return [], {}

    service_ids = {b.service_id for b in bookings if b.service_id}
    master_ids = {b.master_id for b in bookings if b.master_id}

    services = {}
    if service_ids:
        services = {
            s.id: s for s in (await db.execute(
                select(Service).where(Service.id.in_(service_ids))
            )).scalars().all()
        }

    masters, master_names, salons, master_counts = {}, {}, {}, {}
    if master_ids:
        masters = {
            m.id: m for m in (await db.execute(
                select(Master).where(Master.id.in_(master_ids))
            )).scalars().all()
        }
        user_ids = {m.user_id for m in masters.values() if m.user_id}
        if user_ids:
            master_names = {
                u.id: (u.full_name or "") for u in (await db.execute(
                    select(User).where(User.id.in_(user_ids))
                )).scalars().all()
            }
        salon_ids = {m.salon_id for m in masters.values() if m.salon_id}
        if salon_ids:
            salons = {
                s.id: s for s in (await db.execute(
                    select(Salon).where(Salon.id.in_(salon_ids))
                )).scalars().all()
            }
            # Соло или команда решается на тех же фактах, что на витрине:
            # объявленный режим плюс ровно один активный мастер.
            master_counts = dict((await db.execute(
                select(Master.salon_id, func.count(Master.id))
                .where(Master.salon_id.in_(salon_ids), Master.is_active == True)  # noqa: E712
                .group_by(Master.salon_id)
            )).all())

    reviews = (await db.execute(
        select(Review).where(Review.client_id == user.id)
    )).scalars().all()

    return bookings, {
        "services": services,
        "masters": masters,
        "master_names": master_names,
        "salons": salons,
        "master_counts": master_counts,
        "reviews": reviews,
    }


def _review_of(ctx: dict, master_id, salon_id) -> Review | None:
    """Отзыв этого клиента на ЭТУ цель, если он есть.

    Цель — мастер, когда запись к мастеру, иначе салон: ровно так её
    определяет форма отзыва (``target_type``) и проверка в
    ``ReviewService._already_reviewed``.
    """
    for r in ctx["reviews"]:
        if master_id and r.target_type == ReviewTargetType.MASTER and r.master_id == master_id:
            return r
        if not master_id and r.target_type == ReviewTargetType.SALON and r.salon_id == salon_id:
            return r
    return None


def _render_card(b: Booking, ctx: dict, *, upcoming: bool) -> str:
    """Карточка записи. Собрана из ui-примитивов: своих кнопок и плашек у
    страницы нет."""
    service = ctx["services"].get(b.service_id)
    master = ctx["masters"].get(b.master_id)
    salon = ctx["salons"].get(master.salon_id) if master and master.salon_id else None

    service_name = service.name if service else "Услуга"
    master_name = ctx["master_names"].get(master.user_id, "") if master else ""

    solo = False
    if salon:
        solo = solo_from_facts(
            getattr(salon, "panel_mode", None),
            ctx["master_counts"].get(salon.id, 0),
            bool(master and master.user_id == getattr(salon, "creator_id", None)),
        )

    # Соло-мастер — человек, а не организация: «к Анне», а не «мастер такой-то
    # в салоне таком-то». Падеж даёт public_words и при сомнении возвращает
    # пустую строку — тогда остаёмся на имени без падежа.
    if solo and master_name:
        who_label = "К кому"
        who_value = e(dative(first_name(master_name)) or first_name(master_name))
    else:
        who_label = "Мастер"
        who_value = e(master_name or "—")

    # Ссылка на салон остаётся В ОБОИХ режимах. У соло-мастера салон — это его
    # собственное дело под своим названием, и человеку всё равно надо знать,
    # куда он идёт; выкинуть строку только потому, что подпись назвала мастера
    # по имени, значило бы потерять единственный путь к карточке.
    place = (
        f'<a href="/salons?highlight={salon.id}" class="booking-salon-link">'
        f"{e(salon.name)}</a>"
        if salon else ""
    )

    label, tone = _STATUS.get(b.status, ("—", "neutral"))
    duration = int((b.end_time - b.start_time).total_seconds() // 60)

    facts = [
        ("Когда", f"{e(_when(b.start_time))} · {duration} мин"),
        (who_label, who_value),
    ]
    if place:
        facts.append(("Где", place))
    if salon and salon.address:
        facts.append(("Адрес", e(salon.address)))
    if salon and salon.phone:
        facts.append(("Телефон", f'<a href="tel:{e(salon.phone)}">{e(salon.phone)}</a>'))
    if b.hair_survey and isinstance(b.hair_survey, dict):
        length = b.hair_survey.get("length", {})
        l_str = f"{length.get('title', '')} ({length.get('cm', '')})" if length else ""
        h_type = b.hair_survey.get("type", {}).get("title", "")
        h_dens = b.hair_survey.get("density", {}).get("title", "")
        features = b.hair_survey.get("features", [])
        feats_str = f" · {', '.join(features)}" if features else ""
        survey_desc = f"{l_str} · {h_type} · {h_dens}{feats_str}".strip(" ·")
        if survey_desc:
            facts.append(("Волосы", e(survey_desc)))
    facts.append(("Стоимость", f"{b.final_price} ₽" if b.final_price else "—"))

    # ---------- Что с записью можно сделать ----------
    action = ""
    pair = False
    if upcoming and b.status not in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        # Перенос стоит первым: если человеку неудобно время, сдвинуть запись
        # лучше для обеих сторон, чем отменить и искать окно заново (решение 0020).
        # Подтверждение — лист снизу, а не confirm(): отмена освобождает время
        # и необратима, а системное окно браузера нельзя ни прочитать толком,
        # ни отличить от окна другого сайта.
        what = f"{service_name}, {_when(b.start_time)}"
        pair = True
        action = reschedule_button(
            api=f"/api/v1/bookings/{b.id}/reschedule",
            done="/bookings?notice=rescheduled",
            what=what, current=b.start_time.strftime("%Y-%m-%dT%H:%M"), small=True,
        ) + ui.button(
            "Отменить запись", kind="secondary", small=True,
            classes="booking-cancel-btn",
            data={"booking-id": b.id, "booking-what": what},
        )
    elif b.status == BookingStatus.COMPLETED:
        existing = _review_of(ctx, b.master_id, salon.id if salon else None)
        if existing:
            stars = (ICON_STAR_FILLED * existing.rating) + (ICON_STAR_EMPTY * (5 - existing.rating))
            action = (
                '<div class="booking-review">'
                f'<div class="booking-review__stars" aria-label="Ваша оценка: {existing.rating} из 5">'
                f"{stars}</div>"
                + (f'<p class="booking-review__text">{e(existing.comment)}</p>'
                   if existing.comment else "")
                + ui.button("Изменить отзыв", kind="secondary", small=True,
                            icon=ICON_EDIT_PENCIL,
                            classes="booking-review-edit-btn",
                            data={"booking-id": b.id, "review-id": existing.id})
                + "</div>"
            )
        elif salon:
            # Отзыв возможен только когда он возможен на сервере: завершённая
            # запись И отзыва на эту цель ещё нет. Прежняя версия искала отзыв
            # по booking_id и потому предлагала кнопку человеку, который уже
            # оценил этого мастера другой записью, — сервер отвечал 409.
            action = ui.button(
                "Оставить отзыв", small=True, icon=ICON_EDIT_PENCIL,
                classes="booking-review-add-btn",
                data={"booking-id": b.id, "salon-id": salon.id,
                      "master-id": b.master_id or ""},
            )

    return (
        f'<article class="r-card booking-card" data-booking-id="{b.id}">'
        '<div class="booking-card__head">'
        f'<h3 class="r-subtitle booking-card__service">{e(service_name)}</h3>'
        f"{ui.status(label, tone)}"
        "</div>"
        f"{ui.facts(tuple(facts))}"
        + (f'<div class="booking-card__action{" booking-card__action--pair" if pair else ""}">'
           f'{action}</div>' if action else "")
        + "</article>"
    )


async def render_bookings_page(db: AsyncSession, user, notice: str = "", sport: bool = False) -> str:
    """Страница «Мои записи» для клиента (бьюти или спорт)."""
    if sport:
        return await _render_sport_bookings_page(db, user, notice=notice)
    bookings, ctx = await _load(db, user)
    now = datetime.now()

    upcoming, past = [], []
    for b in bookings:
        if b.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED) and b.start_time > now:
            upcoming.append(b)
        else:
            past.append(b)

    # Предстоящие — ближайшая первой: это следующий поступок человека.
    # Прошедшие — наоборот, свежая сверху. Запрос отдаёт по убыванию, поэтому
    # переворачиваем только предстоящие.
    upcoming.reverse()

    notice_html = ""
    if notice in _NOTICES:
        text, tone = _NOTICES[notice]
        notice_html = ui.notice(text, tone=tone)

    to_catalog = ui.empty_state(
        "Предстоящих записей нет",
        text="Выберите мастера, услугу и время — запись появится здесь.",
        action_label="Открыть каталог",
        action_href="/salons",
    )

    if not bookings:
        body = ui.empty_state(
            "Записей пока нет",
            text="Здесь будут ваши визиты: предстоящие — с возможностью отменить, "
                 "прошедшие — с отзывом.",
            action_label="Открыть каталог",
            action_href="/salons",
        )
    else:
        upcoming_html = (
            "".join(_render_card(b, ctx, upcoming=True) for b in upcoming)
            if upcoming else to_catalog
        )
        sections = [
            '<section class="bookings-group">'
            + ui.section_head("Предстоящие")
            + f'<div class="bookings-list">{upcoming_html}</div>'
            + "</section>"
        ]
        # Пустой раздел «Прошедшие» показывать нечего: у нового человека он
        # сообщал бы об отсутствии истории, которой у него и не могло быть.
        if past:
            sections.append(
                '<section class="bookings-group">'
                + ui.section_head("Прошедшие")
                + '<div class="bookings-list">'
                + "".join(_render_card(b, ctx, upcoming=False) for b in past)
                + "</div></section>"
            )
        body = "".join(sections)

    from app.services.cabinet_badge import load_badges
    badges = await load_badges(db, user)
    # Числа — только настоящие: у человека без записей их нет.
    stats = ([("%d" % len(upcoming),
               plural(len(upcoming), "предстоящая", "предстоящие", "предстоящих")),
              ("%d" % len(past), "в истории")]
             if bookings else None)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Мои записи — руми</title>
    <meta name="robots" content="noindex, nofollow">
    {get_base_styles()}
</head>
<body class="page-body">
    {render_header("bookings", user)}

    <main class="main-content cabinet-main">
        {render_cabinet(
            user, "bookings", "Мои записи",
            "Предстоящие визиты и всё, что уже было.",
            notice_html + body,
            action=("Новая запись", "/salons"),
            stats=stats,
            badge=badges,
        )}
        {render_footer(user)}
    </main>

    {ui.sheet(
        '<p class="r-text" id="cancelWhat"></p>'
        '<p class="r-text r-muted">Время освободится, и его сможет занять другой '
        'клиент. Вернуть запись сможет только мастер.</p>'
        '<div class="sheet-actions">'
        + ui.button("Отменить запись", kind="danger", block=True,
                    element_id="cancelConfirm")
        + ui.button("Оставить запись", kind="secondary", block=True,
                    data={"sheet-close": "1"})
        + '</div>',
        element_id="cancelSheet", title="Отменить запись?")}

    {reschedule_sheet()}

    {ui.sheet(
        '<form id="reviewForm" enctype="multipart/form-data">'
        '<input type="hidden" id="reviewBookingId" name="booking_id">'
        '<input type="hidden" id="reviewSalonId" name="salon_id">'
        '<input type="hidden" id="reviewMasterId" name="master_id">'
        '<input type="hidden" id="reviewId" name="review_id">'
        '<div class="r-field">'
        '<span class="r-field__label" id="reviewRatingLabel">Оценка</span>'
        '<div class="review-stars" id="starRating" role="radiogroup"'
        ' aria-labelledby="reviewRatingLabel">'
        + "".join(
            f'<button type="button" class="review-star" data-value="{i}" role="radio"'
            f' aria-checked="false" aria-label="{i} из 5">{ICON_STAR_EMPTY}</button>'
            for i in range(1, 6)
        )
        + '</div>'
        '<input type="hidden" id="reviewRating" name="rating" value="0">'
        '<span class="r-field__error" id="reviewRatingError" role="alert"></span>'
        '</div>'
        '<div class="r-field">'
        '<label class="r-field__label" for="reviewComment">Комментарий</label>'
        '<textarea class="r-input" id="reviewComment" name="comment" rows="4"'
        ' placeholder="Что понравилось, что нет"></textarea>'
        '</div>'
        '<div class="r-field">'
        '<label class="r-field__label" for="reviewPhotos">Фото (до 5)</label>'
        '<input class="r-input" type="file" id="reviewPhotos" name="files"'
        ' accept="image/*" multiple>'
        '</div>'
        + ui.button("Отправить отзыв", type_="submit", block=True,
                    element_id="reviewSubmit", form="reviewForm")
        + '</form>',
        element_id="reviewSheet", title="Отзыв о визите")}
</body>
</html>"""


async def _render_sport_bookings_page(db: AsyncSession, user, notice: str = "") -> str:
    from app.models.sport import SportBooking, SportOrganization, SportTraining, SportCoach, SportService
    bookings = (await db.execute(
        select(SportBooking)
        .where(SportBooking.client_id == user.id)
        .order_by(SportBooking.start_time.desc().nulls_last(), SportBooking.created_at.desc())
    )).scalars().all()

    now = datetime.now()
    upcoming, past = [], []
    for b in bookings:
        is_upcoming = (
            b.status in ("pending", "confirmed") and
            (b.start_time is None or b.start_time > now)
        )
        if is_upcoming:
            upcoming.append(b)
        else:
            past.append(b)
    upcoming.reverse()

    org_ids = {b.organization_id for b in bookings}
    orgs = {}
    if org_ids:
        orgs = {o.id: o for o in (await db.execute(
            select(SportOrganization).where(SportOrganization.id.in_(org_ids))
        )).scalars().all()}

    training_ids = {b.training_id for b in bookings if b.training_id}
    trainings = {}
    if training_ids:
        trainings = {t.id: t for t in (await db.execute(
            select(SportTraining).where(SportTraining.id.in_(training_ids))
        )).scalars().all()}

    coach_ids = {b.coach_id for b in bookings if b.coach_id}
    coaches = {}
    if coach_ids:
        coaches = {c.id: c for c in (await db.execute(
            select(SportCoach).where(SportCoach.id.in_(coach_ids))
        )).scalars().all()}

    service_ids = {b.service_id for b in bookings if b.service_id}
    services = {}
    if service_ids:
        services = {s.id: s for s in (await db.execute(
            select(SportService).where(SportService.id.in_(service_ids))
        )).scalars().all()}

    def _render_sport_card(b):
        org = orgs.get(b.organization_id)
        org_name = org.name if org else "Спортивный клуб"
        org_link = f"/sport/{org.slug}" if org and org.slug else "/sport/clubs"
        tr = trainings.get(b.training_id)
        srv = services.get(b.service_id)
        title = tr.name if tr else (srv.name if srv else b.requested_discipline)
        coach = coaches.get(b.coach_id)
        coach_name = coach.name if coach else ""

        status_map = {
            "pending": ui.status("Заявка на рассмотрении", "warning"),
            "confirmed": ui.status("Запись подтверждена", "success"),
            "came": ui.status("Посещено", "neutral"),
            "cancelled": ui.status("Отменено", "danger"),
        }
        status_badge = status_map.get(b.status, ui.status(b.status, "neutral"))

        date_str = ""
        if b.start_time:
            date_str = b.start_time.strftime("%d.%m.%Y в %H:%M")
        elif b.requested_date:
            date_str = b.requested_date.strftime("%d.%m.%Y")

        facts = [
            ("Клуб", f'<a href="{org_link}">{e(org_name)}</a>'),
            ("Направление", e(b.requested_discipline)),
        ]
        if date_str:
            facts.append(("Время", date_str))
        if coach_name:
            facts.append(("Тренер", e(coach_name)))
        if b.requested_gym:
            facts.append(("Зал", e(b.requested_gym)))
        if b.price:
            facts.append(("Стоимость", f"{b.price:,}".replace(",", " ") + " ₽"))

        return (
            '<article class="booking-card">'
            '<header class="booking-card__head">'
            f'<span class="booking-card__time">{e(date_str or "Дата уточняется")}</span>'
            f'<span class="booking-card__status">{status_badge}</span>'
            '</header>'
            '<div class="booking-card__body">'
            f'<h2 class="booking-card__service">{e(title)}</h2>'
            f'<p class="booking-card__salon"><a href="{org_link}">{e(org_name)}</a></p>'
            + (f'<p class="booking-card__master">Тренер: {e(coach_name)}</p>' if coach_name else '')
            + '</div>'
            + f'{ui.facts(tuple(facts))}'
            '</article>'
        )

    to_catalog = ui.empty_state(
        "Предстоящих тренировок нет",
        text="Выберите спортивный клуб, направление и время — запись появится здесь.",
        action_label="Каталог клубов",
        action_href="/sport/clubs",
    )

    if not bookings:
        body = ui.empty_state(
            "Записей на тренировки пока нет",
            text="Здесь будут ваши визиты: предстоящие тренировки и прошедшие занятия.",
            action_label="Найти клуб",
            action_href="/sport/clubs",
        )
    else:
        upcoming_html = "".join(_render_sport_card(b) for b in upcoming) if upcoming else to_catalog
        sections = [
            '<section class="bookings-group">'
            + ui.section_head("Предстоящие")
            + f'<div class="bookings-list">{upcoming_html}</div>'
            + "</section>"
        ]
        if past:
            sections.append(
                '<section class="bookings-group">'
                + ui.section_head("Прошедшие")
                + '<div class="bookings-list">'
                + "".join(_render_sport_card(b) for b in past)
                + "</div></section>"
            )
        body = "".join(sections)

    from app.services.cabinet_badge import load_badges
    badges = await load_badges(db, user)
    stats = ([("%d" % len(upcoming), plural(len(upcoming), "предстоящая", "предстоящие", "предстоящих")),
              ("%d" % len(past), "в истории")] if bookings else None)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Мои записи — Руми Спорт</title>
    <meta name="robots" content="noindex, nofollow">
    {get_base_styles()}
</head>
<body class="page-body sport-directory">
    {render_header("sport_bookings", user)}

    <main class="main-content cabinet-main">
        {render_cabinet(
            user, "bookings", "Мои записи",
            "Предстоящие тренировки и история посещений клубов.",
            body,
            action=("Новая запись", "/sport/clubs"),
            stats=stats,
            badge=badges,
            sport=True,
        )}
        {render_footer(user, sport=True)}
    </main>
</body>
</html>"""

