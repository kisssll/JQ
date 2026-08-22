# app/services/subscription_service.py
"""Единая точка правды про доступ салона по тарифу — используется и баннером
в бизнес-панели (app/web/pages/business/dashboard.py), и эндпоинтом
скрытия/показа салона (app/api/v1/endpoints/business.py), и фоновой задачей
expire_unpaid_salons (app/tasks.py), чтобы условие не разъезжалось по местам.
"""
from datetime import datetime, timezone

from app.models.models import Salon


def is_billing_active(salon: Salon) -> bool:
    """Доступ по тарифу открыт, пока не истёк subscription_expires_at — единая
    граница для триала/активной подписки/PAST_DUE-грейс-периода (см. докстринг
    Salon.subscription_status в app/models/models.py)."""
    return bool(salon.subscription_expires_at and salon.subscription_expires_at > datetime.now(timezone.utc))
