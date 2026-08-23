# app/api/v1/endpoints/admin.py
"""Действия администратора. Все эндпоинты — только для роли ADMIN (cookie-auth),
каждое изменяющее действие пишется в admin_audit. Защиты: нельзя тронуть себя и
нельзя оставить платформу без активного админа.
"""
import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import (
    User, UserRole, Salon, Master, Service, Booking, Review, Promotion,
    SalonPhoto, Favorite, AdminAudit, SalonMember, SalonRole, OWNER_DEFAULT_PERMISSIONS,
    SalonModerationStatus, PhotoReport, PhotoReportStatus, MasterPhoto, ReviewPhoto,
    ClientLoyalty, SalonModel, ClientNote, ModelModerationStatus,
)
from app.core.security import get_password_hash
from app.web.auth import get_current_user_from_cookie

router = APIRouter()

# Роли, которые админ может назначать вручную. MASTER исключён —
# мастер создаётся через бизнес-флоу (профиль Master + привязка к салону).
# MODEL исключён — статус модели теперь аддитивный флаг User.is_model поверх
# обычной роли (см. app/api/v1/endpoints/model_matching.py), не отдельная role.
ASSIGNABLE_ROLES = {UserRole.CLIENT, UserRole.BUSINESS, UserRole.ADMIN}


# ── helpers ──────────────────────────────────────────────────────────────────
async def _get_admin(request: Request, db: AsyncSession):
    """Любой модератор (базовый или старший) — доступ к заявкам и жалобам на фото."""
    user = await get_current_user_from_cookie(request, db)
    if not user or user.role != UserRole.ADMIN or not user.is_active:
        return None
    return user


async def _get_senior_admin(request: Request, db: AsyncSession):
    """Только старший модератор — пользователи, блокировка салонов, отзывы, аудит."""
    user = await _get_admin(request, db)
    if not user or not user.is_senior_admin:
        return None
    return user


def _audit(db, actor_id, action, target_type, target_id, detail, salon_id=None):
    """salon_id: заполняется для действий модератора над конкретным салоном
    (одобрение/отклонение заявки, блокировка, смена владельца, удаление,
    удаление отзыва/фото по жалобе) — иначе они не попадают в собственный
    лог владельца салона (staff.py фильтрует именно по salon_id). Для
    чисто платформенных действий (роли, блокировка пользователей и т.п.)
    остаётся None."""
    db.add(AdminAudit(
        actor_id=actor_id, action=action,
        target_type=target_type, target_id=target_id, detail=detail,
        salon_id=salon_id,
    ))


async def _active_admins_excluding(db, exclude_id) -> int:
    q = select(func.count(User.id)).where(
        User.role == UserRole.ADMIN, User.is_active == True, User.id != exclude_id
    )
    return (await db.execute(q)).scalar() or 0


async def _active_seniors_excluding(db, exclude_id) -> int:
    q = select(func.count(User.id)).where(
        User.role == UserRole.ADMIN, User.is_active == True,
        User.is_senior_admin == True, User.id != exclude_id,
    )
    return (await db.execute(q)).scalar() or 0


def _back(tab: str, ok: str = "", err: str = "", extra: str = "") -> RedirectResponse:
    url = f"/admin?tab={tab}"
    if ok:
        url += f"&ok={quote(ok)}"
    if err:
        url += f"&err={quote(err)}"
    if extra:
        url += f"&{extra}"
    return RedirectResponse(url=url, status_code=302)


# ── ПОЛЬЗОВАТЕЛИ ─────────────────────────────────────────────────────────────
@router.post("/users/{uid}/role")
async def change_role(uid: int, request: Request, role: str = Form(...), db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    target = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not target:
        return _back("users", err="Пользователь не найден")
    try:
        new_role = UserRole(role)
    except ValueError:
        return _back("users", err="Недопустимая роль")
    if new_role not in ASSIGNABLE_ROLES:
        return _back("users", err="Эту роль нельзя назначить вручную")
    if target.id == admin.id:
        return _back("users", err="Нельзя менять собственную роль")
    if target.role == UserRole.ADMIN and new_role != UserRole.ADMIN and await _active_admins_excluding(db, target.id) == 0:
        return _back("users", err="Нельзя разжаловать последнего администратора")
    if target.role == UserRole.ADMIN and target.is_senior_admin and new_role != UserRole.ADMIN and await _active_seniors_excluding(db, target.id) == 0:
        return _back("users", err="Нельзя разжаловать последнего старшего модератора")

    old = target.role.value
    # Роль ушла с ADMIN — теряется и старшинство, чтобы не оставалось
    # мёртвого senior-флага на пользователе без прав модератора.
    if new_role != UserRole.ADMIN:
        target.is_senior_admin = False
    target.role = new_role
    _audit(db, admin.id, "change_role", "user", target.id, f"{target.phone}: {old} → {new_role.value}")
    await db.commit()
    return _back("users", ok=f"Роль {target.phone}: {old} → {new_role.value}")


@router.post("/salons/{sid}/grant-trial")
async def grant_trial(sid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Выдать салону повторный бесплатный период.

    Обычным путём триал даётся один раз (см. payments.py: trial_available) —
    это единственная лазейка, и она намеренно только у старшего модератора,
    с записью в аудит.
    """
    from app.models.models import Salon, SalonSubscriptionStatus
    from app.services.subscription import start_trial

    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("salons", err="Салон не найден")

    active_masters = (await db.execute(
        select(func.count(Master.id)).where(
            Master.salon_id == salon.id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0
    salon.subscription_status = SalonSubscriptionStatus.TRIALING
    salon.trial_used_at = None  # снимаем отметку, чтобы start_trial проставил свежую
    ends = start_trial(salon, 14, active_masters=active_masters)
    _audit(db, admin.id, "grant_trial", "salon", salon.id,
           f"«{salon.name}»: выдан повторный пробный период до {ends:%d.%m.%Y}",
           salon_id=salon.id)
    await db.commit()
    return _back("salons", ok=f"«{salon.name}»: пробный период до {ends:%d.%m.%Y}")


@router.post("/salons/{sid}/grant-access")
async def grant_access(sid: int, request: Request, months: int = Form(1),
                       db: AsyncSession = Depends(get_db)):
    """Выдать/продлить ПЛАТНЫЙ доступ руками — для оплат мимо кассы (счёт,
    наличные, договор). Продлеваем от текущего срока, если он ещё не истёк,
    иначе от сегодня."""
    from datetime import datetime, timedelta, timezone
    from app.models.models import Salon, SalonSubscriptionStatus
    from app.services.subscription import apply_successful_payment
    from app.services.tariffs import resolve_plan_for_employee_count

    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("salons", err="Салон не найден")
    months = max(1, min(int(months or 1), 120))

    now = datetime.now(timezone.utc)
    current = salon.subscription_expires_at
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    base = current if current and current > now else now

    active_masters = (await db.execute(
        select(func.count(Master.id)).where(
            Master.salon_id == salon.id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0
    if not salon.business_tier:
        plan = resolve_plan_for_employee_count(active_masters)
        salon.business_tier = plan if plan != "custom" else "corporate"

    apply_successful_payment(salon, base + timedelta(days=30 * months),
                             active_masters=active_masters)
    salon.subscription_status = SalonSubscriptionStatus.ACTIVE
    _audit(db, admin.id, "grant_access", "salon", salon.id,
           f"«{salon.name}»: доступ выдан вручную на {months} мес., "
           f"до {salon.access_until:%d.%m.%Y}", salon_id=salon.id)
    await db.commit()
    return _back("salons", ok=f"«{salon.name}»: доступ до {salon.access_until:%d.%m.%Y}")


@router.post("/salons/{sid}/set-plan")
async def set_salon_plan(sid: int, request: Request, plan: str = Form(...),
                         db: AsyncSession = Depends(get_db)):
    """Сменить тариф салона руками — правило «понижение раз в 3 месяца» на
    админа не распространяется (например, после договорённости с продавцом)."""
    from app.models.models import Salon
    from app.services.tariffs import TARIFF_CATALOG

    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("salons", err="Салон не найден")
    if plan not in TARIFF_CATALOG:
        return _back("salons", err="Неизвестный тариф")

    was = salon.business_tier or "—"
    salon.business_tier = plan
    _audit(db, admin.id, "set_plan", "salon", salon.id,
           f"«{salon.name}»: тариф {was} → {plan}", salon_id=salon.id)
    await db.commit()
    return _back("salons", ok=f"«{salon.name}»: тариф {TARIFF_CATALOG[plan].name}")


@router.post("/salons/{sid}/revoke-access")
async def revoke_access(sid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Снять доступ немедленно (нарушение, ошибочная выдача). Салон уходит из
    каталога и перестаёт принимать новую запись; созданные брони не трогаем."""
    from datetime import datetime, timezone
    from app.models.models import Salon, SalonSubscriptionStatus

    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("salons", err="Салон не найден")

    now = datetime.now(timezone.utc)
    salon.access_until = now
    salon.subscription_expires_at = now
    salon.subscription_status = SalonSubscriptionStatus.CANCELED
    salon.auto_renew = False
    _audit(db, admin.id, "revoke_access", "salon", salon.id,
           f"«{salon.name}»: доступ снят вручную", salon_id=salon.id)
    await db.commit()
    return _back("salons", ok=f"«{salon.name}»: доступ снят, салон вне каталога")


@router.post("/users/{uid}/toggle-active")
async def toggle_active(uid: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    target = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not target:
        return _back("users", err="Пользователь не найден")
    if target.id == admin.id:
        return _back("users", err="Нельзя заблокировать самого себя")
    if target.role == UserRole.ADMIN and target.is_active and await _active_admins_excluding(db, target.id) == 0:
        return _back("users", err="Нельзя заблокировать последнего администратора")
    if target.role == UserRole.ADMIN and target.is_active and target.is_senior_admin and await _active_seniors_excluding(db, target.id) == 0:
        return _back("users", err="Нельзя заблокировать последнего старшего модератора")

    target.is_active = not target.is_active
    state = "разблокирован" if target.is_active else "заблокирован"
    _audit(db, admin.id, "toggle_active", "user", target.id, f"{target.phone}: {state}")
    await db.commit()
    return _back("users", ok=f"{target.phone} {state}")


@router.post("/users/{uid}/toggle-senior")
async def toggle_senior(uid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Назначить/снять статус старшего модератора — только среди пользователей с role=ADMIN."""
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    target = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not target:
        return _back("users", err="Пользователь не найден")
    if target.role != UserRole.ADMIN:
        return _back("users", err="Статус старшего модератора применим только к модераторам")
    if target.id == admin.id:
        return _back("users", err="Нельзя менять собственный статус старшинства")
    if target.is_senior_admin and await _active_seniors_excluding(db, target.id) == 0:
        return _back("users", err="Нельзя снять последнего старшего модератора")

    target.is_senior_admin = not target.is_senior_admin
    state = "назначен старшим модератором" if target.is_senior_admin else "снят со старшего модератора"
    _audit(db, admin.id, "toggle_senior", "user", target.id, f"{target.phone}: {state}")
    await db.commit()
    return _back("users", ok=f"{target.phone} {state}")


@router.post("/users/{uid}/reset-password")
async def reset_password(uid: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    target = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not target:
        return _back("users", err="Пользователь не найден")

    temp = secrets.token_urlsafe(9)
    target.hashed_password = get_password_hash(temp)
    _audit(db, admin.id, "reset_password", "user", target.id, f"{target.phone}: сброс пароля")
    await db.commit()
    # временный пароль показываем один раз
    return _back("users", ok=f"Пароль {target.phone} сброшен", extra=f"temp_pw={quote(temp)}&temp_for={quote(target.phone)}")


@router.post("/users/{uid}/delete")
async def delete_user(uid: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    target = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not target:
        return _back("users", err="Пользователь не найден")
    if target.id == admin.id:
        return _back("users", err="Нельзя удалить самого себя")
    if target.role == UserRole.ADMIN and await _active_admins_excluding(db, target.id) == 0:
        return _back("users", err="Нельзя удалить последнего администратора")
    if target.role == UserRole.ADMIN and target.is_senior_admin and await _active_seniors_excluding(db, target.id) == 0:
        return _back("users", err="Нельзя удалить последнего старшего модератора")

    # Сложные связи блокируем — их надо разрулить явно (заблокируйте пользователя).
    # Персонал (SalonMember) держит created_by-ссылки в аудите склада/зарплат/
    # закрытий/движений лояльности (не nullable) — их массово чистить нельзя,
    # это исказит записи салона; такого пользователя удаляем через салон.
    owns_salon = (await db.execute(select(func.count(Salon.id)).where(Salon.creator_id == target.id))).scalar() or 0
    is_master = (await db.execute(select(func.count(Master.id)).where(Master.user_id == target.id))).scalar() or 0
    # Блокируем ТОЛЬКО активное членство (текущий сотрудник). Неактивные
    # (снятый владелец/уволенный сотрудник — remove_member делает soft-delete)
    # не должны мешать удалению: их строки чистим ниже.
    is_staff = (await db.execute(select(func.count(SalonMember.id)).where(
        SalonMember.user_id == target.id, SalonMember.is_active == True
    ))).scalar() or 0
    if owns_salon:
        return _back("users", err="Пользователь владеет салоном — сначала переназначьте владельца")
    if is_master:
        return _back("users", err="У пользователя есть профиль мастера — удалите его через салон")
    if is_staff:
        return _back("users", err="Пользователь — активный сотрудник салона; сначала удалите его из салона (или заблокируйте)")

    phone = target.phone
    # Чистим клиентские зависимости. ClientLoyalty каскадит движения баллов
    # (ondelete=CASCADE). Review.staff_user_id — SET NULL на уровне БД.
    await db.execute(delete(Favorite).where(Favorite.user_id == target.id))
    await db.execute(delete(Review).where(Review.client_id == target.id))
    await db.execute(delete(Booking).where(Booking.client_id == target.id))
    await db.execute(delete(ClientLoyalty).where(ClientLoyalty.client_id == target.id))
    await db.execute(delete(SalonModel).where(SalonModel.user_id == target.id))
    await db.execute(delete(ClientNote).where(
        (ClientNote.client_id == target.id) | (ClientNote.author_id == target.id)
    ))
    await db.execute(delete(PhotoReport).where(PhotoReport.reporter_id == target.id))
    # Неактивные членства (активных нет — заблокированы выше) удаляем; ссылки
    # invited_by на удаляемого обнуляем, иначе FK не даст удалить юзера.
    await db.execute(update(SalonMember).where(SalonMember.invited_by_id == target.id).values(invited_by_id=None))
    await db.execute(delete(SalonMember).where(SalonMember.user_id == target.id))
    await db.delete(target)
    _audit(db, admin.id, "delete_user", "user", uid, f"удалён {phone}")
    try:
        await db.commit()
    except IntegrityError:
        # Остались непредвиденные связанные записи — не роняем 500, просим блокировку
        await db.rollback()
        return _back("users", err="У пользователя остались связанные данные — заблокируйте его вместо удаления")
    return _back("users", ok=f"Пользователь {phone} удалён")


async def _notify_owner_moderation(db, salon, approved: bool):
    """Уведомить владельца салона о решении по заявке (TG + email через ARQ)."""
    if not salon.creator_id:
        return
    owner = (await db.execute(select(User).where(User.id == salon.creator_id))).scalar_one_or_none()
    if not owner:
        return
    if approved:
        # Одобрение больше НЕ выводит салон в каталог само по себе — владелец
        # публикует его вручную кнопкой в шапке панели (см. Salon.published_at).
        tg = (f"✅ Салон «{salon.name}» прошёл модерацию! Откройте панель и нажмите "
              "«Опубликовать салон», чтобы он появился в каталоге и открылась запись.")
        subj = "Салон прошёл модерацию — Руми"
        body = (f"Салон «{salon.name}» прошёл модерацию. Осталось опубликовать его: "
                "откройте бизнес-панель и нажмите «Опубликовать салон» — после этого "
                "он появится в каталоге и клиенты смогут записываться.")
    else:
        why = f"\nПричина: {salon.rejection_reason}" if salon.rejection_reason else ""
        tg = f"⚠️ Заявка по салону «{salon.name}» отклонена.{why}"
        subj = "Заявка отклонена — Руми"
        body = f"Заявка по салону «{salon.name}» отклонена.{why}"
    try:
        from app.core.worker import get_arq_pool
        pool = await get_arq_pool()
        if owner.tg_chat_id:
            await pool.enqueue_job("send_tg_message", owner.tg_chat_id, tg)
        if owner.email:
            await pool.enqueue_job("send_email", owner.email, subj, body)
    except Exception:
        logger.exception("не удалось уведомить владельца о модерации salon=%s", salon.id)


# ── ЖАЛОБЫ НА ФОТО ───────────────────────────────────────────────────────────
@router.post("/reports/{rid}/resolve")
async def report_resolve(rid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Жалоба обоснована: удаляем фото, жалобу закрываем."""
    admin = await _get_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)
    from app.api.v1.endpoints.reports import _photo_and_salon_id
    from app.services.uploads import delete_stored

    report = (await db.execute(select(PhotoReport).where(PhotoReport.id == rid))).scalar_one_or_none()
    if not report or report.status != PhotoReportStatus.PENDING:
        return _back("reports", err="Жалоба не найдена или уже обработана")
    url, _sid = await _photo_and_salon_id(db, report)
    if report.master_photo_id:
        photo = (await db.execute(select(MasterPhoto).where(MasterPhoto.id == report.master_photo_id))).scalar_one_or_none()
    else:
        photo = (await db.execute(select(ReviewPhoto).where(ReviewPhoto.id == report.review_photo_id))).scalar_one_or_none()
    if photo:
        await db.delete(photo)
    report.status = PhotoReportStatus.RESOLVED
    report.resolved_by_id = admin.id
    report.resolved_at = datetime.now(timezone.utc)
    _audit(db, admin.id, "report_resolve", "photo_report", rid, "фото удалено", salon_id=_sid)
    await db.commit()
    if url and url.startswith("/uploads/"):
        delete_stored(url)
    return _back("reports", ok="Фото удалено, жалоба закрыта")


@router.post("/reports/{rid}/dismiss")
async def report_dismiss(rid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Жалоба необоснована: фото остаётся, жалобу закрываем."""
    admin = await _get_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)
    from app.api.v1.endpoints.reports import _photo_and_salon_id

    report = (await db.execute(select(PhotoReport).where(PhotoReport.id == rid))).scalar_one_or_none()
    if not report or report.status != PhotoReportStatus.PENDING:
        return _back("reports", err="Жалоба не найдена или уже обработана")
    _, sid = await _photo_and_salon_id(db, report)
    report.status = PhotoReportStatus.DISMISSED
    report.resolved_by_id = admin.id
    report.resolved_at = datetime.now(timezone.utc)
    _audit(db, admin.id, "report_dismiss", "photo_report", rid, "оставлено", salon_id=sid)
    await db.commit()
    return _back("reports", ok="Жалоба отклонена, фото оставлено")


# ── САЛОНЫ ───────────────────────────────────────────────────────────────────
@router.post("/salons/{sid}/approve")
async def salon_approve(sid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Одобрить заявку салона: договор подтверждён → салон работает."""
    admin = await _get_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)
    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("applications", err="Салон не найден")
    salon.moderation_status = SalonModerationStatus.APPROVED
    salon.rejection_reason = None
    salon.is_active = True
    _audit(db, admin.id, "salon_approve", "salon", sid, salon.name, salon_id=sid)
    await db.commit()
    await _notify_owner_moderation(db, salon, approved=True)
    return _back("applications", ok=f"«{salon.name}» одобрен")


@router.post("/salons/{sid}/reject")
async def salon_reject(sid: int, request: Request, reason: str = Form(""), db: AsyncSession = Depends(get_db)):
    """Отклонить заявку салона (с причиной)."""
    admin = await _get_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)
    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("applications", err="Салон не найден")
    salon.moderation_status = SalonModerationStatus.REJECTED
    salon.rejection_reason = reason.strip() or None
    salon.is_active = False
    _audit(db, admin.id, "salon_reject", "salon", sid, f"{salon.name}: {reason.strip()[:200]}", salon_id=sid)
    await db.commit()
    await _notify_owner_moderation(db, salon, approved=False)
    return _back("applications", ok=f"«{salon.name}» отклонён")


@router.post("/salons/{sid}/toggle-active")
async def salon_toggle(sid: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("salons", err="Салон не найден")
    salon.is_active = not salon.is_active
    state = "активирован" if salon.is_active else "деактивирован"
    _audit(db, admin.id, "salon_toggle", "salon", sid, f"{salon.name}: {state}", salon_id=sid)
    await db.commit()
    return _back("salons", ok=f"«{salon.name}» {state}")


@router.post("/salons/{sid}/owner")
async def salon_owner(sid: int, request: Request, owner_phone: str = Form(""), db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("salons", err="Салон не найден")

    owner_phone = owner_phone.strip()

    # Снимаем is_creator с текущего создателя (если есть) в любом случае —
    # либо совсем снимаем владельца, либо передаём создателя другому.
    current_creator_membership = (await db.execute(
        select(SalonMember).where(SalonMember.salon_id == sid, SalonMember.is_creator == True)
    )).scalar_one_or_none()
    if current_creator_membership is not None:
        current_creator_membership.is_creator = False

    if not owner_phone:  # снять владельца
        # Ex-владелец теряет доступ: снятия is_creator мало — доступ даёт
        # активное членство + permissions, а не флаг создателя.
        if current_creator_membership is not None:
            current_creator_membership.is_active = False
        salon.creator_id = None
        _audit(db, admin.id, "salon_owner", "salon", sid, f"{salon.name}: владелец снят", salon_id=sid)
        await db.commit()
        return _back("salons", ok=f"«{salon.name}»: владелец снят")

    owner = (await db.execute(select(User).where(User.phone == owner_phone))).scalar_one_or_none()
    if not owner:
        return _back("salons", err="Пользователь с таким телефоном не найден")

    # Старый владелец (если это ДРУГОЙ человек) теряет доступ к салону —
    # иначе он сохранял бы OWNER-права: снятия is_creator недостаточно,
    # права даёт активное членство + permissions.
    if (
        current_creator_membership is not None
        and current_creator_membership.user_id != owner.id
    ):
        current_creator_membership.is_active = False

    # Множественные салоны на владельца разрешены — блокировки больше нет.
    membership = (await db.execute(
        select(SalonMember).where(SalonMember.salon_id == sid, SalonMember.user_id == owner.id)
    )).scalar_one_or_none()
    if membership is None:
        membership = SalonMember(
            salon_id=sid, user_id=owner.id, role=SalonRole.OWNER,
            is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        )
        db.add(membership)
    else:
        membership.role = SalonRole.OWNER
        membership.is_creator = True
        membership.is_active = True

    salon.creator_id = owner.id
    if owner.role != UserRole.ADMIN:
        owner.role = UserRole.BUSINESS  # владелец салона → бизнес-роль (для навигации/UX)
    _audit(db, admin.id, "salon_owner", "salon", sid, f"{salon.name}: владелец → {owner.phone}", salon_id=sid)
    await db.commit()
    return _back("salons", ok=f"«{salon.name}»: владелец → {owner.phone}")


@router.post("/salons/{sid}/delete")
async def salon_delete(sid: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == sid))).scalar_one_or_none()
    if not salon:
        return _back("salons", err="Салон не найден")

    masters = (await db.execute(select(func.count(Master.id)).where(Master.salon_id == sid))).scalar() or 0
    if masters:
        return _back("salons", err="В салоне есть мастера — сначала удалите их")

    name = salon.name
    # RESTRICT-FK на salons.id, которые НЕ каскадят: Promotion, Review, Favorite
    # (остальное — CASCADE/SET NULL; Master заблокирован выше). Favorite салона
    # чистим явно, иначе удаление салона из чьего-то избранного роняло 500.
    await db.execute(delete(Promotion).where(Promotion.salon_id == sid))
    await db.execute(delete(Review).where(Review.salon_id == sid))
    await db.execute(delete(SalonPhoto).where(SalonPhoto.salon_id == sid))
    await db.execute(delete(Favorite).where(Favorite.salon_id == sid))
    await db.delete(salon)
    # salon_id тут намеренно не проставляем (не salon_id=sid): салон удалён,
    # его собственную страницу «Сотрудники» с логом больше некому открыть —
    # событие остаётся только в платформенном логе для модератора.
    _audit(db, admin.id, "salon_delete", "salon", sid, f"удалён «{name}»")
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _back("salons", err="У салона остались связанные данные — деактивируйте его вместо удаления")
    return _back("salons", ok=f"Салон «{name}» удалён")


# ── ОТЗЫВЫ ───────────────────────────────────────────────────────────────────
@router.post("/reviews/{rid}/delete")
async def review_delete(rid: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _get_senior_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)

    review = (await db.execute(select(Review).where(Review.id == rid))).scalar_one_or_none()
    if not review:
        return _back("reviews", err="Отзыв не найден")

    master_id, salon_id = review.master_id, review.salon_id
    await db.delete(review)
    await db.flush()

    # пересчёт рейтинга мастера (только по подтверждённым — как в ReviewService)
    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if master:
        avg = (await db.execute(
            select(func.avg(Review.rating)).where(Review.master_id == master_id, Review.is_verified == True)
        )).scalar()
        master.rating = round(float(avg or 0.0), 1)
    # пересчёт рейтинга и счётчика салона (только по подтверждённым)
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon:
        cnt = (await db.execute(
            select(func.count(Review.id)).where(Review.salon_id == salon_id, Review.is_verified == True)
        )).scalar() or 0
        avg = (await db.execute(
            select(func.avg(Review.rating)).where(Review.salon_id == salon_id, Review.is_verified == True)
        )).scalar()
        salon.reviews_count = cnt
        salon.rating = round(float(avg or 0.0), 1)

    _audit(db, admin.id, "review_delete", "review", rid, f"удалён отзыв #{rid}", salon_id=salon_id)
    await db.commit()
    return _back("reviews", ok="Отзыв удалён, рейтинг пересчитан")


# ── МОДЕЛИ (модерация анкет) ─────────────────────────────────────────────────
async def _notify_model_moderation(db, model_user: User, approved: bool):
    """Уведомить модель о решении по анкете (TG через ARQ) — по образцу
    _notify_owner_moderation для салонов."""
    if not model_user.tg_chat_id:
        return
    if approved:
        tg = "✅ Ваша анкета модели одобрена — теперь салоны видят вас в поиске."
    else:
        why = f"\nПричина: {model_user.model_rejection_reason}" if model_user.model_rejection_reason else ""
        tg = f"⚠️ Анкета модели отклонена.{why}"
    try:
        from app.core.worker import get_arq_pool
        pool = await get_arq_pool()
        await pool.enqueue_job("send_tg_message", model_user.tg_chat_id, tg)
    except Exception:
        logger.exception("не удалось уведомить модель о модерации user=%s", model_user.id)


@router.post("/models/{uid}/approve")
async def model_approve(uid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Одобрить анкету модели: становится видна салонам в кандидатах."""
    admin = await _get_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)
    target = (await db.execute(select(User).where(User.id == uid, User.is_model == True))).scalar_one_or_none()
    if not target:
        return _back("applications", err="Анкета не найдена")
    target.model_moderation_status = ModelModerationStatus.APPROVED
    target.model_rejection_reason = None
    _audit(db, admin.id, "model_approve", "user", uid, target.full_name or target.phone)
    await db.commit()
    await _notify_model_moderation(db, target, approved=True)
    return _back("applications", ok=f"Анкета «{target.full_name or target.phone}» одобрена")


@router.post("/models/{uid}/reject")
async def model_reject(uid: int, request: Request, reason: str = Form(""), db: AsyncSession = Depends(get_db)):
    """Отклонить анкету модели (с причиной)."""
    admin = await _get_admin(request, db)
    if not admin:
        return RedirectResponse("/login?redirect=/admin", status_code=302)
    target = (await db.execute(select(User).where(User.id == uid, User.is_model == True))).scalar_one_or_none()
    if not target:
        return _back("applications", err="Анкета не найдена")
    target.model_moderation_status = ModelModerationStatus.REJECTED
    target.model_rejection_reason = reason.strip() or None
    _audit(db, admin.id, "model_reject", "user", uid, f"{target.full_name or target.phone}: {reason.strip()[:200]}")
    await db.commit()
    await _notify_model_moderation(db, target, approved=False)
    return _back("applications", ok=f"Анкета «{target.full_name or target.phone}» отклонена")
