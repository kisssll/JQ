# app/api/v1/endpoints/staff.py
"""Управление совладельцами/админами салона (вкладка «Сотрудники»)."""
import secrets
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from pydantic import BaseModel
from app.models.models import (
    User, SalonMember, SalonRole, AdminAudit, Salon,
    SALON_PERMISSION_KEYS, OWNER_DEFAULT_PERMISSIONS, MANAGER_DEFAULT_PERMISSIONS, ADMIN_DEFAULT_PERMISSIONS,
)
from app.schemas.salon_member import SalonMemberResponse, UpdatePermissionsRequest
from app.schemas.user import try_normalize_phone
from app.api.deps import get_current_user, check_salon_permission, get_salon_membership
from app.core.security import get_password_hash
from app.services.notifications import send_employee_credentials_email

router = APIRouter()


def _filter_permissions(overrides: dict) -> dict:
    return {k: bool(v) for k, v in overrides.items() if k in SALON_PERMISSION_KEYS}


# Право, которым должен обладать нанимающий/снимающий, в зависимости от роли
# ЦЕЛИ. Управляющего гейтим тем же правом, что и совладельца (manage_owners),
# но для него это только необходимое условие — назначить/снять/поменять
# права управляющего может дополнительно только сам создатель салона
# (см. _require_creator_for_manager ниже), а не любой co-owner с этим правом.
_ROLE_HIRE_PERMISSION = {
    SalonRole.OWNER: "manage_owners",
    SalonRole.MANAGER: "manage_owners",
    SalonRole.ADMIN: "manage_admins",
}
_ROLE_DEFAULT_PERMISSIONS = {
    SalonRole.OWNER: OWNER_DEFAULT_PERMISSIONS,
    SalonRole.MANAGER: MANAGER_DEFAULT_PERMISSIONS,
    SalonRole.ADMIN: ADMIN_DEFAULT_PERMISSIONS,
}


def _require_creator_for_manager(membership: SalonMember | None) -> None:
    """Управляющего может назначить/снять/изменить только создатель салона
    (или платформенный супер-админ — membership=None). Обычный совладелец с
    правом manage_owners сюда не допускается: управляющий — это доверенное
    лицо именно создателя, а не любого co-owner."""
    if membership is not None and not membership.is_creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Это действие с управляющим может выполнить только владелец-создатель салона",
        )


@router.post("/add-web")
async def add_member_web(
    request: Request,
    phone: str = Form(...),
    full_name: str = Form(""),
    role: str = Form(...),
    salon_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Добавляет совладельца/админа салона напрямую — без «приглашения»:
    аккаунт с временным паролем создаётся сразу, как при добавлении мастера
    (app/api/v1/endpoints/master.py create_master_web)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"status": "error", "detail": "Требуется вход"}, status_code=401)

    try:
        salon_role = SalonRole(role)
    except ValueError:
        return JSONResponse({"status": "error", "detail": "Некорректная роль"}, status_code=400)

    required_permission = _ROLE_HIRE_PERMISSION[salon_role]
    try:
        membership = await check_salon_permission(db, user, salon_id, required_permission)
        if salon_role == SalonRole.MANAGER:
            _require_creator_for_manager(membership)
    except HTTPException:
        return JSONResponse({"status": "error", "detail": "Недостаточно прав для управления сотрудниками"}, status_code=403)

    norm_phone = try_normalize_phone(phone)
    if norm_phone is None:
        return JSONResponse({"status": "error", "detail": "Некорректный номер телефона"}, status_code=400)

    temp_password = None
    added_user = (await db.execute(select(User).where(User.phone == norm_phone))).scalar_one_or_none()
    if added_user is None:
        # Уникальный случайный временный пароль — показывается добавившему
        # один раз через redirect, дальше нигде не хранится в открытом виде.
        temp_password = secrets.token_urlsafe(9)
        added_user = User(
            phone=norm_phone,
            full_name=full_name or None,
            hashed_password=get_password_hash(temp_password),
            is_active=True,
        )
        db.add(added_user)
        await db.flush()

    existing = (await db.execute(
        select(SalonMember).where(SalonMember.salon_id == salon_id, SalonMember.user_id == added_user.id)
    )).scalar_one_or_none()
    if existing is not None and existing.is_active:
        return JSONResponse({"status": "error", "detail": "Этот сотрудник уже в салоне"}, status_code=400)

    if existing is not None:
        existing.is_active = True
        existing.role = salon_role
        existing.invited_by_id = user.id
        member_id = existing.id
    else:
        default_perms = dict(_ROLE_DEFAULT_PERMISSIONS[salon_role])
        member = SalonMember(
            salon_id=salon_id,
            user_id=added_user.id,
            role=salon_role,
            is_creator=False,
            permissions=default_perms,
            is_active=True,
            invited_by_id=user.id,
        )
        db.add(member)
        await db.flush()
        member_id = member.id

    db.add(AdminAudit(
        actor_id=user.id, action="add_salon_member",
        target_type="salon_member", target_id=added_user.id, salon_id=salon_id,
        detail=f"Добавлен {norm_phone} как {salon_role.value} (#{member_id})",
    ))
    await db.commit()

    creds = None
    if temp_password:
        creds = {"name": full_name or norm_phone, "login": norm_phone, "password": temp_password}
    return JSONResponse({"status": "ok", "credentials": creds})


@router.post("/{member_id}/permissions", response_model=SalonMemberResponse)
async def update_member_permissions(
    member_id: int,
    payload: UpdatePermissionsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Изменяет набор прав участника. Права создателя менять нельзя — они всегда полные."""
    member = (await db.execute(
        select(SalonMember).options(selectinload(SalonMember.user)).where(SalonMember.id == member_id)
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Участник не найден")

    actor_membership = await check_salon_permission(db, current_user, member.salon_id, "manage_owners")
    if member.role == SalonRole.MANAGER:
        _require_creator_for_manager(actor_membership)

    if member.is_creator:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя изменить права создателя салона")

    member.permissions = {**member.permissions, **_filter_permissions(payload.permissions)}

    db.add(AdminAudit(
        actor_id=current_user.id, action="update_salon_member_permissions",
        target_type="salon_member", target_id=member.id, salon_id=member.salon_id,
        detail=f"Изменены права участника #{member.user_id}",
    ))
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/{member_id}")
async def remove_member(
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Снимает участника с бизнес-панели салона (мягкое удаление, is_active=False)."""
    member = (await db.execute(select(SalonMember).where(SalonMember.id == member_id))).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Участник не найден")

    if member.is_creator:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Создателя салона нельзя снять")

    if member.role == SalonRole.MANAGER and current_user.id == member.user_id:
        # Управляющий сам покидает салон — без доп. прав, сам факт, что это
        # его же членство, уже достаточное основание.
        pass
    elif member.role == SalonRole.MANAGER:
        actor_membership = await check_salon_permission(db, current_user, member.salon_id, "manage_owners")
        _require_creator_for_manager(actor_membership)
    else:
        required_permission = "manage_owners" if member.role == SalonRole.OWNER else "manage_admins"
        await check_salon_permission(db, current_user, member.salon_id, required_permission)

    member.is_active = False

    db.add(AdminAudit(
        actor_id=current_user.id, action="remove_salon_member",
        target_type="salon_member", target_id=member.id, salon_id=member.salon_id,
        detail=f"Снят участник #{member.user_id}",
    ))
    await db.commit()
    return {"status": "removed"}


@router.post("/{member_id}/reset-password")
async def reset_member_password(
    member_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Сброс пароля сотрудника: новый временный пароль + реквизиты для попапа.
    Права — как на управление этим участником (управляющего — только создатель),
    пароль создателя салона сбросить нельзя."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"status": "error", "detail": "Требуется вход"}, status_code=401)

    member = (await db.execute(select(SalonMember).where(SalonMember.id == member_id))).scalar_one_or_none()
    if member is None:
        return JSONResponse({"status": "error", "detail": "Участник не найден"}, status_code=404)
    if member.is_creator:
        return JSONResponse({"status": "error", "detail": "Нельзя сбросить пароль создателя салона"}, status_code=400)

    try:
        if member.role == SalonRole.MANAGER:
            actor = await check_salon_permission(db, user, member.salon_id, "manage_owners")
            _require_creator_for_manager(actor)
        else:
            perm = "manage_owners" if member.role == SalonRole.OWNER else "manage_admins"
            await check_salon_permission(db, user, member.salon_id, perm)
    except HTTPException:
        return JSONResponse({"status": "error", "detail": "Недостаточно прав"}, status_code=403)

    target = (await db.execute(select(User).where(User.id == member.user_id))).scalar_one_or_none()
    if target is None:
        return JSONResponse({"status": "error", "detail": "Аккаунт не найден"}, status_code=404)

    new_password = secrets.token_urlsafe(9)
    target.hashed_password = get_password_hash(new_password)
    db.add(AdminAudit(
        actor_id=user.id, action="reset_salon_member_password",
        target_type="salon_member", target_id=member.id, salon_id=member.salon_id,
        detail=f"Сброшен пароль участника #{member.user_id}",
    ))
    await db.commit()
    return JSONResponse({"status": "ok", "credentials": {
        "name": target.full_name or target.phone, "login": target.phone, "password": new_password,
    }})


class SendCredentialsRequest(BaseModel):
    salon_id: int
    name: str
    login: str
    password: str


@router.post("/send-credentials")
async def send_credentials(
    body: SendCredentialsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Отправить реквизиты сотрудника на почту салона (кнопка в попапе)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"status": "error", "detail": "Требуется вход"}, status_code=401)

    membership = await get_salon_membership(db, user.id, body.salon_id)
    can_manage_staff = membership is not None and (
        membership.is_creator
        or any(membership.permissions.get(p, False) for p in ("manage_masters", "manage_admins", "manage_owners"))
    )
    if not can_manage_staff:
        return JSONResponse({"status": "error", "detail": "Недостаточно прав"}, status_code=403)

    salon = (await db.execute(select(Salon).where(Salon.id == body.salon_id))).scalar_one_or_none()
    if salon is None:
        return JSONResponse({"status": "error", "detail": "Салон не найден"}, status_code=404)
    if not salon.email:
        return JSONResponse({"status": "error", "detail": "У салона не указана почта — добавьте её в настройках салона"}, status_code=400)

    try:
        sent_to = await send_employee_credentials_email(db, salon, body.name, body.login, body.password)
    except Exception:
        return JSONResponse({"status": "error", "detail": "Не удалось отправить письмо"}, status_code=502)
    return JSONResponse({"status": "ok", "sent_to": sent_to})
