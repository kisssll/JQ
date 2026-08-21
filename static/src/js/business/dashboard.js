// static/src/js/business/dashboard.js

(function() {
    // Переключение вкладок
    window.switchTab = function(tabName) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        const target = document.getElementById('tab-' + tabName);
        if (target) target.classList.add('active');
        // Найти кнопку с соответствующим onclick и добавить active
        document.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(tabName)) {
                btn.classList.add('active');
            }
        });
    };

    // Показ деталей дня (для графика)
    window.showDayDetails = function(index, dayName, revenue, prevRevenue) {
        const diff = revenue - prevRevenue;
        const trend = diff > 0 ? '▲' : diff < 0 ? '▼' : '—';
        const color = diff > 0 ? '#22c55e' : diff < 0 ? '#ef4444' : 'gray';
        alert(`${dayName}\nВыручка: ${revenue.toLocaleString()} ₽\nПрошлая неделя: ${prevRevenue.toLocaleString()} ₽\n${trend} ${Math.abs(diff).toLocaleString()} ₽`);
    };

    // Публикация салона после модерации: кнопка в шапке (баннер «прошёл
    // модерацию»). Разовый шлюз — на успехе перезагружаем панель, чтобы баннер
    // исчез и салон появился в каталоге. См. POST /api/v1/business/my-salon/publish.
    function bindPublishBtn() {
        const btn = document.getElementById('salonPublishBtn');
        if (!btn) return;
        btn.addEventListener('click', async function() {
            if (!confirm('Опубликовать салон? Он появится в каталоге и поиске, откроется запись клиентов.')) return;
            this.disabled = true;
            try {
                const res = await fetch(`/api/v1/business/my-salon/publish?salon_id=${this.dataset.salonId}`, { method: 'POST' });
                if (res.ok) {
                    window.location.reload();
                } else {
                    const d = await res.json().catch(() => ({}));
                    alert(d.detail || 'Не удалось опубликовать салон');
                    this.disabled = false;
                }
            } catch (e) {
                alert('Ошибка сети, попробуйте ещё раз');
                this.disabled = false;
            }
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindPublishBtn);
    } else {
        bindPublishBtn();
    }

    // Предупреждение «салон не виден без оплаты» (см. publish_gate_modal_html
    // в dashboard.py) — показываем один раз за сессию вкладки браузера, чтобы
    // не всплывало при каждом переходе между вкладками панели (тут навигация —
    // полная перезагрузка страницы, см. tab_buttons в dashboard.py).
    function bindPublishGateModal() {
        const modal = document.getElementById('publishGateModal');
        if (!modal) return;
        const salonId = modal.dataset.salonId;
        const key = 'publishGateModalShown:' + salonId;
        if (!sessionStorage.getItem(key)) {
            modal.classList.add('active');
            sessionStorage.setItem(key, '1');
        }
        const close = () => modal.classList.remove('active');
        document.getElementById('publishGateModalClose').addEventListener('click', close);
        modal.addEventListener('click', function(e) {
            if (e.target === modal) close();
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindPublishGateModal);
    } else {
        bindPublishGateModal();
    }

    // Вкладка «Тариф»: выбор тарифа (если ещё не выбран), разовая ручная
    // оплата и отмена автопродления. Оплата — тот же приём, что на
    // /business/checkout: сервер готовит платёж в Т-Кассе и отдаёт ссылку
    // на страницу оплаты — просто перенаправляем туда, без виджета. Факт
    // оплаты подтверждает вебхук на сервере уже после возврата. Тариф на
    // тарифе не фиксируется — сервер сам пересчитывает его по числу мастеров
    // при каждой следующей оплате (см. resolve_plan_for_employee_count).
    function bindBillingButtons() {
        const note = document.getElementById('billing-note');
        const setNote = (text) => { if (note) note.textContent = text; };

        const selectPlanBtn = document.getElementById('billingSelectPlanBtn');
        if (selectPlanBtn) {
            selectPlanBtn.addEventListener('click', async function() {
                const salonId = parseInt(this.dataset.salonId, 10);
                const activeMasters = parseInt(this.dataset.activeMasters, 10) || null;
                const plan = document.querySelector('input[name="billing-plan"]:checked').value;
                const renewalInput = document.querySelector('input[name="billing-renewal-mode"]:checked');
                const autoRenew = !!renewalInput && renewalInput.value === 'auto';
                this.disabled = true;
                setNote('Готовим тариф…');
                try {
                    const res = await fetch('/api/v1/payments/business/init', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            salon_id: salonId, plan: plan, auto_renew: autoRenew,
                            employee_count: activeMasters,
                        }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) {
                        setNote(data.detail || 'Не удалось подключить тариф.');
                        this.disabled = false;
                        return;
                    }
                    if (!data.requires_payment) {
                        setNote('Пробный период запущен — обновляем страницу…');
                        window.location.reload();
                        return;
                    }
                    setNote('Переходим к оплате…');
                    window.location = data.payment_url;
                } catch (e) {
                    setNote('Ошибка сети, попробуйте ещё раз.');
                    this.disabled = false;
                }
            });
        }

        const payBtn = document.getElementById('billingPayBtn');
        if (payBtn) {
            payBtn.addEventListener('click', async function() {
                const salonId = this.dataset.salonId;
                this.disabled = true;
                setNote('Готовим оплату…');
                try {
                    const res = await fetch('/api/v1/payments/business/manual-charge', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ salon_id: parseInt(salonId, 10) }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) {
                        setNote(data.detail || 'Не удалось подготовить оплату.');
                        this.disabled = false;
                        return;
                    }
                    setNote('Переходим к оплате…');
                    window.location = data.payment_url;
                } catch (e) {
                    setNote('Ошибка сети, попробуйте ещё раз.');
                    this.disabled = false;
                }
            });
        }

        const cancelBtn = document.getElementById('billingCancelBtn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', async function() {
                if (!confirm('Отключить автопродление? Доступ по уже оплаченному периоду сохранится, дальше подписка не продлится сама.')) return;
                this.disabled = true;
                setNote('Отключаем автопродление…');
                try {
                    const res = await fetch('/api/v1/payments/business/cancel-auto-renew', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ salon_id: parseInt(this.dataset.salonId, 10) }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.ok) {
                        window.location.reload();
                    } else {
                        setNote(data.detail || 'Не удалось отключить автопродление.');
                        this.disabled = false;
                    }
                } catch (e) {
                    setNote('Ошибка сети, попробуйте ещё раз.');
                    this.disabled = false;
                }
            });
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindBillingButtons);
    } else {
        bindBillingButtons();
    }

    // Автоматическая активация вкладки при загрузке (по классу active уже проставлен)
    // Если нужно, можно добавить дополнительную инициализацию
    console.log('Business dashboard JS loaded');
})();