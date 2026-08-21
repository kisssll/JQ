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

    // Вкладка «Тариф»: разовая ручная оплата и отмена автопродления.
    // Оплата — тот же приём, что на /business/checkout: сервер готовит счёт
    // (/api/v1/payments/business/manual-charge), сам платёж уходит из
    // браузера прямо в CloudPayments виджетом, факт оплаты подтверждает
    // вебхук на сервере — здесь просто ждём и перезагружаем панель.
    function bindBillingButtons() {
        const note = document.getElementById('billing-note');
        const setNote = (text) => { if (note) note.textContent = text; };

        const payBtn = document.getElementById('billingPayBtn');
        if (payBtn) {
            payBtn.addEventListener('click', async function() {
                const salonId = this.dataset.salonId;
                const employeeInput = document.getElementById('billing-employee-count');
                const employeeCount = employeeInput ? parseInt(employeeInput.value, 10) : null;
                if (employeeInput && (!employeeCount || employeeCount < 1)) {
                    setNote('Укажите количество сотрудников.');
                    return;
                }
                this.disabled = true;
                setNote('Готовим оплату…');
                try {
                    const res = await fetch('/api/v1/payments/business/manual-charge', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ salon_id: parseInt(salonId, 10), employee_count: employeeCount }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) {
                        setNote(data.detail || 'Не удалось подготовить оплату.');
                        this.disabled = false;
                        return;
                    }
                    if (typeof cp === 'undefined') {
                        setNote('Виджет оплаты не загрузился. Обновите страницу и попробуйте ещё раз.');
                        this.disabled = false;
                        return;
                    }
                    setNote('Открываем форму оплаты…');
                    const widget = new cp.CloudPayments();
                    const btn = this;
                    widget.charge({
                        publicId: data.public_id,
                        description: data.description,
                        amount: data.amount,
                        currency: data.currency,
                        invoiceId: data.invoice_id,
                        accountId: data.account_id,
                        email: data.email,
                        skin: 'modern',
                    }, function onSuccess() {
                        setNote('Оплата прошла — обновляем страницу…');
                        window.location.reload();
                    }, function onFail(reason) {
                        setNote('Оплата не прошла (' + (reason || 'попробуйте ещё раз') + ').');
                        btn.disabled = false;
                    });
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