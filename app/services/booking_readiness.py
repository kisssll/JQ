"""Можно ли записаться к этому салону — и если нет, что именно мешает.

Блок «Можно ли к вам записаться» на главном экране панели (решение 0007, п. 6)
— это обещание человеку. Поэтому условия здесь не придуманы под текст, а
выписаны из кода самой записи; у каждого рядом стоит его источник:

  * app/web/pages/guest_booking.py, render_guest_booking_page — страница
    /book/{salon_id}, то есть ссылка и QR из панели;
  * app/api/v1/endpoints/guest.py, create_guest_booking — отправка заявки с
    этой страницы (у неё есть проверка, которой нет на самой странице: тариф);
  * app/api/v1/endpoints/bookings.py, _salon_bookable — запись клиента с
    аккаунтом из каталога (другой набор флагов: смотрит is_deleted и is_hidden,
    но не смотрит guest_booking_enabled);
  * app/api/v1/endpoints/bookings.py, get_available_slots и
    app/services/schedule_utils.py — откуда вообще берутся свободные окна.

Два пути записи закрываются разными флагами, поэтому и причины делятся на две
категории: blocking — не может записаться НИКТО; warning — один из путей
закрыт, второй работает. Сваливать их в одну кучу нельзя: «записаться нельзя»
при выключенной гостевой записи было бы ложью (клиент с аккаунтом записался бы
из каталога), а «всё в порядке» при ней же — ложью про ссылку и QR.

Чего здесь НЕТ намеренно:
  * разметки и ссылок — текст и адрес раздела отдаём как данные, рисует панель;
  * обращений к БД в evaluate() — он работает на значениях, поэтому каждое
    условие проверяется без базы и без HTTP (tests/test_booking_readiness.py).
    Собрать значения — дело collect(), и только оно трогает базу.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Master, Salon, SalonModerationStatus, Schedule, Service,
)
from app.services import panel_tour
from app.services.schedule_utils import (
    build_day_intervals, compute_effective_intervals, get_salon_work_hours,
)
from app.services.subscription import has_access


@dataclass(frozen=True)
class Issue:
    """Одна причина, по которой запись не работает как ожидается.

    text — что не так, одной фразой; action — что человек сделает («Добавить
    услугу»); target — раздел панели (?tab=) либо якорь на странице. Без
    target подписи действия тоже нет: кнопка, которая никуда не ведёт, хуже
    её отсутствия (бывает и честное «сделать нечего» — например, модерация).
    """
    key: str
    text: str
    action: str = ""
    target: str = ""
    blocking: bool = True


@dataclass(frozen=True)
class Readiness:
    issues: Tuple[Issue, ...] = field(default_factory=tuple)

    @property
    def blocking(self) -> Tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.blocking)

    @property
    def warnings(self) -> Tuple[Issue, ...]:
        return tuple(i for i in self.issues if not i.blocking)

    @property
    def can_book(self) -> bool:
        """Хоть кто-то может записаться (клиент с аккаунтом — из каталога)."""
        return not self.blocking

    @property
    def link_works(self) -> bool:
        """Работают ли именно ссылка и QR из панели."""
        return self.can_book and not any(i.key == "guest_booking_off" for i in self.issues)


# Разделы панели, куда ведут действия. Ключи те же, что в ?tab= (см.
# panel_sections.ALL_KEYS); «#salon-status» — якорь на плашку статуса в шапке
# панели: кнопка «Опубликовать салон» живёт только там, второй такой же кнопкой
# мы бы продублировали обработчик по id.
_TAB_EMPLOYEES = "employees"
_TAB_SERVICES = "services"
_TAB_SCHEDULE = "schedule"
_TAB_EDIT = "edit"
_TAB_BILLING = "billing"
_ANCHOR_STATUS = "#salon-status"

# Куда вести за настройками салона. В командном режиме это «Редактировать
# салон»; в соло такой вкладки нет — её содержимое переехало в «Мою карточку
# мастера» и легло там двумя группами, поэтому ведём якорем сразу в нужную
# (решение 0009, п. 2 и п. 8). Без этого каждое второе действие блока
# готовности вело бы в раздел, которого у человека нет, и панель молча
# возвращала бы его в «Обзор».
# Якорь берём у тура, а не пишем строкой: та же группа подсвечивается его
# шагом, и две копии имени якоря разъехались бы при первом переименовании.
_SOLO_SETTINGS = f"{_TAB_EMPLOYEES}#{panel_tour.ANCHOR_CARD_WORK}"


def _settings_target(solo: bool) -> str:
    return _SOLO_SETTINGS if solo else _TAB_EDIT


def evaluate(
    *,
    solo: bool,
    is_active: bool,
    is_deleted: bool,
    is_hidden: bool,
    moderation_status,
    published_at: Optional[datetime],
    has_tariff: bool,
    guest_booking_enabled: bool,
    active_masters: int,
    bookable_masters: int,
    salon_hours_set: bool,
    open_weekdays: int,
) -> Readiness:
    """Причины в том порядке, в котором их имеет смысл устранять."""
    # Удалённый салон публично не существует — остальные строки про него были бы
    # шумом («добавьте услугу» салону, которого нет).
    if not is_active or is_deleted:
        return Readiness((Issue(
            key="salon_deleted",
            text=(
                "Ваш профиль удалён с платформы: запись закрыта, в ленте вас нет."
                if solo else
                "Салон удалён с платформы: запись закрыта, в каталоге его нет."
            ),
        ),))

    issues: list[Issue] = []

    if moderation_status == SalonModerationStatus.PENDING:
        issues.append(Issue(
            key="moderation_pending",
            text=(
                "Ваша заявка ещё на модерации — до подтверждения запись закрыта."
                if solo else
                "Заявка на салон ещё на модерации — до подтверждения запись закрыта."
            ),
        ))
    elif moderation_status == SalonModerationStatus.REJECTED:
        issues.append(Issue(
            key="moderation_rejected",
            text=(
                "Вашу заявку отклонили — напишите в поддержку hello@rrumi.ru."
                if solo else
                "Заявку на салон отклонили — напишите в поддержку hello@rrumi.ru."
            ),
        ))

    # Тариф спрашиваем раньше публикации: без подписки кнопка «Опубликовать»
    # всё равно недоступна (см. плашку в dashboard.py).
    if not has_tariff:
        issues.append(Issue(
            key="no_tariff",
            text="Подписка не оплачена — новые записи не принимаются.",
            action="Оплатить подписку", target=_TAB_BILLING,
        ))

    if published_at is None:
        issues.append(Issue(
            key="not_published",
            text=(
                "Вас пока не видно в ленте — ни лента, ни ссылка для записи не работают."
                if solo else
                "Салон не опубликован — ни каталог, ни ссылка для записи не работают."
            ),
            action="Опубликоваться" if solo else "Опубликовать салон",
            target=_ANCHOR_STATUS,
        ))

    if active_masters == 0:
        issues.append(Issue(
            key="no_master",
            text=(
                "Нет вашей карточки мастера — записываться не к кому."
                if solo else
                "Ни одного активного мастера — записываться не к кому."
            ),
            action="Создать карточку мастера" if solo else "Добавить мастера",
            target=_TAB_EMPLOYEES,
        ))
    elif bookable_masters == 0:
        # Мастер без услуг выпадает из гостевой записи целиком (continue в
        # render_guest_booking_page), поэтому это не «мало услуг», а «нельзя».
        issues.append(Issue(
            key="no_services",
            text="Ни одной услуги для записи — клиенту нечего выбрать.",
            action="Добавить услугу", target=_TAB_SERVICES,
        ))

    if not salon_hours_set:
        issues.append(Issue(
            key="no_salon_hours",
            text=(
                "Часы приёма не заданы — свободных окон не бывает ни в один день."
                if solo else
                "Часы работы салона не заданы — свободных окон не бывает ни в один день."
            ),
            action="Задать часы приёма" if solo else "Задать часы работы",
            target=_settings_target(solo),
        ))
    elif open_weekdays == 0 and bookable_masters > 0:
        # Часы салона есть, но недельный график мастера с ними не пересекается
        # ни в один день (compute_effective_intervals вернёт пусто всегда).
        issues.append(Issue(
            key="no_workdays",
            text=(
                "В вашем графике нет ни одного рабочего дня внутри часов приёма."
                if solo else
                "В графике мастера нет ни одного рабочего дня внутри часов салона."
            ),
            action="Настроить график", target=_TAB_SCHEDULE,
        ))

    # ── Дальше то, что закрывает один путь записи из двух ──
    if is_hidden:
        issues.append(Issue(
            key="hidden",
            text=(
                "Вы скрыты с платформы: в ленте вас нет, запись осталась только по вашей ссылке."
                if solo else
                "Салон скрыт с платформы: в каталоге его нет, запись осталась только по вашей ссылке."
            ),
            action="Вернуться в ленту" if solo else "Вернуть в каталог",
            target=_settings_target(solo), blocking=False,
        ))

    if not guest_booking_enabled:
        issues.append(Issue(
            key="guest_booking_off",
            text=(
                "Запись без регистрации выключена — ссылка и QR не работают. "
                "Клиенты с аккаунтом записываются из каталога."
            ),
            action="Включить запись по ссылке", target=_settings_target(solo),
            blocking=False,
        ))

    return Readiness(tuple(issues))


async def collect(db: AsyncSession, salon: Salon, masters, solo: bool) -> Readiness:
    """Собрать значения для evaluate() из базы.

    masters приходит уже загруженным (панель грузит мастеров один раз на все
    вкладки), поэтому отдельного запроса за ними здесь нет.
    """
    active = [m for m in masters if m.is_active]

    bookable_ids: list[int] = []
    if active:
        # Тот же набор условий, что отбирает услуги гостевой страницы: услуга
        # либо принадлежит мастеру, либо назначена ему, активна и не «модельная»
        # (модельные обычным клиентам не показываются вовсе).
        for m in active:
            exists = await db.scalar(
                select(func.count(Service.id)).where(
                    or_(
                        Service.master_id == m.id,
                        Service.assigned_masters.any(Master.id == m.id),
                    ),
                    Service.is_active == True,  # noqa: E712
                    Service.is_model_practice == False,  # noqa: E712
                )
            )
            if exists:
                bookable_ids.append(m.id)

    # «Часы салона заданы» — не «строка не пустая», а «хотя бы один день
    # разбирается и открыт»: разбором занимается тот же get_salon_work_hours,
    # что и слот-генератор, поэтому расхождения быть не может.
    probe = datetime(2026, 1, 5)  # понедельник; дальше +1 день по неделе
    salon_hours = {
        wd: get_salon_work_hours(salon.working_hours, probe.replace(day=5 + wd))
        for wd in range(7)
    }
    salon_hours_set = any(v is not None for v in salon_hours.values())

    open_weekdays = 0
    if salon_hours_set and bookable_ids:
        rows = (await db.execute(
            select(Schedule).where(Schedule.master_id.in_(bookable_ids))
        )).scalars().all()
        for wd in range(7):
            day = probe.replace(day=5 + wd)
            for mid in bookable_ids:
                mine = [r for r in rows if r.master_id == mid]
                intervals = compute_effective_intervals(
                    salon_hours[wd],
                    bool(mine),
                    build_day_intervals([r for r in mine if r.day_of_week == wd], day),
                )
                if intervals:
                    open_weekdays += 1
                    break

    return evaluate(
        solo=solo,
        is_active=bool(salon.is_active),
        is_deleted=bool(getattr(salon, "is_deleted", False)),
        is_hidden=bool(getattr(salon, "is_hidden", False)),
        moderation_status=salon.moderation_status,
        published_at=salon.published_at,
        has_tariff=has_access(salon),
        guest_booking_enabled=bool(salon.guest_booking_enabled),
        active_masters=len(active),
        bookable_masters=len(bookable_ids),
        salon_hours_set=salon_hours_set,
        open_weekdays=open_weekdays,
    )


# Все причины, которые умеет выдавать evaluate(). Нужен не коду, а тесту на
# полноту сценариев: без него новая причина могла бы остаться непроверенной.
ISSUE_KEYS = frozenset({
    "salon_deleted", "moderation_pending", "moderation_rejected", "no_tariff",
    "not_published", "no_master", "no_services", "no_salon_hours",
    "no_workdays", "hidden", "guest_booking_off",
})
