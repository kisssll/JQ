# app/services/ad_attribution.py
"""Метки рекламы: какие берём из адреса и как сохраняем.

Метки едут по ссылкам (лендинг → регистрация → подключение), а не в cookie:
согласие на cookie для этого не нужно, и учёт не зависит от баннера и
блокировщиков. См. модель AdAttribution.
"""
from __future__ import annotations

from typing import Mapping
from urllib.parse import urlencode

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
KEYS = UTM_KEYS + ("yclid", "landing")
_MAX = {"yclid": 100, "landing": 100}


def pick(params: Mapping[str, str]) -> dict[str, str]:
    """Только известные метки, обрезанные до размера колонки."""
    out = {}
    for key in KEYS:
        value = (params.get(key) or "").strip()
        if value:
            out[key] = value[: _MAX.get(key, 200)]
    return out


def query(params: Mapping[str, str]) -> str:
    """Метки как строка запроса — чтобы передать их следующей ссылке."""
    picked = pick(params)
    return urlencode(picked) if picked else ""


async def record(db, *, user_id: int, salon_id: int, params: Mapping[str, str]) -> bool:
    """Сохранить метки подключения. Нет меток — ничего не пишем (органика).

    Сбой записи не должен ломать подключение: теряем строчку отчёта, а не
    клиента. Поэтому ошибки глотаются с журналом.
    """
    import logging

    from app.models.models import AdAttribution

    picked = pick(params)
    if not picked:
        return False
    try:
        db.add(AdAttribution(user_id=user_id, salon_id=salon_id, **picked))
        await db.commit()
        return True
    except Exception:
        logging.getLogger(__name__).exception("метки рекламы не сохранены: salon=%s", salon_id)
        await db.rollback()
        return False
