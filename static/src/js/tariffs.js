// static/src/js/tariffs.js
// Страница «Тарифы и информация» — переключение под-вкладок (Тарифы/
// Документы/Инструкции) на клиенте, без перезагрузки.
(function () {
    const root = document.getElementById('tariffsTabs');
    if (!root) return;

    const tabs = root.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('#tab-plans, #tab-documents, #tab-guides');

    tabs.forEach(btn => {
        btn.addEventListener('click', function () {
            tabs.forEach(b => b.classList.toggle('active', b === this));
            contents.forEach(c => c.classList.toggle('active', c.id === 'tab-' + this.dataset.tab));
        });
    });
})();
