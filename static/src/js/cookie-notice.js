// static/src/js/cookie-notice.js
//
// Уведомление об использовании cookie. Политика обработки ПДн прямо
// перечисляет cookie и IP среди собираемых данных, а предупреждения на сайте
// не было. Это именно уведомление, а не запрос разрешения: технические cookie
// нужны для входа и работы записи, отключать их нечего.
//
// Выбор храним в localStorage, а не в cookie: незачем заводить ещё один
// идентификатор ради того, чтобы спросить про идентификаторы.

const STORAGE_KEY = 'cookieNoticeAccepted';

document.addEventListener('DOMContentLoaded', function () {
    let accepted = null;
    try {
        accepted = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
        // Приватный режим может запрещать хранилище — тогда просто не мешаем
        // человеку и не показываем плашку на каждой странице.
        return;
    }
    if (accepted === '1') return;

    const box = document.createElement('div');
    box.className = 'cookie-notice';
    box.setAttribute('role', 'region');
    box.setAttribute('aria-label', 'Уведомление об использовании cookie');

    const text = document.createElement('p');
    text.className = 'cookie-notice-text';
    text.innerHTML = 'Мы используем cookie, чтобы сайт работал: помним вход и ваш выбор. ' +
        'Подробнее — в <a href="/cookies">Политике использования файлов cookie</a>.';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cookie-notice-btn';
    btn.textContent = 'Понятно';
    btn.addEventListener('click', function () {
        try {
            localStorage.setItem(STORAGE_KEY, '1');
        } catch (e) { /* не смогли запомнить — плашка вернётся, это не страшно */ }
        box.remove();
    });

    box.append(text, btn);
    document.body.appendChild(box);
});
