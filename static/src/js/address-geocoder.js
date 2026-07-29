// static/src/js/address-geocoder.js
// Подсказки адреса (Яндекс SuggestView) + мини-карта с меткой для любого
// текстового поля с классом .address-geocode. Подключается только когда на
// сервере задан YANDEX_MAPS_API_KEY (тогда же в HTML появляется скрипт
// ymaps) — без ключа этот файл просто ничего не находит и не работает,
// поле адреса остаётся обычным текстом.
(function () {
    if (typeof ymaps === 'undefined') return;

    ymaps.ready(function () {
        // Статичная карта с меткой (публичная страница салона) — просто
        // показывает точку, без подсказок.
        document.querySelectorAll('.salon-static-map').forEach(function (el) {
            const lat = parseFloat(el.dataset.lat);
            const lon = parseFloat(el.dataset.lon);
            if (isNaN(lat) || isNaN(lon)) return;
            const map = new ymaps.Map(el.id, { center: [lat, lon], zoom: 15, controls: ['zoomControl'] });
            map.geoObjects.add(new ymaps.Placemark([lat, lon], { balloonContent: el.dataset.title || '' }));
            map.behaviors.disable('scrollZoom');
        });

        document.querySelectorAll('.address-geocode').forEach(function (input) {
            const latField = document.getElementById(input.dataset.latField);
            const lonField = document.getElementById(input.dataset.lonField);
            const mapId = input.dataset.mapId;
            const mapEl = mapId ? document.getElementById(mapId) : null;

            let map = null;
            let placemark = null;
            const suggestView = new ymaps.SuggestView(input.id);

            function applyCoords(coords) {
                if (latField) latField.value = coords[0];
                if (lonField) lonField.value = coords[1];
                input.dataset.confirmed = '1';

                if (mapEl) {
                    mapEl.style.display = 'block';
                    if (!map) {
                        map = new ymaps.Map(mapId, { center: coords, zoom: 16, controls: ['zoomControl'] });
                    } else {
                        map.setCenter(coords, 16);
                    }
                    if (placemark) map.geoObjects.remove(placemark);
                    placemark = new ymaps.Placemark(coords);
                    map.geoObjects.add(placemark);
                }
            }

            suggestView.events.add('select', function (e) {
                const value = e.get('item').value;
                input.value = value;
                ymaps.geocode(value).then(function (res) {
                    const geoObject = res.geoObjects.get(0);
                    if (!geoObject) return;
                    applyCoords(geoObject.geometry.getCoordinates());
                });
            });

            // Адрес поменяли руками после выбора подсказки — координаты
            // больше не соответствуют тексту, сбрасываем, пока не выберут заново.
            input.addEventListener('input', function () {
                input.dataset.confirmed = '0';
                if (latField) latField.value = '';
                if (lonField) lonField.value = '';
            });
        });
    });

    // Обычные (не fetch) формы: не даём отправить, пока адрес не выбран из
    // подсказок — иначе координаты останутся пустыми/неточными.
    document.querySelectorAll('form').forEach(function (form) {
        const addressInput = form.querySelector('.address-geocode');
        if (!addressInput) return;
        form.addEventListener('submit', function (e) {
            if (addressInput.value.trim() && addressInput.dataset.confirmed !== '1') {
                e.preventDefault();
                alert('Выберите адрес из подсказок, чтобы мы могли определить точное расположение салона.');
                addressInput.focus();
            }
        });
    });
})();
