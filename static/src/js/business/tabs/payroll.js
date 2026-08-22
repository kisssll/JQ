// static/src/js/business/tabs/payroll.js

(function() {
    'use strict';

    // === Переключение карточек (аккордеон) ===
    function togglePayrollCard(header) {
        const body = header.nextElementSibling;
        const chevron = header.querySelector('.payroll-card-chevron');
        if (body) {
            body.classList.toggle('open');
            if (chevron) {
                if (body.classList.contains('open')) {
                    chevron.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>`;
                } else {
                    chevron.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`;
                }
            }
        }
    }

    // Назначаем обработчики на все заголовки карточек
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.payroll-card-header').forEach(function(header) {
            header.addEventListener('click', function(e) {
                e.stopPropagation();
                togglePayrollCard(this);
            });
        });
    });

    // === Модалки (сохраняем глобальные функции для onclick) ===

    window.openRateModal = function(masterId, salary, commission) {
        const modal = document.getElementById('rateModal');
        if (!modal) return;
        document.getElementById('rateSalary').value = salary;
        document.getElementById('rateCommission').value = commission;
        document.getElementById('rateForm').dataset.masterId = masterId;
        modal.classList.add('active');
    };

    window.openAdjustmentModal = function(masterId) {
        const modal = document.getElementById('adjustmentModal');
        if (!modal) return;
        document.getElementById('adjustmentAmount').value = '';
        document.getElementById('adjustmentReason').value = '';
        document.getElementById('adjustmentForm').dataset.masterId = masterId;
        modal.classList.add('active');
    };

    window.closeModal = function(id) {
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
    };

    // === Обработчики форм модалок ===

    document.addEventListener('DOMContentLoaded', function() {
        const rateForm = document.getElementById('rateForm');
        if (rateForm) {
            rateForm.addEventListener('submit', function(e) {
                e.preventDefault();
                const masterId = this.dataset.masterId;
                if (!masterId) return;
                this.action = '/api/v1/payroll/master/' + masterId + '/settings';
                this.method = 'post';
                this.submit();
            });
        }

        const adjustmentForm = document.getElementById('adjustmentForm');
        if (adjustmentForm) {
            adjustmentForm.addEventListener('submit', function(e) {
                e.preventDefault();
                const masterId = this.dataset.masterId;
                if (!masterId) return;
                // period_month берётся из поля #adjustmentMonth в самой форме
                this.action = '/api/v1/payroll/master/' + masterId + '/adjustment';
                this.method = 'post';
                this.submit();
            });
        }
    });

    // Закрытие модалок по клику на оверлей
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('payroll-modal-overlay')) {
            e.target.classList.remove('active');
        }
    });

    // Закрытие по Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.payroll-modal-overlay.active').forEach(function(el) {
                el.classList.remove('active');
            });
        }
    });
})();