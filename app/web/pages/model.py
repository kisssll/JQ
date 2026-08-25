# app/web/pages/model.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_CALENDAR_DAYS,
    ICON_CHECK,
    ICON_GIFT,
    ICON_MONEY,
    ICON_STAR_FILLED,
)


def render_model_page(user=None) -> str:
    """Страница 'Стань моделью' с тарифами и информацией."""
    
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Стань моделью — руми</title>
    {get_base_styles()}
    <style>
        .model-hero {{
            background: linear-gradient(135deg, var(--page-gradient-1), var(--page-gradient-2), var(--page-gradient-3));
            text-align: center;
            padding: 6rem 2rem 4rem;
        }}
        .model-hero h1 {{
            font-size: 3rem;
            margin-bottom: 1rem;
        }}
        .model-hero p {{
            font-size: 1.15rem;
            color: var(--color-muted);
            max-width: 35rem;
            margin: 0 auto 2rem;
        }}
        .pricing-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
            max-width: 60rem;
            margin: 0 auto;
        }}
        @media (max-width: 768px) {{
            .pricing-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .pricing-card {{
            background: var(--color-surface);
            border: 2px solid var(--color-border);
            border-radius: 1.5rem;
            padding: 2rem;
            text-align: center;
            transition: all 0.2s;
            position: relative;
        }}
        .pricing-card:hover {{
            border-color: var(--color-primary);
            box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            transform: translateY(-4px);
        }}
        .pricing-card.popular {{
            border-color: var(--color-primary);
            background: linear-gradient(to bottom, #fff, #fff5f5);
        }}
        .popular-badge {{
            position: absolute;
            top: -0.75rem;
            left: 50%;
            transform: translateX(-50%);
            background: linear-gradient(135deg, var(--color-primary), var(--color-accent));
            color: white;
            padding: 0.35rem 1.5rem;
            border-radius: 2rem;
            font-size: 0.75rem;
            font-weight: 700;
            white-space: nowrap;
        }}
        .plan-name {{
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--color-heading);
            margin-bottom: 0.75rem;
        }}
        .plan-price {{
            font-size: 3rem;
            font-weight: 800;
            color: var(--color-primary);
        }}
        .plan-price span {{
            font-size: 1rem;
            color: var(--color-muted);
        }}
        .plan-features {{
            list-style: none;
            padding: 0;
            margin: 1.5rem 0;
            text-align: left;
        }}
        .plan-features li {{
            padding: 0.5rem 0;
            font-size: 0.9rem;
            color: var(--color-body);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .plan-features li::before {{
            content: "\2713";
            color: #22c55e;
            font-weight: 700;
            font-size: 1rem;
        }}
        .how-it-works {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 2rem;
            max-width: 48rem;
            margin: 3rem auto 0;
            text-align: center;
        }}
        @media (max-width: 768px) {{
            .how-it-works {{
                grid-template-columns: 1fr;
            }}
        }}
        .step-circle {{
            width: 4rem;
            height: 4rem;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--color-primary), var(--color-accent));
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0 auto 1rem;
        }}
        .benefits {{
            background: linear-gradient(135deg, #FFF8F6, #F8C8DC33);
            padding: 4rem 0;
            margin-top: 4rem;
        }}
        .benefits h2 {{
            text-align: center;
            font-size: 2rem;
            margin-bottom: 2rem;
            color: var(--color-heading);
        }}
        .benefits-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1.5rem;
            max-width: 800px;
            margin: 0 auto;
            padding: 0 2rem;
        }}
        @media (max-width: 600px) {{
            .benefits-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .benefit-card {{
            background: var(--color-surface);
            border-radius: 1rem;
            padding: 1.5rem;
            display: flex;
            gap: 1rem;
            align-items: start;
        }}
        .benefit-icon {{
            font-size: 2rem;
            flex-shrink: 0;
        }}
        .benefit-card h3 {{
            font-size: 1.05rem;
            color: var(--color-heading);
            margin-bottom: 0.25rem;
        }}
        .benefit-card p {{
            font-size: 0.85rem;
            color: var(--color-muted);
        }}
    </style>
</head>
<body>
    {render_header("model")}
    {render_sidebar("model", user)}
    
    <main style="margin-right: 16rem;">
        <!-- Hero -->
        <section class="model-hero">
            <div class="section-container">
                <div class="badge" style="margin-bottom:1rem">По подписке</div>
                <h1 class="text-display">Стань моделью</h1>
                <p>Оформи подписку и получай услуги от лучших мастеров по специальным ценам. Пробуй новые процедуры, создавай образ мечты.</p>
            </div>
        </section>
        
        <!-- Тарифы -->
        <section class="section-py bg-surface">
            <div class="section-container">
                <div style="text-align:center;margin-bottom:3rem">
                    <h2 class="text-display" style="font-size:2rem">Выбери свой план</h2>
                    <p style="color:var(--color-muted)">Чем дольше подписка — тем выгоднее</p>
                </div>
                
                <div class="pricing-grid">
                    <!-- Старт -->
                    <div class="pricing-card">
                        <div class="plan-name">Старт</div>
                        <div class="plan-price">490 <span>₽/мес</span></div>
                        <ul class="plan-features">
                            <li>Скидка 30% на все услуги</li>
                            <li>2 записи в месяц</li>
                            <li>Доступ к базовым салонам</li>
                            <li>Push-уведомления</li>
                        </ul>
                        <a href="/model/checkout?plan=start" class="btn-primary" style="width:100%">Выбрать Старт</a>
                    </div>
                    
                    <!-- Про (популярный) -->
                    <div class="pricing-card popular">
                        <div class="popular-badge">ПОПУЛЯРНЫЙ</div>
                        <div class="plan-name">Про</div>
                        <div class="plan-price">990 <span>₽/мес</span></div>
                        <ul class="plan-features">
                            <li>Скидка 50% на все услуги</li>
                            <li>5 записей в месяц</li>
                            <li>Доступ ко всем салонам</li>
                            <li>Приоритетная запись</li>
                            <li>Эксклюзивные акции</li>
                        </ul>
                        <a href="/model/checkout?plan=pro" class="btn-primary" style="width:100%">Выбрать Про</a>
                    </div>
                    
                    <!-- Премиум -->
                    <div class="pricing-card">
                        <div class="plan-name">Премиум</div>
                        <div class="plan-price">1 990 <span>₽/мес</span></div>
                        <ul class="plan-features">
                            <li>Скидка 70% на все услуги</li>
                            <li>Безлимитные записи</li>
                            <li>Все салоны и мастера</li>
                            <li>VIP-поддержка 24/7</li>
                            <li>Закрытые мероприятия</li>
                            <li>Персональный стилист</li>
                        </ul>
                        <a href="/model/checkout?plan=premium" class="btn-primary" style="width:100%">Выбрать Премиум</a>
                    </div>
                </div>
                
                <!-- Партнёр (Альфа-Банк) — временно скрыт -->
                <!--
                <div class="partner-banner" style="max-width:60rem;margin:2rem auto 0">
                    <div class="alfa-logo">A</div>
                    <p>Оплачивай подписку <strong>Альфа‑Картой</strong> — получай <strong style="color:#EE3424">кешбэк 5%</strong> на все услуги мастеров</p>
                    <a href="https://alfabank.ru" target="_blank" class="btn-primary" style="background:#EE3424;font-size:0.8rem;padding:0.5rem 1rem;white-space:nowrap">Оформить карту →</a>
                    <span style="font-size:0.65rem;color:var(--color-muted)">Реклама · Альфа-Банк</span>
                </div>
                -->
                
                <!-- Как это работает -->
                <div style="margin-top:5rem;text-align:center">
                    <h2 class="text-display" style="font-size:2rem;margin-bottom:2rem">Как это работает</h2>
                    <div class="how-it-works">
                        <div>
                            <div class="step-circle">1</div>
                            <h3 style="margin-bottom:0.5rem">Выберите план</h3>
                            <p style="color:var(--color-muted);font-size:0.9rem">Подберите подходящий тариф под ваши потребности</p>
                        </div>
                        <div>
                            <div class="step-circle">2</div>
                            <h3 style="margin-bottom:0.5rem">Оплатите</h3>
                            <p style="color:var(--color-muted);font-size:0.9rem">Оплатите картой любого банка — быстро и безопасно</p>
                        </div>
                        <div>
                            <div class="step-circle">3</div>
                            <h3 style="margin-bottom:0.5rem">Записывайтесь</h3>
                            <p style="color:var(--color-muted);font-size:0.9rem">Выбирайте салоны и мастеров, записывайтесь со скидкой</p>
                        </div>
                    </div>
                </div>
            </div>
        </section>
        
        <!-- Преимущества -->
        <div class="benefits">
            <h2>Почему быть моделью выгодно?</h2>
            <div class="benefits-grid">
                <div class="benefit-card">
                    <div class="benefit-icon">{ICON_MONEY}</div>
                    <div>
                        <h3>Экономия до 70%</h3>
                        <p>Платишь только часть стоимости, остальное — за наш счёт</p>
                    </div>
                </div>
                <div class="benefit-card">
                    <div class="benefit-icon">{ICON_STAR_FILLED}</div>
                    <div>
                        <h3>Топ-мастера</h3>
                        <p>Проверенные салоны и мастера с высоким рейтингом</p>
                    </div>
                </div>
                <div class="benefit-card">
                    <div class="benefit-icon">{ICON_CALENDAR_DAYS}</div>
                    <div>
                        <h3>Приоритетная запись</h3>
                        <p>Модели получают места в первую очередь</p>
                    </div>
                </div>
                <div class="benefit-card">
                    <div class="benefit-icon">{ICON_GIFT}</div>
                    <div>
                        <h3>Бонусы и подарки</h3>
                        <p>Косметика и уходовые средства от партнёров</p>
                    </div>
                </div>
            </div>
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
    
    return html