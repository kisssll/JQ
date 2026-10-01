// static/src/js/business/panel-edit.js
//
// Режим редактирования бизнес-панели: владелец сам решает, какие разделы у него
// есть и в каком порядке (решение 0007, дополнение 30.09.2026). Образец —
// домашний экран iOS: плитки дрожат, у каждой минус, порядок меняется рукой.
//
// Разметку целиком даёт сервер (см. dashboard.py): плитки, минусы, стрелки
// порядка, заготовки <template> для скрытых разделов. Скрипт её только
// показывает и переставляет — тогда все подписи для экранного диктора лежат в
// одном месте и на русском, а не собираются строками здесь.
//
// Перетаскивание написано на Pointer Events руками: сторонних библиотек в
// проекте нет, и одна мышь-плюс-палец-плюс-перо в одном API дешевле, чем
// раздельные mouse/touch обработчики.
import { confirmDialog, toastNetworkError, toastSuccess } from '../ui-feedback.js';

(function () {
    const nav = document.getElementById('panelNav');
    const gear = document.getElementById('panelEditBtn');
    const panel = document.getElementById('panelEditPanel');
    // Кнопки нет у того, кто не вправе менять салон, — тогда и режима нет.
    if (!nav || !gear || !panel) return;

    const chips = panel.querySelector('.panel-edit-chips');
    const doneBtn = document.getElementById('panelEditDone');
    const cancelBtn = document.getElementById('panelEditCancel');
    const note = document.getElementById('panelEditNote');
    const hrefBase = nav.dataset.hrefBase || '';

    // Снимок разметки до правок — «Отмена» возвращает его целиком, без запроса.
    // Обработчики висят на ленте и на списке скрытых, поэтому замена innerHTML
    // ничего не отвязывает.
    let snapshot = null;
    // Убранные плитки держим живыми узлами: вернуть раздел — значит вставить
    // ровно то, что убрали, вместе с его кнопками.
    const stash = new Map();
    let activeKeyOnEnter = null;

    const editing = () => nav.classList.contains('is-editing');
    const items = () => Array.from(nav.querySelectorAll('.tab-item'));
    const setNote = (text) => { if (note) note.textContent = text || ''; };

    function enter() {
        if (editing()) return;
        snapshot = { nav: nav.innerHTML, chips: chips ? chips.innerHTML : '' };
        stash.clear();
        const active = nav.querySelector('.tab-btn.active');
        activeKeyOnEnter = active ? active.closest('.tab-item').dataset.key : null;

        nav.classList.add('is-editing');
        panel.hidden = false;
        gear.setAttribute('aria-pressed', 'true');
        // Пока правим — по вкладкам не ходим (иначе правки потеряются), и об
        // этом должен знать не только зрячий: ссылка объявляется недоступной.
        items().forEach(markLinkBlocked);
        setNote('Разделы можно переставить и убрать. Нажмите «Готово», чтобы сохранить.');
        const first = nav.querySelector('.tab-item-minus, .tab-item-up');
        if (first) first.focus();
    }

    function leave() {
        nav.classList.remove('is-editing');
        panel.hidden = true;
        gear.setAttribute('aria-pressed', 'false');
        setNote('');
        gear.focus();
    }

    function cancel() {
        if (snapshot) {
            nav.innerHTML = snapshot.nav;
            if (chips) chips.innerHTML = snapshot.chips;
        }
        stash.clear();
        leave();
    }

    function markLinkBlocked(item) {
        const link = item.querySelector('.tab-btn');
        if (link) link.setAttribute('aria-disabled', 'true');
    }

    function announcePosition(item) {
        const list = items();
        const place = list.indexOf(item) + 1;
        setNote(`«${item.dataset.label}» — ${place}-й из ${list.length}.`);
    }

    // ---------- Убрать раздел ----------

    async function removeItem(item) {
        // Обязательные разделы минуса и не имеют — но проверка тут, а не в
        // разметке: без «Тарифа» или «Настроек» панель нерабочая.
        if (!item || item.dataset.locked) return;
        const label = item.dataset.label;
        const ok = await confirmDialog({
            title: `Убрать раздел «${label}» из панели?`,
            message: 'Его можно вернуть здесь же. Данные раздела остаются на месте.',
            confirmText: 'Убрать',
            danger: true,
        });
        if (!ok) return;

        const next = item.nextElementSibling || item.previousElementSibling;
        stash.set(item.dataset.key, item);
        item.remove();
        addChip(item);
        setNote(`«${label}» убран из панели — вернуть можно ниже.`);
        // Фокус не должен провалиться в никуда: уводим на соседнюю плитку.
        const fallback = next && next.querySelector('.tab-item-minus, .tab-item-up');
        (fallback || chips.querySelector(`.panel-edit-chip[data-key="${item.dataset.key}"]`) || doneBtn).focus();
    }

    function addChip(item) {
        if (!chips) return;
        const key = item.dataset.key;
        const label = item.dataset.label;
        const empty = chips.querySelector('.panel-edit-empty');
        if (empty) empty.remove();

        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'panel-edit-chip';
        chip.dataset.key = key;
        chip.setAttribute('aria-label', `Вернуть раздел «${label}» в панель`);
        const icon = item.querySelector('.tab-btn svg');
        if (icon) chip.appendChild(icon.cloneNode(true));
        const text = document.createElement('span');
        text.className = 'panel-edit-chip-text';
        text.textContent = label;
        const plus = document.createElement('span');
        plus.className = 'panel-edit-chip-plus';
        plus.setAttribute('aria-hidden', 'true');
        plus.textContent = '+';
        chip.append(text, plus);
        chips.appendChild(chip);
    }

    // ---------- Вернуть раздел ----------

    function restore(key) {
        let item = stash.get(key);
        if (item) {
            stash.delete(key);
        } else {
            // Раздел был выключен ещё до входа в режим — берём заготовку с сервера.
            const tpl = panel.querySelector(`template.panel-edit-template[data-key="${key}"]`);
            if (!tpl) return;
            item = tpl.content.firstElementChild.cloneNode(true);
        }
        const link = item.querySelector('.tab-btn');
        // Пока раздел выключен, ссылки на него в странице нет вовсе — адрес
        // появляется только здесь, в момент возврата.
        if (link && !link.getAttribute('href')) link.setAttribute('href', hrefBase + key);
        markLinkBlocked(item);
        nav.appendChild(item);

        const chip = chips && chips.querySelector(`.panel-edit-chip[data-key="${key}"]`);
        if (chip) chip.remove();
        if (chips && !chips.querySelector('.panel-edit-chip')) {
            const empty = document.createElement('p');
            empty.className = 'panel-edit-empty';
            empty.textContent = 'Скрытых разделов нет — в панели все.';
            chips.appendChild(empty);
        }
        setNote(`«${item.dataset.label}» вернулся в панель, в конец.`);
        const btn = item.querySelector('.tab-item-minus, .tab-item-up');
        if (btn) btn.focus();
    }

    // ---------- Порядок ----------

    function move(item, step) {
        if (!item || item.dataset.pinned) return;
        const list = items();
        const target = list[list.indexOf(item) + step];
        // «Обзор» закреплён первым: перед ним места нет.
        if (!target || target.dataset.pinned) return;
        const focused = document.activeElement;
        if (step < 0) nav.insertBefore(item, target);
        else nav.insertBefore(target, item);
        // Перенос узла в некоторых браузерах сбрасывает фокус — возвращаем,
        // иначе с клавиатуры нельзя переставить раздел на два места подряд.
        if (focused && focused.isConnected && focused.focus) focused.focus();
        announcePosition(item);
    }

    // ---------- Перетаскивание (мышь, палец, перо) ----------

    let drag = null;

    function itemUnder(x, y) {
        const el = document.elementFromPoint(x, y);
        return el ? el.closest('.tab-item') : null;
    }

    function follow(ev) {
        // Считаем сдвиг от «слота», в котором плитка лежит сейчас: после каждой
        // перестановки слот меняется, и без пересчёта плитка прыгала бы из-под
        // пальца.
        drag.item.style.transform = '';
        const rect = drag.item.getBoundingClientRect();
        drag.item.style.transform =
            `translate(${ev.clientX - drag.dx - rect.left}px, ${ev.clientY - drag.dy - rect.top}px)`;
    }

    nav.addEventListener('pointerdown', function (ev) {
        if (!editing() || drag || (ev.pointerType === 'mouse' && ev.button !== 0)) return;
        // Нажатие на кнопку — это кнопка, а не перетаскивание.
        if (ev.target.closest('.tab-item-minus, .tab-item-move')) return;
        const item = ev.target.closest('.tab-item');
        if (!item || item.dataset.pinned) return;
        const rect = item.getBoundingClientRect();
        drag = {
            item, id: ev.pointerId, moved: false,
            dx: ev.clientX - rect.left, dy: ev.clientY - rect.top,
            fromX: ev.clientX, fromY: ev.clientY,
        };
        // Захват указателя нужен, чтобы плитка продолжала получать события,
        // когда палец ушёл за её край. Если браузер отказал (указателя уже
        // нет), перетаскивание всё равно работает — события дойдут по всплытию.
        try { item.setPointerCapture(ev.pointerId); } catch (e) { /* не страшно */ }
    });

    nav.addEventListener('pointermove', function (ev) {
        if (!drag || ev.pointerId !== drag.id) return;
        if (!drag.moved) {
            // Порог: короткое нажатие с дрожанием руки — это нажатие, а не
            // перетаскивание, иначе не получилось бы просто ткнуть в плитку.
            if (Math.abs(ev.clientX - drag.fromX) + Math.abs(ev.clientY - drag.fromY) < 6) return;
            drag.moved = true;
            drag.item.classList.add('is-dragging');
        }
        ev.preventDefault();
        const over = itemUnder(ev.clientX, ev.clientY);
        if (over && over !== drag.item && over.parentElement === nav && !over.dataset.pinned) {
            const rect = over.getBoundingClientRect();
            const after = ev.clientX > rect.left + rect.width / 2;
            nav.insertBefore(drag.item, after ? over.nextElementSibling : over);
        }
        follow(ev);
    });

    function endDrag(ev) {
        if (!drag || ev.pointerId !== drag.id) return;
        const { item, moved, id } = drag;
        drag = null;
        item.style.transform = '';
        item.classList.remove('is-dragging');
        try {
            if (item.hasPointerCapture && item.hasPointerCapture(id)) item.releasePointerCapture(id);
        } catch (e) { /* захвата и не было */ }
        if (moved) announcePosition(item);
    }
    nav.addEventListener('pointerup', endDrag);
    nav.addEventListener('pointercancel', endDrag);

    // ---------- Нажатия в ленте ----------

    nav.addEventListener('click', function (ev) {
        if (!editing()) return;
        const link = ev.target.closest('.tab-btn');
        if (link) {
            // Переход по вкладке — это перезагрузка страницы, а правки ещё не
            // сохранены. Объясняем, а не молчим.
            ev.preventDefault();
            setNote('Сначала нажмите «Готово» или «Отмена» — потом открывайте разделы.');
            return;
        }
        const minus = ev.target.closest('.tab-item-minus');
        if (minus) { ev.preventDefault(); removeItem(minus.closest('.tab-item')); return; }
        const up = ev.target.closest('.tab-item-up');
        if (up) { ev.preventDefault(); move(up.closest('.tab-item'), -1); return; }
        const down = ev.target.closest('.tab-item-down');
        if (down) { ev.preventDefault(); move(down.closest('.tab-item'), 1); }
    });

    if (chips) {
        chips.addEventListener('click', function (ev) {
            const chip = ev.target.closest('.panel-edit-chip');
            if (chip) restore(chip.dataset.key);
        });
    }

    // ---------- Сохранение ----------

    async function save() {
        const order = items().map((it) => it.dataset.key);
        doneBtn.disabled = true;
        setNote('Сохраняем…');
        try {
            const res = await fetch('/api/v1/business/my-salon/panel-sections', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    salon_id: parseInt(nav.dataset.salonId, 10),
                    sections: order,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setNote(data.detail || 'Не удалось сохранить набор разделов.');
                doneBtn.disabled = false;
                return;
            }
            doneBtn.disabled = false;
            // Если убрали раздел, который сейчас открыт, страница показывала бы
            // содержимое исчезнувшей вкладки — перечитываем её у сервера.
            if (activeKeyOnEnter && order.indexOf(activeKeyOnEnter) === -1) {
                window.location = hrefBase.replace(/&tab=$/, '');
                return;
            }
            snapshot = null;
            items().forEach((item) => {
                const link = item.querySelector('.tab-btn');
                if (link) link.removeAttribute('aria-disabled');
            });
            leave();
            toastSuccess('Панель сохранена.');
        } catch (e) {
            toastNetworkError();
            doneBtn.disabled = false;
        }
    }

    gear.addEventListener('click', function () {
        if (editing()) cancel();
        else enter();
    });
    doneBtn.addEventListener('click', save);
    cancelBtn.addEventListener('click', cancel);

    // Escape — привычный выход без сохранения (как в диалогах проекта).
    // defaultPrevented обязателен: диалог подтверждения слушает Escape в фазе
    // перехвата, то есть раньше нас, и к этому моменту он уже снял своё
    // затемнение — одно нажатие закрывало и окно, и весь режим правки.
    document.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Escape' || ev.defaultPrevented || !editing()) return;
        if (document.querySelector('.rumi-dialog-overlay')) return;
        ev.preventDefault();
        cancel();
    });

    // Вход по ссылке из настроек салона (?edit=1). Параметр сразу убираем из
    // адреса: перезагрузка страницы не должна снова открывать режим правки.
    const params = new URLSearchParams(window.location.search);
    if (params.get('edit') === '1') {
        params.delete('edit');
        const rest = params.toString();
        window.history.replaceState({}, '', window.location.pathname + (rest ? '?' + rest : ''));
        enter();
    }
})();
