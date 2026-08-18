// static/src/js/salons.js
//
// Фронт-этап фильтров /salons: серверная фильтрация теперь без перезагрузки.
// Перехватываем GET-форму #salonsFilterForm и её контролы, тянем фрагмент
// (/salons?...&partial=1), подменяем сетку #salons-list, правим URL через
// pushState. Без JS форма продолжает работать на полной перезагрузке
// (прогрессивное улучшение — этот слой лишь ускоряет UX).
import { toastNetworkError } from './ui-feedback.js';

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('salonsFilterForm');
    const grid = document.getElementById('salons-list');
    const searchInput = document.getElementById('searchInput');
    if (!form || !grid) return;

    // Инлайновые onchange у контролов делают this.form.submit() — это путь для
    // работы без JS. Программный submit() НЕ поднимает событие 'submit', поэтому
    // перехватчик ниже его не видел: город, рейтинг, «только с акциями» и
    // сортировка уходили в полную перезагрузку мимо всего AJAX-слоя. Поднимаем
    // флаг — инлайновые обработчики видят его и уступают место обработке ниже.
    form.dataset.ajax = '1';

    const DATA = window.salonFilters || { pageSize: 20, categoriesByCity: {} };
    const citySelect = document.getElementById('citySelect');
    const sortSelect = document.getElementById('sortSelect');
    const categoryOptions = Array.from(document.querySelectorAll('.category-option'));
    const categoryLabel = document.getElementById('categoryDropdownLabel');

    let userCoords = null;   // {lat, lon} после согласия на геолокацию
    let loading = false;

    // Селекты обёрнуты в Choices — присвоения .value видимую часть не двигают.
    function setSelectValue(el, value) {
        if (!el) return;
        el.value = value;
        if (el._choices) el._choices.setChoiceByValue(value);
    }

    // --- Параметры из формы (без partial/offset/координат) ---
    function paramsFromForm() {
        const sp = new URLSearchParams();
        for (const [k, v] of new FormData(form).entries()) {
            if (v === '' && k !== 'q') continue;
            sp.append(k, v);
        }
        const q = (searchInput ? searchInput.value : '').trim();
        sp.delete('q');
        if (q) sp.set('q', q);
        return sp;
    }

    async function fetchGrid(sp, extra) {
        const url = new URLSearchParams(sp);
        url.set('partial', '1');
        if (extra) for (const [k, v] of Object.entries(extra)) url.set(k, v);
        if (url.get('sort') === 'distance' && userCoords) {
            url.set('lat', userCoords.lat);
            url.set('lon', userCoords.lon);
        }
        const resp = await fetch('/salons?' + url.toString(), { headers: { 'X-Requested-With': 'fetch' } });
        return await resp.text();
    }

    function setLoading(on) {
        loading = on;
        grid.style.opacity = on ? '0.5' : '';
        grid.style.pointerEvents = on ? 'none' : '';
    }

    // --- Применить фильтры: подменить сетку + история ---
    async function applyFilters(historyMode) {
        if (loading) return;
        const sp = paramsFromForm();
        setLoading(true);
        try {
            grid.innerHTML = await fetchGrid(sp);
            markFavorites();
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
        if (historyMode !== 'none') {
            const qs = sp.toString();
            const url = '/salons' + (qs ? '?' + qs : '');
            if (historyMode === 'replace') history.replaceState({ salons: true }, '', url);
            else history.pushState({ salons: true }, '', url);
        }
    }

    // --- Показать ещё: догрузить и дописать ---
    async function loadMore() {
        if (loading) return;
        const count = grid.querySelectorAll('.salon-card').length;
        setLoading(true);
        try {
            const tmp = document.createElement('div');
            tmp.innerHTML = await fetchGrid(paramsFromForm(), { offset: count });
            const more = grid.querySelector('.salons-more');
            tmp.querySelectorAll('.salon-card').forEach(c => grid.insertBefore(c, more));
            const newMore = tmp.querySelector('.salons-more');
            if (more) { newMore ? more.replaceWith(newMore) : more.remove(); }
            markFavorites();
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    // --- Умный список категорий по выбранному городу ---
    function applyCityCategoryFilter() {
        const city = citySelect ? citySelect.value : '';
        const map = DATA.categoriesByCity || {};
        const avail = city ? (map[city] || []) : (map[''] || []);
        categoryOptions.forEach(opt => {
            const ok = avail.includes(opt.dataset.slug);
            opt.hidden = !ok;
            if (!ok) {
                const cb = opt.querySelector('input[type="checkbox"]');
                if (cb && cb.checked) cb.checked = false;
            }
        });
        updateCategoryLabel();
    }

    // Класс .active проставляет сервер, а при AJAX форма не перерисовывается —
    // подсветка застревала на старом чипе, и «выбранными» выглядели сразу два.
    // (CSS-правило :has(input:checked) закрывает это лишь в браузерах с :has.)
    function syncRatingChips() {
        document.querySelectorAll('.filter-chip').forEach(chip => {
            const input = chip.querySelector('input');
            chip.classList.toggle('active', !!input && input.checked);
        });
    }

    function updateCategoryLabel() {
        if (!categoryLabel) return;
        const n = form.querySelectorAll('input[name="category"]:checked').length;
        categoryLabel.textContent = n ? `Категории (${n})` : 'Категории';
    }

    // --- Геолокация для «Рядом со мной» ---
    function requestGeoThenApply() {
        if (userCoords) { applyFilters(); return; }
        if (!navigator.geolocation) {
            alert('Ваш браузер не поддерживает геолокацию.');
            setSelectValue(sortSelect, '');
            return;
        }
        navigator.geolocation.getCurrentPosition(
            function (pos) {
                // округляем до ~квартала (2 знака) — в URL координаты не пишем
                userCoords = { lat: pos.coords.latitude.toFixed(2), lon: pos.coords.longitude.toFixed(2) };
                applyFilters();
            },
            function () {
                alert('Не удалось определить местоположение — разрешите доступ к геолокации.');
                setSelectValue(sortSelect, '');
                applyFilters();
            }
        );
    }

    // --- Слушатели ---
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        applyFilters();  // Enter в поиске / «Применить» категорий
    });

    form.addEventListener('change', function (e) {
        const el = e.target;
        if (el.name === 'category') { updateCategoryLabel(); return; }  // ждём «Применить»
        if (el.name === 'min_rating') syncRatingChips();
        if (el.name === 'city') applyCityCategoryFilter();
        if (el.name === 'sort' && el.value === 'distance') { requestGeoThenApply(); return; }
        applyFilters();
    });

    if (searchInput) {
        let t = null;
        searchInput.addEventListener('input', function () {
            clearTimeout(t);
            t = setTimeout(() => applyFilters('replace'), 300);
        });
    }

    grid.addEventListener('click', function (e) {
        const more = e.target.closest('.salons-more-btn');
        if (more) { e.preventDefault(); loadMore(); }
    });

    window.addEventListener('popstate', function () {
        const sp = new URLSearchParams(location.search);
        setLoading(true);
        fetchGrid(sp).then(h => { grid.innerHTML = h; markFavorites(); }).finally(() => setLoading(false));
    });

    applyCityCategoryFilter();  // подрезаем категории под текущий город при загрузке
    syncRatingChips();

    // === Дропдаун категорий: открыть/закрыть ===
    const categoryDropdown = document.getElementById('categoryDropdown');
    const categoryDropdownBtn = document.getElementById('categoryDropdownBtn');
    const categoryDropdownPanel = document.getElementById('categoryDropdownPanel');
    if (categoryDropdown && categoryDropdownBtn && categoryDropdownPanel) {
        categoryDropdownBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            const isOpen = categoryDropdown.classList.toggle('open');
            categoryDropdownPanel.hidden = !isOpen;
        });
        document.addEventListener('click', function (e) {
            if (!categoryDropdown.contains(e.target)) {
                categoryDropdown.classList.remove('open');
                categoryDropdownPanel.hidden = true;
            }
        });
    }

    // === Избранное (делегирование — карточки пересоздаются при подмене) ===
    grid.addEventListener('click', async function (e) {
        const btn = e.target.closest('.favorite-btn');
        if (!btn) return;
        e.preventDefault();
        const type = btn.dataset.type, id = btn.dataset.id;
        const isLiked = btn.classList.contains('liked');
        try {
            const response = await fetch(`/api/v1/favorites/toggle-${type}/${id}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
            });
            if (response.redirected && response.url.includes('/login')) {
                window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
            } else if (response.ok) {
                btn.classList.toggle('liked', !isLiked);
                btn.querySelector('.heart-icon').innerHTML = isLiked ? btn.dataset.iconHeart : btn.dataset.iconHeartFilled;
            } else {
                alert('Не удалось изменить избранное. Попробуйте позже.');
            }
        } catch (err) { console.error(err); toastNetworkError(); }
    });

    async function markFavorites() {
        try {
            const response = await fetch('/api/v1/favorites/my');
            if (!response.ok) return;
            const data = await response.json();
            grid.querySelectorAll('.favorite-btn[data-type="salon"]').forEach(btn => {
                const liked = data.salon_ids.includes(parseInt(btn.dataset.id));
                btn.classList.toggle('liked', liked);
                btn.querySelector('.heart-icon').innerHTML = liked ? btn.dataset.iconHeartFilled : btn.dataset.iconHeart;
            });
        } catch (e) { /* не авторизован */ }
    }
    markFavorites();
});
