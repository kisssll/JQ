# app/web/pages/model_landing.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_CAMERA,
    ICON_SPARKLES,
    ICON_USER_PLUS,
    ICON_SEARCH,
    ICON_CALENDAR_CHECK,
    ICON_ARROW_RIGHT,
)
from app.web.components.tbank import render_tbank_partner_banner

def render_model_landing_page(user=None) -> str:
    """Страница «Стань моделью» (лендинг)."""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Стань моделью | Руми</title>
    <meta name="description" content="Стань моделью бесплатно: заполни анкету и получай приглашения от мастеров для отработки техник.">
    {get_base_styles()}
</head>
<body>
    {render_header("model", user)}

    <main class="home-main">
        <!-- Hero -->
        <section class="model-hero">
            <div class="section-container">
                <div class="model-hero-content">
                    <div class="model-hero-badge">
                        {ICON_CAMERA}
                        <span>Бесплатно для моделей</span>
                    </div>
                    <h1 class="model-hero-title">Стань моделью в <span class="highlight">руми</span></h1>
                    <p class="model-hero-subtitle">Заполни анкету и получай приглашения от мастеров для отработки техник и создания портфолио. Участие в моделинге бесплатное.</p>
                    <div class="model-hero-buttons">
                        <a href="/model/join" class="model-hero-btn-primary">
                            Стать моделью бесплатно
                            {ICON_ARROW_RIGHT}
                        </a>
                        <a href="#how-it-works" class="model-hero-btn-secondary">Как это работает?</a>
                    </div>
                </div>
            </div>
        </section>

        <!-- Как это работает -->
        <section id="how-it-works" class="section-py model-how">
            <div class="section-container">
                <div class="section-header-center">
                    <span class="badge">Как это работает</span>
                    <h2>4 простых шага</h2>
                    <p>От анкеты до приглашения — всё просто и бесплатно</p>
                </div>
                <div class="how-steps-grid">
                    <div class="how-step-item">
                        <div class="step-icon">
                            {ICON_USER_PLUS}
                        </div>
                        <h3>Зарегистрируйся</h3>
                        <p>Создай аккаунт в руми и заполни профиль — расскажи о себе, загрузи фото.</p>
                    </div>
                    <div class="how-step-item">
                        <div class="step-icon">
                            {ICON_SPARKLES}
                        </div>
                        <h3>Заполни анкету</h3>
                        <p>Расскажи о себе и отметь услуги, в которых хочешь участвовать как модель.</p>
                    </div>
                    <div class="how-step-item">
                        <div class="step-icon">
                            {ICON_SEARCH}
                        </div>
                        <h3>Дождись одобрения</h3>
                        <p>После проверки анкеты мастера смогут приглашать тебя на отработку техник.</p>
                    </div>
                    <div class="how-step-item">
                        <div class="step-icon">
                            {ICON_CALENDAR_CHECK}
                        </div>
                        <h3>Выбери приглашение</h3>
                        <p>Общайся с мастером и выбери удобное время для процедуры.</p>
                    </div>
                </div>
            </div>
        </section>

        <!-- Партнёрство с Т‑Банком -->
        {render_tbank_partner_banner()}

        <section class="section-py model-plans">
            <div class="section-container">
                <div class="section-header-center">
                    <span class="badge">Без оплаты</span>
                    <h2>Моделинг бесплатный</h2>
                    <p>Заполнение анкеты и участие в поиске моделей ничего не стоят.</p>
                </div>
                <a href="/model/join" class="model-hero-btn-primary">Заполнить анкету {ICON_ARROW_RIGHT}</a>
            </div>
        </section>

        <!-- FAQ -->
        <section class="section-py model-faq">
            <div class="section-container">
                <div class="section-header-center">
                    <span class="badge">Вопросы</span>
                    <h2>Частые вопросы</h2>
                </div>
                <div class="faq-list">
                    <div class="faq-item">
                        <button class="faq-question">Что значит «стать моделью»? <span class="faq-icon">+</span></button>
                        <div class="faq-answer" style="display:none;">Стать моделью — значит получать приглашения от мастеров для отработки техник и создания портфолио.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">Кто может стать моделью? <span class="faq-icon">+</span></button>
                        <div class="faq-answer" style="display:none;">Любой желающий, достигший 18 лет. Опыт не требуется — достаточно заполнить анкету.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">Сколько стоит участие в моделинге? <span class="faq-icon">+</span></button>
                        <div class="faq-answer" style="display:none;">Участие в моделинге бесплатное. Никакая подписка или оплата за анкету не требуется.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">Какие услуги доступны моделям? <span class="faq-icon">+</span></button>
                        <div class="faq-answer" style="display:none;">Мастера публикуют приглашения на процедуры для отработки техник и создания портфолио. Условия каждой процедуры указываются в приглашении.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">Как мастера выбирают моделей? <span class="faq-icon">+</span></button>
                        <div class="faq-answer" style="display:none;">Мастера сами публикуют запросы на модели для отработки новых техник или для портфолио. Вы можете откликаться на подходящие предложения.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">Что входит в портфолио? <span class="faq-icon">+</span></button>
                        <div class="faq-answer" style="display:none;">В портфолио входят профессиональные фото ваших образов, созданные мастерами. Это помогает вам получать ещё больше предложений.</div>
                    </div>
                </div>
            </div>
        </section>

        {render_footer(user)}
    </main>

    <script>
        // Аккордеон для FAQ
        document.querySelectorAll('.faq-question').forEach(button => {{
            button.addEventListener('click', function() {{
                const answer = this.nextElementSibling;
                const icon = this.querySelector('.faq-icon');
                if (answer.style.display === 'none' || !answer.style.display) {{
                    answer.style.display = 'block';
                    icon.textContent = '−';
                }} else {{
                    answer.style.display = 'none';
                    icon.textContent = '+';
                }}
            }});
        }});
    </script>
</body>
</html>"""
    return html