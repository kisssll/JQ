// static/src/js/salon-detail.js — запись на странице салона и мастера.
//
// Заход «витрина» (решение 0011, п. 13). Что изменилось по сравнению с прежней
// версией:
//
//   * шагов четыре, а не пять: шаг «Напоминание» убран, потому что его выбор
//     («за 30 минут / за час / за два / за день» и выключатель) никуда не
//     уходил — POST /api/v1/bookings принимает только мастера, услугу и время,
//     а напоминание сервер ставит сам за два часа. Страница теперь говорит об
//     этом словами вместо шага, которого нет;
//   * сводка одна. Раньше в разметке лежали четыре её копии с id вида
//     selected-master-name-4, и каждый шаг переписывал имя мастера в пяти
//     местах;
//   * виджет ОДИН на страницу и переезжает между липкой колонкой (широкий
//     экран) и листом снизу (телефон). Две копии одних и тех же полей — это
//     две копии одних и тех же id;
//   * в соло (один мастер) шага выбора мастера нет вовсе.
import { esc } from './escape-html.js';
import { toastNetworkError } from './ui-feedback.js';
import { open as openSheet, close as closeSheet } from './sheet.js';

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

/** Ширина, с которой запись живёт в колонке справа, а не в листе снизу.
 *  То же число стоит в salon-detail.css — здесь оно нужно, чтобы перенести
 *  узел, и держать его в двух местах неизбежно; поэтому оно одно и названо. */
const WIDE = '(min-width: 900px)';

function money(service) {
    const low = service.price.toLocaleString('ru-RU');
    return service.price_max === null || service.price_max === undefined
        ? `${low} ₽`
        : `от ${low} до ${service.price_max.toLocaleString('ru-RU')} ₽`;
}

/** Локальная дата YYYY-MM-DD. Не toISOString: он переводит в UTC, и в поясах
 *  впереди UTC кнопка «27» отправляла «26». */
function ymd(d) {
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${d.getFullYear()}-${mm}-${dd}`;
}

function hhmm(value) {
    // Слот приходит как «2026-10-04T15:00» — местное время салона, без зоны.
    // new Date() на такой строке в части браузеров трактует её как UTC, поэтому
    // время берём из самой строки, а не из объекта даты.
    const m = /T(\d{2}:\d{2})/.exec(value);
    return m ? m[1] : '';
}

document.addEventListener('DOMContentLoaded', function () {
    setupFavorites();

    const widget = document.getElementById('bookingWidget');
    if (!widget) return;

    const masters = JSON.parse(widget.dataset.masters || '[]');
    const userData = JSON.parse(widget.dataset.user || 'null');
    const preset = JSON.parse(widget.dataset.preset || '{}');
    // Текст подтверждения берём из data-атрибута, а не из строки здесь: он
    // разный у соло и команды и живёт в одном реестре (public_words).
    const doneText = widget.dataset.done || '';
    const maxDays = parseInt(widget.dataset.maxDays, 10) || 60;
    const solo = widget.dataset.solo === '1';
    const body = widget.querySelector('#bookBody');
    const back = widget.querySelector('[data-book-back]');
    const backLabel = widget.querySelector('[data-book-back-label]');

    const state = { master: solo ? masters[0] : null, service: null, date: null, time: null };

    // ---------- Перенос виджета между колонкой и листом ----------
    // Один узел на страницу: на широком экране он стоит в липкой колонке, на
    // телефоне — внутри листа. hostFor возвращает тот, что нужен сейчас.
    const wide = window.matchMedia(WIDE);
    function hostFor() {
        return document.getElementById(wide.matches ? 'bookingHost' : 'bookingSheetHost');
    }
    function place() {
        const host = hostFor();
        if (host && widget.parentElement !== host) host.appendChild(widget);
    }
    place();
    // Поворот телефона и изменение окна меняют ответ: виджет переезжает, а не
    // остаётся в спрятанном листе.
    wide.addEventListener('change', function () {
        place();
        if (wide.matches) closeSheet();
    });

    // ---------- Шаги ----------
    const STEPS = solo ? ['service', 'time', 'confirm'] : ['master', 'service', 'time', 'confirm'];
    const BACK_LABEL = { service: 'К мастерам', time: 'К услугам', confirm: 'К времени' };
    let step = STEPS[0];

    function go(next) {
        step = next;
        const index = STEPS.indexOf(step);
        back.hidden = index <= 0;
        if (!back.hidden) backLabel.textContent = BACK_LABEL[step] || 'Назад';
        render();
    }

    back.addEventListener('click', function () {
        const index = STEPS.indexOf(step);
        if (index <= 0) return;
        const prev = STEPS[index - 1];
        if (prev === 'master') { state.master = null; state.service = null; }
        if (prev === 'service') { state.service = null; }
        if (prev === 'time') { state.time = null; }
        go(prev);
    });

    function render() {
        if (step === 'master') return renderMasters();
        if (step === 'service') return renderServices();
        if (step === 'time') return renderTime();
        return renderConfirm();
    }

    // ---------- Мастер ----------
    function renderMasters() {
        body.innerHTML = masters.map(function (m) {
            const meta = [m.specialization, m.experience ? `опыт ${m.experience} лет` : '']
                .filter(Boolean).join(' · ');
            return `
                <button type="button" class="pick" data-master="${m.id}">
                    <span class="r-mark r-mark--md" aria-hidden="true">${esc(m.name[0] || '?')}</span>
                    <span class="pick__body">
                        <strong>${esc(m.name)}</strong>
                        <small>${esc(meta)}</small>
                    </span>
                </button>`;
        }).join('') || '<p class="r-text r-muted">Мастеров пока нет.</p>';
    }

    // ---------- Услуга ----------
    function renderServices() {
        const list = (state.master && state.master.services) || [];
        if (!list.length) {
            body.innerHTML = '<p class="r-text r-muted">У мастера пока нет услуг.</p>';
            return;
        }
        body.innerHTML = list.map(function (s) {
            return `
                <button type="button" class="pick" data-service="${s.id}">
                    <span class="pick__body">
                        <strong>${esc(s.name)}</strong>
                        <small>${esc(String(s.duration))} мин</small>
                    </span>
                    <span class="pick__price">${esc(money(s))}</span>
                </button>`;
        }).join('');
    }

    // ---------- Дата и время ----------
    let slotsRequest = 0;

    function renderTime() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let strip = '';
        for (let i = 0; i < maxDays; i++) {
            const d = new Date(today);
            d.setDate(d.getDate() + i);
            const key = ymd(d);
            strip += `
                <button type="button" class="day${key === state.date ? ' is-active' : ''}"
                        data-date="${key}">
                    <span class="day__dow">${i === 0 ? 'сегодня' : WEEKDAYS[d.getDay()]}</span>
                    <span class="day__num">${d.getDate()}</span>
                    <span class="day__mon">${MONTHS[d.getMonth()]}</span>
                </button>`;
        }
        body.innerHTML = `
            <div class="days" role="group" aria-label="Дата записи">${strip}</div>
            <div class="r-slots" id="bookSlots" aria-live="polite"></div>`;
        if (state.date) loadSlots();
        else document.getElementById('bookSlots').innerHTML =
            '<p class="book__empty">Выберите день — покажем свободное время.</p>';
    }

    function loadSlots() {
        const grid = document.getElementById('bookSlots');
        if (!grid) return;
        grid.innerHTML = '<p class="book__empty">Загрузка…</p>';
        // Быстро перещёлкивая дни, можно получить ответы не по порядку — рисуем
        // только ответ на ПОСЛЕДНИЙ выбор.
        const id = ++slotsRequest;
        fetch(`/api/v1/bookings/available/${state.master.id}` +
              `?date=${state.date}&service_id=${state.service.id}`)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (id !== slotsRequest) return;
                if (!data.slots || !data.slots.length) {
                    grid.innerHTML = '<p class="book__empty">' +
                        esc(data.message || 'В этот день свободного времени нет — выберите другой') +
                        '</p>';
                    return;
                }
                grid.innerHTML = data.slots.map(function (slotValue) {
                    return `<button type="button" class="r-slot` +
                        (slotValue === state.time ? ' is-active' : '') +
                        `" data-slot="${esc(slotValue)}">${esc(hhmm(slotValue))}</button>`;
                }).join('');
            })
            .catch(function () {
                if (id !== slotsRequest) return;
                grid.innerHTML = '<p class="book__empty">Не удалось загрузить время. ' +
                    'Проверьте связь и выберите день снова.</p>';
            });
    }

    // ---------- Подтверждение ----------
    function renderConfirm() {
        const m = state.master;
        const s = state.service;
        const dateObj = new Date(state.date + 'T00:00:00');
        const when = `${dateObj.getDate()} ${MONTHS[dateObj.getMonth()]}, ${hhmm(state.time)}`;
        const who = userData
            ? `<div class="book__row"><dt>Вы</dt><dd>${esc(userData.full_name || '')}` +
              `${userData.phone ? ' · ' + esc(userData.phone) : ''}</dd></div>`
            : '';
        body.innerHTML = `
            <dl class="book__sum">
                <div class="book__row"><dt>Мастер</dt><dd>${esc(m.name)}</dd></div>
                <div class="book__row"><dt>Услуга</dt>
                    <dd>${esc(s.name)} · ${esc(String(s.duration))} мин</dd></div>
                <div class="book__row"><dt>Цена</dt><dd class="tabular-nums">${esc(money(s))}</dd></div>
                <div class="book__row"><dt>Когда</dt><dd class="tabular-nums">${esc(when)}</dd></div>
                ${who}
            </dl>
            <p class="book__error" id="bookError" role="alert"></p>
            <button type="button" class="r-btn r-btn--primary r-btn--block" id="bookSubmit">
                <span class="r-btn__label">${userData ? 'Записаться' : 'Войти и записаться'}</span>
                <span class="r-btn__spinner" aria-hidden="true"></span>
            </button>`;
    }

    async function submit(btn) {
        if (!userData) {
            // Гостя отправляем входить, запомнив выбор: вернувшись, он попадает
            // сразу на подтверждение, а не проходит три шага заново.
            localStorage.setItem('bookingState', JSON.stringify({
                masterId: state.master.id, serviceId: state.service.id,
                date: state.date, time: state.time,
            }));
            window.location.href = '/login?redirect=' +
                encodeURIComponent(window.location.pathname);
            return;
        }
        const error = document.getElementById('bookError');
        btn.classList.add('is-loading');
        try {
            const res = await fetch('/api/v1/bookings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    master_id: state.master.id,
                    service_id: state.service.id,
                    start_time: state.time,
                }),
            });
            const data = await res.json().catch(function () { return {}; });
            if (res.ok && data.id) {
                renderDone();
                return;
            }
            // Отказ называет причину и выход из неё: «это время только что
            // заняли» означает «выберите другое», а не «что-то пошло не так».
            error.textContent = data.detail ||
                'Записаться не удалось. Возможно, это время только что заняли — выберите другое.';
        } catch (err) {
            toastNetworkError();
        } finally {
            btn.classList.remove('is-loading');
        }
    }

    /** Готово. Отдельный экран, а не alert и не переход в «Мои записи»:
     *  человек должен увидеть, ЧТО именно создалось, и сам решить, уходить ли
     *  со страницы. Прежняя версия показывала системный alert и уводила. */
    function renderDone() {
        const s = state.service;
        const dateObj = new Date(state.date + 'T00:00:00');
        const when = `${dateObj.getDate()} ${MONTHS[dateObj.getMonth()]}, ${hhmm(state.time)}`;
        back.hidden = true;
        body.innerHTML = `
            <p class="book__done-title">Заявка отправлена</p>
            <p class="book__done-text">${esc(doneText)}</p>
            <dl class="book__sum">
                <div class="book__row"><dt>Услуга</dt><dd>${esc(s.name)}</dd></div>
                <div class="book__row"><dt>Когда</dt>
                    <dd class="tabular-nums">${esc(when)}</dd></div>
            </dl>
            <a class="r-btn r-btn--secondary r-btn--block" href="/bookings">
                <span class="r-btn__label">Мои записи</span></a>`;
    }

    // ---------- Один обработчик на весь виджет ----------
    // Делегирование, а не слушатель на каждой кнопке: содержимое шага
    // перерисовывается целиком, и развешенные слушатели умирали вместе с ним.
    widget.addEventListener('click', function (ev) {
        const master = ev.target.closest('[data-master]');
        if (master) {
            state.master = masters.find(function (m) { return m.id === +master.dataset.master; });
            state.service = null;
            go('service');
            return;
        }
        const service = ev.target.closest('[data-service]');
        if (service) {
            state.service = state.master.services.find(function (s) {
                return s.id === +service.dataset.service;
            });
            state.time = null;
            go('time');
            return;
        }
        const day = ev.target.closest('[data-date]');
        if (day) {
            state.date = day.dataset.date;
            state.time = null;
            widget.querySelectorAll('.day').forEach(function (b) {
                b.classList.toggle('is-active', b.dataset.date === state.date);
            });
            loadSlots();
            return;
        }
        const slotBtn = ev.target.closest('[data-slot]');
        if (slotBtn) {
            state.time = slotBtn.dataset.slot;
            go('confirm');
            return;
        }
        const submitBtn = ev.target.closest('#bookSubmit');
        if (submitBtn) submit(submitBtn);
    });

    // ---------- Кнопка «Записаться» у мастера в команде ----------
    document.addEventListener('click', function (ev) {
        const pick = ev.target.closest('[data-book-master]');
        if (!pick) return;
        ev.preventDefault();
        const m = masters.find(function (x) { return x.id === +pick.dataset.bookMaster; });
        if (!m) return;
        state.master = m;
        state.service = null;
        go('service');
        if (!wide.matches) {
            const sheet = document.getElementById('bookSheet');
            if (sheet) openSheet(sheet, pick);
        } else {
            widget.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    });

    // ---------- Предвыбор из карточки каталога ----------
    // Окно в каталоге уже назвало мастера, услугу и время — повторять за
    // человеком те же три шага незачем. Слот проверяется живым запросом: если
    // его успели занять, человек увидит остальные окна того же дня.
    function applyPreset() {
        if (!preset || !preset.master) return false;
        const m = masters.find(function (x) { return x.id === preset.master; });
        if (!m) return false;
        const s = (m.services || []).find(function (x) { return x.id === preset.service; });
        if (!s) return false;
        state.master = m;
        state.service = s;
        if (preset.slot && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(preset.slot)) {
            state.date = preset.slot.slice(0, 10);
            state.time = preset.slot;
            go('confirm');
        } else {
            go('time');
        }
        // На телефоне выбор живёт в листе, и он закрыт. Человек нажал на время
        // в каталоге — показать ему результат этого нажатия, а не страницу, на
        // которой «ничего не произошло».
        if (!wide.matches) {
            const sheet = document.getElementById('bookSheet');
            if (sheet) openSheet(sheet, document.querySelector('[data-sheet-open]'));
        }
        return true;
    }

    // ---------- Возврат после входа ----------
    function restore() {
        const saved = localStorage.getItem('bookingState');
        if (!saved || !userData) return false;
        localStorage.removeItem('bookingState');
        try {
            const data = JSON.parse(saved);
            const m = masters.find(function (x) { return x.id === data.masterId; });
            const s = m && (m.services || []).find(function (x) { return x.id === data.serviceId; });
            if (!m || !s) return false;
            state.master = m;
            state.service = s;
            state.date = data.date;
            state.time = data.time;
            go('confirm');
            return true;
        } catch (err) {
            return false;
        }
    }

    if (!restore() && !applyPreset()) go(STEPS[0]);
});

// ---------- Избранное ----------
function setupFavorites() {
    const buttons = document.querySelectorAll('.salon-top-fav, .master-fav-btn');
    if (!buttons.length) return;

    fetch('/api/v1/favorites/my')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
            if (!data) return;
            buttons.forEach(function (btn) {
                const ids = btn.dataset.type === 'salon' ? data.salon_ids : data.master_ids;
                const liked = (ids || []).includes(parseInt(btn.dataset.id, 10));
                btn.classList.toggle('liked', liked);
                const icon = btn.querySelector('.heart-icon');
                if (icon) {
                    icon.innerHTML = liked ? btn.dataset.iconHeartFilled : btn.dataset.iconHeart;
                }
            });
        })
        .catch(function () { /* не авторизован — сердца остаются пустыми */ });

    buttons.forEach(function (btn) {
        btn.addEventListener('click', async function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            const liked = btn.classList.contains('liked');
            try {
                const res = await fetch(
                    `/api/v1/favorites/toggle-${btn.dataset.type}/${btn.dataset.id}`,
                    { method: 'POST', headers: { 'Content-Type': 'application/json' } }
                );
                if (res.redirected && res.url.includes('/login')) {
                    window.location.href = '/login?redirect=' +
                        encodeURIComponent(window.location.pathname);
                    return;
                }
                if (!res.ok) return;
                btn.classList.toggle('liked', !liked);
                const icon = btn.querySelector('.heart-icon');
                if (icon) {
                    icon.innerHTML = !liked ? btn.dataset.iconHeartFilled : btn.dataset.iconHeart;
                }
            } catch (err) {
                toastNetworkError();
            }
        });
    });
}
