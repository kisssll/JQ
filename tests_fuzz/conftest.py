"""Оснастка фаззинга (решение 0016, п. 3).

Лежит ОТДЕЛЬНО от tests/: обычный `pytest -q` (гейт выката) этих проверок не
собирает, их гоняет отдельное задание CI. Запуск: `pytest tests_fuzz -p no:randomly`.

Что здесь гарантируется:
  - окружение, БД и Redis те же, что в tests/ (фикстуры берём оттуда, чтобы
    не плодить второй способ поднять схему);
  - ограничитель скорости slowapi выключен — но только внутри этого каталога;
  - наружу фаззинг ходить не умеет: любое соединение не на localhost и любой
    DNS-запрос на чужое имя пишется в журнал, а тест в конце падает. Это дефект
    оснастки (кто-то забыл заглушку), а не находка по приложению.
"""
import socket

import pytest

# Порядок важен: tests.conftest выставляет окружение ДО импорта приложения.
from tests.conftest import (  # noqa: F401  (фикстуры pytest подхватывает по имени)
    _clean_state, _database, client, db_session, register_user,
)

_LOCAL = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "", None}


def _is_local(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    return host in _LOCAL or (isinstance(host, str) and host.startswith("127."))


@pytest.fixture(autouse=True)
def no_outbound(monkeypatch):
    """Журнал попыток выйти наружу; в конце теста должен быть пуст."""
    attempts: list[str] = []
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect

    def guarded_getaddrinfo(host, *a, **kw):
        if not _is_local(host):
            attempts.append(f"DNS {host!r}")
            raise socket.gaierror(socket.EAI_NONAME, "fuzz: внешний DNS запрещён")
        return real_getaddrinfo(host, *a, **kw)

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        # unix-сокеты (строка пути) и локальные адреса — можно; всё прочее — нет
        if isinstance(address, tuple) and not _is_local(host):
            attempts.append(f"CONNECT {address!r}")
            raise OSError("fuzz: внешнее соединение запрещено")
        return real_connect(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield attempts
    assert not attempts, f"дефект оснастки — исходящие обращения во время фаззинга: {attempts}"


@pytest.fixture(autouse=True)
def limiter_off():
    """slowapi задушил бы фаззинг 429-ми. Включаем обратно после теста."""
    from app.core.limiter import limiter

    was = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was


@pytest.fixture()
def run():
    """Синхронный запуск корутин на ОДНОМ event loop'е теста.

    Hypothesis вызывает тело примера синхронно много раз, а пулы SQLAlchemy и
    redis привязываются к loop'у первого запроса — отдельный loop на каждый
    пример их ломал бы. Здесь loop один на весь тест, в конце пул закрывается."""
    import asyncio

    from app.db import session as db_session_mod

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop.run_until_complete
        loop.run_until_complete(db_session_mod.engine.dispose())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def wipe_all_tables():
    """Обнулить ВСЕ таблицы тестовой базы между примерами одного свойства.

    Это не «удаление по шаблону»: чистится целиком изолированная beauty_test
    (то же делает фикстура _clean_state), боевые и dev-базы сюда не попадают."""
    import asyncpg

    from app.core.config import settings
    from tests.conftest import _pg_dsn

    assert settings.POSTGRES_DB == "beauty_test", "фаззинг только на тестовой базе"
    conn = await asyncpg.connect(_pg_dsn(settings.POSTGRES_DB))
    try:
        tables = await conn.fetch(
            "select tablename from pg_tables "
            "where schemaname='public' and tablename <> 'alembic_version'"
        )
        if tables:
            names = ", ".join(f'"{t["tablename"]}"' for t in tables)
            await conn.execute(f"truncate {names} restart identity cascade")
    finally:
        await conn.close()
