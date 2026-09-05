// static/src/js/cookie-notice.js
//
// Баннер про cookie и загрузка Яндекс.Метрики.
//
// Раньше это было чистое уведомление с одной кнопкой «Понятно»: технические
// cookie нужны для входа и записи, отключать их нечего, спрашивать не о чем.
// С появлением аналитики вопрос меняется — п. 2.3 Политики использования
// файлов cookie разрешает аналитические cookie ТОЛЬКО после согласия.
//
// Поэтому баннеров два, и какой показать, решает наличие счётчика:
//   счётчика нет  → прежнее уведомление, одна кнопка, согласие ни при чём;
//   счётчик есть  → выбор из двух ответов, Метрика грузится лишь при «Принять».
//
// Выбор храним в localStorage, а не в cookie: незачем заводить ещё один
// идентификатор ради того, чтобы спросить про идентификаторы.

const CONSENT_KEY = 'cookieConsent';
// Ключ старого уведомления. Значение '1' означало «баннер закрыт», а не
// согласие на аналитику — тогда спрашивали о другом. Как согласие он НЕ
// засчитывается: когда появится счётчик, вопрос будет задан заново.
const NOTICE_KEY = 'cookieNoticeAccepted';

const ACCEPT_ALL = 'all';
const NECESSARY_ONLY = 'necessary';

const NOTICE_TEXT = 'Мы используем cookie, чтобы сайт работал: помним вход и ваш выбор. ' +
    'Подробнее — в <a href="/cookies">Политике использования файлов cookie</a>.';
const CONSENT_TEXT = 'Мы используем cookie, чтобы сайт работал: помним вход и ваш выбор. ' +
    'С вашего согласия — ещё и для статистики посещений. ' +
    'Подробнее — в <a href="/cookies">Политике использования файлов cookie</a>.';

// Приватный режим может запрещать хранилище. Тогда мы не сможем запомнить
// ответ — и не станем показывать плашку на каждой странице.
function storage() {
    try {
        localStorage.getItem(CONSENT_KEY);
        return localStorage;
    } catch (e) {
        return null;
    }
}

function readConsent(store) {
    const v = store.getItem(CONSENT_KEY);
    return v === ACCEPT_ALL || v === NECESSARY_ONLY ? v : null;
}

function counterId() {
    const meta = document.querySelector('meta[name="ym-counter"]');
    const id = meta && meta.getAttribute('content');
    return /^[0-9]+$/.test(id || '') ? id : null;
}

// Официальный сниппет Метрики, вызывается только после согласия. Вебвизор
// намеренно выключен: он пишет сессию целиком, а для ответа на вопрос «сколько
// было трафика» это лишние персональные данные.
function loadMetrika(id) {
    if (window.ym) return;
    window.ym = function () {
        (window.ym.a = window.ym.a || []).push(arguments);
    };
    window.ym.a = [];
    window.ym.l = +new Date();

    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://mc.yandex.ru/metrika/tag.js';
    document.head.appendChild(s);

    window.ym(id, 'init', {
        clickmap: true,
        trackLinks: true,
        accurateTrackBounce: true,
        webvisor: false,
    });
}

function render(text, buttons) {
    const box = document.createElement('div');
    box.className = 'cookie-notice';
    box.setAttribute('role', 'region');
    box.setAttribute('aria-label', 'Уведомление об использовании cookie');

    const p = document.createElement('p');
    p.className = 'cookie-notice-text';
    p.innerHTML = text;

    const actions = document.createElement('div');
    actions.className = 'cookie-notice-actions';
    buttons.forEach(function (b) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'cookie-notice-btn' + (b.secondary ? ' cookie-notice-btn-secondary' : '');
        btn.textContent = b.label;
        btn.addEventListener('click', function () {
            b.onClick();
            box.remove();
        });
        actions.appendChild(btn);
    });

    box.append(p, actions);
    document.body.appendChild(box);
}

document.addEventListener('DOMContentLoaded', function () {
    const store = storage();
    if (!store) return;

    const id = counterId();

    if (!id) {
        // Счётчика нет — аналитических cookie тоже, спрашивать не о чем.
        // Прежнее уведомление; закрытый ранее баннер не показываем снова.
        if (readConsent(store) || store.getItem(NOTICE_KEY) === '1') return;
        render(NOTICE_TEXT, [{
            label: 'Понятно',
            onClick: function () {
                try { store.setItem(NOTICE_KEY, '1'); } catch (e) { /* вернётся, не страшно */ }
            },
        }]);
        return;
    }

    // Счётчик есть — нужен настоящий выбор.
    const choice = readConsent(store);
    if (choice) {
        if (choice === ACCEPT_ALL) loadMetrika(id);
        return;
    }

    function answer(value) {
        try {
            store.setItem(CONSENT_KEY, value);
            store.removeItem(NOTICE_KEY);
        } catch (e) { /* не смогли запомнить — баннер вернётся, это не страшно */ }
        if (value === ACCEPT_ALL) loadMetrika(id);
    }

    render(CONSENT_TEXT, [
        { label: 'Только необходимые', secondary: true, onClick: function () { answer(NECESSARY_ONLY); } },
        { label: 'Принять', onClick: function () { answer(ACCEPT_ALL); } },
    ]);
});
