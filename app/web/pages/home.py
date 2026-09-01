# app/web/pages/home.py
from app.web.components.escaping import e
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Salon, SalonModerationStatus
from app.services.subscription import access_clause
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_SEARCH,
    ICON_SCISSORS,
    ICON_SPARKLES,
    ICON_PERCENT,
    ICON_STORE,
    ICON_ARROW_RIGHT,
    ICON_MAP_PIN,
    ICON_STAR_FILLED,
)
from app.web.components.tbank import render_tbank_partner_banner


async def render_home_page(db: AsyncSession, user=None) -> str:
    """Главная страница руми."""

    # Получаем популярные салоны (топ-3 по рейтингу)
    try:
        result = await db.execute(
            select(Salon).where(
                Salon.is_active == True, Salon.moderation_status == SalonModerationStatus.APPROVED,
                Salon.published_at.isnot(None), Salon.is_hidden == False,
                access_clause(Salon),  # тариф: доступ открыт
            ).order_by(Salon.rating.desc()).limit(3)
        )
        salons = result.scalars().all()
    except Exception as exc:
        # имя exc, а не e: e — экранировщик HTML, импортированный выше
        print(f"Ошибка загрузки салонов: {exc}")
        salons = []

    # Карточки салонов
    salon_cards = ""
    for s in salons:
        logo_html = ""
        if s.logo_url:
            logo_html = f'<img src="{s.logo_url}" alt="{e(s.name)}" class="popular-salon-avatar-img" loading="lazy">'
        else:
            logo_html = f'<span class="popular-salon-avatar-letter">{e(s.name[0].upper())}</span>'

        city = s.address.split(',')[0].strip() if s.address else "Адрес не указан"

        salon_cards += f"""
        <a href="/salons/{s.id}" class="popular-salon-link">
            <div class="popular-salon-card">
                <div class="popular-salon-avatar">
                    {logo_html}
                </div>
                <h3 class="popular-salon-name">{e(s.name)}</h3>
                <p class="popular-salon-address">
                    {ICON_MAP_PIN} {city}
                </p>
                <div class="popular-salon-rating">
                    {ICON_STAR_FILLED}
                    <span class="rating-value">{s.rating or 0.0:.1f}</span>
                    <span class="rating-count">({s.reviews_count or 0} отзывов)</span>
                </div>
            </div>
        </a>
        """

    if not salons:
        salon_cards = '<p class="salon-empty">Пока нет салонов. <a href="/register">Зарегистрируйтесь</a> как владелец, чтобы добавить первый салон!</p>'

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Руми — мастера и салоны красоты рядом</title>
    <meta name="description" content="Платформа для клиентов и бизнеса: находите лучших мастеров, становитесь моделью или управляйте своим салоном.">
    {get_base_styles()}
</head>
<body>
    {render_header("home")}
    {render_sidebar("home", user)}

    <main class="home-main">
        <!-- Hero секция -->
        <section class="home-hero">
        
            <img src="/static/images/flower-home.jpg" alt="" class="home-hero-bg-img">
            <div class="home-hero-gradient"></div>

            <div class="section-container">
                <div class="home-hero-content">
                    <h1 class="home-hero-title text-display">
                        Красота — это просто<span class="dot-primary">.</span>
                    </h1>
                    <p class="home-hero-subtitle text-body-lg">
                        Салон, услуга, время — готово. Без звонков и ожиданий.
                    </p>

                    <!-- Поиск -->
                    <div class="home-search-card">
                        <a href="/salons" class="home-search-link group">
                            <div class="home-search-icon-wrapper">
                                {ICON_SEARCH}
                            </div>
                            <div class="home-search-info">
                                <span class="home-search-title">Найти салон или услугу</span>
                                <span class="home-search-desc">Маникюр, стрижка, окрашивание, брови...</span>
                            </div>
                            <div class="home-search-btn">Найти</div>
                        </a>
                    </div>

                    <!-- Теги удалены по запросу -->
                </div>
            </div>
        </section>

        <!-- Как записаться -->
        <section class="section-py" style="background:var(--color-surface);">
            <div class="section-container">
                <div class="how-title-wrapper">
                    <h2 class="how-title">
                        Как записаться<span class="how-title-dot">?</span>
                    </h2>
                    <p class="how-subtitle">
                        Никаких звонков. Никаких форм с десятью полями. Ничего лишнего.
                    </p>
                </div>

                <!-- Блок с 4 шагами -->
                <div class="steps-grid">
                    <div class="step-item">
                        <span class="step-num">1</span>
                        <h3 class="step-headline">Салон</h3>
                        <p class="step-desc">Выберите подходящий салон с нужным мастером.</p>
                    </div>
                    <div class="step-item">
                        <span class="step-num">2</span>
                        <h3 class="step-headline">Услуга</h3>
                        <p class="step-desc">Выберите что нужно сделать.</p>
                    </div>
                    <div class="step-item">
                        <span class="step-num">3</span>
                        <h3 class="step-headline">Время</h3>
                        <p class="step-desc">Возьмите свободное окно.</p>
                    </div>
                    <div class="step-item">
                        <span class="step-num">4</span>
                        <h3 class="step-headline">Готово</h3>
                        <p class="step-desc">Приходите. Напоминание придёт само.</p>
                    </div>
                </div>
            </div>
        </section>
        
        <!-- Популярные салоны -->
        <section class="section-py popular-salons-section">
            <div class="section-container">
                <div class="popular-salons-header">
                    <h2 class="text-display popular-salons-title">Популярные салоны</h2>
                    <p class="text-muted popular-salons-subtitle">Лучшие салоны красоты по отзывам пользователей руми</p>
                </div>
                <div class="popular-salons-grid">
                    {salon_cards}
                </div>
                <div class="popular-salons-footer">
                    <a href="/salons" class="btn-outline popular-salons-btn">Смотреть все салоны →</a>
                </div>
            </div>
        </section>

        <!-- Партнёрство с Т‑Банком -->
        {render_tbank_partner_banner()}

        <!-- Стать моделью -->
        <section class="section-py" id="become-model">
            <div class="section-container">
                <div class="model-label">Для клиентов</div>
                <div class="model-header">
                    <div class="model-title-wrap">
                        <h2 class="model-title">Стать моделью —<br />и платить меньше<span class="model-title-dot">.</span></h2>
                        <p class="model-subtitle">Мастерам нужна практика. Вам — красивая стрижка или новая техника. Подписка — и услуги до 70% дешевле.</p>
                    </div>
                </div>
                <div class="model-grid">
                    <div class="model-item">
                        <p class="model-item-desc">Услуги от мастеров со скидкой до <span class="model-item-highlight">70%</span></p>
                    </div>
                    <div class="model-item">
                        <p class="model-item-desc"><span class="model-item-highlight">Первыми</span> получаете лучшие окна записи</p>
                    </div>
                    <div class="model-item">
                        <p class="model-item-desc"><span class="model-item-highlight">Первые</span> тестируете процедуры и техники</p>
                    </div>
                    <div class="model-item">
                        <p class="model-item-desc"><span class="model-item-highlight">Профессиональные</span> фото после визита</p>
                    </div>
                </div>
                <div class="model-cta">
                    <a href="/model" class="btn-primary model-btn">
                        Оформить подписку
                        {ICON_ARROW_RIGHT}
                    </a>
                </div>
            </div>
        </section>

        <!-- Для бизнеса -->
        <section class="section-py section-gradient" id="for-business">
            <div class="section-container">
                <div class="business-label">Для бизнеса</div>
                <div class="business-header">
                    <div class="business-title-wrap">
                        <h2 class="business-title">Управлять салоном —<br />тоже просто<span class="business-title-dot">.</span></h2>
                        <p class="business-subtitle">Расписание, оплаты, клиенты, аналитика — всё в одном окне. Подключение за 15 минут. Первые 14 дней бесплатно.</p>
                    </div>
                </div>
                <div class="business-grid">
                    <div class="business-item">
                        <div class="business-number">1</div>
                        <h3 class="business-item-title">Расписание</h3>
                        <p class="business-item-desc">Записи мастеров — в одном окне.</p>
                    </div>
                    <div class="business-item">
                        <div class="business-number">2</div>
                        <h3 class="business-item-title">Клиенты</h3>
                        <p class="business-item-desc">История, заметки, повторные визиты.</p>
                    </div>
                    <div class="business-item">
                        <div class="business-number">3</div>
                        <h3 class="business-item-title">Оплата</h3>
                        <p class="business-item-desc">Касса, чаевые, отчёты — внутри.</p>
                    </div>
                    <div class="business-item">
                        <div class="business-number">4</div>
                        <h3 class="business-item-title">Аналитика</h3>
                        <p class="business-item-desc">Выручка, загрузка, эффективность.</p>
                    </div>
                </div>
                <div class="business-cta">
                    <a href="/business" class="btn-primary business-btn">
                        Подробнее
                        {ICON_ARROW_RIGHT}
                    </a>
                </div>
            </div>
        </section>

        {render_footer(user)}
    </main>
</body>
</html>"""

    return html