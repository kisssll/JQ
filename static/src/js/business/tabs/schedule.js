// static/src/js/business/tabs/schedule.js
(function() {
    'use strict';

    // ===== Десктопные функции =====
    window.showMonth = function(monthKey) {
        document.querySelectorAll('.schedule-month-panel').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.schedule-month-btn').forEach(el => el.classList.remove('active'));
        document.getElementById('month-' + monthKey).classList.add('active');
        const btn = document.querySelector(`.schedule-month-btn[data-month="${monthKey}"]`);
        if (btn) btn.classList.add('active');
    };

    window.showWeek = function(monthKey, weekId) {
        document.querySelectorAll(`.schedule-week-panel[data-month="${monthKey}"]`).forEach(el => el.classList.remove('active'));
        document.querySelectorAll(`.schedule-week-btn[data-month="${monthKey}"]`).forEach(el => el.classList.remove('active'));
        document.getElementById('week-' + weekId).classList.add('active');
        const btn = document.querySelector(`.schedule-week-btn[data-month="${monthKey}"][data-week="${weekId}"]`);
        if (btn) btn.classList.add('active');
    };

    // ===== Универсальные функции для отметок =====
    window.markBooking = function(bookingId, action) {
        const label = action === 'complete' ? 'выполненной' : 'неявкой';
        if (!confirm(`Отметить запись ${label}?`)) return;
        fetch(`/api/v1/bookings/${bookingId}/${action}`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else r.json().then(d => alert(d.detail || 'Ошибка'));
            });
    };

    // Подтверждение/отклонение записи салоном (PENDING → CONFIRMED / CANCELLED)
    window.acceptBooking = function(bookingId) {
        if (!confirm('Подтвердить запись?')) return;
        fetch(`/api/v1/bookings/${bookingId}/accept`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else r.json().then(d => alert(d.detail || 'Не удалось подтвердить'));
            });
    };

    window.rejectBooking = function(bookingId) {
        if (!confirm('Отклонить запись? Клиент получит уведомление.')) return;
        fetch(`/api/v1/bookings/${bookingId}/reject`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else r.json().then(d => alert(d.detail || 'Не удалось отклонить'));
            });
    };

    // Мастер отмечает, что видел плановую запись
    window.markSeen = function(bookingId, btn) {
        fetch(`/api/v1/bookings/${bookingId}/mark-seen`, { method: 'POST' })
            .then(r => {
                if (r.ok) {
                    btn.outerHTML = '<span class="seen-indicator" title="Вы отметили, что видели эту запись">👁 Видели</span>';
                } else {
                    r.json().then(d => alert(d.detail || 'Не удалось отметить'));
                }
            });
    };

    // ===== Модалка завершения =====
    let completeModalBookingId = null;

    window.openCompleteModal = async function(bookingId, clientId) {
        completeModalBookingId = bookingId;
        const body = document.getElementById('completeModalBody');
        body.innerHTML = 'Загрузка…';
        document.getElementById('completeBookingModal').classList.add('active');

        let status;
        try {
            const res = await fetch(`/api/v1/loyalty/salon/${window.salonId}/client/${clientId}`);
            status = await res.json();
        } catch (e) {
            body.innerHTML = 'Не удалось загрузить скидки клиента. Можно завершить без скидки.';
            status = { offers: [], bonus_points: 0 };
        }

        let html = '<label style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem;cursor:pointer">'
            + '<input type="radio" name="discountChoice" value="none" checked> Без скидки</label>';

        if (status.is_regular_client && status.regular_client_discount_percent > 0) {
            html += `<label style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem;cursor:pointer">
                <input type="radio" name="discountChoice" value="regular_client"> Постоянный клиент (-${status.regular_client_discount_percent}%)</label>`;
        }
        if (status.personal_discount_percent) {
            html += `<label style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem;cursor:pointer">
                <input type="radio" name="discountChoice" value="personal"> Персональная скидка (-${status.personal_discount_percent}%)</label>`;
        }
        (status.offers || []).forEach(o => {
            if (!o.promo_code) return;
            html += `<label style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem;cursor:pointer">
                <input type="radio" name="discountChoice" value="promo" data-code="${o.promo_code}"> ${o.title} (-${o.discount_percent}%, промокод ${o.promo_code})</label>`;
        });

        html += `<div style="margin-top:0.75rem">
            <label style="display:block;font-weight:500;margin-bottom:0.25rem">Списать баллов (доступно: ${status.bonus_points || 0})</label>
            <input type="number" id="completeBonusPoints" min="0" max="${status.bonus_points || 0}" value="0" style="width:100%;padding:0.5rem;border:1px solid var(--color-border);border-radius:0.5rem">
        </div>`;

        body.innerHTML = html;
    };

    window.submitCompleteWithDiscount = async function() {
        const selected = document.querySelector('input[name="discountChoice"]:checked');
        const discount_choice = selected ? selected.value : 'none';
        const promo_code = selected && selected.dataset.code ? selected.dataset.code : null;
        const bonusEl = document.getElementById('completeBonusPoints');
        const bonus_points_redeemed = bonusEl ? (parseInt(bonusEl.value) || 0) : 0;

        const res = await fetch(`/api/v1/bookings/${completeModalBookingId}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ discount_choice, promo_code, bonus_points_redeemed })
        });
        if (res.ok) location.reload();
        else { const d = await res.json(); alert(d.detail || 'Ошибка'); }
    };

    // ===== Закрытие даты =====
    window.submitCloseDate = async function() {
        const date = document.getElementById('closeDateInput').value;
        const masterId = document.getElementById('closeDateMaster').value;
        const reason = document.getElementById('closeDateReason').value;
        if (!date) { alert('Укажите дату'); return; }
        const res = await fetch(`/api/v1/schedule/salon/${window.salonId}/closures`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date, master_id: masterId ? parseInt(masterId) : null, reason: reason || null })
        });
        if (res.ok) location.reload();
        else { const d = await res.json(); alert(d.detail || 'Ошибка'); }
    };

    window.reopenClosure = function(closureId) {
        if (!confirm('Открыть эту дату снова для записи?')) return;
        fetch(`/api/v1/schedule/salon/${window.salonId}/closures/${closureId}`, { method: 'DELETE' })
            .then(async r => { if (r.ok) location.reload(); else { const d = await r.json(); alert(d.detail || 'Ошибка'); } });
    };

    // ===== Закрытие модалок =====
    document.querySelectorAll('.schedule-modal-close').forEach(btn => {
        btn.addEventListener('click', function() {
            this.closest('.schedule-modal-overlay').classList.remove('active');
        });
    });

    document.querySelectorAll('.schedule-modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.schedule-modal-overlay.active').forEach(el => el.classList.remove('active'));
        }
    });

    // ===== Раскрывающиеся карточки (десктоп) =====
    function closeAllBookingCards() {
        document.querySelectorAll('.schedule-booking-wrapper.open').forEach(w => {
            w.classList.remove('open');
            w.querySelector('.schedule-booking-header')?.classList.remove('open');
        });
    }

    function toggleBookingCard(header) {
        const wrapper = header.closest('.schedule-booking-wrapper');
        if (!wrapper) return;
        const isOpen = wrapper.classList.contains('open');
        closeAllBookingCards();
        if (!isOpen) {
            wrapper.classList.add('open');
            header.classList.add('open');
        }
    }

    document.addEventListener('click', function(e) {
        const header = e.target.closest('.schedule-booking-header');
        if (header) {
            e.stopPropagation();
            toggleBookingCard(header);
            return;
        }
        const wrapper = e.target.closest('.schedule-booking-wrapper');
        if (!wrapper) {
            closeAllBookingCards();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeAllBookingCards();
        }
    });

    // ===== Мобильная навигация (без перезагрузки) =====
    document.addEventListener('DOMContentLoaded', function() {
        const mobileContainer = document.querySelector('.schedule-mobile-container');
        if (!mobileContainer) {
            console.log('Мобильный контейнер не найден');
            return;
        }

        const listEl = document.getElementById('schedule-mobile-list');
        const dateLabel = document.getElementById('mobile-date-label');
        if (!listEl || !dateLabel) {
            console.error('Не найдены элементы списка или даты');
            return;
        }

        // Проверяем наличие данных
        if (typeof window.weekData === 'undefined' || !window.weekData.length) {
            console.warn('weekData не определён или пуст');
            // Можно попробовать загрузить текущую неделю через fetch
        }

        const masterId = window.scheduleMasterId;
        const salonId = window.scheduleSalonId;
        let currentDateStr = window.currentDate || new Date().toISOString().split('T')[0];
        let weekData = window.weekData || [];
        let weekStart = window.weekStart || null;
        let weekDays = window.weekDays || [];

        // Функция рендеринга списка для конкретной даты
        function renderDay(dateStr) {
            // Находим день в weekData
            let dayData = weekData.find(d => d.date === dateStr);
            if (!dayData) {
                // Если день не найден, возможно мы вышли за пределы недели
                listEl.innerHTML = '<div class="schedule-mobile-empty">Загрузка...</div>';
                fetchWeek(dateStr).then(() => {
                    renderDay(dateStr);
                });
                return;
            }

            const bookings = dayData.bookings || [];
            if (bookings.length === 0) {
                listEl.innerHTML = '<div class="schedule-mobile-empty">На этот день записей нет</div>';
                return;
            }

            let cards = '';
            bookings.forEach(b => {
                const canManage = window.canManageSchedule && (b.status === 'pending' || b.status === 'confirmed');
                let actions = '';
                if (canManage) {
                    if (b.status === 'pending') {
                        actions = `
                            <div class="schedule-mobile-actions">
                                <button class="btn-action btn-action-success" onclick="acceptBooking(${b.id})">Подтвердить</button>
                                <button class="btn-action btn-action-danger" onclick="rejectBooking(${b.id})">Отклонить</button>
                            </div>
                        `;
                    } else if (b.status === 'confirmed') {
                        actions = `
                            <div class="schedule-mobile-actions">
                                <button class="btn-action btn-action-success" onclick="markBooking(${b.id}, 'complete')">Пришёл</button>
                                <button class="btn-action btn-action-danger" onclick="markBooking(${b.id}, 'no-show')">Не пришёл</button>
                            </div>
                        `;
                    }
                }
                cards += `
                    <div class="schedule-mobile-card">
                        <div class="schedule-mobile-header">
                            <span class="schedule-mobile-time">${b.time}</span>
                            <span class="status-badge ${b.status_class}">${b.status_label}</span>
                        </div>
                        <div class="schedule-mobile-body">
                            <div><strong>${b.client_name}</strong></div>
                            <div class="schedule-mobile-detail">${b.service_name}</div>
                            <div class="schedule-mobile-detail">Сумма: ${b.price.toLocaleString()} ₽</div>
                            ${actions}
                        </div>
                    </div>
                `;
            });
            listEl.innerHTML = cards;

            // Обновляем label
            const d = new Date(dateStr + 'T00:00:00');
            const monthNames = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                                'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
            dateLabel.textContent = `${d.getDate()} ${monthNames[d.getMonth()]} ${d.getFullYear()}`;
            currentDateStr = dateStr;

            // Обновляем URL без перезагрузки
            const url = new URL(window.location);
            url.searchParams.set('date', dateStr);
            window.history.pushState({}, '', url);
        }

        // Функция загрузки новой недели (fetch)
        function fetchWeek(dateStr) {
            // Определяем начало недели для этой даты
            const d = new Date(dateStr + 'T00:00:00');
            const dayOfWeek = d.getDay(); // 0 = воскресенье
            const startOfWeek = new Date(d);
            startOfWeek.setDate(d.getDate() - (dayOfWeek === 0 ? 6 : dayOfWeek - 1)); // понедельник

            const params = new URLSearchParams(window.location.search);
            params.set('date', startOfWeek.toISOString().split('T')[0]);
            params.set('tab', 'schedule');
            if (masterId) params.set('schedule_master_id', masterId);
            const url = window.location.pathname + '?' + params.toString();

            return fetch(url)
                .then(response => response.text())
                .then(html => {
                    // Парсим HTML, извлекаем window.weekData
                    const match = html.match(/window\.weekData\s*=\s*(\[.*?\]);/s);
                    if (match) {
                        try {
                            const newData = JSON.parse(match[1]);
                            weekData = newData;
                            // Обновляем weekStart, weekDays
                            const matchStart = html.match(/window\.weekStart\s*=\s*['"](.*?)['"]/);
                            if (matchStart) weekStart = matchStart[1];
                            const matchDays = html.match(/window\.weekDays\s*=\s*(\[.*?\]);/s);
                            if (matchDays) weekDays = JSON.parse(matchDays[1]);
                            // Обновляем URL без перезагрузки
                            const urlObj = new URL(window.location);
                            urlObj.searchParams.set('date', startOfWeek.toISOString().split('T')[0]);
                            window.history.pushState({}, '', urlObj);
                            return Promise.resolve();
                        } catch (e) {
                            console.error('Ошибка парсинга weekData', e);
                            return Promise.reject(e);
                        }
                    } else {
                        console.error('Не удалось найти weekData в HTML');
                        return Promise.reject('No weekData');
                    }
                })
                .catch(err => {
                    console.error('Ошибка загрузки недели:', err);
                    listEl.innerHTML = '<div class="schedule-mobile-empty">Ошибка загрузки</div>';
                    return Promise.reject(err);
                });
        }

        // Обработчики кнопок
        const navButtons = mobileContainer.querySelectorAll('.schedule-nav-btn');
        navButtons.forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const offset = parseInt(this.dataset.offset);
                if (isNaN(offset)) return;

                // Если offset = 0, переходим на сегодня
                let targetDateStr;
                if (offset === 0) {
                    const todayObj = new Date();
                    targetDateStr = todayObj.toISOString().split('T')[0];
                } else {
                    const currentDateObj = new Date(currentDateStr + 'T00:00:00');
                    currentDateObj.setDate(currentDateObj.getDate() + offset);
                    targetDateStr = currentDateObj.toISOString().split('T')[0];
                }

                // Проверяем, есть ли день в текущей неделе
                const dayExists = weekData.some(d => d.date === targetDateStr);
                if (dayExists) {
                    renderDay(targetDateStr);
                } else {
                    // Загружаем новую неделю
                    fetchWeek(targetDateStr).then(() => {
                        renderDay(targetDateStr);
                    }).catch(() => {
                        // Если загрузка не удалась, пробуем перезагрузить страницу
                        window.location.href = window.location.pathname + '?' + new URLSearchParams({
                            tab: 'schedule',
                            salon_id: salonId,
                            schedule_master_id: masterId,
                            date: targetDateStr
                        }).toString();
                    });
                }
            });
        });

        // Инициализация: рендерим текущий день
        if (currentDateStr && weekData.length > 0) {
            renderDay(currentDateStr);
        } else {
            // Если данных нет, загружаем неделю из текущего URL
            const params = new URLSearchParams(window.location.search);
            const dateParam = params.get('date') || new Date().toISOString().split('T')[0];
            fetchWeek(dateParam).then(() => {
                renderDay(dateParam);
            }).catch(() => {
                // Если не удалось загрузить, перезагружаем страницу
                window.location.reload();
            });
        }
    });

    console.log('Schedule JS loaded');
})();