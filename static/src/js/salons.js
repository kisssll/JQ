// static/src/js/salons.js
//
// Бэкенд-этап: фильтрация/поиск/сортировка теперь на сервере (GET-форма
// #salonsFilterForm, полная перезагрузка). Клиентского фильтра больше нет.
// Здесь осталось только то, без чего форма не живёт: раскрытие дропдауна
// категорий + избранное. Фронт-этап заменит перезагрузку на AJAX-подмену
// сетки (#salons-list) с pushState и «Показать ещё» без релоада.

document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('searchInput')) return;

    // === Дропдаун категорий: открыть/закрыть (сабмит — по кнопке «Применить») ===
    const categoryDropdown = document.getElementById('categoryDropdown');
    const categoryDropdownBtn = document.getElementById('categoryDropdownBtn');
    const categoryDropdownPanel = document.getElementById('categoryDropdownPanel');

    if (categoryDropdown && categoryDropdownBtn && categoryDropdownPanel) {
        categoryDropdownBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            const isOpen = categoryDropdown.classList.toggle('open');
            categoryDropdownPanel.hidden = !isOpen;
        });
        // Клик вне дропдауна — закрыть (клики внутри панели не закрывают,
        // чтобы можно было отметить несколько категорий).
        document.addEventListener('click', function (e) {
            if (!categoryDropdown.contains(e.target)) {
                categoryDropdown.classList.remove('open');
                categoryDropdownPanel.hidden = true;
            }
        });
    }

    // === Избранное ===
    const favButtons = document.querySelectorAll('.favorite-btn');
    favButtons.forEach(btn => {
        btn.addEventListener('click', async function (e) {
            e.preventDefault();
            const type = this.dataset.type;
            const id = this.dataset.id;
            const isLiked = this.classList.contains('liked');
            const heartIcon = this.dataset.iconHeart;
            const heartFilledIcon = this.dataset.iconHeartFilled;
            try {
                const response = await fetch(`/api/v1/favorites/toggle-${type}/${id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (response.redirected && response.url.includes('/login')) {
                    window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
                } else if (response.ok) {
                    if (isLiked) {
                        this.classList.remove('liked');
                        this.querySelector('.heart-icon').innerHTML = heartIcon;
                    } else {
                        this.classList.add('liked');
                        this.querySelector('.heart-icon').innerHTML = heartFilledIcon;
                    }
                } else {
                    alert('Не удалось изменить избранное. Попробуйте позже.');
                }
            } catch (err) {
                console.error(err);
                alert('Ошибка соединения.');
            }
        });
    });

    async function loadFavorites() {
        try {
            const response = await fetch('/api/v1/favorites/my');
            if (response.ok) {
                const data = await response.json();
                document.querySelectorAll('.favorite-btn[data-type="salon"]').forEach(btn => {
                    const id = parseInt(btn.dataset.id);
                    if (data.salon_ids.includes(id)) {
                        btn.classList.add('liked');
                        btn.querySelector('.heart-icon').innerHTML = btn.dataset.iconHeartFilled;
                    } else {
                        btn.classList.remove('liked');
                        btn.querySelector('.heart-icon').innerHTML = btn.dataset.iconHeart;
                    }
                });
            }
        } catch (e) {
            // не авторизован — ничего не делаем
        }
    }
    loadFavorites();
});
