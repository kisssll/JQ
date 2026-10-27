// static/src/js/tariffs.js
// Страница «Тарифы и информация» — переключение вкладок без перезагрузки.
// Вкладки — настоящие ссылки (?tab=…): без скрипта страница открывает нужную
// вкладку на сервере, со скриптом переключение мгновенное, а адрес
// обновляется, чтобы им можно было поделиться.
(function () {
    const root = document.getElementById('tariffsTabs');
    if (!root) return;

    const tabs = root.querySelectorAll('.tariffs-tab');
    const panes = document.querySelectorAll('.tab-content');

    function select(key, push) {
        tabs.forEach(t => {
            const on = t.dataset.tab === key;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        panes.forEach(p => p.classList.toggle('active', p.id === 'tab-' + key));
        if (push) {
            const url = key === 'plans' ? '/tariffs' : '/tariffs?tab=' + key;
            history.replaceState(null, '', url);
        }
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', function (ev) {
            if (ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
            ev.preventDefault();
            select(this.dataset.tab, true);
        });
    });
})();
