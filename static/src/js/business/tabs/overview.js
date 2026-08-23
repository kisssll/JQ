import { esc } from '../../escape-html.js';
// static/src/js/business/tabs/overview.js

(function() {
    const weekOperations = window.weekOperations || [];
    const days = window.days || [];
    let currentOpenDay = null;
    let activeColumn = null;

    function closeDayDetails() {
        const accordion = document.getElementById('dayAccordion');
        if (accordion) accordion.style.display = 'none';
        currentOpenDay = null;
        // Снимаем выделение со столбца
        setActiveColumn(null);
    }

    function setActiveColumn(col) {
        // Сбрасываем предыдущий активный
        if (activeColumn) {
            const prevFill = activeColumn.querySelector('.chart-fill');
            if (prevFill) {
                prevFill.style.background = 'linear-gradient(to top, #34d399, #34d399cc)';
            }
            activeColumn.classList.remove('active');
        }
        activeColumn = col;
        if (col) {
            const fill = col.querySelector('.chart-fill');
            if (fill) {
                fill.style.background = 'linear-gradient(to top, #059669, #059669cc)';
            }
            col.classList.add('active');
        }
    }

    function toggleDayDetails(index, dayName, revenue, prevRevenue) {
        const accordion = document.getElementById('dayAccordion');
        const title = document.getElementById('accordionDayTitle');
        const summary = document.getElementById('accordionDaySummary');
        const container = document.getElementById('accordionDayOperations');
        
        if (currentOpenDay === index && accordion.style.display !== 'none') {
            closeDayDetails();
            return;
        }
        
        const ops = weekOperations[index] || [];
        title.textContent = `Операции за ${dayName}`;
        const totalOps = ops.length;
        const paidCount = ops.filter(o => o.status === 'completed').length;
        summary.textContent = `${totalOps} операций • ${revenue.toLocaleString()} ₽ • Оплачено: ${paidCount}/${totalOps}`;
        
        container.innerHTML = '';
        if (totalOps === 0) {
            container.innerHTML = '<p class="text-muted">Нет операций за этот день</p>';
        } else {
            ops.forEach(op => {
                const time = new Date(op.start_time).toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
                const price = (op.final_price || op.service.price).toLocaleString();
                const statusLabel = op.status === 'completed' ? '✓' : '○';
                const statusClass = op.status === 'completed' ? 'status-paid' : 'status-waiting';
                const initials = op.client.full_name ? op.client.full_name.split(' ').map(n => n[0]).join('') : 'К';
                const method = op.payment_method || 'Карта';

                const item = document.createElement('div');
                item.className = 'booking-item';
                item.innerHTML = `
                    <div class="avatar">${esc(initials)}</div>
                    <div class="info">
                        <div class="name">${esc(op.client.full_name || op.client.phone)}</div>
                        <div class="desc">
                            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                            ${time} • ${op.service.name}
                        </div>
                    </div>
                    <div class="price">${price} ₽</div>
                    <div style="display:flex;align-items:center;gap:0.5rem;flex-shrink:0">
                        <span style="font-size:0.7rem;color:var(--color-muted)">${method}</span>
                        <span class="status ${statusClass}">${statusLabel}</span>
                    </div>
                `;
                container.appendChild(item);
            });
        }
        
        accordion.style.display = 'block';
        accordion.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        currentOpenDay = index;

        // Выделяем столбец
        const columns = document.querySelectorAll('#overviewChartBar .chart-column');
        if (columns[index]) {
            setActiveColumn(columns[index]);
        }
    }

    // Назначаем обработчики кликов на столбцы
    document.addEventListener('DOMContentLoaded', function() {
        const columns = document.querySelectorAll('#overviewChartBar .chart-column');
        columns.forEach((col, index) => {
            col.addEventListener('click', function(e) {
                e.stopPropagation();
                const dayName = days[index] || `День ${index+1}`;
                const revenue = weekOperations[index]?.reduce((sum, op) => sum + (op.final_price || op.service.price), 0) || 0;
                const prevRevenue = 0; // можно не использовать
                toggleDayDetails(index, dayName, revenue, prevRevenue);
            });
        });
    });

    // Глобальная функция для вызова из HTML (оставлена для обратной совместимости)
    window.toggleDayDetails = toggleDayDetails;
    window.closeDayDetails = closeDayDetails;

    // Обработчик крестика
    document.addEventListener('click', function(e) {
        const closeBtn = e.target.closest('.accordion-close');
        if (closeBtn) {
            e.preventDefault();
            closeDayDetails();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeDayDetails();
        }
    });

    // Закрытие при клике вне аккордеона и вне столбцов
    document.addEventListener('click', function(e) {
        const accordion = document.getElementById('dayAccordion');
        if (accordion && accordion.style.display !== 'none') {
            const target = e.target;
            if (!accordion.contains(target) && !target.closest('#overviewChartBar .chart-column')) {
                closeDayDetails();
            }
        }
    });
})();