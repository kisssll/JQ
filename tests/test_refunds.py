"""Возврат денег должен забирать оплаченный период.

Найдено вживую на стейдже: клиент возвращал платёж из приложения банка, а
доступ в нашей системе оставался до прежней даты. Причин было две — статусы
REFUNDED/REVERSED/PARTIAL_REFUNDED не обрабатывались вообще, и защита от
повторных уведомлений глушила их ещё раньше (платёж-то уже SUCCEEDED).
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.models import (
    Payment, PaymentKind, PaymentStatus, Salon, SalonModerationStatus,
    SalonSubscriptionStatus, User, UserRole,
)
from app.services.subscription import has_access, revoke_paid_period
from app.services.tkassa import _sign


def _target(days_left=30, **kw):
    now = datetime.now(timezone.utc)
    base = dict(
        subscription_expires_at=now + timedelta(days=days_left),
        access_until=now + timedelta(days=days_left),
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── Правило отката ───────────────────────────────────────────────────────────

def test_full_refund_of_one_month_closes_access():
    target = _target(days_left=30)
    until = revoke_paid_period(target, months=1)
    assert until <= datetime.now(timezone.utc) + timedelta(seconds=1)
    assert not has_access(target)
    assert target.access_until == target.subscription_expires_at


def test_refund_takes_back_exactly_the_paid_term():
    """Предоплата на 3 месяца поверх ещё живого месяца: возврат забирает
    только свои 90 дней, ранее оплаченный срок остаётся."""
    target = _target(days_left=120)
    until = revoke_paid_period(target, months=3)
    left = (until - datetime.now(timezone.utc)).days
    assert 29 <= left <= 30
    assert has_access(target)


def test_partial_refund_takes_back_proportional_share():
    target = _target(days_left=30)
    until = revoke_paid_period(target, months=1, share=0.5)
    left = (until - datetime.now(timezone.utc)).days
    assert 14 <= left <= 15


def test_revocation_never_goes_below_now():
    """Возврат старого платежа, срок которого и так почти истёк, не должен
    загонять дату в прошлое — иначе «доступ до» показывал бы прошлый год."""
    target = _target(days_left=1)
    until = revoke_paid_period(target, months=12)
    assert until >= datetime.now(timezone.utc) - timedelta(seconds=1)


# ── Вебхук ───────────────────────────────────────────────────────────────────

def _signed(payload: dict) -> dict:
    fields = {
        "TerminalKey": str(payload.get("TerminalKey", "")),
        "OrderId": str(payload.get("OrderId", "")),
        "Success": "true" if payload.get("Success") else "false",
        "Status": str(payload.get("Status", "")),
        "PaymentId": str(payload.get("PaymentId", "")),
        "ErrorCode": str(payload.get("ErrorCode", "")),
        "Amount": str(payload.get("Amount", "")),
        "Pan": str(payload.get("Pan", "")),
        "ExpDate": str(payload.get("ExpDate", "")),
    }
    return {**payload, "Token": _sign(fields, settings.TKASSA_PASSWORD)}


@pytest.fixture()
def tkassa_creds(monkeypatch):
    monkeypatch.setattr(settings, "TKASSA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TKASSA_PASSWORD", "test-password", raising=False)
    monkeypatch.setattr(settings, "TKASSA_TERMINAL_KEY", "TEST-TERMINAL", raising=False)
    return settings


_phone_seq = iter(range(1000, 9999))


async def _salon_with_paid_month(db):
    n = next(_phone_seq)
    owner = User(
        phone=f"+7999000{n}", full_name="Владелец",
        hashed_password=get_password_hash("Testpass1"),
        role=UserRole.BUSINESS, is_active=True,
    )
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    now = datetime.now(timezone.utc)
    salon = Salon(
        name=f"Возвратный-{n}", address="Т", phone="+70000000800",
        latitude=1.0, longitude=1.0, city="Томск", is_active=True,
        creator_id=owner.id,
        moderation_status=SalonModerationStatus.APPROVED,
        business_tier="lite",
        subscription_status=SalonSubscriptionStatus.ACTIVE,
        auto_renew=True, recurring_token="rebill-123",
    )
    db.add(salon)
    await db.commit()
    await db.refresh(salon)
    # листенер conftest грандфазерит access_until одобренным салонам — ставим свой
    salon.subscription_expires_at = now + timedelta(days=30)
    salon.access_until = now + timedelta(days=30)

    payment = Payment(
        salon_id=salon.id, plan="lite", kind=PaymentKind.RECURRENT,
        amount=1250.0, months=1, invoice_id=f"order-refund-{n}",
        provider_transaction_id=f"pay-{n}", status=PaymentStatus.SUCCEEDED,
        paid_at=now,
    )
    db.add(payment)
    await db.commit()
    return salon, payment


async def test_webhook_refund_revokes_access(client, db_session, tkassa_creds):
    async with db_session() as db:
        salon, payment = await _salon_with_paid_month(db)
        salon_id, order_id = salon.id, payment.invoice_id
        pay_id = payment.provider_transaction_id

    resp = await client.post("/api/v1/payments/tkassa/notify", json=_signed({
        "TerminalKey": settings.TKASSA_TERMINAL_KEY, "OrderId": order_id,
        "Success": True, "Status": "REFUNDED", "PaymentId": pay_id,
        "Amount": 125000,
    }))
    assert resp.status_code == 200

    async with db_session() as db:
        salon = await db.get(Salon, salon_id)
        payment = (await db.execute(
            select(Payment).where(Payment.invoice_id == order_id)
        )).scalar_one()
        assert payment.status == PaymentStatus.REFUNDED
        assert not has_access(salon)
        assert salon.subscription_status == SalonSubscriptionStatus.CANCELED
        # Деньги вернули — списывать повторно в следующем месяце нельзя
        assert salon.auto_renew is False
        assert salon.recurring_token is None


async def test_webhook_partial_refund_shortens_period(client, db_session, tkassa_creds):
    async with db_session() as db:
        salon, payment = await _salon_with_paid_month(db)
        salon_id, order_id = salon.id, payment.invoice_id
        pay_id = payment.provider_transaction_id

    resp = await client.post("/api/v1/payments/tkassa/notify", json=_signed({
        "TerminalKey": settings.TKASSA_TERMINAL_KEY, "OrderId": order_id,
        "Success": True, "Status": "PARTIAL_REFUNDED", "PaymentId": pay_id,
        "Amount": 62500,  # половина от 1250 ₽
    }))
    assert resp.status_code == 200

    async with db_session() as db:
        salon = await db.get(Salon, salon_id)
        left = (salon.access_until - datetime.now(timezone.utc)).days
        assert 14 <= left <= 15
        assert has_access(salon)          # доступ остаётся, но короче
        assert salon.auto_renew is True   # частичный возврат подписку не рвёт


async def test_repeated_refund_notification_is_idempotent(client, db_session, tkassa_creds):
    async with db_session() as db:
        salon, payment = await _salon_with_paid_month(db)
        salon_id, order_id = salon.id, payment.invoice_id
        pay_id = payment.provider_transaction_id

    body = _signed({
        "TerminalKey": settings.TKASSA_TERMINAL_KEY, "OrderId": order_id,
        "Success": True, "Status": "REFUNDED", "PaymentId": pay_id,
        "Amount": 125000,
    })
    assert (await client.post("/api/v1/payments/tkassa/notify", json=body)).status_code == 200
    async with db_session() as db:
        first = (await db.get(Salon, salon_id)).access_until

    assert (await client.post("/api/v1/payments/tkassa/notify", json=body)).status_code == 200
    async with db_session() as db:
        # Повтор не должен вычитать срок второй раз
        assert (await db.get(Salon, salon_id)).access_until == first


async def test_repeated_confirmation_still_ignored(client, db_session, tkassa_creds):
    """Защиту от дублей мы сузили — проверяем, что она не сломалась."""
    async with db_session() as db:
        salon, payment = await _salon_with_paid_month(db)
        salon_id, order_id = salon.id, payment.invoice_id
        pay_id = payment.provider_transaction_id
        before = salon.access_until

    assert (await client.post("/api/v1/payments/tkassa/notify", json=_signed({
        "TerminalKey": settings.TKASSA_TERMINAL_KEY, "OrderId": order_id,
        "Success": True, "Status": "CONFIRMED", "PaymentId": pay_id,
        "Amount": 125000,
    }))).status_code == 200
    async with db_session() as db:
        assert (await db.get(Salon, salon_id)).access_until == before


def test_refund_does_not_touch_access_granted_outside_payments():
    """Бессрочный доступ (grandfather) и ручная выдача админом живут на
    access_until без subscription_expires_at — возврат их не отбирает."""
    forever = datetime(2099, 1, 1, tzinfo=timezone.utc)
    target = SimpleNamespace(subscription_expires_at=None, access_until=forever)
    assert revoke_paid_period(target, months=1) == forever
    assert target.access_until == forever
