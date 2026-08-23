"""Правила подписки: срок доступа, доплата за рост штата, смена тарифа.

До этого тариф почти ни на что не влиял (единственной проверкой был запрет
публикации без подписки). Здесь проверяем, что подписка реально управляет
видимостью салона и что деньги считаются по согласованной формуле.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.core.security import get_password_hash
from app.models.models import (
    Salon, SalonModerationStatus, SalonSubscriptionStatus, User, UserRole,
)
from app.services.subscription import (
    DOWNGRADE_COOLDOWN_DAYS, TRIAL_GRACE_DAYS, SubscriptionError,
    access_until_for_paid, access_until_for_trial, ensure_can_change_plan,
    has_access, proration_for_growth, register_headcount, start_trial,
    suggested_downgrade, trial_available,
)


def _salon(**kw):
    base = dict(
        business_tier="lite", billed_plan="lite", billed_masters=0,
        prorated_masters=0, proration_from=None, pending_proration=0.0,
        subscription_status=SalonSubscriptionStatus.ACTIVE,
        last_downgrade_at=None, trial_used_at=None, access_until=None,
        trial_ends_at=None, subscription_expires_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── Срок доступа ─────────────────────────────────────────────────────────────

def test_trial_gets_grace_but_paid_does_not():
    ends = datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert access_until_for_trial(ends) == ends + timedelta(days=TRIAL_GRACE_DAYS)
    assert access_until_for_paid(ends) == ends  # после оплаты запаса нет


def test_has_access_by_deadline():
    future = datetime.now(timezone.utc) + timedelta(days=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert has_access(_salon(access_until=future)) is True
    assert has_access(_salon(access_until=past)) is False
    assert has_access(_salon(access_until=None)) is False


def test_start_trial_marks_used_and_opens_access():
    s = _salon(subscription_status=SalonSubscriptionStatus.TRIALING)
    assert trial_available(s) is True
    now = datetime.now(timezone.utc)
    ends = start_trial(s, 14, now, active_masters=3)
    assert ends == now + timedelta(days=14)
    assert s.access_until == ends + timedelta(days=TRIAL_GRACE_DAYS)
    assert s.billed_masters == 3          # планка = штат на старте
    assert trial_available(s) is False    # второй раз не дадим


# ── Доплата за рост штата ────────────────────────────────────────────────────

def test_proration_within_lite_is_delta_based():
    # было 4 мастера (1000 ₽), стало 5 (1250 ₽): доплата = 250/30 × дни
    # с 16 мая остаётся 16 дней (включая текущий), делитель всегда 30
    at = datetime(2026, 5, 16, tzinfo=timezone.utc)
    got = proration_for_growth("lite", 4, "lite", 5, at)
    assert got == (Decimal("250") / 30 * 16).quantize(Decimal("0.01")) == Decimal("133.33")


def test_proration_between_tariffs_uses_difference_not_full_price():
    # Лайт(5)=1250 → Бизнес=3500: берём разницу 2250, а НЕ полные 3500
    at = datetime(2026, 5, 16, tzinfo=timezone.utc)
    got = proration_for_growth("lite", 5, "business", 6, at)
    assert got == (Decimal("2250") / 30 * 16).quantize(Decimal("0.01")) == Decimal("1200.00")
    # для контраста: по полной цене нового тарифа вышло бы заметно больше
    assert got < (Decimal("3500") / 30 * 16)


def test_watermark_prevents_double_charge_on_toggle():
    """Выключил и снова включил того же мастера — второй раз не платит.

    Доплата теперь капает по дням: считаем два дня на уровне 5 мастеров,
    затем возврат к 4 и снова 5 — за «повторный найм» ничего не начисляется
    сверх фактически отработанного времени.
    """
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon(billed_masters=4, business_tier="lite", proration_from=t0, prorated_masters=4)

    register_headcount(s, 5, at=t0)                      # нанял — отсчёт пошёл
    assert s.pending_proration == 0.0                    # времени ещё не прошло

    register_headcount(s, 4, at=t0 + timedelta(days=2))  # проработал 2 дня
    after_two_days = s.pending_proration
    assert after_two_days > 0

    # вернули того же мастера и сразу выключили — лишнего не начислили
    register_headcount(s, 5, at=t0 + timedelta(days=2))
    register_headcount(s, 4, at=t0 + timedelta(days=2))
    assert s.pending_proration == after_two_days

def test_no_proration_during_trial():
    """Бесплатный период бесплатен целиком, сколько бы мастеров ни завели."""
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon(billed_masters=1, prorated_masters=1, proration_from=t0,
               subscription_status=SalonSubscriptionStatus.TRIALING)
    register_headcount(s, 5, at=t0)
    register_headcount(s, 5, at=t0 + timedelta(days=10))
    assert s.pending_proration == 0.0

# ── Смена тарифа ─────────────────────────────────────────────────────────────

def test_upgrade_is_always_allowed():
    s = _salon(business_tier="lite", last_downgrade_at=datetime.now(timezone.utc))
    ensure_can_change_plan(s, "business")  # не бросает, хотя понижали только что


def test_downgrade_blocked_for_three_months():
    s = _salon(business_tier="business", last_downgrade_at=datetime.now(timezone.utc))
    try:
        ensure_can_change_plan(s, "lite")
    except SubscriptionError as exc:
        assert "раз в 3 месяца" in str(exc)
    else:
        raise AssertionError("понижение должно быть заблокировано")


def test_downgrade_allowed_after_cooldown():
    old = datetime.now(timezone.utc) - timedelta(days=DOWNGRADE_COOLDOWN_DAYS + 1)
    ensure_can_change_plan(_salon(business_tier="business", last_downgrade_at=old), "lite")


def test_suggested_downgrade_hints_cheaper_plan():
    # 3 мастера на Бизнесе — по штату хватает Лайта
    assert suggested_downgrade(_salon(business_tier="business"), 3) == "lite"
    # на Лайте с тем же штатом предлагать нечего
    assert suggested_downgrade(_salon(business_tier="lite"), 3) is None


# ── Enforcement в каталоге ───────────────────────────────────────────────────

async def _mk_salon(db_session, name, access_until):
    async with db_session() as db:
        owner = User(phone=f"+7999{abs(hash(name)) % 10**7:07d}", full_name="В",
                     hashed_password=get_password_hash("Bizpass1"), role=UserRole.BUSINESS)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        s = Salon(name=name, address="Т", phone="+70000000800", latitude=1.0, longitude=1.0,
                  city="Томск", is_active=True, creator_id=owner.id,
                  moderation_status=SalonModerationStatus.APPROVED,
                  subscription_status=SalonSubscriptionStatus.ACTIVE)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        # листенер conftest ставит access_until — задаём нужный явно
        s.access_until = access_until
        await db.commit()
        return s.id


async def test_expired_subscription_drops_salon_from_catalog(client, db_session):
    live = datetime.now(timezone.utc) + timedelta(days=5)
    dead = datetime.now(timezone.utc) - timedelta(days=1)
    await _mk_salon(db_session, "ОплаченныйZZ", live)
    await _mk_salon(db_session, "ПросроченныйZZ", dead)

    html = (await client.get("/salons")).text
    assert "ОплаченныйZZ" in html
    assert "ПросроченныйZZ" not in html


# ── Напоминания по подписке ──────────────────────────────────────────────────

async def test_reminders_warn_before_cutoff(db_session, monkeypatch):
    """Жёсткое отключение честно только с предупреждением заранее: за 3 дня до
    конца триала и за 7/3/1 день при ручной оплате."""
    import app.tasks as tasks
    from app.models.models import Salon

    sent: list[str] = []

    async def fake_notify(db, salon, text):
        sent.append(text)

    monkeypatch.setattr("app.services.notifications.notify_subscription", fake_notify)

    now = datetime.now(timezone.utc)
    sid = await _mk_salon(db_session, "НапоминаемZZ", now + timedelta(days=10))
    async with db_session() as db:
        s = await db.get(Salon, sid)
        s.subscription_status = SalonSubscriptionStatus.TRIALING
        s.trial_ends_at = now + timedelta(days=3)      # триал кончается через 3 дня
        s.business_tier = "lite"
        await db.commit()

    await tasks.subscription_reminders({"job_try": 1})
    assert any("бесплатный период" in t for t in sent), sent

    sent.clear()
    async with db_session() as db:
        s = await db.get(Salon, sid)
        s.subscription_status = SalonSubscriptionStatus.ACTIVE
        s.trial_ends_at = None
        s.auto_renew = False
        s.subscription_expires_at = now + timedelta(days=7)   # ручная оплата: за 7 дней
        await db.commit()

    await tasks.subscription_reminders({"job_try": 1})
    assert any("продлите тариф" in t for t in sent), sent


async def test_admin_can_grant_repeat_trial(db_session):
    """Триал даётся один раз, но у старшего модератора есть ручная лазейка."""
    from app.models.models import Salon
    from app.services.subscription import start_trial, trial_available

    sid = await _mk_salon(db_session, "ПовторныйТриалZZ", datetime.now(timezone.utc) - timedelta(days=1))
    async with db_session() as db:
        s = await db.get(Salon, sid)
        start_trial(s, 14)
        await db.commit()
        assert trial_available(s) is False       # второй раз сам не возьмёт

        # то, что делает админ-роут: снимает отметку и выдаёт заново
        s.trial_used_at = None
        ends = start_trial(s, 14)
        await db.commit()
        await db.refresh(s)
        assert s.access_until > datetime.now(timezone.utc)
        assert ends > datetime.now(timezone.utc)


# ── Новый салон не платит за собственный штат ────────────────────────────────

def test_no_proration_before_tariff_chosen():
    """Салон ещё не выбрал тариф и заводит своих мастеров — денег не должен."""
    t0 = datetime(2026, 5, 10, tzinfo=timezone.utc)
    s = _salon(subscription_status=SalonSubscriptionStatus.NONE, business_tier=None,
               billed_plan=None, billed_masters=0, prorated_masters=0, proration_from=t0)
    register_headcount(s, 3, at=t0)
    register_headcount(s, 3, at=t0 + timedelta(days=10))
    assert s.pending_proration == 0.0

def test_trial_start_clears_pending_accrued_earlier():
    """Даже если что-то накопилось до подключения тарифа, старт бесплатного
    периода обнуляет счётчик: триал бесплатный целиком."""
    s = _salon(subscription_status=SalonSubscriptionStatus.NONE, pending_proration=825.0)
    start_trial(s, 14, active_masters=3)
    assert s.pending_proration == 0.0


def test_canceled_subscription_does_not_accrue():
    s = _salon(subscription_status=SalonSubscriptionStatus.CANCELED, billed_masters=2)
    assert register_headcount(s, 5) == 0
    assert s.pending_proration == 0.0


# ── Предоплата вперёд ────────────────────────────────────────────────────────

async def test_prepay_extends_access_by_paid_months(db_session):
    """Оплата на несколько месяцев вперёд продлевает доступ на весь срок,
    а не на один месяц."""
    from app.services.subscription import apply_successful_payment

    now = datetime.now(timezone.utc)
    s = _salon(pending_proration=500.0, billed_masters=3)
    months = 12
    apply_successful_payment(s, now + timedelta(days=30 * months), active_masters=3)
    assert s.access_until == now + timedelta(days=360)
    assert s.pending_proration == 0.0   # доплата вошла в этот платёж
