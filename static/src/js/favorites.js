// static/src/js/favorites.js
import { confirmDialog, toastNetworkError } from './ui-feedback.js';

document.addEventListener('DOMContentLoaded', function () {
    // Проверяем, что мы на странице избранного
    if (!document.querySelector('.favorites-main')) {
        return;
    }

    const removeButtons = document.querySelectorAll('.fav-remove-btn');

    removeButtons.forEach(btn => {
        btn.addEventListener('click', async function (e) {
            e.preventDefault();
            const type = this.dataset.type;
            const id = this.dataset.id;
            const card = this.closest('.fav-card');

            if (!await confirmDialog({ title: `Убрать ${type === 'salon' ? 'салон' : 'мастера'} из избранного?`, confirmText: 'Убрать', danger: true })) {
                return;
            }

            try {
                const response = await fetch(`/api/v1/favorites/toggle-${type}/${id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });

                if (response.redirected && response.url.includes('/login')) {
                    window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
                } else if (response.ok) {
                    if (card) card.remove();
                    if (!document.querySelector('.fav-card')) location.reload();
                } else {
                    alert('Не удалось удалить из избранного. Попробуйте позже.');
                }
            } catch (err) {
                console.error(err);
                toastNetworkError();
            }
        });
    });
});