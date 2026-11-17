// Search and city filters for /sport: server-rendered results remain usable
// without JavaScript; this only replaces full reloads with grid updates.
document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('gymsFilterForm');
    const grid = document.getElementById('gyms-list');
    const searchInput = document.getElementById('gymSearchInput');
    const citySelect = document.getElementById('gymCitySelect');
    if (!form || !grid) return;

    form.dataset.ajax = '1';
    let activeRequest = 0;

    function paramsFromForm() {
        const params = new URLSearchParams(new FormData(form));
        const q = searchInput ? searchInput.value.trim() : '';
        params.delete('q');
        if (q) params.set('q', q);
        return params;
    }

    function setLoading(loading) {
        grid.style.opacity = loading ? '0.5' : '';
        grid.style.pointerEvents = loading ? 'none' : '';
    }

    async function fetchGrid(params, offset) {
        const query = new URLSearchParams(params);
        query.set('partial', '1');
        if (offset) query.set('offset', offset);
        const response = await fetch('/sport?' + query.toString(), {
            headers: { 'X-Requested-With': 'fetch' },
        });
        if (!response.ok) throw new Error(`Gym catalog request failed: ${response.status}`);
        return await response.text();
    }

    async function applyFilters(historyMode) {
        const requestId = ++activeRequest;
        const params = paramsFromForm();
        setLoading(true);
        try {
            const markup = await fetchGrid(params);
            if (requestId === activeRequest) grid.innerHTML = markup;
        } catch (error) {
            console.error(error);
        } finally {
            if (requestId === activeRequest) setLoading(false);
        }

        if (historyMode && requestId === activeRequest) {
            const query = params.toString();
            const url = '/sport' + (query ? '?' + query : '');
            if (historyMode === 'replace') history.replaceState({ gyms: true }, '', url);
            else history.pushState({ gyms: true }, '', url);
        }
    }

    async function loadMore() {
        const requestId = ++activeRequest;
        const count = grid.querySelectorAll('.gym-card').length;
        const more = grid.querySelector('.salons-more');
        if (!more) return;
        setLoading(true);
        try {
            const container = document.createElement('div');
            container.innerHTML = await fetchGrid(paramsFromForm(), count);
            if (requestId !== activeRequest) return;
            container.querySelectorAll('.gym-card').forEach(card => grid.insertBefore(card, more));
            const nextMore = container.querySelector('.salons-more');
            if (nextMore) more.replaceWith(nextMore);
            else more.remove();
        } catch (error) {
            console.error(error);
        } finally {
            if (requestId === activeRequest) setLoading(false);
        }
    }

    form.addEventListener('submit', event => {
        event.preventDefault();
        applyFilters('push');
    });
    form.addEventListener('change', event => {
        if (event.target === citySelect) applyFilters('push');
    });
    if (searchInput) {
        let timer = null;
        searchInput.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => applyFilters('replace'), 300);
        });
    }
    grid.addEventListener('click', event => {
        const button = event.target.closest('.salons-more-btn');
        if (button) {
            event.preventDefault();
            loadMore();
        }
    });
    window.addEventListener('popstate', () => {
        const params = new URLSearchParams(location.search);
        if (searchInput) searchInput.value = params.get('q') || '';
        if (citySelect) citySelect.value = params.get('city') || '';
        applyFilters();
    });
});
