# app/api/v1/endpoints/auth_web.py
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.models import User, UserRole, ConsentDocument
from app.schemas.user import try_normalize_phone
from app.core.config import settings
from app.core.security import (
    create_access_token,      # единая функция для JWT
    get_password_hash,
    verify_password,
    needs_rehash,
    validate_password_strength,
)
from app.core.limiter import (
    limiter,
    is_account_locked,
    otp_send_allowed,
    register_login_failure,
    reset_login_failures,
)
from app.services import otp
from app.services.consent_service import record_consent
from app.services import password_reset

router = APIRouter()

def _safe_redirect(target: str) -> str:
    """Защита от open redirect."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target

def _set_auth_cookie(response: RedirectResponse, user_id: int) -> None:
    """Устанавливает cookie с JWT-токеном (используя create_access_token из security)."""
    token = create_access_token(user_id)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/",
    )


@router.post("/login-web")
@limiter.limit("5/minute")  # лимит по IP

async def login_web(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    redirect: str = Form("/"),
    db: AsyncSession = Depends(get_db),
):
    """Вход через веб-форму."""
    redirect = _safe_redirect(redirect)
    norm_phone = try_normalize_phone(phone)
    lookup_phone = norm_phone or phone
    keep_phone = quote(lookup_phone)

    if norm_phone and await is_account_locked(norm_phone):
        return RedirectResponse(
            url=f"/login?error=locked&redirect={quote(redirect)}&phone={keep_phone}",
            status_code=302,
        )

    result = await db.execute(select(User).where(User.phone == lookup_phone))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        if norm_phone:
            await register_login_failure(norm_phone)
        return RedirectResponse(
            url=f"/login?error=1&redirect={quote(redirect)}&phone={keep_phone}",
            status_code=302,
        )

    # Деактивированный аккаунт (мягкое удаление / блокировка админом) не пускаем —
    # иначе is_active=False ничего не значит на веб-пути (см. deps.get_current_user).
    if not user.is_active:
        return RedirectResponse(
            url=f"/login?error=locked&redirect={quote(redirect)}&phone={keep_phone}",
            status_code=302,
        )

    if norm_phone:
        await reset_login_failures(norm_phone)

    # Бесшовная миграция старого хеша на Argon2id
    if needs_rehash(user.hashed_password):
        user.hashed_password = get_password_hash(password)
        await db.commit()

    response = RedirectResponse(url=redirect, status_code=302)
    _set_auth_cookie(response, user.id)
    return response


@router.post("/register-web")
# Лимит по IP: у формы регистрации его не было вовсе, и двойное нажатие
# обрабатывалось дважды в полную силу (инцидент 04.09.2026). Порог
# щадящий — за одним IP может сидеть целый салон.
@limiter.limit("10/minute")
async def register_web(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    request_id: str = Form(""),
    code: str = Form(""),
    pd_consent: str = Form(""),
    consent_version: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Регистрация через веб-форму. Роль всегда CLIENT (назначает сервер).

    ВНИМАНИЕ ПРИ MERGE: поля request_id/code и блок verify_code ниже — это
    подтверждение телефона (блоки 07 SMS + 18 Telegram). Эта обвязка уже
    трижды терялась при разрешении конфликтов «в пользу frontend-ветки» —
    не удалять; без неё регистрация не проверяет телефон вовсе.
    """
    norm_phone = try_normalize_phone(phone)
    keep = f"phone={quote(norm_phone or phone)}&full_name={quote(full_name)}"

    if norm_phone is None:
        return RedirectResponse(url=f"/register?error=bad_phone&{keep}", status_code=302)

    # Согласие на обработку ПДн обязательно: без него нельзя создавать учётную
    # запись, потому что сама регистрация и есть сбор персональных данных.
    if pd_consent != "1":
        return RedirectResponse(url=f"/register?error=no_consent&{keep}", status_code=302)

    try:
        validate_password_strength(password)
    except ValueError:
        return RedirectResponse(url=f"/register?error=weak_password&{keep}", status_code=302)

    existing = (await db.execute(select(User).where(User.phone == norm_phone))).scalar_one_or_none()
    # Реальный аккаунт с этим номером блокирует регистрацию; гостя (создан
    # гостевой записью) — не блокируем, «заберём» после верификации ниже.
    if existing is not None and not existing.is_guest:
        return RedirectResponse(url=f"/register?error=phone_exists&{keep}", status_code=302)

    # При выключенном OTP (нет каналов) поля подтверждения не требуем вовсе —
    # страница их и не показывает; verify_code в этом режиме всегда True.
    # Требуем только request_id: код нужен лишь СМС-каналу, для Telegram
    # его нет по устройству — какой канал и что проверять, решает verify_code.
    if settings.OTP_ENABLED and not request_id:
        return RedirectResponse(url=f"/register?error=no_code&{keep}", status_code=302)

    try:
        code_valid = await otp.verify_code(request_id, code, norm_phone)
    except otp.OTPError:
        return RedirectResponse(url=f"/register?error=otp_unavailable&{keep}", status_code=302)

    if not code_valid:
        return RedirectResponse(url=f"/register?error=bad_code&{keep}", status_code=302)

    if existing is not None:
        # Гость «забирается»: апгрейд до полноценного аккаунта. Гостевые брони
        # (client_id=existing.id) остаются за ним.
        user = existing
        user.full_name = full_name or user.full_name
        user.hashed_password = get_password_hash(password)
        user.is_guest = False
        user.is_active = True
    else:
        user = User(
            phone=norm_phone,
            full_name=full_name,
            hashed_password=get_password_hash(password),
            role=UserRole.CLIENT,
            is_active=True,
        )
        db.add(user)
    await db.commit()
    await db.refresh(user)

    # Если номер подтверждали ботом (Telegram или MAX) — забираем оставленный
    # им chat_id в профиль и выставляем канал уведомлений: чем подтвердил,
    # туда и шлём. Уведомления о записях заработают с первого дня.
    from app.services.notify_channel import bind_after_verification
    await bind_after_verification(db, user, norm_phone)

    # id читаем до записи журнала: record_consent делает commit, а он сбрасывает
    # состояние объекта, и обращение к user.id после него уходит в ленивую
    # подгрузку внутри async-контекста.
    user_id = user.id
    await record_consent(
        db, document=ConsentDocument.PD_CONSENT, version=consent_version,
        source="register", user_id=user_id, phone=norm_phone, request=request,
    )

    response = RedirectResponse(url="/profile", status_code=302)
    _set_auth_cookie(response, user_id)
    return response

@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password_web(
    request: Request,
    phone: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """«Забыли пароль»: выпускает токен и шлёт ссылку по каналам пользователя.

    Ответ ОДИНАКОВ для любого номера — существование аккаунта не раскрываем
    (анти-перебор). Поверх IP-лимита — бюджет попыток на номер (тот же,
    что у OTP: каналы разные, защита одна).
    """
    norm_phone = try_normalize_phone(phone)
    done_url = "/forgot-password?sent=1"

    if norm_phone is None:
        return RedirectResponse(url=done_url, status_code=302)
    if not await otp_send_allowed(norm_phone):
        return RedirectResponse(url=done_url, status_code=302)

    user = (
        await db.execute(select(User).where(User.phone == norm_phone))
    ).scalar_one_or_none()
    if user and user.is_active:
        token = await password_reset.issue_token(user)
        await password_reset.deliver(user, token, request.url.netloc)

    return RedirectResponse(url=done_url, status_code=302)


@router.post("/reset-password")
@limiter.limit("10/minute")
async def reset_password_web(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Смена пароля по одноразовому токену из ссылки (TG/email)."""
    try:
        validate_password_strength(password)
    except ValueError:
        return RedirectResponse(
            url=f"/reset-password?token={quote(token)}&error=weak_password",
            status_code=302,
        )

    user_id = await password_reset.consume_token(token)
    if user_id is None:
        return RedirectResponse(url="/reset-password?error=bad_token", status_code=302)

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return RedirectResponse(url="/reset-password?error=bad_token", status_code=302)

    user.hashed_password = get_password_hash(password)
    await db.commit()

    # Смена пароля снимает блокировку перебора и уведомляет владельца
    await reset_login_failures(user.phone)
    await password_reset.notify_changed(user)

    return RedirectResponse(url="/login?reset=1", status_code=302)
