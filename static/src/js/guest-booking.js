import { esc } from './escape-html.js';
// static/src/js/guest-booking.js — запись без регистрации (страница /book/{salon})
// и управление бронью по токену (/guest-booking/{token}).
import { confirmDialog } from './ui-feedback.js';

(function () {
    // ---- Тумблер «запись без регистрации» в панели салона ----
    const guestToggle = document.getElementById('guestToggle');
    if (guestToggle) {
        guestToggle.addEventListener('change', async function () {
            guestToggle.disabled = true;
            try {
                await fetch(`/api/v1/business/my-salon/guest-toggle?salon_id=${guestToggle.dataset.salonId}`, { method: 'POST' });
            } catch (e) { /* сеть моргнула — состояние применится при следующем клике */ }
            guestToggle.disabled = false;
        });
    }

    // ---- Копирование ссылки записи без регистрации (панель салона) ----
    const copyBtn = document.getElementById('guestCopyLink');
    if (copyBtn) {
        copyBtn.addEventListener('click', async function () {
            const link = location.origin + '/book/' + copyBtn.dataset.salonId;
            const msg = document.getElementById('guestCopyMsg');
            try {
                await navigator.clipboard.writeText(link);
                if (msg) { msg.textContent = 'Скопировано ✓'; setTimeout(() => { msg.textContent = ''; }, 2000); }
            } catch (e) {
                // clipboard API недоступен (http/старый браузер) — показываем для ручного копирования
                window.prompt('Скопируйте ссылку:', link);
            }
        });
    }

    // ---- Управление бронью (отмена по токену) ----
    const cancelBtn = document.getElementById('gb-cancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', async function () {
            if (!await confirmDialog({ title: 'Отменить запись?', message: 'Запись будет отменена, время освободится.', confirmText: 'Отменить запись', cancelText: 'Оставить', danger: true })) return;
            cancelBtn.disabled = true;
            const msg = document.getElementById('gb-cancel-msg');
            try {
                const res = await fetch(`/api/v1/guest/booking/${cancelBtn.dataset.token}/cancel`, { method: 'POST' });
                if (res.ok) {
                    msg.textContent = 'Запись отменена.';
                    cancelBtn.remove();
                    setTimeout(() => location.reload(), 1000);
                } else {
                    const d = await res.json();
                    msg.textContent = d.detail || 'Не удалось отменить';
                    cancelBtn.disabled = false;
                }
            } catch (e) {
                msg.textContent = 'Сеть недоступна, попробуйте ещё раз';
                cancelBtn.disabled = false;
            }
        });
    }

    // ---- Страница записи ----
    const root = document.getElementById('guest-book');
    if (!root) return;
    const salonId = parseInt(root.dataset.salonId);
    const masters = JSON.parse(root.dataset.masters);
    const state = { master: null, service: null, slot: null };

    function show(step) {
        root.querySelectorAll('.gb-step').forEach(s => {
            s.style.display = (s.dataset.step === step) ? 'block' : 'none';
        });
    }
    root.querySelectorAll('.gb-back').forEach(b => b.addEventListener('click', () => show(b.dataset.to)));

    // Шаг 1 — мастера
    const mList = document.getElementById('gb-masters');
    masters.forEach(m => {
        const b = document.createElement('button');
        b.className = 'gb-card';
        b.innerHTML = `<div class="gb-ava">${esc(m.name[0] || 'М')}</div>` +
            `<div class="gb-card-body"><strong>${esc(m.name)}</strong><small>${esc(m.spec)}</small></div>`;
        b.addEventListener('click', () => { state.master = m; renderServices(); show('service'); });
        mList.appendChild(b);
    });

    // Шаг 2 — услуги
    function renderServices() {
        const el = document.getElementById('gb-services');
        el.innerHTML = '';
        state.master.services.forEach(s => {
            const b = document.createElement('button');
            b.className = 'gb-card';
            b.innerHTML = `<div class="gb-card-body"><strong>${esc(s.name)}</strong><small>${esc(s.duration)} мин</small></div>` +
                `<div class="gb-card-price">${s.price.toLocaleString('ru-RU')} ₽</div>`;
            b.addEventListener('click', () => { state.service = s; setupDate(); show('slot'); });
            el.appendChild(b);
        });
    }

    // Шаг 3 — дата и слоты
    const dateInput = document.getElementById('gb-date');
    function setupDate() {
        // Локальная дата (toISOString даёт UTC — в TZ впереди UTC ранним утром
        // это «вчера», и min/дефолт съезжают на день назад).
        const now = new Date();
        const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        dateInput.min = today;
        if (!dateInput.value) dateInput.value = today;
        loadSlots();
    }
    if (dateInput) dateInput.addEventListener('change', loadSlots);

    async function loadSlots() {
        const grid = document.getElementById('gb-slots');
        grid.innerHTML = '<p class="text-muted">Загрузка…</p>';
        try {
            const res = await fetch(`/api/v1/bookings/available/${state.master.id}?date=${dateInput.value}&service_id=${state.service.id}`);
            const data = await res.json();
            grid.innerHTML = '';
            if (data.slots && data.slots.length) {
                data.slots.forEach(slot => {
                    const b = document.createElement('button');
                    b.className = 'gb-slot';
                    b.textContent = new Date(slot).toTimeString().slice(0, 5);
                    b.addEventListener('click', () => { state.slot = slot; renderDetails(); show('details'); });
                    grid.appendChild(b);
                });
            } else {
                grid.innerHTML = '<p class="text-muted">Нет свободных окон на эту дату</p>';
            }
        } catch (e) {
            grid.innerHTML = '<p class="text-muted">Ошибка загрузки</p>';
        }
    }

    // Шаг 4 — данные и отправка
    function renderDetails() {
        const d = new Date(state.slot);
        document.getElementById('gb-summary').textContent =
            `${state.master.name} · ${state.service.name} · ` +
            `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} ${d.toTimeString().slice(0, 5)}`;
    }

    document.getElementById('gb-submit').addEventListener('click', async function () {
        const err = document.getElementById('gb-error');
        const name = document.getElementById('gb-name').value.trim();
        const phone = document.getElementById('gb-phone').value.trim();
        const email = document.getElementById('gb-email').value.trim();
        if (!name || !phone) { err.textContent = 'Укажите имя и телефон'; return; }
        // Согласие на ПДн обязательно и здесь: форма собирает имя, телефон и
        // почту, то есть ровно те же категории, что и регистрация.
        const consent = document.getElementById('gb-consent');
        if (consent && !consent.checked) {
            err.textContent = 'Отметьте согласие на обработку персональных данных';
            return;
        }
        this.disabled = true;
        err.textContent = '';
        try {
            const res = await fetch('/api/v1/guest/booking', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    salon_id: salonId, master_id: state.master.id, service_id: state.service.id,
                    start_time: state.slot, name, phone, email: email || null,
                    pd_consent: true, consent_version: document.body.dataset.legalVersion || null,
                }),
            });
            const data = await res.json();
            if (!res.ok) { err.textContent = data.detail || 'Не удалось записаться'; this.disabled = false; return; }
            const link = `${location.origin}/guest-booking/${data.manage_token}`;
            const a = document.getElementById('gb-manage-link');
            a.href = link;
            a.textContent = link;
            show('done');
        } catch (e) {
            err.textContent = 'Сеть недоступна, попробуйте ещё раз';
            this.disabled = false;
        }
    });
})();
