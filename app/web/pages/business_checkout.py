# app/web/pages/business_checkout.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_ARROW_LEFT,
    ICON_CIRCLE_CHECK,
)
from app.core.config import settings
import json

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
    {'<script src="https://widget.cloudpayments.ru/bundles/cloudpayments.js"></script>' if settings.CLOUDPAYMENTS_ENABLED else ''}
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
                                <div id="employee-count-wrap" style="display:none;">
                                    <label class="form-label">Количество сотрудников *</label>
                                    <input type="number" id="cx-employees" min="1" max="5" placeholder="От 1 до 5" class="form-input">
                                    <p class="form-hint">Тариф «Лайт» — 250 ₽ за сотрудника/мес, это и есть ваша итоговая сумма.</p>
                                </div>
                                <div id="renewal-mode-wrap"{'' if settings.CLOUDPAYMENTS_ENABLED else ' style="display:none;"'}>
                                    <label class="form-label">Продление подписки</label>
                                    <label class="checkbox-label">
                                        <input type="radio" name="renewal-mode" value="auto" class="checkbox-input" checked>
                                        <span class="checkbox-text">Автоматически каждый месяц (можно отменить в любой момент)</span>
                                    </label>
                                    <label class="checkbox-label">
                                        <input type="radio" name="renewal-mode" value="manual" class="checkbox-input">
                                        <span class="checkbox-text">Буду продлевать вручную</span>
                                    </label>
                                </div>
                                <label class="checkbox-label">
                                    <input type="checkbox" class="checkbox-input" id="terms-checkbox">
                                    <span class="checkbox-text">Я соглашаюсь с <a href="/terms" class="text-link">условиями использования</a> и <a href="/privacy" class="text-link">политикой конфиденциальности</a></span>
                                </label>
                            </div>
                            <button class="checkout-submit" id="submit-btn">
                                Подключить салон
                            </button>
                            <p class="checkout-note" id="submit-note">Первые 14 дней — бесплатно. {'Карта привязывается сразу, но списания не будет до конца пробного периода.' if settings.CLOUDPAYMENTS_ENABLED else 'Оплата картой скоро появится — пока тариф активируется сразу на пробный период.'}</p>
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
        const cloudPaymentsEnabled = {'true' if settings.CLOUDPAYMENTS_ENABLED else 'false'};

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

            document.getElementById('employee-count-wrap').style.display = planId === 'lite' ? '' : 'none';
            document.getElementById('renewal-mode-wrap').style.display =
                (cloudPaymentsEnabled && planId !== 'custom') ? '' : 'none';

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

        // === Оплата: готовим счёт на сервере, платёж всегда идёт из браузера
        // напрямую в CloudPayments (номер карты сервер не видит) ===
        function setNote(text) {{
            document.getElementById('submit-note').textContent = text;
        }}

        async function startPayment(salonId, plan, autoRenew, employeeCount, btn) {{
            try {{
                const res = await fetch('/api/v1/payments/business/init', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        salon_id: salonId, plan: plan, auto_renew: autoRenew,
                        employee_count: employeeCount,
                    }}),
                }});
                const data = await res.json().catch(() => ({{}}));
                if (!res.ok) {{
                    setNote(data.detail || 'Не удалось подготовить тариф.');
                    btn.disabled = false; btn.style.opacity = '1';
                    return;
                }}
                if (!data.requires_payment) {{
                    setNote('Пробный период запущен — открываем кабинет...');
                    window.location = data.redirect || '/business/dashboard';
                    return;
                }}
                if (typeof cp === 'undefined') {{
                    setNote('Виджет оплаты не загрузился. Обновите страницу и попробуйте ещё раз.');
                    btn.disabled = false; btn.style.opacity = '1';
                    return;
                }}
                setNote('Открываем форму оплаты…');
                const widget = new cp.CloudPayments();
                widget.charge({{
                    publicId: data.public_id,
                    description: data.description,
                    amount: data.amount,
                    currency: data.currency,
                    invoiceId: data.invoice_id,
                    accountId: data.account_id,
                    email: data.email,
                    skin: 'modern',
                    // Признак для CloudPayments: с этого платежа нужен Token карты
                    // для будущей подписки (оформляется сервером после успеха).
                    data: {{ cloudPayments: {{ recurrent: {{ interval: 'Month', period: 1 }} }} }},
                }}, function onSuccess() {{
                    window.location = '/business/dashboard?payment=pending';
                }}, function onFail(reason) {{
                    setNote('Оплата не прошла (' + (reason || 'попробуйте ещё раз') + '). Салон уже создан — можно повторить привязку карты.');
                    btn.disabled = false; btn.style.opacity = '1';
                    btn.textContent = 'Повторить привязку карты';
                }});
            }} catch (err) {{
                setNote('Ошибка сети при подготовке оплаты. Салон уже создан — попробуйте ещё раз.');
                btn.disabled = false; btn.style.opacity = '1';
            }}
        }}

        // Салон создаём только один раз за визит на страницу — при повторной
        // попытке (после неудачной привязки карты) просто пересоздаём счёт
        // на оплату для того же салона, а не подаём заявку ещё раз.
        let createdSalonId = null;

        document.getElementById('submit-btn').addEventListener('click', async function(e) {{
            e.preventDefault();
            const checkbox = document.getElementById('terms-checkbox');
            if (!checkbox.checked) {{
                alert('Пожалуйста, согласитесь с условиями использования и политикой конфиденциальности.');
                return;
            }}
            const salon = document.getElementById('cx-salon').value.trim();
            const phone = document.getElementById('cx-phone').value.trim();
            if (!salon || !phone) {{
                alert('Укажите название салона и телефон.');
                return;
            }}
            const plan = new URLSearchParams(window.location.search).get('plan') || 'business';

            let employeeCount = null;
            if (plan === 'lite') {{
                employeeCount = parseInt(document.getElementById('cx-employees').value, 10);
                if (!employeeCount || employeeCount < 1 || employeeCount > 5) {{
                    alert('Укажите количество сотрудников от 1 до 5 для тарифа «Лайт».');
                    return;
                }}
            }}

            const renewalInput = document.querySelector('input[name="renewal-mode"]:checked');
            const autoRenew = cloudPaymentsEnabled && (!renewalInput || renewalInput.value === 'auto');

            const btn = this;
            btn.disabled = true; btn.style.opacity = '0.7';

            if (createdSalonId) {{
                await startPayment(createdSalonId, plan, autoRenew, employeeCount, btn);
                return;
            }}

            const fd = new FormData();
            fd.append('salon_name', salon);
            fd.append('phone', phone);
            fd.append('contact_name', document.getElementById('cx-contact').value.trim());
            fd.append('email', document.getElementById('cx-email').value.trim());
            fd.append('plan', plan);
            fd.append('offer_accepted', '1');
            try {{
                const res = await fetch('/api/v1/business/apply', {{ method: 'POST', body: fd }});
                if (res.status === 401) {{
                    window.location = '/register?redirect=' + encodeURIComponent(window.location.pathname + window.location.search);
                    return;
                }}
                const data = await res.json().catch(() => ({{}}));
                if (!res.ok) {{
                    btn.disabled = false; btn.style.opacity = '1';
                    alert(data.detail || 'Не удалось отправить заявку.');
                    return;
                }}
                createdSalonId = data.salon_id;
                if (plan === 'custom' || !createdSalonId) {{
                    setNote('Заявка принята — открываем кабинет...');
                    window.location = data.redirect || '/business/dashboard';
                    return;
                }}
                await startPayment(createdSalonId, plan, autoRenew, employeeCount, btn);
            }} catch (err) {{
                btn.disabled = false; btn.style.opacity = '1';
                alert('Ошибка сети. Попробуйте ещё раз.');
            }}
        }});
    </script>
</body>
</html>"""
    return html