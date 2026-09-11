# app/api/v1/endpoints/uploads.py
"""Загрузка фото: аватар (за себя) и галерея салона (право manage_salon).

Мутации под cookie-аутентификацией — CSRF-щит (CSRFOriginMiddleware)
покрывает их так же, как остальные POST'ы с cookie.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_salon_permission, get_current_user
from app.db.session import get_db
from app.models.models import Master, MasterPhoto, ModelPhoto, Review, ReviewPhoto, Salon, SalonPhoto, User, Service, ServicePhoto
from app.services.uploads import UploadError, delete_stored, save_image

router = APIRouter()

MAX_MASTER_PHOTOS = 20
MAX_REVIEW_PHOTOS = 5
MAX_MODEL_PHOTOS = 6
MAX_SERVICE_PHOTOS = 20


def _safe_next(target: str, fallback: str) -> str:
    """Только внутренние пути (защита от open redirect) — как в auth_web."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return fallback
    return target


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    master_id: int | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Аватар текущего пользователя или мастера, если есть manage_masters.

    Отдаёт JSON: зовётся fetch'ем из profile.js, страница обновляет картинку
    без перезагрузки. Старый файл удаляется — мусор не копится.
    """
    target_user = current_user
    if master_id is not None:
        target_master = (await db.execute(
            select(Master).where(Master.id == master_id)
        )).scalar_one_or_none()
        if target_master is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мастер не найден")
        if target_master.user_id != current_user.id:
            await check_salon_permission(db, current_user, target_master.salon_id, "manage_masters")
        target_user = (await db.execute(
            select(User).where(User.id == target_master.user_id)
        )).scalar_one()

    try:
        url = await save_image(file, "avatars")
    except UploadError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    old = target_user.avatar_url
    target_user.avatar_url = url
    await db.commit()
    if old and old.startswith("/uploads/"):
        delete_stored(old)
    return {"url": url}


@router.post("/salon/{salon_id}/photo")
async def upload_salon_photos(
    salon_id: int,
    files: list[UploadFile] = File(...),
    next: str = Form("/business/my-salon"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Фото в галерею салона, можно НЕСКОЛЬКО за раз. Право: manage_salon.

    Частичный успех честный: валидные файлы сохраняются, по каждому битому
    возвращается своя причина — страница показывает и то и другое.
    """
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Салон не найден")
    await check_salon_permission(db, current_user, salon_id, "manage_salon")

    saved, errors = [], []
    for file in files:
        try:
            url = await save_image(file, "salons")
        except UploadError as e:
            errors.append({"file": file.filename or "файл", "detail": str(e)})
            continue
        db.add(SalonPhoto(salon_id=salon_id, url=url))
        saved.append(url)
    if saved:
        # Первое фото салона автоматически становится обложкой (logo_url —
        # именно его показывают карточки в списке и на главной)
        if not salon.logo_url:
            salon.logo_url = saved[0]
        await db.commit()

    if not saved and errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors[0]["detail"])
    return {"saved": saved, "errors": errors}


@router.post("/salon/{salon_id}/photo/{photo_id}/cover")
async def set_salon_cover(
    salon_id: int,
    photo_id: int,
    next: str = Form("/business/my-salon"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Назначает фото обложкой: карточка салона в списке и на главной
    показывает salon.logo_url — сюда оно и записывается."""
    await check_salon_permission(db, current_user, salon_id, "manage_salon")
    photo = (
        await db.execute(
            select(SalonPhoto).where(SalonPhoto.id == photo_id, SalonPhoto.salon_id == salon_id)
        )
    ).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фото не найдено")

    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Салон не найден")
    salon.logo_url = photo.url
    await db.commit()
    return RedirectResponse(url=_safe_next(next, "/business/my-salon"), status_code=302)


@router.post("/salon/{salon_id}/photo/{photo_id}/delete")
async def delete_salon_photo(
    salon_id: int,
    photo_id: int,
    next: str = Form("/business/my-salon"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_salon")
    photo = (
        await db.execute(
            select(SalonPhoto).where(SalonPhoto.id == photo_id, SalonPhoto.salon_id == salon_id)
        )
    ).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фото не найдено")

    url = photo.url
    await db.delete(photo)

    # Если удалили обложку — переназначаем на первое оставшееся фото
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Салон не найден")
    if salon.logo_url == url:
        remaining = (
            await db.execute(
                select(SalonPhoto)
                .where(SalonPhoto.salon_id == salon_id, SalonPhoto.id != photo_id)
                .order_by(SalonPhoto.id)
            )
        ).scalars().first()
        salon.logo_url = remaining.url if remaining else None

    await db.commit()
    if url.startswith("/uploads/"):
        delete_stored(url)
    return RedirectResponse(url=_safe_next(next, "/business/my-salon"), status_code=302)


@router.post("/master/photo")
async def upload_master_photos(
    files: list[UploadFile] = File(...),
    master_id: int | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Портфолио мастера — своё или мастера своего салона при manage_masters.

    Проверка через реальную запись Master (не через User.role — оно не
    всегда синхронизировано, см. has_master_profile в app/web/auth.py).
    """
    own_master_request = master_id is None
    if own_master_request:
        master = (await db.execute(select(Master).where(Master.user_id == current_user.id))).scalar_one_or_none()
    else:
        master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if master is None:
        detail = "У вас нет профиля мастера" if own_master_request else "Мастер не найден"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN if own_master_request else status.HTTP_404_NOT_FOUND,
            detail=detail,
        )
    if master.user_id != current_user.id:
        await check_salon_permission(db, current_user, master.salon_id, "manage_masters")

    existing_count = (await db.execute(
        select(func.count(MasterPhoto.id)).where(MasterPhoto.master_id == master.id)
    )).scalar() or 0

    saved, errors = [], []
    for file in files:
        if existing_count + len(saved) >= MAX_MASTER_PHOTOS:
            errors.append({"file": file.filename or "файл", "detail": f"Максимум {MAX_MASTER_PHOTOS} фото в портфолио"})
            continue
        try:
            url = await save_image(file, "masters")
        except UploadError as e:
            errors.append({"file": file.filename or "файл", "detail": str(e)})
            continue
        db.add(MasterPhoto(master_id=master.id, url=url))
        saved.append(url)
    if saved:
        await db.commit()

    if not saved and errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors[0]["detail"])
    return {"saved": saved, "errors": errors}


@router.post("/service/{service_id}/photo")
async def upload_service_photos(
    service_id: int,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Фото услуги, доступное владельцу/администратору салона."""
    service = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    master = (await db.execute(select(Master).where(Master.id == service.master_id))).scalar_one()
    await check_salon_permission(db, current_user, master.salon_id, "manage_masters")
    existing_count = (await db.execute(
        select(func.count(ServicePhoto.id)).where(ServicePhoto.service_id == service_id)
    )).scalar() or 0
    saved, errors = [], []
    for file in files:
        if existing_count + len(saved) >= MAX_SERVICE_PHOTOS:
            errors.append({"file": file.filename or "файл", "detail": f"Максимум {MAX_SERVICE_PHOTOS} фото у услуги"})
            continue
        try:
            url = await save_image(file, "services")
        except UploadError as e:
            errors.append({"file": file.filename or "файл", "detail": str(e)})
            continue
        db.add(ServicePhoto(service_id=service_id, url=url))
        saved.append(url)
    if saved:
        await db.commit()
    if not saved and errors:
        raise HTTPException(status_code=400, detail=errors[0]["detail"])
    return {"saved": saved, "errors": errors}


@router.post("/service/photo/{photo_id}/delete")
async def delete_service_photo(
    photo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    photo = (await db.execute(select(ServicePhoto).where(ServicePhoto.id == photo_id))).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Фото не найдено")
    service = (await db.execute(select(Service).where(Service.id == photo.service_id))).scalar_one()
    master = (await db.execute(select(Master).where(Master.id == service.master_id))).scalar_one()
    await check_salon_permission(db, current_user, master.salon_id, "manage_masters")
    url = photo.url
    await db.delete(photo)
    await db.commit()
    if url.startswith("/uploads/"):
        delete_stored(url)
    return {"status": "deleted"}


@router.post("/master/photo/{photo_id}/delete")
async def delete_master_photo(
    photo_id: int,
    master_id: int | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Мастер удаляет своё фото, либо менеджер — фото мастера своего салона."""
    own_master_request = master_id is None
    if own_master_request:
        master = (await db.execute(select(Master).where(Master.user_id == current_user.id))).scalar_one_or_none()
    else:
        master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if master is None:
        detail = "У вас нет профиля мастера" if own_master_request else "Мастер не найден"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN if own_master_request else status.HTTP_404_NOT_FOUND,
            detail=detail,
        )
    if master.user_id != current_user.id:
        await check_salon_permission(db, current_user, master.salon_id, "manage_masters")

    photo = (await db.execute(
        select(MasterPhoto).where(MasterPhoto.id == photo_id, MasterPhoto.master_id == master.id)
    )).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фото не найдено")

    url = photo.url
    await db.delete(photo)
    await db.commit()
    if url.startswith("/uploads/"):
        delete_stored(url)
    return {"status": "deleted"}


@router.post("/review/{review_id}/photo/{photo_id}/delete")
async def delete_review_photo(
    review_id: int,
    photo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удаление фото из отзыва: автор отзыва — своё, владелец/админ салона —
    любое в своём салоне (модерация)."""
    review = (await db.execute(select(Review).where(Review.id == review_id))).scalar_one_or_none()
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отзыв не найден")

    if review.client_id != current_user.id:
        await check_salon_permission(db, current_user, review.salon_id, "manage_reviews")

    photo = (await db.execute(
        select(ReviewPhoto).where(ReviewPhoto.id == photo_id, ReviewPhoto.review_id == review_id)
    )).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фото не найдено")

    url = photo.url
    await db.delete(photo)
    await db.commit()
    if url.startswith("/uploads/"):
        delete_stored(url)
    return {"status": "deleted"}


@router.post("/model/photo")
async def upload_model_photos(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Галерея анкеты модели — свои фото, до MAX_MODEL_PHOTOS штук.

    Не проверяем current_user.is_model — модель может начать собирать
    галерею до отправки анкеты (та же логика, что и upsert профиля)."""
    existing_count = (await db.execute(
        select(func.count(ModelPhoto.id)).where(ModelPhoto.model_user_id == current_user.id)
    )).scalar() or 0

    saved, errors = [], []
    for file in files:
        if existing_count + len(saved) >= MAX_MODEL_PHOTOS:
            errors.append({"file": file.filename or "файл", "detail": f"Максимум {MAX_MODEL_PHOTOS} фото в галерее"})
            continue
        try:
            url = await save_image(file, "models")
        except UploadError as e:
            errors.append({"file": file.filename or "файл", "detail": str(e)})
            continue
        db.add(ModelPhoto(model_user_id=current_user.id, url=url))
        saved.append(url)
    if saved:
        await db.commit()

    if not saved and errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors[0]["detail"])
    return {"saved": saved, "errors": errors}


@router.post("/model/photo/{photo_id}/delete")
async def delete_model_photo(
    photo_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Модель удаляет своё фото из галереи."""
    photo = (await db.execute(
        select(ModelPhoto).where(ModelPhoto.id == photo_id, ModelPhoto.model_user_id == current_user.id)
    )).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фото не найдено")

    url = photo.url
    await db.delete(photo)
    await db.commit()
    if url.startswith("/uploads/"):
        delete_stored(url)
    return {"status": "deleted"}
