// static/src/js/favorites.js — «Избранное».
//
// Один орган управления: сердечко на карточке. Оно же добавляло — оно же
// убирает, и приходит с сервера уже закрашенным (ui.salon_card, favorite_on),
// поэтому вспышки пустых сердечек при загрузке нет и дорисовывать их
// запросом «что у меня в избранном» не нужно.
//
// Подтверждение — лист снизу: карточку убирают одним касанием, и вернуть её
// можно только тем же сердечком в каталоге, то есть сначала салон надо снова
// найти.
import { open as openSheet, close as closeSheet } from './sheet.js';
import { toastError, toastNetworkError } from './ui-feedback.js';

document.addEventListener('DOMContentLoaded', function () {
    const page = document.querySelector('.favorites-main');
    if (!page) return;

    const sheet = document.getElementById('favSheet');
    const confirmBtn = document.getElementById('favConfirm');
    const what = document.getElementById('favWhat');

    let pending = null; // { type, id, card }

    page.addEventListener('click', function (ev) {
        const btn = ev.target.closest('.favorite-btn');
        if (!btn || !sheet) return;
        ev.preventDefault();
        const card = btn.closest('.r-salon');
        const name = card ? (card.querySelector('.r-salon__name') || {}).textContent : '';
        pending = { type: btn.dataset.type, id: btn.dataset.id, card: card };
        if (what) what.textContent = (name || '').trim();
        openSheet(sheet, btn);
    });

    if (!confirmBtn) return;

    confirmBtn.addEventListener('click', async function () {
        if (!pending) return;
        const { type, id, card } = pending;
        confirmBtn.classList.add('is-loading');
        confirmBtn.disabled = true;
        try {
            const res = await fetch('/api/v1/favorites/toggle-' + type + '/' + id, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (res.redirected && res.url.includes('/login')) {
                window.location.href = '/login?redirect='
                    + encodeURIComponent(window.location.pathname);
                return;
            }
            if (!res.ok) {
                toastError('Не удалось убрать из избранного');
                return;
            }
            closeSheet(sheet);
            const group = card ? card.closest('.fav-group') : null;
            if (card) card.remove();
            // Убрали последний салон — заголовок «Салоны» над пустотой остался
            // бы висеть разделом без содержимого.
            if (group && !group.querySelector('.r-salon')) group.remove();
            pending = null;
            // Убрали последнюю карточку — на экране должно остаться полезное
            // пустое состояние со ссылкой в каталог, а не пустой заголовок
            // «Салоны». Его рисует сервер, поэтому перезагружаем.
            if (!page.querySelector('.r-salon')) {
                window.location.href = '/favorites?notice=removed';
            }
        } catch (err) {
            toastNetworkError();
        } finally {
            confirmBtn.classList.remove('is-loading');
            confirmBtn.disabled = false;
        }
    });
});
