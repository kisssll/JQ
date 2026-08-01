/* static/src/js/custom-forms.js */

import Choices from 'choices.js';
import flatpickr from 'flatpickr';
import 'flatpickr/dist/l10n/ru.js';

// Инициализация всех select'ов с классом .custom-select
document.querySelectorAll('select.custom-select').forEach(el => {
    new Choices(el, {
        searchEnabled: false,
        itemSelectText: '',
        shouldSort: false,
        position: 'auto',
        placeholder: true,
        placeholderValue: el.getAttribute('placeholder') || 'Выберите...',
        renderSelectedChoices: 'auto',
        removeItemButton: false,
        allowHTML: false,
    });
});

// Инициализация date/time/month инпутов с классом .custom-date
document.querySelectorAll('input.custom-date').forEach(el => {
    const config = {
        dateFormat: el.type === 'date' ? 'Y-m-d' : (el.type === 'month' ? 'Y-m' : 'H:i'),
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
        config.dateFormat = 'Y-m';
    } else {
        // Календарь выбора даты
        config.dateFormat = 'Y-m-d';
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