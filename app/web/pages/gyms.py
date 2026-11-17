import html
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlencode

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sport import SportOrganization
from app.web.components import ui
from app.web.components.empty_state import render_empty_state
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import ICON_MAP_PIN, ICON_SEARCH
from app.web.components.styles import get_base_styles

PAGE_SIZE = 20
MAX_LIMIT = 200


@dataclass
class GymQuery:
    q: str = ""
    city: str = ""
    limit: int = PAGE_SIZE
    offset: int = 0


def parse_gym_query(request, default_city: str = "") -> GymQuery:
    qp = request.query_params

    def number(name: str, default: int) -> int:
        try:
            return int(qp.get(name, default))
        except (TypeError, ValueError):
            return default

    limit = max(PAGE_SIZE, min(number("limit", PAGE_SIZE), MAX_LIMIT))
    offset = max(0, number("offset", 0))
    city = qp.get("city")
    return GymQuery(
        q=(qp.get("q", "") or "").strip(),
        city=default_city if city is None else city.strip(),
        limit=limit,
        offset=offset,
    )


async def _available_cities(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(SportOrganization.city)
        .where(
            SportOrganization.is_published.is_(True),
            SportOrganization.city != "",
        )
        .distinct()
        .order_by(SportOrganization.city)
    )
    return list(result.scalars().all())


async def _load_page(db: AsyncSession, query: GymQuery):
    statement = select(SportOrganization).where(
        SportOrganization.is_published.is_(True)
    )
    if query.city:
        statement = statement.where(SportOrganization.city == query.city)
    if query.q:
        pattern = f"%{query.q}%"
        statement = statement.where(
            or_(
                SportOrganization.name.ilike(pattern),
                SportOrganization.city.ilike(pattern),
                SportOrganization.description.ilike(pattern),
            )
        )

    result = await db.execute(
        statement.order_by(
            SportOrganization.sort_order,
            SportOrganization.name,
            SportOrganization.id,
        )
        .limit(query.limit + 1)
        .offset(query.offset)
    )
    organizations = result.scalars().all()
    return organizations[:query.limit], len(organizations) > query.limit


def _render_card(gym: SportOrganization) -> str:
    name = gym.name or ""
    city = gym.city or ""
    description = gym.description or ""
    href = "/sport/" + quote(gym.slug, safe="")
    image = ui.mark(name, image=gym.logo_url or "", alt=name, size="lg")
    description_html = (
        f'<p class="gym-description">{html.escape(description)}</p>'
        if description
        else ""
    )
    return (
        '<article class="r-salon gym-card" data-gym-id="'
        f'{gym.id}" data-layout="horizontal">'
        '<div class="r-salon__layout">'
        f'<a class="r-salon__image" href="{html.escape(href, quote=True)}" '
        f'aria-label="Открыть {html.escape(name, quote=True)}">{image}</a>'
        '<div class="r-salon__body">'
        '<div class="r-salon__top"><a class="r-salon__face" '
        f'href="{html.escape(href, quote=True)}">'
        '<span class="r-salon__id">'
        f'<span class="r-salon__name">{html.escape(name)}</span>'
        f'<span class="r-salon__where">{html.escape(city)}</span>'
        '</span></a></div>'
        f'{description_html}'
        f'<a class="r-salon__all" href="{html.escape(href, quote=True)}">'
        'Открыть страницу</a>'
        '</div></div></article>'
    )


def _query_string(query: GymQuery, *, limit: Optional[int] = None) -> str:
    values = {}
    if query.q:
        values["q"] = query.q
    if query.city:
        values["city"] = query.city
    if limit is not None:
        values["limit"] = str(limit)
    return urlencode(values)


async def render_gyms_grid(db: AsyncSession, query: GymQuery) -> str:
    gyms, has_more = await _load_page(db, query)
    if not gyms and query.offset == 0:
        return render_empty_state(
            title="Ничего не найдено",
            text="Попробуйте изменить запрос или выбрать другой город.",
            icon=ICON_SEARCH,
            action_href="/sport",
            action_label="Сбросить фильтры",
        )

    cards = "".join(_render_card(gym) for gym in gyms)
    if has_more:
        href = "/sport?" + _query_string(query, limit=query.limit + PAGE_SIZE)
        cards += (
            '<div class="salons-more">'
            + ui.button(
                "Показать ещё",
                kind="secondary",
                href=href,
                classes="salons-more-btn",
            )
            + "</div>"
        )
    return cards


async def render_gyms_page(
    db: AsyncSession,
    user=None,
    query: Optional[GymQuery] = None,
    partial: bool = False,
) -> str:
    query = query or GymQuery()
    if partial:
        return await render_gyms_grid(db, query)

    cities = await _available_cities(db)
    all_cities = cities if not query.city or query.city in cities else [query.city, *cities]
    city_options = '<option value="">Все города</option>' + "".join(
        f'<option value="{html.escape(city, quote=True)}"'
        f'{" selected" if city == query.city else ""}>{html.escape(city)}</option>'
        for city in all_cities
    )
    search_value = html.escape(query.q, quote=True)
    grid = await render_gyms_grid(db, query)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Спорт — руми</title>
    <meta name="description" content="Спортивные клубы, школы и секции рядом с вами.">
    {get_base_styles()}
</head>
<body>
    {render_header("sport", user)}
    <main class="main-content">
        <section class="catalog-hero">
            <div class="section-container">
                <div class="catalog-hero__intro">
                    <h1 class="r-display">Спорт рядом</h1>
                    <p class="r-text r-muted">Спортивные клубы, школы и секции на Руми.</p>
                </div>
                <div class="catalog-search">
                    <span class="catalog-search__icon" aria-hidden="true">{ICON_SEARCH}</span>
                    <input type="search" name="q" id="gymSearchInput" form="gymsFilterForm"
                           value="{search_value}" placeholder="Название клуба или направление"
                           class="search-input" aria-label="Поиск по спортивным залам"
                           enterkeyhint="search">
                    {ui.button("Найти", type_="submit", small=True, form="gymsFilterForm")}
                </div>
                <p class="gym-business-link">{ui.button("Подключить спортивный клуб", kind="secondary", href="/sport/business")}</p>
            </div>
        </section>
        <section class="catalog-body">
            <div class="section-container">
                <form method="get" action="/sport" id="gymsFilterForm" class="salons-filter-bar">
                    <div class="filter-row">
                        <div class="city-select-wrapper">
                            {ICON_MAP_PIN}
                            <select id="gymCitySelect" name="city" class="city-select custom-select"
                                    onchange="if(!this.form.dataset.ajax)this.form.submit()">
                                {city_options}
                            </select>
                        </div>
                    </div>
                </form>
                <div id="gyms-list" class="salons-grid">{grid}</div>
            </div>
        </section>
        {render_footer(user)}
    </main>
</body>
</html>"""
