// static/src/js/settings.js

document.addEventListener('DOMContentLoaded', function() {
    // === Тема ===
    const themeButtons = document.querySelectorAll('.theme-btn');
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);

    themeButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const theme = this.dataset.theme;
            applyTheme(theme);
            localStorage.setItem('theme', theme);
        });
    });

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        themeButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.theme === theme);
        });
    }

    // === Уведомления ===
    const notifyBookings = document.getElementById('notify-bookings');
    const notifyPromotions = document.getElementById('notify-promotions');
    const notifyMethod = document.getElementById('notify-method');

    function saveNotificationSettings() {
        const settings = {
            bookings: notifyBookings.checked,
            promotions: notifyPromotions.checked,
            method: notifyMethod.value
        };
        localStorage.setItem('notification_settings', JSON.stringify(settings));
        console.log('Настройки уведомлений сохранены:', settings);
    }

    if (notifyBookings) notifyBookings.addEventListener('change', saveNotificationSettings);
    if (notifyPromotions) notifyPromotions.addEventListener('change', saveNotificationSettings);
    if (notifyMethod) notifyMethod.addEventListener('change', saveNotificationSettings);

    const savedNotifications = localStorage.getItem('notification_settings');
    if (savedNotifications) {
        try {
            const settings = JSON.parse(savedNotifications);
            if (notifyBookings) notifyBookings.checked = settings.bookings !== undefined ? settings.bookings : true;
            if (notifyPromotions) notifyPromotions.checked = settings.promotions !== undefined ? settings.promotions : true;
            if (notifyMethod) notifyMethod.value = settings.method || 'email';
        } catch (e) {}
    }

    // === Аккордеон ===
    const accordionHeaders = document.querySelectorAll('.accordion-header');
    accordionHeaders.forEach(header => {
        header.addEventListener('click', function() {
            const parentItem = this.closest('.accordion-item');
            parentItem.classList.toggle('active');
        });
    });

    // === Формы смены данных ===
    const accordionForms = document.querySelectorAll('.accordion-form');
    accordionForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const type = this.dataset.type;
            const formData = new FormData(this);
            const data = Object.fromEntries(formData);

            console.log(`Смена данных (${type}):`, data);
            alert(`Данные для "${type}" успешно изменены (имитация).`);
        });
    });

    // === Удаление аккаунта ===
    const deleteBtn = document.getElementById('delete-account-btn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', function() {
            if (confirm('Вы уверены, что хотите удалить аккаунт? Это действие необратимо!')) {
                const password = prompt('Введите ваш пароль для подтверждения:');
                if (password) {
                    // Пароль в консоль не пишем: это была утечка в devtools.
                    // Сам поток — заглушка, настоящее удаление живёт в profile.js.
                    alert('Аккаунт удалён (имитация).');
                }
            }
        });
    }
});