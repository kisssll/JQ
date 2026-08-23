/* static/src/js/custom-forms.js */

import Choices from 'choices.js';
import flatpickr from 'flatpickr';
import 'flatpickr/dist/l10n/ru.js';
import monthSelectPlugin from 'flatpickr/dist/plugins/monthSelect/index.js';

// Инициализация всех select'ов с классом .custom-select
document.querySelectorAll('select.custom-select').forEach(el => {
    // Кладём инстанс на элемент: при программной смене значения (например,
    // сброс сортировки на /salons) нужно обновить и видимую часть — сам по
    // себе скрытый <select> её не двигает.
    el._choices = new Choices(el, {
        searchEnabled: false,
        itemSelectText: '',
        shouldSort: false,
        position: 'auto',
        // Раньше стояло placeholder:true с дефолтом «Выберите...» — Choices
        // подменял этим текстом первую опцию с пустым value, и осмысленные
        // подписи вроде «Все города» пропадали. Плейсхолдер включаем только
        // там, где его явно попросили атрибутом.
        placeholder: el.hasAttribute('placeholder'),
        placeholderValue: el.getAttribute('placeholder') || undefined,
        renderSelectedChoices: 'auto',
        removeItemButton: false,
        allowHTML: false,
    });
});

// Инициализация date/time/month инпутов с классом .custom-date.
// altInput показывает пользователю дату в привычном ДД.ММ.ГГГГ, а исходный
// input (тот же id, скрытый) продолжает отдавать value в ISO-формате
// (Y-m-d / Y-m), который парсит бэкенд — серверный код менять не нужно.
document.querySelectorAll('input.custom-date').forEach(el => {
    const config = {
        locale: 'ru',
        allowInput: true,
        disableMobile: true,
    };

    if (el.type === 'time') {
        config.enableTime = true;
        config.noCalendar = true;
        config.time_24hr = true;
        config.dateFormat = 'H:i';
    } else if (el.type === 'month') {
        // Обычный flatpickr для type="month" рисовал посуточную сетку: клик
        // по числу форматировался в Y-m, поэтому визуально ничего не менялось,
        // если день был внутри уже выбранного месяца. monthSelectPlugin рисует
        // сетку из 12 месяцев и переключает год стрелками — реальный выбор периода.
        config.altInput = true;
        config.plugins = [
            new monthSelectPlugin({ shorthand: false, dateFormat: 'Y-m', altFormat: 'F Y' }),
        ];
    } else {
        // Календарь выбора даты
        config.dateFormat = 'Y-m-d';
        config.altInput = true;
        config.altFormat = 'd.m.Y';
        config.onDayCreate = function(dObj, dStr, fp, dayElem) {
            const dayDate = new Date(dayElem.dateObj);
            const today = new Date();
            today.setHours(0, 0, 0, 0);

            // Для прошедших дней добавляем класс .past-day
            if (dayDate < today) {
                dayElem.classList.add('past-day');
            }
        };
    }

    flatpickr(el, config);
});