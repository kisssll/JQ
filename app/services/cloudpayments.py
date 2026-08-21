# app/services/cloudpayments.py
"""Интеграция с CloudPayments (касса для оплаты бизнес-подписок).

Два независимых направления:
1. Проверка подлинности HTTP-уведомлений (вебхуков), которые CloudPayments
   шлёт нам на /api/v1/payments/cloudpayments/* — verify_signature().
2. Серверные вызовы REST API CloudPayments (создать подписку на рекуррентные
   платежи, вернуть верификационный платёж, отменить подписку) — CloudPaymentsClient.

Аутентификация REST API — HTTP Basic: Public ID как логин, Api Secret как
пароль (см. https://developers.cloudpayments.ru/, раздел Аутентификация).
Ответ — {"Success": bool, "Message": str|null, "Model": {...}}.

Подпись уведомлений — заголовок Content-HMAC: HMAC-SHA256(сырое тело
запроса, ключ = Api Secret), результат в base64 (см. документацию,
раздел «Проверка подлинности уведомлений»).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloudpayments.ru"


class CloudPaymentsError(Exception):
    """Сбой запроса к CloudPayments (сеть, неожиданный ответ, Success=false)."""


def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """True, если Content-HMAC из запроса совпадает с посчитанным по телу.

    Сравнение — hmac.compare_digest (защита от timing-атак). Без заголовка
    или без настроенного секрета подпись всегда считается неверной — вызывающий
    код обязан явно проверить settings.CLOUDPAYMENTS_ENABLED заранее.
    """
    if not signature_header or not settings.CLOUDPAYMENTS_API_SECRET:
        return False
    digest = hmac.new(
        settings.CLOUDPAYMENTS_API_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature_header)


@dataclass
class SubscriptionResult:
    id: str
    status: str
    amount: Decimal
    next_transaction_date: Optional[datetime]


class CloudPaymentsClient:
    """Тонкая обёртка над REST API. Один клиент — один запрос (httpx.AsyncClient
    открывается на вызов, как в geocoding_service.py — эти вызовы не на
    горячем пути запроса пользователя, отдельный пул незачем)."""

    def __init__(self) -> None:
        if not (settings.CLOUDPAYMENTS_PUBLIC_ID and settings.CLOUDPAYMENTS_API_SECRET):
            raise CloudPaymentsError(
                "CLOUDPAYMENTS_PUBLIC_ID/CLOUDPAYMENTS_API_SECRET не заданы"
            )
        self._auth = (settings.CLOUDPAYMENTS_PUBLIC_ID, settings.CLOUDPAYMENTS_API_SECRET)

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15, auth=self._auth) as client:
                response = await client.post(f"{API_BASE}{path}", json=payload)
        except httpx.HTTPError as exc:
            raise CloudPaymentsError(f"Сеть/таймаут при обращении к CloudPayments {path}: {exc}") from exc

        if response.status_code != 200:
            raise CloudPaymentsError(
                f"CloudPayments {path} вернул {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        if not data.get("Success"):
            raise CloudPaymentsError(
                f"CloudPayments {path}: Success=false, Message={data.get('Message')!r}"
            )
        return data.get("Model") or {}

    async def refund(self, transaction_id: str, amount: Decimal) -> None:
        """Возврат платежа (используем для верификационного 1₽-списания —
        оно нужно только чтобы получить Token карты, клиент его не должен
        видеть как реальный расход)."""
        await self._post("/payments/refund", {
            "TransactionId": transaction_id,
            "Amount": float(amount),
        })

    async def create_subscription(
        self, *, token: str, account_id: str, description: str,
        amount: Decimal, email: str = "", start_date: datetime,
        interval: str = "Month", period: int = 1,
    ) -> SubscriptionResult:
        """Оформляет регулярное списание по токену карты, полученному из
        успешного платежа. start_date — момент первого СПИСАНИЯ по подписке
        (используем конец пробного периода, чтобы триал был реально бесплатным)."""
        model = await self._post("/subscriptions/create", {
            "Token": token,
            "AccountId": account_id,
            "Description": description,
            "Email": email,
            "Amount": float(amount),
            "Currency": "RUB",
            "RequireConfirmation": False,
            "StartDate": start_date.isoformat(),
            "Interval": interval,
            "Period": period,
        })
        return SubscriptionResult(
            id=model["Id"],
            status=model.get("Status", ""),
            amount=Decimal(str(model.get("Amount", amount))),
            next_transaction_date=None,
        )

    async def cancel_subscription(self, subscription_id: str) -> None:
        await self._post("/subscriptions/cancel", {"Id": subscription_id})
