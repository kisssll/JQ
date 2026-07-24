// static/src/js/pwa.js — PWA: регистрация service worker + баннер «Установить приложение».
// SW network-first (не кэширует app-shell) → без риска устаревших версий.

// --- регистрация service worker (scope / — файл отдаётся с корня) ---
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
        navigator.serviceWorker.register('/sw.js').catch(function () { /* не критично */ });
    });
}

// --- баннер «Установить приложение» ---
(function () {
    // уже установлено (запущено как приложение) — не предлагаем
    var standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    if (standalone) return;
    if (localStorage.getItem('pwa_prompt_dismissed')) return;
    var ua = navigator.userAgent;
    var isMobile = /Android|iPhone|iPad|iPod/i.test(ua);
    if (!isMobile) return;            // на десктопе — нативная иконка установки браузера
    var isIOS = /iPhone|iPad|iPod/i.test(ua);

    function injectStyle() {
        if (document.getElementById('pwa-banner-style')) return;
        var s = document.createElement('style');
        s.id = 'pwa-banner-style';
        s.textContent =
            '#pwa-banner{position:fixed;left:.5rem;right:.5rem;bottom:.5rem;z-index:9999;' +
            'background:#fff;border:1px solid #ececec;border-radius:14px;box-shadow:0 6px 28px rgba(20,10,40,.16);' +
            'padding:.8rem .9rem;display:flex;align-items:center;gap:.75rem;font-family:system-ui,-apple-system,sans-serif}' +
            '#pwa-banner img{width:42px;height:42px;border-radius:11px;flex:none}' +
            '#pwa-banner .pwa-txt{flex:1;font-size:.88rem;line-height:1.3;color:#1a1523}' +
            '#pwa-banner .pwa-txt b{display:block;margin-bottom:.1rem}' +
            '#pwa-banner .pwa-txt small{color:#6b6577}' +
            '#pwa-banner .pwa-install{background:#c081b8;color:#fff;border:none;border-radius:10px;' +
            'padding:.55rem .95rem;font-weight:600;font-size:.9rem;cursor:pointer;flex:none}' +
            '#pwa-banner .pwa-close{background:none;border:none;color:#9a93a8;font-size:1.5rem;' +
            'line-height:1;cursor:pointer;padding:0 .2rem;flex:none}' +
            '@media (prefers-color-scheme:dark){#pwa-banner{background:#1b1725;border-color:#2a2438}' +
            '#pwa-banner .pwa-txt{color:#ece9f4}#pwa-banner .pwa-txt small{color:#9a93a8}}';
        document.head.appendChild(s);
    }

    function showBanner(inner, onInstall) {
        injectStyle();
        var bar = document.createElement('div');
        bar.id = 'pwa-banner';
        bar.innerHTML = inner;
        document.body.appendChild(bar);
        bar.querySelector('.pwa-close').addEventListener('click', function () {
            bar.remove();
            localStorage.setItem('pwa_prompt_dismissed', '1');
        });
        var btn = bar.querySelector('.pwa-install');
        if (btn && onInstall) btn.addEventListener('click', onInstall);
    }

    var ICON = '<img src="/static/icons/icon-192.png" alt="Руми">';

    if (isIOS) {
        // iOS Safari: события beforeinstallprompt нет — показываем инструкцию
        showBanner(
            ICON +
            '<div class="pwa-txt"><b>Добавьте Руми на главный экран</b>' +
            '<small>Нажмите ⋮ (три точки) → «Поделиться» → «Показать больше» → «Добавить на экран Домой»</small></div>' +
            '<button class="pwa-close" aria-label="Закрыть">×</button>'
        );
    } else {
        // Android Chrome: ловим системное событие установки
        var deferred = null;
        window.addEventListener('beforeinstallprompt', function (e) {
            e.preventDefault();
            deferred = e;
            showBanner(
                ICON +
                '<div class="pwa-txt"><b>Установите приложение Руми</b>' +
                '<small>Быстрый доступ прямо с главного экрана</small></div>' +
                '<button class="pwa-install">Установить</button>' +
                '<button class="pwa-close" aria-label="Закрыть">×</button>',
                async function () {
                    if (!deferred) return;
                    deferred.prompt();
                    try { await deferred.userChoice; } catch (e2) { /* ignore */ }
                    deferred = null;
                    var b = document.getElementById('pwa-banner');
                    if (b) b.remove();
                    localStorage.setItem('pwa_prompt_dismissed', '1');
                }
            );
        });
    }
})();
