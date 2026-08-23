// static/src/js/password-toggle.js
// Кнопка-глаз у всех полей пароля на сайте (вход/регистрация/смена пароля/
// удаление аккаунта) — показать/скрыть введённый текст. Один общий модуль
// вместо правки разметки каждой страницы по отдельности.
(function () {
    const EYE_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>';
    const EYE_OFF = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-7 0-10-7-10-7a18.53 18.53 0 0 1 4.22-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 7 10 7a18.53 18.53 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

    document.querySelectorAll('input[type="password"]').forEach(function (input) {
        if (input.closest('.password-field-wrapper')) return; // уже обёрнут

        const wrapper = document.createElement('div');
        wrapper.className = 'password-field-wrapper';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'password-toggle-btn';
        btn.setAttribute('aria-label', 'Показать пароль');
        btn.innerHTML = EYE_OPEN;
        wrapper.appendChild(btn);

        btn.addEventListener('click', function () {
            const showing = input.type === 'text';
            input.type = showing ? 'password' : 'text';
            btn.innerHTML = showing ? EYE_OPEN : EYE_OFF;
            btn.setAttribute('aria-label', showing ? 'Показать пароль' : 'Скрыть пароль');
        });
    });
})();
