# tests/conftest.py
"""Инфраструктура тестов (блок 12): изолированная БД + Redis + временные ключи.

Принципы:
  - БД: отдельная база beauty_test на том же Postgres (создаётся сама),
    схема — СТРОГО через alembic upgrade head (заодно проверяем миграции);
  - Redis: отдельный логический db=9, чистится перед каждым тестом
    (вместе с ним обнуляются rate-limit'ы slowapi и OTP-состояние);
  - RS256-ключи: временная пара на сессию (боевые/дев-ключи не трогаем);
  - клиент: httpx.AsyncClient поверх ASGITransport — без сетевого сервера.

Локально хост/порт/пароль Postgres берутся из .env проекта (стенд на :5433),
в CI переопределяются переменными окружения (см. job tests в devsecops.yml).
"""
import asyncio
import os
import pathlib
import signal
import tempfile

# arq.Worker.close() безусловно шлёт себе signal.SIGUSR1 (см. worker.py) — на
# POSIX (CI) это штатный сигнал, на Windows его вообще нет в модуле signal,
# и тесты с Worker(handle_signals=False) падают AttributeError ещё до assert'ов.
# Подставляем существующий сигнал-заглушку — arq использует только .name для лога.
if not hasattr(signal, "SIGUSR1"):
    signal.SIGUSR1 = signal.SIGTERM

# ── Окружение — ДО любого импорта приложения ────────────────────────────────
_KEYS_DIR = tempfile.mkdtemp(prefix="rumi-test-keys-")

os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ["POSTGRES_DB"] = "beauty_test"          # приложение смотрит в тестовую БД
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/9")
os.environ["ENVIRONMENT"] = "development"          # dev_code в ответе, cookie без Secure
os.environ["OTP_ENABLED"] = "true"
os.environ["SMS_MODE"] = "mock"
os.environ["CORS_ORIGINS"] = '["http://testserver"]'
os.environ["JWT_PRIVATE_KEY_PATH"] = str(pathlib.Path(_KEYS_DIR) / "jwt_private.pem")
os.environ["JWT_PUBLIC_KEY_PATH"] = str(pathlib.Path(_KEYS_DIR) / "jwt_public.pem")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pathlib.Path(os.environ["JWT_PRIVATE_KEY_PATH"]).write_bytes(
    _key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
)
pathlib.Path(os.environ["JWT_PUBLIC_KEY_PATH"]).write_bytes(
    _key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402
from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402

from app.core.config import settings  # noqa: E402  (уже с тестовым окружением)


# ── Grandfather published_at в тестах ────────────────────────────────────────
# Салон, СОЗДАННЫЙ сразу как approved (в обход боевого флоу «заявка → одобрение
# → публикация»), считается уже опубликованным — ровно как боевой бэкфилл в
# миграции a1b2c3d4e5f6. Одобрение через админ-эндпоинт делает UPDATE, а не
# INSERT, поэтому листенер его НЕ трогает: published_at остаётся NULL до явной
# публикации владельцем (это и проверяют тесты фичи публикации).
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
from sqlalchemy import event as _sa_event  # noqa: E402
from app.models.models import Salon as _Salon, SalonModerationStatus as _SMS  # noqa: E402


@_sa_event.listens_for(_Salon, "before_insert")
def _grandfather_published_at(_mapper, _connection, target):
    if getattr(target, "published_at", None) is None and target.moderation_status == _SMS.APPROVED:
        target.published_at = _dt.now(_tz.utc)


# ── Сессионная подготовка: тестовая БД + миграции ────────────────────────────
def _pg_dsn(db: str) -> str:
    return (
        f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{db}"
    )


@pytest.fixture(scope="session", autouse=True)
def _database():
    async def prepare():
        conn = await asyncpg.connect(_pg_dsn("postgres"))
        exists = await conn.fetchval(
            "select 1 from pg_database where datname = $1", settings.POSTGRES_DB
        )
        if not exists:
            await conn.execute(f'create database "{settings.POSTGRES_DB}"')
        await conn.close()

    asyncio.run(prepare())
    # Схема — только миграциями: тест заодно ловит дрейф моделей/миграций
    cfg = AlembicConfig(str(pathlib.Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
async def _clean_state():
    """Чистые таблицы, чистый Redis и сброс пулов перед каждым тестом.

    Пул SQLAlchemy и клиент redis создаются на уровне модулей и привязываются
    к event loop'у первого теста; у каждого теста loop свой -> соединения
    надо сбрасывать, иначе "Future attached to a different loop".
    """
    from app.db import session as db_session_mod
    import app.core.limiter as limiter_mod

    await db_session_mod.engine.dispose()
    limiter_mod._redis = None

    conn = await asyncpg.connect(_pg_dsn(settings.POSTGRES_DB))
    tables = await conn.fetch(
        "select tablename from pg_tables "
        "where schemaname='public' and tablename <> 'alembic_version'"
    )
    if tables:
        names = ", ".join(f'"{t["tablename"]}"' for t in tables)
        await conn.execute(f"truncate {names} restart identity cascade")
    await conn.close()

    r = aioredis.from_url(settings.REDIS_URL)
    await r.flushdb()
    await r.aclose()
    yield


# ── HTTP-клиент ──────────────────────────────────────────────────────────────
@pytest.fixture()
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        # Origin нужен CSRF-middleware для cookie-мутаций; для Bearer-API безвреден
        headers={"Origin": "http://testserver"},
    ) as c:
        yield c


# ── Хелперы данных ───────────────────────────────────────────────────────────
@pytest.fixture()
def db_session():
    """Фабрика асинхронных сессий для прямой подготовки данных в тестах."""
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal


async def register_user(client: httpx.AsyncClient, phone: str, password: str = "Testpass1",
                        full_name: str = "Тест Тестов") -> dict:
    """Полный путь регистрации: send-code -> register (mock: код в dev_code)."""
    r = await client.post("/api/v1/auth/register/send-code", json={"phone": phone})
    assert r.status_code == 200, r.text
    data = r.json()
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "phone": phone,
            "full_name": full_name,
            "password": password,
            "request_id": data["request_id"],
            "code": data["dev_code"],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()
