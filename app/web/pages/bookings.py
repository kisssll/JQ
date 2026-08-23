# app/web/pages/bookings.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from app.models.models import Booking, BookingStatus, Master, Service, Salon, User, Review, ReviewTargetType
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_CALENDAR_BIG,
    ICON_MAP_PIN,
    ICON_PHONE,
    ICON_CALENDAR_BOOKING,
    ICON_USER_BOOKING,
    ICON_BUILDING_BOOKING,
    ICON_MONEY_BOOKING,
    ICON_EDIT_PENCIL,
    ICON_STAR_EMPTY,
    ICON_X,
    ICON_CHECK_SMALL,      # для сообщения об успехе
    ICON_CLOCK,
    ICON_TRASH,
    ICON_STAR_FILLED,

    ICON_SCISSORS_SMALL,
)

async def render_bookings_page(db: AsyncSession, user) -> str:
    """Страница 'Мои записи' для клиента."""
    
    bookings_result = await db.execute(
        select(Booking).where(
            Booking.client_id == user.id
        ).order_by(Booking.start_time.desc())
    )
    bookings = bookings_result.scalars().all()

    now = datetime.now()

    upcoming = []
    completed = []
    cancelled = []

    for b in bookings:
        if b.status == BookingStatus.CANCELLED:
            cancelled.append(b)
        elif b.status == BookingStatus.COMPLETED:
            completed.append(b)
        elif b.start_time > now and b.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            upcoming.append(b)
        else:
            completed.append(b)

    async def render_booking_card(booking):
        master = None
        if booking.master_id:
            master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
        service = None
        if booking.service_id:
            service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
        
        master_name = "Мастер"
        service_name = "Услуга"
        salon_name = "Салон"
        salon_address = ""
        salon_phone = ""
        salon_id = None
        
        if master:
            master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
            master_name = master_user.full_name if master_user else "Мастер"
            if master.salon_id:
                salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
                if salon:
                    salon_name = salon.name
                    salon_address = salon.address or ""
                    salon_phone = salon.phone or ""
                    salon_id = salon.id
        
        if service:
            service_name = service.name

        # NO_SHOW появился вместе с отметкой «Пришёл», но в эту карту его не
        # добавили — такие записи показывали клиенту прочерк в плашке статуса.
        status_label = {
            BookingStatus.PENDING: "Ожидает",
            BookingStatus.CONFIRMED: "Подтверждено",
            BookingStatus.COMPLETED: "Завершено",
            BookingStatus.CANCELLED: "Отменено",
            BookingStatus.NO_SHOW: "Пропущено",
        }.get(booking.status, "—")
        # Статус читается цветом, а не только текстом: до этого все плашки были
        # одинаково розовыми и «Завершено» не отличалось от «Отменено».
        status_tone = {
            BookingStatus.PENDING: "is-pending",
            BookingStatus.CONFIRMED: "is-confirmed",
            BookingStatus.COMPLETED: "is-completed",
            BookingStatus.CANCELLED: "is-cancelled",
            BookingStatus.NO_SHOW: "is-cancelled",
        }.get(booking.status, "")
        
        cancel_btn = ""
        if booking in upcoming and booking.status != BookingStatus.CANCELLED:
            cancel_btn = f'<div class="booking-actions"><button class="btn-outline" style="color:var(--color-danger, #ef4444); border-color:var(--color-danger, #ef4444);" onclick="cancelBooking({booking.id})">{ICON_TRASH} Отменить</button></div>'
        
        date_str = booking.start_time.replace(tzinfo=None).strftime('%d.%m.%Y в %H:%M')
        price_str = f"{booking.final_price or '—'} ₽"
        duration_minutes = int((booking.end_time - booking.start_time).total_seconds() // 60)

        salon_link_html = (
            f'<a href="/salons?highlight={salon_id}" class="booking-salon-link">{salon_name}</a>'
            if salon_id else f'<span class="booking-salon-link booking-salon-link--plain">{salon_name}</span>'
        )
        
        # Проверяем, есть ли уже отзыв на эту запись
        review = None
        review_html = ""
        if booking.status == BookingStatus.COMPLETED:
            review = (await db.execute(
                select(Review).where(Review.booking_id == booking.id)
            )).scalar_one_or_none()
            if review:
                # Используем звёзды из иконок
                stars = f"{ICON_STAR_FILLED}" * review.rating + f"{ICON_STAR_EMPTY}" * (5 - review.rating)
                review_html = f"""
                <div class="booking-review">
                    <div class="booking-review-stars">{stars}</div>
                    <div class="booking-review-text">{review.comment or 'Без комментария'}</div>
                    <button class="btn-outline booking-review-edit-btn" data-booking-id="{booking.id}" data-review-id="{review.id}">
                        {ICON_EDIT_PENCIL} Редактировать отзыв
                    </button>
                </div>
                """
            else:
                review_html = f"""
                <div class="booking-review">
                    <button class="btn-primary booking-review-add-btn" data-booking-id="{booking.id}" data-salon-id="{salon_id}" data-master-id="{master.id if master else ''}">
                        {ICON_EDIT_PENCIL} Оставить отзыв
                    </button>
                </div>
                """
        
        return f"""
        <div class="booking-card" data-booking-id="{booking.id}">
            <div class="booking-header">
                <span class="service-name">{service_name}</span>
                <span class="booking-status {status_tone}">{status_label}</span>
            </div>
            <div class="booking-info-grid">
                <div class="booking-col booking-col-salon">
                    <p class="booking-salon-name"><span class="booking-icon-wrapper">{ICON_BUILDING_BOOKING}</span>{salon_link_html}</p>
                    {f'<p class="booking-address"><span class="booking-icon-wrapper">{ICON_MAP_PIN}</span>{salon_address}</p>' if salon_address else ''}
                    {f'<p class="booking-phone"><span class="booking-icon-wrapper">{ICON_PHONE}</span><span class="label">Телефон:</span> {salon_phone}</p>' if salon_phone else ''}
                </div>
                <div class="booking-col booking-col-service">
                    <p><span class="booking-icon-wrapper">{ICON_USER_BOOKING}</span><span class="label">Мастер:</span> {master_name}</p>
                    <p><span class="booking-icon-wrapper">{ICON_SCISSORS_SMALL}</span>{service_name}</p>
                    <p><span class="booking-icon-wrapper">{ICON_CALENDAR_BOOKING}</span>{date_str}</p>
                    <p><span class="booking-icon-wrapper">{ICON_CLOCK}</span>{duration_minutes} мин</p>
                </div>
                <div class="booking-col booking-col-price">
                    <p class="booking-price"><span class="booking-icon-wrapper">{ICON_MONEY_BOOKING}</span>{price_str}</p>
                </div>
            </div>
            {cancel_btn}
            {review_html}
        </div>
        """

    async def render_category(bookings_list, empty_message, empty_detail, show_salon_button=False):
        if bookings_list:
            cards = ""
            for b in bookings_list:
                cards += await render_booking_card(b)
            return cards
        else:
            button_html = f'<a href="/salons" class="btn-primary">Выбрать салон</a>' if show_salon_button else ''
            return f"""
            <div class="empty-state">
                <div class="empty-icon">{ICON_CALENDAR_BIG}</div>
                <h3>{empty_message}</h3>
                <p>{empty_detail}</p>
                {button_html}
            </div>
            """

    upcoming_html = await render_category(upcoming, "Нет предстоящих записей", "Выберите салон и запишитесь к мастеру — запись появится здесь", show_salon_button=True)
    completed_html = await render_category(completed, "Нет завершённых записей", "Здесь будут отображаться завершённые записи")
    cancelled_html = await render_category(cancelled, "Нет отменённых записей", "Здесь будут отображаться отменённые записи")

    upcoming_count = len(upcoming)
    completed_count = len(completed)
    cancelled_count = len(cancelled)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Мои записи — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("bookings")}
    {render_sidebar("bookings", user)}
    
    <main class="bookings-main">
        <div class="section-container">
            <div class="bookings-header">
                <h1>Мои записи</h1>
                <p>Все ваши записи в салоны красоты</p>
            </div>

            <div class="bookings-tabs" id="bookingsTabs">
                <button class="tab-btn" data-tab="upcoming">Предстоящие <span class="badge">{upcoming_count}</span></button>
                <button class="tab-btn" data-tab="completed">Завершённые <span class="badge">{completed_count}</span></button>
                <button class="tab-btn" data-tab="cancelled">Отменённые <span class="badge">{cancelled_count}</span></button>
            </div>

            <div id="tab-upcoming" class="tab-content">
                {upcoming_html}
            </div>
            <div id="tab-completed" class="tab-content">
                {completed_html}
            </div>
            <div id="tab-cancelled" class="tab-content">
                {cancelled_html}
            </div>
        </div>
        {render_footer(user)}
    </main>

    <!-- Модальное окно для отзыва -->
    <div class="review-modal-overlay" id="reviewModal">
        <div class="review-modal-box">
            <button class="review-modal-close" onclick="closeReviewModal()">{ICON_X}</button>
            <h2 id="reviewModalTitle">Оставить отзыв</h2>
            <form id="reviewForm" enctype="multipart/form-data">
                <input type="hidden" id="reviewBookingId" name="booking_id">
                <input type="hidden" id="reviewSalonId" name="salon_id">
                <input type="hidden" id="reviewMasterId" name="master_id">
                <input type="hidden" id="reviewId" name="review_id">
                <div class="form-group">
                    <label>Оценка</label>
                    <div class="star-rating" id="starRating">
                        <span class="star" data-value="1">{ICON_STAR_EMPTY}</span>
                        <span class="star" data-value="2">{ICON_STAR_EMPTY}</span>
                        <span class="star" data-value="3">{ICON_STAR_EMPTY}</span>
                        <span class="star" data-value="4">{ICON_STAR_EMPTY}</span>
                        <span class="star" data-value="5">{ICON_STAR_EMPTY}</span>
                    </div>
                    <input type="hidden" id="reviewRating" name="rating" value="0">
                </div>
                <div class="form-group">
                    <label for="reviewComment">Комментарий</label>
                    <textarea id="reviewComment" name="comment" rows="3" placeholder="Расскажите о своём опыте..."></textarea>
                </div>
                <div class="form-group">
                    <label for="reviewPhotos">Фото (до 5)</label>
                    <input type="file" id="reviewPhotos" name="files" accept="image/*" multiple>
                </div>
                <button type="submit" class="btn-primary" style="width:100%">Отправить отзыв</button>
            </form>
            <div id="reviewSuccess" style="display:none;text-align:center;padding:1rem;color:#22c55e">
                {ICON_CHECK_SMALL} Отзыв сохранён
            </div>
        </div>
    </div>

    <script src="/static/src/js/bookings.js"></script>
</body>
</html>"""
    return html