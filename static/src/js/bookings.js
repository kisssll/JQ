// static/src/js/bookings.js
import { confirmDialog, toastNetworkError } from './ui-feedback.js';

document.addEventListener('DOMContentLoaded', function() {
    // Проверяем, что мы на странице записей
    if (!document.querySelector('.bookings-tabs')) {
        return;
    }

    // === Восстановление активной вкладки из localStorage ===
    const tabs = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');
    const activeTab = localStorage.getItem('bookingsActiveTab') || 'upcoming';

    function activateTab(tabId) {
        tabs.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
        });
        contents.forEach(content => {
            content.classList.toggle('active', content.id === 'tab-' + tabId);
        });
        localStorage.setItem('bookingsActiveTab', tabId);
    }

    // Активируем сохранённую вкладку
    activateTab(activeTab);

    // === Переключение вкладок ===
    tabs.forEach(btn => {
        btn.addEventListener('click', function() {
            const target = this.dataset.tab;
            activateTab(target);
        });
    });

    // === Отмена записи ===
    window.cancelBooking = async function(bookingId) {
        if (await confirmDialog({ title: 'Отменить запись?', message: 'Время освободится, и его сможет занять другой клиент.', confirmText: 'Отменить запись', cancelText: 'Оставить', danger: true })) {
            fetch('/api/v1/bookings/' + bookingId + '/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                alert('Запись отменена');
                location.reload();
            })
            .catch(err => {
                alert('Ошибка при отмене: ' + err.message);
            });
        }
    };

    // === РАБОТА С ОТЗЫВАМИ ===
    const modal = document.getElementById('reviewModal');
    const closeBtn = document.querySelector('.review-modal-close');
    const form = document.getElementById('reviewForm');
    const stars = document.querySelectorAll('.star');
    const ratingInput = document.getElementById('reviewRating');
    const modalTitle = document.getElementById('reviewModalTitle');
    const successDiv = document.getElementById('reviewSuccess');

    let currentBookingId = null;
    let currentReviewId = null;

    // Открытие модалки
    function openReviewModal(bookingId, salonId, masterId, reviewId = null) {
        currentBookingId = bookingId;
        currentReviewId = reviewId;
        document.getElementById('reviewBookingId').value = bookingId;
        document.getElementById('reviewSalonId').value = salonId;
        document.getElementById('reviewMasterId').value = masterId || '';
        document.getElementById('reviewId').value = reviewId || '';

        // Очистка формы
        form.reset();
        successDiv.style.display = 'none';
        ratingInput.value = 0;
        stars.forEach(s => s.classList.remove('active'));
        document.getElementById('reviewComment').value = '';

        if (reviewId) {
            modalTitle.textContent = 'Редактировать отзыв';
            // Загрузить существующий отзыв
            fetch('/api/v1/reviews/' + reviewId)
                .then(r => r.json())
                .then(data => {
                    if (data.rating) {
                        setRating(data.rating);
                        document.getElementById('reviewComment').value = data.comment || '';
                    }
                })
                .catch(err => {
                    alert('Не удалось загрузить отзыв');
                });
        } else {
            modalTitle.textContent = 'Оставить отзыв';
        }

        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeReviewModal() {
        modal.classList.remove('active');
        document.body.style.overflow = '';
    }

    // Звёздный рейтинг
    function setRating(value) {
        ratingInput.value = value;
        stars.forEach(star => {
            const val = parseInt(star.dataset.value);
            star.classList.toggle('active', val <= value);
        });
    }

    stars.forEach(star => {
        star.addEventListener('click', function() {
            const value = parseInt(this.dataset.value);
            setRating(value);
        });
        star.addEventListener('mouseenter', function() {
            const value = parseInt(this.dataset.value);
            stars.forEach(s => {
                const v = parseInt(s.dataset.value);
                s.style.color = v <= value ? '#facc15' : '#d1d5db';
            });
        });
        star.addEventListener('mouseleave', function() {
            stars.forEach(s => {
                const v = parseInt(s.dataset.value);
                s.style.color = v <= parseInt(ratingInput.value) ? '#facc15' : '#d1d5db';
            });
        });
    });

    // Отправка формы
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        const rating = parseInt(ratingInput.value);
        if (rating === 0) {
            alert('Поставьте оценку');
            return;
        }
        const comment = document.getElementById('reviewComment').value.trim();
        const salonId = document.getElementById('reviewSalonId').value;
        const masterId = document.getElementById('reviewMasterId').value;
        const bookingId = document.getElementById('reviewBookingId').value;
        const reviewId = document.getElementById('reviewId').value;
        const files = document.getElementById('reviewPhotos').files;

        const formData = new FormData();
        formData.append('salon_id', salonId);
        formData.append('target_type', masterId ? 'master' : 'salon');
        if (masterId) formData.append('master_id', masterId);
        formData.append('rating', rating);
        formData.append('comment', comment);
        formData.append('booking_id', bookingId);
        for (let file of files) {
            formData.append('files', file);
        }

        let url = '/api/v1/reviews/create';
        let method = 'POST';
        if (reviewId) {
            url = '/api/v1/reviews/' + reviewId;
            method = 'PATCH';
            formData.delete('files');
            formData.append('_method', 'PATCH');
        }

        try {
            const res = await fetch(url, {
                method: method,
                body: formData
            });
            if (res.ok) {
                successDiv.style.display = 'block';
                setTimeout(() => {
                    closeReviewModal();
                    location.reload();
                }, 1000);
            } else {
                const data = await res.json();
                alert(data.detail || 'Ошибка при сохранении отзыва');
            }
        } catch (err) {
            toastNetworkError();
        }
    });

    // Обработчики кнопок "Оставить отзыв" и "Редактировать"
    document.addEventListener('click', function(e) {
        const addBtn = e.target.closest('.booking-review-add-btn');
        if (addBtn) {
            e.preventDefault();
            const bookingId = addBtn.dataset.bookingId;
            const salonId = addBtn.dataset.salonId;
            const masterId = addBtn.dataset.masterId;
            openReviewModal(bookingId, salonId, masterId);
        }

        const editBtn = e.target.closest('.booking-review-edit-btn');
        if (editBtn) {
            e.preventDefault();
            const bookingId = editBtn.dataset.bookingId;
            const reviewId = editBtn.dataset.reviewId;
            fetch('/api/v1/reviews/' + reviewId)
                .then(r => r.json())
                .then(data => {
                    openReviewModal(bookingId, data.salon_id, data.master_id, reviewId);
                })
                .catch(() => {
                    alert('Не удалось загрузить данные отзыва');
                });
        }
    });

    // Закрытие по клику на оверлей
    modal.addEventListener('click', function(e) {
        if (e.target === this) {
            closeReviewModal();
        }
    });

    // Закрытие по Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeReviewModal();
        }
    });

    window.closeReviewModal = closeReviewModal;
    window.openReviewModal = openReviewModal;
});