# app/web/pages/business/tabs/employees.py
import html
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Master, User as UserModel, SalonMember, SalonRole, AdminAudit, SALON_PERMISSION_KEYS
from app.web.components.icons import (
    ICON_EDIT,
    ICON_USER_PLUS,
    ICON_TRASH,
    ICON_POWER,
    ICON_USER,
    ICON_CHEVRON_DOWN,
    ICON_FILE_TEXT,
)
from app.web.components.hint import hint as _hint

_ERROR_MESSAGES = {
    "bad_phone": "Не удалось распознать телефон. Формат: +7 999 123-45-67 или 8 999 123-45-67.",
    "bad_role": "Неизвестная роль.",
    "member_exists": "Этот пользователь уже участник салона.",
}

ROLE_LABELS = {
    SalonRole.OWNER: "Владелец",
    SalonRole.MANAGER: "Управляющий",
    SalonRole.ADMIN: "Админ",
}

PERMISSION_LABELS = {
    "manage_salon": "Настройки салона",
    "manage_owners": "Совладельцы",
    "manage_admins": "Админы",
    "manage_masters": "Мастера и услуги",
    "manage_schedule": "Расписание",
    "manage_promotions": "Акции",
    "manage_reviews": "Отзывы",
    "view_finances": "Финансы",
    "manage_tariff": "Тариф",
    "view_audit_log": "Лог действий",
    "manage_inventory": "Склад",
    "manage_payroll": "Зарплаты",
}


async def render_employees_tab(db: AsyncSession, salon, masters, user, membership, perms, query_params=None) -> str:
    """Объединённая вкладка «Сотрудники»: мастера + участники салона + лог действий."""
    
    query_params = query_params or {}
    notice = {
        "added": query_params.get("added"),
        "temp_pw": query_params.get("temp_pw"),
        "error": query_params.get("error"),
    }
    
    is_creator = membership.is_creator
    can_manage_masters = perms.get("manage_masters", False)
    can_manage_owners = perms.get("manage_owners", False)
    can_manage_admins = perms.get("manage_admins", False)
    can_view_audit = perms.get("view_audit_log", False)
    is_full_admin = is_creator or can_manage_owners or can_manage_admins

    # ----- Баннер уведомлений -----
    notice_banner = ""
    if notice.get("temp_pw"):
        safe_pw = html.escape(notice["temp_pw"], quote=True)
        notice_banner = (
            '<div class="notice-banner success">'
            f'Сотрудник добавлен. Временный пароль (передайте лично, он больше нигде не отобразится): '
            f'<code class="temp-pw">{safe_pw}</code>'
            '</div>'
        )
    elif notice.get("added"):
        notice_banner = '<div class="notice-banner success">Сотрудник добавлен.</div>'
    elif notice.get("error"):
        message = _ERROR_MESSAGES.get(notice["error"], "Что-то пошло не так, попробуйте ещё раз.")
        notice_banner = f'<div class="notice-banner error">{message}</div>'

    # ----- БЛОК УЧАСТНИКОВ (владельцы/админы) — только для полного доступа -----
    staff_section = ""
    if is_full_admin:
        members_result = await db.execute(
            select(SalonMember, UserModel)
            .join(UserModel, UserModel.id == SalonMember.user_id)
            .where(SalonMember.salon_id == salon.id, SalonMember.is_active == True)
            .order_by(SalonMember.is_creator.desc(), SalonMember.created_at.asc())
        )
        members = members_result.all()

        staff_rows = ""
        for member, u in members:
            role_label = ROLE_LABELS.get(member.role, "Админ")
            creator_badge = ' <span class="creator-badge">(создатель)</span>' if member.is_creator else ""
            perms_summary = ", ".join(
                PERMISSION_LABELS[k] for k in SALON_PERMISSION_KEYS
                if (member.is_creator or member.permissions.get(k, False))
            ) or "—"

            is_self = user.id == member.user_id
            if member.role == SalonRole.MANAGER:
                # Управляющего может редактировать/снять только создатель салона;
                # снять (но не редактировать права) может также сам управляющий.
                can_edit_perms_this = (not member.is_creator) and is_creator
                can_remove_this = (not member.is_creator) and (is_creator or is_self)
            else:
                can_edit_perms_this = (not member.is_creator) and (
                    (member.role == SalonRole.OWNER and can_manage_owners) or
                    (member.role == SalonRole.ADMIN and can_manage_admins)
                )
                can_remove_this = can_edit_perms_this

            member_name = (u.full_name or u.phone).replace("'", "").replace('"', "")
            effective_perms = {k: (member.is_creator or member.permissions.get(k, False)) for k in SALON_PERMISSION_KEYS}
            perms_json = json.dumps(effective_perms)

            actions = ""
            if can_edit_perms_this:
                actions += f"""<button class="action-btn edit-btn" onclick='openPermissionsModal({member.id}, "{member_name}", {perms_json})' title="Права">{ICON_EDIT}</button>"""
            if can_remove_this and not member.is_creator:
                actions += f"""<button class="action-btn" onclick="resetMemberPassword({member.id})" title="Сбросить пароль">🔑</button>"""
            if can_remove_this:
                actions += f"""<button class="action-btn delete-btn" onclick="removeMember({member.id}, '{member_name}')" title="Снять">{ICON_TRASH}</button>"""

            staff_rows += f"""
            <tr>
                <td>
                    <strong>{u.full_name or '—'}</strong>{creator_badge}
                    <div class="employee-phone">{u.phone}</div>
                </td>
                <td>{role_label}</td>
                <td class="perms-cell">{perms_summary}</td>
                <td>
                    <div class="employee-actions">
                        {actions}
                    </div>
                </td>
            </tr>"""

        if not staff_rows:
            staff_rows = '<tr><td colspan="4" class="empty-state">Пока нет других участников</td></tr>'

        invite_btn = ""
        if can_manage_owners or can_manage_admins:
            role_options = ""
            if can_manage_owners:
                role_options += '<option value="owner">Владелец</option>'
            if is_creator:
                # Управляющего назначает только создатель салона — обычному
                # совладельцу с правом manage_owners эта опция не предлагается,
                # чтобы не показывать пункт, который на бэкенде всё равно 403.
                role_options += '<option value="manager">Управляющий</option>'
            if can_manage_admins:
                role_options += '<option value="admin">Админ</option>'
            invite_btn = f"""
            <button class="btn-primary add-btn" onclick="document.getElementById('inviteMemberModal').classList.add('active')">
                {ICON_USER_PLUS} Добавить участника
            </button>
            """

        # Форма добавления участника
        invite_form = f"""
        <div class="modal-overlay" id="inviteMemberModal">
            <div class="modal-box">
                <button class="modal-close" onclick="document.getElementById('inviteMemberModal').classList.remove('active')">&times;</button>
                <h2>Добавить участника</h2>
                <form id="staffAddForm" action="/api/v1/business/staff/add-web" method="post">
                    <input type="hidden" name="salon_id" value="{salon.id}">
                    <div class="form-group">
                        <label for="invitePhone">Телефон *</label>
                        <input type="tel" id="invitePhone" name="phone" value="+7" required placeholder="+7XXXXXXXXXX">
                    </div>
                    <div class="form-group">
                        <label for="inviteName">Имя (если новый пользователь)</label>
                        <input type="text" id="inviteName" name="full_name" placeholder="Имя">
                    </div>
                    <div class="form-group">
                        <label for="inviteRole">Роль</label>
                        <select id="inviteRole" name="role">{role_options}</select>
                    </div>
                    <button type="submit" class="btn-primary" style="width:100%">Добавить</button>
                </form>
            </div>
        </div>
        """

        # Модалка прав
        permission_checkboxes = "".join(
            f'<label class="checkbox-label"><input type="checkbox" id="perm-{k}"> {v}</label>'
            for k, v in PERMISSION_LABELS.items()
        )
        permissions_modal = f"""
        <div class="modal-overlay" id="editPermissionsModal">
            <div class="modal-box">
                <button class="modal-close" onclick="document.getElementById('editPermissionsModal').classList.remove('active')">&times;</button>
                <h2 id="permissionsModalTitle">Права участника</h2>
                <div id="permissionsCheckboxes">{permission_checkboxes}</div>
                <button type="button" class="btn-primary" style="width:100%;margin-top:1rem" onclick="submitPermissions()">Сохранить</button>
            </div>
        </div>
        """

        staff_section = f"""
        <div class="staff-section">
            <div class="section-header">
                <h2>Участники салона</h2>
                {invite_btn}
            </div>
            <div class="card table-wrap">
                <table>
                    <thead>
                        <tr><th>Участник</th><th>Роль</th><th>Права</th><th style="width:100px">Действия</th></tr>
                    </thead>
                    <tbody>{staff_rows}</tbody>
                </table>
            </div>
        </div>
        {invite_form}
        {permissions_modal}
        """

    # ----- СЕКЦИЯ МАСТЕРОВ -----
    active_masters = len([m for m in masters if m.is_active])
    total_masters = len(masters)

    masters_rows = ""
    for m in masters:
        user_result = await db.execute(select(UserModel).where(UserModel.id == m.user_id))
        master_user = user_result.scalar_one_or_none()
        user_name = master_user.full_name if master_user else "—"
        phone = master_user.phone if master_user else "—"

        status_class = "on" if m.is_active else "off"
        status_text = "На смене" if m.is_active else "Отключён"

        actions = f"""
            <button class="action-btn edit-btn" onclick="editEmployee({m.id}, '{user_name}', '{m.specialization}', {m.experience_years})" title="Редактировать">{ICON_EDIT}</button>
            <button class="action-btn toggle-btn {status_class}" onclick="toggleEmployee({m.id}, '{user_name}', {str(m.is_active).lower()})" title="{'Отключить' if m.is_active else 'Включить'}">{ICON_POWER}</button>
        """
        if can_manage_masters:
            actions += f'<button class="action-btn" onclick="resetMasterPassword({m.id})" title="Сбросить пароль">🔑</button>'
            actions += f'<button class="action-btn delete-btn" onclick="deleteEmployee({m.id}, \'{user_name}\')" title="Удалить">{ICON_TRASH}</button>'

        masters_rows += f"""
        <tr>
            <td>
                <div class="employee-cell">
                    <div class="employee-avatar">{user_name[0].upper() if user_name else '?'}</div>
                    <div>
                        <div class="employee-name">{user_name}</div>
                        <div class="employee-phone">{phone}</div>
                    </div>
                </div>
            </td>
            <td>{m.specialization}</td>
            <td>{m.experience_years} лет</td>
            <td>⭐ {m.rating}</td>
            <td>
                <span class="status-badge {status_class}">
                    {ICON_POWER} {status_text}
                </span>
            </td>
            <td>
                <div class="employee-actions">
                    {actions}
                </div>
            </td>
        </tr>"""

    if not masters_rows:
        masters_rows = '<tr><td colspan="6" class="empty-state">Пока нет мастеров</td></tr>'

    add_master_btn = ""
    if can_manage_masters:
        add_master_btn = f"""
        <button class="btn-primary add-btn" onclick="document.getElementById('addEmployeeModal').classList.add('active')">
            {ICON_USER_PLUS} Добавить мастера
        </button>
        """

    masters_section = f"""
    <div class="employees-section">
        <div class="section-header">
            <h2>Мастера</h2>
            {add_master_btn}
        </div>
        <div class="stats-group">
            <div class="stat-card compact">
                <span class="stat-value">{total_masters}</span>
                <span class="stat-label">Всего</span>
            </div>
            <div class="stat-card compact">
                <span class="stat-value" style="color:#22c55e">{active_masters}</span>
                <span class="stat-label">Активных</span>
            </div>
        </div>
        <div class="card table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Мастер</th>
                        <th>Специализация</th>
                        <th>Опыт</th>
                        <th>Рейтинг</th>
                        <th>Статус</th>
                        <th style="width:120px">Действия {_hint("Отключить — временно скрыть мастера из записи, не теряя историю визитов и зарплат. Удалить — убрать мастера из салона полностью (аккаунт пользователя при этом сохраняется).")}</th>
                    </tr>
                </thead>
                <tbody>
                    {masters_rows}
                </tbody>
            </table>
        </div>
    </div>
    """

    # ----- МОДАЛКА ДОБАВЛЕНИЯ МАСТЕРА -----
    add_master_modal = f"""
    <div class="modal-overlay" id="addEmployeeModal">
        <div class="modal-box">
            <button class="modal-close" onclick="document.getElementById('addEmployeeModal').classList.remove('active')">&times;</button>
            <h2>Добавить мастера</h2>
            <form id="employeeForm" action="/api/v1/master/create-web" method="post">
                <input type="hidden" name="master_id" id="employeeId">
                <div class="form-group">
                    <label for="employeeName">Имя *</label>
                    <input type="text" name="full_name" id="employeeName" required placeholder="Имя мастера">
                </div>
                <div class="form-group">
                    <label for="employeePhone">Телефон *</label>
                    <input type="tel" name="phone" id="employeePhone" value="+7" required placeholder="+7XXXXXXXXXX">
                </div>
                <div class="form-group">
                    <label for="employeeSpec">Специализация *</label>
                    <input type="text" name="specialization" id="employeeSpec" required placeholder="Например: барбер-стилист">
                </div>
                <div class="form-group">
                    <label for="employeeExp">Опыт (лет)</label>
                    <input type="number" name="experience_years" id="employeeExp" value="0">
                </div>
                <button type="submit" class="btn-primary" style="width:100%">Сохранить</button>
            </form>
        </div>
    </div>
    """

    # МОДАЛКА РЕДАКТИРОВАНИЯ МАСТЕРА
    edit_master_modal = f"""
    <div class="modal-overlay" id="editEmployeeModal">
        <div class="modal-box">
            <button class="modal-close" onclick="document.getElementById('editEmployeeModal').classList.remove('active')">&times;</button>
            <h2>Редактировать мастера</h2>
            <form id="editMasterForm" method="post">
                <input type="hidden" name="master_id" id="editMasterId">
                <div class="form-group">
                    <label for="editMasterName">Имя *</label>
                    <input type="text" id="editMasterName" name="full_name" required>
                </div>
                <div class="form-group">
                    <label for="editMasterSpec">Специализация *</label>
                    <input type="text" id="editMasterSpec" name="specialization" required>
                </div>
                <div class="form-group">
                    <label for="editMasterExp">Опыт (лет)</label>
                    <input type="number" id="editMasterExp" name="experience_years" value="0">
                </div>
                <button type="submit" class="btn-primary" style="width:100%">Сохранить</button>
            </form>
        </div>
    </div>
    """

    # ----- ЛОГ ДЕЙСТВИЙ (только для владельца или с правом view_audit_log) -----
    audit_section = ""
    if can_view_audit:
        audit_result = await db.execute(
            select(AdminAudit).where(AdminAudit.salon_id == salon.id).order_by(AdminAudit.created_at.desc()).limit(50)
        )
        audit_rows = ""
        for a in audit_result.scalars().all():
            audit_rows += f"""
            <tr>
                <td class="audit-time">{a.created_at.strftime('%d.%m.%Y %H:%M')}</td>
                <td>{a.action}</td>
                <td>{a.detail or '—'}</td>
            </tr>"""
        if not audit_rows:
            audit_rows = '<tr><td colspan="3" class="empty-state">Пока пусто</td></tr>'

        audit_section = f"""
        <div class="audit-section">
            <h2>{ICON_FILE_TEXT} Лог действий</h2>
            <div class="card table-wrap">
                <table>
                    <thead><tr><th>Когда</th><th>Действие</th><th>Детали</th></tr></thead>
                    <tbody>{audit_rows}</tbody>
                </table>
            </div>
        </div>
        """

    # ----- СБОРКА (порядок: участники → мастера → лог) -----
    html = f"""
    <div id="tab-employees" class="tab-content">
        {notice_banner}

        <!-- Секция участников (только для владельца/админа с правами) -->
        {staff_section}

        <!-- Секция мастеров -->
        {masters_section}

        <!-- Лог действий -->
        {audit_section}

        <!-- Модалки -->
        {add_master_modal}
        {edit_master_modal}

        <!-- Реквизиты нового сотрудника/мастера (попап после добавления/сброса) -->
        <div class="modal-overlay" id="credentialsModal">
            <div class="modal-box">
                <button class="modal-close" onclick="document.getElementById('credentialsModal').classList.remove('active')">&times;</button>
                <h2>Реквизиты для входа</h2>
                <p class="text-muted" style="font-size:0.85rem;margin-bottom:1rem">Передайте их сотруднику. Пароль показывается один раз — скопируйте или отправьте на почту салона.</p>
                <div class="creds-row"><span>Сотрудник</span><b id="credName">—</b></div>
                <div class="creds-row"><span>Логин (телефон)</span><b id="credLogin">—</b></div>
                <div class="creds-row"><span>Временный пароль</span><code id="credPassword">—</code></div>
                <div class="creds-actions">
                    <button type="button" id="credCopyBtn" class="btn-outline" onclick="copyCredentials()">Копировать</button>
                    <button type="button" class="btn-primary" onclick="sendCredentialsToSalonEmail()">Отправить на почту салона</button>
                </div>
                <div id="credEmailResult" class="creds-email-result"></div>
            </div>
        </div>
    </div>
    """
    return html