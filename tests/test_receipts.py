"""Кассовый чек (54-ФЗ) и уведомление об успешной оплате.

Ключевой инвариант чека: сумма позиций обязана в точности совпадать с суммой
платежа — иначе касса отвергает Init, то есть оплата просто не состоится.
Поэтому проверяем не «в чеке что-то есть», а копейка в копейку.
"""
from decimal import Decimal

import pytest

from app.core.config import settings
from app.services.receipts import subscription_receipt, verification_receipt
from app.services.tkassa import rubles_to_kopecks


def _sum(receipt) -> int:
    return sum(i["Amount"] for i in receipt["Items"])


# ── Копейки ──────────────────────────────────────────────────────────────────

def test_kopecks_keep_fractions():
    """Прежняя версия квантовала до целых рублей ДО умножения на 100, из-за
    чего доплата 137,50 ₽ списывалась как 138 ₽ — и чек бы не сошёлся."""
    assert rubles_to_kopecks(Decimal("137.50")) == 13750
    assert rubles_to_kopecks(Decimal("1387.50")) == 138750
    assert rubles_to_kopecks(Decimal("1250")) == 125000


# ── Состав чека ──────────────────────────────────────────────────────────────

def test_plain_month_is_one_line():
    r = subscription_receipt(
        total_rub=Decimal("1250"), monthly_rub=Decimal("1250"), months=1,
        plan_title="Лайт", email="a@b.ru", phone=None,
    )
    assert len(r["Items"]) == 1
    assert r["Items"][0]["Quantity"] == 1
    assert _sum(r) == 125000


def test_prepay_shows_months_as_quantity():
    r = subscription_receipt(
        total_rub=Decimal("3750"), monthly_rub=Decimal("1250"), months=3,
        plan_title="Лайт", email="a@b.ru", phone=None,
    )
    assert len(r["Items"]) == 1
    assert r["Items"][0]["Quantity"] == 3
    assert r["Items"][0]["Price"] == 125000
    assert _sum(r) == 375000


def test_proration_becomes_its_own_line():
    """1250 тарифа + 137,50 доплаты за найм — человек должен видеть, откуда
    взялась незнакомая сумма."""
    r = subscription_receipt(
        total_rub=Decimal("1387.50"), monthly_rub=Decimal("1250"), months=1,
        plan_title="Лайт", email="a@b.ru", phone=None,
    )
    assert len(r["Items"]) == 2
    assert r["Items"][1]["Amount"] == 13750
    assert "оплата" in r["Items"][1]["Name"].lower()
    assert _sum(r) == 138750


def test_items_always_balance_with_payment():
    for total, monthly, months in [
        ("1250", "1250", 1), ("3887.50", "1250", 3), ("1990", "1990", 1),
        ("14887.50", "1250", 11), ("1000", "1250", 1),  # последний — цена > итога
    ]:
        r = subscription_receipt(
            total_rub=Decimal(total), monthly_rub=Decimal(monthly), months=months,
            plan_title="Лайт", email="a@b.ru", phone=None,
        )
        assert _sum(r) == rubles_to_kopecks(Decimal(total)), (total, monthly, months)


def test_taxation_and_tax_from_settings():
    r = subscription_receipt(
        total_rub=Decimal("1250"), monthly_rub=Decimal("1250"), months=1,
        plan_title="Лайт", email="a@b.ru", phone=None,
    )
    assert r["Taxation"] == settings.RECEIPT_TAXATION
    assert r["Items"][0]["Tax"] == settings.RECEIPT_TAX
    assert r["Items"][0]["PaymentMethod"] == "full_payment"
    assert r["Items"][0]["PaymentObject"] == "service"


# ── Контакты ─────────────────────────────────────────────────────────────────

def test_phone_alone_is_enough():
    """Почты нет ни у одного салона на проде — телефон держит доставку."""
    r = subscription_receipt(
        total_rub=Decimal("1250"), monthly_rub=Decimal("1250"), months=1,
        plan_title="Лайт", email=None, phone="+79990000001",
    )
    assert r["Phone"] == "+79990000001"
    assert "Email" not in r


def test_no_contacts_means_no_receipt():
    assert subscription_receipt(
        total_rub=Decimal("1250"), monthly_rub=Decimal("1250"), months=1,
        plan_title="Лайт", email=None, phone=None,
    ) is None


def test_verification_receipt_is_one_rouble():
    r = verification_receipt(amount_rub=Decimal("1.00"), email=None, phone="+79990000001")
    assert _sum(r) == 100
    assert len(r["Items"]) == 1


def test_long_name_is_trimmed_to_ffd_limit():
    r = subscription_receipt(
        total_rub=Decimal("1250"), monthly_rub=Decimal("1250"), months=1,
        plan_title="Т" * 300, email="a@b.ru", phone=None,
    )
    assert len(r["Items"][0]["Name"]) <= 128


# ── Уведомление об успешной оплате ───────────────────────────────────────────

def test_notice_breaks_down_hire_surcharge():
    """Жалоба «почему 1575, я же на триале» рождалась из непрозрачной суммы."""
    from app.services.payment_notice import build_lines

    lines = build_lines(plan_title="Лайт", monthly=1250, months=1, total=1575)
    assert len(lines) == 2
    assert lines[0][1] == "1 250 ₽"
    assert lines[1][1] == "325 ₽"


def test_notice_kopecks_shown_only_when_present():
    from app.services.payment_notice import _rub

    assert _rub(1250) == "1 250 ₽"
    assert _rub(137.5) == "137,50 ₽"


def test_notice_falls_back_to_single_line():
    """Месячная цена неизвестна — одна честная строка вместо вранья."""
    from app.services.payment_notice import build_lines

    lines = build_lines(plan_title="Бизнес", monthly=0, months=1, total=3500)
    assert lines == [("Тариф «Бизнес»", "3 500 ₽")]


# ── Чек доходит до кассы ─────────────────────────────────────────────────────

class _CapturingKassa:
    """Ловит то, что ушло бы в Т-Кассу."""

    def __init__(self):
        self.init_kwargs = None

    async def init(self, **kw):
        from app.services.tkassa import InitResult
        self.init_kwargs = kw
        return InitResult(payment_id="pay-cap", payment_url="https://pay", status="NEW")


async def test_manual_charge_sends_receipt_to_kassa(client, db_session, monkeypatch):
    """Сквозная проверка: ручная оплата действительно кладёт Receipt в Init,
    а сумма позиций сходится с суммой платежа."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.core.security import get_password_hash
    from app.models.models import (
        Master, OWNER_DEFAULT_PERMISSIONS, Payment, Salon, SalonMember,
        SalonModerationStatus, SalonRole, SalonSubscriptionStatus, User, UserRole,
    )

    monkeypatch.setattr(settings, "TKASSA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TKASSA_TERMINAL_KEY", "T", raising=False)
    monkeypatch.setattr(settings, "TKASSA_PASSWORD", "P", raising=False)

    fake = _CapturingKassa()
    # payments.py импортирует TKassaClient на уровне модуля — патчить надо
    # именно там, иначе подменённое имя в app.services.tkassa не увидят
    monkeypatch.setattr("app.api.v1.endpoints.payments.TKassaClient",
                        lambda *a, **kw: fake)

    async with db_session() as db:
        owner = User(phone="+79990001234", full_name="В", email="owner@b.ru",
                     hashed_password=get_password_hash("Bizpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(name="Чековый", address="Т", phone="+70000000800",
                      latitude=1.0, longitude=1.0, city="Томск", is_active=True,
                      creator_id=owner.id, email="buh@salon.ru",
                      moderation_status=SalonModerationStatus.APPROVED,
                      business_tier="lite",
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=5))
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS),
                           is_active=True))
        await db.commit()

        for i in range(2):
            mu = User(phone=f"+7999000200{i}", full_name=f"М{i}",
                      hashed_password=get_password_hash("Masterp1"),
                      role=UserRole.MASTER, is_active=True)
            db.add(mu)
            await db.flush()
            db.add(Master(salon_id=salon.id, user_id=mu.id,
                          specialization="Мастер", is_active=True))
        await db.commit()
        salon_id, owner_phone = salon.id, owner.phone

    r = await client.post("/api/v1/auth/login",
                          json={"phone": owner_phone, "password": "Bizpass1"})
    assert r.status_code == 200, r.text
    client.cookies.set("access_token", r.json()["access_token"])

    r = await client.post("/api/v1/payments/business/manual-charge",
                          json={"salon_id": salon_id, "months": 2})
    assert r.status_code == 200, r.text

    receipt = fake.init_kwargs["receipt"]
    assert receipt is not None, "Receipt обязан уходить в кассу"
    # Почта салона приоритетнее почты владельца, телефон — всегда
    assert receipt["Email"] == "buh@salon.ru"
    assert receipt["Phone"] == owner_phone
    assert receipt["Items"][0]["Quantity"] == 2  # оплатили 2 месяца

    async with db_session() as db:
        payment = (await db.execute(
            select(Payment).where(Payment.salon_id == salon_id)
        )).scalars().first()
        assert payment.receipt_status == "pending"
        assert _sum(receipt) == rubles_to_kopecks(Decimal(str(payment.amount)))


# ── Уведомление доходит, чек контролируется ──────────────────────────────────

async def test_webhook_success_notifies_owner(client, db_session, monkeypatch):
    """Раньше про УСПЕХ система молчала: при автосписании владелец узнавал о
    деньгах только из выписки банка."""
    from datetime import datetime, timedelta, timezone

    from app.core.security import get_password_hash
    from app.models.models import (
        Payment, PaymentKind, PaymentStatus, Salon, SalonModerationStatus,
        SalonSubscriptionStatus, User, UserRole,
    )
    from app.services.tkassa import _sign

    monkeypatch.setattr(settings, "TKASSA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TKASSA_TERMINAL_KEY", "T", raising=False)
    monkeypatch.setattr(settings, "TKASSA_PASSWORD", "P", raising=False)

    sent: list = []

    async def _capture(db, salon, text):
        sent.append(text)

    monkeypatch.setattr("app.services.notifications.notify_subscription", _capture)

    letters: list = []

    class _Pool:
        async def enqueue_job(self, name, *a, **kw):
            letters.append((name, a))

    async def _pool():
        return _Pool()

    monkeypatch.setattr("app.core.worker.get_arq_pool", _pool)
    monkeypatch.setattr("app.services.payment_notice.get_arq_pool", _pool)

    now = datetime.now(timezone.utc)
    async with db_session() as db:
        owner = User(phone="+79990003456", full_name="В",
                     hashed_password=get_password_hash("Bizpass1"),
                     role=UserRole.BUSINESS, is_active=True)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        salon = Salon(name="Уведомляемый", address="Т", phone="+70000000800",
                      latitude=1.0, longitude=1.0, city="Томск", is_active=True,
                      creator_id=owner.id, email="buh2@salon.ru",
                      moderation_status=SalonModerationStatus.APPROVED,
                      business_tier="lite", subscription_amount=1250.0,
                      subscription_status=SalonSubscriptionStatus.ACTIVE)
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        salon.subscription_expires_at = now + timedelta(days=1)
        payment = Payment(salon_id=salon.id, plan="lite", kind=PaymentKind.RECURRENT,
                          amount=1575.0, months=1, invoice_id="order-notice-1",
                          status=PaymentStatus.PENDING, receipt_status="pending")
        db.add(payment)
        await db.commit()

    fields = {"TerminalKey": "T", "OrderId": "order-notice-1", "Success": "true",
              "Status": "CONFIRMED", "PaymentId": "pay-n1", "ErrorCode": "",
              "Amount": "157500", "Pan": "", "ExpDate": ""}
    body = {"TerminalKey": "T", "OrderId": "order-notice-1", "Success": True,
            "Status": "CONFIRMED", "PaymentId": "pay-n1", "Amount": 157500,
            "Token": _sign(fields, "P")}

    r = await client.post("/api/v1/payments/tkassa/notify", json=body)
    assert r.status_code == 200, r.text

    assert sent, "владелец должен получить уведомление об оплате"
    assert "1 575 ₽" in sent[0]
    assert "Доплата" in sent[0]        # расшифровка, а не голая сумма
    assert any(name == "send_email" and a[0] == "buh2@salon.ru"
               for name, a in letters), "письмо на почту салона не ушло"


async def test_stale_receipt_raises_alarm(db_session, monkeypatch):
    """Т-Касса не присылает «чек не пробит» — ловим с обратной стороны:
    платёж успешен давно, а фискальных реквизитов так и нет."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.core.security import get_password_hash
    from app.models.models import (
        Payment, PaymentKind, PaymentStatus, User, UserRole,
    )
    from app.tasks import check_pending_receipts

    alerts: list = []

    async def _capture(db, subject, body=""):
        alerts.append(subject)

    monkeypatch.setattr("app.services.notifications.notify_admins", _capture)

    async with db_session() as db:
        payer = User(phone="+79990004567", full_name="П",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.CLIENT, is_active=True)
        db.add(payer)
        await db.commit()
        await db.refresh(payer)
        db.add(Payment(user_id=payer.id, plan="lite", kind=PaymentKind.MANUAL,
                       amount=1250.0, invoice_id="order-stale-1",
                       status=PaymentStatus.SUCCEEDED, receipt_status="pending",
                       paid_at=datetime.now(timezone.utc) - timedelta(hours=6)))
        await db.commit()

    result = await check_pending_receipts({})
    assert "stale:1" in result
    assert alerts

    async with db_session() as db:
        payment = (await db.execute(
            select(Payment).where(Payment.invoice_id == "order-stale-1")
        )).scalar_one()
        assert payment.receipt_status == "failed"


async def test_fresh_payment_is_not_flagged_yet(db_session, monkeypatch):
    """Уведомление о чеке может задержаться на минуты — не поднимаем тревогу
    сразу, иначе алерт будет срабатывать на каждой оплате."""
    from datetime import datetime, timezone

    from app.core.security import get_password_hash
    from app.models.models import (
        Payment, PaymentKind, PaymentStatus, User, UserRole,
    )
    from app.tasks import check_pending_receipts

    async with db_session() as db:
        payer = User(phone="+79990005678", full_name="П",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.CLIENT, is_active=True)
        db.add(payer)
        await db.commit()
        await db.refresh(payer)
        db.add(Payment(user_id=payer.id, plan="lite", kind=PaymentKind.MANUAL,
                       amount=1250.0, invoice_id="order-fresh-1",
                       status=PaymentStatus.SUCCEEDED, receipt_status="pending",
                       paid_at=datetime.now(timezone.utc)))
        await db.commit()

    assert await check_pending_receipts({}) == "stale:0"


async def test_fiscal_notification_after_confirmation_is_recorded(
    client, db_session, monkeypatch,
):
    """Чек касса подтверждает ОТДЕЛЬНЫМ уведомлением по уже подтверждённому
    платежу. Защита от дублей стояла выше этой проверки и глушила его —
    отметка терялась, и ночной контроль ругался бы на каждый нормальный
    платёж."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.security import get_password_hash
    from app.models.models import (
        Payment, PaymentKind, PaymentStatus, User, UserRole,
    )
    from app.services.tkassa import _sign

    monkeypatch.setattr(settings, "TKASSA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TKASSA_TERMINAL_KEY", "T", raising=False)
    monkeypatch.setattr(settings, "TKASSA_PASSWORD", "P", raising=False)

    async with db_session() as db:
        payer = User(phone="+79990006789", full_name="П",
                     hashed_password=get_password_hash("Testpass1"),
                     role=UserRole.CLIENT, is_active=True)
        db.add(payer)
        await db.commit()
        await db.refresh(payer)
        db.add(Payment(user_id=payer.id, plan="lite", kind=PaymentKind.MANUAL,
                       amount=750.0, invoice_id="order-fiscal-1",
                       provider_transaction_id="pay-f1",
                       status=PaymentStatus.SUCCEEDED, receipt_status="pending",
                       paid_at=datetime.now(timezone.utc)))
        await db.commit()

    fields = {"TerminalKey": "T", "OrderId": "order-fiscal-1", "Success": "true",
              "Status": "CONFIRMED", "PaymentId": "pay-f1", "ErrorCode": "",
              "Amount": "75000", "Pan": "", "ExpDate": ""}
    body = {"TerminalKey": "T", "OrderId": "order-fiscal-1", "Success": True,
            "Status": "CONFIRMED", "PaymentId": "pay-f1", "Amount": 75000,
            "FiscalDocumentNumber": 42, "ReceiptDatetime": "2026-08-25T10:00:00+03:00",
            "Token": _sign(fields, "P")}

    r = await client.post("/api/v1/payments/tkassa/notify", json=body)
    assert r.status_code == 200

    async with db_session() as db:
        payment = (await db.execute(
            select(Payment).where(Payment.invoice_id == "order-fiscal-1")
        )).scalar_one()
        assert payment.receipt_status == "done"
