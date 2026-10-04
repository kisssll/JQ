# app/web/pages/favorites.py
"""«Избранное» — салоны и мастера, к которым человек хочет вернуться.

Карточка салона здесь ТА ЖЕ, что в каталоге: один сборщик
(``salons.render_card``) на тех же колонках и с теми же дополнениями
(услуги с ценой, акции, ближайшие окна). Прежняя версия рисовала свою
карточку руками — с рейтингом «0.0» у салона без отзывов, без услуг и без
свободного времени, — и человек, перешедший в избранное из каталога, видел
тот же салон в другом виде и беднее.

У мастера карточка своя (``ui.person_card``), но из тех же частей: ни услуг,
ни окон у мастера в избранном нет, и карточка с пятью пустыми ветками
читалась бы хуже двух честных.

Видимость: активный и не скрытый владельцем. Специально МЯГЧЕ каталожной —
салон, у которого кончился тариф, из личного списка исчезать не должен,
иначе человек решит, что сам его удалил. Ровно это условие стояло здесь и
до переделки вида.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Favorite, Master, Salon, User as UserModel
from app.web.components import ui
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import ICON_HEART, ICON_HEART_FILLED
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.pages.salons import load_cards_by_ids

#: Что сказать по итогам действия. Параметр в адресе ставит эндпоинт
#: ``/api/v1/favorites/toggle-*`` при переходе без JS — до этого захода его
#: никто не читал, и человек без скрипта не понимал, сработало ли нажатие.
_NOTICES = {
    "added": ("Добавлено в избранное.", "success"),
    "removed": ("Убрано из избранного.", "neutral"),
}


def _heart(kind: str, obj_id: int) -> str:
    """Закрашенное сердечко на карточке мастера.

    Разметка один в один с сердечком карточки салона (``ui.salon_card``):
    тот же класс, те же data-атрибуты, тот же обработчик. Отдельная функция
    только потому, что ``person_card`` принимает «правый верхний угол» готовой
    разметкой — своих кнопок у неё нет.
    """
    return (
        f'<button class="favorite-btn r-salon__fav liked" type="button" '
        f'data-type="{kind}" data-id="{obj_id}" '
        f'data-icon-heart="{ICON_HEART.replace(chr(34), "&quot;")}" '
        f'data-icon-heart-filled="{ICON_HEART_FILLED.replace(chr(34), "&quot;")}" '
        f'aria-pressed="true" aria-label="Убрать из избранного" '
        f'title="Убрать из избранного">'
        f'<span class="heart-icon">{ICON_HEART_FILLED}</span></button>'
    )


async def render_favorites_page(db: AsyncSession, user, notice: str = "") -> str:
    """Страница избранного. Запросов постоянное число: само избранное,
    карточки салонов (одним запросом на все плюс один на их содержимое),
    мастера, их пользователи и салоны — пачками."""
    favorites = (await db.execute(
        select(Favorite).where(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
    )).scalars().all()

    salon_order = [f.salon_id for f in favorites if f.salon_id]
    master_order = [f.master_id for f in favorites if f.master_id]

    # ---------- Салоны ----------
    cards_by_id = await load_cards_by_ids(db, salon_order)
    salon_cards = ""
    for salon_id in salon_order:
        card = cards_by_id.get(salon_id)
        if not card:
            continue
        # Убрать из избранного — ТО ЖЕ сердечко, которым человек карточку
        # добавил: оно уже стоит в карточке каталога и здесь приходит
        # закрашенным. Второй кнопки «Убрать» рядом с ним нет намеренно — это
        # был бы второй орган управления одним и тем же.
        salon_cards += card

    # ---------- Мастера ----------
    master_cards = ""
    if master_order:
        masters = {
            m.id: m for m in (await db.execute(
                select(Master).where(Master.id.in_(master_order), Master.is_active == True)  # noqa: E712
            )).scalars().all()
        }
        user_ids = {m.user_id for m in masters.values() if m.user_id}
        names = {}
        if user_ids:
            names = {
                u.id: (u.full_name or "") for u in (await db.execute(
                    select(UserModel).where(UserModel.id.in_(user_ids))
                )).scalars().all()
            }
        salon_ids = {m.salon_id for m in masters.values() if m.salon_id}
        salon_names = {}
        if salon_ids:
            salon_names = {
                s.id: (s.name or "") for s in (await db.execute(
                    select(Salon).where(Salon.id.in_(salon_ids), Salon.is_active == True)  # noqa: E712
                )).scalars().all()
            }

        for master_id in master_order:
            master = masters.get(master_id)
            if master is None:
                continue
            master_cards += ui.person_card(
                name=names.get(master.user_id, "") or "Мастер",
                href=f"/masters/{master.id}",
                meta=master.specialization or "",
                where=salon_names.get(master.salon_id, ""),
                rating=master.rating or 0.0,
                avatar_url=getattr(master, "photo_url", "") or "",
                aside=_heart("master", master.id),
                all_label="Услуги и запись",
            )

    notice_html = ""
    if notice in _NOTICES:
        text, tone = _NOTICES[notice]
        notice_html = ui.notice(text, tone=tone)

    # ---------- Пустые состояния ----------
    # Оба объясняют, КАК сюда что-то попадает, и ведут в каталог ссылкой:
    # «пока ничего нет» без выхода — тупик, а избранное пустое у каждого, кто
    # зашёл на него первым.
    if not salon_cards and not master_cards:
        body = ui.empty_state(
            "В избранном пока пусто",
            text="Нажмите сердечко на карточке мастера или салона — и он появится "
                 "здесь, чтобы не искать заново.",
            action_label="Открыть каталог",
            action_href="/salons",
        )
    else:
        groups = []
        if salon_cards:
            groups.append(
                '<section class="fav-group">'
                + ui.section_head("Салоны")
                + f'<div class="fav-list">{salon_cards}</div></section>'
            )
        if master_cards:
            groups.append(
                '<section class="fav-group">'
                + ui.section_head("Мастера")
                + f'<div class="fav-list">{master_cards}</div></section>'
            )
        body = "".join(groups)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Избранное — руми</title>
    <meta name="robots" content="noindex, nofollow">
    {get_base_styles()}
</head>
<body class="page-body">
    {render_header("favorites")}
    {render_sidebar("favorites", user)}

    <main class="main-content cabinet-main favorites-main">
        <div class="section-container">
            <header class="cabinet-head">
                <h1 class="r-display">Избранное</h1>
                <p class="r-text r-muted">Мастера и салоны, к которым вы хотите
                    вернуться.</p>
            </header>
            {notice_html}
            {body}
        </div>
        {render_footer(user)}
    </main>

    {ui.sheet(
        '<p class="r-text" id="favWhat"></p>'
        '<p class="r-text r-muted">Карточку всегда можно вернуть сердечком.</p>'
        '<div class="sheet-actions">'
        + ui.button("Убрать", kind="danger", block=True, element_id="favConfirm")
        + ui.button("Оставить", kind="secondary", block=True,
                    data={"sheet-close": "1"})
        + '</div>',
        element_id="favSheet", title="Убрать из избранного?")}
</body>
</html>"""
