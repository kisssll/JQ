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

    // Автоматическая активация вкладки при загрузке (по классу active уже проставлен)
    // Если нужно, можно добавить дополнительную инициализацию
    console.log('Business dashboard JS loaded');
})();