// static/src/js/reschedule.js — перенос записи клиентом (решение 0020).
//
// Один лист на «Мои записи» и гостевую страницу: кнопка .js-reschedule-btn
// несёт адрес API своей записи, а лист — общий (components/reschedule.py).
//
// Порядок шагов — день → время → итог → подтверждение. Итог запрашивается у
// сервера, а не считается здесь: цена могла измениться (скидка вечернего окна
// действует только вечером), и человек должен увидеть это ДО того, как
// согласится.
import { esc } from './escape-html.js';
import { open as openSheet } from './sheet.js';
import { toastError, toastNetworkError } from './ui-feedback.js';

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

function ymd(d) {
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${d.getFullYear()}-${m}-${day}`;
}

function hhmm(slot) { return slot.slice(11, 16); }

function humanWhen(slot) {
    const d = new Date(slot.slice(0, 10) + 'T00:00:00');
    return `${d.getDate()} ${MONTHS_GEN[d.getMonth()]}, ${hhmm(slot)}`;
}

function rub(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' ₽'; }

async function detailOf(res, fallback) {
    try { return (await res.json()).detail || fallback; } catch (e) { return fallback; }
}

document.addEventListener('DOMContentLoaded', function () {
    const sheet = document.getElementById('rescheduleSheet');
    if (!sheet) return;

    const what = document.getElementById('rescheduleWhat');
    const days = document.getElementById('rescheduleDays');
    const grid = document.getElementById('rescheduleSlots');
    const summary = document.getElementById('rescheduleSummary');
    const whenEl = document.getElementById('rescheduleWhen');
    const priceEl = document.getElementById('reschedulePrice');
    const confirmBtn = document.getElementById('rescheduleConfirm');
    const maxDays = parseInt(days.dataset.maxDays, 10) || 60;

    const state = { api: '', done: '', date: '', slot: '' };
    // Быстро перещёлкивая дни и окна, можно получить ответы не по порядку —
    // рисуем только ответ на последний выбор (как на странице салона).
    let slotsRequest = 0;
    let quoteRequest = 0;

    function resetChoice() {
        state.slot = '';
        summary.hidden = true;
        priceEl.hidden = true;
        confirmBtn.disabled = true;
        quoteRequest++;
    }

    function renderDays() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let html = '';
        for (let i = 0; i <= maxDays; i++) {
            const d = new Date(today);
            d.setDate(d.getDate() + i);
            const key = ymd(d);
            html += `
                <button type="button" class="day${key === state.date ? ' is-active' : ''}"
                        data-reschedule-date="${key}">
                    <span class="day__dow">${i === 0 ? 'сегодня' : WEEKDAYS[d.getDay()]}</span>
                    <span class="day__num">${d.getDate()}</span>
                    <span class="day__mon">${MONTHS[d.getMonth()]}</span>
                </button>`;
        }
        days.innerHTML = html;
        const active = days.querySelector('.is-active');
        if (active) active.scrollIntoView({ block: 'nearest', inline: 'center' });
    }

    function loadSlots() {
        resetChoice();
        grid.innerHTML = '<p class="book__empty">Загрузка…</p>';
        const id = ++slotsRequest;
        fetch(`${state.api}/slots?date=${encodeURIComponent(state.date)}`)
            .then(async function (r) {
                if (!r.ok) throw new Error(await detailOf(r, ''));
                return r.json();
            })
            .then(function (data) {
                if (id !== slotsRequest) return;
                if (!data.slots || !data.slots.length) {
                    grid.innerHTML = '<p class="book__empty">' +
                        esc(data.message || 'В этот день свободного времени нет — выберите другой') +
                        '</p>';
                    return;
                }
                grid.innerHTML = data.slots.map(function (slot) {
                    return `<button type="button" class="r-slot" data-reschedule-slot="${esc(slot)}">` +
                        `${esc(hhmm(slot))}</button>`;
                }).join('');
            })
            .catch(function (err) {
                if (id !== slotsRequest) return;
                grid.innerHTML = '<p class="book__empty">' +
                    esc(err.message || 'Не удалось загрузить время. Проверьте связь и выберите день снова.') +
                    '</p>';
            });
    }

    function loadQuote() {
        const id = ++quoteRequest;
        summary.hidden = false;
        whenEl.textContent = 'Новое время: ' + humanWhen(state.slot);
        priceEl.hidden = true;
        confirmBtn.disabled = true;
        fetch(`${state.api}/quote?start_time=${encodeURIComponent(state.slot)}`)
            .then(async function (r) {
                if (!r.ok) throw new Error(await detailOf(r, 'Это время недоступно'));
                return r.json();
            })
            .then(function (q) {
                if (id !== quoteRequest) return;
                if (q.price_changed && q.final_price != null) {
                    priceEl.textContent = (q.old_price != null ? `Стоимость станет ${rub(q.final_price)} ` +
                        `вместо ${rub(q.old_price)}` : `Стоимость: ${rub(q.final_price)}`) +
                        ' — скидка вечернего окна действует только на вечернее время.';
                    priceEl.hidden = false;
                }
                confirmBtn.disabled = false;
            })
            .catch(function (err) {
                if (id !== quoteRequest) return;
                toastError(err.message);
                loadSlots();
            });
    }

    document.addEventListener('click', function (ev) {
        const btn = ev.target.closest('.js-reschedule-btn');
        if (!btn) return;
        ev.preventDefault();
        state.api = btn.dataset.rescheduleApi;
        state.done = btn.dataset.rescheduleDone;
        const current = btn.dataset.rescheduleCurrent || '';
        // Лист открывается на дне нынешней записи, если он ещё не прошёл:
        // чаще всего запись двигают на соседний час того же дня.
        const today = ymd(new Date());
        state.date = current.slice(0, 10) >= today ? current.slice(0, 10) : today;
        what.textContent = btn.dataset.rescheduleWhat || '';
        renderDays();
        loadSlots();
        openSheet(sheet, btn);
    });

    sheet.addEventListener('click', function (ev) {
        const day = ev.target.closest('[data-reschedule-date]');
        if (day) {
            state.date = day.dataset.rescheduleDate;
            days.querySelectorAll('.day').forEach(function (b) {
                b.classList.toggle('is-active', b === day);
            });
            loadSlots();
            return;
        }
        const slot = ev.target.closest('[data-reschedule-slot]');
        if (slot) {
            state.slot = slot.dataset.rescheduleSlot;
            grid.querySelectorAll('.r-slot').forEach(function (b) {
                b.classList.toggle('is-active', b === slot);
            });
            loadQuote();
        }
    });

    confirmBtn.addEventListener('click', async function () {
        if (!state.slot) return;
        // Повторный тап не должен послать второй перенос: сервер запись и так
        // блокирует, но ответ «и так на это время» человека только запутает.
        confirmBtn.classList.add('is-loading');
        confirmBtn.disabled = true;
        try {
            const res = await fetch(state.api, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ start_time: state.slot }),
            });
            if (!res.ok) {
                toastError(await detailOf(res, 'Не удалось перенести запись'));
                confirmBtn.classList.remove('is-loading');
                // Окно могли занять, пока человек думал, — показываем свежие.
                loadSlots();
                return;
            }
            window.location.href = state.done;
        } catch (err) {
            toastNetworkError();
            confirmBtn.classList.remove('is-loading');
            confirmBtn.disabled = false;
        }
    });
});
