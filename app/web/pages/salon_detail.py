# app/web/pages/salon_detail.py
"""Страница салона или частного мастера: слева представление, справа запись.

Заход «витрина» (решение 0011, п. 13). Главное, что изменилось: запись больше
не лежит длинной лентой шагов под отзывами — она всегда под рукой. На широком
экране это липкая колонка справа, на телефоне — закреплённая снизу кнопка,
поднимающая лист с тем же самым выбором. Разметка выбора ОДНА: скрипт
переносит её между колонкой и листом, потому что два экземпляра одних и тех же
полей — это два экземпляра одних и тех же id.

Второе: восемь из девяти салонов на проде — один человек, поэтому страница в
соло говорит о человеке («Записаться к Анне»), а не об организации. Подписи
берутся из ``app/services/public_words.py`` — одного реестра на все публичные
страницы, а не тернарниками по месту.

Третье: шаг «Напоминание» убран. Он предлагал выбрать «за 30 минут / за час /
за два / за день» и выключатель, а в запрос на создание брони эти значения не
уходили вообще (``BookingCreate`` их не принимает): напоминание ставится
сервером всегда за два часа и только тем, у кого подключён канал
(``notifications.REMINDER_BEFORE``). Обещать выбор, которого нет, нельзя;
вместо шага страница говорит, как оно работает на самом деле.
"""
import html
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Master, MasterPhoto, Promotion, Review, ReviewPhoto, ReviewTargetType,
    Salon, SalonChain, SalonModerationStatus, SalonPhoto, Service, User,
)
from app.services.loyalty_service import LoyaltyService
from app.services.public_words import words_for
from app.services.schedule_utils import MAX_BOOKING_DAYS_AHEAD, format_working_hours_summary
from app.services.subscription import access_clause
from app.web.components import ui
from app.web.components.escaping import e, ejson
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import (
    ICON_ARROW_LEFT,
    ICON_CIRCLE_CHECK,
    ICON_CLOCK,
    ICON_FLAG,
    ICON_GIFT,
    ICON_HEART,
    ICON_HEART_FILLED,
    ICON_MAP_PIN,
    ICON_PHONE,
    ICON_STAR_EMPTY,
    ICON_STAR_FILLED,
    ICON_TROPHY,
    ICON_X,
)
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.yandex_maps import render_yandex_maps_script, yandex_maps_enabled

#: Якорь колонки записи. По нему же приходит ссылка из карточки каталога:
#: /salons/1?master=2&service=3&slot=2026-10-04T15:00#booking
BOOKING_ANCHOR = "booking"


def _reminder_channel_hint(user) -> str:
    """Напоминание некуда прислать — говорим об этом и предлагаем подключить.

    Пустая строка, если канал есть или человек не вошёл: подсказка нужна ровно
    тому, кого она касается. Запись НЕ блокируем — человек пришёл записаться, а
    не настраивать уведомления.

    VK_START_HINT обязателен: ВКонтакте показывает кнопку «Начать» только в
    пустом диалоге, и кто уже писал сообществу, её не увидит. 16 и 17 сентября
    на этом застряли двое, поэтому про код со страницы привязки сказано ДО
    перехода во ВКонтакте.
    """
    if user is None:
        return ""
    from app.core.config import settings
    from app.services.notify_channel import has_channel
    from app.web.pages.profile import VK_START_HINT

    if has_channel(user):
        return ""

    buttons = []
    if settings.vk_bot_address:
        buttons.append(
            '<form method="post" action="/api/v1/users/me/vk-connect" target="_blank">'
            + ui.button("Подключить ВКонтакте", kind="secondary", type_="submit", small=True)
            + "</form>"
        )
    if settings.TG_BOT_USERNAME:
        buttons.append(ui.button(
            "Подключить Telegram", kind="secondary", small=True,
            href=f"https://t.me/{e(settings.TG_BOT_USERNAME)}",
        ))
    if settings.MAX_BOT_USERNAME:
        buttons.append(ui.button(
            "Подключить MAX", kind="secondary", small=True,
            href=f"https://max.ru/{e(settings.MAX_BOT_USERNAME)}",
        ))
    tail = f"<p>{VK_START_HINT}</p>" if settings.vk_bot_address else ""
    return (
        "<p>Напоминание сейчас некуда прислать: у вас не подключён ни мессенджер, "
        "ни почта. Записаться можно и без этого.</p>"
        f'<div class="book__note-act">{"".join(buttons)}</div>{tail}'
    )


def _reminder_note(user) -> str:
    """Как работает напоминание — одним абзацем и правдиво.

    Время задано сервером (``notifications.REMINDER_BEFORE``), а не выбором на
    странице: прежний шаг предлагал «за 30 минут / за час / за два / за день»,
    и ни одно из этих значений никуда не уходило.
    """
    base = "Напомним за два часа до визита."
    hint = _reminder_channel_hint(user)
    if hint:
        return f'<div class="book__note" role="note"><p>{base}</p>{hint}</div>'
    if user is None:
        base += (" Напоминание приходит в мессенджер или на почту — их можно"
                 " подключить в профиле после входа.")
    return f'<p class="book__note">{base}</p>'


async def _load_masters(db: AsyncSession, salon_id: int):
    """Мастера салона с именами, портфолио и услугами — четырьмя запросами на
    всех, а не тремя на каждого.

    Раньше здесь был цикл с тремя запросами внутри: на салон с пятью мастерами
    это пятнадцать кругов до базы на каждое открытие страницы.
    """
    masters = (await db.execute(
        select(Master).where(Master.salon_id == salon_id, Master.is_active == True)  # noqa: E712
    )).scalars().all()
    if not masters:
        return [], []

    ids = [m.id for m in masters]
    users = {
        u.id: u for u in (await db.execute(
            select(User).where(User.id.in_([m.user_id for m in masters]))
        )).scalars().all()
    }

    photos: dict[int, list[str]] = {}
    for ph in (await db.execute(
        select(MasterPhoto).where(MasterPhoto.master_id.in_(ids)).order_by(MasterPhoto.id.desc())
    )).scalars().all():
        photos.setdefault(ph.master_id, []).append(ph.url)

    # Услуга принадлежит мастеру напрямую (master_id) либо назначена ему
    # (service_masters) — оба случая нужны, иначе назначенные услуги исчезают
    # из выбора у всех, кроме владельца услуги.
    services = (await db.execute(
        select(Service).options(
            selectinload(Service.photos), selectinload(Service.assigned_masters)
        ).where(
            or_(Service.master_id.in_(ids), Service.assigned_masters.any(Master.id.in_(ids))),
            Service.is_active == True, Service.is_model_practice == False,  # noqa: E712
        ).order_by(Service.price, Service.id)
    )).scalars().all()

    by_master: dict[int, list[dict]] = {}
    for s in services:
        payload = {
            "id": s.id, "name": s.name, "price": s.price, "price_max": s.price_max,
            "duration": s.duration_minutes,
            "photos": [photo.url for photo in s.photos],
        }
        targets = {s.master_id} | {m.id for m in s.assigned_masters}
        for mid in targets & set(ids):
            by_master.setdefault(mid, []).append(payload)

    out = []
    for m in masters:
        mu = users.get(m.user_id)
        out.append({
            "id": m.id,
            "name": (mu.full_name if mu else None) or "Мастер",
            "specialization": m.specialization or "",
            "experience": m.experience_years or 0,
            "rating": m.rating or 0.0,
            "avatar": (mu.avatar_url if mu else "") or "",
            "portfolio": photos.get(m.id, []),
            "services": by_master.get(m.id, []),
        })
    # Вторым значением — те же мастера объектами: по ним public_words решает
    # «соло или команда», и повторная выборка ради этого была бы лишним кругом.
    return out, masters


async def _load_reviews(db: AsyncSession, salon_id: int, user=None) -> str:
    """Отзывы с подписями «о кого» — тремя запросами на весь список.

    Раньше на каждый отзыв уходило до трёх запросов (клиент, мастер, сотрудник)
    плюс один на фотографии: десять отзывов = до сорока кругов до базы.
    """
    reviews = (await db.execute(
        select(Review).where(Review.salon_id == salon_id)
        .order_by(Review.created_at.desc()).limit(10)
    )).scalars().all()
    if not reviews:
        return ""

    user_ids = {r.client_id for r in reviews} | {
        r.staff_user_id for r in reviews if r.staff_user_id
    }
    names = {
        u.id: (u.full_name or "Клиент") for u in (await db.execute(
            select(User).where(User.id.in_(user_ids))
        )).scalars().all()
    }
    master_names = dict((await db.execute(
        select(Master.id, User.full_name).join(User, User.id == Master.user_id)
        .where(Master.id.in_({r.master_id for r in reviews if r.master_id}))
    )).all()) if any(r.master_id for r in reviews) else {}

    photos: dict[int, list[ReviewPhoto]] = {}
    for ph in (await db.execute(
        select(ReviewPhoto).where(ReviewPhoto.review_id.in_([r.id for r in reviews]))
    )).scalars().all():
        photos.setdefault(ph.review_id, []).append(ph)

    labels = {
        ReviewTargetType.MASTER: "Мастер",
        ReviewTargetType.SALON: "Салон",
        ReviewTargetType.STAFF: "Сотрудник",
    }

    out = ""
    for r in reviews:
        label = labels.get(r.target_type, "")
        if r.target_type == ReviewTargetType.MASTER and r.master_id:
            label += f": {e(master_names.get(r.master_id) or '')}"
        elif r.target_type == ReviewTargetType.STAFF and r.staff_user_id:
            label += f": {e(names.get(r.staff_user_id) or '')}"

        stars = ICON_STAR_FILLED * r.rating + ICON_STAR_EMPTY * (5 - r.rating)
        date_str = r.created_at.strftime("%d.%m.%Y") if r.created_at else ""
        verified = (
            ui.status("Подтверждено записью", "success", icon=ICON_CIRCLE_CHECK)
            if r.is_verified else ui.status("Без подтверждения", "neutral")
        )

        shots = ""
        items = photos.get(r.id, [])
        if items:
            tiles = ""
            for ph in items:
                tiles += (
                    f'<div class="review-photo-item">'
                    f'<img src="{e(ph.url)}" alt="" loading="lazy" '
                    f'data-lightbox-src="{e(ph.url)}" data-lightbox-alt="Фото из отзыва">'
                    + (f'<button class="review-photo-delete" data-review-id="{r.id}" '
                       f'data-photo-id="{ph.id}" title="Удалить фото">{ICON_X}</button>'
                       if user is not None and user.id == r.client_id else "")
                    + f'<button class="review-photo-report" data-photo-id="{ph.id}" '
                      f'title="Пожаловаться">{ICON_FLAG}</button>'
                    + "</div>"
                )
            shots = f'<div class="review-photos">{tiles}</div>'

        out += f"""
            <article class="review-item" data-target-type="{r.target_type.value}"
                     data-verified="{'1' if r.is_verified else '0'}">
                <div class="review-header">
                    <strong class="review-author">{e(names.get(r.client_id) or 'Клиент')}</strong>
                    <span class="review-date tabular-nums">{date_str}</span>
                </div>
                <div class="review-marks">{ui.status(label, "neutral")}{verified}</div>
                <div class="review-stars" aria-label="Оценка {r.rating} из 5">{stars}</div>
                <p class="review-text">{e(r.comment or 'Без комментария')}</p>
                {shots}
            </article>"""
    return out


def _booking_widget(*, salon, masters_data, user, w, solo, preset: dict) -> str:
    """Выбор услуги и времени — ОДНА разметка на колонку и на лист.

    Шаги рисует static/src/js/salon-booking.js из data-masters: держать в
    разметке четыре скрытые копии сводки (как было раньше — пять шагов с
    пятью наборами «хлебных крошек» и дублями id вида
    selected-master-name-4) значило переписывать её на каждом шаге в пяти
    местах и расходиться в одном из них.
    """
    title = w("book_panel_title") or "Запись"
    user_payload = {"id": user.id, "full_name": user.full_name, "phone": user.phone} if user else None
    return f"""
<div class="book" id="bookingWidget"
     data-salon-id="{salon.id}"
     data-solo="{'1' if solo else '0'}"
     data-max-days="{MAX_BOOKING_DAYS_AHEAD}"
     data-masters='{ejson(masters_data)}'
     data-user='{ejson(user_payload)}'
     data-preset='{ejson(preset)}'
     data-done='{e(w("guest_done"))}'>
    <div class="book__head">
        <h2 class="book__title">{title}</h2>
        <p class="book__hint">{w("book_panel_hint")}</p>
    </div>
    <button class="book__back" type="button" data-book-back hidden>
        {ICON_ARROW_LEFT}<span data-book-back-label>Назад</span>
    </button>
    <div class="book__body" id="bookBody" aria-live="polite"></div>
    <noscript><p class="book__note">Выбор времени требует включённого JavaScript.
        Позвоните, пожалуйста: {e(salon.phone or "телефон не указан")}.</p></noscript>
    {_reminder_note(user)}
</div>"""


async def render_salon_detail(db: AsyncSession, salon_id: int, user=None,
                              preset: dict | None = None) -> str:
    # Публично видны только одобренные активные салоны (модерация регистрации).
    salon = (await db.execute(select(Salon).where(
        Salon.id == salon_id,
        Salon.is_active == True,  # noqa: E712
        Salon.moderation_status == SalonModerationStatus.APPROVED,
        Salon.published_at.isnot(None),
        access_clause(Salon),  # тариф: доступ открыт
        Salon.is_hidden == False,  # noqa: E712
    ))).scalar_one_or_none()

    if not salon:
        return _not_found()

    masters_data, masters_orm = await _load_masters(db, salon.id)
    holder = masters_data[0]["name"] if masters_data else ""
    w, solo = words_for(salon, masters_orm, holder)

    promotions = (await db.execute(
        select(Promotion).where(Promotion.salon_id == salon.id, Promotion.is_active == True)  # noqa: E712
    )).scalars().all()

    verified_count = (await db.execute(
        select(func.count(Review.id)).where(
            Review.salon_id == salon.id, Review.is_verified == True,  # noqa: E712
        )
    )).scalar() or 0

    reviews_html = await _load_reviews(db, salon.id, user)

    salon_photos = (await db.execute(
        select(SalonPhoto).where(SalonPhoto.salon_id == salon.id).order_by(SalonPhoto.id)
    )).scalars().all()
    # Обложка идёт первой: она же стоит в карточке каталога.
    salon_photos = sorted(salon_photos, key=lambda p: p.url != salon.logo_url)

    # ---------- Лояльность (видна до записи; её даёт салон, не Руми) ----------
    loyalty_html = ""
    if user:
        loyalty = await LoyaltyService.get_client_status(db, salon.id, user.id)
        chips = []
        if loyalty["is_regular_client"] and loyalty["regular_client_discount_percent"] > 0:
            chips.append(ui.status(
                f'Постоянный клиент −{loyalty["regular_client_discount_percent"]}%',
                "success", icon=ICON_TROPHY))
        if loyalty["personal_discount_percent"]:
            chips.append(ui.status(
                f'Ваша скидка −{loyalty["personal_discount_percent"]}%',
                "accent", icon=ICON_GIFT))
        if loyalty["bonus_points"] > 0:
            chips.append(ui.status(f'{loyalty["bonus_points"]} баллов', "neutral",
                                   icon=ICON_STAR_FILLED))
        if chips:
            loyalty_html = f'<div class="salon-marks">{"".join(chips)}</div>'

    # ---------- Другие адреса сети ----------
    chain_html = ""
    if salon.chain_id is not None:
        chain = (await db.execute(
            select(SalonChain).where(SalonChain.id == salon.chain_id)
        )).scalar_one_or_none()
        siblings = (await db.execute(select(Salon).where(
            Salon.chain_id == salon.chain_id,
            Salon.id != salon.id,
            Salon.is_active == True,  # noqa: E712
            Salon.moderation_status == SalonModerationStatus.APPROVED,
            Salon.published_at.isnot(None),
            access_clause(Salon),
            Salon.is_hidden == False,  # noqa: E712
        ).order_by(Salon.name))).scalars().all()
        if chain and siblings:
            links = "".join(
                f'<a class="salon-chain__link" href="/salons/{s.id}">'
                f'{ICON_MAP_PIN}{e(s.address or s.name)}</a>'
                for s in siblings
            )
            chain_html = f"""
            <section class="salon-block salon-chain">
                <h2 class="r-subtitle">Сеть «{e(chain.name)}»</h2>
                <div class="salon-chain__links">{links}</div>
            </section>"""

    # ---------- Карта ----------
    map_html = ""
    if yandex_maps_enabled():
        map_html = (
            f'<div id="salonMap" class="salon-map"'
            f' data-lat="{salon.latitude}" data-lon="{salon.longitude}"'
            f' data-title="{html.escape(salon.name, quote=True)}"></div>'
        )

    heart = ICON_HEART.replace('"', "&quot;")
    heart_filled = ICON_HEART_FILLED.replace('"', "&quot;")

    # ---------- Шапка страницы ----------
    rating_html = ""
    if (salon.rating or 0) > 0:
        total = salon.reviews_count or 0
        counts = (
            f'<span class="rating-count">{total} отзывов, '
            f'{verified_count} подтверждено</span>' if total else ""
        )
        rating_html = (
            f'<span class="salon-rating" title="{verified_count} из {total} '
            f'отзывов подтверждены реальной записью">'
            f'{ICON_STAR_FILLED}<span class="rating-val">{salon.rating:.1f}</span>'
            f'{counts}</span>'
        )

    # В соло вторая строка называет человека — но только если название страницы
    # не повторяет его имя (у частных мастеров салон обычно назван своим именем,
    # и «Анна Смирнова / Анна Смирнова» читается как ошибка).
    who = ""
    if solo and masters_data:
        m = masters_data[0]
        bits = [m["specialization"]] if m["specialization"] else []
        if m["experience"]:
            bits.append(f'опыт {m["experience"]} лет')
        name_part = m["name"] if m["name"].strip().lower() != (salon.name or "").strip().lower() else ""
        line = " · ".join([p for p in [name_part] if p] + bits)
        if line:
            who = f'<p class="salon-who">{e(line)}</p>'

    badges = []
    if salon.contest_winner_until and salon.contest_winner_until > datetime.now(
        salon.contest_winner_until.tzinfo
    ):
        badges.append(ui.status("Победитель конкурса Руми", "accent"))
    badges_html = f'<div class="salon-marks">{"".join(badges)}</div>' if badges else ""

    # Акции — строками, а не плашками: это предложение целиком («Новым
    # клиентам» плюс «Скидка первым посетителям 20%»), и в пилюле такой текст
    # не переносится и уезжает за край.
    promos_html = ""
    if promotions:
        items = "".join(
            f'<li><span class="salon-promo__tag">{e(p.tag)}</span>{e(p.title)}'
            + (f'<small>{e(p.description)}</small>' if (p.description or "").strip() else "")
            + "</li>"
            for p in promotions[:3]
        )
        promos_html = f'<ul class="salon-promos">{items}</ul>' 

    desc = (salon.description or "").strip()
    about_html = ""
    if desc:
        about_html = f"""
            <section class="salon-block">
                <h2 class="r-subtitle">{w("about_title")}</h2>
                <p class="r-text salon-about">{e(desc)}</p>
            </section>"""

    photos_html = ""
    if salon_photos:
        shots = "".join(
            f'<img src="{e(p.url)}" alt="Фото работы" loading="lazy" decoding="async" '
            f'data-lightbox-src="{e(p.url)}" data-lightbox-alt="Фото работы" '
            f'data-lightbox-group="salon-{salon.id}">'
            for p in salon_photos
        )
        photos_html = f"""
            <section class="salon-block">
                <h2 class="r-subtitle">{w("photos_title")}</h2>
                <div class="salon-photos">{shots}</div>
            </section>"""

    # ---------- Команда (в соло раздела нет) ----------
    team_html = ""
    if not solo and masters_data:
        cards = ""
        for m in masters_data:
            shots = "".join(
                f'<img src="{e(url)}" alt="Работа мастера" loading="lazy" '
                f'data-lightbox-src="{e(url)}" data-lightbox-alt="Работа мастера" '
                f'data-lightbox-group="master-{m["id"]}">'
                for url in m["portfolio"][:4]
            )
            meta = " · ".join(p for p in (
                m["specialization"],
                f'опыт {m["experience"]} лет' if m["experience"] else "",
            ) if p)
            cards += f"""
                <article class="team-card">
                    <div class="team-card__top">
                        {ui.mark(m["name"], image=m["avatar"], alt=m["name"], size="lg")}
                        <div class="team-card__id">
                            <a class="team-card__name" href="/masters/{m["id"]}">{e(m["name"])}</a>
                            <p class="team-card__meta">{e(meta)}</p>
                        </div>
                        <button class="favorite-btn master-fav-btn team-card__fav" type="button"
                                data-type="master" data-id="{m["id"]}"
                                data-icon-heart="{heart}" data-icon-heart-filled="{heart_filled}"
                                aria-label="В избранное" title="В избранное">
                            <span class="heart-icon">{ICON_HEART}</span>
                        </button>
                    </div>
                    {f'<div class="team-card__shots">{shots}</div>' if shots else ''}
                    {ui.button("Записаться", kind="secondary", small=True,
                               data={"book-master": m["id"]})}
                </article>"""
        team_html = f"""
            <section class="salon-block" id="team">
                <h2 class="r-subtitle">{w("team_title")}</h2>
                <div class="team-grid">{cards}</div>
            </section>"""

    booking = _booking_widget(
        salon=salon, masters_data=masters_data, user=user, w=w, solo=solo,
        preset=preset or {},
    )
    has_services = any(m["services"] for m in masters_data)
    if not has_services:
        booking = ui.empty_state(w("no_services"),
                                 text="Как только услуги появятся, здесь откроется запись.")

    cta = w("book_cta") or "Записаться"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>{e(salon.name)} | руми</title>
    {get_base_styles()}
    {render_yandex_maps_script()}
</head>
<body class="page-body salon-page">
    {render_header("salons")}
    {render_sidebar("salons", user)}

    <div class="main-wrapper">
        <main>
            <div class="section-container">
                <a class="salon-back" href="/salons">{ICON_ARROW_LEFT}Все салоны</a>

                <div class="salon-cols">
                    <div class="salon-main">
                        <header class="salon-head">
                            <div class="salon-head__top">
                                {ui.mark(salon.name, image=salon.logo_url or "",
                                         alt=salon.name, size="xl")}
                                <div class="salon-head__id">
                                    <h1 class="r-display salon-title">{e(salon.name)}</h1>
                                    {who}
                                    <p class="salon-where">{e(" · ".join(p for p in (
                                        w("catalog_kind"), salon.city or "") if p))}</p>
                                </div>
                                <button class="favorite-btn salon-top-fav" type="button"
                                        data-type="salon" data-id="{salon.id}"
                                        data-icon-heart="{heart}"
                                        data-icon-heart-filled="{heart_filled}"
                                        aria-label="В избранное" title="В избранное">
                                    <span class="heart-icon">{ICON_HEART}</span>
                                </button>
                            </div>
                            {rating_html}
                            {badges_html}
                            {promos_html}
                            {loyalty_html}
                            <dl class="salon-facts">
                                <div><dt>{ICON_MAP_PIN}Адрес</dt>
                                     <dd>{e(salon.address or 'не указан')}</dd></div>
                                <div><dt>{ICON_PHONE}Телефон</dt>
                                     <dd>{e(salon.phone or '—')}</dd></div>
                                <div><dt>{ICON_CLOCK}{w("hours_label")}</dt>
                                     <dd>{format_working_hours_summary(salon.working_hours)}</dd></div>
                            </dl>
                            {map_html}
                        </header>

                        {about_html}
                        {photos_html}
                        {team_html}
                        {chain_html}

                        <section class="salon-block" id="reviews">
                            <h2 class="r-subtitle">{w("reviews_title")}</h2>
                            {_reviews_filter() if reviews_html else ''}
                            <div class="reviews-list">
                                {reviews_html or f'<p class="r-text r-muted">{w("reviews_empty")}</p>'}
                            </div>
                        </section>
                    </div>

                    <aside class="salon-aside" id="{BOOKING_ANCHOR}">
                        <div class="salon-aside__host" id="bookingHost">
                            {booking}
                        </div>
                    </aside>
                </div>
            </div>

            {render_footer(user)}
        </main>
    </div>

    {ui.dock(ui.button(cta, block=True, data={"sheet-open": "bookSheet"}),
             element_id="bookDock") if has_services else ''}
    {ui.sheet('<div id="bookingSheetHost"></div>', element_id="bookSheet", title=cta)
     if has_services else ''}

    <script>
        window.salonId = {salon.id};
        window.maxBookingDays = {MAX_BOOKING_DAYS_AHEAD};
    </script>
    {_reviews_script()}
</body>
</html>"""


def _not_found() -> str:
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Салон не найден | руми</title>{get_base_styles()}</head>
<body><main class="section-container" style="padding:4rem 1rem">
{ui.empty_state("Такой страницы нет",
                text="Салон закрыт, скрыт владельцем или ссылка устарела.",
                action_label="Открыть каталог", action_href="/salons")}
</main></body></html>"""


def _reviews_filter() -> str:
    """Фильтр отзывов. Кнопки, а не ссылки: они ничего не открывают."""
    kinds = [("all", "Все"), ("master", "О мастерах"), ("salon", "О салоне"),
             ("staff", "О сотрудниках"), ("verified", "Только подтверждённые")]
    return (
        '<div class="review-filters" role="group" aria-label="Фильтр отзывов">'
        + "".join(
            f'<button type="button" class="review-filter-btn{" is-active" if k == "all" else ""}" '
            f'data-filter="{k}">{label}</button>'
            for k, label in kinds
        )
        + "</div>"
    )


def _reviews_script() -> str:
    """Фильтр отзывов и жалоба на фото.

    Инлайновый скрипт: CSP запрещает внешние источники, но inline разрешён, а
    тащить двадцать строк в бандл ради одной страницы незачем.
    """
    return """
    <script>
    (function () {
        document.querySelectorAll('.review-filter-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                document.querySelectorAll('.review-filter-btn')
                    .forEach(function (b) { b.classList.remove('is-active'); });
                btn.classList.add('is-active');
                var kind = btn.dataset.filter;
                document.querySelectorAll('.review-item').forEach(function (el) {
                    var show = true;
                    if (kind === 'verified') show = el.dataset.verified === '1';
                    else if (kind !== 'all') show = el.dataset.targetType === kind;
                    el.hidden = !show;
                });
            });
        });
        document.addEventListener('click', async function (ev) {
            var del = ev.target.closest('.review-photo-delete');
            if (del) {
                if (!confirm('Удалить это фото?')) return;
                var r = await fetch('/api/v1/upload/review/' + del.dataset.reviewId +
                                    '/photo/' + del.dataset.photoId + '/delete',
                                    { method: 'POST' });
                if (r.ok) location.reload(); else alert('Не удалось удалить фото');
                return;
            }
            var btn = ev.target.closest('.review-photo-report');
            if (!btn) return;
            var reason = prompt('Опишите проблему с этим фото (необязательно):', '');
            if (reason === null) return;
            var body = new URLSearchParams({ review_photo_id: btn.dataset.photoId,
                                             reason: reason || '' });
            var res = await fetch('/api/v1/reports/photo', { method: 'POST', body: body });
            alert(res.ok ? 'Жалоба отправлена, спасибо' : 'Не удалось отправить жалобу');
        });
    })();
    </script>"""
