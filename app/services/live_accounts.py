"""Кому можно показывать мастера и салон: проверка аккаунта человека за ними.

Карточка мастера и салон живут своими флагами (``is_active``, ``is_deleted``,
``is_hidden``), а аккаунт человека — своим (``users.is_active``). До решения
0016 показ верил одной карточке: человек удалял аккаунт, а его карточка и
салон оставались в каталоге и принимали записи — клиент пришёл бы к тому,
кого нет.

Удаление аккаунта теперь гасит карточку и салон само (app/services/departure.py),
но это проверка второго уровня: условие стоит прямо в выборках, а не в данных.
Тогда старые записи в базе, где аккаунт отключён, а карточка «активна»
(например, человека заблокировал модератор), тоже перестают светиться, и
забытая где-то ветка цепочки не приведёт клиента к пустому креслу.

Два вида на одно правило: выражения SQLAlchemy для ORM-запросов и фрагменты
сырого SQL для каталога, который собран на ``text()``. Держать их нужно рядом —
разойдясь, каталог и страница салона покажут разное.
"""
from sqlalchemy import and_, exists, not_, or_, select
from sqlalchemy.orm import aliased

from app.models.models import Master, Salon, SalonMember, SalonRole, User


def live_master():
    """Карточка мастера активна И аккаунт мастера не отключён."""
    owner = aliased(User)
    return and_(
        Master.is_active == True,  # noqa: E712
        exists(select(owner.id).where(owner.id == Master.user_id,
                                      owner.is_active == True)),  # noqa: E712
    )


def salon_has_live_owner():
    """У салона есть владелец с рабочим аккаунтом.

    Владелец — активное членство с ролью owner. Салоны, где членств-владельцев
    нет вовсе (созданы до появления SalonMember), судим по создателю: нет
    создателя или он активен — салон живой. Иначе условие отрезало бы такие
    салоны целиком, хотя ничего с ними не случилось.
    """
    owner_user = aliased(User)
    creator = aliased(User)
    owner_member = aliased(SalonMember)
    any_member = aliased(SalonMember)
    live_owner = exists(
        select(owner_member.id)
        .join(owner_user, owner_user.id == owner_member.user_id)
        .where(owner_member.salon_id == Salon.id,
               owner_member.role == SalonRole.OWNER,
               owner_member.is_active == True,  # noqa: E712
               owner_user.is_active == True)  # noqa: E712
    )
    any_owner = exists(
        select(any_member.id).where(any_member.salon_id == Salon.id,
                                    any_member.role == SalonRole.OWNER,
                                    any_member.is_active == True)  # noqa: E712
    )
    creator_live = or_(
        Salon.creator_id.is_(None),
        exists(select(creator.id).where(creator.id == Salon.creator_id,
                                        creator.is_active == True)),  # noqa: E712
    )
    return or_(live_owner, and_(not_(any_owner), creator_live))


def live_master_sql(alias: str) -> str:
    """То же, что ``live_master``, для сырого SQL: ``alias`` — псевдоним masters."""
    return (
        f"({alias}.is_active = true AND EXISTS (SELECT 1 FROM users lmu "
        f"WHERE lmu.id = {alias}.user_id AND lmu.is_active = true))"
    )


def salon_has_live_owner_sql(alias: str) -> str:
    """То же, что ``salon_has_live_owner``, для сырого SQL: ``alias`` — псевдоним salons.

    Роль пишется ИМЕНЕМ члена перечисления ('OWNER') — так SQLAlchemy хранит
    Enum в этом проекте (см. moderation_status = 'APPROVED' в каталоге).
    """
    return (
        f"(EXISTS (SELECT 1 FROM salon_members lsm JOIN users lsu ON lsu.id = lsm.user_id "
        f"WHERE lsm.salon_id = {alias}.id AND lsm.role = 'OWNER' AND lsm.is_active = true "
        f"AND lsu.is_active = true) "
        f"OR (NOT EXISTS (SELECT 1 FROM salon_members lsa "
        f"WHERE lsa.salon_id = {alias}.id AND lsa.role = 'OWNER' AND lsa.is_active = true) "
        f"AND ({alias}.creator_id IS NULL OR EXISTS (SELECT 1 FROM users lcu "
        f"WHERE lcu.id = {alias}.creator_id AND lcu.is_active = true))))"
    )


async def salon_is_live(db, salon_id: int) -> bool:
    """Одиночная проверка для мест, где салон уже загружен целиком."""
    return (await db.execute(
        select(Salon.id).where(Salon.id == salon_id, salon_has_live_owner())
    )).scalar_one_or_none() is not None
