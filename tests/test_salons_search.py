"""Серверные фильтры/поиск на /salons (бэкенд-этап).

Проверяем: гибрид-резолвинг категории услуги, разбор query-параметров и сам
эндпоинт — фильтр по категории/городу/рейтингу, полнотекст по названиям услуг
и устойчивость к опечаткам (trigram, если расширение доступно в тест-БД).
"""
import itertools

from starlette.datastructures import QueryParams

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonModerationStatus, Master, Service,
)
from app.web.service_categories import suggest_category
from app.api.v1.endpoints.services import _resolve_category
from app.web.pages.salons import parse_salon_query, SalonQuery


_phone_seq = itertools.count(1)


def _phone() -> str:
    return f"+7999{next(_phone_seq):07d}"


async def _mk_published_salon(db_session, name, *, city="Томск", rating=5.0,
                              reviews=10, service_name="Женская стрижка",
                              category="__auto__"):
    """Опубликованный салон (moderation=APPROVED → grandfather-листенер conftest
    проставляет published_at на INSERT) с одним мастером и одной услугой."""
    async with db_session() as db:
        owner = User(phone=_phone(), full_name="Вл",
                     hashed_password=get_password_hash("Bizpass1"),
                     role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        s = Salon(name=name, description="", address="Томск, ул. 1",
                  latitude=56.5, longitude=84.9, phone=_phone(), city=city,
                  rating=rating, reviews_count=reviews, is_active=True,
                  moderation_status=SalonModerationStatus.APPROVED, creator_id=owner.id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        assert s.published_at is not None  # grandfather сработал

        m = Master(user_id=owner.id, salon_id=s.id, specialization="Парикмахер", is_active=True)
        db.add(m)
        await db.commit()
        await db.refresh(m)

        cat = suggest_category(service_name) if category == "__auto__" else category
        db.add(Service(master_id=m.id, name=service_name, price=1000,
                       duration_minutes=30, category=cat, is_active=True))
        await db.commit()
        return s.id


# ── Гибрид-резолвинг категории ───────────────────────────────────────────────

def test_resolve_category_explicit_wins():
    # Владелец явно выбрал массаж, хотя название про стрижку — уважаем выбор.
    assert _resolve_category("massazh", "Мужская стрижка") == "massazh"


def test_resolve_category_matcher_fallback():
    # Пусто → матчер по названию.
    assert _resolve_category("", "Женская стрижка") == "strizhki"
    assert _resolve_category("   ", "Маникюр с покрытием") == "manikur"


def test_resolve_category_invalid_falls_back_to_matcher():
    # Мусорный слаг игнорируем, идём в матчер.
    assert _resolve_category("not-a-slug", "Окрашивание волос") == "okrashivanie"


def test_resolve_category_no_match_is_none():
    assert _resolve_category("", "Консультация") is None


# ── Разбор query-параметров ──────────────────────────────────────────────────

def _pq(qs: str):
    class R:
        query_params = QueryParams(qs)
    return parse_salon_query(R())


def test_parse_query_basics():
    p = _pq("q=%20стрижка%20&city=Томск&category=strizhki&category=manikur&min_rating=4.5&promo=1&sort=reviews")
    assert p.q == "стрижка"
    assert p.city == "Томск"
    assert p.categories == ["strizhki", "manikur"]
    assert p.min_rating == 4.5
    assert p.promo_only is True
    assert p.sort == "reviews"


def test_parse_query_drops_bad_values():
    p = _pq("category=bogus&sort=weird&min_rating=abc&limit=5")
    assert p.categories == []          # невалидный слаг отброшен
    assert p.sort == ""                # невалидная сортировка сброшена
    assert p.min_rating == 0.0         # нечисло → 0
    assert p.limit >= 20               # limit не опускается ниже страницы


# ── Эндпоинт /salons ─────────────────────────────────────────────────────────

async def test_search_matches_service_name(client, db_session):
    await _mk_published_salon(db_session, "СтрижкиТут", service_name="Женская стрижка")
    assert "СтрижкиТут" in (await client.get("/salons?q=стрижка")).text
    assert "СтрижкиТут" not in (await client.get("/salons?q=маникюр")).text


async def test_category_filter(client, db_session):
    await _mk_published_salon(db_session, "ТолькоСтрижки", service_name="Женская стрижка")
    assert "ТолькоСтрижки" in (await client.get("/salons?category=strizhki")).text
    assert "ТолькоСтрижки" not in (await client.get("/salons?category=massazh")).text


async def test_city_filter(client, db_session):
    await _mk_published_salon(db_session, "ТомскСалон", city="Томск")
    await _mk_published_salon(db_session, "НовосибСалон", city="Новосибирск")
    html = (await client.get("/salons?city=Томск")).text
    assert "ТомскСалон" in html and "НовосибСалон" not in html


async def test_min_rating_filter(client, db_session):
    await _mk_published_salon(db_session, "Высокий", rating=4.8)
    await _mk_published_salon(db_session, "Низкий", rating=3.0)
    html = (await client.get("/salons?min_rating=4.5")).text
    assert "Высокий" in html and "Низкий" not in html


async def test_partial_returns_grid_only(client, db_session):
    await _mk_published_salon(db_session, "ФрагментСалон")
    r = await client.get("/salons?partial=1")
    assert "ФрагментСалон" in r.text
    assert "<html" not in r.text  # только сетка, без обёртки страницы


async def test_typo_tolerance_trigram(client, db_session):
    """Опечатка ловится триграмом. Если pg_trgm в тест-БД недоступен —
    деградация в FTS-only, тогда тест не применим (пропускаем)."""
    from app.web.pages.salons import _trgm_available
    async with db_session() as db:
        has_trgm = await _trgm_available(db)
    if not has_trgm:
        import pytest
        pytest.skip("pg_trgm недоступен — FTS-only, опечатки не ловятся")
    await _mk_published_salon(db_session, "ОпечаткаТест", service_name="Женская стрижка")
    assert "ОпечаткаТест" in (await client.get("/salons?q=стижка")).text
