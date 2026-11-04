import re
from decimal import Decimal

import pytest

from app.services.tariffs import (
    TariffError,
    compute_amount,
    resolve_plan_for_employee_count,
)
from app.web.pages.business_checkout import render_business_checkout_page
from app.web.pages.business_landing import render_business_landing_page
from app.web.pages.model_join import render_model_join_page
from app.web.pages.model_landing import render_model_landing_page
from app.web.pages.tariffs import render_tariffs_page


@pytest.mark.parametrize(
    ("count", "amount"),
    [
        (1, 399),
        (2, 599),
        (3, 839),
        (4, 1079),
        (5, 1319),
        (6, 3500),
        (10, 3500),
        (11, 6990),
        (20, 6990),
    ],
)
def test_business_monthly_price_by_headcount(count, amount):
    plan = resolve_plan_for_employee_count(count)
    assert compute_amount(plan, count) == Decimal(amount)


@pytest.mark.parametrize(
    ("count", "plan"),
    [
        (1, "lite"),
        (5, "lite"),
        (6, "business"),
        (10, "business"),
        (11, "corporate"),
        (20, "corporate"),
        (21, "custom"),
    ],
)
def test_plan_by_headcount(count, plan):
    assert resolve_plan_for_employee_count(count) == plan


def test_lite_rejects_counts_outside_its_range():
    with pytest.raises(TariffError):
        compute_amount("lite", 6)


def test_business_calculator_precedes_benefits_section():
    html = render_business_landing_page()
    calculator = html.index('data-price-calculator')
    salon_benefits = html.index("Зачем это салону")
    assert calculator < salon_benefits
    assert "data-pricing=" in html
    assert "599" in html and "839" in html and "1319" in html
    assert 'id="pricing"' not in html
    assert "bl-pricing-card" not in html
    assert "https://vk.me/rummmiii?ref=support" in html
    assert "mailto:hello@rrumi.ru" in html
    assert 'name="phone"' in html and "Телефон (необязательно)" in html
    assert 'name="comment"' in html and 'maxlength="1000"' in html


def test_tariffs_page_shows_current_lite_pricing_and_custom_contact_path():
    html = render_tariffs_page()
    assert "1 мастер — 399 ₽/мес; 2 мастера — 599 ₽/мес" in html
    assert "3–5 мастеров — +240 ₽ за каждого начиная с 3-го (до 1 319 ₽/мес)" in html
    assert 'href="/business?employees=21#business-price-calculator"' in html
    assert "Запросить условия" in html


def test_model_pages_are_free_and_have_no_payment_steps():
    landing = render_model_landing_page()
    join = render_model_join_page(None)
    tariffs = render_tariffs_page()
    for html in (landing, join, tariffs):
        assert "Оплатить" not in html and "Оформить подписку" not in html
    for html in (landing, join):
        assert not re.search(r'<span class="amount">(?:490|990|1 990) ₽</span>', html)
    tariff_amounts = re.findall(r'<span class="amount">([^<]+)</span>', tariffs)
    assert not {"490 ₽", "990 ₽", "1 990 ₽"} & set(tariff_amounts)
    assert "Моделинг бесплатный" in landing
    assert "Стать моделью бесплатно" in landing
    assert 'data-step="tariff"' not in join
    assert 'name="model-plan"' not in join
    assert "Участие в моделинге бесплатное. Стоимость процедуры зависит от договорённости с мастером." in tariffs
    assert "/api/v1/payments/model/" not in join


@pytest.mark.asyncio
async def test_legacy_model_payment_endpoints_are_disabled():
    from fastapi import HTTPException

    from app.api.v1.endpoints.payments import (
        InitModelPaymentRequest,
        init_model_payment,
        manual_model_charge,
    )

    with pytest.raises(HTTPException) as init_error:
        await init_model_payment(
            InitModelPaymentRequest(plan="pro", auto_renew=True),
            request=None, current_user=None, db=None,
        )
    assert init_error.value.status_code == 410

    with pytest.raises(HTTPException) as charge_error:
        await manual_model_charge(request=None, current_user=None, db=None)
    assert charge_error.value.status_code == 410


def test_model_profile_clears_legacy_billing_state():
    from types import SimpleNamespace

    from app.api.v1.endpoints.model_matching import _disable_legacy_model_billing
    from app.models.models import SalonSubscriptionStatus, SubscriptionTier

    user = SimpleNamespace(
        subscription_tier=SubscriptionTier.PRO,
        subscription_status=SalonSubscriptionStatus.ACTIVE,
        auto_renew=True,
        trial_ends_at=object(),
        subscription_expires_at=object(),
        recurring_token="legacy-token",
        subscription_amount=990,
        card_last4="1234",
        access_until=object(),
        trial_used_at=object(),
        last_downgrade_at=object(),
    )
    _disable_legacy_model_billing(user)

    assert user.subscription_tier is None
    assert user.subscription_status == SalonSubscriptionStatus.NONE
    assert user.auto_renew is False
    assert user.recurring_token is None
    assert user.subscription_amount is None
    assert user.card_last4 is None
    assert user.access_until is None


@pytest.mark.asyncio
async def test_approved_model_does_not_need_a_subscription():
    from types import SimpleNamespace

    from app.api.deps import require_approved_model
    from app.models.models import ModelModerationStatus, SalonSubscriptionStatus

    user = SimpleNamespace(
        is_model=True,
        model_moderation_status=ModelModerationStatus.APPROVED,
        subscription_status=SalonSubscriptionStatus.NONE,
    )
    assert await require_approved_model(user) is user


def test_checkout_shows_the_new_lite_price_and_calculates_each_team_size():
    html = render_business_checkout_page(plan="lite")
    assert "От 399 ₽" in html
    assert '"1": 399' in html and '"2": 599' in html and '"5": 1319' in html
    assert "240 ₽" not in html
