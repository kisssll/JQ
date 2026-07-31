// static/src/js/business/tabs/schedule.js
// Управление навигацией по неделям (стрелки) и общие функции для расписания

(function () {
    'use strict';

    // --- Навигация по неделям (стрелки) ---
    let currentWeekIndex = window.activeWeekIndex || 0;
    const weekData = window.weekData || [];
    const totalWeeks = weekData.length;

    function updateWeekDisplay(index) {
        if (index < 0 || index >= totalWeeks) return;

        document.querySelectorAll('.schedule-week-panel-wrapper').forEach(el => {
            el.classList.remove('active');
        });
        const target = document.querySelector(`.schedule-week-panel-wrapper[data-week-index="${index}"]`);
        if (target) target.classList.add('active');

        const monthSpan = document.getElementById('scheduleCurrentMonth');
        if (monthSpan && weekData[index]) {
            monthSpan.textContent = `${weekData[index].month_name} ${weekData[index].year}`;
        }

        const prevBtn = document.getElementById('schedulePrevWeek');
        const nextBtn = document.getElementById('scheduleNextWeek');
        if (prevBtn) prevBtn.disabled = (index === 0);
        if (nextBtn) nextBtn.disabled = (index === totalWeeks - 1);

        currentWeekIndex = index;
    }

    window.goToWeek = function (index) {
        if (index < 0 || index >= totalWeeks) return;
        updateWeekDisplay(index);
    };

    window.prevWeek = function () {
        if (currentWeekIndex > 0) {
            updateWeekDisplay(currentWeekIndex - 1);
        }
    };

    window.nextWeek = function () {
        if (currentWeekIndex < totalWeeks - 1) {
            updateWeekDisplay(currentWeekIndex + 1);
        }
    };

    function initScheduleNavigation() {
        if (!weekData.length) return;
        updateWeekDisplay(currentWeekIndex);
        document.getElementById('schedulePrevWeek')?.addEventListener('click', window.prevWeek);
        document.getElementById('scheduleNextWeek')?.addEventListener('click', window.nextWeek);
    }

    // --- Остальные функции (без изменений) ---
    window.markBooking = function (bookingId, action) {
        const label = action === 'complete' ? 'выполненной' : 'неявкой';
        if (!confirm(`Отметить запись ${label}?`)) return;
        fetch(`/api/v1/bookings/${bookingId}/${action}`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else r.json().then(d => alert(d.detail || 'Ошибка'));
            });
    };

    window.acceptBooking = function (bookingId) {
        if (!confirm('Подтвердить запись?')) return;
        fetch(`/api/v1/bookings/${bookingId}/accept`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else r.json().then(d => alert(d.detail || 'Не удалось подтвердить'));
            });
    };

    window.rejectBooking = function (bookingId) {
        if (!confirm('Отклонить запись? Клиент получит уведомление.')) return;
        fetch(`/api/v1/bookings/${bookingId}/reject`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else r.json().then(d => alert(d.detail || 'Не удалось отклонить'));
            });
    };

    window.markSeen = function (bookingId, btn) {
        fetch(`/api/v1/bookings/${bookingId}/mark-seen`, { method: 'POST' })
            .then(r => {
                if (r.ok) {
                    btn.outerHTML = '<span class="seen-indicator" title="Вы отметили, что видели эту запись">👁 Видели</span>';
                } else {
                    r.json().then(d => alert(d.detail || 'Не удалось отметить'));
                }
            });
    };

    let completeModalBookingId = null;

    window.openCompleteModal = async function (bookingId, clientId) {
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

    window.submitCompleteWithDiscount = async function () {
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

    window.submitCloseDate = async function () {
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

    window.reopenClosure = function (closureId) {
        if (!confirm('Открыть эту дату снова для записи?')) return;
        fetch(`/api/v1/schedule/salon/${window.salonId}/closures/${closureId}`, { method: 'DELETE' })
            .then(async r => { if (r.ok) location.reload(); else { const d = await r.json(); alert(d.detail || 'Ошибка'); } });
    };

    document.querySelectorAll('.schedule-modal-close').forEach(btn => {
        btn.addEventListener('click', function () {
            this.closest('.schedule-modal-overlay').classList.remove('active');
        });
    });

    document.querySelectorAll('.schedule-modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function (e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.schedule-modal-overlay.active').forEach(el => el.classList.remove('active'));
        }
    });

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

    document.addEventListener('click', function (e) {
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

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            closeAllBookingCards();
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        initScheduleNavigation();
    });

    console.log('Schedule JS loaded');
})();