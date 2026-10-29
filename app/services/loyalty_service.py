# app/services/loyalty_service.py
"""Лояльность салона: статус «постоянный клиент», персональная скидка,
именные скидки/промокоды и бонусные баллы.

Скидку клиенту даёт только салон (никакой скидки «от РУМИ» здесь нет).
Единый источник истины для баланса баллов — LoyaltyPointsMovement (журнал),
ClientLoyalty.bonus_points денормализован и обновляется только через
методы этого сервиса, никогда напрямую.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Booking, BookingStatus, Master, Service,
    SalonLoyaltySettings, LoyaltyOffer, ClientLoyalty, LoyaltyPointsMovement,
    LoyaltyStatusSource, LoyaltyPointsMovementType,
)


class LoyaltyError(Exception):
    """Бизнес-ошибка лояльности. message — текст для пользователя, status — HTTP-код."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class LoyaltyService:
    @staticmethod
    async def _get_or_create_client_loyalty(db: AsyncSession, salon_id: int, client_id: int) -> ClientLoyalty:
        row = (await db.execute(
            select(ClientLoyalty).where(ClientLoyalty.salon_id == salon_id, ClientLoyalty.client_id == client_id)
        )).scalar_one_or_none()
        if row:
            return row
        row = ClientLoyalty(salon_id=salon_id, client_id=client_id)
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def get_client_status(db: AsyncSession, salon_id: int, client_id: int) -> dict:
        """Сводка для модалки завершения записи и для страницы салона у клиента."""
        client_loyalty = (await db.execute(
            select(ClientLoyalty).where(ClientLoyalty.salon_id == salon_id, ClientLoyalty.client_id == client_id)
        )).scalar_one_or_none()

        settings = (await db.execute(
            select(SalonLoyaltySettings).where(SalonLoyaltySettings.salon_id == salon_id)
        )).scalar_one_or_none()

        offers_result = await db.execute(
            select(LoyaltyOffer).where(LoyaltyOffer.salon_id == salon_id, LoyaltyOffer.is_active == True)
            .order_by(LoyaltyOffer.created_at.desc())
        )

        return {
            "is_regular_client": bool(client_loyalty and client_loyalty.is_regular_client),
            "regular_client_discount_percent": settings.regular_client_discount_percent if settings else 0,
            "personal_discount_percent": client_loyalty.personal_discount_percent if client_loyalty else None,
            "bonus_points": client_loyalty.bonus_points if client_loyalty else 0,
            "offers": [
                {"id": o.id, "title": o.title, "discount_percent": o.discount_percent, "promo_code": o.promo_code}
                for o in offers_result.scalars().all()
            ],
        }

    @staticmethod
    async def complete_with_discount(
        db: AsyncSession, *, booking: Booking,
        discount_choice: str = "none", promo_code: Optional[str] = None,
        bonus_points_redeemed: int = 0, actor,
    ) -> Booking:
        """Считает и фиксирует финальную цену завершаемой записи с учётом
        выбранной скидки лояльности и списания баллов. Вызывается из
        BookingService.complete_booking — сама запись уже переведена в
        COMPLETED вызывающим кодом."""
        master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one()
        service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one()
        salon_id = master.salon_id

        client_loyalty = await LoyaltyService._get_or_create_client_loyalty(db, salon_id, booking.client_id)

        discount_percent = 0
        loyalty_source: Optional[str] = None

        if discount_choice == "none":
            pass
        elif discount_choice == "regular_client":
            if not client_loyalty.is_regular_client:
                raise LoyaltyError("У клиента нет статуса «постоянный клиент» в этом салоне")
            settings = (await db.execute(
                select(SalonLoyaltySettings).where(SalonLoyaltySettings.salon_id == salon_id)
            )).scalar_one_or_none()
            discount_percent = settings.regular_client_discount_percent if settings else 0
            loyalty_source = "regular_client"
        elif discount_choice == "personal":
            if client_loyalty.personal_discount_percent is None:
                raise LoyaltyError("У клиента нет персональной скидки в этом салоне")
            discount_percent = client_loyalty.personal_discount_percent
            loyalty_source = "personal"
        elif discount_choice == "promo":
            if not promo_code:
                raise LoyaltyError("Укажите промокод")
            offer = (await db.execute(
                select(LoyaltyOffer).where(
                    LoyaltyOffer.salon_id == salon_id,
                    LoyaltyOffer.promo_code == promo_code,
                    LoyaltyOffer.is_active == True,
                )
            )).scalar_one_or_none()
            if not offer:
                raise LoyaltyError("Промокод не найден или неактивен", status=404)
            discount_percent = offer.discount_percent
            loyalty_source = f"promo:{promo_code}"
        else:
            raise LoyaltyError("Неизвестный вариант скидки")

        base_price = service.price
        discounted_price = round(base_price * (100 - discount_percent) / 100)

        bonus_points_redeemed = int(bonus_points_redeemed or 0)
        if bonus_points_redeemed < 0:
            raise LoyaltyError("Количество списываемых баллов не может быть отрицательным")
        if bonus_points_redeemed > client_loyalty.bonus_points:
            raise LoyaltyError(
                f"У клиента только {client_loyalty.bonus_points} баллов, "
                f"нельзя списать {bonus_points_redeemed}"
            )
        if bonus_points_redeemed > discounted_price:
            raise LoyaltyError("Нельзя списать баллов больше, чем стоит услуга после скидки")

        final_price = discounted_price - bonus_points_redeemed

        booking.discount_percent = discount_percent
        booking.loyalty_source = loyalty_source
        booking.bonus_points_redeemed = bonus_points_redeemed
        booking.final_price = final_price

        if bonus_points_redeemed > 0:
            db.add(LoyaltyPointsMovement(
                client_loyalty_id=client_loyalty.id,
                type=LoyaltyPointsMovementType.REDEEMED,
                amount=-bonus_points_redeemed,
                booking_id=booking.id,
                created_by_id=actor.id,
            ))
            client_loyalty.bonus_points -= bonus_points_redeemed

        settings = (await db.execute(
            select(SalonLoyaltySettings).where(SalonLoyaltySettings.salon_id == salon_id)
        )).scalar_one_or_none()
        if settings and settings.bonus_accrual_percent > 0:
            accrued = round(final_price * settings.bonus_accrual_percent / 100)
            if accrued > 0:
                db.add(LoyaltyPointsMovement(
                    client_loyalty_id=client_loyalty.id,
                    type=LoyaltyPointsMovementType.ACCRUAL,
                    amount=accrued,
                    booking_id=booking.id,
                    created_by_id=actor.id,
                    comment="Автоначисление после оплаты",
                ))
                client_loyalty.bonus_points += accrued

        await LoyaltyService._maybe_grant_regular_client_status(db, client_loyalty, salon_id, booking.client_id)

        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def _maybe_grant_regular_client_status(
        db: AsyncSession, client_loyalty: ClientLoyalty, salon_id: int, client_id: int,
    ) -> None:
        """После завершения визита проверяет, не пора ли автоматически
        выдать статус «постоянный клиент» по числу визитов за 12 мес."""
        if client_loyalty.is_regular_client:
            return
        settings = (await db.execute(
            select(SalonLoyaltySettings).where(SalonLoyaltySettings.salon_id == salon_id)
        )).scalar_one_or_none()
        if not settings or not settings.regular_client_visits_threshold:
            return

        master_ids_result = await db.execute(select(Master.id).where(Master.salon_id == salon_id))
        master_ids = [row[0] for row in master_ids_result.all()]
        if not master_ids:
            return

        year_ago = datetime.now() - timedelta(days=365)
        visits = (await db.execute(
            select(func.count(Booking.id)).where(
                Booking.client_id == client_id,
                Booking.master_id.in_(master_ids),
                Booking.status == BookingStatus.COMPLETED,
                Booking.start_time >= year_ago,
            )
        )).scalar() or 0

        if visits >= settings.regular_client_visits_threshold:
            client_loyalty.is_regular_client = True
            client_loyalty.regular_client_source = LoyaltyStatusSource.AUTO

    @staticmethod
    async def _require_salon_client(db: AsyncSession, salon_id: int, client_id: int) -> None:
        """Ручная лояльность — только клиенту этого салона (решение 0017, п. 2).

        Без проверки _get_or_create_client_loyalty заводил строку на любого
        пользователя сервиса. 404, а не 403: существование чужого id
        раскрывать незачем. Автоматический путь (complete_with_discount)
        проверку не проходит намеренно: он работает от записи этого салона.
        """
        from app.services.salon_clients import is_salon_client
        if not await is_salon_client(db, salon_id, client_id):
            raise LoyaltyError("Клиент не найден", status=404)

    @staticmethod
    async def manual_adjust_points(
        db: AsyncSession, *, salon_id: int, client_id: int, amount: int, comment: str, actor,
    ) -> ClientLoyalty:
        """Ручное начисление/списание баллов админом."""
        amount = int(amount)
        if amount == 0:
            raise LoyaltyError("Сумма корректировки не может быть нулевой")

        await LoyaltyService._require_salon_client(db, salon_id, client_id)
        client_loyalty = await LoyaltyService._get_or_create_client_loyalty(db, salon_id, client_id)
        if amount < 0 and abs(amount) > client_loyalty.bonus_points:
            raise LoyaltyError(f"У клиента только {client_loyalty.bonus_points} баллов")

        db.add(LoyaltyPointsMovement(
            client_loyalty_id=client_loyalty.id,
            type=LoyaltyPointsMovementType.MANUAL_ADD if amount > 0 else LoyaltyPointsMovementType.MANUAL_REMOVE,
            amount=amount,
            created_by_id=actor.id,
            comment=comment or None,
        ))
        client_loyalty.bonus_points += amount
        await db.commit()
        await db.refresh(client_loyalty)
        return client_loyalty

    @staticmethod
    async def set_regular_client_status(
        db: AsyncSession, *, salon_id: int, client_id: int, is_regular: bool, actor,
    ) -> ClientLoyalty:
        """Ручное присвоение/снятие статуса «постоянный клиент» админом."""
        await LoyaltyService._require_salon_client(db, salon_id, client_id)
        client_loyalty = await LoyaltyService._get_or_create_client_loyalty(db, salon_id, client_id)
        client_loyalty.is_regular_client = is_regular
        client_loyalty.regular_client_source = LoyaltyStatusSource.MANUAL if is_regular else None
        await db.commit()
        await db.refresh(client_loyalty)
        return client_loyalty

    @staticmethod
    async def set_personal_discount(
        db: AsyncSession, *, salon_id: int, client_id: int, discount_percent: Optional[int], actor,
    ) -> ClientLoyalty:
        """Назначает/снимает персональную скидку конкретному клиенту (None — снять)."""
        if discount_percent is not None and not (0 < discount_percent < 100):
            raise LoyaltyError("Персональная скидка должна быть от 1 до 99%")
        await LoyaltyService._require_salon_client(db, salon_id, client_id)
        client_loyalty = await LoyaltyService._get_or_create_client_loyalty(db, salon_id, client_id)
        client_loyalty.personal_discount_percent = discount_percent
        await db.commit()
        await db.refresh(client_loyalty)
        return client_loyalty
