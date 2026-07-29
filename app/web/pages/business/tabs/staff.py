# app/web/pages/business/tabs/staff.py
import html
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import SalonMember, SalonRole, AdminAudit, User as UserModel, SALON_PERMISSION_KEYS
from app.web.components.hint import hint as _hint

_ERROR_MESSAGES = {
    "bad_phone": "Не удалось распознать телефон. Формат: +7 999 123-45-67 или 8 999 123-45-67.",
    "bad_role": "Неизвестная роль.",
    "member_exists": "Этот пользователь уже участник салона.",
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


async def render_staff_tab(db: AsyncSession, salon, user, membership: SalonMember, perms: dict, notice: dict = None) -> str:
    """Вкладка «Сотрудники» — совладельцы и админы салона, их права, лог действий."""

    notice = notice or {}
    notice_banner = ""
    if notice.get("temp_pw"):
        safe_pw = html.escape(notice["temp_pw"], quote=True)
        notice_banner = (
            '<div style="background:#DCFCE7;color:#166534;border:1px solid #86EFAC;'
            'border-radius:0.5rem;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.875rem">'
            f'Сотрудник добавлен. Временный пароль (передайте лично, он больше нигде не отобразится): '
            f'<code style="background:white;padding:0.15rem 0.5rem;border-radius:0.25rem;font-weight:700">{safe_pw}</code>'
            '</div>'
        )
    elif notice.get("added"):
        notice_banner = (
            '<div style="background:#DCFCE7;color:#166534;border:1px solid #86EFAC;'
            'border-radius:0.5rem;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.875rem">'
            'Сотрудник добавлен.</div>'
        )
    elif notice.get("error"):
        message = _ERROR_MESSAGES.get(notice["error"], "Что-то пошло не так, попробуйте ещё раз.")
        notice_banner = (
            '<div style="background:#FEE2E2;color:#991B1B;border:1px solid #FCA5A5;'
            'border-radius:0.5rem;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.875rem">'
            f'{message}</div>'
        )

    members_result = await db.execute(
        select(SalonMember, UserModel)
        .join(UserModel, UserModel.id == SalonMember.user_id)
        .where(SalonMember.salon_id == salon.id, SalonMember.is_active == True)
        .order_by(SalonMember.is_creator.desc(), SalonMember.created_at.asc())
    )
    members = members_result.all()

    can_manage_owners = perms.get("manage_owners", False)
    can_manage_admins = perms.get("manage_admins", False)

    rows = ""
    for member, u in members:
        role_label = "Владелец" if member.role == SalonRole.OWNER else "Админ"
        creator_badge = ' <span style="font-size:0.7rem;color:var(--color-primary)">(создатель)</span>' if member.is_creator else ""
        perms_summary = ", ".join(
            PERMISSION_LABELS[k] for k in SALON_PERMISSION_KEYS
            if (member.is_creator or member.permissions.get(k, False))
        ) or "—"

        can_edit_this = (not member.is_creator) and (
            (member.role == SalonRole.OWNER and can_manage_owners) or
            (member.role == SalonRole.ADMIN and can_manage_admins)
        )

        member_name = (u.full_name or u.phone).replace("'", "").replace('"', "")
        effective_perms = {k: (member.is_creator or member.permissions.get(k, False)) for k in SALON_PERMISSION_KEYS}
        perms_json = json.dumps(effective_perms)

        actions = ""
        if can_edit_this:
            actions = f"""
            <button onclick='openPermissionsModal({member.id}, "{member_name}", {perms_json})'
                style="background:none;border:none;color:var(--color-primary);cursor:pointer;font-size:1.1rem" title="Права">⚙️</button>
            <button onclick="removeMember({member.id}, '{member_name}')"
                style="background:none;border:none;color:#ef4444;cursor:pointer;font-size:1.1rem;margin-left:0.5rem" title="Снять">🗑️</button>"""

        rows += f"""
        <tr>
            <td><strong>{u.full_name or '—'}</strong>{creator_badge}<div style="font-size:0.8rem;color:var(--color-muted)">{u.phone}</div></td>
            <td>{role_label}</td>
            <td style="font-size:0.8rem;max-width:320px">{perms_summary}</td>
            <td>{actions}</td>
        </tr>"""

    invite_form = ""
    if can_manage_owners or can_manage_admins:
        role_options = ""
        if can_manage_owners:
            role_options += '<option value="owner">Владелец</option>'
        if can_manage_admins:
            role_options += '<option value="admin">Админ</option>'
        invite_form = f"""
        <button class="btn-primary" style="font-size:0.85rem;padding:0.5rem 1rem;margin-bottom:1rem" onclick="document.getElementById('inviteMemberModal').classList.add('active')">
            + Добавить
        </button>
        <div class="modal-overlay" id="inviteMemberModal">
            <div class="modal-box">
                <button class="modal-close" onclick="document.getElementById('inviteMemberModal').classList.remove('active')">&times;</button>
                <h2 style="margin-bottom:1.5rem">Добавить сотрудника {_hint("Если телефон уже зарегистрирован — просто даёт этому пользователю доступ к бизнес-панели салона. Если телефон новый — заведёт для него аккаунт с временным паролем (покажется один раз после отправки формы).")}</h2>
                <form action="/api/v1/business/staff/add-web" method="post">
                    <input type="hidden" name="salon_id" value="{salon.id}">
                    <div style="margin-bottom:1rem">
                        <label style="display:block;font-weight:500;margin-bottom:0.5rem">Телефон *</label>
                        <input type="tel" name="phone" required placeholder="+7XXXXXXXXXX" style="width:100%;padding:0.75rem;border:1px solid var(--color-border);border-radius:0.5rem">
                    </div>
                    <div style="margin-bottom:1rem">
                        <label style="display:block;font-weight:500;margin-bottom:0.5rem">Имя (если новый пользователь)</label>
                        <input type="text" name="full_name" placeholder="Имя" style="width:100%;padding:0.75rem;border:1px solid var(--color-border);border-radius:0.5rem">
                    </div>
                    <div style="margin-bottom:1rem">
                        <label style="display:block;font-weight:500;margin-bottom:0.5rem">Роль {_hint("Владелец и Админ отличаются только тем, кто вправе ими управлять: снять/изменить права владельца может лишь тот, у кого есть право «Совладельцы», админа — у кого есть право «Админы». Конкретные возможности каждого настраиваются галочками ниже, отдельно для каждого участника.")}</label>
                        <select name="role" class="custom-select" style="width:100%;padding:0.75rem;border:1px solid var(--color-border);border-radius:0.5rem">{role_options}</select>
                    </div>
                    <button type="submit" class="btn-primary" style="width:100%">Добавить</button>
                </form>
            </div>
        </div>"""

    permission_checkboxes = "".join(
        f'<label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;cursor:pointer">'
        f'<input type="checkbox" id="perm-{k}"> {v}</label>'
        for k, v in PERMISSION_LABELS.items()
    )
    permissions_modal = f"""
    <div class="modal-overlay" id="editPermissionsModal">
        <div class="modal-box">
            <button class="modal-close" onclick="document.getElementById('editPermissionsModal').classList.remove('active')">&times;</button>
            <h2 style="margin-bottom:1rem" id="permissionsModalTitle">Права участника {_hint("Определяют, какие вкладки и действия доступны этому участнику в бизнес-панели. У создателя салона права всегда полные и здесь не редактируются.")}</h2>
            <div id="permissionsCheckboxes">{permission_checkboxes}</div>
            <button type="button" class="btn-primary" style="width:100%;margin-top:1rem" onclick="submitPermissions()">Сохранить</button>
        </div>
    </div>"""

    audit_html = ""
    if perms.get("view_audit_log", False):
        audit_result = await db.execute(
            select(AdminAudit).where(AdminAudit.salon_id == salon.id).order_by(AdminAudit.created_at.desc()).limit(50)
        )
        audit_rows = ""
        for a in audit_result.scalars().all():
            audit_rows += f"""
            <tr>
                <td style="font-size:0.8rem;color:var(--color-muted)">{a.created_at.strftime('%d.%m.%Y %H:%M')}</td>
                <td>{a.action}</td>
                <td>{a.detail or '—'}</td>
            </tr>"""
        audit_html = f"""
        <h3 style="margin:2rem 0 1rem">📋 Лог действий</h3>
        <div class="card" style="overflow-x:auto">
            <table>
                <thead><tr><th>Когда</th><th>Действие</th><th>Детали</th></tr></thead>
                <tbody>{audit_rows or '<tr><td colspan="3" style="text-align:center;padding:2rem;color:var(--color-muted)">Пока пусто</td></tr>'}</tbody>
            </table>
        </div>"""

    return f"""
    <div id="tab-staff" class="tab-content">
        {notice_banner}
        {invite_form}
        <div class="card" style="overflow-x:auto">
            <table>
                <thead>
                    <tr><th>Участник</th><th>Роль</th><th>Права</th><th style="width:100px">Действия</th></tr>
                </thead>
                <tbody>
                    {rows or '<tr><td colspan="4" style="text-align:center;padding:2rem;color:var(--color-muted)">Пока нет других участников</td></tr>'}
                </tbody>
            </table>
        </div>
        {audit_html}
    </div>
    {permissions_modal}

    <script>
        let currentPermissionsMemberId = null;

        function openPermissionsModal(memberId, name, currentPermissions) {{
            currentPermissionsMemberId = memberId;
            document.getElementById('permissionsModalTitle').textContent = 'Права: ' + name;
            for (const k in currentPermissions) {{
                const el = document.getElementById('perm-' + k);
                if (el) el.checked = !!currentPermissions[k];
            }}
            document.getElementById('editPermissionsModal').classList.add('active');
        }}

        function submitPermissions() {{
            const keys = {list(PERMISSION_LABELS.keys())};
            const permissions = {{}};
            for (const k of keys) {{
                const el = document.getElementById('perm-' + k);
                permissions[k] = el ? el.checked : false;
            }}
            fetch(`/api/v1/business/staff/${{currentPermissionsMemberId}}/permissions`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ permissions }})
            }}).then(async r => {{
                if (r.ok) {{ location.reload(); }} else {{ const d = await r.json(); alert(d.detail || 'Ошибка'); }}
            }});
        }}

        function removeMember(memberId, name) {{
            if (!confirm(`Снять «${{name}}» с бизнес-панели салона?`)) return;
            fetch(`/api/v1/business/staff/${{memberId}}`, {{ method: 'DELETE' }})
                .then(async r => {{ if (r.ok) location.reload(); else {{ const d = await r.json(); alert(d.detail || 'Ошибка'); }} }});
        }}
    </script>"""
