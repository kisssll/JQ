# app/services/consent_service.py
"""Запись факта согласия в журнал.

Пункт 8 Согласия считает моментом согласия проставление отметки в форме,
поэтому фиксируем именно этот факт: документ, редакцию, время, адрес и то,
с какой формы пришло. Ошибка записи не должна ломать регистрацию или запись
к мастеру — журнал ведётся рядом с основным действием, а не вместо него.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ConsentDocument, UserConsent

logger = logging.getLogger(__name__)

_UA_LIMIT = 512


def _client_ip(request) -> str | None:
    """IP с учётом того, что приложение стоит за Caddy."""
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    client = getattr(request, "client", None)
    return client.host[:64] if client and client.host else None


async def record_consents(
    db: AsyncSession,
    *,
    documents,
    version: str,
    source: str,
    user_id: int | None = None,
    phone: str | None = None,
    request=None,
) -> None:
    """Пишет сразу несколько согласий одним коммитом.

    Именно одним: каждый commit сбрасывает состояние объектов сессии, и если
    коммитить в цикле, следующее обращение к user.id уходит в ленивую подгрузку
    внутри async-контекста и падает с MissingGreenlet. Поэтому вызывающий код
    обязан передавать уже прочитанные user_id и phone, а не ORM-объект.
    """
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") if request else "") or ""
    try:
        for document in documents:
            db.add(UserConsent(
                user_id=user_id,
                phone=(phone or None) and phone[:32],
                document=document,
                version=(version or "unknown")[:32],
                source=source[:64],
                ip=ip,
                user_agent=ua[:_UA_LIMIT] or None,
            ))
        await db.commit()
    except Exception:
        # Согласие человек уже дал — терять из-за этого регистрацию нельзя.
        logger.exception("Не удалось записать согласие (%s, %s)", list(documents), source)
        await db.rollback()


async def record_consent(
    db: AsyncSession,
    *,
    document: ConsentDocument,
    version: str,
    source: str,
    user_id: int | None = None,
    phone: str | None = None,
    request=None,
) -> None:
    """Один документ — частный случай record_consents."""
    await record_consents(
        db, documents=(document,), version=version, source=source,
        user_id=user_id, phone=phone, request=request,
    )
