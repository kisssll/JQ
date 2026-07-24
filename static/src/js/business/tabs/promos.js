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
        }
    });

})();