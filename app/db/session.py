# app/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator
from app.core.config import settings

# TLS к БД: при заданном POSTGRES_SSLMODE прокидываем его в asyncpg (шифрование
# трафика к managed-БД по публичному интернету). Пусто → без SSL (локалка/тесты).
_connect_args = {"ssl": settings.POSTGRES_SSLMODE} if settings.POSTGRES_SSLMODE else {}

engine = create_async_engine(
    settings.DATABASE_URL,

    echo=settings.SQL_ECHO,  # в проде False: иначе SQL с параметрами утекает в логи
    future=True,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session