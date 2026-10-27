"""Свойства денег: доплата, смена плана, возврат, скидка вечернего окна.

Объекты салона — SimpleNamespace с теми же полями, что читают функции
subscription.py: свойство проверяет арифметику, а не ORM.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from hypothesis import assume, given, seed, strategies as st

from app.models.models import SalonSubscriptionStatus as S
from app.services import subscription as sub
from app.services.evening_deals_service import discounted_price
from app.services.tariffs import TARIFF_CATALOG
from tests_fuzz.profile import SEED, props

plans = st.one_of(st.none(), st.sampled_from(list(TARIFF_CATALOG) + ["custom", "zzz"]))
masters = st.integers(-5, 40)
moments = st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2030, 1, 1),
                       timezones=st.just(timezone.utc))


def _salon(plan, billed_plan, billed_masters, prorated, since, status, pending=0.0, **extra):
    return SimpleNamespace(
        business_tier=plan, billed_plan=billed_plan, billed_masters=billed_masters,
        prorated_masters=prorated, proration_from=since, subscription_status=status,
        pending_proration=pending, last_downgrade_at=None, **extra)


@seed(SEED)
@props()
@given(pb=plans, mb=masters, pa=st.sampled_from(list(TARIFF_CATALOG) + ["custom"]), ma=masters, at=moments)
def test_growth_proration_is_never_negative(pb, mb, pa, ma, at):
    assert sub.proration_for_growth(pb, mb, pa, ma, at) >= Decimal("0")


@seed(SEED)
@props()
@given(plan=plans, billed=plans, bm=st.integers(0, 40), pm=st.integers(0, 40),
       since=moments, dt=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=90)),
       status=st.sampled_from(list(S)), pending=st.floats(0, 1e6))
def test_accrual_never_takes_money_back(plan, billed, bm, pm, since, dt, status, pending):
    """Начисление только прибавляет: pending_proration не убывает и не уходит в минус."""
    salon = _salon(plan, billed, bm, pm, since, status, pending)
    got = sub.accrue_proration(salon, since + dt)
    assert got >= 0
    assert salon.pending_proration >= pending - 1e-9
    assert salon.pending_proration >= 0


@seed(SEED)
@props()
@given(start=st.sampled_from(["lite", "business", "corporate"]),
       other=st.sampled_from(["lite", "business", "corporate"]),
       bm=st.integers(0, 20), at=moments,
       gap=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=20)))
def test_plan_round_trip_never_extends_paid_period(start, other, bm, at, gap):
    """Туда-обратно между тарифами: срок доступа не меняется вообще, а доплата
    не отрицательна. Смена плана — это не оплата и срока не даёт."""
    until = at + timedelta(days=30)
    salon = _salon(start, start, bm, bm, at, S.ACTIVE, access_until=until,
                   subscription_expires_at=until)
    sub.register_plan_change(salon, other, bm, at + gap)
    sub.register_plan_change(salon, start, bm, at + gap * 2)
    assert salon.access_until == until
    assert salon.subscription_expires_at == until
    assert salon.pending_proration >= 0


@pytest.mark.xfail(strict=True, reason=(
    "docs/fuzz-findings.md#F1: возврат по уже истёкшей подписке двигает "
    "subscription_expires_at ВПЕРЁД, к «сейчас». Деньги — правка отдельным заходом."))
@seed(SEED)
@props()
@given(now=moments, current_off=st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400)),
       months=st.integers(1, 12), share=st.floats(0, 1))
def test_refund_never_extends_the_period(now, current_off, months, share):
    """Возврат забирает срок, но не выдаёт его: новый конец не позже прежнего."""
    current = now + current_off
    t = SimpleNamespace(subscription_expires_at=current, access_until=current)
    new = sub.revoke_paid_period(t, months, share, at=now)
    assert new <= current, f"возврат сдвинул срок вперёд: {current} → {new}"


@seed(SEED)
@props()
@given(expires=moments, masters_=st.one_of(st.none(), st.integers(0, 30)))
def test_payment_gives_access_exactly_to_paid_end(expires, masters_):
    t = SimpleNamespace(billed_plan=None, business_tier="lite", pending_proration=5.0,
                        billed_masters=0, proration_from=None, prorated_masters=0)
    sub.apply_successful_payment(t, expires, masters_)
    assert t.access_until == expires
    assert t.pending_proration == 0.0


@seed(SEED)
@props()
@given(base=st.integers(0, 10_000_000), pct=st.integers(0, 100))
def test_evening_discount_stays_between_zero_and_base(base, pct):
    price = discounted_price(base, pct)
    assert 0 <= price <= base


@seed(SEED)
@props()
@given(base=st.integers(0, 10_000_000), pct=st.integers(-1000, 1000))
def test_evening_discount_is_never_below_zero_for_any_percent(base, pct):
    assert discounted_price(base, pct) >= 0
