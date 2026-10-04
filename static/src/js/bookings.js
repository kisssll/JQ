// static/src/js/bookings.js — «Мои записи».
//
// Два действия: отменить предстоящую и оставить отзыв о прошедшей. Оба живут
// в листе снизу (sheet.js) — на телефоне диалог приезжает оттуда, где палец,
// а движение и жест «потянуть вниз» решены в motion.js один раз.
//
// Вкладок больше нет: предстоящие и прошедшие стоят двумя разделами на
// странице, и прятать половину экрана за переключателем незачем.
import { open as openSheet, close as closeSheet } from './sheet.js';
import { toastError, toastNetworkError } from './ui-feedback.js';

document.addEventListener('DOMContentLoaded', function () {
    if (!document.querySelector('.cabinet-main')) return;

    const cancelSheet = document.getElementById('cancelSheet');
    const cancelConfirm = document.getElementById('cancelConfirm');
    const cancelWhat = document.getElementById('cancelWhat');

    const reviewSheet = document.getElementById('reviewSheet');
    const form = document.getElementById('reviewForm');
    const stars = Array.from(document.querySelectorAll('.review-star'));
    const ratingInput = document.getElementById('reviewRating');
    const ratingError = document.getElementById('reviewRatingError');
    const submitBtn = document.getElementById('reviewSubmit');

    // ===================== Отмена записи =====================
    let cancelId = null;

    document.addEventListener('click', function (ev) {
        const btn = ev.target.closest('.booking-cancel-btn');
        if (!btn || !cancelSheet) return;
        ev.preventDefault();
        cancelId = btn.dataset.bookingId;
        if (cancelWhat) cancelWhat.textContent = btn.dataset.bookingWhat || '';
        openSheet(cancelSheet, btn);
    });

    if (cancelConfirm) {
        cancelConfirm.addEventListener('click', async function () {
            if (!cancelId) return;
            // Повторный тап по той же кнопке не должен послать вторую отмену:
            // первая уже сняла запись, вторая получит «Запись уже отменена».
            cancelConfirm.classList.add('is-loading');
            cancelConfirm.disabled = true;
            try {
                const res = await fetch('/api/v1/bookings/' + cancelId + '/cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (!res.ok) {
                    let detail = '';
                    try { detail = (await res.json()).detail || ''; } catch (e) { /* не JSON */ }
                    toastError(detail || 'Не удалось отменить запись');
                    cancelConfirm.classList.remove('is-loading');
                    cancelConfirm.disabled = false;
                    return;
                }
                // Перезагрузка с признаком: страница сама скажет, что вышло.
                // Раньше об успехе сообщал alert(), который на телефоне
                // перекрывает экран и не читается скринридером как результат.
                window.location.href = '/bookings?notice=cancelled';
            } catch (err) {
                toastNetworkError();
                cancelConfirm.classList.remove('is-loading');
                cancelConfirm.disabled = false;
            }
        });
    }

    // ===================== Отзыв =====================
    if (!form || !reviewSheet) return;

    function setRating(value) {
        ratingInput.value = value;
        stars.forEach(function (star) {
            const v = parseInt(star.dataset.value, 10);
            star.classList.toggle('is-on', v <= value);
            star.setAttribute('aria-checked', v === value ? 'true' : 'false');
        });
        if (ratingError) ratingError.textContent = '';
    }

    stars.forEach(function (star) {
        star.addEventListener('click', function () {
            setRating(parseInt(this.dataset.value, 10));
        });
    });

    // Клавиатура: стрелками, как в настоящей группе радиокнопок. Без этого
    // оценку нельзя поставить вовсе, не трогая экран.
    const group = document.getElementById('starRating');
    if (group) {
        group.addEventListener('keydown', function (ev) {
            const current = parseInt(ratingInput.value, 10) || 0;
            if (ev.key === 'ArrowRight' || ev.key === 'ArrowUp') {
                ev.preventDefault();
                setRating(Math.min(5, current + 1));
            } else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowDown') {
                ev.preventDefault();
                setRating(Math.max(1, current - 1));
            }
        });
    }

    function sheetTitle(text) {
        const title = document.getElementById('reviewSheet-title');
        if (title) title.textContent = text;
    }

    function openReview(opener, { bookingId, salonId, masterId, reviewId }) {
        form.reset();
        document.getElementById('reviewBookingId').value = bookingId || '';
        document.getElementById('reviewSalonId').value = salonId || '';
        document.getElementById('reviewMasterId').value = masterId || '';
        document.getElementById('reviewId').value = reviewId || '';
        document.getElementById('reviewComment').value = '';
        setRating(0);
        ratingInput.value = 0;
        sheetTitle(reviewId ? 'Изменить отзыв' : 'Отзыв о визите');
        openSheet(reviewSheet, opener);
    }

    document.addEventListener('click', function (ev) {
        const add = ev.target.closest('.booking-review-add-btn');
        if (add) {
            ev.preventDefault();
            openReview(add, {
                bookingId: add.dataset.bookingId,
                salonId: add.dataset.salonId,
                masterId: add.dataset.masterId,
            });
            return;
        }

        const edit = ev.target.closest('.booking-review-edit-btn');
        if (edit) {
            ev.preventDefault();
            const reviewId = edit.dataset.reviewId;
            fetch('/api/v1/reviews/' + reviewId)
                .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
                .then(function (data) {
                    openReview(edit, {
                        bookingId: edit.dataset.bookingId,
                        salonId: data.salon_id,
                        masterId: data.master_id,
                        reviewId: reviewId,
                    });
                    setRating(data.rating || 0);
                    document.getElementById('reviewComment').value = data.comment || '';
                })
                .catch(function () { toastError('Не удалось загрузить отзыв'); });
        }
    });

    form.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        const rating = parseInt(ratingInput.value, 10);
        if (!rating) {
            // Ошибка живёт в поле, а не в alert(): место под неё в разметке
            // есть всегда, и кнопка «Отправить» от её появления не уезжает.
            if (ratingError) ratingError.textContent = 'Поставьте оценку';
            if (stars[0]) stars[0].focus();
            return;
        }

        const salonId = document.getElementById('reviewSalonId').value;
        const masterId = document.getElementById('reviewMasterId').value;
        const reviewId = document.getElementById('reviewId').value;

        const fd = new FormData();
        fd.append('salon_id', salonId);
        fd.append('target_type', masterId ? 'master' : 'salon');
        if (masterId) fd.append('master_id', masterId);
        fd.append('rating', rating);
        fd.append('comment', document.getElementById('reviewComment').value.trim());
        fd.append('booking_id', document.getElementById('reviewBookingId').value);

        let url = '/api/v1/reviews/create';
        let method = 'POST';
        if (reviewId) {
            // Правка отзыва фото не меняет: эндпоинт PATCH их не принимает.
            url = '/api/v1/reviews/' + reviewId;
            method = 'PATCH';
            fd.append('_method', 'PATCH');
        } else {
            const files = document.getElementById('reviewPhotos').files;
            for (const file of files) fd.append('files', file);
        }

        submitBtn.classList.add('is-loading');
        submitBtn.disabled = true;
        try {
            const res = await fetch(url, { method: method, body: fd });
            if (!res.ok) {
                let detail = '';
                try { detail = (await res.json()).detail || ''; } catch (e) { /* HTML */ }
                toastError(detail || 'Не удалось сохранить отзыв');
                submitBtn.classList.remove('is-loading');
                submitBtn.disabled = false;
                return;
            }
            closeSheet(reviewSheet);
            window.location.href = '/bookings?notice=reviewed';
        } catch (err) {
            toastNetworkError();
            submitBtn.classList.remove('is-loading');
            submitBtn.disabled = false;
        }
    });
});
