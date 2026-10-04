# app/web/pages/salons.py
import html
import json
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.empty_state import render_empty_state
from app.web.components.icons import (
    ICON_SEARCH,
    ICON_MAP_PIN,
    ICON_HEART,
    ICON_HEART_FILLED,
    ICON_FILTER,
    ICON_CHEVRON_DOWN,
)
from app.services.catalog_slots import CardExtras, load_card_extras
from app.services.price import format_service_price
from app.services.public_words import solo_from_facts, word
from app.web.components import ui
from app.web.service_categories import SERVICE_CATEGORY_GROUPS, VALID_CATEGORY_SLUGS

PAGE_SIZE = 20
MAX_LIMIT = 200
_VALID_SORTS = {"rating", "reviews", "distance"}

# Кэш наличия pg_trgm: миграция создаёт расширение, но на managed-БД без
# привилегии оно может отсутствовать (тогда деградируем в FTS-only). Проверяем
# один раз за процесс.
_trgm_cache: Optional[bool] = None


async def _trgm_available(db: AsyncSession) -> bool:
    global _trgm_cache
    if _trgm_cache is None:
        row = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
        _trgm_cache = row.scalar() is not None
    return _trgm_cache


@dataclass
class SalonQuery:
    q: str = ""
    city: str = ""
    categories: list[str] = field(default_factory=list)
    min_rating: float = 0.0
    promo_only: bool = False
    sort: str = ""          # ""|rating|reviews|distance ("" → релевантность при поиске, иначе рейтинг)
    limit: int = PAGE_SIZE  # окно для полной страницы (растёт по «Показать ещё» без JS)
    offset: int = 0         # для AJAX-догрузки фрагмента (фронт-этап)
    lat: Optional[float] = None
    lon: Optional[float] = None


def parse_salon_query(request, default_city: str = "") -> SalonQuery:
    """Разбор query-параметров /salons в SalonQuery. Все значения — из URL
    (GET-форма), координаты — из тела на фронт-этапе; здесь тоже читаем из query,
    если пришли.

    default_city — город из профиля пользователя (см. вызов в views.py):
    подставляется, только если в URL параметра city вообще НЕТ (первый заход
    на страницу, например по ссылке «Салоны» из сайдбара). Если параметр
    присутствует — даже пустой строкой, т.е. выбрали «Все города» в фильтре —
    он побеждает: город из профиля не навязывается, когда человек явно смотрит
    другой город/весь каталог. Сам профиль при этом не трогаем — это разовый
    просмотр, а не смена города пребывания."""
    qp = request.query_params

    def _num(name, default):
        raw = qp.get(name)
        if raw in (None, ""):
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    categories = [c for c in qp.getlist("category") if c in VALID_CATEGORY_SLUGS]
    sort = qp.get("sort", "")
    if sort not in _VALID_SORTS:
        sort = ""

    limit = int(_num("limit", PAGE_SIZE))
    limit = max(PAGE_SIZE, min(limit, MAX_LIMIT))
    offset = max(0, int(_num("offset", 0)))

    lat = qp.get("lat")
    lon = qp.get("lon")
    city_param = qp.get("city")
    city = default_city if city_param is None else city_param.strip()
    return SalonQuery(
        q=(qp.get("q", "") or "").strip(),
        city=city,
        categories=categories,
        min_rating=_num("min_rating", 0.0),
        promo_only=qp.get("promo") == "1",
        sort=sort,
        limit=limit,
        offset=offset,
        lat=_num("lat", None) if lat not in (None, "") else None,
        lon=_num("lon", None) if lon not in (None, "") else None,
    )


# Документ для полнотекста/триграма: имя + описание + реальные названия услуг
# мастеров (агрегируются в CTE sn) — чтобы находилось по слову из услуги.
_DOC = "(coalesce(s.name,'') || ' ' || coalesce(s.description,'') || ' ' || coalesce(sn.svc,''))"


#: Тарифы, которые покупают приоритет в выдаче («Лайт» — нет).
_PAID = "coalesce(s.business_tier, '') IN ('business', 'corporate', 'custom')"


# Колонки, из которых собирается карточка салона. Вынесены в константу, потому
# что по ним строится И выдача каталога, И список избранного: разойдясь, два
# запроса дали бы две разные карточки у одного и того же салона.
_CARD_COLUMNS = f"""s.id, s.name, s.description, s.address, s.city, s.rating,
               s.reviews_count, s.latitude, s.longitude, s.logo_url, s.panel_mode,
               (s.contest_winner_until IS NOT NULL AND s.contest_winner_until > now()) AS is_winner,
               ({_PAID}) AS is_promoted,
               -- Соло или команда решается на тех же фактах, что и на странице
               -- салона (public_words.solo_from_facts): объявленный режим плюс
               -- ровно один активный мастер. Считаем подзапросами в том же
               -- SELECT — отдельный круг до базы за этим не ходит.
               (SELECT count(*) FROM masters mm
                 WHERE mm.salon_id = s.id AND mm.is_active = true) AS master_count,
               EXISTS (SELECT 1 FROM masters mo
                        WHERE mo.salon_id = s.id AND mo.is_active = true
                          AND mo.user_id = s.creator_id) AS owner_is_master"""


def _build_search_sql(p: SalonQuery, trgm: bool):
    """Строит SELECT (текст + связки). Пользовательские значения — только через
    bind-параметры; в f-string идут лишь структурные фрагменты."""
    binds: dict = {}
    where = [
        "s.is_active = true",
        "s.moderation_status = 'APPROVED'",
        "s.published_at IS NOT NULL",
        "s.is_hidden = false",
        # Тариф: доступ должен быть открыт (см. services/subscription.py)
        "s.access_until > now()",
    ]

    if p.city:
        where.append("s.city = :city")
        binds["city"] = p.city
    if p.min_rating and p.min_rating > 0:
        where.append("coalesce(s.rating, 0) >= :min_rating")
        binds["min_rating"] = p.min_rating
    if p.promo_only:
        where.append(
            "EXISTS (SELECT 1 FROM promotions pr WHERE pr.salon_id = s.id AND pr.is_active = true)"
        )
    if p.categories:
        where.append(
            "EXISTS (SELECT 1 FROM masters m JOIN services sv ON sv.master_id = m.id "
            "WHERE m.salon_id = s.id AND m.is_active = true AND sv.is_active = true "
            "AND sv.is_model_practice = false AND sv.category IN :cats)"
        )
        binds["cats"] = p.categories

    has_q = bool(p.q)
    if has_q:
        binds["q"] = p.q
        binds["qlike"] = f"%{p.q}%"
        pred = (
            f"(to_tsvector('russian', {_DOC}) @@ plainto_tsquery('russian', :q) "
            f"OR {_DOC} ILIKE :qlike"
        )
        if trgm:
            pred += f" OR word_similarity(:q, {_DOC}) > 0.3"
        pred += ")"
        where.append(pred)

    # Доп. колонки: rank (при поиске) и dist (при координатах)
    extra_cols = ""
    if has_q:
        rank = f"ts_rank(to_tsvector('russian', {_DOC}), plainto_tsquery('russian', :q))"
        if trgm:
            rank += f" + word_similarity(:q, {_DOC})"
        extra_cols += f", ({rank}) AS rank"

    has_coords = p.lat is not None and p.lon is not None
    if has_coords:
        binds["lat"] = p.lat
        binds["lon"] = p.lon
        dist = (
            "CASE WHEN s.latitude IS NULL OR s.longitude IS NULL THEN NULL ELSE "
            "6371 * 2 * asin(sqrt("
            "power(sin(radians((:lat - s.latitude) / 2)), 2) + "
            "cos(radians(:lat)) * cos(radians(s.latitude)) * "
            "power(sin(radians((:lon - s.longitude) / 2)), 2))) END"
        )
        extra_cols += f", ({dist}) AS dist"

    # Сортировка. Подъём победителей конкурса и платных салонов действует ТОЛЬКО
    # в порядке по умолчанию: если человек выбрал «по рейтингу» или «по близости»,
    # он выбрал правило, и подменять его — обманывать (docs/decisions/0006).
    # coalesce обязателен: у салона без тарифа business_tier = NULL, и выражение
    # IN даёт NULL, а не false. В ORDER BY ... DESC NULL идёт ПЕРВЫМ — салоны без
    # тарифа оказывались выше платных, то есть подъём работал наоборот.
    boost = ("(s.contest_winner_until IS NOT NULL AND s.contest_winner_until > now()) DESC, "
             f"({_PAID}) DESC, ")
    if p.sort == "reviews":
        order = "coalesce(s.reviews_count, 0) DESC"
    elif p.sort == "distance" and has_coords:
        order = "dist ASC NULLS LAST, coalesce(s.rating, 0) DESC"
    elif p.sort == "rating":
        order = "coalesce(s.rating, 0) DESC"
    elif has_q:  # sort не задан + есть запрос → релевантность
        order = boost + "rank DESC, coalesce(s.rating, 0) DESC"
    else:
        order = boost + "coalesce(s.rating, 0) DESC"
    order += ", s.id DESC"  # детерминированный тайбрейк

    binds["lim"] = p.limit + 1  # +1 чтобы понять, есть ли ещё
    binds["off"] = p.offset

    sql = f"""
        WITH sn AS (
            SELECT m.salon_id AS salon_id, string_agg(sv.name, ' ') AS svc
            FROM masters m JOIN services sv ON sv.master_id = m.id
            WHERE m.is_active = true AND sv.is_active = true AND sv.is_model_practice = false
            GROUP BY m.salon_id
        )
        SELECT {_CARD_COLUMNS}{extra_cols}
        FROM salons s
        LEFT JOIN sn ON sn.salon_id = s.id
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT :lim OFFSET :off
    """
    stmt = text(sql)
    if p.categories:
        stmt = stmt.bindparams(bindparam("cats", expanding=True))
    return stmt, binds


async def _load_page(db: AsyncSession, p: SalonQuery):
    """Возвращает (rows, has_more): rows — до p.limit салонов, has_more — есть ли ещё."""
    trgm = await _trgm_available(db)
    stmt, binds = _build_search_sql(p, trgm)
    result = await db.execute(stmt, binds)
    rows = result.mappings().all()
    has_more = len(rows) > p.limit
    return rows[: p.limit], has_more


async def _available_cities(db: AsyncSession) -> list[str]:
    """Города, где есть видимые салоны — для дропдауна (не зависит от текущих
    фильтров, список стабилен)."""
    rows = await db.execute(text(
        "SELECT DISTINCT city FROM salons "
        "WHERE is_active = true AND moderation_status = 'APPROVED' "
        "AND published_at IS NOT NULL AND is_hidden = false AND access_until > now() "
        "AND city IS NOT NULL AND city <> '' ORDER BY city"
    ))
    return [r[0] for r in rows.all()]


async def _categories_by_city(db: AsyncSession) -> dict[str, list[str]]:
    """Карта {город: [слаги категорий, реально предлагаемых в городе]} — чтобы
    фронт-этап прятал из фильтра категории, которых в выбранном городе нет.
    Ключ "" — все категории (когда город не выбран)."""
    rows = await db.execute(text(
        "SELECT DISTINCT s.city, sv.category "
        "FROM salons s "
        "JOIN masters m ON m.salon_id = s.id "
        "JOIN services sv ON sv.master_id = m.id "
        "WHERE s.is_active = true AND s.moderation_status = 'APPROVED' "
        "AND s.published_at IS NOT NULL AND s.is_hidden = false AND s.access_until > now() "
        "AND s.city IS NOT NULL AND s.city <> '' "
        "AND m.is_active = true AND sv.is_active = true "
        "AND sv.is_model_practice = false AND sv.category IS NOT NULL"
    ))
    by_city: dict[str, set[str]] = {}
    all_cats: set[str] = set()
    for city, cat in rows.all():
        by_city.setdefault(city, set()).add(cat)
        all_cats.add(cat)
    result = {city: sorted(cats) for city, cats in by_city.items()}
    result[""] = sorted(all_cats)
    return result


def render_card(s, extras: CardExtras, *, favorite_on: bool = False) -> str:
    """Карточка каталога в новой форме.

    Её несут имя, город, услуги с ценой и временем и ближайшие свободные окна.
    Фотографии нет почти ни у кого (на 03.10.2026 обложка у двух салонов из
    девяти, описание не заполнено ни у кого), поэтому карточка собрана так,
    чтобы без снимка и без описания она была ПОЛНОЙ, а не дырявой
    (решение 0011, п. 11).

    Описание с карточки убрано намеренно: его не заполнил никто, а место под
    него оставляло в каждой карточке пустую строку. Поиск по описанию при этом
    работает как раньше — индекс не трогали.
    """
    solo = solo_from_facts(s["panel_mode"], s["master_count"] or 0, bool(s["owner_is_master"]))
    # Город отдельной колонкой есть не у всех (его завели позже адреса) —
    # тогда берём первую часть адреса, как делала старая карточка.
    city = (s["city"] or "").strip() or (
        (s["address"] or "").split(",")[0].strip() if s["address"] else ""
    )

    # Метки видны всегда, даже когда подъём не действует: клиент должен
    # понимать, почему карточка наверху, иначе это скрытая реклама.
    badges = []
    if s.get("is_winner"):
        badges.append(ui.status("Победитель конкурса Руми", "accent"))
    if s.get("is_promoted"):
        badges.append(ui.status("Продвигается", "neutral"))

    services = tuple(
        ui.service_line(
            item.name,
            price=format_service_price(item.price, item.price_max),
            duration=f"{item.duration} мин",
        )
        for item in extras.services
    )

    # Окно ведёт прямо в запись с уже выбранными мастером, услугой и временем:
    # «записаться из списка» (решение 0011, п. 11) значит не «открыть салон», а
    # попасть в тот же шаг, который человек уже сделал глазами.
    slots = ()
    slot_service = ""
    if extras.slot_service:
        lead = extras.slot_service
        slots = tuple(
            ui.slot(
                sl.label,
                href=(f"/salons/{s['id']}?master={lead.master_id}&service={lead.id}"
                      f"&slot={sl.value}#booking"),
                value=sl.value,
                title=sl.full,
            )
            for sl in extras.slots
        )
        slot_service = lead.name

    return ui.salon_card(
        salon_id=s["id"],
        name=s["name"] or "",
        href=f"/salons/{s['id']}",
        kind_label=word("catalog_kind", solo=solo),
        city=city,
        rating=s["rating"] or 0.0,
        reviews=s["reviews_count"] or 0,
        logo_url=s["logo_url"] or "",
        badges=tuple(badges),
        services=services,
        services_total=extras.services_total,
        slots=slots,
        slot_service=slot_service,
        promos=tuple(extras.promos),
        favorite_icons=(ICON_HEART, ICON_HEART_FILLED),
        favorite_on=favorite_on,
    )


async def load_cards_by_ids(db: AsyncSession, salon_ids: list[int]) -> dict[int, str]:
    """Готовые карточки каталога для перечисленных салонов: {id: разметка}.

    Нужна избранному: оно обязано показывать ТУ ЖЕ карточку, что каталог, и
    единственный способ это гарантировать — тот же сборщик (``render_card``) на
    тех же колонках (``_CARD_COLUMNS``) и тех же дополнениях
    (``load_card_extras``). Второй, «похожий» список карточек разошёлся бы с
    каталогом на первой же правке.

    Видимость здесь НАРОЧНО мягче каталожной: отбираются активные и не скрытые
    владельцем салоны, без требований модерации, публикации и оплаченного
    тарифа. Избранное — это личный список человека; салон, у которого кончился
    тариф, из него исчезать не должен, иначе человек решит, что сам его удалил.
    Ровно это условие стояло в избранном и до переделки вида.

    Порядок возвращённого словаря не важен: карточки раскладывает вызывающий
    в порядке самого избранного (сначала добавленные позже).
    """
    if not salon_ids:
        return {}

    stmt = text(f"""
        SELECT {_CARD_COLUMNS}
        FROM salons s
        WHERE s.id IN :ids AND s.is_active = true AND s.is_hidden = false
    """).bindparams(bindparam("ids", expanding=True))
    rows = (await db.execute(stmt, {"ids": salon_ids})).mappings().all()
    if not rows:
        return {}

    extras = await load_card_extras(db, [r["id"] for r in rows])
    # favorite_on=True: это список избранного, здесь закрашено всё.
    return {r["id"]: render_card(r, extras.get(r["id"], CardExtras()), favorite_on=True)
            for r in rows}


def _query_string(p: SalonQuery, **overrides) -> str:
    """Собирает querystring из текущих параметров (для ссылки «Показать ещё»)."""
    parts: list[tuple[str, str]] = []
    q = overrides.get("q", p.q)
    city = overrides.get("city", p.city)
    if q:
        parts.append(("q", q))
    if city:
        parts.append(("city", city))
    for c in p.categories:
        parts.append(("category", c))
    if p.min_rating and p.min_rating > 0:
        parts.append(("min_rating", str(p.min_rating)))
    if p.promo_only:
        parts.append(("promo", "1"))
    if p.sort:
        parts.append(("sort", p.sort))
    limit = overrides.get("limit")
    if limit:
        parts.append(("limit", str(limit)))
    from urllib.parse import urlencode
    return urlencode(parts)


def _render_filter_bar(p: SalonQuery, cities: list[str]) -> str:
    # cities — только города, где реально ЕСТЬ салоны (см. _available_cities).
    # Текущий фильтр (p.city — свежий город из профиля или явный выбор) может
    # в этот список не попасть, если там пока пусто: без явной подстраховки
    # <select> тихо показал бы «Все города» вместо настоящего применённого
    # фильтра — салонов ноль, а выглядит как будто фильтра нет вовсе.
    all_cities = cities if (not p.city or p.city in cities) else [p.city, *cities]
    city_options = '<option value="">Все города</option>' + "".join(
        f'<option value="{html.escape(c, quote=True)}"{" selected" if c == p.city else ""}>{c}</option>'
        for c in all_cities
    )
    # Категории — мультивыбор; в reload-режиме не сабмитим на каждую галочку,
    # владелец отмечает несколько и жмёт «Применить» (фронт-этап сделает AJAX).
    category_options = "".join(
        f'<label class="category-option" data-slug="{slug}">'
        f'<input type="checkbox" name="category" value="{slug}" form="salonsFilterForm"'
        f'{" checked" if slug in p.categories else ""}> {label}</label>'
        for slug, label, _kw in SERVICE_CATEGORY_GROUPS
    )

    rating_levels = [("0", "Любой рейтинг"), ("4.5", "от 4.5"), ("4", "от 4.0"), ("3.5", "от 3.5")]
    rating_chips = ""
    for val, lbl in rating_levels:
        checked = " checked" if abs(p.min_rating - float(val)) < 1e-9 else ""
        # Радио не прячем через display:none — так чип нельзя выбрать с
        # клавиатуры. Визуально скрываем классом, фокус ловим на самом чипе.
        rating_chips += (
            f'<label class="filter-chip{" active" if checked else ""}">'
            f'<input type="radio" class="filter-chip-input" name="min_rating" value="{val}" '
            f'form="salonsFilterForm" onchange="if(!this.form.dataset.ajax)this.form.submit()"{checked}>{lbl}</label>'
        )

    # Порядок по умолчанию больше не «по рейтингу»: сверху идут победители
    # конкурса и салоны на платном тарифе (они помечены на карточках).
    # Называть его «по рейтингу» значит обманывать — это «рекомендуемые».
    default_label = "По релевантности" if p.q else "Рекомендуемые"
    sort_opts = [("", default_label), ("rating", "По рейтингу"),
                 ("reviews", "По отзывам"), ("distance", "Рядом со мной")]
    sort_options = "".join(
        f'<option value="{val}"{" selected" if val == p.sort else ""}>{lbl}</option>'
        for val, lbl in sort_opts
    )

    return f"""
    <form method="get" action="/salons" id="salonsFilterForm" class="salons-filter-bar">
        <div class="filter-row filter-categories">
            <div class="city-select-wrapper">
                {ICON_MAP_PIN}
                <select id="citySelect" name="city" class="city-select custom-select" onchange="if(!this.form.dataset.ajax)this.form.submit()">
                    {city_options}
                </select>
            </div>
            <div class="category-dropdown" id="categoryDropdown">
                <button type="button" class="category-dropdown-btn" id="categoryDropdownBtn">
                    {ICON_FILTER}
                    <span id="categoryDropdownLabel">Категории{f' ({len(p.categories)})' if p.categories else ''}</span>
                    {ICON_CHEVRON_DOWN}
                </button>
                <div class="category-dropdown-panel" id="categoryDropdownPanel" hidden>
                    {category_options}
                    <div class="category-dropdown-actions">
                        <a href="/salons?{_query_string(SalonQuery(q=p.q, city=p.city, min_rating=p.min_rating, promo_only=p.promo_only, sort=p.sort))}" class="category-clear-btn" id="categoryClearBtn">Сбросить</a>
                        <button type="submit" form="salonsFilterForm" class="category-apply-btn">Применить</button>
                    </div>
                </div>
            </div>
        </div>
        <div class="filter-row filter-controls">
            <div class="filter-controls-left">
                <div class="filter-group" id="ratingFilterGroup">
                    {rating_chips}
                </div>
                <label class="promo-toggle">
                    <input type="checkbox" name="promo" value="1" id="promoOnlyToggle" form="salonsFilterForm"
                           onchange="if(!this.form.dataset.ajax)this.form.submit()"{" checked" if p.promo_only else ""}>
                    Только с акциями
                </label>
            </div>
            <div class="sort-group">
                <label for="sortSelect">Сортировка</label>
                <select id="sortSelect" name="sort" class="sort-select custom-select" onchange="if(!this.form.dataset.ajax)this.form.submit()">
                    {sort_options}
                </select>
            </div>
        </div>
    </form>
    """


async def render_cards(db: AsyncSession, p: SalonQuery, *, with_slots: bool = True):
    """Карточки по тем же правилам, что каталог, и признак «есть ещё».

    Отдельная функция, потому что главная показывает ТОТ ЖЕ компонент и тот же
    порядок, что каталог (решение 0011, п. 12). Второй похожий список на
    главной через месяц разошёлся бы с каталогом и по виду, и по подъёму.

    Цена: ОДИН запрос на выборку салонов плюс ОДИН на содержимое карточек
    (услуги, акции, категории, свободные окна) — см. catalog_slots.
    """
    rows, has_more = await _load_page(db, p)
    extras = await load_card_extras(db, [r["id"] for r in rows], with_slots=with_slots)
    empty = CardExtras()
    return "".join(render_card(r, extras.get(r["id"], empty)) for r in rows), has_more


async def render_salons_grid(db: AsyncSession, p: SalonQuery) -> str:
    """Сетка карточек + маркер «Показать ещё». Используется и в полной странице,
    и во фрагменте (?partial=1) — единый источник разметки карточек."""
    cards, has_more = await render_cards(db, p)
    if not cards and p.offset == 0:
        return render_empty_state(
            title="Ничего не найдено",
            text="Попробуйте изменить запрос или снять часть фильтров.",
            icon=ICON_SEARCH,
            action_href="/salons",
            action_label="Сбросить фильтры",
            element_id="salonsEmptyState",
        )

    more = ""
    if has_more:
        # Без JS: ссылка расширяет окно (limit растёт). Фронт-этап заменит на
        # AJAX-догрузку по offset.
        next_limit = p.limit + PAGE_SIZE
        more = (
            '<div class="salons-more">'
            + ui.button("Показать ещё", kind="secondary",
                        href=f"/salons?{_query_string(p, limit=next_limit)}",
                        classes="salons-more-btn")
            + "</div>"
        )
    return cards + more


async def render_salons_page(db: AsyncSession, user=None, p: Optional[SalonQuery] = None, partial: bool = False) -> str:
    """Страница салонов. Серверная фильтрация/поиск/сортировка/пагинация.
    partial=True → только сетка карточек (для AJAX-подмены на фронт-этапе)."""
    if p is None:
        p = SalonQuery()

    if partial:
        return await render_salons_grid(db, p)

    cities = await _available_cities(db)
    cats_by_city = await _categories_by_city(db)
    grid = await render_salons_grid(db, p)
    filter_bar = _render_filter_bar(p, cities)
    search_value = html.escape(p.q, quote=True)
    # Данные для фронт-этапа (AJAX): размер страницы + категории по городам
    # (умный список). Инлайним JSON — CSP запрещает внешние скрипты, но inline
    # разрешён; json.dumps безопасно экранирует.
    filters_data = json.dumps({
        "pageSize": PAGE_SIZE,
        "categoriesByCity": cats_by_city,
    }, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Салоны — руми</title>
    <meta name="description" content="Найдите лучший салон красоты рядом с вами.">
    {get_base_styles()}
</head>
<body>
    {render_header("salons")}
    {render_sidebar("salons", user)}

    <main class="main-content">
        <section class="catalog-hero">
            <div class="section-container">
                <div class="catalog-hero__intro">
                    <h1 class="r-display">Кто рядом</h1>
                    <p class="r-text r-muted">Имя, услуга или салон. Цены и свободное
                        время видно сразу в списке.</p>
                </div>
                <div class="catalog-search">
                    <span class="catalog-search__icon" aria-hidden="true">{ICON_SEARCH}</span>
                    <input type="search" name="q" id="searchInput" form="salonsFilterForm"
                           value="{search_value}" placeholder="Маникюр, стрижка, имя мастера"
                           class="search-input" aria-label="Поиск по каталогу"
                           enterkeyhint="search">
                    {ui.button("Найти", type_="submit", small=True, form="salonsFilterForm")}
                </div>
            </div>
        </section>

        <section class="catalog-body">
            <div class="section-container">
                {filter_bar}
                <div id="salons-list" class="salons-grid">
                    {grid}
                </div>
            </div>
        </section>

        {render_footer(user)}
    </main>
    <script>window.salonFilters = {filters_data};</script>
</body>
</html>"""
