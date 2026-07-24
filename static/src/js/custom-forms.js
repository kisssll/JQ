// static/src/js/custom-forms.js
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
        renderSelectedChoices: 'always', // выбранный элемент остаётся в списке
    });
});

// Инициализация date/time/month инпутов с классом .custom-date
document.querySelectorAll('input.custom-date[type="date"]').forEach(el => {
    flatpickr(el, {
        dateFormat: 'Y-m-d',
        locale: 'ru',
        allowInput: true,
        disableMobile: true,
    });
});

document.querySelectorAll('input.custom-date[type="month"]').forEach(el => {
    flatpickr(el, {
        dateFormat: 'Y-m',
        locale: 'ru',
        allowInput: true,
        disableMobile: true,
    });
});

document.querySelectorAll('input.custom-date[type="time"]').forEach(el => {
    flatpickr(el, {
        enableTime: true,
        noCalendar: true,
        dateFormat: 'H:i',
        time_24hr: true,
        allowInput: true,
        disableMobile: true,
    });
});