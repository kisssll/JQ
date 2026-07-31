// static/src/js/salons.js

document.addEventListener('DOMContentLoaded', function() {
    // Проверяем, что мы на странице салонов
    if (!document.getElementById('searchInput')) {
        return;
    }

    // === Поиск + фильтры + сортировка ===
    const searchInput = document.getElementById('searchInput');
    const grid = document.getElementById('salons-list');
    const cards = Array.from(document.querySelectorAll('.salon-card'));
    const emptyState = document.getElementById('salonsEmptyState');
    const sortSelect = document.getElementById('sortSelect');

    const filterState = { query: '', category: '', minRating: 0, promoOnly: false, sort: 'rating' };
    let userCoords = null; // {lat, lon} — заполняется после согласия на геолокацию

    function applyFilters() {
        let anyVisible = false;
        cards.forEach(card => {
            const haystack = card.dataset.search || '';
            const categories = (card.dataset.categories || '').split(' ');
            const rating = parseFloat(card.dataset.rating) || 0;
            const hasPromo = card.dataset.hasPromo === '1';

            const matches = (
                (!filterState.query || haystack.includes(filterState.query)) &&
                (!filterState.category || categories.includes(filterState.category)) &&
                (rating >= filterState.minRating) &&
                (!filterState.promoOnly || hasPromo)
            );
            card.style.display = matches ? '' : 'none';
            if (matches) anyVisible = true;
        });
        if (emptyState) emptyState.style.display = anyVisible ? 'none' : '';
    }

    function haversineKm(lat1, lon1, lat2, lon2) {
        const R = 6371;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    function applySort() {
        if (!grid) return;
        const sorted = [...cards].sort((a, b) => {
            if (filterState.sort === 'reviews') {
                return (parseInt(b.dataset.reviews) || 0) - (parseInt(a.dataset.reviews) || 0);
            }
            if (filterState.sort === 'distance' && userCoords) {
                const da = haversineKm(userCoords.lat, userCoords.lon, parseFloat(a.dataset.lat), parseFloat(a.dataset.lon));
                const db = haversineKm(userCoords.lat, userCoords.lon, parseFloat(b.dataset.lat), parseFloat(b.dataset.lon));
                return da - db;
            }
            return (parseFloat(b.dataset.rating) || 0) - (parseFloat(a.dataset.rating) || 0);
        });
        sorted.forEach(card => grid.appendChild(card));
    }

    function requestGeolocationAndSort() {
        if (!navigator.geolocation) {
            alert('Ваш браузер не поддерживает геолокацию.');
            if (sortSelect) sortSelect.value = 'rating';
            filterState.sort = 'rating';
            return;
        }
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                userCoords = { lat: pos.coords.latitude, lon: pos.coords.longitude };
                applySort();
            },
            function() {
                alert('Не удалось определить местоположение — разрешите доступ к геолокации в браузере.');
                if (sortSelect) sortSelect.value = 'rating';
                filterState.sort = 'rating';
            }
        );
    }

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            filterState.query = this.value.toLowerCase().trim();
            applyFilters();
        });
    }

    document.querySelectorAll('.filter-categories .filter-chip[data-category]').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.filter-categories .filter-chip').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            filterState.category = this.dataset.category;
            applyFilters();
        });
    });

    document.querySelectorAll('#ratingFilterGroup .filter-chip').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('#ratingFilterGroup .filter-chip').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            filterState.minRating = parseFloat(this.dataset.minRating) || 0;
            applyFilters();
        });
    });

    const promoToggle = document.getElementById('promoOnlyToggle');
    if (promoToggle) {
        promoToggle.addEventListener('change', function() {
            filterState.promoOnly = this.checked;
            applyFilters();
        });
    }

    if (sortSelect) {
        sortSelect.addEventListener('change', function() {
            filterState.sort = this.value;
            if (filterState.sort === 'distance' && !userCoords) {
                requestGeolocationAndSort();
            } else {
                applySort();
            }
        });
    }

    // === Избранное ===
    const favButtons = document.querySelectorAll('.favorite-btn');

    favButtons.forEach(btn => {
        btn.addEventListener('click', async function(e) {
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

                if (response.redirected) {
                    // fetch сам сходил по редиректу на /login (не авторизован) —
                    // response.ok при этом true (страница логина отдаёт 200),
                    // поэтому проверяем ДО response.ok, иначе выглядело бы
                    // как успешное добавление в избранное.
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

    // Инициализация состояния избранного
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
            // пользователь не авторизован – ничего не делаем
        }
    }

    loadFavorites();
});