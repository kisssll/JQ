# app/services/auth_redirect.py
"""Куда вернуть человека после входа или регистрации.

Человек приходит на вход не сам по себе, а откуда-то: со страницы подключения
тарифа, с записи в салон. Раньше регистрация и вход через Яндекс/VK всегда
вели в /profile, и эта страница терялась — вместе с выбранным тарифом и
метками рекламы в адресе.
"""
from __future__ import annotations

from typing import Optional

_TTL_SECONDS = 600   # как и state OAuth: столько живёт вход через провайдера


def safe_redirect(target: Optional[str]) -> str:
    """Только относительный адрес этого сайта — защита от open redirect.
    Пустая строка, если адрес не годится."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return ""
    return target


def _key(provider: str, state: str) -> str:
    return f"oauth:{provider}:redirect:{state}"


async def remember_for_oauth(provider: str, state: str, target: Optional[str]) -> None:
    """Запомнить адрес возврата на время входа через провайдера. Сбой Redis
    не мешает входу: человек просто попадёт в профиль, как раньше."""
    target = safe_redirect(target)
    if not target:
        return
    from app.core.limiter import get_redis

    try:
        await get_redis().set(_key(provider, state), target, ex=_TTL_SECONDS)
    except Exception:
        pass


async def pop_for_oauth(provider: str, state: str, default: str = "/profile") -> str:
    from app.core.limiter import get_redis

    try:
        value = await get_redis().getdel(_key(provider, state))
    except Exception:
        value = None
    if isinstance(value, bytes):
        value = value.decode()
    return safe_redirect(value) or default
