# app/web/pages/master_detail.py
"""Страница мастера: слева работы и услуги, справа запись.

Та же раскладка и тот же виджет записи, что на странице салона (решение 0011,
п. 13): липкая колонка на широком экране, лист снизу на телефоне. Страница
мастера говорит о человеке всегда — поэтому подписи берутся из того же реестра
``public_words`` с ``solo=True``, а не пишутся здесь во второй раз.

Раньше вся эта страница была набором инлайновых стилей в f-строках (ширины в
rem, градиентные заглушки под аватар, цвета мимо токенов) и записи на ней не
было вовсе — только кнопка «Записаться», ведущая обратно на салон.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.api.deps import check_salon_permission
from app.models.models import (
    Master, MasterPhoto, Review, ReviewPhoto, ReviewTargetType, Salon, Service, User,
)
from app.services.price import format_service_price
from app.services.public_words import dative, first_name, word
from app.services.schedule_utils import MAX_BOOKING_DAYS_AHEAD
from app.web.components import ui
from app.web.components.escaping import e, ejson
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import (
    ICON_ARROW_LEFT, ICON_HEART, ICON_HEART_FILLED, ICON_STAR_FILLED, ICON_X,
)
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles

#: Сколько своих фото мастер может держать в портфолио (подпись на кнопке).
PORTFOLIO_LIMIT = 20


def _upload_block(master_id: int, own_count: int) -> str:
    """Загрузка фото — видна только тому, кто имеет право ею пользоваться.

    Это кусок панели, живущий на публичной странице; он был здесь до захода, и
    выносить его сейчас значило бы трогать бизнесовый мир, у которого свой
    заход. Форма приведена к слою компонентов, поведение не менялось.
    """
    return f"""
        <div class="master-manage">
            <input type="file" id="masterAvatarInput" accept="image/*" hidden>
            {ui.button("Изменить фото мастера", kind="secondary", small=True,
                       element_id="masterAvatarBtn")}
            <input type="file" id="portfolioFileInput" accept="image/*" multiple hidden>
            {ui.button(f"Добавить фото ({own_count}/{PORTFOLIO_LIMIT})", kind="secondary",
                       small=True, element_id="portfolioBtn")}
        </div>
        <script>
        (function () {{
            var masterId = '{master_id}';
            function pick(btnId, inputId) {{
                var b = document.getElementById(btnId), i = document.getElementById(inputId);
                if (b && i) b.addEventListener('click', function () {{ i.click(); }});
            }}
            pick('masterAvatarBtn', 'masterAvatarInput');
            pick('portfolioBtn', 'portfolioFileInput');

            async function send(url, form) {{
                var res = await fetch(url, {{ method: 'POST', body: form }});
                if (res.ok) {{ location.reload(); return; }}
                var d = await res.json().catch(function () {{ return {{}}; }});
                alert(d.detail || 'Не удалось загрузить фото');
            }}
            var avatar = document.getElementById('masterAvatarInput');
            if (avatar) avatar.addEventListener('change', function (ev) {{
                var f = ev.target.files[0];
                if (!f) return;
                var form = new FormData();
                form.append('file', f);
                form.append('master_id', masterId);
                send('/api/v1/upload/avatar', form);
            }});
            var many = document.getElementById('portfolioFileInput');
            if (many) many.addEventListener('change', function (ev) {{
                if (!ev.target.files.length) return;
                var form = new FormData();
                for (var i = 0; i < ev.target.files.length; i++)
                    form.append('files', ev.target.files[i]);
                form.append('master_id', masterId);
                send('/api/v1/upload/master/photo', form);
            }});
            document.addEventListener('click', async function (ev) {{
                var btn = ev.target.closest('.portfolio-photo-delete');
                if (!btn) return;
                if (!confirm('Удалить это фото?')) return;
                var form = new FormData();
                form.append('master_id', masterId);
                var res = await fetch(btn.dataset.url, {{ method: 'POST', body: form }});
                if (res.ok) location.reload(); else alert('Не удалось удалить фото');
            }});
        }})();
        </script>"""


def _tiles(urls, delete_urls=None) -> str:
    """Плитка работ. Фото — настоящее содержание страницы, поэтому крупное."""
    out = ""
    for url in urls:
        del_url = (delete_urls or {}).get(url)
        btn = (
            f'<button class="portfolio-photo-delete" data-url="{e(del_url)}" '
            f'title="Удалить фото" aria-label="Удалить фото">{ICON_X}</button>'
            if del_url else ""
        )
        out += (
            '<div class="shot">'
            f'<img src="{e(url)}" alt="Работа мастера" loading="lazy" decoding="async" '
            f'data-lightbox-src="{e(url)}" data-lightbox-alt="Работа мастера" '
            f'data-lightbox-group="master-works">{btn}</div>'
        )
    return out


async def render_master_detail(db: AsyncSession, master_id: int, user=None,
                               preset: dict | None = None) -> str:
    """Страница конкретного мастера."""
    master = (await db.execute(
        select(Master).where(Master.id == master_id)
    )).scalar_one_or_none()
    if not master:
        return _not_found()

    master_user = (await db.execute(
        select(User).where(User.id == master.user_id)
    )).scalar_one_or_none()
    master_name = (master_user.full_name if master_user else None) or "Мастер"
    avatar = (master_user.avatar_url if master_user else "") or ""

    salon = (await db.execute(
        select(Salon).where(Salon.id == master.salon_id)
    )).scalar_one_or_none()

    services = (await db.execute(
        select(Service).options(selectinload(Service.photos)).where(
            or_(
                Service.master_id == master.id,
                Service.assigned_masters.any(Master.id == master.id),
            ),
            Service.is_active == True, Service.is_model_practice == False,  # noqa: E712
        ).order_by(Service.price, Service.id)
    )).scalars().all()

    # ---------- Права на фото ----------
    can_manage = bool(user and master_user and user.id == master_user.id)
    if user and not can_manage:
        try:
            await check_salon_permission(db, user, master.salon_id, "manage_masters")
            can_manage = True
        except HTTPException:
            pass

    own_photos = (await db.execute(
        select(MasterPhoto).where(MasterPhoto.master_id == master.id)
        .order_by(MasterPhoto.id.desc())
    )).scalars().all()
    client_photos = (await db.execute(
        select(ReviewPhoto).join(Review, Review.id == ReviewPhoto.review_id).where(
            Review.master_id == master.id,
            Review.target_type == ReviewTargetType.MASTER,
        ).order_by(ReviewPhoto.id.desc())
    )).scalars().all()

    verified_count = (await db.execute(select(func.count(Review.id)).where(
        Review.master_id == master.id,
        Review.target_type == ReviewTargetType.MASTER,
        Review.is_verified == True,  # noqa: E712
    ))).scalar() or 0
    reviews_total = (await db.execute(select(func.count(Review.id)).where(
        Review.master_id == master.id,
        Review.target_type == ReviewTargetType.MASTER,
    ))).scalar() or 0

    # ---------- Подписи: страница мастера всегда о человеке ----------
    name_dative = dative(first_name(master_name))

    def w(key: str) -> str:
        return word(key, solo=True, name=name_dative)

    cta = w("book_cta") or "Записаться"

    # ---------- Услуги ----------
    services_html = ""
    if services:
        rows = "".join(
            ui.service_line(
                s.name,
                price=format_service_price(s.price, s.price_max),
                duration=f"{s.duration_minutes} мин",
            )
            for s in services
        )
        services_html = f"""
            <section class="salon-block">
                <h2 class="r-subtitle">{w("services_title")}</h2>
                <ul class="r-svc">{rows}</ul>
            </section>"""
    else:
        services_html = f"""
            <section class="salon-block">
                <h2 class="r-subtitle">{w("services_title")}</h2>
                <p class="r-text r-muted">{w("no_services")}</p>
            </section>"""

    delete_urls = {}
    if can_manage:
        delete_urls = {
            p.url: f"/api/v1/upload/master/photo/{p.id}/delete" for p in own_photos
        }

    own_tiles = _tiles([p.url for p in own_photos], delete_urls)
    client_tiles = _tiles([p.url for p in client_photos])

    works_html = ""
    if own_tiles or client_tiles or can_manage:
        parts = ""
        if can_manage:
            parts += _upload_block(master.id, len(own_photos))
        if own_tiles:
            parts += f'<div class="shots">{own_tiles}</div>'
        elif can_manage:
            parts += '<p class="r-text r-muted">Фото пока нет — добавьте первое.</p>'
        if client_tiles:
            parts += ('<h3 class="master-works__sub">Из отзывов клиентов</h3>'
                      f'<div class="shots">{client_tiles}</div>')
        works_html = f"""
            <section class="salon-block">
                <h2 class="r-subtitle">{w("photos_title")}</h2>
                {parts}
            </section>"""

    # ---------- Виджет записи: тот же, что на странице салона ----------
    masters_data = [{
        "id": master.id,
        "name": master_name,
        "specialization": master.specialization or "",
        "experience": master.experience_years or 0,
        "rating": master.rating or 0.0,
        "avatar": avatar,
        "portfolio": [p.url for p in own_photos],
        "services": [
            {
                "id": s.id, "name": s.name, "price": s.price, "price_max": s.price_max,
                "duration": s.duration_minutes, "photos": [ph.url for ph in s.photos],
            }
            for s in services
        ],
    }]
    user_payload = {"id": user.id, "full_name": user.full_name, "phone": user.phone} if user else None

    booking = f"""
<div class="book" id="bookingWidget"
     data-salon-id="{master.salon_id}"
     data-solo="1"
     data-max-days="{MAX_BOOKING_DAYS_AHEAD}"
     data-masters='{ejson(masters_data)}'
     data-user='{ejson(user_payload)}'
     data-preset='{ejson(preset or {})}'
     data-done='{e(w("guest_done"))}'>
    <div class="book__head">
        <h2 class="book__title">{w("book_panel_title") or "Запись"}</h2>
        <p class="book__hint">{w("book_panel_hint")}</p>
    </div>
    <button class="book__back" type="button" data-book-back hidden>
        {ICON_ARROW_LEFT}<span data-book-back-label>Назад</span>
    </button>
    <div class="book__body" id="bookBody" aria-live="polite"></div>
    <noscript><p class="book__note">Выбор времени требует включённого JavaScript.
        Откройте <a href="/salons/{master.salon_id}">страницу салона</a> — там есть телефон.</p></noscript>
</div>"""
    if not services:
        booking = ui.empty_state(
            w("no_services"), text="Как только услуги появятся, здесь откроется запись.")

    meta = " · ".join(p for p in (
        master.specialization or "",
        f"опыт {master.experience_years} лет" if master.experience_years else "",
    ) if p)

    # «0 из 0 подтверждено» рядом с оценкой — это не информация, а строка,
    # которую нечем заполнить: при отсутствии отзывов показываем только оценку.
    rating_html = ""
    if (master.rating or 0) > 0:
        counts = (
            f'<span class="rating-count">{verified_count} из {reviews_total} '
            f'подтверждено</span>' if reviews_total else ""
        )
        rating_html = (
            f'<span class="salon-rating" title="{verified_count} из {reviews_total} '
            f'отзывов подтверждены реальной записью">{ICON_STAR_FILLED}'
            f'<span class="rating-val">{master.rating:.1f}</span>{counts}</span>'
        )

    heart = ICON_HEART.replace('"', "&quot;")
    heart_filled = ICON_HEART_FILLED.replace('"', "&quot;")
    back_href = f"/salons/{master.salon_id}"
    back_label = f"К «{salon.name}»" if salon else "В каталог"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>{e(master_name)} — {e(master.specialization or 'мастер')} — руми</title>
    {get_base_styles()}
</head>
<body class="page-body salon-page">
    {render_header("salons")}
    {render_sidebar("salons", user)}

    <div class="main-wrapper">
        <main>
            <div class="section-container">
                <a class="salon-back" href="{e(back_href)}">{ICON_ARROW_LEFT}{e(back_label)}</a>

                <div class="salon-cols">
                    <div class="salon-main">
                        <header class="salon-head">
                            <div class="salon-head__top">
                                {ui.mark(master_name, image=avatar, alt=master_name, size="xl")}
                                <div class="salon-head__id">
                                    <h1 class="r-display salon-title">{e(master_name)}</h1>
                                    <p class="salon-who">{e(meta)}</p>
                                </div>
                                <button class="favorite-btn master-fav-btn salon-top-fav"
                                        type="button" data-type="master" data-id="{master.id}"
                                        data-icon-heart="{heart}"
                                        data-icon-heart-filled="{heart_filled}"
                                        aria-label="В избранное" title="В избранное">
                                    <span class="heart-icon">{ICON_HEART}</span>
                                </button>
                            </div>
                            {rating_html}
                        </header>

                        {services_html}
                        {works_html}
                    </div>

                    <aside class="salon-aside" id="booking">
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
             element_id="bookDock") if services else ''}
    {ui.sheet('<div id="bookingSheetHost"></div>', element_id="bookSheet", title=cta)
     if services else ''}
</body>
</html>"""


def _not_found() -> str:
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Мастер не найден — руми</title>{get_base_styles()}</head>
<body><main class="section-container" style="padding:4rem 1rem">
{ui.empty_state("Такой страницы нет",
                text="Мастер больше не принимает или ссылка устарела.",
                action_label="Открыть каталог", action_href="/salons")}
</main></body></html>"""
