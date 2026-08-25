# app/services/tkassa.py
"""Интеграция с Т-Кассой (Т-Бизнес/Тинькофф Эквайринг) — касса для оплаты
бизнес-подписок.

Base URL: https://securepay.tinkoff.ru/v2/{Method}
Аутентификация — не HTTP-заголовок, а подпись Token В КАЖДОМ запросе:
SHA-256(конкатенация значений полей, отсортированных по ключу), где среди
полей — TerminalKey и Password (пароль терминала). Набор полей для подписи
СВОЙ для каждого метода (описан в GetValuesForToken() у каждого запроса ниже)
и НЕ совпадает с набором полей, реально отправляемых в теле запроса —
опциональные незаполненные поля в тело не идут, но участвуют в подписи как
пустая строка. Алгоритм и точные наборы полей сверены с рабочим клиентом
github.com/nikita-vanyasin/tinkoff (Go), а не восстановлены по памяти.

Суммы у Т-Кассы — в КОПЕЙКАХ (целое число), не в рублях.

У Т-Кассы нет объекта «подписка»: одноразовая привязка карты (Init с
Recurrent=Y) даёт RebillId, а каждое следующее списание — это Init (новый
OrderId/Amount) + Charge(PaymentId, RebillId), инициированные НАМИ по своему
расписанию (см. app.tasks.charge_due_subscriptions). Метод Charge по
умолчанию заблокирован — доступен только после обращения в поддержку
Т-Кассы и прохождения чек-листа по регулярным платежам (это не про код,
чисто организационный шаг на её стороне).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import ssl
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

import certifi
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://securepay.tinkoff.ru/v2"

# securepay.tinkoff.ru (T-Bank) отдаёт TLS-сертификат, выпущенный нацУЦ Минцифры
# (Russian Trusted Root CA), которого нет в certifi-бандле httpx → без этого
# любой запрос падает с "self-signed certificate in certificate chain". Доверяем
# стандартным CA + российскому корню ТОЛЬКО в этом клиенте (не глобально —
# чтобы не расширять поверхность доверия остального приложения).
_RU_CA = Path(__file__).resolve().parent.parent / "certs" / "russian_trusted_ca.crt"


def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    if _RU_CA.exists():
        ctx.load_verify_locations(cafile=str(_RU_CA))
    else:  # pragma: no cover
        logger.warning("Russian Trusted CA не найден (%s) — запрос к Т-Кассе, вероятно, упадёт по TLS", _RU_CA)
    return ctx


_SSL_CTX = _build_ssl_context()


class TKassaError(Exception):
    """Сбой запроса к Т-Кассе (сеть, неожиданный ответ, Success=false)."""


def rubles_to_kopecks(amount: Decimal) -> int:
    """Рубли → копейки. Округляем ПОСЛЕ перевода: прежний вариант квантовал до
    целых рублей до умножения, из-за чего доплата за мастеров 137,50 ₽
    списывалась как 138 ₽ (в базе при этом оставалось 137,50). С чеками это
    ещё и ломает Init — сумма позиций обязана сходиться с суммой платежа."""
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sign(fields: dict, password: str) -> str:
    payload = {**fields, "Password": password}
    parts = [str(payload[k]) for k in sorted(payload.keys())]
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def verify_notification(payload: dict) -> bool:
    """Проверка Token уведомления. Поле-набор для подписи взят из
    Notification.GetValuesForToken() эталонного клиента: TerminalKey, OrderId,
    Success, Status, PaymentId, ErrorCode, Amount, Pan, ExpDate всегда, плюс
    CardId/RebillId/DATA — только если непусты/ненулевые."""
    token = payload.get("Token")
    if not token or not settings.TKASSA_PASSWORD:
        return False
    fields = {
        "TerminalKey": str(payload.get("TerminalKey", "")),
        "OrderId": str(payload.get("OrderId", "")),
        "Success": "true" if payload.get("Success") in (True, "true", "True") else "false",
        "Status": str(payload.get("Status", "")),
        "PaymentId": str(payload.get("PaymentId", "")),
        "ErrorCode": str(payload.get("ErrorCode", "")),
        "Amount": str(payload.get("Amount", "")),
        "Pan": str(payload.get("Pan", "")),
        "ExpDate": str(payload.get("ExpDate", "")),
    }
    card_id = payload.get("CardId")
    if card_id:
        fields["CardId"] = str(card_id)
    rebill_id = payload.get("RebillId")
    if rebill_id:
        fields["RebillId"] = str(rebill_id)
    data = payload.get("DATA")
    if data:
        fields["DATA"] = str(data)
    expected = _sign(fields, settings.TKASSA_PASSWORD)
    return hmac.compare_digest(expected, str(token))


@dataclass
class InitResult:
    payment_id: str
    payment_url: str
    status: str


@dataclass
class ChargeResult:
    payment_id: str
    status: str


class TKassaClient:
    def __init__(self) -> None:
        if not (settings.TKASSA_TERMINAL_KEY and settings.TKASSA_PASSWORD):
            raise TKassaError("TKASSA_TERMINAL_KEY/TKASSA_PASSWORD не заданы")
        self._terminal_key = settings.TKASSA_TERMINAL_KEY
        self._password = settings.TKASSA_PASSWORD

    async def _call(self, method: str, sign_fields: dict, body_fields: dict) -> dict:
        sign_fields = {**sign_fields, "TerminalKey": self._terminal_key}
        body = {
            "TerminalKey": self._terminal_key,
            "Token": _sign(sign_fields, self._password),
            **{k: v for k, v in body_fields.items() if v not in (None, "")},
        }
        try:
            async with httpx.AsyncClient(timeout=15, verify=_SSL_CTX) as client:
                response = await client.post(f"{API_BASE}/{method}", json=body)
        except httpx.HTTPError as exc:
            raise TKassaError(f"Сеть/таймаут при обращении к Т-Кассе {method}: {exc}") from exc

        if response.status_code != 200:
            raise TKassaError(f"Т-Касса {method} вернул {response.status_code}: {response.text[:300]}")
        data = response.json()
        if not data.get("Success"):
            raise TKassaError(
                f"Т-Касса {method}: код {data.get('ErrorCode')} — "
                f"{data.get('Message')} ({data.get('Details')})"
            )
        return data

    async def init(
        self, *, order_id: str, amount_rub: Decimal, description: str,
        notification_url: str, success_url: str, fail_url: str,
        recurrent: bool = False, customer_key: Optional[str] = None,
        client_ip: Optional[str] = None, receipt: Optional[dict] = None,
    ) -> InitResult:
        """Создаёт платёж и возвращает ссылку на страницу оплаты (PaymentURL) —
        клиента достаточно туда перенаправить, без всякого JS-виджета.
        recurrent=True + customer_key — регистрирует карту для будущих
        списаний (первый платёж «родитель», RebillId придёт в уведомлении).
        receipt — блок фискализации (см. app/services/receipts.py); в подпись
        Token он не входит, там участвуют только скалярные поля верхнего
        уровня."""
        amount_kop = rubles_to_kopecks(amount_rub)
        sign_fields = {
            "OrderId": order_id, "IP": client_ip or "", "Description": description,
            "Language": "", "CustomerKey": customer_key or "", "RedirectDueDate": "",
            "NotificationURL": notification_url, "SuccessURL": success_url, "FailURL": fail_url,
            "Recurrent": "Y" if recurrent else "",
            "Amount": amount_kop,
        }
        body_fields = {
            "OrderId": order_id, "Amount": amount_kop, "Description": description,
            "IP": client_ip, "CustomerKey": customer_key,
            "NotificationURL": notification_url, "SuccessURL": success_url, "FailURL": fail_url,
            "Recurrent": "Y" if recurrent else None,
            "Receipt": receipt,
        }
        data = await self._call("Init", sign_fields, body_fields)
        return InitResult(
            payment_id=data["PaymentId"], payment_url=data.get("PaymentURL", ""),
            status=data.get("Status", ""),
        )

    async def charge(self, *, payment_id: str, rebill_id: str) -> ChargeResult:
        """Плановое автосписание по ранее сохранённому RebillId. payment_id —
        Id платежа из ПРЕДЫДУЩЕГО вызова init() на эту же сумму/период (Т-Касса
        требует свежий Init под каждое списание, Charge сам суммы не берёт)."""
        sign_fields = {"PaymentId": payment_id, "RebillId": rebill_id}
        data = await self._call("Charge", sign_fields, sign_fields)
        return ChargeResult(payment_id=data["PaymentId"], status=data.get("Status", ""))

    async def cancel(self, *, payment_id: str, amount_rub: Optional[Decimal] = None,
                     receipt: Optional[dict] = None) -> None:
        """Отмена неподтверждённого платежа или возврат подтверждённого
        (используем для отмены верификационного 1₽ после привязки карты).
        receipt нужен на фискализированном терминале, чтобы касса пробила
        чек возврата."""
        sign_fields = {"PaymentId": payment_id, "IP": ""}
        body_fields: dict = {"PaymentId": payment_id, "Receipt": receipt}
        if amount_rub is not None:
            kop = rubles_to_kopecks(amount_rub)
            sign_fields["Amount"] = kop
            body_fields["Amount"] = kop
        await self._call("Cancel", sign_fields, body_fields)

    async def get_state(self, *, payment_id: str) -> str:
        sign_fields = {"PaymentId": payment_id, "IP": ""}
        data = await self._call("GetState", sign_fields, {"PaymentId": payment_id})
        return data.get("Status", "")
