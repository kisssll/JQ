"""Свойства «текст от человека»: имя, название салона, специализация, услуга.

Расширяет tests/test_xss_ssr.py генератором: там один пейлоад на каждую
страницу, здесь — пустое, из пробелов, предельной длины, эмодзи, кавычки,
угловые скобки, их смеси. Значения кладём в БД напрямую (в обход валидации
форм): страница обязана выжить с тем, что там УЖЕ лежит.

Свойство: страница отвечает без 5xx, а всё, что вставлено между метками
ZQX…ZQY, не содержит сырых «<» и «>» — иначе это разметка, а не текст.
"""
import re
from datetime import datetime, timedelta, timezone

import httpx
from hypothesis import given, seed, strategies as st

from app.core.security import create_access_token, get_password_hash
from app.models.models import (
    Master, Salon, SalonMember, SalonModerationStatus, SalonRole,
    SalonSubscriptionStatus, Service, User, UserRole,
)
from tests_fuzz.conftest import wipe_all_tables
from tests_fuzz.profile import SEED, props

NASTY = ["<script>alert(1)</script>", '"><img src=x onerror=1>', "'", '"', "</script>",
         "<svg onload=1>", "&amp;", "&lt;", "\\", "{{7*7}}", "${7}", "%s", "😀", "👩‍👩‍👧",
         " ", " ", "‮", "﻿", "\n", "\t", "́"]
# Postgres не хранит NUL и непарные суррогаты — таких строк в базе быть не может
safe_text = st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"), max_size=120)
human = st.one_of(
    st.just(""), st.just(" "), st.just("   \t\n"),
    st.lists(st.sampled_from(NASTY) | safe_text, min_size=1, max_size=6).map("".join),
    safe_text,
    st.just("Я" * 100),
)

MARK = ("ZQX", "ZQY")


def _fit(value: str, limit: int) -> str:
    return value[:limit]


def _wrapped(value: str, limit: int) -> str:
    # Пустое и из пробелов оставляем КАК ЕСТЬ: это и есть случай с IndexError на
    # имени из пробела, метки его бы замаскировали. Остальное — в метках внутри
    # лимита колонки, чтобы обрезка не съела закрывающую.
    if not value.strip():
        return value
    return MARK[0] + _fit(value, limit - 6) + MARK[1]


def _raw_markup_between_marks(html: str) -> list[str]:
    bad = []
    for seg in re.findall(re.escape(MARK[0]) + r"(.*?)" + re.escape(MARK[1]), html, flags=re.S):
        if "<" in seg or ">" in seg:
            bad.append(seg[:80])
    return bad


async def _build(db_session, *, user_name, salon_name, spec, service_name, address):
    await wipe_all_tables()
    pw = get_password_hash("Fuzzpass1")
    async with db_session() as db:
        owner = User(phone="+79990000001", full_name=_wrapped(user_name, 100),
                     hashed_password=pw, role=UserRole.BUSINESS)
        muser = User(phone="+79990000002", full_name=_wrapped(user_name, 100),
                     hashed_password=pw, role=UserRole.MASTER)
        db.add_all([owner, muser])
        await db.commit()
        salon = Salon(name=_wrapped(salon_name, 100), description=_wrapped(salon_name, 400),
                      address=_wrapped(address, 255), latitude=56.5, longitude=84.9,
                      phone="+79990001111", city="Томск", is_active=True, creator_id=owner.id,
                      moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      access_until=datetime.now(timezone.utc) + timedelta(days=30),
                      published_at=datetime.now(timezone.utc))
        db.add(salon)
        await db.commit()
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        master = Master(user_id=muser.id, salon_id=salon.id, specialization=_wrapped(spec, 100), is_active=True)
        db.add(master)
        await db.commit()
        db.add(Service(master_id=master.id, name=_wrapped(service_name, 100), price=1000,
                       duration_minutes=60, is_active=True))
        await db.commit()
        return owner.id, salon.id, master.id


async def _check_pages(db_session, ids):
    from app.main import app

    owner_id, salon_id, master_id = ids
    problems = []
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as anon, \
            httpx.AsyncClient(transport=transport, base_url="http://testserver",
                              cookies={"access_token": create_access_token(owner_id)}) as owner:
        pages = [(anon, "/"), (anon, "/salons"), (anon, f"/salons/{salon_id}"), (anon, f"/masters/{master_id}"),
                 (anon, f"/book/{salon_id}"), (owner, "/"), (owner, "/profile"), (owner, "/bookings"),
                 (owner, "/business/dashboard?tab=overview"), (owner, "/business/dashboard?tab=employees"),
                 (owner, "/business/dashboard?tab=services"), (owner, "/business/dashboard?tab=edit")]
        for client, url in pages:
            r = await client.get(url)
            if r.status_code >= 500:
                problems.append(f"{url}: {r.status_code}")
                continue
            bad = _raw_markup_between_marks(r.text)
            if bad:
                problems.append(f"{url}: сырая разметка в {bad[:2]}")
    return problems


@seed(SEED)
@props(examples=25)
@given(user_name=human, salon_name=human, spec=human, service_name=human, address=human)
def test_pages_survive_and_escape_human_text(run, db_session, user_name, salon_name, spec, service_name, address):
    ids = run(_build(db_session, user_name=user_name, salon_name=salon_name, spec=spec,
                     service_name=service_name, address=address))
    problems = run(_check_pages(db_session, ids))
    assert not problems, "\n".join(problems)
