"""Выход гасит обе копии одной сессии, даже если другая вкладка ещё открыта."""
import hashlib
import time

from app.core.config import settings
from app.core.limiter import get_redis
from app.core.security import decode_access_token


def _logout_key(token: str) -> str:
    return "web:logout:" + hashlib.sha256(token.encode()).hexdigest()


async def session_claims(token: str):
    claims = decode_access_token(token)
    if claims and settings.SPORT_HOST and await get_redis().exists(_logout_key(token)):
        return None
    return claims


async def revoke_session(token: str | None):
    if token and settings.SPORT_HOST:
        claims = decode_access_token(token)
        if claims:
            await get_redis().setex(_logout_key(token), max(1, int(claims["exp"] - time.time()) + 1), "1")
