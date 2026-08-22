# app/api/v1/endpoints/auth.py
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.models import User, UserRole
from app.schemas.user import RegisterRequest, LoginRequest, SendCodeRequest
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
    needs_rehash,
    validate_password_strength,
)
from app.core.config import settings
from app.core.limiter import (
    limiter,
    is_account_locked,
    otp_send_allowed,
    register_login_failure,
    reset_login_failures,
)
from app.services import otp

router = APIRouter()


@router.post("/register/send-code")
@limiter.limit("3/minute")
async def send_register_code(
    request: Request,
    data: SendCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Отправляет код подтверждения на телефон перед регистрацией."""
    # В production mock-СМС не канал (коды никуда не уходят): пока нет
    # договора с провайдером, СМС-путь закрыт — есть Telegram (tg-start).
    if settings.ENVIRONMENT == "production" and settings.SMS_MODE == "mock":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Подтверждение по СМС временно недоступно",
        )

    existing_user = (await db.execute(select(User).where(User.phone == data.phone))).scalar_one_or_none()
    # Гость (создан гостевой записью) НЕ блокирует: verification-start его
    # пропускает, register — «забирает» (is_guest→False ниже). Реальный — блок.
    if existing_user is not None and not existing_user.is_guest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким номером уже зарегистрирован",
        )

    # Второй лимит поверх IP-шного slowapi: по самому номеру, против
    # распределённого SMS-бомбинга одного телефона с разных IP
    if not await otp_send_allowed(data.phone):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов кода на этот номер, попробуйте позже",
        )

    try:
        result = await otp.send_code(data.phone)
    except otp.OTPError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    return result


@router.post("/register/tg-start")
@limiter.limit("3/minute")
async def start_tg_verification(
    request: Request,
    data: SendCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Начинает подтверждение телефона через Telegram-бота (блок 18).

    Возвращает deep link на бота; дальше бот переводит запись в confirmed,
    страница узнаёт об этом через /register/tg-status.
    """
    if not settings.TG_VERIFY_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Подтверждение через Telegram выключено",
        )

    existing_user = (await db.execute(select(User).where(User.phone == data.phone))).scalar_one_or_none()
    # Гость (создан гостевой записью) НЕ блокирует: verification-start его
    # пропускает, register — «забирает» (is_guest→False ниже). Реальный — блок.
    if existing_user is not None and not existing_user.is_guest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким номером уже зарегистрирован",
        )

    # Общий с send-code бюджет попыток на номер: каналы разные, цель одна
    if not await otp_send_allowed(data.phone):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток подтверждения этого номера, попробуйте позже",
        )

    try:
        return await otp.start_tg_verification(data.phone)
    except otp.OTPError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.post("/register/max-start")
@limiter.limit("3/minute")
async def start_max_verification(
    request: Request,
    data: SendCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Начинает подтверждение телефона через MAX-бота (блок 18, этап 2)."""
    if not settings.MAX_VERIFY_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Подтверждение через MAX выключено",
        )

    existing_user = (await db.execute(select(User).where(User.phone == data.phone))).scalar_one_or_none()
    # Гость (создан гостевой записью) НЕ блокирует: verification-start его
    # пропускает, register — «забирает» (is_guest→False ниже). Реальный — блок.
    if existing_user is not None and not existing_user.is_guest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким номером уже зарегистрирован",
        )

    # Общий с остальными каналами бюджет попыток на номер
    if not await otp_send_allowed(data.phone):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток подтверждения этого номера, попробуйте позже",
        )

    try:
        return await otp.start_messenger_verification(data.phone, "max")
    except otp.OTPError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.get("/register/tg-status")
@limiter.limit("30/minute")
async def tg_verification_status(request: Request, request_id: str):
    """Статус подтверждения (Telegram И MAX — имя историческое) для поллинга:
    pending|confirmed|not_found."""
    if not (settings.TG_VERIFY_ENABLED or settings.MAX_VERIFY_ENABLED):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Подтверждение через мессенджеры выключено",
        )
    try:
        return {"status": await otp.get_tg_status(request_id)}
    except otp.OTPError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.post("/register")
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Регистрация нового пользователя.

    Роль ВСЕГДА client — её нельзя задать из запроса (защита от privilege
    escalation). BUSINESS/MASTER назначаются отдельным модерируемым процессом.

    Требует предварительного вызова /register/send-code — телефон должен
    быть подтверждён кодом (request_id/code проверяются в app.services.otp).
    """
    try:
        validate_password_strength(data.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    existing_user = (await db.execute(select(User).where(User.phone == data.phone))).scalar_one_or_none()
    # Гость (создан гостевой записью) НЕ блокирует: verification-start его
    # пропускает, register — «забирает» (is_guest→False ниже). Реальный — блок.
    if existing_user is not None and not existing_user.is_guest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким номером уже зарегистрирован",
        )

    try:
        code_valid = await otp.verify_code(data.request_id, data.code, data.phone)
    except otp.OTPError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    if not code_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный или истёкший код подтверждения",
        )

    if existing_user is not None:
        # «Забираем» гостя: апгрейд до полноценного аккаунта, гостевые брони за ним.
        user = existing_user
        user.full_name = data.full_name or user.full_name
        user.hashed_password = get_password_hash(data.password)
        user.is_guest = False
        user.is_active = True
    else:
        user = User(
            phone=data.phone,
            full_name=data.full_name,
            hashed_password=get_password_hash(data.password),
            role=UserRole.CLIENT,  # назначается сервером, не из тела запроса
        )
        db.add(user)
    await db.commit()
    await db.refresh(user)

    # Привязка мессенджера (TG/MAX) + канал уведомлений, если номер
    # подтверждали ботом (см. auth_web то же)
    from app.services.notify_channel import bind_after_verification
    await bind_after_verification(db, user, data.phone)

    token = create_access_token(user.id)

    return {
        "user": {
            "id": user.id,
            "phone": user.phone,
            "full_name": user.full_name,
            "role": user.role
        },
        "access_token": token,
        "token_type": "bearer"
    }


@router.post("/login")
@limiter.limit("5/minute")  # лимит по IP (общий счётчик в Redis между воркерами)
async def login(
    request: Request,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Вход. Возвращает JWT (Authorization: Bearer <токен>)."""
    # Уровень блокировки по аккаунту (против распределённого брутфорса)
    if await is_account_locked(data.phone):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа. Попробуйте через 15 минут.",
        )

    result = await db.execute(select(User).where(User.phone == data.phone))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        await register_login_failure(data.phone)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный номер телефона или пароль",
        )

    await reset_login_failures(data.phone)

    # Бесшовная миграция: старый bcrypt/pbkdf2-хеш → переподписываем на Argon2id
    if needs_rehash(user.hashed_password):
        user.hashed_password = get_password_hash(data.password)
        await db.commit()

    token = create_access_token(user.id)
    return {
        "user": {
            "id": user.id,
            "phone": user.phone,
            "full_name": user.full_name,
            "role": user.role,
        },
        "access_token": token,
        "token_type": "bearer",
    }
