# tests/test_catalog_badges.py
"""Метки и порядок в каталоге: победители конкурса и платный приоритет.

Подъём без метки — скрытая реклама: клиент думает, что видит лучших по
качеству, а видит оплаченных. И наоборот: если человек сам выбрал сортировку
«по рейтингу», подменять её подъёмом нельзя (docs/decisions/0006).
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.models.models import Salon, SalonModerationStatus

_WORK = json.dumps({d: "10:00-20:00" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


async def _salon(db_session, name, *, rating=0.0, tier=None, winner_days=None,
                 phone="+70000000000") -> int:
    now = datetime.now(timezone.utc)
    async with db_session() as db:
        salon = Salon(
            name=name, address="Томск, Ленина 1", city="Томск", phone=phone,
            latitude=56.48, longitude=84.95, working_hours=_WORK,
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            published_at=now - timedelta(days=30), access_until=now + timedelta(days=30),
            rating=rating, reviews_count=10, business_tier=tier,
            contest_winner_until=(now + timedelta(days=winner_days)) if winner_days else None,
        )
        db.add(salon)
        await db.commit()
        return salon.id


def _order(html: str, names: list[str]) -> list[str]:
    """Порядок карточек в выдаче."""
    found = [(html.index(name), name) for name in names if name in html]
    return [name for _, name in sorted(found)]


async def _catalog(client, query: str = "") -> str:
    r = await client.get(f"/salons{query}")
    assert r.status_code == 200
    return r.text


async def test_winner_and_paid_rise_in_default_order(client, db_session):
    await _salon(db_session, "ЛучшийРейтингZZ", rating=5.0, phone="+70000000001")
    await _salon(db_session, "ПлатныйZZ", rating=1.0, tier="business", phone="+70000000002")
    await _salon(db_session, "ПобедительZZ", rating=0.0, winner_days=90, phone="+70000000003")

    html = await _catalog(client)
    assert _order(html, ["ПобедительZZ", "ПлатныйZZ", "ЛучшийРейтингZZ"]) == [
        "ПобедительZZ", "ПлатныйZZ", "ЛучшийРейтингZZ"]


async def test_explicit_sort_is_not_overridden(client, db_session):
    """Человек выбрал «по рейтингу» — он выбрал правило, подменять нельзя."""
    await _salon(db_session, "ЛучшийРейтингZZ", rating=5.0, phone="+70000000004")
    await _salon(db_session, "ПлатныйZZ", rating=1.0, tier="business", phone="+70000000005")
    await _salon(db_session, "ПобедительZZ", rating=0.0, winner_days=90, phone="+70000000006")

    html = await _catalog(client, "?sort=rating")
    assert _order(html, ["ЛучшийРейтингZZ", "ПлатныйZZ", "ПобедительZZ"])[0] == "ЛучшийРейтингZZ"


async def test_badges_are_shown(client, db_session):
    await _salon(db_session, "ПобедительZZ", winner_days=90, phone="+70000000007")
    await _salon(db_session, "ПлатныйZZ", tier="corporate", phone="+70000000008")

    html = await _catalog(client)
    assert "Победитель конкурса Руми" in html
    assert "Продвигается" in html


async def test_badges_stay_in_explicit_sort(client, db_session):
    """Подъёма нет, но метка остаётся: почему карточка такая — видно всегда."""
    await _salon(db_session, "ПобедительZZ", winner_days=90, phone="+70000000009")
    html = await _catalog(client, "?sort=rating")
    assert "Победитель конкурса Руми" in html


async def test_lite_salon_is_not_marked_as_promoted(client, db_session):
    """«Лайт» приоритета не покупает — метки быть не должно."""
    await _salon(db_session, "ЛайтZZ", tier="lite", phone="+70000000010")
    html = await _catalog(client)
    assert "ЛайтZZ" in html and "Продвигается" not in html


async def test_expired_winner_loses_boost_and_badge(client, db_session):
    """Приз на три месяца, а не навсегда."""
    salon_id = await _salon(db_session, "БывшийПобедительZZ", rating=0.0, phone="+70000000011")
    await _salon(db_session, "ОбычныйZZ", rating=5.0, phone="+70000000012")
    async with db_session() as db:
        await db.execute(update(Salon).where(Salon.id == salon_id).values(
            contest_winner_until=datetime.now(timezone.utc) - timedelta(days=1)))
        await db.commit()

    html = await _catalog(client)
    assert "Победитель конкурса Руми" not in html
    assert _order(html, ["ОбычныйZZ", "БывшийПобедительZZ"])[0] == "ОбычныйZZ"


async def test_admin_marks_and_unmarks_winner(client, db_session):
    """Отметку ставит старший модератор, и она попадает в журнал действий."""
    from sqlalchemy import select

    from app.models.models import AdminAudit, User, UserRole
    from tests.conftest import register_user

    salon_id = await _salon(db_session, "КонкурсантZZ", phone="+70000000013")
    data = await register_user(client, "+79997770301")
    async with db_session() as db:
        await db.execute(update(User).where(User.phone == "+79997770301")
                         .values(role=UserRole.ADMIN, is_senior_admin=True))
        await db.commit()
    client.cookies.set("access_token", data["access_token"])

    r = await client.post(f"/api/v1/admin/salons/{salon_id}/contest-winner", data={"months": "3"})
    assert r.status_code == 302
    async with db_session() as db:
        salon = await db.get(Salon, salon_id)
        assert salon.contest_winner_until > datetime.now(timezone.utc) + timedelta(days=85)
        actions = [a.action for a in (await db.execute(select(AdminAudit))).scalars()]
        assert "contest_winner" in actions

    r = await client.post(f"/api/v1/admin/salons/{salon_id}/contest-winner", data={"months": "0"})
    async with db_session() as db:
        assert (await db.get(Salon, salon_id)).contest_winner_until is None
    client.cookies.clear()
