# app/api/v1/endpoints/users.py
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.models import User
from app.schemas.user import UserResponse, UserUpdate
from app.api.deps import get_current_user
from app.core.limiter import limiter

router = APIRouter()

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Получить профиль текущего пользователя"""
    return current_user

@router.post("/me")
async def update_me_form(
    request: Request,
    full_name: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Обновление имени пользователя через веб-форму."""
    from app.web.auth import get_current_user_from_cookie
    
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    user.full_name = full_name
    await db.commit()
    
    return RedirectResponse(url="/profile?success=updated", status_code=302)

@router.patch("/me", response_model=UserResponse)
async def update_me(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Обновить профиль текущего пользователя"""
    
    if user_data.full_name is not None:
        current_user.full_name = user_data.full_name

    # Email НЕ меняется здесь: смена email требует подтверждения кодом на новый
    # адрес — единственный путь /me/email/send-code → /me/email-form (иначе
    # это обход верификации). Поле email в теле игнорируем намеренно.

    if user_data.avatar_url is not None:
        current_user.avatar_url = user_data.avatar_url
    
    if user_data.portfolio_desc is not None:
        current_user.portfolio_desc = user_data.portfolio_desc
    
    await db.commit()
    await db.refresh(current_user)
    
    return current_user

@router.post("/me/update-form")
async def update_profile_form(
    request: Request,
    full_name: str = Form(...),
    avatar_url: str = Form(None),
    portfolio_desc: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Обновление профиля через форму (имя/аватар/био).

    Email здесь НЕ меняется: для него отдельный верифицированный путь
    /me/email/send-code → /me/email-form (подтверждение кодом на новый адрес).
    """
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Обновляем базовые поля
    user.full_name = full_name

    if avatar_url is not None:
        user.avatar_url = avatar_url
    
    if portfolio_desc is not None:
        user.portfolio_desc = portfolio_desc
    
    await db.commit()
    await db.refresh(user)
    
    return RedirectResponse(url="/profile?success=updated", status_code=302)

@router.post("/me/password-form")
async def update_password_form(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Обновление пароля через форму (веб-интерфейс)."""
    from app.web.auth import get_current_user_from_cookie
    from app.core.security import (
        verify_password,
        get_password_hash,
        validate_password_strength,
    )

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Проверяем текущий пароль через единый интерфейс (Argon2id + legacy)
    if not verify_password(current_password, user.hashed_password):
        return RedirectResponse(url="/profile?error=wrong_password", status_code=302)

    # Проверяем совпадение паролей
    if new_password != confirm_password:
        return RedirectResponse(url="/profile?error=password_mismatch", status_code=302)

    # Политика сложности пароля
    try:
        validate_password_strength(new_password)
    except ValueError:
        return RedirectResponse(url="/profile?error=password_too_short", status_code=302)

    # Обновляем пароль (Argon2id)
    user.hashed_password = get_password_hash(new_password)
    await db.commit()
    
    return RedirectResponse(
        url="/profile?success=password_updated",
        status_code=302
    )

@router.post("/me/email/send-code")
@limiter.limit("3/minute")
async def email_send_code(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Шлёт код подтверждения на НОВЫЙ email (шаг 1 смены email)."""
    from app.web.auth import get_current_user_from_cookie
    from app.services import email_verify

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"detail": "Не авторизованы"}, status_code=401)

    email = (email or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse({"detail": "Некорректный email"}, status_code=400)
    if email == (user.email or "").lower():
        return JSONResponse({"detail": "Это ваш текущий email"}, status_code=400)

    existing = await db.execute(
        select(User).where(User.email == email, User.id != user.id)
    )
    if existing.scalar_one_or_none():
        return JSONResponse({"detail": "Этот email уже используется"}, status_code=409)

    try:
        result = await email_verify.send_email_code(email)
    except email_verify.EmailVerifyError as e:
        return JSONResponse({"detail": str(e)}, status_code=503)

    return JSONResponse(result)


@router.post("/me/email-form")
async def update_email_form(
    request: Request,
    email: str = Form(...),
    request_id: str = Form(""),
    code: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Смена email — шаг 2: применяет новый адрес после ввода кода из письма."""
    from app.web.auth import get_current_user_from_cookie
    from app.services import email_verify

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    email = (email or "").strip().lower()
    if not email:
        return RedirectResponse(url="/profile?error=update_failed", status_code=302)

    if email == (user.email or "").lower():
        return RedirectResponse(url="/profile?success=email_updated", status_code=302)

    existing = await db.execute(
        select(User).where(User.email == email, User.id != user.id)
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/profile?error=email_taken", status_code=302)

    try:
        ok = await email_verify.verify_email_code(request_id, code, email)
    except email_verify.EmailVerifyError:
        return RedirectResponse(url="/profile?error=otp_unavailable", status_code=302)
    if not ok:
        return RedirectResponse(url="/profile?error=email_not_verified", status_code=302)

    user.email = email
    await db.commit()

    return RedirectResponse(url="/profile?success=email_updated", status_code=302)


@router.post("/me/city-form")
async def update_city_form(
    request: Request,
    city: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Смена города через веб-форму."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    user.city = (city or "").strip() or None
    await db.commit()

    return RedirectResponse(url="/profile?success=city_updated", status_code=302)


@router.post("/me/notify-channel")
async def update_notify_channel_form(
    request: Request,
    channel: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Смена канала уведомлений (Telegram / MAX / почта).

    Переключиться можно только на ПОДКЛЮЧЁННЫЙ канал: выбрать мессенджер, к
    которому не привязан бот, нельзя — иначе уведомления молча перестали бы
    приходить.
    """
    from app.web.auth import get_current_user_from_cookie
    from app.models.models import NotifyChannel

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        target = NotifyChannel(channel)
    except ValueError:
        return RedirectResponse(url="/profile?error=notify_channel_invalid", status_code=302)

    addresses = {
        NotifyChannel.TG: user.tg_chat_id,
        NotifyChannel.MAX: user.max_chat_id,
        NotifyChannel.EMAIL: (user.email or "").strip() or None,
    }
    if target == NotifyChannel.NONE or not addresses.get(target):
        return RedirectResponse(url="/profile?error=notify_channel_unavailable", status_code=302)

    user.notify_channel = target
    await db.commit()
    return RedirectResponse(url="/profile?success=notify_channel_updated", status_code=302)


@router.post("/me/disconnect-channel")
async def disconnect_channel_form(
    request: Request,
    channel: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Отвязать мессенджер (Telegram или MAX).

    Последний рабочий канал отвязать нельзя: иначе человек молча перестал бы
    получать напоминания о записях и предупреждения об оплате, не понимая
    почему. Просим сначала подключить другой (решение Артёма).
    """
    from app.web.auth import get_current_user_from_cookie
    from app.models.models import NotifyChannel
    from app.services.notify_channel import resolve

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        target = NotifyChannel(channel)
    except ValueError:
        return RedirectResponse(url="/profile?error=notify_channel_invalid", status_code=302)
    if target not in (NotifyChannel.TG, NotifyChannel.MAX):
        return RedirectResponse(url="/profile?error=notify_channel_invalid", status_code=302)

    # Сколько каналов останется, если отвязать этот
    remaining = []
    if user.tg_chat_id and target != NotifyChannel.TG:
        remaining.append(NotifyChannel.TG)
    if user.max_chat_id and target != NotifyChannel.MAX:
        remaining.append(NotifyChannel.MAX)
    if (user.email or "").strip():
        remaining.append(NotifyChannel.EMAIL)
    if not remaining:
        return RedirectResponse(url="/profile?error=notify_channel_last", status_code=302)

    if target == NotifyChannel.TG:
        user.tg_chat_id = None
    else:
        user.max_chat_id = None

    # Если отвязали текущий канал доставки — переводим на оставшийся
    if user.notify_channel == target:
        user.notify_channel = remaining[0]
    await db.commit()
    # Страховка: канал мог протухнуть иначе — синхронизируем с реальностью
    actual, _addr = resolve(user)
    if user.notify_channel != actual:
        user.notify_channel = actual
        await db.commit()
    return RedirectResponse(url="/profile?success=notify_channel_disconnected", status_code=302)


@router.post("/me/phone-form")
async def update_phone_form(
    request: Request,
    phone: str = Form(...),
    request_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Смена телефона с подтверждением владения новым номером через Telegram.

    Телефон — логин-идентификатор, поэтому новый номер обязан пройти ту же
    TG-верификацию, что и при регистрации (request_id из /register/tg-start →
    бот подтверждает контакт). verify_code одноразовый; при OTP_ENABLED=false
    вернёт True (fallback для окружений без OTP).
    """
    from app.web.auth import get_current_user_from_cookie
    from app.schemas.user import try_normalize_phone
    from app.services import otp

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    norm = try_normalize_phone(phone)
    if not norm:
        return RedirectResponse(url="/profile?error=bad_phone", status_code=302)

    if norm == user.phone:
        return RedirectResponse(url="/profile?success=phone_updated", status_code=302)

    existing = await db.execute(
        select(User).where(User.phone == norm, User.id != user.id)
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/profile?error=phone_exists", status_code=302)

    try:
        ok = await otp.verify_code(request_id, "", norm)
    except otp.OTPError:
        return RedirectResponse(url="/profile?error=otp_unavailable", status_code=302)
    if not ok:
        return RedirectResponse(url="/profile?error=phone_not_verified", status_code=302)

    user.phone = norm
    await db.commit()
    # Номер сменили через бота — переносим новую привязку мессенджера и канал
    from app.services.notify_channel import bind_after_verification
    await bind_after_verification(db, user, norm)

    return RedirectResponse(url="/profile?success=phone_updated", status_code=302)


@router.post("/me/delete-form")
async def delete_account_form(
    request: Request,
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Мягкое удаление аккаунта: деактивация + сброс cookie (выход).

    Данные (брони/отзывы/салоны) сохраняются — админ может восстановить.
    Требует подтверждения текущим паролем.
    """
    from app.web.auth import get_current_user_from_cookie
    from app.core.security import verify_password

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not verify_password(password, user.hashed_password):
        return RedirectResponse(url="/profile?error=wrong_password", status_code=302)

    user.is_active = False
    await db.commit()

    response = RedirectResponse(url="/?account_deleted=1", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Получить публичный профиль пользователя по ID"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    return user