// static/src/js/business/tabs/promos.js

(function() {
    'use strict';

    // Добавление акции
    const addBtn = document.getElementById('promosAddBtn');
    const addModal = document.getElementById('promosAddModal');
    const closeAddBtn = document.getElementById('promosModalCloseAdd');

    if (addBtn && addModal) {
        addBtn.addEventListener('click', function(e) {
            e.preventDefault();
            addModal.classList.add('active');
        });
    }

    if (closeAddBtn && addModal) {
        closeAddBtn.addEventListener('click', function(e) {
            e.preventDefault();
            addModal.classList.remove('active');
        });
    }

    if (addModal) {
        addModal.addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    }

    // Редактирование акции
    const editModal = document.getElementById('promosEditModal');
    const closeEditBtn = document.getElementById('promosModalCloseEdit');
    const editCancelBtn = document.getElementById('promosEditCancel');
    const editForm = document.getElementById('promosEditForm');

    // Глобальная функция для открытия модалки редактирования
    window.editPromo = function(id, title, description, tag) {
        if (!editModal) return;
        // Заполняем поля
        document.getElementById('editPromoId').value = id;
        document.getElementById('promoTitleEdit').value = title;
        document.getElementById('promoDescEdit').value = description;
        document.getElementById('promoTagEdit').value = tag;
        // Устанавливаем action формы
        editForm.action = '/api/v1/business/my-salon/promotions/' + id + '/update';
        editModal.classList.add('active');
    };

    if (closeEditBtn && editModal) {
        closeEditBtn.addEventListener('click', function(e) {
            e.preventDefault();
            editModal.classList.remove('active');
        });
    }

    if (editCancelBtn && editModal) {
        editCancelBtn.addEventListener('click', function(e) {
            e.preventDefault();
            editModal.classList.remove('active');
        });
    }

    if (editModal) {
        editModal.addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    }

    // Удаление акции
    window.deletePromo = function(id, title) {
        if (confirm('Удалить акцию "' + title + '"? Это действие нельзя отменить.')) {
            fetch('/api/v1/business/my-salon/promotions/' + id + '/delete', { method: 'POST' })
                .then(r => {
                    if (r.ok) location.reload();
                    else alert('Ошибка при удалении');
                })
                .catch(() => alert('Ошибка сети'));
        }
    };

    // Закрытие по Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            if (addModal) addModal.classList.remove('active');
            if (editModal) editModal.classList.remove('active');
            const loyaltyModal = document.getElementById('addLoyaltyOfferModal');
            if (loyaltyModal) loyaltyModal.classList.remove('active');
        }
    });

    // ---- Функции лояльности (перенесены из my-salon.js) ----

    // Сохранение настроек лояльности
    window.saveLoyaltySettings = async function(salonId) {
        const body = {
            regular_client_discount_percent: parseInt(document.getElementById('loyaltyRegularPercent').value) || 0,
            regular_client_visits_threshold: document.getElementById('loyaltyVisitsThreshold').value
                ? parseInt(document.getElementById('loyaltyVisitsThreshold').value) : null,
            bonus_accrual_percent: parseFloat(document.getElementById('loyaltyBonusAccrual').value) || 0,
        };
        try {
            const res = await fetch(`/api/v1/loyalty/salon/${salonId}/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (res.ok) {
                alert('Настройки лояльности сохранены');
            } else {
                const d = await res.json();
                alert(d.detail || 'Ошибка');
            }
        } catch (e) {
            alert('Ошибка сети');
        }
    };

    // Добавление именной скидки / промокода
    window.addLoyaltyOffer = async function(salonId) {
        const title = document.getElementById('loyaltyOfferTitle').value.trim();
        const discount_percent = parseInt(document.getElementById('loyaltyOfferPercent').value);
        const promo_code = document.getElementById('loyaltyOfferCode').value.trim() || null;
        if (!title || !discount_percent) {
            alert('Заполните название и размер скидки');
            return;
        }
        try {
            const res = await fetch(`/api/v1/loyalty/salon/${salonId}/offers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, discount_percent, promo_code })
            });
            if (res.ok) {
                location.reload();
            } else {
                const d = await res.json();
                alert(d.detail || 'Ошибка');
            }
        } catch (e) {
            alert('Ошибка сети');
        }
    };

    // Удаление именной скидки
    window.deleteLoyaltyOffer = function(id, title) {
        if (!confirm(`Удалить скидку «${title}»?`)) return;
        const salonId = window.salonId; // теперь определён
        if (!salonId) {
            alert('Не удалось определить салон');
            return;
        }
        fetch(`/api/v1/loyalty/salon/${salonId}/offers/${id}`, { method: 'DELETE' })
            .then(r => {
                if (r.ok) location.reload();
                else r.json().then(d => alert(d.detail || 'Ошибка'));
            });
    };

    // Закрытие модалок лояльности
    document.querySelectorAll('.my-salon-modal-close').forEach(btn => {
        btn.addEventListener('click', function() {
            this.closest('.my-salon-modal-overlay').classList.remove('active');
        });
    });

    document.querySelectorAll('.my-salon-modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    });

})();