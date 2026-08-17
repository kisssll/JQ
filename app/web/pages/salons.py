# app/web/pages/salons.py
import html
import json
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Promotion, Master, Service
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_SEARCH,
    ICON_MAP_PIN,
    ICON_STAR_FILLED,
    ICON_HEART,
    ICON_HEART_FILLED,
    ICON_ARROW_RIGHT,
    ICON_FILTER,
    ICON_CHEVRON_DOWN,
)
from app.web.service_categories import SERVICE_CATEGORY_GROUPS, VALID_CATEGORY_SLUGS, slug_to_label

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


def parse_salon_query(request) -> SalonQuery:
    """Разбор query-параметров /salons в SalonQuery. Все значения — из URL
    (GET-форма), координаты — из тела на фронт-этапе; здесь тоже читаем из query,
    если пришли."""
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
    return SalonQuery(
        q=(qp.get("q", "") or "").strip(),
        city=(qp.get("city", "") or "").strip(),
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


def _build_search_sql(p: SalonQuery, trgm: bool):
    """Строит SELECT (текст + связки). Пользовательские значения — только через
    bind-параметры; в f-string идут лишь структурные фрагменты."""
    binds: dict = {}
    where = [
        "s.is_active = true",
        "s.moderation_status = 'APPROVED'",
        "s.published_at IS NOT NULL",
        "s.is_hidden = false",
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

    # Сортировка
    if p.sort == "reviews":
        order = "coalesce(s.reviews_count, 0) DESC"
    elif p.sort == "distance" and has_coords:
        order = "dist ASC NULLS LAST, coalesce(s.rating, 0) DESC"
    elif p.sort == "rating":
        order = "coalesce(s.rating, 0) DESC"
    elif has_q:  # sort не задан + есть запрос → релевантность
        order = "rank DESC, coalesce(s.rating, 0) DESC"
    else:
        order = "coalesce(s.rating, 0) DESC"
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
        SELECT s.id, s.name, s.description, s.address, s.city, s.rating,
               s.reviews_count, s.latitude, s.longitude, s.logo_url{extra_cols}
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
        "AND published_at IS NOT NULL AND is_hidden = false "
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
        "AND s.published_at IS NOT NULL AND s.is_hidden = false "
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


async def _promotions_and_categories(db: AsyncSession, salon_ids: list[int]):
    """Акции и хранимые категории услуг для салонов текущей страницы (для
    карточек). Категории — из Service.category (факт), а не из угадывания."""
    promotions_by_salon: dict[int, list] = {}
    categories_by_salon: dict[int, list[str]] = {}
    if not salon_ids:
        return promotions_by_salon, categories_by_salon

    promos = (await db.execute(
        select(Promotion).where(
            Promotion.salon_id.in_(salon_ids), Promotion.is_active == True  # noqa: E712
        ).order_by(Promotion.salon_id, Promotion.id)
    )).scalars().all()
    for pr in promos:
        promotions_by_salon.setdefault(pr.salon_id, []).append(pr)

    cat_rows = (await db.execute(
        select(Master.salon_id, Service.category)
        .join(Master, Master.id == Service.master_id)
        .where(
            Master.salon_id.in_(salon_ids), Master.is_active == True,  # noqa: E712
            Service.is_active == True, Service.is_model_practice == False,  # noqa: E712
            Service.category.isnot(None),
        ).distinct()
    )).all()
    for salon_id, cat in cat_rows:
        categories_by_salon.setdefault(salon_id, []).append(cat)
    return promotions_by_salon, categories_by_salon


def _render_card(s, promos, categories) -> str:
    rating = s["rating"] or 0.0
    reviews = s["reviews_count"] or 0

    # Категорий может не быть (мастера ещё не завели услуги) — тогда блок чипов
    # не рендерим вовсе, чтобы не показывать бессмысленный плейсхолдер «Услуги».
    chips_html = ""
    if categories:
        chips = "".join(
            f'<span class="service-chip">{slug_to_label(slug)}</span>' for slug in categories[:3]
        )
        extra = len(categories) - 3
        if extra > 0:
            chips += f'<span class="service-chip service-chip-more">+{extra}</span>'
        chips_html = f'<div class="services-chips">{chips}</div>'

    # Оценку показываем только когда она есть. «0.0» — это не «плохо», а «нет
    # данных»: на части салонов reviews_count заполнен, а rating нулевой, и
    # бейдж «0.0 (312)» читался как единица с тремя сотнями подтверждений.
    if rating > 0:
        rating_html = (
            f'<div class="salon-rating-badge">{ICON_STAR_FILLED}'
            f'<span class="rating-value">{rating:.1f}</span>'
            f'<span class="rating-count">({reviews})</span></div>'
        )
    elif reviews > 0:
        word = "отзыв" if reviews % 10 == 1 and reviews % 100 != 11 else (
            "отзыва" if reviews % 10 in (2, 3, 4) and reviews % 100 not in (12, 13, 14) else "отзывов"
        )
        rating_html = f'<div class="salon-rating-badge is-empty">{reviews} {word}</div>'
    else:
        rating_html = '<div class="salon-rating-badge is-empty">Нет оценок</div>'

    desc = (s["description"] or "").strip()
    desc_html = f'<p class="salon-desc">{html.escape(desc)}</p>' if desc else ""

    heart_svg = ICON_HEART.replace('"', '&quot;')
    heart_filled_svg = ICON_HEART_FILLED.replace('"', '&quot;')

    if s["logo_url"]:
        image_html = (
            f'<img src="{s["logo_url"]}" alt="{html.escape(s["name"] or "", quote=True)}" '
            f'loading="lazy" decoding="async">'
        )
    else:
        letter = (s["name"] or "?")[0].upper()
        image_html = f'<div class="salon-image-fallback" aria-hidden="true">{letter}</div>'

    promo_items = ""
    for promo in promos[:3]:
        promo_desc = (promo.description or "").strip()
        promo_items += f"""
        <div class="promo-item">
            <span class="promo-tag">{html.escape(promo.tag or '')}</span>
            <div class="promo-info">
                <span class="promo-title">{html.escape(promo.title or '')}</span>
                {f'<span class="promo-desc">{html.escape(promo_desc)}</span>' if promo_desc else ''}
            </div>
        </div>
        """
    desktop_promo_block = f'<div class="salon-promo-desktop"><p class="promo-label">Акции</p>{promo_items}</div>' if promo_items else ""
    mobile_promo_block = f'<div class="salon-promo-mobile"><p class="promo-label">Акции</p>{promo_items}</div>' if promo_items else ""

    return f"""
    <div class="salon-card" data-salon-id="{s['id']}">
        <div class="salon-card-inner">
            <div class="salon-image">
                {image_html}
                <button class="favorite-btn" data-type="salon" data-id="{s['id']}"
                        data-icon-heart="{heart_svg}" data-icon-heart-filled="{heart_filled_svg}"
                        title="В избранное">
                    <span class="heart-icon">{ICON_HEART}</span>
                </button>
            </div>
            <div class="salon-info">
                <div class="salon-info-header">
                    <div class="salon-info-title">
                        <h3 class="salon-name">{html.escape(s['name'] or '')}</h3>
                        <p class="salon-address">{ICON_MAP_PIN}<span>{html.escape(s['address'] or 'Адрес не указан')}</span></p>
                    </div>
                    {rating_html}
                </div>
                {desc_html}
                {chips_html}
                <a href="/salons/{s['id']}" class="btn-primary salon-btn">Смотреть мастеров {ICON_ARROW_RIGHT}</a>
            </div>
            {desktop_promo_block}
        </div>
        {mobile_promo_block}
    </div>
    """


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
    city_options = '<option value="">Все города</option>' + "".join(
        f'<option value="{html.escape(c, quote=True)}"{" selected" if c == p.city else ""}>{c}</option>'
        for c in cities
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

    sort_opts = [("", "По релевантности" if p.q else "По рейтингу"), ("rating", "По рейтингу"),
                 ("reviews", "По отзывам"), ("distance", "Рядом со мной")]
    # убираем дубль «По рейтингу», когда запроса нет (пустой sort уже = рейтинг)
    if not p.q:
        sort_opts = [("", "По рейтингу"), ("reviews", "По отзывам"), ("distance", "Рядом со мной")]
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


async def render_salons_grid(db: AsyncSession, p: SalonQuery) -> str:
    """Сетка карточек + маркер «Показать ещё». Используется и в полной странице,
    и во фрагменте (?partial=1) — единый источник разметки карточек."""
    rows, has_more = await _load_page(db, p)
    salon_ids = [r["id"] for r in rows]
    promotions_by_salon, categories_by_salon = await _promotions_and_categories(db, salon_ids)

    cards = "".join(
        _render_card(r, promotions_by_salon.get(r["id"], []), categories_by_salon.get(r["id"], []))
        for r in rows
    )
    if not cards and p.offset == 0:
        return f"""
        <div id="salonsEmptyState" class="salons-empty">
            <div class="salons-empty-icon">{ICON_SEARCH}</div>
            <p class="salons-empty-title">Ничего не найдено</p>
            <p class="salons-empty-text">Попробуйте изменить запрос или снять часть фильтров.</p>
            <a href="/salons" class="btn-outline salons-empty-reset">Сбросить фильтры</a>
        </div>
        """

    more = ""
    if has_more:
        # Без JS: ссылка расширяет окно (limit растёт). Фронт-этап заменит на
        # AJAX-догрузку по offset.
        next_limit = p.limit + PAGE_SIZE
        more = (
            f'<div class="salons-more"><a class="btn-outline salons-more-btn" '
            f'href="/salons?{_query_string(p, limit=next_limit)}">Показать ещё</a></div>'
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
        <section class="section-py bg-surface-alt salons-hero">
            <div class="section-container">
                <div class="salons-hero-content">
                    <h1 class="text-display salons-title">Салоны красоты</h1>
                    <p class="text-body-lg salons-subtitle">Найдите лучший салон рядом с вами по названию или услуге</p>
                    <div class="search-box">
                        {ICON_SEARCH}
                        <input type="text" name="q" id="searchInput" form="salonsFilterForm"
                               value="{search_value}" placeholder="Название салона или услуга"
                               class="search-input">
                    </div>
                </div>
            </div>
        </section>

        <section class="section-py bg-surface salons-list-section">
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
