// static/src/js/card-transition.js — переход «карточка каталога → страница салона».
//
// Это ЕДИНСТВЕННОЕ авторское движение клиентского мира (docs/design.md: один
// продуманный момент на поверхность, и в клиентском мире он потрачен сюда).
// Больше ничего на этих страницах не «появляется»: анимаций по прокрутке нет.
//
// Механика — переходы между документами (View Transitions). Браузер сам
// переносит монограмму и имя из карточки в шапку открывшейся страницы, если у
// элементов по обе стороны одно и то же view-transition-name. Нам остаётся
// назвать ИМЕННО ту карточку, по которой нажали: имя обязано быть уникальным в
// документе, а карточек на экране двадцать.
//
// Правило навигации объявлено в CSS (@view-transition внутри
// prefers-reduced-motion: no-preference), поэтому в браузере без поддержки или
// у человека с выключенным движением здесь просто ничего не происходит —
// переход остаётся обычным.
const MARK = 'salon-mark';
const TITLE = 'salon-title';

function supported() {
    return typeof CSS !== 'undefined' && CSS.supports && CSS.supports('view-transition-name', 'x');
}

function clear() {
    document.querySelectorAll('[data-vt]').forEach(function (el) {
        el.style.viewTransitionName = '';
        el.removeAttribute('data-vt');
    });
}

function tag(el, name) {
    if (!el) return;
    el.style.viewTransitionName = name;
    el.setAttribute('data-vt', name);
}

if (supported()) {
    document.addEventListener('click', function (ev) {
        const link = ev.target.closest('[data-salon-link]');
        if (!link) return;
        // Новая вкладка и клик с модификатором — не переход этой страницы.
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
        clear();
        const card = link.closest('.r-salon');
        if (!card) return;
        tag(card.querySelector('.r-mark'), MARK);
        tag(card.querySelector('.r-salon__name'), TITLE);
    });

    // Назад из салона в каталог: имена надо снять, иначе следующая карточка
    // получит второе такое же имя, и браузер откажется от перехода вовсе.
    window.addEventListener('pagereveal', clear);
    window.addEventListener('popstate', clear);
}
