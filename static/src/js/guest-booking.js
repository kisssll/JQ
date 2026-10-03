import { esc } from './escape-html.js';
import { enter, prefersReducedMotion } from './motion.js';
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

    // ---- Ссылка и QR для записи (блок booking_link.py: «Обзор» и «Редактировать салон») ----
    // Не по id, а по классу: блок один, но живёт на двух вкладках, и когда-нибудь
    // может оказаться на одной странице дважды — обработчик по id тогда молча
    // достался бы только первой кнопке.
    document.querySelectorAll('.js-copy-booking-link').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const link = location.origin + '/book/' + btn.dataset.salonId;
            const msg = btn.closest('.booking-link-side')?.querySelector('.js-copy-booking-msg');
            try {
                await navigator.clipboard.writeText(link);
                if (msg) { msg.textContent = 'Ссылка скопирована'; setTimeout(() => { msg.textContent = ''; }, 2500); }
            } catch (e) {
                // clipboard API недоступен (http/старый браузер) — показываем для ручного копирования
                window.prompt('Скопируйте ссылку:', link);
            }
        });
    });

    // Домен в разметке не зашит: на стейдже и в localhost он другой, а мастер
    // читает эту строку вслух клиенту — показываем настоящий адрес страницы.
    document.querySelectorAll('.js-booking-link-url').forEach(function (a) {
        a.textContent = location.host + new URL(a.href).pathname;
    });

    // ---- Управление бронью (отмена по токену) ----
    const cancelBtn = document.getElementById('gb-cancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', async function () {
            if (!await confirmDialog({ title: 'Отменить запись?', message: 'Запись будет отменена, время освободится.', confirmText: 'Отменить запись', cancelText: 'Оставить', danger: true })) return;
            cancelBtn.disabled = true;
            cancelBtn.classList.add('is-loading');
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
                    cancelBtn.classList.remove('is-loading');
                }
            } catch (e) {
                msg.textContent = 'Сеть недоступна, попробуйте ещё раз';
                cancelBtn.disabled = false;
                cancelBtn.classList.remove('is-loading');
            }
        });
    }

    // ---- Страница записи ----
    const root = document.getElementById('guest-book');
    if (!root) return;
    const salonId = parseInt(root.dataset.salonId);
    const masters = JSON.parse(root.dataset.masters);
    const state = { master: null, service: null, slot: null };

    // Единственный продуманный момент этой поверхности — переход между шагами.
    // Не въезд по прокрутке и не анимация каждой карточки: человек идёт по
    // короткому пути к «Записаться», и движение здесь нужно только затем,
    // чтобы показать, что экран сменился, а не просто перерисовался.
    function show(step) {
        let shown = null;
        root.querySelectorAll('.gb-step').forEach(s => {
            const active = s.dataset.step === step;
            s.hidden = !active;
            if (active) shown = s;
        });
        if (!shown) return;
        enter(shown, { y: 12 });

        // Длинный список мастеров прокручен вниз; следующий шаг короче, и без
        // этого человек оказывается в пустоте под ним и думает, что ничего
        // не произошло. Прокручиваем, только если шаг действительно ушёл
        // выше окна, — иначе дёргали бы страницу на каждом клике.
        const top = shown.getBoundingClientRect().top;
        if (top < 0) {
            window.scrollTo({
                top: window.scrollY + top - 16,
                behavior: prefersReducedMotion() ? 'auto' : 'smooth',
            });
        }
    }
    root.querySelectorAll('.gb-back').forEach(b => b.addEventListener('click', () => show(b.dataset.to)));

    // Шаг 1 — мастера
    const mList = document.getElementById('gb-masters');
    masters.forEach(m => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'r-card r-card--pick';
        b.innerHTML = `<div class="gb-ava" aria-hidden="true">${esc(m.name[0] || 'М')}</div>` +
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
            b.type = 'button';
            b.className = 'r-card r-card--pick';
            // Размеры снимка — классом, а не инлайновым style: до этого их
            // было не видно ни из CSS, ни из темы.
            const photos = (s.photos || []).map(url =>
                `<img src="${esc(url)}" alt="${esc(s.name)}" loading="lazy" data-lightbox-src="${esc(url)}" data-lightbox-alt="${esc(s.name)}" data-lightbox-group="service-${s.id}">`
            ).join('');
            b.innerHTML = `<div class="gb-card-body"><strong>${esc(s.name)}</strong><small>${esc(s.duration)} мин</small></div>` +
                (photos ? `<div class="gb-card-photos">${photos}</div>` : '') +
                `<div class="gb-card-price">${s.price_max == null ? s.price.toLocaleString('ru-RU') : `от ${s.price.toLocaleString('ru-RU')} до ${s.price_max.toLocaleString('ru-RU')}`} ₽</div>`;
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
        grid.innerHTML = '<p>Загрузка…</p>';
        try {
            const res = await fetch(`/api/v1/bookings/available/${state.master.id}?date=${dateInput.value}&service_id=${state.service.id}`);
            const data = await res.json();
            grid.innerHTML = '';
            if (data.slots && data.slots.length) {
                data.slots.forEach(slot => {
                    const b = document.createElement('button');
                    b.type = 'button';
                    b.className = 'gb-slot';
                    b.textContent = new Date(slot).toTimeString().slice(0, 5);
                    b.addEventListener('click', () => { state.slot = slot; renderDetails(); show('details'); });
                    grid.appendChild(b);
                });
            } else {
                grid.innerHTML = '<p>Нет свободных окон на эту дату</p>';
            }
        } catch (e) {
            grid.innerHTML = '<p>Ошибка загрузки</p>';
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
        // Кнопка уходит в загрузку, а не просто гаснет: между нажатием и
        // ответом сервера проходит секунда, и без признака работы человек
        // жмёт второй раз (ровно этим был инцидент двойной регистрации).
        this.disabled = true;
        this.classList.add('is-loading');
        this.setAttribute('aria-busy', 'true');
        err.textContent = '';
        const stopLoading = () => {
            this.disabled = false;
            this.classList.remove('is-loading');
            this.removeAttribute('aria-busy');
        };
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
            if (!res.ok) { err.textContent = data.detail || 'Не удалось записаться'; stopLoading(); return; }
            const link = `${location.origin}/guest-booking/${data.manage_token}`;
            const a = document.getElementById('gb-manage-link');
            a.href = link;
            a.textContent = link;
            show('done');
        } catch (e) {
            err.textContent = 'Сеть недоступна, попробуйте ещё раз';
            stopLoading();
        }
    });
})();
