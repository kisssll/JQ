# app/web/pages/business_checkout.py
from app.web.components.escaping import e
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

def render_business_checkout_page(plan: str = "business", user=None, for_master: bool = False,
                                  current_url: str = "") -> str:
    """Страница подключения. for_master — режим частного мастера (лендинг
    /dlya-masterov): только «Лайт» на одного человека, без слов «салон» и
    «сотрудники», мастером сразу заводится сам владелец (см. /business/apply)."""
    from urllib.parse import quote as _quote

    if for_master:
        plan = "lite"
    active = TARIFFS.get(plan, TARIFFS["business"])
    m = for_master
    page_title = "Подключение мастера" if m else "Подключение салона"
    # Частный мастер без входа не должен заполнять форму впустую: при отправке
    # его всё равно отправит на регистрацию, и введённое пропадёт.
    login_gate = ""
    if m and user is None:
        back = _quote(current_url or "/business/checkout?plan=lite&for=master", safe="")
        login_gate = (
            '<div class="checkout-form" style="max-width:32rem">'
            '<p class="text-body">Чтобы подключиться, создайте аккаунт на Руми — это пара минут. '
            'После регистрации вы вернётесь сюда.</p>'
            '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1rem">'
            f'<a class="checkout-submit" style="text-align:center;text-decoration:none" href="/register?redirect={back}">Зарегистрироваться</a>'
            f'<a class="btn-outline" href="/login?redirect={back}">У меня есть аккаунт</a>'
            '</div></div>'
        )
    spec_field = (
        '<div><label class="form-label" for="cx-specialization">Чем занимаетесь</label>'
        '<input type="text" id="cx-specialization" placeholder="Например, маникюр" class="form-input" maxlength="100"></div>'
    ) if m else ""
    name_value = e(getattr(user, "full_name", "") or "") if m else ""
    phone_value = e(getattr(user, "phone", "") or "+7") if m else "+7"

    tariffs_json = json.dumps(TARIFFS, ensure_ascii=False)
    
    features_html = ''.join(f'<li>{ICON_CIRCLE_CHECK}<span>{f}</span></li>' for f in active["features"])

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{page_title} | Руми</title>
    <meta name="description" content="{'Подключитесь к Руми как частный мастер' if m else 'Подключите свой салон к платформе Руми'}">
    {'<meta name="robots" content="noindex">' if m else ''}
    {get_base_styles()}
</head>
<body>
    {render_header("business")}
    {render_sidebar("business", user)}

    <main class="home-main">
        <section class="section-py section-gradient checkout-section">
            <div class="section-container">
                <div class="checkout-wrapper">
                    <a href="{'/dlya-masterov' if m else '/business#pricing'}" class="checkout-back-link">
                        {ICON_ARROW_LEFT}
                        {'Назад' if m else 'Назад к тарифам'}
                    </a>
                    <div class="checkout-header">
                        <h1 class="text-display checkout-title">{page_title}</h1>
                        <p class="text-body checkout-subtitle">{'Пара полей — и можно настраивать запись. Первые 14 дней бесплатно.' if m else 'Заполните данные — мы свяжемся для настройки'}</p>
                    </div>
                    {login_gate}

                    <!-- Селектор тарифов (у частного мастера тариф один) -->
                    <div class="tariff-selector"{' style="display:none"' if m else ''}>
                        <button class="tariff-btn" data-plan="lite">Лайт</button>
                        <button class="tariff-btn active" data-plan="business">Бизнес</button>
                        <button class="tariff-btn" data-plan="corporate">Корпоративный</button>
                        <button class="tariff-btn" data-plan="custom">Индивидуальный</button>
                    </div>

                    <div class="checkout-grid"{' style="display:none"' if login_gate else ''}>
                        <div class="checkout-form">
                            <div class="form-fields">
                                <div{' style="display:none"' if m else ''}>
                                    <label class="form-label">Контактное лицо</label>
                                    <input type="text" id="cx-contact" placeholder="Иван Петров" class="form-input">
                                </div>
                                <div>
                                    <label class="form-label">{'Как вас показывать клиентам *' if m else 'Название салона *'}</label>
                                    <input type="text" id="cx-salon" placeholder="{'Например, Анна Смирнова или студия «Ноготочки»' if m else 'Салон «Красота»'}" class="form-input" required value="{name_value}">
                                </div>
                                {spec_field}
                                <div>
                                    <label class="form-label">Телефон *</label>
                                    <input type="tel" id="cx-phone" value="{phone_value}" placeholder="+7 (999) 123-45-67" class="form-input phone-input" required>
                                </div>
                                <div>
                                    <label class="form-label">Email</label>
                                    <input type="email" id="cx-email" placeholder="{'you@example.com' if m else 'salon@example.com'}" class="form-input">
                                </div>
                                <div id="employee-count-wrap" style="display:none;">
                                    <label class="form-label">Количество сотрудников *</label>
                                    <input type="number" id="cx-employees" min="1" max="5" placeholder="От 1 до 5" class="form-input">
                                    <p class="form-hint">Тариф «Лайт» — 250 ₽ за сотрудника/мес, это и есть ваша итоговая сумма.</p>
                                </div>
                                <!-- Ссылки вели на 404, пока страниц документов не
                                     существовало. Плюс согласие на ПДн отделено от
                                     принятия условий: склеивать их нельзя. -->
                                <div class="consent-block">
                                    <label class="consent-check">
                                        <input type="checkbox" class="consent-check-input" id="terms-checkbox">
                                        <!-- Раньше здесь было «Пользовательское соглашение» (/terms),
                                             а сервер записывал в журнал принятие оферты для бизнеса —
                                             человек соглашался с одним, мы фиксировали другое. -->
                                        <span class="consent-check-text">Я принимаю
                                            <a href="/license" target="_blank" rel="noopener">Лицензионный договор-оферту</a>.</span>
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
                            <div class="form-group" style="margin-top: 1rem;">
                                <label class="form-label" for="receipt-email">Почта для чека</label>
                                <input type="email" id="receipt-email" class="form-input"
                                       placeholder="{'you@example.com' if m else 'buh@salon.ru'}" autocomplete="email"
                                       value="{e(getattr(user, 'email', '') or '')}">
                                <p class="consent-note">Необязательно — пришлём туда кассовый чек.
                                    Если не указать, чек придёт на телефон владельца.</p>
                            </div>
                            <button class="checkout-submit" id="submit-btn">
                                {'Подключиться — 14 дней бесплатно' if m else 'Подключить салон'}
                            </button>
                            <p class="checkout-note" id="submit-note">Первые 14 дней — бесплатно, карта не нужна. Дальше оплата — в кабинете, во вкладке «Тариф»: сами решаете, продолжать ли.</p>
                        </div>
                        <div class="checkout-summary" id="tariff-card">
                            <h3 class="tariff-card-name" id="tariff-name">{e(active["name"])}</h3>
                            <p class="tariff-card-desc" id="tariff-desc">{e(active["description"])}</p>
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
        const forMaster = {'true' if m else 'false'};
        const paymentsEnabled = {'true' if settings.TKASSA_ENABLED else 'false'};

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

            document.getElementById('employee-count-wrap').style.display = (planId === 'lite' && !forMaster) ? '' : 'none';
            // Переключатель автопродления убран (d3538e4 — всегда ручная оплата),
            // а обращение к нему осталось и роняло функцию на каждом клике.
            const renewalWrap = document.getElementById('renewal-mode-wrap');
            if (renewalWrap) renewalWrap.style.display = (paymentsEnabled && planId !== 'custom') ? '' : 'none';

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

        // === Оплата: сервер готовит платёж в Т-Кассе и отдаёт ссылку на
        // страницу оплаты — просто перенаправляем туда браузер, никакого
        // виджета не нужно. Факт оплаты подтверждает вебхук на сервере. ===
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
                        receipt_email: (document.getElementById('receipt-email')
                            || {{}}).value || null,
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
                setNote('Переходим к оплате…');
                window.location = data.payment_url;
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
            // Две отметки проверяются раздельно: согласие на ПДн нельзя
            // считать данным вместе с принятием соглашения.
            if (!document.getElementById('terms-checkbox').checked) {{
                window.rumiToastError('Примите лицензионный договор-оферту, чтобы продолжить.');
                return;
            }}
            if (!document.getElementById('consent-checkbox').checked) {{
                window.rumiToastError('Отметьте согласие на обработку персональных данных.');
                return;
            }}
            const salon = document.getElementById('cx-salon').value.trim();
            const phone = document.getElementById('cx-phone').value.trim();
            if (!salon || !phone) {{
                alert(forMaster ? 'Укажите, как вас показывать клиентам, и телефон.' : 'Укажите название салона и телефон.');
                return;
            }}
            const plan = forMaster ? 'lite' : (new URLSearchParams(window.location.search).get('plan') || 'business');

            let employeeCount = null;
            if (forMaster) {{
                employeeCount = 1;   // частный мастер — это один человек
            }} else if (plan === 'lite') {{
                employeeCount = parseInt(document.getElementById('cx-employees').value, 10);
                if (!employeeCount || employeeCount < 1 || employeeCount > 5) {{
                    alert('Укажите количество сотрудников от 1 до 5 для тарифа «Лайт».');
                    return;
                }}
            }}

            const autoRenew = false;

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
            fd.append('pd_consent', '1');
            fd.append('consent_version', '{LEGAL_VERSION}');
            if (forMaster) {{
                fd.append('for_master', '1');
                fd.append('specialization', (document.getElementById('cx-specialization') || {{}}).value || '');
            }}
            // Метки рекламы из адреса — сервер сохранит их к подключению
            // (учёт без cookie, см. services/ad_attribution.py).
            new URLSearchParams(window.location.search).forEach((value, key) => {{
                if (/^utm_(source|medium|campaign|content|term)$/.test(key) || key === 'yclid' || key === 'landing') {{
                    fd.append(key, value);
                }}
            }});
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