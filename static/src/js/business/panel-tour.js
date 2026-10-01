// static/src/js/business/panel-tour.js
//
// Знакомство с панелью (решение 0008). Сам тур работает БЕЗ скрипта: полосу
// рисует сервер, «Назад / Дальше / Выйти» — обычные ссылки, шаг лежит в базе.
// Здесь только то, чего разметкой не сделать:
//
//   1) подсвеченную кнопку раздела нужно показать. На телефоне лента вкладок
//      прокручивается вбок, и раздел шага легко оказывается за краем экрана —
//      человек читает «загляните в Услуги» и не видит, куда нажимать;
//   2) под полосу надо освободить ровно столько места, сколько она занимает:
//      высота зависит от длины реплики (у «Услуг» она вдвое длиннее, чем у
//      «Клиентов»), и угаданное в CSS число оказывалось то мало — и полоса
//      накрывала кнопку сохранения, — то много;
//   3) приглашение «продолжить знакомство» должно убираться на этот заход.
//      Отказ «сейчас не надо» — про текущую вкладку браузера, а не про
//      человека, поэтому он в sessionStorage, а не в базе (тем же приёмом
//      закрывается предупреждение о публикации, см. dashboard.js). Шаг тура в
//      хранилище браузера НЕ попадает: с телефона и с ноутбука тур должен
//      продолжаться с одного места (решение 0008, п. 6).

(function () {
    // Приватный режим может запрещать хранилище — тогда просто не запоминаем.
    function store() {
        try {
            sessionStorage.getItem('x');
            return sessionStorage;
        } catch (e) {
            return null;
        }
    }

    function revealTourTab() {
        const bar = document.getElementById('panelTour');
        if (!bar) return;
        const item = document.querySelector('.tab-item.is-tour');
        if (!item) return;   // шаг пролога и финала ни на какой раздел не показывает
        const nav = item.closest('.tab-nav');
        if (!nav) return;
        if (nav.scrollWidth <= nav.clientWidth) return;   // лента влезла целиком

        // Двигаем саму ленту, а не зовём scrollIntoView: он прокручивает всех
        // прокручиваемых предков, то есть заодно и страницу. Позицию считаем
        // по рамкам, а не по offsetLeft: у .tab-nav нет position, offsetParent
        // у плитки — body, и offsetLeft отсчитывается не от ленты.
        const navBox = nav.getBoundingClientRect();
        const itemBox = item.getBoundingClientRect();
        const left = nav.scrollLeft + (itemBox.left - navBox.left)
            - (nav.clientWidth - itemBox.width) / 2;
        // Прокрутка мгновенная и намеренно: плавную обрывает любой пересчёт
        // раскладки, а он здесь гарантирован — reserveSpace() меняет отступ
        // страницы в том же кадре.
        nav.scrollLeft = Math.max(0, left);
    }

    // Запас места под полосу — по её настоящей высоте. Пересчитываем на
    // поворот экрана и на изменение размера окна: от ширины зависит, во
    // сколько строк ляжет реплика.
    function reserveSpace() {
        const bar = document.getElementById('panelTour');
        if (!bar) return;
        const height = Math.ceil(bar.getBoundingClientRect().height);
        if (height > 0) {
            document.body.style.setProperty('--panel-tour-space', height + 'px');
        }
    }

    function watchSize() {
        const bar = document.getElementById('panelTour');
        if (!bar) return;
        if (typeof ResizeObserver === 'function') {
            // Высота меняется не только с окном: шрифт может догрузиться позже,
            // и реплика переложится уже после DOMContentLoaded.
            new ResizeObserver(reserveSpace).observe(bar);
            return;
        }
        window.addEventListener('resize', reserveSpace);
        window.addEventListener('orientationchange', reserveSpace);
    }

    function bindInvite() {
        const invite = document.getElementById('panelTourInvite');
        if (!invite) return;
        const s = store();
        const key = 'panelTourInviteHidden:' + (invite.dataset.salonId || '');
        if (s && s.getItem(key) === '1') {
            invite.remove();
            return;
        }
        const close = document.getElementById('panelTourInviteClose');
        if (!close) return;
        close.addEventListener('click', function () {
            invite.remove();
            try { if (s) s.setItem(key, '1'); } catch (e) { /* вернётся, не страшно */ }
        });
    }

    function init() {
        reserveSpace();
        watchSize();
        bindInvite();
        // После reserveSpace: он меняет отступ страницы, и позицию плитки надо
        // считать по уже пересчитанной раскладке.
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(revealTourTab);
        } else {
            revealTourTab();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
