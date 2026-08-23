// static/src/js/business/tabs/analytics.js
// Вкладка «Аналитика»: переключатель гранулярности (день/неделя/месяц/год) +
// свой диапазон дат, данные — через JSON API /api/v1/business/my-salon/analytics.

(function() {
    const root = document.getElementById('tab-analytics');
    if (!root) return;

    const salonId = root.dataset.salonId;
    let currentGranularity = 'day';
    let currentOpenDate = null;
    let activeColumn = null;

    function formatMoney(n) {
        return (n || 0).toLocaleString('ru-RU') + ' ₽';
    }

    // ISO (Y-m-d) → ДД.ММ.ГГГГ для отображения пользователю.
    function formatRuDate(iso) {
        const [y, m, d] = (iso || '').split('-');
        return (y && m && d) ? `${d}.${m}.${y}` : (iso || '');
    }

    function daysInMonth(year, month1to12) {
        return new Date(Date.UTC(year, month1to12, 0)).getUTCDate();
    }

    // Конец периода от даты начала: день — тот же день, неделя — +6 дней,
    // месяц/год — ровно календарный месяц/год минус 1 день (с клампом на
    // короткие месяцы, чтобы 31.01 + месяц не улетало на март).
    function addPeriodEnd(fromISO, granularity) {
        const [y, m, day] = fromISO.split('-').map(Number);
        if (granularity === 'day') return fromISO;
        if (granularity === 'week') {
            const d = new Date(Date.UTC(y, m - 1, day + 6));
            return d.toISOString().slice(0, 10);
        }
        const monthsToAdd = granularity === 'year' ? 12 : 1;
        const total = y * 12 + (m - 1) + monthsToAdd;
        const ny = Math.floor(total / 12);
        const nm = (total % 12) + 1;
        const clampedDay = Math.min(day, daysInMonth(ny, nm));
        const d = new Date(Date.UTC(ny, nm - 1, clampedDay - 1));
        return d.toISOString().slice(0, 10);
    }

    function formatLabel(periodStart, granularity) {
        const d = new Date(periodStart + 'T00:00:00');
        if (granularity === 'day') return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' });
        if (granularity === 'week') return 'с ' + d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' });
        if (granularity === 'month') return d.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' });
        return String(d.getFullYear());
    }

    async function loadAnalytics(granularity, dateFrom, dateTo) {
        const params = new URLSearchParams({ salon_id: salonId, granularity });
        if (dateFrom) params.set('date_from', dateFrom);
        if (dateTo) params.set('date_to', dateTo);
        const res = await fetch(`/api/v1/business/my-salon/analytics?${params}`);
        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            throw new Error(d.detail || 'Не удалось загрузить аналитику');
        }
        return res.json();
    }

    function renderKpi(data) {
        const kpi = document.getElementById('analyticsKpi');
        const s = data.summary;
        kpi.innerHTML = `
            <div class="kpi-card">
                <div class="kpi-label">Выручка за период</div>
                <div class="kpi-value">${formatMoney(s.total_revenue)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Средний чек</div>
                <div class="kpi-value">${formatMoney(s.avg_check)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Всего записей</div>
                <div class="kpi-value">${s.total_bookings}</div>
                <div class="kpi-trend" style="color:var(--color-muted)">c ${formatRuDate(data.date_from)} по ${formatRuDate(data.date_to)}</div>
            </div>
        `;
    }

    function renderChart(data) {
        const chart = document.getElementById('analyticsChart');
        chart.innerHTML = '';
        chart.classList.toggle('chart-bar--dense', data.points.length > 14);

        const maxRevenue = Math.max(...data.points.map(p => p.revenue), 1);
        const MAX_BAR_HEIGHT = 80;
        const MIN_BAR_HEIGHT = 8;

        data.points.forEach(p => {
            const height = Math.max(MIN_BAR_HEIGHT, Math.round((p.revenue / maxRevenue) * MAX_BAR_HEIGHT));
            // Все столбцы светло-зелёные, выделение будет через активный класс
            const barColor = '#34d399';

            const col = document.createElement('div');
            col.className = 'chart-column';
            col.dataset.periodStart = p.period_start;
            col.dataset.revenue = p.revenue;
            col.title = `${formatLabel(p.period_start, data.granularity)}: ${formatMoney(p.revenue)}`;
            col.innerHTML = `
                <div class="chart-value">${formatMoney(p.revenue)}</div>
                <div class="chart-fill" style="height:${height}px;background:linear-gradient(to top, ${barColor}, ${barColor}cc)"></div>
                <span class="chart-label">${formatLabel(p.period_start, data.granularity)}</span>
            `;
            if (data.granularity === 'day') {
                col.style.cursor = 'pointer';
                col.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (activeColumn === this) {
                        closeDayDetails();
                        return;
                    }
                    showDayDetails(p.period_start, p.revenue);
                    setActiveColumn(this);
                });
            }
            chart.appendChild(col);
        });

        activeColumn = null;

        const hint = document.getElementById('analyticsChartHint');
        if (hint) {
            hint.style.display = data.granularity === 'day' ? '' : 'none';
        }
    }

    function setActiveColumn(col) {
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

    function renderTopServices(list) {
        const tbody = document.getElementById('analyticsTopServices');
        if (!list || !list.length) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:2rem;color:var(--color-muted)">Нет данных за период</td></tr>';
            return;
        }
        tbody.innerHTML = list.map(s => `
            <tr>
                <td>${s.name}</td>
                <td>${s.bookings}</td>
                <td><strong>${formatMoney(s.revenue)}</strong></td>
            </tr>
        `).join('');
    }

    function setDateInput(id, isoValue) {
        const el = document.getElementById(id);
        // custom-forms.js оборачивает эти инпуты в flatpickr с altInput —
        // видимое поле не синхронизируется само при прямом el.value = ...,
        // поэтому даты нужно проставлять через API самого инстанса.
        if (el._flatpickr) {
            el._flatpickr.setDate(isoValue, false);
        } else {
            el.value = isoValue;
        }
    }

    function applyData(data) {
        // currentGranularity — это активная ВКЛАДКА (день/неделя/месяц/год),
        // а не бакет конкретного ответа: при «Показать» с якорной датой бэкенд
        // может вернуть более мелкий бакет (см. chartGranularityForPeriod), и
        // затирать им currentGranularity нельзя — иначе собьётся авто-подстановка
        // конца периода при следующем выборе даты начала.
        setDateInput('analyticsDateFrom', data.date_from);
        setDateInput('analyticsDateTo', data.date_to);
        renderKpi(data);
        renderChart(data);
        renderTopServices(data.top_services);
        closeDayDetails();
    }

    // При выборе «даты с» конец периода подставляется автоматически по
    // активной вкладке гранулярности (день→тот же день, неделя→+6 дней и
    // т.д.), но остаётся обычным редактируемым полем — пользователь может
    // сдвинуть его вручную на любую другую дату перед «Показать».
    function syncDateToFromAnchor() {
        const fromEl = document.getElementById('analyticsDateFrom');
        if (!fromEl || !fromEl.value) return;
        setDateInput('analyticsDateTo', addPeriodEnd(fromEl.value, currentGranularity));
    }

    // Неделя/месяц, применённые к конкретному якорному диапазону (а не как
    // общий обзорный тренд по клику на вкладку), разбиваем на бары уровнем
    // мельче — иначе 7–30-дневный диапазон даёт бакет того же уровня в 1-2
    // малополезных столбца (что и показывал график на скриншоте пользователя).
    function chartGranularityForPeriod(uiGranularity) {
        if (uiGranularity === 'week' || uiGranularity === 'month') return 'day';
        if (uiGranularity === 'year') return 'month';
        return uiGranularity;
    }

    const dateFromEl = document.getElementById('analyticsDateFrom');
    if (dateFromEl && dateFromEl._flatpickr) {
        dateFromEl._flatpickr.config.onChange.push(syncDateToFromAnchor);
    }

    if (window.analyticsInitial) {
        applyData(window.analyticsInitial);
    }

    document.querySelectorAll('.analytics-gran-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            document.querySelectorAll('.analytics-gran-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentGranularity = this.dataset.granularity;
            this.disabled = true;
            try {
                const data = await loadAnalytics(currentGranularity);
                applyData(data);
            } catch (e) {
                alert(e.message || 'Ошибка сети');
            }
            this.disabled = false;
        });
    });

    const applyBtn = document.getElementById('analyticsApplyRange');
    if (applyBtn) {
        applyBtn.addEventListener('click', async function() {
            const dateFrom = document.getElementById('analyticsDateFrom').value;
            const dateTo = document.getElementById('analyticsDateTo').value;
            if (!dateFrom || !dateTo) return;
            this.disabled = true;
            try {
                const data = await loadAnalytics(chartGranularityForPeriod(currentGranularity), dateFrom, dateTo);
                applyData(data);
            } catch (e) {
                alert(e.message || 'Ошибка сети');
            }
            this.disabled = false;
        });
    }

    const allTimeBtn = document.getElementById('analyticsAllTime');
    if (allTimeBtn) {
        allTimeBtn.addEventListener('click', async function() {
            const sinceDate = window.analyticsInitial && window.analyticsInitial.salon_created_at;
            if (!sinceDate) return;
            const today = new Date().toISOString().slice(0, 10);
            // День/неделя над многолетним диапазоном дали бы тысячи точек на
            // графике (см. MAX_POINTS на бэкенде) — для «всего периода»
            // переключаемся на более крупный бакет, если сейчас выбран мелкий.
            let granularity = currentGranularity;
            if (granularity === 'day' || granularity === 'week') granularity = 'month';
            this.disabled = true;
            try {
                const data = await loadAnalytics(granularity, sinceDate, today);
                currentGranularity = granularity;
                document.querySelectorAll('.analytics-gran-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.granularity === granularity);
                });
                applyData(data);
            } catch (e) {
                alert(e.message || 'Ошибка сети');
            }
            this.disabled = false;
        });
    }

    function closeDayDetails() {
        const accordion = document.getElementById('dayAccordion');
        if (accordion) accordion.style.display = 'none';
        currentOpenDate = null;
        setActiveColumn(null);
    }

    async function showDayDetails(dateStr, revenue) {
        const accordion = document.getElementById('dayAccordion');
        const title = document.getElementById('accordionDayTitle');
        const summary = document.getElementById('accordionDaySummary');
        const container = document.getElementById('accordionDayOperations');

        if (currentOpenDate === dateStr && accordion.style.display !== 'none') {
            closeDayDetails();
            return;
        }

        currentOpenDate = dateStr;
        title.textContent = 'Операции за ' + new Date(dateStr + 'T00:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
        summary.textContent = 'Загрузка…';
        container.innerHTML = '';
        accordion.style.display = 'block';
        accordion.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        try {
            const res = await fetch(`/api/v1/business/my-salon/analytics/day?salon_id=${salonId}&date=${dateStr}`);
            if (!res.ok) throw new Error();
            const data = await res.json();
            const ops = data.operations || [];
            const paidCount = ops.filter(o => o.status === 'completed').length;
            summary.textContent = `${ops.length} операций • ${formatMoney(revenue)} • Оплачено: ${paidCount}/${ops.length}`;

            if (!ops.length) {
                container.innerHTML = '<p class="text-muted">Нет операций за этот день</p>';
                return;
            }
            container.innerHTML = ops.map(op => {
                const time = new Date(op.start_time).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
                const price = (op.final_price || op.service.price).toLocaleString('ru-RU');
                const statusLabel = op.status === 'completed' ? '✓' : '○';
                const statusClass = op.status === 'completed' ? 'status-paid' : 'status-waiting';
                const initials = op.client.full_name ? op.client.full_name.split(' ').map(n => n[0]).join('') : 'К';
                return `
                    <div class="booking-item">
                        <div class="avatar">${initials}</div>
                        <div class="info">
                            <div class="name">${op.client.full_name || op.client.phone}</div>
                            <div class="desc">${time} • ${op.service.name}</div>
                        </div>
                        <div class="price">${price} ₽</div>
                        <span class="status ${statusClass}">${statusLabel}</span>
                    </div>
                `;
            }).join('');
        } catch (e) {
            summary.textContent = '';
            container.innerHTML = '<p class="text-muted">Не удалось загрузить операции</p>';
        }
    }

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

    document.addEventListener('click', function(e) {
        const accordion = document.getElementById('dayAccordion');
        if (accordion && accordion.style.display !== 'none') {
            const target = e.target;
            if (!accordion.contains(target) && !target.closest('.chart-column')) {
                closeDayDetails();
            }
        }
    });
})();