// static/src/js/business/tabs/services.js

(function() {
    'use strict';

    const modal = document.getElementById('servicesModal');
    const modalTitle = document.getElementById('servicesModalTitle');
    const form = document.getElementById('servicesForm');
    const closeBtn = document.getElementById('servicesModalClose');
    const cancelBtn = document.getElementById('servicesModalCancel');
    const addBtn = document.getElementById('servicesAddBtn');

    // Открытие модалки для добавления
    if (addBtn) {
        addBtn.addEventListener('click', function(e) {
            e.preventDefault();
            modalTitle.textContent = 'Добавить услугу';
            form.reset();
            document.getElementById('serviceId').value = '';
            form.action = '/api/v1/services/create';
            modal.classList.add('active');
        });
    }

    // Закрытие модалки
    function closeModal() {
        modal.classList.remove('active');
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', closeModal);
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', closeModal);
    }

    // Закрытие по клику на оверлей
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal();
            }
        });
    }

    // Закрытие по Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && modal.classList.contains('active')) {
            closeModal();
        }
    });

    // Глобальная функция для редактирования
    window.openEditModal = function(id, name, price, duration, desc, masterId) {
        if (!modal) return;
        modalTitle.textContent = 'Редактировать услугу';
        document.getElementById('serviceId').value = id;
        document.getElementById('serviceName').value = name;
        document.getElementById('servicePrice').value = price;
        document.getElementById('serviceDuration').value = duration;
        document.getElementById('serviceDescription').value = desc;
        document.getElementById('serviceMaster').value = masterId;
        form.action = '/api/v1/services/' + id + '/update';
        modal.classList.add('active');
    };
    
})();