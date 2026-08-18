// static/src/js/ui-feedback.js
//
// Тосты и диалог подтверждения вместо системных alert()/confirm().
// Причина: браузерная модалка выглядит как ОС, а не как Руми, и блокирует поток
// до клика. Оформление взято от .profile-alert — визуальный язык сообщений в
// продукте уже был, ему не хватало вызова из JS.
//
// confirm() синхронный и возвращает boolean, а диалог здесь асинхронный:
// на каждой точке вызова нужен await, поэтому функция и называется иначе.

const TOAST_TIMEOUT = 5000;

// Единая формулировка: в продукте было четыре разных текста про одно и то же
// («Ошибка сети», «Сеть недоступна, попробуйте ещё раз», «Ошибка сети,
// попробуйте ещё раз», «Ошибка соединения.»).
export const NETWORK_ERROR = 'Не удалось связаться с сервером. Проверьте соединение и попробуйте ещё раз.';

function toastHost() {
    let host = document.getElementById('rumi-toasts');
    if (!host) {
        host = document.createElement('div');
        host.id = 'rumi-toasts';
        host.className = 'rumi-toasts';
        document.body.appendChild(host);
    }
    return host;
}

export function toast(message, kind = 'info') {
    if (!message) return;
    const el = document.createElement('div');
    el.className = `rumi-toast rumi-toast-${kind}`;
    // Ошибку объявляем настойчиво, остальное — вежливо.
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    el.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');

    const text = document.createElement('span');
    text.className = 'rumi-toast-text';
    text.textContent = message;

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'rumi-toast-close';
    close.setAttribute('aria-label', 'Закрыть сообщение');
    close.textContent = '×';

    let removed = false;
    const remove = () => {
        if (removed) return;
        removed = true;
        el.classList.add('is-leaving');
        // Уходим по окончании анимации, но не зависаем, если её нет.
        setTimeout(() => el.remove(), 200);
    };
    close.addEventListener('click', remove);

    el.append(text, close);
    toastHost().appendChild(el);
    setTimeout(remove, TOAST_TIMEOUT);
    return remove;
}

export const toastError = (message) => toast(message, 'error');
export const toastSuccess = (message) => toast(message, 'success');
export const toastNetworkError = () => toastError(NETWORK_ERROR);

/**
 * Диалог подтверждения. Возвращает Promise<boolean>.
 * @param {Object|string} options — текст или {title, message, confirmText, cancelText, danger}
 */
export function confirmDialog(options) {
    const opts = typeof options === 'string' ? { message: options } : (options || {});
    const {
        title = 'Подтвердите действие',
        message = '',
        confirmText = 'Подтвердить',
        cancelText = 'Отмена',
        danger = false,
    } = opts;

    return new Promise((resolve) => {
        const previouslyFocused = document.activeElement;

        const overlay = document.createElement('div');
        overlay.className = 'rumi-dialog-overlay';

        const box = document.createElement('div');
        box.className = `rumi-dialog${danger ? ' is-danger' : ''}`;
        box.setAttribute('role', 'dialog');
        box.setAttribute('aria-modal', 'true');

        const titleEl = document.createElement('h2');
        titleEl.className = 'rumi-dialog-title';
        titleEl.textContent = title;
        const titleId = 'rumi-dialog-title-' + Math.random().toString(36).slice(2, 8);
        titleEl.id = titleId;
        box.setAttribute('aria-labelledby', titleId);

        const actions = document.createElement('div');
        actions.className = 'rumi-dialog-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn-outline rumi-dialog-cancel';
        cancelBtn.textContent = cancelText;

        const okBtn = document.createElement('button');
        okBtn.type = 'button';
        okBtn.className = `rumi-dialog-confirm${danger ? ' is-danger' : ''}`;
        okBtn.textContent = confirmText;

        actions.append(cancelBtn, okBtn);
        box.appendChild(titleEl);
        if (message) {
            const msgEl = document.createElement('p');
            msgEl.className = 'rumi-dialog-message';
            msgEl.textContent = message;
            box.appendChild(msgEl);
        }
        box.appendChild(actions);
        overlay.appendChild(box);

        let settled = false;
        function finish(result) {
            if (settled) return;
            settled = true;
            document.removeEventListener('keydown', onKeydown, true);
            overlay.remove();
            document.body.classList.remove('rumi-dialog-open');
            if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
            resolve(result);
        }

        // Клавиатура: Escape отменяет, Tab не выпускает фокус из диалога.
        function onKeydown(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                finish(false);
                return;
            }
            if (e.key !== 'Tab') return;
            const focusable = [cancelBtn, okBtn];
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }

        cancelBtn.addEventListener('click', () => finish(false));
        okBtn.addEventListener('click', () => finish(true));
        // Клик по затемнению = отмена, но только по нему самому, не по карточке.
        overlay.addEventListener('mousedown', (e) => {
            if (e.target === overlay) finish(false);
        });
        document.addEventListener('keydown', onKeydown, true);

        document.body.classList.add('rumi-dialog-open');
        document.body.appendChild(overlay);
        okBtn.focus();
    });
}

// Декларативное подтверждение для нативных форм: <form data-confirm="Текст?">.
// В разметке было onsubmit="return confirm(...)" — синхронный вызов, который
// нашим асинхронным диалогом не заменить на месте. Перехватываем сабмит здесь.
document.addEventListener('submit', async function (e) {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    const message = form.dataset.confirm;
    if (!message || form.dataset.confirmed === '1') return;

    e.preventDefault();
    const ok = await confirmDialog({
        title: message,
        confirmText: form.dataset.confirmLabel || 'Подтвердить',
        danger: form.dataset.confirmDanger !== '0',
    });
    if (!ok) return;
    form.dataset.confirmed = '1';
    // requestSubmit сохраняет submitter и валидацию; submit() — фолбэк.
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
}, true);

// Часть точек вызова живёт в инлайновых onclick из серверной разметки — им
// нужны глобальные имена, импорт там недоступен.
window.rumiToast = toast;
window.rumiToastError = toastError;
window.rumiToastSuccess = toastSuccess;
window.rumiToastNetworkError = toastNetworkError;
window.rumiConfirm = confirmDialog;
