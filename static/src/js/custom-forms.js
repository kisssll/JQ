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
document.querySelectorAll('input.custom-date').forEach(el => {
    // Для скрытых полей (picker) — настраиваем отдельно
    const isPicker = el.id === 'datePickerInput' || el.id === 'weekPickerInput';
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
    }
    if (el.type === 'date') {
        config.dateFormat = 'Y-m-d';
    }
    if (el.type === 'month') {
        config.dateFormat = 'Y-m';
    }
    // Для пикеров добавляем отключение прошедших дат
    if (isPicker) {
        config.disable = [
            {
                from: '2020-01-01',
                to: new Date(new Date().setDate(new Date().getDate() - 1))
            }
        ];
    }
    flatpickr(el, config);
});