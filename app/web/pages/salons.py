# app/web/pages/salons.py
import html
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Salon, Promotion, Master, Service, SalonModerationStatus
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
from app.web.service_categories import SERVICE_CATEGORY_GROUPS, match_category_slugs, slug_to_label


async def render_salons_page(db: AsyncSession, user=None) -> str:
    """Страница со списком салонов: поиск (по названию/описанию/реальным
    услугам мастеров), фильтры (категория/рейтинг/акции) и сортировка
    (рейтинг/отзывы/расстояние) — всё на клиенте, без перезагрузки страницы."""

    result = await db.execute(
        select(Salon).where(
            Salon.is_active == True, Salon.moderation_status == SalonModerationStatus.APPROVED,
            Salon.published_at.isnot(None), Salon.is_hidden == False,
        ).order_by(Salon.rating.desc())
    )
    salons = result.scalars().all()

    # Загружаем акции для всех салонов
    salon_ids = [s.id for s in salons]
    promotions_by_salon = {}
    if salon_ids:
        promos_result = await db.execute(
            select(Promotion).where(
                Promotion.salon_id.in_(salon_ids),
                Promotion.is_active == True
            ).order_by(Promotion.salon_id, Promotion.id)
        )
        promotions = promos_result.scalars().all()
        for p in promotions:
            promotions_by_salon.setdefault(p.salon_id, []).append(p)

    # Реальные названия услуг мастеров каждого салона — чтобы поиск и теги
    # на карточке отражали то, что салон реально предлагает, а не только
    # ключевые слова, которые владелец случайно упомянул в описании.
    services_by_salon: dict[int, list[str]] = {}
    if salon_ids:
        services_result = await db.execute(
            select(Master.salon_id, Service.name)
            .join(Master, Master.id == Service.master_id)
            .where(
                Master.salon_id.in_(salon_ids), Master.is_active == True,
                Service.is_active == True, Service.is_model_practice == False,
            )
        )
        for salon_id, service_name in services_result.all():
            services_by_salon.setdefault(salon_id, []).append(service_name)

    salon_cards = ""
    available_cities: set[str] = set()
    for s in salons:
        service_names = services_by_salon.get(s.id, [])
        # "Стог сена" для текстового поиска — описание салона + реальные
        # названия услуг мастеров, чтобы находилось по слову из услуги, даже
        # если его нет в описании.
        haystack = ((s.description or "") + " " + " ".join(service_names)).lower()
        # А вот категории (теги на карточке + пункты в фильтре) матчим строго
        # по названиям услуг мастеров, а не по свободному тексту описания —
        # категория должна означать «это реально можно забронировать», а не
        # «владелец упомянул слово в описании».
        matched_categories = match_category_slugs(" ".join(service_names))

        if s.city:
            available_cities.add(s.city)

        service_chips = "".join(
            f'<span class="service-chip">{slug_to_label(slug)}</span>' for slug in matched_categories[:3]
        ) or '<span class="service-chip">Услуги</span>'

        rating = s.rating or 0.0
        reviews = s.reviews_count or 0

        heart_svg = ICON_HEART.replace('"', '&quot;')
        heart_filled_svg = ICON_HEART_FILLED.replace('"', '&quot;')

        # Обложка (logo_url, назначается в «Мой салон»); без неё — градиент
        # с первой буквой: файла default-salon.jpg больше нет, битую картинку
        # не показываем
        if s.logo_url:
            image_html = f'<img src="{s.logo_url}" alt="{s.name}">'
        else:
            image_html = (
                f'<div style="width:100%;height:100%;display:flex;align-items:center;'
                f'justify-content:center;background:linear-gradient(135deg,var(--color-primary),var(--color-accent));'
                f'color:#fff;font-size:3rem;font-weight:700">{s.name[0].upper()}</div>'
            )

        # --- Акции салона (до 3-х) ---
        promos = promotions_by_salon.get(s.id, [])[:3]
        promo_items = ""
        for promo in promos:
            promo_items += f"""
            <div class="promo-item">
                <span class="promo-tag" style="background: linear-gradient(135deg, var(--color-primary), var(--color-accent-hover));">
                    {promo.tag}
                </span>
                <div class="promo-info">
                    <span class="promo-title">{promo.title}</span>
                    <span class="promo-desc">{promo.description or ''}</span>
                </div>
            </div>
            """

        # Блок акций для десктопа (справа)
        desktop_promo_block = ""
        if promo_items:
            desktop_promo_block = f"""
            <div class="salon-promo-desktop">
                <p class="promo-label">Акции</p>
                {promo_items}
            </div>
            """

        # Блок акций для мобилки (внизу)
        mobile_promo_block = ""
        if promo_items:
            mobile_promo_block = f"""
            <div class="salon-promo-mobile">
                <p class="promo-label">Акции</p>
                {promo_items}
            </div>
            """

        search_haystack = html.escape(f"{s.name} {haystack}", quote=True)
        city_attr = html.escape(s.city or "", quote=True)

        salon_cards += f"""
        <div class="salon-card"
             data-salon-id="{s.id}"
             data-search="{search_haystack}"
             data-categories="{' '.join(matched_categories)}"
             data-city="{city_attr}"
             data-rating="{rating}"
             data-reviews="{reviews}"
             data-lat="{s.latitude}"
             data-lon="{s.longitude}"
             data-has-promo="{1 if promos else 0}">
            <div class="salon-card-inner">
                <div class="salon-image">
                    {image_html}
                    <button class="favorite-btn"
                            data-type="salon"
                            data-id="{s.id}"
                            data-icon-heart="{heart_svg}"
                            data-icon-heart-filled="{heart_filled_svg}"
                            title="В избранное">
                        <span class="heart-icon">{ICON_HEART}</span>
                    </button>
                </div>

                <div class="salon-info">
                    <div class="salon-info-header">
                        <div>
                            <h3 class="salon-name">{s.name}</h3>
                            <p class="salon-address">
                                {ICON_MAP_PIN}
                                {s.address or 'Адрес не указан'}
                            </p>
                        </div>
                        <div class="salon-rating-badge">
                            {ICON_STAR_FILLED}
                            <span class="rating-value">{rating:.1f}</span>
                            <span class="rating-count">({reviews})</span>
                        </div>
                    </div>
                    <p class="salon-desc">{s.description or ''}</p>
                    <div class="services-chips">
                        {service_chips}
                    </div>
                    <a href="/salons/{s.id}" class="btn-primary salon-btn">
                        Смотреть мастеров
                        {ICON_ARROW_RIGHT}
                    </a>
                </div>

                {desktop_promo_block}
            </div>

            {mobile_promo_block}
        </div>
        """

    if not salons:
        salon_cards = """
        <div class="salon-card" style="padding:3rem;text-align:center;">
            <p class="text-muted">Пока нет салонов. <a href="/register" style="color:var(--color-primary);">Зарегистрируйтесь</a> как владелец, чтобы добавить первый салон!</p>
        </div>
        """

    category_options = "".join(
        f'<label class="category-option" data-slug="{slug}"><input type="checkbox" value="{slug}"> {label}</label>'
        for slug, label, _keywords in SERVICE_CATEGORY_GROUPS
    )

    # Список городов — только те, где реально есть салоны (плюс «Все города»).
    # Список категорий в фильтре потом подрезается JS-ом под выбранный город:
    # категория, которую в этом городе никто не предлагает, из списка убирается.
    city_options = '<option value="">Все города</option>' + "".join(
        f'<option value="{html.escape(c, quote=True)}">{c}</option>' for c in sorted(available_cities)
    )

    filter_bar = f"""
    <div class="salons-filter-bar">
        <div class="filter-row filter-categories">
            <div class="city-select-wrapper">
                {ICON_MAP_PIN}
                <select id="citySelect" class="city-select">
                    {city_options}
                </select>
            </div>
            <div class="category-dropdown" id="categoryDropdown">
                <button type="button" class="category-dropdown-btn" id="categoryDropdownBtn">
                    {ICON_FILTER}
                    <span id="categoryDropdownLabel">Категории</span>
                    {ICON_CHEVRON_DOWN}
                </button>
                <div class="category-dropdown-panel" id="categoryDropdownPanel" hidden>
                    {category_options}
                    <p id="categoryEmptyHint" class="category-empty-hint" hidden>В этом городе пока нет салонов с такими услугами.</p>
                    <button type="button" class="category-clear-btn" id="categoryClearBtn">Сбросить</button>
                </div>
            </div>
        </div>
        <div class="filter-row filter-controls">
            <div class="filter-controls-left">
                <div class="filter-group" id="ratingFilterGroup">
                    <button type="button" class="filter-chip active" data-min-rating="0">Любой рейтинг</button>
                    <button type="button" class="filter-chip" data-min-rating="4.5">от 4.5</button>
                    <button type="button" class="filter-chip" data-min-rating="4">от 4.0</button>
                    <button type="button" class="filter-chip" data-min-rating="3.5">от 3.5</button>
                </div>
                <label class="promo-toggle">
                    <input type="checkbox" id="promoOnlyToggle">
                    Только с акциями
                </label>
            </div>
            <div class="sort-group">
                <label for="sortSelect">Сортировка</label>
                <select id="sortSelect" class="sort-select">
                    <option value="rating">По рейтингу</option>
                    <option value="reviews">По отзывам</option>
                    <option value="distance">Рядом со мной</option>
                </select>
            </div>
        </div>
    </div>
    """

    # Город из профиля — если он есть среди городов с салонами, JS выберет
    # его по умолчанию при первом визите (пока пользователь сам не переключил
    # город — тогда в приоритете его явный выбор, сохранённый в localStorage).
    user_city = getattr(user, "city", None) or ""
    if user_city not in available_cities:
        user_city = ""

    page_html = f"""<!DOCTYPE html>
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
                        <input type="text" id="searchInput" placeholder="Поиск салона по названию или услуге..." class="search-input">
                    </div>
                </div>
            </div>
        </section>

        <section class="section-py bg-surface salons-list-section">
            <div class="section-container">
                {filter_bar}
                <div id="salons-list" class="salons-grid">
                    {salon_cards}
                </div>
                <p id="salonsEmptyState" class="text-muted" style="display:none;text-align:center;padding:2rem">Ничего не найдено — попробуйте изменить фильтры.</p>
            </div>
        </section>

        {render_footer(user)}
    </main>
    <script>
        window.userCity = {json.dumps(user_city)};
    </script>
</body>
</html>"""

    return page_html