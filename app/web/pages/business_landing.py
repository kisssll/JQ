# app/web/pages/business_landing.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_BRIEFCASE,
    ICON_CALENDAR_DAYS,
    ICON_CHART_COLUMN,
    ICON_USERS,
    ICON_SHIELD_CHECK,
    ICON_CLOCK,
    ICON_TRENDING_UP,
    ICON_CIRCLE_CHECK,
    ICON_ARROW_RIGHT,
    ICON_ZAP,
    ICON_CIRCLE_X,
    ICON_CREDIT_CARD,
    ICON_PERCENT,
    ICON_STORE,
    ICON_SPARKLES,
)
from app.web.components.tbank import render_tbank_partner_banner


def render_business_landing_page(user=None) -> str:
    """Объединённая страница «Для бизнеса» (лендинг)."""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Для бизнеса | Руми</title>
    <meta name="description" content="руми — платформа, которая приводит клиентов и управляет салоном. Запись, оплата, касса, команда и аналитика — в одном окне.">
    {get_base_styles()}
</head>
<body>
    {render_header("business")}
    {render_sidebar("business", user)}

    <main class="home-main bl-wrapper">

        <!-- HERO -->
        <section class="bl-hero">
            <div class="section-container">
                <div class="bl-hero-content">
                    <span class="bl-hero-badge">Коммерческое предложение</span>
                    <h1 class="bl-hero-title">руми — платформа, которая приводит клиентов и управляет салоном</h1>
                    <p class="bl-hero-subtitle">Запись, оплаты, касса, команда и аналитика — в одном окне. Плюс поток новых клиентов из маркетплейса.</p>
                    <div class="bl-hero-buttons">
                        <a href="/business/checkout?plan=business" class="bl-hero-btn-primary">
                            Подключить салон
                            {ICON_ARROW_RIGHT}
                        </a>
                        <a href="#pricing" class="bl-hero-btn-secondary">Смотреть тарифы</a>
                    </div>
                </div>

                <!-- Статистика -->
                <!--
                <div class="bl-stats">
                    <div class="bl-stat-item">
                        <p class="bl-stat-value">−50%</p>
                        <p class="bl-stat-label">неявок клиентов</p>
                    </div>
                    <div class="bl-stat-item">
                        <p class="bl-stat-value">4 клика</p>
                        <p class="bl-stat-label">до записи</p>
                    </div>
                    <div class="bl-stat-item">
                        <p class="bl-stat-value">0 ₽</p>
                        <p class="bl-stat-label">подключение кассы</p>
                    </div>
                    <div class="bl-stat-item">
                        <p class="bl-stat-value">5%</p>
                        <p class="bl-stat-label">кешбэк клиентам</p>
                    </div>
                </div>
                -->
            </div>
        </section>

        <!-- Закрываем реальные боли -->
        <section class="section-py bl-pains">
            <div class="section-container">
                <div class="bl-section-header">
                    <span class="bl-badge bl-badge-lg">Зачем это салону</span>
                    <h2>Выбирайте лучшее — руми</h2>
                </div>
                <div class="bl-pains-grid">
                    <!-- Карточка 1 -->
                    <div class="bl-pain-card">
                        <div class="bl-pain-header">
                            {ICON_CIRCLE_CHECK}
                            <span class="bl-pain-title">Быстрый поиск клиентов для новых мастеров</span>
                        </div>
                        <div class="bl-pain-solution">
                            {ICON_CIRCLE_CHECK}
                            <p>Программа «Модели» заполняет слоты клиентами. Мастера набирают практику и портфолио, а салон получает оборот вместо простоя.</p>
                        </div>
                        <a href="#pricing" class="bl-pain-link">
                            {ICON_TRENDING_UP}
                            <span>Загрузка новых мастеров без затрат на рекламу</span>
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>

                    <!-- Карточка 2
                    <div class="bl-pain-card">
                        <div class="bl-pain-header">
                            {ICON_CIRCLE_X}
                            <span class="bl-pain-title">Записи срываются, клиенты не приходят</span>
                        </div>
                        <div class="bl-pain-solution">
                            {ICON_CIRCLE_CHECK}
                            <p>Онлайн-предоплата через Т‑Банк закрепляет бронь. Клиент, который оплатил вперёд, почти всегда доходит, а свободные слоты не простаивают впустую.</p>
                        </div>
                        <a href="#pricing" class="bl-pain-link">
                            {ICON_TRENDING_UP}
                            <span>Снижение неявок (no-show) до 50%</span>
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>
                    -->

                    <!-- Карточка 3 -->
                    <div class="bl-pain-card">
                        <div class="bl-pain-header">
                            {ICON_CIRCLE_CHECK}
                            <span class="bl-pain-title">Много новых клиентов, бесплатная реклама</span>
                        </div>
                        <div class="bl-pain-solution">
                            {ICON_CIRCLE_CHECK}
                            <p>Салон попадает в маркетплейс руми — витрину, куда люди приходят искать, где постричься. Это поток новых клиентов, а не просто хранилище для текущих.</p>
                        </div>
                        <a href="#pricing" class="bl-pain-link">
                            {ICON_TRENDING_UP}
                            <span>Новые клиенты из поиска без бюджета на привлечение</span>
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>

                    <!-- Карточка 4 -->
                    <div class="bl-pain-card">
                        <div class="bl-pain-header">
                            {ICON_CIRCLE_CHECK}
                            <span class="bl-pain-title">Клиенты не звонят, чтобы записаться</span>
                        </div>
                        <div class="bl-pain-solution">
                            {ICON_CIRCLE_CHECK}
                            <p>Онлайн-запись за 4 клика — без звонков и форм. Клиент выбирает услугу, мастера и время сам, в любое время суток, а расписание обновляется в реальном времени.</p>
                        </div>
                        <a href="#pricing" class="bl-pain-link">
                            {ICON_TRENDING_UP}
                            <span>До 40% записей приходят вне рабочих часов администратора</span>
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>

                    <!-- Карточка 5 
                    <div class="bl-pain-card">
                        <div class="bl-pain-header">
                            {ICON_CIRCLE_X}
                            <span class="bl-pain-title">Касса, чеки и 54-ФЗ — отдельная головная боль</span>
                        </div>
                        <div class="bl-pain-solution">
                            {ICON_CIRCLE_CHECK}
                            <p>Эквайринг, торговый терминал и онлайн-касса Т‑Банка подключаются из коробки. Фискальные чеки формируются автоматически — без отдельных договоров и интеграторов.</p>
                        </div>
                        <a href="#pricing" class="bl-pain-link">
                            {ICON_TRENDING_UP}
                            <span>Подключение за 1 день, 0 ₽ за старт</span>
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>
                    -->

                    <!-- Карточка 6 -->
                    <div class="bl-pain-card">
                        <div class="bl-pain-header">
                            {ICON_CIRCLE_CHECK}
                            <span class="bl-pain-title">Видно, что реально приносит деньги</span>
                        </div>
                        <div class="bl-pain-solution">
                            {ICON_CIRCLE_CHECK}
                            <p>Понятные дашборды: выручка, загрузка по мастерам, средний чек, возвраты клиентов. Видно, какие услуги и сотрудники работают, а какие тянут вниз.</p>
                        </div>
                        <a href="#pricing" class="bl-pain-link">
                            {ICON_TRENDING_UP}
                            <span>Решения по цифрам, а не по ощущениям</span>
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>
                </div>
            </div>
        </section>

        <!-- Возможности -->
        <section id="features" class="section-py bl-features bl-gradient-up">
            <div class="section-container">
                <div class="bl-section-header">
                    <span class="bl-badge">Возможности</span>
                    <h2>Всё для вашего салона</h2>
                    <p>От расписания до аналитики — управляйте бизнесом в одном месте</p>
                </div>
                <div class="bl-features-grid">
                    <div class="bl-feature-card">
                        <div class="bl-feature-header">
                            <div class="bl-icon-wrapper">{ICON_CALENDAR_DAYS}</div>
                            <h3>Управление расписанием</h3>
                        </div>
                        <p>Полный контроль над записями мастеров. Окна, отмены, переносы — всё в реальном времени. Клиенты записываются онлайн.</p>
                    </div>
                    <div class="bl-feature-card">
                        <div class="bl-feature-header">
                            <div class="bl-icon-wrapper">{ICON_CHART_COLUMN}</div>
                            <h3>Аналитика доходов</h3>
                        </div>
                        <p>Отслеживайте выручку по дням, неделям и месяцам. Смотрите какие услуги приносят больше прибыли и кто из мастеров самый эффективный.</p>
                    </div>
                    <div class="bl-feature-card">
                        <div class="bl-feature-header">
                            <div class="bl-icon-wrapper">{ICON_USERS}</div>
                            <h3>Привлечение клиентов</h3>
                        </div>
                        <p>Ваш салон видят тысячи пользователей руми. Рейтинг и отзывы помогают выделиться. Модели приходят сами.</p>
                    </div>
                    <div class="bl-feature-card">
                        <div class="bl-feature-header">
                            <div class="bl-icon-wrapper">{ICON_SHIELD_CHECK}</div>
                            <h3>Проверенные клиенты</h3>
                        </div>
                        <p>Все пользователи верифицированы. Меньше отмен, больше лояльных клиентов, рейтинг доверия для каждого.</p>
                    </div>
                    <div class="bl-feature-card">
                        <div class="bl-feature-header">
                            <div class="bl-icon-wrapper">{ICON_CLOCK}</div>
                            <h3>Экономия времени</h3>
                        </div>
                        <p>Автоматические напоминания клиентам, управление очередью, синхронизация с календарём — рутина на автопилоте.</p>
                    </div>
                    <div class="bl-feature-card">
                        <div class="bl-feature-header">
                            <div class="bl-icon-wrapper">{ICON_TRENDING_UP}</div>
                            <h3>Рост бизнеса</h3>
                        </div>
                        <p>Инструменты для масштабирования: акции, программы лояльности, работа с несколькими филиалами из одного кабинета.</p>
                    </div>
                </div>
            </div>
        </section>

        <!-- Сравнение -->
        <section class="section-py bl-comparison">
            <div class="section-container">
                <div class="bl-section-header">
                    <span class="bl-badge">Сравнение</span>
                    <h2>Почему руми, а не другие</h2>
                </div>
                <div class="bl-comparison-table">
                    <div class="bl-comparison-header">
                        <span>Что важно салону</span>
                        <span class="bl-comparison-brand">руми</span>
                        <span class="bl-comparison-other-title">Другие CRM</span>
                    </div>
                    <!--
                    <div class="bl-comparison-row">
                        <span>Подключение эквайринга и кассы</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Из коробки, 0 ₽</span>
                        <span class="bl-comparison-other">Доплата + настройка</span>
                    </div>
                    -->
                    <!--
                    <div class="bl-comparison-row">
                        <span>Онлайн-предоплата за запись</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Да, через Т‑Банк</span>
                        <span class="bl-comparison-other">Через сторонние модули</span>
                    </div>
                    -->
                    <div class="bl-comparison-row">
                        <span>Маркетплейс клиентов</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Встроен — поток новых клиентов</span>
                        <span class="bl-comparison-other">Только CRM</span>
                    </div>
                    <div class="bl-comparison-row">
                        <span>Программа «Модели»</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Модели сами бронируют свободные окна мастеров</span>
                        <span class="bl-comparison-other">Нет</span>
                    </div>
                    <div class="bl-comparison-row">
                        <span>Встроенная CRM</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Уже внутри, без интеграций</span>
                        <span class="bl-comparison-other">Отдельная система</span>
                    </div>
                    <div class="bl-comparison-row">
                        <span>Аналитика салона</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} По мастерам, услугам и выручке</span>
                        <span class="bl-comparison-other">Урезанная или платно</span>
                    </div>
                    <div class="bl-comparison-row">
                        <span>Складской учёт</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Остатки материалов считаются автоматически</span>
                        <span class="bl-comparison-other">Часто платный модуль</span>
                    </div>
                    <div class="bl-comparison-row">
                        <span>Всё в одном окне и приложении</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Запись, CRM и аналитика — в одном месте</span>
                        <span class="bl-comparison-other">Разные системы</span>
                    </div>
                    <div class="bl-comparison-row">
                        <span>Быстрая поддержка</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} Ответ в течение часа</span>
                        <span class="bl-comparison-other">Долгие очереди тикетов</span>
                    </div>
                    <div class="bl-comparison-row">
                        <span>Стоимость входа</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} От 250 ₽ за сотрудника</span>
                        <span class="bl-comparison-other">Выше, пакеты</span>
                    </div>
                    <!--
                    <div class="bl-comparison-row">
                        <span>Кешбэк клиентам</span>
                        <span class="bl-comparison-rumi">{ICON_CIRCLE_CHECK} 5% с Т‑Картой</span>
                        <span class="bl-comparison-other">Нет</span>
                    </div>
                    -->
                </div>
            </div>
        </section>

        <!-- Как подключить -->
        <section id="how-it-works" class="section-py bl-how bl-gradient-down">
            <div class="section-container">
                <div class="bl-section-header">
                    <span class="bl-badge">Начало работы</span>
                    <h2>Как подключить салон</h2>
                    <p>4 шага — и ваш салон на платформе</p>
                </div>
                <div class="bl-how-steps">
                    <div class="bl-how-step">
                        <span class="bl-step-num" aria-hidden="true">1</span>
                        <div class="bl-step-content">
                            <h3 class="bl-step-title">Зарегистрируйте салон</h3>
                            <p class="bl-step-desc">Создайте профиль салона, добавьте фото, описание, адрес и список услуг.</p>
                        </div>
                    </div>
                    <div class="bl-how-step">
                        <span class="bl-step-num" aria-hidden="true">2</span>
                        <div class="bl-step-content">
                            <h3 class="bl-step-title">Настройте расписание</h3>
                            <p class="bl-step-desc">Добавьте мастеров, их графики, услуги и цены. Всё настраивается за 15 минут.</p>
                        </div>
                    </div>
                    <div class="bl-how-step">
                        <span class="bl-step-num" aria-hidden="true">3</span>
                        <div class="bl-step-content">
                            <h3 class="bl-step-title">Привлекайте клиентов</h3>
                            <p class="bl-step-desc">Оплатите подписку — и ваш салон появится в общем списке платформы. Клиенты и модели начнут записываться.</p>
                        </div>
                    </div>
                    <div class="bl-how-step">
                        <span class="bl-step-num" aria-hidden="true">4</span>
                        <div class="bl-step-content">
                            <h3 class="bl-step-title">Развивайте бизнес</h3>
                            <p class="bl-step-desc">Используйте аналитику, акции и программы лояльности для роста.</p>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Партнёрство с Т‑Банком -->
        {render_tbank_partner_banner()}

        <!-- Тарифы -->
        <section id="pricing" class="section-py bl-pricing">
            <div class="section-container">
                <div class="bl-section-header">
                    <span class="bl-badge">Тарифы</span>
                    <h2>Простые и прозрачные цены</h2>
                    <p>Выберите тариф под размер вашего салона. Более 20 сотрудников? Свяжитесь с нами для индивидуального предложения.</p>
                </div>
                <div class="bl-pricing-grid">
                    <!-- Лайт -->
                    <div class="bl-pricing-card">
                        <div class="bl-plan-name" style="text-align: center;">Лайт</div>
                        <div class="bl-plan-sub" style="text-align: center;">До 5 сотрудников</div>
                        <div class="bl-plan-price">
                            <span class="bl-price-amount">250 ₽</span>
                            <span class="bl-price-period">за сотрудника/мес</span>
                        </div>
                        <ul class="bl-plan-features">
                            <li>{ICON_CIRCLE_CHECK}<span>Оплата только за сотрудников</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Управление расписанием</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Онлайн-запись клиентов</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Базовая аналитика</span></li>
                        </ul>
                        <a href="/business/checkout?plan=lite" class="bl-plan-btn">
                            Подключить
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>

                    <!-- Бизнес (популярный) -->
                    <div class="bl-pricing-card bl-popular">
                        <div class="bl-popular-badge">Популярный</div>
                        <div class="bl-plan-name" style="text-align: center;">Бизнес</div>
                        <div class="bl-plan-sub" style="text-align: center;">От 5 до 10 сотрудников</div>
                        <div class="bl-plan-price">
                            <span class="bl-price-amount">3 500 ₽</span>
                            <span class="bl-price-period">/мес</span>
                        </div>
                        <ul class="bl-plan-features">
                            <li>{ICON_CIRCLE_CHECK}<span>Всё из тарифа «Лайт»</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Расширенная аналитика</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Приоритет в выдаче</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Акции и программы лояльности</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Персональная поддержка</span></li>
                        </ul>
                        <a href="/business/checkout?plan=business" class="bl-plan-btn">
                            Подключить
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>

                    <!-- Корпоративный -->
                    <div class="bl-pricing-card">
                        <div class="bl-plan-name" style="text-align: center;">Корпоративный</div>
                        <div class="bl-plan-sub" style="text-align: center;">От 10 до 20 сотрудников</div>
                        <div class="bl-plan-price">
                            <span class="bl-price-amount">6 990 ₽</span>
                            <span class="bl-price-period">/мес</span>
                        </div>
                        <ul class="bl-plan-features">
                            <li>{ICON_CIRCLE_CHECK}<span>Всё из тарифа «Бизнес»</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Мульти-филиалы</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>VIP поддержка</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Индивидуальные интеграции</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Расширенная отчётность</span></li>
                            <li>{ICON_CIRCLE_CHECK}<span>Выделенный менеджер</span></li>
                        </ul>
                        <a href="/business/checkout?plan=corporate" class="bl-plan-btn">
                            Подключить
                            {ICON_ARROW_RIGHT}
                        </a>
                    </div>
                </div>
                <div class="bl-pricing-footer">
                    Более 20 сотрудников? <a href="/business/checkout?plan=custom" class="bl-text-link">Запросите индивидуальный тариф</a>
                </div>
            </div>
        </section>
        {render_footer(user)}
    </main>
</body>
</html>"""
    return html