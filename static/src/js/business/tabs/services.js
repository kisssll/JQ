// static/src/js/business/tabs/services.js
import { confirmDialog, toastError } from '../../ui-feedback.js';

(function() {
    'use strict';

    const modal = document.getElementById('servicesModal');
    const modalTitle = document.getElementById('servicesModalTitle');
    const form = document.getElementById('servicesForm');
    const closeBtn = document.getElementById('servicesModalClose');
    const cancelBtn = document.getElementById('servicesModalCancel');
    const addBtn = document.getElementById('servicesAddBtn');
    const priceMode = document.getElementById('servicePriceMode');
    const priceMaxRow = document.getElementById('servicePriceMaxRow');
    const priceMaxInput = document.getElementById('servicePriceMax');

    function updatePriceMode() {
        const isRange = priceMode && priceMode.value === 'range';
        if (priceMaxRow) priceMaxRow.style.display = isRange ? '' : 'none';
        if (priceMaxInput) priceMaxInput.required = isRange;
        if (!isRange && priceMaxInput) priceMaxInput.value = '';
    }

    if (priceMode) {
        priceMode.addEventListener('change', updatePriceMode);
    }

    if (form) {
        form.addEventListener('submit', function(e) {
            if (!priceMode || priceMode.value !== 'range') return;

            const price = Number(document.getElementById('servicePrice').value);
            const maxPrice = Number(priceMaxInput.value);
            if (!Number.isFinite(price) || !Number.isFinite(maxPrice) || maxPrice >= price) return;

            e.preventDefault();
            toastError('Верхняя граница цены не может быть меньше нижней.');
            priceMaxInput.focus();
        });
    }

    // Открытие модалки для добавления
    if (addBtn) {
        addBtn.addEventListener('click', function(e) {
            e.preventDefault();
            modalTitle.textContent = 'Добавить услугу';
            form.reset();
            document.getElementById('serviceId').value = '';
            form.action = '/api/v1/services/create';
            updatePriceMode();
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
    window.openEditModal = function(id, name, price, priceMax, duration, desc, masterIds, category) {
        if (!modal) return;
        modalTitle.textContent = 'Редактировать услугу';
        document.getElementById('serviceId').value = id;
        document.getElementById('serviceName').value = name;
        document.getElementById('servicePrice').value = price;
        if (priceMode) priceMode.value = priceMax === null ? 'fixed' : 'range';
        if (priceMaxInput) priceMaxInput.value = priceMax === null ? '' : priceMax;
        updatePriceMode();
        document.getElementById('serviceDuration').value = duration;
        document.getElementById('serviceDescription').value = desc;
        const masterSelect = document.getElementById('serviceMaster');
        Array.from(masterSelect.options).forEach(option => {
            option.selected = masterIds.includes(Number(option.value));
        });
        const catSel = document.getElementById('serviceCategory');
        if (catSel) catSel.value = category || '';
        form.action = '/api/v1/services/' + id + '/update';
        modal.classList.add('active');
    };

    document.addEventListener('change', async function(e) {
        const input = e.target.closest('.service-photo-input');
        if (!input || !input.files.length) return;
        const formData = new FormData();
        Array.from(input.files).forEach(file => formData.append('files', file));
        try {
            const response = await fetch(`/api/v1/upload/service/${input.dataset.serviceId}/photo`, {
                method: 'POST',
                body: formData,
            });

            document.addEventListener('click', async function(e) {
                const button = e.target.closest('.service-photo-delete');
                if (!button) return;
                const confirmed = await confirmDialog({
                    title: 'Удалить фото услуги?',
                    message: 'Фото будет удалено без возможности восстановления.',
                    confirmText: 'Удалить',
                    danger: true,
                });
                if (!confirmed) return;
                try {
                    const response = await fetch(`/api/v1/upload/service/photo/${button.dataset.photoId}/delete`, {
                        method: 'POST',
                    });
                    if (!response.ok) {
                        const data = await response.json().catch(() => ({}));
                        toastError(data.detail || 'Не удалось удалить фото услуги');
                        return;
                    }
                    button.closest('.service-photo-preview').remove();
                } catch (error) {
                    toastError('Не удалось удалить фото услуги');
                }
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                toastError(data.detail || 'Не удалось загрузить фото услуги');
                return;
            }
            window.location.reload();
        } catch (error) {
            toastError('Не удалось загрузить фото услуги');
        } finally {
            input.value = '';
        }
    });
    
})();