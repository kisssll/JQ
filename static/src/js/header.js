// static/src/js/header.js — бургер шапки (до 900px) и этикетка-вход в аккаунт.
import { enter, exit } from './motion.js';

document.addEventListener('DOMContentLoaded', function () {
    const burger = document.getElementById('header-burger');
    const nav = document.getElementById('header-nav');
    const tag = document.getElementById('acct-tag');
    const tagBtn = document.getElementById('acct-tag-btn');
    const menu = document.getElementById('acct-menu');

    function setNav(open) {
        if (!burger || !nav) return;
        nav.classList.toggle('open', open);
        burger.setAttribute('aria-expanded', String(open));
        burger.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
        if (open) enter(nav, { y: -6 });
    }

    // Счётчик, а не флаг: быстрый повторный клик не должен дать закрывающей
    // анимации спрятать уже снова открытое меню (прерываемость).
    let menuTurn = 0;
    function setMenu(open) {
        if (!tag || !tagBtn || !menu) return;
        const turn = ++menuTurn;
        tagBtn.setAttribute('aria-expanded', String(open));
        tag.classList.toggle('is-open', open);
        if (open) {
            menu.hidden = false;
            enter(menu, { y: -6 });
        } else {
            exit(menu, { y: -6 }).finished.then(function () {
                if (turn === menuTurn) menu.hidden = true;
            });
        }
    }

    const menuOpen = () => !!tagBtn && tagBtn.getAttribute('aria-expanded') === 'true';
    const navOpen = () => !!nav && nav.classList.contains('open');

    if (burger) {
        burger.addEventListener('click', function () {
            setNav(!navOpen());
        });
    }
    if (tagBtn) {
        tagBtn.addEventListener('click', function () {
            setMenu(!menuOpen());
        });
    }

    document.addEventListener('click', function (e) {
        if (menuOpen() && tag && !tag.contains(e.target)) setMenu(false);
        if (navOpen() && !nav.contains(e.target) && !burger.contains(e.target)) setNav(false);
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (menuOpen()) {
            setMenu(false);
            if (tagBtn) tagBtn.focus();
        }
        if (navOpen()) {
            setNav(false);
            if (burger) burger.focus();
        }
    });

    window.addEventListener('resize', function () {
        if (window.innerWidth > 900 && navOpen()) setNav(false);
    });
});
