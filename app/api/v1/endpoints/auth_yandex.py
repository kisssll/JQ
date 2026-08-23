# app/api/v1/endpoints/auth_yandex.py
"""Вход через Яндекс ID (OAuth 2.0). Стал возможен с доменом rrumi.ru.

Флоу: /start → redirect на oauth.yandex.ru (с одноразовым state в Redis,
защита от CSRF) → Яндекс возвращает на /callback с code → обмениваем на
токен → берём профиль (login.yandex.ru/info) → связываем по НОМЕРУ
ТЕЛЕФОНА (scope login:default_phone, номер проверен Яндексом — наша
телефон-центричная модель сохраняется):
- номер известен нам → вход в существующий аккаунт;
- номер новый → создаём клиента (пароль — случайный, вход через Яндекс
  или сброс пароля; телефон считается подтверждённым);
- Яндекс не отдал номер (пользователь запретил) → на обычную регистрацию.

Секреты только в .env; токены Яндекса не логируются и не хранятся —
нужны один раз на время callback'а.
"""
import secrets
import uuid

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import get_redis, limiter
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.models import User, UserRole
from app.schemas.user import try_normalize_phone

router = APIRouter()

AUTH_URL = "https://oauth.yandex.ru/authorize"
TOKEN_URL = "https://oauth.yandex.ru/token"
INFO_URL = "https://login.yandex.ru/info"

_STATE_TTL = 600  # 10 минут на прохождение флоу


def _redirect_uri(request: Request) -> str:
    """Callback строго на нашем хосте (тот же, что зарегистрирован у Яндекса)."""
    return f"https://{request.url.netloc}/api/v1/auth/yandex/callback"


def _set_auth_cookie(response: RedirectResponse, user_id: int) -> None:
    from app.api.v1.endpoints.auth_web import _set_auth_cookie as _impl

    _impl(response, user_id)


@router.get("/yandex/start")
@limiter.limit("10/minute")
async def yandex_start(request: Request):
    """Кнопка «Войти с Яндекс ID» ведёт сюда."""
    if not settings.YANDEX_OAUTH_ENABLED:
        return RedirectResponse(url="/login", status_code=302)

    state = str(uuid.uuid4())
    r = get_redis()
    await r.set(f"oauth:yandex:{state}", "1", ex=_STATE_TTL)

    from urllib.parse import urlencode

    params = urlencode({
        "response_type": "code",
        "client_id": settings.YANDEX_CLIENT_ID,
        "redirect_uri": _redirect_uri(request),
        "state": state,
    })
    return RedirectResponse(url=f"{AUTH_URL}?{params}", status_code=302)


async def _exchange_code(code: str, redirect_uri: str) -> str | None:
    """code → access_token. None при любом отказе Яндекса."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.YANDEX_CLIENT_ID,
            "client_secret": settings.YANDEX_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
        })
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


async def _fetch_profile(access_token: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            INFO_URL, params={"format": "json"},
            headers={"Authorization": f"OAuth {access_token}"},
        )
    if resp.status_code != 200:
        return None
    return resp.json()


@router.get("/yandex/callback")
@limiter.limit("10/minute")
async def yandex_callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    if not settings.YANDEX_OAUTH_ENABLED:
        return RedirectResponse(url="/login", status_code=302)

    # state одноразовый: нет в Redis (истёк/подделан/повторён) — отказ
    r = get_redis()
    known = await r.get(f"oauth:yandex:{state}") if state else None
    if not known:
        return RedirectResponse(url="/login?error=yandex", status_code=302)
    await r.delete(f"oauth:yandex:{state}")

    if not code:
        return RedirectResponse(url="/login?error=yandex", status_code=302)

    token = await _exchange_code(code, _redirect_uri(request))
    profile = await _fetch_profile(token) if token else None
    if not profile:
        return RedirectResponse(url="/login?error=yandex", status_code=302)

    raw_phone = ((profile.get("default_phone") or {}).get("number")) or ""
    phone = try_normalize_phone(raw_phone)
    if not phone:
        # Пользователь не поделился номером — наша модель телефон-центрична,
        # без него аккаунт не завести. Отправляем на обычную регистрацию.
        return RedirectResponse(url="/register?error=yandex_no_phone", status_code=302)

    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None:
        display_name = (
            profile.get("real_name") or profile.get("display_name") or ""
        ).strip()[:100]
        user = User(
            phone=phone,
            full_name=display_name or None,
            # Пароль никому не известен: вход — через Яндекс либо сброс.
            # Argon2id от 64 случайных hex — брутфорсу ловить нечего.
            hashed_password=get_password_hash(secrets.token_hex(32)),
            role=UserRole.CLIENT,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Почта из профиля — единственный канал уведомлений у тех, кто вошёл через
    # OAuth и не подключал мессенджер (см. services/notify_channel.py).
    from app.services.notify_channel import adopt_oauth_email
    await adopt_oauth_email(db, user, profile.get("default_email"))

    if not user.is_active:
        return RedirectResponse(url="/login?error=locked", status_code=302)

    response = RedirectResponse(url="/profile", status_code=302)
    _set_auth_cookie(response, user.id)
    return response
