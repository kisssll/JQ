# app/services/cabinet_badge.py
"""Бейдж подписки в левой карточке кабинета (решение 0015, п. 3).

Платный тариф в сервисе бывает у двоих: у салона (его видит владелец) и у
модели. У клиента платного тарифа НЕТ — бейджа у него нет, и выдумывать его
нельзя: подпись «Про» у человека, который ничего не покупал, — ложное
обещание. По той же причине на просроченном тарифе пишем, что он кончился,
а не название тарифа: доступа по нему уже нет (каталог и запись спрашивают
access_until, см. app/services/subscription.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Salon, SalonMember, SalonRole, SalonSubscriptionStatus
from app.services.subscription import _aware, _now
from app.services.tariffs import MODEL_TARIFF_CATALOG, TARIFF_CATALOG

# Дальше этого срока доступ — не оплаченный период: месячные тарифы так далеко
# не продлеваются даже пачкой.
_OPEN_ENDED = timedelta(days=3 * 365)


def badge_text(who: str, status, plan_name: str, access_until: Optional[datetime],
               now: Optional[datetime] = None) -> str:
    """Подпись бейджа для одного тарифа; пусто — тарифа нет вовсе.

    ``who`` — чей тариф («Салон», «Модель»): у владельца-модели их два, и без
    этого не понять, какой из них кончился."""
    now = now or _now()
    until = _aware(access_until)
    if status == SalonSubscriptionStatus.NONE and until is None:
        return ""
    if until is None or until <= now:
        return f"{who} · тариф закончился"
    if until - now > _OPEN_ENDED:
        # Бессрочный доступ без оплаты (старые салоны, ручная выдача админом):
        # дата «до 2099 года» выглядела бы опечаткой, а название тарифа —
        # обещанием, что за него платят.
        return f"{who} · доступ открыт"
    date = until.strftime("%d.%m.%Y")
    if status == SalonSubscriptionStatus.TRIALING:
        return f"{who} · пробный до {date}"
    if status == SalonSubscriptionStatus.PAST_DUE:
        # Доступ ещё открыт (грейс), но платёж не прошёл — об этом и речь,
        # а не о названии тарифа. Дата в узкой карточке уже не помещается.
        return f"{who} · платёж не прошёл"
    name = plan_name or "тариф"
    return f"{who} · {name} до {date}"


async def load_badges(db: AsyncSession, user) -> list[str]:
    """Все бейджи человека: тариф салона, которым он владеет, и тариф модели."""
    if user is None:
        return []
    badges: list[str] = []

    salon = (await db.execute(
        select(Salon)
        .join(SalonMember, SalonMember.salon_id == Salon.id)
        .where(
            SalonMember.user_id == user.id,
            SalonMember.role == SalonRole.OWNER,
            SalonMember.is_active == True,  # noqa: E712
        )
        # Тот же порядок, что у get_user_primary_salon_id: свой созданный
        # салон раньше салона, куда позвали совладельцем.
        .order_by(SalonMember.is_creator.desc(), SalonMember.created_at.asc())
        .limit(1)
    )).scalar_one_or_none()
    if salon is not None:
        tariff = TARIFF_CATALOG.get(salon.business_tier or "")
        text = badge_text("Салон", salon.subscription_status,
                          tariff.name if tariff else "", salon.access_until)
        if text:
            badges.append(text)

    if getattr(user, "is_model", False):
        tier = getattr(user, "subscription_tier", None)
        tariff = MODEL_TARIFF_CATALOG.get(tier.value if tier else "")
        text = badge_text("Модель", user.subscription_status,
                          tariff.name if tariff else "", user.access_until)
        if text:
            badges.append(text)
    return badges
