// static/src/js/business/evening-deal.js
//
// Поведение секции «Вечерние окна со скидкой». Раньше это был инлайновый
// <script> внутри компонента: мимо сборки, с системным confirm() и с ошибками
// в скрытом <p>. Теперь модуль, общий диалог подтверждения и тосты.

import { confirmDialog, toastNetworkError } from '../ui-feedback.js';

const API = '/api/v1/business/my-salon/evening-deal';

document.addEventListener('DOMContentLoaded', function () {
    const block = document.querySelector('.evening-deal-block');
    if (!block) return;

    const salonId = block.dataset.salonId;
    const modal = block.querySelector('#eveningDealModal');
    const errorEl = block.querySelector('#edError');
    let lastFocused = null;

    const url = () => `${API}?salon_id=${salonId}`;

    function showError(text) {
        errorEl.textContent = text;
        errorEl.hidden = false;
    }

    function closeModal() {
        modal.hidden = true;
        document.body.classList.remove('ed-modal-open');
        document.removeEventListener('keydown', onKeydown, true);
        if (lastFocused && lastFocused.focus) lastFocused.focus();
    }

    function onKeydown(e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            closeModal();
        }
    }

    async function openModal() {
        lastFocused = document.activeElement;
        errorEl.hidden = true;

        // Показываем сразу, с уже отрисованными значениями: раньше окно ждало
        // ответа сервера и по медленной сети открывалось с заметной паузой.
        modal.hidden = false;
        document.body.classList.add('ed-modal-open');
        document.addEventListener('keydown', onKeydown, true);
        block.querySelector('#edDiscount').focus();

        // Затем подтягиваем актуальные значения: настройку могли поменять в
        // другой вкладке панели, а разметка отрисована один раз при загрузке.
        try {
            const res = await fetch(url());
            if (res.ok) {
                const d = await res.json();
                block.querySelector('#edDiscount').value = d.discount_percent || 15;
                block.querySelector('#edFrom').value = d.evening_from || '17:00';
                block.querySelector('#edTo').value = d.evening_to || '21:00';
                const days = d.weekdays || [];
                const svc = d.service_ids || [];
                block.querySelectorAll('.ed-weekday').forEach(cb => {
                    cb.checked = days.indexOf(parseInt(cb.value, 10)) >= 0;
                });
                block.querySelectorAll('.ed-service').forEach(cb => {
                    cb.checked = svc.indexOf(parseInt(cb.value, 10)) >= 0;
                });
            }
        } catch (e) { /* остаёмся на том, что уже отрисовано */ }
    }

    async function save() {
        const discount = parseInt(block.querySelector('#edDiscount').value, 10) || 0;
        const from = block.querySelector('#edFrom').value;
        const to = block.querySelector('#edTo').value;
        // Проверяем до отправки: сервер вернёт ту же ошибку, но лишний круг
        // по сети ради очевидного случая человеку не нужен.
        if (discount < 1 || discount > 99) {
            showError('Скидка должна быть от 1 до 99%.');
            return;
        }
        if (from && to && from >= to) {
            showError('Начало вечера должно быть раньше конца.');
            return;
        }

        const body = {
            enabled: true,
            discount_percent: discount,
            evening_from: from,
            evening_to: to,
            weekdays: [...block.querySelectorAll('.ed-weekday:checked')].map(c => parseInt(c.value, 10)),
            service_ids: [...block.querySelectorAll('.ed-service:checked')].map(c => parseInt(c.value, 10)),
        };
        try {
            const res = await fetch(url(), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (res.ok) { location.reload(); return; }
            const err = await res.json().catch(() => ({}));
            showError(err.detail || 'Не удалось сохранить');
        } catch (e) {
            toastNetworkError();
        }
    }

    async function disable() {
        const ok = await confirmDialog({
            title: 'Выключить вечерние скидки?',
            message: 'Салон перестанет попадать в подборку вечерних окон.',
            confirmText: 'Выключить',
            danger: true,
        });
        if (!ok) return;
        try {
            const res = await fetch(url(), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: false, discount_percent: 0 }),
            });
            if (res.ok) location.reload();
            else toastNetworkError();
        } catch (e) {
            toastNetworkError();
        }
    }

    block.addEventListener('click', function (e) {
        if (e.target.closest('[data-ed-open]')) openModal();
        else if (e.target.closest('[data-ed-close]')) closeModal();
        else if (e.target.closest('[data-ed-save]')) save();
        else if (e.target.closest('[data-ed-disable]')) disable();
    });

    // Клик по затемнению закрывает — но только по нему самому, не по карточке.
    modal.addEventListener('mousedown', function (e) {
        if (e.target === modal) closeModal();
    });
});
