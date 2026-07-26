// static/src/js/salon-detail.js

(function() {
    const container = document.getElementById('booking-flow-container');
    if (!container) return;

    const masters = JSON.parse(container.dataset.masters);
    const userData = JSON.parse(container.dataset.user || 'null');

    // Состояние
    const state = {
        master: null,
        service: null,
        date: null,
        time: null,
        reminder: 60, // минут
        reminderEnabled: true,
    };

    // DOM элементы шагов
    const steps = {
        masters: document.getElementById('step-masters'),
        services: document.getElementById('step-services'),
        date: document.getElementById('step-date'),
        time: document.getElementById('step-time'),
        reminder: document.getElementById('step-reminder'),
        confirm: document.getElementById('step-confirm'),
    };

    // Функция переключения шага (без скролла вверх)
    function goToStep(stepName) {
        Object.keys(steps).forEach(key => {
            steps[key].style.display = (key === stepName) ? 'block' : 'none';
        });
        // Убираем принудительный скролл вверх
    }

    // Всегда показываем список мастеров, даже если только один
    goToStep('masters');
    renderMasters();

    // ---- Шаг 1: Мастера ----
    function renderMasters() {
        const grid = document.querySelector('.masters-grid');
        // Уже отрендерено через HTML, добавляем обработчики
        document.querySelectorAll('.master-card .master-book-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const id = parseInt(this.dataset.masterId);
                selectMaster(id);
            });
        });
        document.querySelectorAll('.master-card').forEach(card => {
            card.addEventListener('click', function() {
                const id = parseInt(this.dataset.masterId);
                selectMaster(id);
            });
        });
    }

    function selectMaster(id) {
        const master = masters.find(m => m.id === id);
        if (!master) return;
        state.master = master;
        goToStep('services');
        renderServices();
    }

    // ---- Шаг 2: Услуги ----
    function renderServices() {
        const master = state.master;
        // Обновляем хлебные крошки
        document.getElementById('breadcrumb-master').textContent = master.name;
        // Сводка
        document.getElementById('selected-master-name').textContent = master.name;
        document.getElementById('selected-master-spec').textContent = master.specialization;
        const avatar = document.getElementById('selected-master-avatar');
        avatar.innerHTML = master.avatar ? `<img src="${master.avatar}" alt="">` : `<span>${master.name[0]}</span>`;

        // Список услуг
        const list = document.getElementById('services-list');
        list.innerHTML = '';
        master.services.forEach(service => {
            const btn = document.createElement('button');
            btn.className = 'service-btn';
            btn.dataset.serviceId = service.id;
            btn.innerHTML = `
                <div class="service-info">
                    <span class="service-name">${service.name}</span>
                    <span class="service-duration">${service.duration} мин</span>
                </div>
                <div class="service-price">${service.price.toLocaleString()} ₽</div>
                <span class="chevron">${getIcon('chevron-right')}</span>
            `;
            btn.addEventListener('click', () => selectService(service.id));
            list.appendChild(btn);
        });

        // Показываем шаг
        goToStep('services');
    }

    function selectService(id) {
        const service = state.master.services.find(s => s.id === id);
        if (!service) return;
        state.service = service;
        goToStep('date');
        renderDateSelection();
    }

    // ---- Шаг 3: Дата ----
    function renderDateSelection() {
        const master = state.master;
        const service = state.service;
        // Обновляем breadcrumb
        document.getElementById('breadcrumb-master-2').textContent = master.name;
        document.getElementById('breadcrumb-service').textContent = service.name;
        // Сводка
        document.getElementById('selected-master-name-2').textContent = master.name;
        document.getElementById('selected-master-spec-2').textContent = master.specialization;
        const avatar = document.getElementById('selected-master-avatar-2');
        avatar.innerHTML = master.avatar ? `<img src="${master.avatar}" alt="">` : `<span>${master.name[0]}</span>`;
        document.getElementById('selected-service-summary').textContent = service.name;
        document.getElementById('selected-service-price').textContent = `${service.price.toLocaleString()} ₽`;

        // Генерируем даты (сегодня + MAX_BOOKING_DAYS_AHEAD дней)
        const today = new Date();
        today.setHours(0,0,0,0);
        const dates = [];
        for (let i = 0; i < window.maxBookingDays; i++) {
            const d = new Date(today);
            d.setDate(d.getDate() + i);
            dates.push(d);
        }

        const grid = document.getElementById('dates-grid');
        grid.innerHTML = '';
        const todayStr = today.toDateString();
        dates.forEach((d, index) => {
            const btn = document.createElement('button');
            btn.className = 'date-btn';
            const isToday = d.toDateString() === todayStr;
            const dayLabel = isToday ? 'Сегодня' : ['Вс','Пн','Вт','Ср','Чт','Пт','Сб'][d.getDay()];
            const dayNumber = d.getDate();
            const month = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'][d.getMonth()];
            btn.innerHTML = `
                <span class="day-label">${dayLabel}</span>
                <span class="day-number">${dayNumber}</span>
                <span class="month-label">${month}</span>
            `;
            // Локальная дата (не toISOString — он переводит в UTC и в TZ впереди
            // UTC сдвигает дату на день назад, из-за чего кнопка «27» слала «26»).
            const yyyy = d.getFullYear();
            const mm = String(d.getMonth() + 1).padStart(2, '0');
            const dd = String(d.getDate()).padStart(2, '0');
            btn.dataset.date = `${yyyy}-${mm}-${dd}`;
            btn.addEventListener('click', () => selectDate(btn.dataset.date));
            grid.appendChild(btn);
        });
    }

    function selectDate(dateStr) {
        state.date = dateStr;
        // Обновляем активную кнопку
        document.querySelectorAll('.date-btn').forEach(b => b.classList.remove('active'));
        document.querySelector(`.date-btn[data-date="${dateStr}"]`)?.classList.add('active');
        goToStep('time');
        renderTimeSelection();
    }

    // ---- Шаг 4: Время ----
    function renderTimeSelection() {
        const master = state.master;
        const service = state.service;
        const date = state.date;
        // Обновляем breadcrumb
        document.getElementById('breadcrumb-master-3').textContent = master.name;
        document.getElementById('breadcrumb-service-2').textContent = service.name;
        const dateObj = new Date(date + 'T00:00:00');
        const dateStr = dateObj.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
        document.getElementById('breadcrumb-date').textContent = dateStr;
        // Сводка
        document.getElementById('selected-master-name-3').textContent = master.name;
        document.getElementById('selected-master-spec-3').textContent = master.specialization;
        const avatar = document.getElementById('selected-master-avatar-3');
        avatar.innerHTML = master.avatar ? `<img src="${master.avatar}" alt="">` : `<span>${master.name[0]}</span>`;
        document.getElementById('selected-service-summary-2').textContent = service.name;
        document.getElementById('selected-service-price-2').textContent = `${service.price.toLocaleString()} ₽`;
        document.getElementById('selected-date-summary').textContent = dateStr;

        // Загружаем слоты
        const grid = document.getElementById('times-grid');
        grid.innerHTML = '<p style="color:var(--color-muted)">Загрузка...</p>';
        fetch(`/api/v1/bookings/available/${master.id}?date=${date}&service_id=${service.id}`)
            .then(r => r.json())
            .then(data => {
                grid.innerHTML = '';
                if (data.slots && data.slots.length) {
                    data.slots.forEach(slot => {
                        const btn = document.createElement('button');
                        btn.className = 'time-btn';
                        const dt = new Date(slot);
                        const timeStr = dt.toTimeString().slice(0,5);
                        btn.textContent = timeStr;
                        btn.dataset.time = slot;
                        btn.addEventListener('click', () => selectTime(slot));
                        grid.appendChild(btn);
                    });
                } else {
                    grid.innerHTML = '<p style="color:var(--color-muted)">Нет свободных окон на эту дату</p>';
                }
            })
            .catch(() => {
                grid.innerHTML = '<p style="color:var(--color-muted)">Ошибка загрузки</p>';
            });
    }

    function selectTime(time) {
        state.time = time;
        document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
        document.querySelector(`.time-btn[data-time="${time}"]`)?.classList.add('active');
        goToStep('reminder');
        renderReminder();
    }

    // ---- Шаг 5: Напоминание ----
    function renderReminder() {
        const master = state.master;
        const service = state.service;
        const date = state.date;
        const time = state.time;
        const dateObj = new Date(date + 'T00:00:00');
        const dateStr = dateObj.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
        const timeObj = new Date(time);
        const timeStr = timeObj.toTimeString().slice(0,5);
        document.getElementById('breadcrumb-master-4').textContent = master.name;
        document.getElementById('breadcrumb-service-3').textContent = service.name;
        document.getElementById('breadcrumb-date-2').textContent = dateStr;
        document.getElementById('breadcrumb-time').textContent = timeStr;
        // Сводка
        document.getElementById('selected-master-name-4').textContent = master.name;
        document.getElementById('selected-master-spec-4').textContent = master.specialization;
        const avatar = document.getElementById('selected-master-avatar-4');
        avatar.innerHTML = master.avatar ? `<img src="${master.avatar}" alt="">` : `<span>${master.name[0]}</span>`;
        document.getElementById('selected-service-summary-3').textContent = service.name;
        document.getElementById('selected-service-price-3').textContent = `${service.price.toLocaleString()} ₽`;
        document.getElementById('selected-date-summary-2').textContent = dateStr;
        document.getElementById('selected-time-summary').textContent = timeStr;

        // Напоминание
        const toggle = document.getElementById('reminder-toggle');
        toggle.classList.toggle('active', state.reminderEnabled);
        document.querySelectorAll('.reminder-option').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.minutes) === state.reminder);
        });
        // Обработчики
        toggle.onclick = function() {
            state.reminderEnabled = !state.reminderEnabled;
            this.classList.toggle('active');
        };
        document.querySelectorAll('.reminder-option').forEach(btn => {
            btn.onclick = function() {
                document.querySelectorAll('.reminder-option').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                state.reminder = parseInt(this.dataset.minutes);
            };
        });
        document.getElementById('reminder-next').onclick = function() {
            goToStep('confirm');
            renderConfirm();
        };
    }

    // ---- Шаг 6: Подтверждение ----
    function renderConfirm() {
        const master = state.master;
        const service = state.service;
        const date = state.date;
        const time = state.time;
        const dateObj = new Date(date + 'T00:00:00');
        const dateStr = dateObj.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', weekday: 'short' });
        const timeObj = new Date(time);
        const timeStr = timeObj.toTimeString().slice(0,5);
        const datetimeStr = `${dateStr} — ${timeStr}`;
        const reminderLabel = state.reminderEnabled ? `За ${state.reminder >= 1440 ? 'день' : state.reminder >= 60 ? state.reminder/60 + ' часа' : state.reminder + ' мин'}` : 'Не напоминать';

        document.getElementById('confirm-master').textContent = master.name;
        document.getElementById('confirm-master-spec').textContent = master.specialization;
        document.getElementById('confirm-service').textContent = service.name;
        document.getElementById('confirm-duration').textContent = `${service.duration} мин`;
        document.getElementById('confirm-price').textContent = `${service.price.toLocaleString()} ₽`;
        document.getElementById('confirm-datetime').textContent = datetimeStr;
        document.getElementById('confirm-reminder').textContent = reminderLabel;

        // Данные пользователя
        if (userData) {
            document.getElementById('confirm-user-name').textContent = userData.full_name || 'Гость';
            document.getElementById('confirm-user-phone').textContent = userData.phone || '';
        } else {
            document.getElementById('confirm-user-name').textContent = 'Гость';
            document.getElementById('confirm-user-phone').textContent = '';
        }

        // Кнопка записи
        document.getElementById('confirm-submit').onclick = function() {
            if (!userData) {
                window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
                return;
            }
            const data = {
                master_id: master.id,
                service_id: service.id,
                start_time: time,
            };
            fetch('/api/v1/bookings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            .then(r => r.json())
            .then(result => {
                if (result.id) {
                    alert('Запись успешно создана!');
                    window.location.href = '/bookings';
                } else {
                    alert(result.detail || 'Ошибка при создании записи');
                }
            })
            .catch(err => {
                alert('Сетевая ошибка, попробуйте позже.');
            });
        };
    }

    // ---- Вспомогательные функции ----
    function getIcon(name) {
        const icons = {
            'chevron-right': `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>`,
            'arrow-left': `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>`,
        };
        return icons[name] || '';
    }

    // ---- Навигация по хлебным крошкам и кнопкам "назад" ----
    document.querySelectorAll('.breadcrumb-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const step = this.dataset.step;
            // Если идём на шаг мастера, сбрасываем выбор
            if (step === 'masters') {
                state.master = null;
                state.service = null;
                state.date = null;
                state.time = null;
                goToStep('masters');
                renderMasters();
            } else {
                goToStep(step);
                // Перерендерить соответствующий шаг
                if (step === 'services') renderServices();
                else if (step === 'date') renderDateSelection();
                else if (step === 'time') renderTimeSelection();
                else if (step === 'reminder') renderReminder();
            }
        });
    });

    document.querySelectorAll('.back-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const step = this.dataset.step;
            goToStep(step);
            if (step === 'masters') {
                state.master = null;
                state.service = null;
                state.date = null;
                state.time = null;
                renderMasters();
            } else if (step === 'services') renderServices();
            else if (step === 'date') renderDateSelection();
            else if (step === 'time') renderTimeSelection();
            else if (step === 'reminder') renderReminder();
        });
    });

    // ---- Инициализация избранного (салон + мастера) ----
    async function loadFavorites() {
        try {
            const response = await fetch('/api/v1/favorites/my');
            if (response.ok) {
                const data = await response.json();
                document.querySelectorAll('.salon-top-fav[data-type="salon"]').forEach(btn => {
                    const id = parseInt(btn.dataset.id);
                    if (data.salon_ids.includes(id)) {
                        btn.classList.add('liked');
                    } else {
                        btn.classList.remove('liked');
                    }
                });
                document.querySelectorAll('.master-fav-btn[data-type="master"]').forEach(btn => {
                    const id = parseInt(btn.dataset.id);
                    if (data.master_ids.includes(id)) {
                        btn.classList.add('liked');
                    } else {
                        btn.classList.remove('liked');
                    }
                });
            }
        } catch (e) {}
    }
    loadFavorites();

    document.querySelectorAll('.salon-top-fav, .master-fav-btn').forEach(btn => {
        btn.addEventListener('click', async function(e) {
            e.preventDefault();
            e.stopPropagation();
            const type = this.dataset.type;
            const id = this.dataset.id;
            const isLiked = this.classList.contains('liked');
            try {
                const response = await fetch(`/api/v1/favorites/toggle-${type}/${id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (response.ok) {
                    if (isLiked) {
                        this.classList.remove('liked');
                    } else {
                        this.classList.add('liked');
                    }
                } else if (response.status === 302) {
                    window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
                } else {
                    alert('Не удалось изменить избранное. Попробуйте позже.');
                }
            } catch (err) {
                console.error(err);
                alert('Ошибка соединения.');
            }
        });
    });
})();