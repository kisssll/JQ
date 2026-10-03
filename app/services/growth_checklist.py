"""«Чтобы выбирали вас» — что ещё можно сделать, когда записаться уже можно.

Группа 2 живого блока «Путь к первому клиенту» (решение 0010, п. 3). Группу 1
считает booking_readiness — тот отвечает на вопрос «можно ли записаться» и
переписан здесь не будет; этот модуль про другое: записаться уже можно, но в
ленте человека ещё не выбирают.

Правила те же, что у booking_readiness, и по тем же причинам:

  * ни одного обращения к базе в evaluate() — он работает на значениях,
    поэтому каждый пункт проверяется без базы и без HTTP;
  * разметки и текстов здесь нет: текст лежит в panel_guide (там он попадает
    под защиту от запрещённых обещаний), рисует «Обзор»;
  * каждое утверждение пункта выписано из кода каталога, рядом стоит источник
    (panel_guide.SOURCES, блок «добавлено в заходе 6»).

Три состояния пункта, а не два (решение 0010, п. 5):

  * НЕ СДЕЛАН — строка с действием и ссылкой;
  * СДЕЛАН — схлопывается в «Сделано: N», отдельной строкой не висит;
  * НЕПРИМЕНИМ — не показывается вовсе и в «Сделано: N» не попадает. Акция без
    услуг и вечерние окна без заданных часов приёма физически не сработают, и
    требовать их — отправлять человека делать то, что ничего не изменит.

Кнопки «не нужно» у пункта нет намеренно (решение 0010, п. 5): сначала владелец
пройдёт список руками и скажет, раздражает ли он. Скрытый пункт — ещё и способ
спрятать от себя настоящую проблему.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from sqlalchemy import Boolean, cast, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Booking, BookingStatus, Review, Salon, SalonEveningDeal,
)
from app.services import panel_guide, panel_sections, panel_tour

#: Тарифы, которые поднимают карточку в каталоге и дают метку «Продвигается».
#: Тот же набор, что отбирает каталог (salons.py — _PAID): отдельный список
#: разъехался бы с ним при первом новом тарифе.
PROMOTED_TIERS = frozenset({"business", "corporate", "custom"})

#: Причина booking_readiness, по которой видно, что часы приёма не заданы.
#: Берём её ключом, а не вторым разбором working_hours: разбор там идёт тем же
#: get_salon_work_hours, что у слот-генератора, и вторая его копия здесь
#: разъехалась бы с первой. Ключ входит в контракт сервиса
#: (booking_readiness.ISSUE_KEYS), и тест это держит.
_NO_HOURS_KEY = "no_salon_hours"


@dataclass(frozen=True)
class Item:
    """Один пункт группы 2.

    target — раздел панели (?tab=) либо раздел с якорем, как у
    booking_readiness.Issue: адрес собирается по режиму, потому что в соло
    настройки салона лежат в «Моей карточке мастера» двумя группами.
    """
    key: str
    text: str
    action: str
    target: str
    done: bool


@dataclass(frozen=True)
class Checklist:
    """Применимые пункты группы 2 в порядке реестра."""
    items: Tuple[Item, ...] = ()

    @property
    def pending(self) -> Tuple[Item, ...]:
        return tuple(i for i in self.items if not i.done)

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.items if i.done)

    @property
    def all_done(self) -> bool:
        return not self.pending


#: Якорь секции вечерних окон (components/evening_deal.py). Имя здесь, а не
#: строкой в двух местах: компонент берёт его отсюда же.
ANCHOR_EVENING = "evening-deals"


# Куда ведёт пункт. «settings_public» — та половина настроек, которую видит
# клиент (имя, описание, фотографии): в команде это «Редактировать салон», в
# соло — группа «Как вас видят клиенты» внутри «Моей карточки мастера».
# «evening» — секция вечерних окон внутри «Акций»: без якоря ссылка привела бы
# в начало длинной вкладки, где этой секции не видно.
_ROLES = {
    "services": lambda solo: "services",
    "promos": lambda solo: "promos",
    "evening": lambda solo: f"promos#{ANCHOR_EVENING}",
    "billing": lambda solo: "billing",
    "reviews": lambda solo: "reviews",
    "settings_public": lambda solo: (
        f"employees#{panel_tour.ANCHOR_CARD_PUBLIC}" if solo else "edit"
    ),
}


def _target(role: str, solo: bool) -> str:
    return _ROLES[role](solo)


def evaluate(
    *,
    solo: bool,
    has_cover: bool,
    has_description: bool,
    services_total: int,
    has_active_promo: bool,
    evening_on: bool,
    salon_hours_set: bool,
    promoted_tier: bool,
    has_completed_booking: bool,
    has_review: bool,
) -> Checklist:
    """Пункты группы 2 — применимые, в порядке реестра.

    services_total — услуги, которые клиент может выбрать (активные и не
    модельные), тем же набором условий, что отбирает гостевая страница записи.
    По нему же решается применимость акции: скидка без услуг ни к чему не
    применяется.
    """
    done = {
        "cover": has_cover,
        "description": has_description,
        "services": services_total > 0,
        "promo": has_active_promo,
        "evening": evening_on,
        "tariff": promoted_tier,
    }
    # Пункт, который не может сработать, не показываем вовсе — ни строкой, ни в
    # «Сделано: N»: иначе человек увидел бы «сделано 5», не сделав ничего.
    applicable = {
        "promo": services_total > 0,
        "evening": salon_hours_set and services_total > 0,
    }

    items: list[Item] = []
    for key, text, action, role in panel_guide.check_items(solo=solo):
        if not applicable.get(key, True):
            continue
        items.append(Item(
            key=key, text=text, action=action,
            target=_target(role, solo), done=done[key],
        ))

    # Условный пункт: до первой завершённой записи отзыв невозможен, после
    # появления отзыва просить его незачем (решение 0010, п. 3).
    if has_completed_booking and not has_review:
        key, text, action, role = panel_guide.check_review_item(solo=solo)
        items.append(Item(
            key=key, text=text, action=action,
            target=_target(role, solo), done=False,
        ))

    return Checklist(tuple(items))


async def collect(
    db: AsyncSession,
    salon: Salon,
    *,
    solo: bool,
    master_ids,
    services_total: int,
    promotions,
    readiness,
    has_any_booking: bool,
) -> Checklist:
    """Собрать значения для evaluate() из базы.

    Своих запросов здесь не больше двух, и ни одного в цикле по мастерам или
    услугам: «Обзор» — самый посещаемый раздел панели, и его однажды разгоняли
    с девяти секунд до двух с половиной.

    Что приходит готовым и НЕ переспрашивается: услуги (services_total считает
    панель одним запросом на всю вкладку), акции (promotions — тот же список,
    что идёт в блоки «Обзора»), причины готовности (readiness), признак «записи
    вообще есть» (has_any_booking).

      1. настройка вечерних окон — и только если часы приёма заданы: без них
         пункт неприменим, и спрашивать нечего;
      2. завершённая запись и отзыв — одним запросом на два EXISTS, потому что
         нужны они вместе и только вместе. Если записей нет вовсе, запрос не
         идёт: отзыв без завершённой записи невозможен.
    """
    salon_hours_set = not any(i.key == _NO_HOURS_KEY for i in readiness.issues)

    evening_on = False
    if salon_hours_set and services_total > 0:
        deal = (await db.execute(
            select(SalonEveningDeal).where(SalonEveningDeal.salon_id == salon.id)
        )).scalar_one_or_none()
        evening_on = bool(
            deal is not None and deal.enabled and deal.discount_percent > 0
        )

    has_completed_booking = False
    has_review = False
    if has_any_booking and master_ids:
        # Счётчик salon.reviews_count не спрашиваем намеренно: он
        # пересчитывается только при создании отзыва (review_service), и на
        # устаревшем нуле мы продолжали бы просить отзыв, который уже есть.
        row = (await db.execute(select(
            cast(exists(
                select(Booking.id).where(
                    Booking.master_id.in_(master_ids),
                    Booking.status == BookingStatus.COMPLETED,
                )
            ), Boolean).label("done_booking"),
            cast(exists(
                select(Review.id).where(Review.salon_id == salon.id)
            ), Boolean).label("any_review"),
        ))).one()
        has_completed_booking = bool(row.done_booking)
        has_review = bool(row.any_review)

    return evaluate(
        solo=solo,
        has_cover=bool((salon.logo_url or "").strip()),
        has_description=bool((salon.description or "").strip()),
        services_total=services_total,
        has_active_promo=any(bool(p.is_active) for p in promotions),
        evening_on=evening_on,
        salon_hours_set=salon_hours_set,
        promoted_tier=(salon.business_tier or "") in PROMOTED_TIERS,
        has_completed_booking=has_completed_booking,
        has_review=has_review,
    )


def next_links(salon, *, solo: bool, visible_keys) -> Tuple[Tuple[str, str, str], ...]:
    """Группа 3: (ключ раздела, название раздела, одна фраза).

    Раздел, которого у человека нет, ссылкой не становится — такая ссылка молча
    вернула бы его в «Обзор» (то же правило у справочника и у тура). Поэтому
    ссылок может оказаться меньше четырёх: это лучше, чем ссылка в никуда.
    """
    mode = salon.panel_mode
    visible = frozenset(visible_keys) if visible_keys is not None else None
    out = []
    for key, phrase in panel_guide.check_next(solo=solo):
        # «Обзор» в соло — это сама открытая вкладка, её видимость спрашивать
        # незачем: блок рисуется именно в ней.
        if key != "overview" and visible is not None and key not in visible:
            continue
        out.append((key, panel_sections.label(key, mode), phrase))
    return tuple(out)
