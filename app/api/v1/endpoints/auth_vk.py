# app/api/v1/endpoints/auth_vk.py
"""Вход через VK ID (OAuth 2.1 + PKCE). Стал возможен с доменом rrumi.ru и ООО.

Флоу (зеркало Яндекс-входа, но VK ID требует PKCE и device_id):
  /start → генерим одноразовый state + PKCE code_verifier (в Redis), редиректим
  на id.vk.ru/authorize с code_challenge → VK возвращает на /callback с
  code + state + device_id → обмениваем code на access_token (id.vk.ru/oauth2/auth,
  БЕЗ client_secret — публичный клиент, безопасность на code_verifier) → берём
  профиль (oauth2/user_info) → связываем по НОМЕРУ ТЕЛЕФОНА (scope phone,
  номер проверен VK):
  - номер известен нам → вход в существующий аккаунт;
  - номер новый → создаём клиента (пароль случайный, вход через VK или сброс);
  - VK не отдал номер → на обычную регистрацию.

Секреты только в .env; токены VK не логируются и не хранятся — нужны один раз
на время callback'а.
"""
import base64
import hashlib
import secrets
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.config import settings
from app.core.limiter import get_redis, limiter
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.models import User, UserRole
from app.schemas.user import try_normalize_phone

router = APIRouter()

AUTH_URL = "https://id.vk.ru/authorize"
TOKEN_URL = "https://id.vk.ru/oauth2/auth"
INFO_URL = "https://id.vk.ru/oauth2/user_info"

# Скоуп: phone обязателен (наша модель телефон-центрична), email — бонус.
# Имя/аватар VK отдаёт в user_info по умолчанию.
SCOPE = "phone email"
_STATE_TTL = 600  # 10 минут на прохождение флоу


def _redirect_uri(request: Request) -> str:
    """Callback строго на нашем хосте (тот же, что зарегистрирован в кабинете VK)."""
    return f"https://{request.url.netloc}/api/v1/auth/vk/callback"


def _pkce_pair() -> tuple[str, str]:
    """code_verifier (хранится у нас) + code_challenge=S256 (уходит в VK)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def _set_auth_cookie(response: RedirectResponse, user_id: int) -> None:
    from app.api.v1.endpoints.auth_web import _set_auth_cookie as _impl

    _impl(response, user_id)


@router.get("/vk/start")
@limiter.limit("10/minute")
async def vk_start(request: Request):
    """Кнопка «Войти с VK ID» ведёт сюда."""
    if not settings.VK_OAUTH_ENABLED:
        return RedirectResponse(url="/login", status_code=302)

    state = str(uuid.uuid4())
    verifier, challenge = _pkce_pair()
    r = get_redis()
    # Храним code_verifier по state (он же — CSRF-маркер, одноразовый).
    await r.set(f"oauth:vk:{state}", verifier, ex=_STATE_TTL)

    from urllib.parse import urlencode

    params = urlencode({
        "response_type": "code",
        "client_id": settings.VK_CLIENT_ID,
        "scope": SCOPE,
        "redirect_uri": _redirect_uri(request),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return RedirectResponse(url=f"{AUTH_URL}?{params}", status_code=302)


async def _exchange_code(code: str, code_verifier: str, device_id: str, redirect_uri: str) -> str | None:
    """code → access_token (PKCE, без client_secret). None при любом отказе VK."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": settings.VK_CLIENT_ID,
            "device_id": device_id,
            "redirect_uri": redirect_uri,
        })
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


async def _fetch_profile(access_token: str) -> dict | None:
    """access_token → объект user {user_id, first_name, last_name, phone, email}."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(INFO_URL, data={
            "client_id": settings.VK_CLIENT_ID,
            "access_token": access_token,
        })
    if resp.status_code != 200:
        return None
    return resp.json().get("user")


@router.get("/vk/callback")
@limiter.limit("10/minute")
async def vk_callback(
    request: Request,
    code: str = "",
    state: str = "",
    device_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    if not settings.VK_OAUTH_ENABLED:
        return RedirectResponse(url="/login", status_code=302)

    # state одноразовый: нет в Redis (истёк/подделан/повторён) — отказ.
    # Значение = PKCE code_verifier для обмена кода.
    r = get_redis()
    verifier = await r.get(f"oauth:vk:{state}") if state else None
    if not verifier:
        return RedirectResponse(url="/login?error=vk", status_code=302)
    await r.delete(f"oauth:vk:{state}")

    if not code or not device_id:
        return RedirectResponse(url="/login?error=vk", status_code=302)

    if isinstance(verifier, bytes):
        verifier = verifier.decode()

    token = await _exchange_code(code, verifier, device_id, _redirect_uri(request))
    profile = await _fetch_profile(token) if token else None
    if not profile:
        return RedirectResponse(url="/login?error=vk", status_code=302)

    phone = try_normalize_phone(str(profile.get("phone") or ""))
    if not phone:
        # VK не отдал номер — наша модель телефон-центрична, без него аккаунт
        # не завести. Отправляем на обычную регистрацию.
        return RedirectResponse(url="/register?error=vk_no_phone", status_code=302)

    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None:
        display_name = " ".join(
            p for p in (profile.get("first_name"), profile.get("last_name")) if p
        ).strip()[:100]
        user = User(
            phone=phone,
            full_name=display_name or None,
            # Пароль никому не известен: вход — через VK либо сброс.
            hashed_password=get_password_hash(secrets.token_hex(32)),
            role=UserRole.CLIENT,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    if not user.is_active:
        return RedirectResponse(url="/login?error=locked", status_code=302)

    response = RedirectResponse(url="/profile", status_code=302)
    _set_auth_cookie(response, user.id)
    return response
