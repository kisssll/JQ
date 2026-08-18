// static/src/js/business/tabs/employees.js
import { confirmDialog, toastError } from '../../ui-feedback.js';

(function() {
    // Переменные для модального окна
    let currentEmployeeId = null;
    let currentPermissionsMemberId = null;

    // ---- Мастера ----

    // Открытие модалки редактирования мастера
    window.editEmployee = function(id, name, spec, exp) {
        const modal = document.getElementById('editEmployeeModal');
        if (!modal) return;
        document.getElementById('editMasterId').value = id;
        document.getElementById('editMasterName').value = name;
        document.getElementById('editMasterSpec').value = spec;
        document.getElementById('editMasterExp').value = exp;
        document.getElementById('editMasterForm').action = '/api/v1/master/' + id + '/update';
        modal.classList.add('active');
    };

    // Включение/отключение мастера
    window.toggleEmployee = async function(id, name, isActive) {
        const action = isActive ? 'отключить' : 'включить';
        if (!await confirmDialog({ title: `${action.charAt(0).toUpperCase() + action.slice(1)} мастера «${name}»?`, confirmText: action.charAt(0).toUpperCase() + action.slice(1) })) return;
        fetch(`/api/v1/master/${id}/toggle`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else toastError('Ошибка при изменении статуса');
            });
    };

    // Удаление мастера
    window.deleteEmployee = async function(id, name) {
        if (!await confirmDialog({ title: `Удалить мастера «${name}»?`, message: 'Это действие нельзя отменить.', confirmText: 'Удалить', danger: true })) return;
        fetch(`/api/v1/master/${id}/delete`, { method: 'POST' })
            .then(r => {
                if (r.ok) location.reload();
                else toastError('Ошибка при удалении');
            });
    };

    // ---- Участники (владельцы/админы) ----

    // Открытие модалки прав
    window.openPermissionsModal = function(memberId, name, currentPermissions) {
        currentPermissionsMemberId = memberId;
        const modal = document.getElementById('editPermissionsModal');
        if (!modal) return;
        document.getElementById('permissionsModalTitle').textContent = 'Права: ' + name;
        for (const k in currentPermissions) {
            const el = document.getElementById('perm-' + k);
            if (el) el.checked = !!currentPermissions[k];
        }
        modal.classList.add('active');
    };

    // Сохранение прав
    window.submitPermissions = function() {
        const keys = ["manage_salon", "manage_owners", "manage_admins", "manage_masters",
                      "manage_schedule", "manage_promotions", "manage_reviews",
                      "view_finances", "manage_tariff", "view_audit_log",
                      "manage_inventory", "manage_payroll"];
        const permissions = {};
        for (const k of keys) {
            const el = document.getElementById('perm-' + k);
            permissions[k] = el ? el.checked : false;
        }
        fetch(`/api/v1/business/staff/${currentPermissionsMemberId}/permissions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ permissions })
        }).then(async r => {
            if (r.ok) location.reload();
            else { const d = await r.json(); alert(d.detail || 'Ошибка'); }
        });
    };

    // Снятие участника
    window.removeMember = async function(memberId, name) {
        if (!await confirmDialog({ title: `Снять «${name}» с бизнес-панели салона?`, confirmText: 'Снять доступ', danger: true })) return;
        fetch(`/api/v1/business/staff/${memberId}`, { method: 'DELETE' })
            .then(async r => {
                if (r.ok) location.reload();
                else { const d = await r.json(); alert(d.detail || 'Ошибка'); }
            });
    };

    // ---- Закрытие модалок ----

    function closeModal(modalId) {
        const el = document.getElementById(modalId);
        if (el) el.classList.remove('active');
    }

    document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', function() {
            const modal = this.closest('.modal-overlay');
            if (modal) modal.classList.remove('active');
        });
    });

    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay.active').forEach(el => el.classList.remove('active'));
        }
    });

    // При клике на кнопку "Добавить мастера" (если она есть) — сброс формы
    document.querySelector('[onclick*="addEmployeeModal"]')?.addEventListener('click', function() {
        const form = document.getElementById('employeeForm');
        if (form) form.reset();
        document.getElementById('employeeId').value = '';
        form.action = '/api/v1/master/create-web';
    });

    // ===== Функции для мобильных карточек =====
    // Переключаем класс .open на родительском элементе карточки
    function toggleStaffCard(header) {
        const card = header.closest('.staff-card');
        if (card) {
            card.classList.toggle('open');
        }
    }

    function toggleMasterCard(header) {
        const card = header.closest('.master-card');
        if (card) {
            card.classList.toggle('open');
        }
    }

    // Навешиваем обработчики через делегирование на контейнеры карточек
    document.addEventListener('click', function(e) {
        // Карточки участников
        const staffHeader = e.target.closest('.staff-card-header');
        if (staffHeader) {
            e.stopPropagation();
            toggleStaffCard(staffHeader);
            return;
        }
        // Карточки мастеров
        const masterHeader = e.target.closest('.master-card-header');
        if (masterHeader) {
            e.stopPropagation();
            toggleMasterCard(masterHeader);
            return;
        }
    });

    console.log('Employees JS loaded');
})();