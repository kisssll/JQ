# app/web/pages/business_checkout.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_ARROW_LEFT,
    ICON_CIRCLE_CHECK,
)
import json
from app.web.pages.legal import LEGAL_VERSION

TARIFFS = {
    "lite": {
        "id": "lite",
        "name": "Лайт",
        "description": "До 5 сотрудников",
        "price": "250 ₽",
        "period": "за сотрудника/мес",
        "features": [
            "Оплата только за сотрудников",
            "Управление расписанием",
            "Онлайн-запись клиентов",
            "Базовая аналитика"
        ]
    },
    "business": {
        "id": "business",
        "name": "Бизнес",
        "description": "5–10 сотрудников",
        "price": "3 500 ₽",
        "period": "/мес",
        "features": [
            "Расширенная аналитика",
            "Приоритет в выдаче",
            "Акции и программы лояльности",
            "Персональная поддержка"
        ]
    },
    "corporate": {
        "id": "corporate",
        "name": "Корпоративный",
        "description": "10–20 сотрудников",
        "price": "6 990 ₽",
        "period": "/мес",
        "features": [
            "Мульти-филиалы",
            "VIP поддержка",
            "Индивидуальные интеграции",
            "Расширенная отчётность",
            "Выделенный менеджер"
        ]
    },
    "custom": {
        "id": "custom",
        "name": "Индивидуальный",
        "description": "Более 20 сотрудников",
        "price": "По запросу",
        "period": "",
        "features": [
            "Всё из тарифа «Корпоративный»",
            "Индивидуальные условия",
            "Персональный SLA"
        ]
    }
}

def render_business_checkout_page(plan: str = "business", user=None) -> str:
    active = TARIFFS.get(plan, TARIFFS["business"])
    tariffs_json = json.dumps(TARIFFS, ensure_ascii=False)
    
    features_html = ''.join(f'<li>{ICON_CIRCLE_CHECK}<span>{f}</span></li>' for f in active["features"])

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Подключение салона | Руми</title>
    <meta name="description" content="Подключите свой салон к платформе Руми">
    {get_base_styles()}
</head>
<body>
    {render_header("business")}
    {render_sidebar("business", user)}

    <main class="home-main">
        <section class="section-py section-gradient checkout-section">
            <div class="section-container">
                <div class="checkout-wrapper">
                    <a href="/business#pricing" class="checkout-back-link">
                        {ICON_ARROW_LEFT}
                        Назад к тарифам
                    </a>
                    <div class="checkout-header">
                        <h1 class="text-display checkout-title">Подключение салона</h1>
                        <p class="text-body checkout-subtitle">Заполните данные — мы свяжемся для настройки</p>
                    </div>

                    <!-- Селектор тарифов -->
                    <div class="tariff-selector">
                        <button class="tariff-btn" data-plan="lite">Лайт</button>
                        <button class="tariff-btn active" data-plan="business">Бизнес</button>
                        <button class="tariff-btn" data-plan="corporate">Корпоративный</button>
                        <button class="tariff-btn" data-plan="custom">Индивидуальный</button>
                    </div>

                    <div class="checkout-grid">
                        <div class="checkout-form">
                            <div class="form-fields">
                                <div>
                                    <label class="form-label">Контактное лицо</label>
                                    <input type="text" id="cx-contact" placeholder="Иван Петров" class="form-input">
                                </div>
                                <div>
                                    <label class="form-label">Название салона *</label>
                                    <input type="text" id="cx-salon" placeholder="Салон «Красота»" class="form-input" required>
                                </div>
                                <div>
                                    <label class="form-label">Телефон *</label>
                                    <input type="tel" id="cx-phone" value="+7" placeholder="+7 (999) 123-45-67" class="form-input phone-input" required>
                                </div>
                                <div>
                                    <label class="form-label">Email</label>
                                    <input type="email" id="cx-email" placeholder="salon@example.com" class="form-input">
                                </div>
                                <div>
                                    <label class="form-label">Количество сотрудников</label>
                                    <input type="text" id="cx-exp" placeholder="Например: 7" class="form-input">
                                </div>
                                <!-- Ссылки вели на 404, пока страниц документов не
                                     существовало. Плюс согласие на ПДн отделено от
                                     принятия условий: склеивать их нельзя. -->
                                <div class="consent-block">
                                    <label class="consent-check">
                                        <input type="checkbox" class="consent-check-input" id="terms-checkbox">
                                        <span class="consent-check-text">Я принимаю
                                            <a href="/terms" target="_blank" rel="noopener">Пользовательское соглашение</a>.</span>
                                    </label>
                                    <label class="consent-check" style="margin-top: 0.6rem;">
                                        <input type="checkbox" class="consent-check-input" id="consent-checkbox">
                                        <span class="consent-check-text">Я даю согласие на обработку персональных данных на условиях
                                            <a href="/consent" target="_blank" rel="noopener">Согласия</a>.</span>
                                    </label>
                                    <p class="consent-note">Как мы обрабатываем данные — в
                                        <a href="/privacy" target="_blank" rel="noopener">Политике обработки персональных данных</a>.</p>
                                </div>
                            </div>
                            <button class="checkout-submit" id="submit-btn">
                                Подключить салон
                            </button>
                            <p class="checkout-note" id="submit-note">Оплата будет доступна после интеграции с банком. Сейчас — заявка.</p>
                        </div>
                        <div class="checkout-summary" id="tariff-card">
                            <h3 class="tariff-card-name" id="tariff-name">{active["name"]}</h3>
                            <p class="tariff-card-desc" id="tariff-desc">{active["description"]}</p>
                            <div class="tariff-card-price" id="tariff-price">
                                <span class="price-amount">{active["price"]}</span>
                                <span class="price-period">{active["period"]}</span>
                            </div>
                            <ul class="tariff-card-features" id="tariff-features">
                                {features_html}
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </section>
        {render_footer(user)}
    </main>

    <script>
        // Данные тарифов из Python
        const tariffs = {tariffs_json};

        // Иконка галочки для вставки в список
        const checkIcon = `{ICON_CIRCLE_CHECK}`;

        function switchTariff(planId) {{
            document.querySelectorAll('.tariff-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.plan === planId);
            }});

            const tariff = tariffs[planId];
            if (!tariff) return;

            document.getElementById('tariff-name').textContent = tariff.name;
            document.getElementById('tariff-desc').textContent = tariff.description;
            const priceEl = document.getElementById('tariff-price');
            priceEl.querySelector('.price-amount').textContent = tariff.price;
            priceEl.querySelector('.price-period').textContent = tariff.period;

            const featuresList = document.getElementById('tariff-features');
            featuresList.innerHTML = tariff.features.map(f => 
                `<li>${{checkIcon}}<span>${{f}}</span></li>`
            ).join('');

            const url = new URL(window.location);
            url.searchParams.set('plan', planId);
            window.history.pushState({{ plan: planId }}, '', url);
        }}

        document.querySelectorAll('.tariff-btn').forEach(btn => {{
            btn.addEventListener('click', function(e) {{
                const plan = this.dataset.plan;
                switchTariff(plan);
            }});
        }});

        document.addEventListener('DOMContentLoaded', function() {{
            const params = new URLSearchParams(window.location.search);
            const plan = params.get('plan');
            if (plan && tariffs[plan]) {{
                switchTariff(plan);
            }}
        }});

        // === Обработка отправки формы ===
        document.getElementById('submit-btn').addEventListener('click', async function(e) {{
            e.preventDefault();
            // Две отметки проверяются раздельно: согласие на ПДн нельзя
            // считать данным вместе с принятием соглашения.
            if (!document.getElementById('terms-checkbox').checked) {{
                window.rumiToastError('Примите Пользовательское соглашение, чтобы продолжить.');
                return;
            }}
            if (!document.getElementById('consent-checkbox').checked) {{
                window.rumiToastError('Отметьте согласие на обработку персональных данных.');
                return;
            }}
            const salon = document.getElementById('cx-salon').value.trim();
            const phone = document.getElementById('cx-phone').value.trim();
            if (!salon || !phone) {{
                alert('Укажите название салона и телефон.');
                return;
            }}
            const btn = this;
            btn.disabled = true; btn.style.opacity = '0.7';
            const fd = new FormData();
            fd.append('salon_name', salon);
            fd.append('phone', phone);
            fd.append('contact_name', document.getElementById('cx-contact').value.trim());
            fd.append('email', document.getElementById('cx-email').value.trim());
            fd.append('experience', document.getElementById('cx-exp').value.trim());
            fd.append('plan', new URLSearchParams(window.location.search).get('plan') || 'business');
            fd.append('offer_accepted', '1');
            fd.append('pd_consent', '1');
            fd.append('consent_version', '{LEGAL_VERSION}');
            try {{
                const res = await fetch('/api/v1/business/apply', {{ method: 'POST', body: fd }});
                if (res.status === 401) {{
                    window.location = '/register?redirect=' + encodeURIComponent(window.location.pathname + window.location.search);
                    return;
                }}
                const data = await res.json().catch(() => ({{}}));
                if (res.ok) {{
                    btn.textContent = 'Заявка отправлена';
                    btn.style.cursor = 'default';
                    document.getElementById('submit-note').textContent = 'Заявка принята — открываем кабинет...';
                    window.location = data.redirect || '/business/dashboard';
                }} else {{
                    btn.disabled = false; btn.style.opacity = '1';
                    alert(data.detail || 'Не удалось отправить заявку.');
                }}
            }} catch (err) {{
                btn.disabled = false; btn.style.opacity = '1';
                alert('Ошибка сети. Попробуйте ещё раз.');
            }}
        }});
    </script>
</body>
</html>"""
    return html