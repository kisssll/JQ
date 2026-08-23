// static/src/js/profile.js
import { confirmDialog, toastError, toastNetworkError } from './ui-feedback.js';

document.addEventListener('DOMContentLoaded', function() {
    // === РЕДАКТИРОВАНИЕ ПРОФИЛЯ ===
    const editToggle = document.getElementById('profile-edit-toggle');
    if (editToggle) {
        const viewMode = document.getElementById('profile-view');
        const editMode = document.getElementById('profile-edit');
        const cancelBtn = document.getElementById('profile-edit-cancel');
        const saveBtn = document.getElementById('profile-edit-save');
        const editForm = document.getElementById('profile-edit-form');

        if (editToggle && viewMode && editMode) {
            editToggle.addEventListener('click', function() {
                viewMode.style.display = 'none';
                editMode.style.display = 'block';
                editMode.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });

            if (cancelBtn) {
                cancelBtn.addEventListener('click', function() {
                    editMode.style.display = 'none';
                    viewMode.style.display = 'block';
                });
            }

            if (saveBtn) {
                saveBtn.addEventListener('click', function() {
                    editForm.submit();
                });
            }
        }

        // === ЗАГРУЗКА АВАТАРА ===
        const avatarEditBtn = document.getElementById('profile-avatar-edit');
        const avatarInput = document.getElementById('profile-avatar-input');
        const avatarContainer = document.getElementById('profile-avatar-container');

        if (avatarEditBtn && avatarInput) {
            avatarEditBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                avatarInput.click();
            });

            if (avatarContainer) {
                avatarContainer.addEventListener('click', function(e) {
                    if (e.target.closest('.profile-avatar-edit')) return;
                    avatarInput.click();
                });
            }

            avatarInput.addEventListener('change', async function(e) {
                const file = e.target.files[0];
                if (!file) return;
                // Мгновенное превью + индикатор, пока грузится
                const container = document.getElementById('profile-avatar-container');
                const letter = container.querySelector('.profile-avatar-letter');
                if (letter) letter.remove();
                let img = container.querySelector('img');
                if (!img) { 
                    img = document.createElement('img'); 
                    container.prepend(img); 
                }
                img.src = URL.createObjectURL(file);
                img.style.opacity = '0.5';
                avatarEditBtn.disabled = true;
                const formData = new FormData();
                formData.append('file', file);
                try {
                    const res = await fetch('/api/v1/upload/avatar', { method: 'POST', body: formData });
                    const data = await res.json();
                    const img = container.querySelector('img');
                    if (!res.ok) {
                        if (img) img.remove();
                        toastError(data.detail || 'Не удалось загрузить фото');
                        return;
                    }
                    img.src = data.url + '?t=' + Date.now();
                    img.style.opacity = '';
                } catch (err) {
                    const img = container.querySelector('img');
                    if (img) img.remove();
                    toastNetworkError();
                } finally {
                    avatarEditBtn.disabled = false;
                    avatarInput.value = '';
                }
            });
        }
    }

    // === НАСТРОЙКИ (Тема, уведомления, аккордеон, формы, удаление) ===

    // Тема
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

    // Уведомления
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

    // Аккордеон
    const accordionHeaders = document.querySelectorAll('.accordion-header');
    accordionHeaders.forEach(header => {
        header.addEventListener('click', function() {
            const parentItem = this.closest('.accordion-item');
            if (parentItem) {
                parentItem.classList.toggle('active');
            }
        });
    });

    // Смена телефона — с подтверждением владения новым номером через Telegram.
    // Пароль/email/город отправляются нативным POST-ом формы (обработчик не нужен).
    (function initPhoneChange() {
        // Кнопок подтверждения теперь может быть несколько (Telegram и MAX):
        // общий обработчик, а канал берём из data-start-url нажатой кнопки.
        const verifyButtons = Array.from(document.querySelectorAll('.phone-verify-btn'));
        const verifyBtn = verifyButtons[0] || document.getElementById('phone-verify-btn');
        const saveBtn = document.getElementById('phone-save-btn');
        const phoneInput = document.getElementById('settings-phone');
        const reqIdInput = document.getElementById('phone-request-id');
        const hint = document.getElementById('phone-verify-hint');
        if (!verifyBtn || !saveBtn || !phoneInput || !reqIdInput) return;

        let pollTimer = null;
        let deadline = 0;
        const setHint = (t) => { if (hint) hint.textContent = t; };
        const stopPoll = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } };
        const resetVerify = () => {
            // Возвращаем ИМЕННО свои подписи — кнопок может быть две (TG и MAX)
            verifyButtons.forEach(b => {
                b.disabled = false;
                b.textContent = 'Подтвердить в ' + (b.dataset.channel || 'мессенджере');
            });
        };

        async function poll() {
            if (Date.now() > deadline) {
                stopPoll(); resetVerify();
                setHint('Время подтверждения вышло — нажмите кнопку ещё раз.');
                return;
            }
            try {
                const res = await fetch('/api/v1/auth/register/tg-status?request_id=' + encodeURIComponent(reqIdInput.value));
                if (!res.ok) return;
                const data = await res.json();
                if (data.status === 'confirmed') {
                    stopPoll();
                    verifyBtn.disabled = true;
                    verifyBtn.textContent = 'Номер подтверждён ✓';
                    saveBtn.disabled = false;
                    setHint('Готово! Нажмите «Сохранить».');
                } else if (data.status === 'not_found') {
                    stopPoll(); resetVerify();
                    setHint('Подтверждение устарело — нажмите кнопку ещё раз.');
                }
            } catch (e) { /* сеть моргнула — ждём следующий тик */ }
        }

        verifyButtons.forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const phone = phoneInput.value.trim();
            if (!phone) { toastError('Сначала введите новый номер'); return; }
            verifyButtons.forEach(b => { b.disabled = true; });
            btn.textContent = 'Открываем ' + (btn.dataset.channel || 'мессенджер') + '…';
            saveBtn.disabled = true;
            try {
                const res = await fetch(btn.dataset.startUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone: phone })
                });
                const data = await res.json();
                if (!res.ok) {
                    toastError(data.detail || 'Не удалось начать подтверждение');
                    resetVerify();
                    return;
                }
                reqIdInput.value = data.request_id;
                deadline = Date.now() + (data.expires_in_seconds || 600) * 1000;
                window.open(data.deep_link, '_blank');
                btn.textContent = 'Ждём подтверждения…';
                setHint('В боте нажмите «Поделиться контактом». Страница поймёт всё сама.');
                stopPoll();
                pollTimer = setInterval(poll, 2500);
            } catch (e) {
                toastNetworkError();
                resetVerify();
            }
        });
        });

        // Изменил номер после подтверждения — требуем верификацию заново
        phoneInput.addEventListener('input', function () {
            stopPoll();
            reqIdInput.value = '';
            saveBtn.disabled = true;
            resetVerify();
        });
    })();

    // Смена email — с подтверждением кодом, отправленным на новый адрес.
    (function initEmailChange() {
        const sendBtn = document.getElementById('email-send-code-btn');
        const saveBtn = document.getElementById('email-save-btn');
        const emailInput = document.getElementById('settings-email');
        const reqIdInput = document.getElementById('email-request-id');
        const codeGroup = document.getElementById('email-code-group');
        const codeInput = document.getElementById('settings-email-code');
        const hint = document.getElementById('email-verify-hint');
        if (!sendBtn || !saveBtn || !emailInput || !reqIdInput) return;
        const setHint = (t) => { if (hint) hint.textContent = t; };

        sendBtn.addEventListener('click', async function () {
            const email = emailInput.value.trim();
            if (!email) { toastError('Сначала введите новый email'); return; }
            sendBtn.disabled = true;
            sendBtn.textContent = 'Отправляем…';
            try {
                const res = await fetch('/api/v1/users/me/email/send-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'email=' + encodeURIComponent(email)
                });
                const data = await res.json();
                if (!res.ok) {
                    toastError(data.detail || 'Не удалось отправить код');
                    sendBtn.disabled = false;
                    sendBtn.textContent = 'Отправить код';
                    return;
                }
                reqIdInput.value = data.request_id;
                if (codeGroup) codeGroup.style.display = '';
                saveBtn.disabled = false;
                sendBtn.disabled = false;
                sendBtn.textContent = 'Отправить код ещё раз';
                setHint('Код отправлен на ' + email + '. Введите его и сохраните.');
                if (codeInput) codeInput.focus();
            } catch (e) {
                toastNetworkError();
                sendBtn.disabled = false;
                sendBtn.textContent = 'Отправить код';
            }
        });

        // Сменил адрес — прежний код больше не годится, требуем новый
        emailInput.addEventListener('input', function () {
            reqIdInput.value = '';
            saveBtn.disabled = true;
            if (codeGroup) codeGroup.style.display = 'none';
            sendBtn.textContent = 'Отправить код';
        });
    })();

    // Удаление аккаунта — нативная форма с паролем, подтверждаем намерение
    const deleteForm = document.getElementById('delete-account-form');
    if (deleteForm) {
        // Диалог асинхронный, поэтому сабмит гасим всегда и отправляем форму
        // сами после подтверждения.
        deleteForm.addEventListener('submit', async function (e) {
            if (deleteForm.dataset.confirmed === '1') return;
            e.preventDefault();
            const ok = await confirmDialog({
                title: 'Деактивировать аккаунт?',
                message: 'Вы выйдете из системы. Восстановление — через поддержку.',
                confirmText: 'Деактивировать',
                danger: true,
            });
            if (!ok) return;
            deleteForm.dataset.confirmed = '1';
            deleteForm.submit();
        });
    }
});