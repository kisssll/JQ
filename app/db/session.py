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

    # Без этого — классический сценарий "приложение долго простаивало (мало
    # трафика ночью / у клиента вкладка висела в фоне), managed Postgres или
    # сетевая инфраструктура между сервером и БД тихо обрывает бездействующее
    # TCP-соединение из пула, а следующий запрос падает необработанным
    # исключением на протухшем соединении (500 без единого шанса словить это
    # выше по стеку). pool_pre_ping проверяет соединение лёгким SELECT перед
    # выдачей из пула и прозрачно переподключается, если оно уже мертво.
    # pool_recycle — подстраховка на случай более раннего тайм-аута на
    # стороне БД/провайдера, чем успеет заметить pre_ping.
    pool_pre_ping=True,
    pool_recycle=1800,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session