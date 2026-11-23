# app/core/security.py
"""Единая точка для паролей и JWT по всему проекту.

- Пароли: Argon2id (memory-hard) через passlib. Старые bcrypt/pbkdf2-хеши
  ещё проверяются (deprecated) и автоматически переподписываются при логине.
  Сырой unsalted SHA-256 НЕ принимается (это была уязвимость).
- JWT: RS256 (асимметричная подпись). Приватным ключом подписываем,
  публичным проверяем. Ключи — в файлах вне git (см. app/scripts/gen_keys.py).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import jwt
from jwt.exceptions import PyJWTError
from passlib.context import CryptContext

from app.core.config import settings

# ── Пароли ───────────────────────────────────────────────────────────────────
# argon2 — основной; bcrypt/pbkdf2 оставлены deprecated для бесшовной миграции
# исторических хешей (passlib помечает их needs_update → перехешируем на логине).
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt", "pbkdf2_sha256"],
    deprecated=["bcrypt", "pbkdf2_sha256"],
)


def get_password_hash(password: str) -> str:
    """Хеширует пароль текущей схемой (Argon2id)."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль. Неизвестный формат (например, сырой sha256) → False."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        # passlib не распознал формат хеша — считаем пароль неверным
        return False


def needs_rehash(hashed_password: str) -> bool:
    """True, если хеш сделан устаревшей схемой и его пора переподписать."""
    try:
        return pwd_context.needs_update(hashed_password)
    except (ValueError, TypeError):
        return True


# ── Политика сложности пароля (бриф 3.2) ────────────────────────────────────
MIN_PASSWORD_LENGTH = 8

# Небольшой стоп-лист очевидно слабых паролей
_COMMON_PASSWORDS = {
    "password", "qwerty", "12345678", "123456789", "1234567890",
    "master123", "client123", "owner123", "model123", "anna123456",
    "admin", "adminadmin", "qwerty123", "password1",
}


def validate_password_strength(password: str) -> None:
    """Бросает ValueError с понятным сообщением, если пароль слабый.

    Требования: длина ≥ 8, есть строчная и заглавная буква и цифра,
    не входит в стоп-лист. Тестовые `anna123456`/`master123` это не проходят.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Слишком распространённый пароль")
    if not re.search(r"[a-zа-яё]", password):
        raise ValueError("Пароль должен содержать строчную букву")
    if not re.search(r"[A-ZА-ЯЁ]", password):
        raise ValueError("Пароль должен содержать заглавную букву")
    if not re.search(r"\d", password):
        raise ValueError("Пароль должен содержать цифру")


# ── JWT (RS256) ──────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _private_key() -> str:
    path = Path(settings.JWT_PRIVATE_KEY_PATH)
    if not path.exists():
        raise RuntimeError(
            f"Не найден приватный JWT-ключ: {path}. "
            "Сгенерируйте: python -m app.scripts.gen_keys"
        )
    return path.read_text()


@lru_cache(maxsize=1)
def _public_key() -> str:
    path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if not path.exists():
        raise RuntimeError(
            f"Не найден публичный JWT-ключ: {path}. "
            "Сгенерируйте: python -m app.scripts.gen_keys"
        )
    return path.read_text()


def create_access_token(subject: int | str, expires_delta: Optional[timedelta] = None) -> str:
    """Создаёт подписанный RS256 access-токен. subject → claim `sub`."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"jti": uuid.uuid4().hex, "sub": str(subject), "iat": now, "exp": expire}
    return jwt.encode(payload, _private_key(), algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Проверяет подпись/срок токена. Возвращает payload или None."""
    try:
        return jwt.decode(token, _public_key(), algorithms=[settings.ALGORITHM])
    except PyJWTError:
        return None
