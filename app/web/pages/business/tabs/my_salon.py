# app/web/pages/business/tabs/my_salon.py
import html
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Salon, Promotion, SalonLoyaltySettings, LoyaltyOffer, User as UserModel, SalonPhoto

DAY_KEYS_RU = [
    ("mon", "Понедельник"), ("tue", "Вторник"), ("wed", "Среда"), ("thu", "Четверг"),
    ("fri", "Пятница"), ("sat", "Суббота"), ("sun", "Воскресенье"),
]
from app.web.components.icons import (
    ICON_TRASH,
    ICON_SAVE,
    ICON_PLUS,
    ICON_COPY,
    ICON_EDIT,
    ICON_MAP_PIN,
    ICON_PHONE,
    ICON_STAR_FILLED,
    ICON_X,
    ICON_EYE,
)

_ERROR_MESSAGES = {
    "bad_phone": "Не удалось распознать телефон мастера. Формат: +7 999 123-45-67 или 8 999 123-45-67.",
    "master_exists": "У этого пользователя уже есть профиль мастера.",
}


def _render_edit_card(salon: Salon, photos: list) -> str:
    """Карточка салона с режимом редактирования и галереей фото."""
    rating = salon.rating or 0.0
    reviews = salon.reviews_count or 0

    if salon.logo_url:
        photo_html = f'<img src="{salon.logo_url}" alt="{salon.name}" class="salon-edit-photo">'
    else:
        photo_html = f'<div class="salon-edit-photo-placeholder">{salon.name[0].upper()}</div>'

    # Статическая часть (видна всегда, кроме режима редактирования)
    static_html = f"""
        <div class="salon-edit-static">
            <div class="salon-edit-photo-wrapper">
                {photo_html}
            </div>
            <div class="salon-edit-info">
                <h2 class="salon-edit-name" id="salonEditNameDisplay">{salon.name}</h2>
                <div class="salon-edit-rating">
                    {ICON_STAR_FILLED}
                    <span>{rating:.1f}</span>
                    <span class="rating-count">({reviews} отзывов)</span>
                </div>
                <p class="salon-edit-address">
                    {ICON_MAP_PIN} <span id="salonEditAddressDisplay">{salon.address or 'Адрес не указан'}</span>
                </p>
                <p class="salon-edit-phone">
                    {ICON_PHONE} <span id="salonEditPhoneDisplay">{salon.phone or ''}</span>
                </p>
                <p class="salon-edit-desc" id="salonEditDescDisplay">{salon.description or ''}</p>
            </div>
        </div>
    """

    # Блок галереи
    def _photo_card(p) -> str:
        is_cover = salon.logo_url == p.url
        border_class = "cover-border" if is_cover else "default-border"
        cover_badge = (
            f'<span class="cover-badge">★ Обложка</span>'
            if is_cover else
            f'''<form method="post" action="/api/v1/upload/salon/{salon.id}/photo/{p.id}/cover" style="margin:0;position:absolute;bottom:0.25rem;left:0.25rem">
                    <button type="submit" title="Показывать это фото на карточке салона в общем списке" class="cover-btn">Сделать обложкой</button>
                </form>'''
        )
        return f'''
        <div class="my-salon-photo-item">
            <img src="{p.url}" alt="" class="{border_class}">
            <form method="post" action="/api/v1/upload/salon/{salon.id}/photo/{p.id}/delete" style="margin:0;position:absolute;top:0.25rem;right:0.25rem">
                <button type="submit" title="Удалить фото" onclick="return confirm('Удалить фото?')" class="delete-btn">&times;</button>
            </form>
            {cover_badge}
        </div>'''

    photo_cards = "".join(_photo_card(p) for p in photos)

    # Редактируемая часть
    inputs_html = f"""
        <div class="salon-edit-inputs" style="display:none;">
            <!-- Блок фото салона -->
            <div class="salon-edit-photos-block">
                <div class="salon-edit-photos-label">Фото салона</div>
                <div id="photoDropZone" data-upload-url="/api/v1/upload/salon/{salon.id}/photo" class="my-salon-dropzone">
                    <p>Перетащите фото сюда или нажмите, чтобы выбрать</p>
                    <p class="hint">Можно несколько сразу · JPG/PNG до 5 МБ · появятся на странице салона</p>
                </div>
                <input type="file" id="photoFileInput" accept="image/*" multiple style="display:none">
                <div id="photoUploadStatus"></div>
                <div class="my-salon-photos">
                    {photo_cards or '<p style="color:var(--color-muted);margin:0">Пока нет фотографий</p>'}
                </div>
            </div>

            <!-- Поля ввода -->
            <div class="salon-edit-fields" style="margin-top: 1.5rem; border-top: 1px solid var(--color-border); padding-top: 1.5rem;">
                <div class="salon-edit-field">
                    <label>Название</label>
                    <input type="text" id="salonEditNameInput" value="{salon.name}" class="salon-edit-input">
                </div>
                <div class="salon-edit-field">
                    <label>Телефон</label>
                    <input type="tel" id="salonEditPhoneInput" value="{salon.phone or ''}" class="salon-edit-input phone-input">
                </div>
                <div class="salon-edit-field">
                    <label>Адрес</label>
                    <input type="text" id="salonEditAddressInput" value="{salon.address or ''}" class="salon-edit-input">
                </div>
                <div class="salon-edit-field">
                    <label>Описание</label>
                    <textarea id="salonEditDescInput" class="salon-edit-input salon-edit-textarea">{salon.description or ''}</textarea>
                </div>
            </div>
        </div>
    """

    # Скрипт с начальными данными для JS (передаём массив объектов с id и url)
    photos_data = [{"id": p.id, "url": p.url} for p in photos]
    initial_logo = salon.logo_url or ''
    import json
    init_script = f"""
    <script>
        window.initialPhotos = {json.dumps(photos_data)};
        window.initialLogo = {json.dumps(initial_logo)};
    </script>
    """

    return f"""
    <div class="salon-edit-card" id="salonEditCard">
        {static_html}
        {inputs_html}
        <div class="salon-edit-toggle" id="salonEditToggleContainer">
            <button class="btn-outline salon-edit-toggle-btn" id="salonEditToggleBtn">
                {ICON_EDIT} Редактировать
            </button>
        </div>
        {init_script}
    </div>
    """


def _render_danger_zone(salon: Salon, can_manage_salon: bool, is_creator: bool) -> str:
    """Блок «Опасная зона»: скрыть салон (обратимо) / удалить салон (безвозвратно, только создатель)."""
    if salon.is_hidden:
        hide_hint = "Салон скрыт: его не видно в каталоге, поиске и записи. Включите обратно в любой момент."
        hide_btn = f'<button type="button" class="my-salon-btn-primary" id="salonVisibilityBtn" data-salon-id="{salon.id}" data-hidden="1">{ICON_EYE} Показать салон</button>'
    else:
        hide_hint = "Салон скрыт не будет — он виден клиентам в каталоге, поиске и доступен для записи."
        hide_btn = f'<button type="button" class="my-salon-btn-outline" id="salonVisibilityBtn" data-salon-id="{salon.id}" data-hidden="0">{ICON_EYE} Скрыть салон</button>'

    delete_block = ""
    if is_creator:
        delete_block = f"""
        <div style="margin-top:1.5rem;padding-top:1.5rem;border-top:1px solid var(--color-border)">
            <h3 style="margin:0 0 0.5rem;font-size:1rem">Удалить салон</h3>
            <p class="my-salon-card-hint">
                Салон уйдёт из каталога и записи безвозвратно (для вас — без возможности восстановить самостоятельно).
                Брони, отзывы и история клиентов сохранятся.
            </p>
            <button type="button" class="my-salon-btn-outline" id="salonDeleteBtn" data-salon-id="{salon.id}"
                    style="color:#dc2626;border-color:#dc2626">
                {ICON_TRASH} Удалить салон
            </button>
        </div>
        """

    return f"""
    <div class="my-salon-card">
        <h2 class="my-salon-card-title">Опасная зона</h2>
        <h3 style="margin:0 0 0.5rem;font-size:1rem">Скрыть салон</h3>
        <p class="my-salon-card-hint" id="salonVisibilityHint">{hide_hint}</p>
        {hide_btn}
        {delete_block}
    </div>
    """


async def render_my_salon_tab(
    db: AsyncSession, salon: Salon, user=None, query_params=None,
    can_manage_salon: bool = False, is_creator: bool = False,
) -> str:
    """Вкладка «Редактировать салон» для бизнес-панели."""
    query_params = query_params or {}

    # Загружаем фото галереи (нужны для карточки)
    photos = (
        await db.execute(select(SalonPhoto).where(SalonPhoto.salon_id == salon.id).order_by(SalonPhoto.id))
    ).scalars().all()

    error_banner = ""
    error_code = query_params.get("error")
    if error_code:
        message = _ERROR_MESSAGES.get(error_code, "Что-то пошло не так, попробуйте ещё раз.")
        error_banner = (
            '<div class="alert error">'
            f'{message}</div>'
        )

    success_banner = ""
    temp_pw = query_params.get("temp_pw")
    if temp_pw:
        safe_temp_pw = html.escape(temp_pw, quote=True)
        success_banner = (
            '<div class="alert success">'
            f'Мастер добавлен. Временный пароль (передайте его мастеру, он больше нигде не отобразится): '
            f'<code class="temp-pw">{safe_temp_pw}</code>'
            '</div>'
        )
    elif query_params.get("added"):
        success_banner = (
            '<div class="alert success">Мастер добавлен.</div>'
        )

    # Акции
    promos_result = await db.execute(select(Promotion).where(Promotion.salon_id == salon.id))
    promotions = promos_result.scalars().all()

    # Лояльность
    loyalty_settings = (await db.execute(
        select(SalonLoyaltySettings).where(SalonLoyaltySettings.salon_id == salon.id)
    )).scalar_one_or_none()
    loyalty_offers_result = await db.execute(
        select(LoyaltyOffer).where(LoyaltyOffer.salon_id == salon.id).order_by(LoyaltyOffer.created_at.desc())
    )
    loyalty_offers = loyalty_offers_result.scalars().all()

    loyalty_offers_rows = ""
    for o in loyalty_offers:
        code_str = o.promo_code or "—"
        loyalty_offers_rows += f"""
        <tr>
            <td><strong>{o.title}</strong></td>
            <td>{o.discount_percent}%</td>
            <td><code>{code_str}</code></td>
            <td>
                <button onclick="deleteLoyaltyOffer({o.id}, '{o.title}')" class="delete-btn-icon">{ICON_TRASH}</button>
            </td>
        </tr>
        """

    # Часы работы
    parsed_hours = {}
    if salon.working_hours:
        try:
            parsed_hours = json.loads(salon.working_hours)
        except (ValueError, TypeError):
            parsed_hours = {}

    hours_rows = ""
    for key, label in DAY_KEYS_RU:
        raw = (parsed_hours.get(key) or "").strip()
        is_closed = raw in ("closed", "выходной", "day off")
        start_val, end_val = "10:00", "20:00"
        if raw and not is_closed and "-" in raw:
            parts = raw.split("-")
            if len(parts) == 2:
                start_val, end_val = parts[0].strip(), parts[1].strip()
        checked = "checked" if is_closed else ""
        disabled = "disabled" if is_closed else ""
        hours_rows += f"""
        <div class="my-salon-hours-row">
            <span class="day-label">{label}</span>
            <label class="closed-label">
                <input type="checkbox" class="wh-closed" data-day="{key}" {checked} onchange="toggleDayClosed('{key}', this.checked)"> Выходной
            </label>
            <input type="time" id="wh-start-{key}" value="{start_val}" {disabled}>
            <span class="time-sep">—</span>
            <input type="time" id="wh-end-{key}" value="{end_val}" {disabled}>
        </div>"""

    # Акции (таблица)
    promos_rows = ""
    for p in promotions:
        promos_rows += f"""
        <tr>
            <td><strong>{p.title}</strong></td>
            <td>{p.tag}</td>
            <td>
                <button onclick="deletePromo({p.id}, '{p.title}')" class="delete-btn-icon">{ICON_TRASH}</button>
            </td>
        </tr>
        """

    # Подключаем иконки в глобальные переменные JS
    icon_script = f"""
    <script>
        window.ICON_EDIT = `{ICON_EDIT}`;
        window.ICON_EYE = `{ICON_EYE}`;
        window.ICON_SAVE = `{ICON_SAVE}`;
        window.ICON_X = `{ICON_X}`;
    </script>
    """

    html_content = f"""
    <div id="tab-edit" class="tab-content">
        {icon_script}
        <div class="my-salon-tab">
            <!-- Заголовок вкладки -->
            <div class="my-salon-header">
                <div>
                    <h1>{salon.name}</h1>
                    <p>Редактирование карточки салона</p>
                </div>
            </div>

            {error_banner}
            {success_banner}

            <!-- Карточка салона с редактированием -->
            <div class="my-salon-card">
                <h2 class="my-salon-card-title">Основная информация</h2>
                {_render_edit_card(salon, photos)}
            </div>

            <!-- Часы работы -->
            <div class="my-salon-card">
                <h2 class="my-salon-card-title">Часы работы</h2>
                <p class="my-salon-card-hint">
                    Без часов работы расписание пустое и клиенты не могут записаться — заполните хотя бы будни.
                </p>
                <div class="hours-container">
                    {hours_rows}
                </div>
                <div class="hours-actions">
                    <button type="button" class="my-salon-btn-primary" onclick="saveWorkingHours({salon.id})">{ICON_SAVE} Сохранить часы работы</button>
                    <button type="button" class="my-salon-btn-outline" onclick="copyMondayToWeekdays()">{ICON_COPY} Скопировать понедельник на пн–пт</button>
                </div>
            </div>

            <!-- Запись без регистрации -->
            <div class="my-salon-card">
                <h2 class="my-salon-card-title">Запись без регистрации</h2>
                <p class="my-salon-card-hint">Клиенты записываются по ссылке или QR без регистрации; заявка приходит вам на подтверждение.</p>
                <label style="display:block;margin:0.5rem 0">
                    <input type="checkbox" id="guestToggle" data-salon-id="{salon.id}" {"checked" if salon.guest_booking_enabled else ""}>
                    Принимать записи без регистрации
                </label>
                <p style="margin:0.5rem 0;display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap">
                    Ссылка: <a href="/book/{salon.id}" target="_blank" class="text-link">…/book/{salon.id}</a>
                    <button type="button" class="my-salon-btn-outline" id="guestCopyLink" data-salon-id="{salon.id}" style="padding:0.2rem 0.7rem">Копировать</button>
                    <span id="guestCopyMsg" style="color:var(--color-success,#27ae60)"></span>
                </p>
                <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
                    <img src="/book/{salon.id}/qr" alt="QR-код записи" style="width:150px;height:150px;border:1px solid var(--color-border,#eee);border-radius:8px">
                    <a href="/book/{salon.id}/qr" download="rumi-qr-{salon.id}.png" class="my-salon-btn-outline">Скачать QR</a>
                </div>
            </div>

            <!-- Акции -->
            <div class="my-salon-card">
                <div class="my-salon-card-header">
                    <h2 class="my-salon-card-title" style="margin:0;">Акции</h2>
                    <button class="my-salon-btn-primary" onclick="document.getElementById('addPromoModal').classList.add('active')">
                        {ICON_PLUS} Добавить акцию
                    </button>
                </div>
                <div class="table-wrap">
                    <table class="my-salon-table">
                        <thead>
                            <tr>
                                <th>Название</th>
                                <th>Тег</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {promos_rows or '<tr><td colspan="3" class="empty-state">Пока нет акций</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Лояльность -->
            <div class="my-salon-card">
                <h2 class="my-salon-card-title">Лояльность</h2>
                <p class="my-salon-card-hint">
                    Скидку клиенту даёт только ваш салон — настройте её сами. Мастер такие скидки не применяет,
                    это делает администратор при завершении записи в «Расписании».
                </p>

                <div class="my-salon-grid-2">
                    <div class="loyalty-field">
                        <label for="loyaltyRegularPercent">Скидка «постоянному клиенту», %</label>
                        <input type="number" id="loyaltyRegularPercent" min="0" max="99" value="{loyalty_settings.regular_client_discount_percent if loyalty_settings else 0}">
                    </div>
                    <div class="loyalty-field">
                        <label for="loyaltyVisitsThreshold">Визитов за год для авто-статуса</label>
                        <input type="number" id="loyaltyVisitsThreshold" min="1" placeholder="Не задано — только вручную" value="{loyalty_settings.regular_client_visits_threshold if loyalty_settings and loyalty_settings.regular_client_visits_threshold else ''}">
                    </div>
                </div>
                <div class="loyalty-field full-width">
                    <label for="loyaltyBonusAccrual">Автоначисление баллов после оплаты, % от чека</label>
                    <input type="number" id="loyaltyBonusAccrual" min="0" max="99" step="0.1" placeholder="0 — выключено" value="{loyalty_settings.bonus_accrual_percent if loyalty_settings else 0}">
                </div>
                <button type="button" class="my-salon-btn-primary" onclick="saveLoyaltySettings({salon.id})">{ICON_SAVE} Сохранить настройки лояльности</button>

                <div class="loyalty-offers-header">
                    <h3>Именные скидки и промокоды</h3>
                    <button class="my-salon-btn-primary" onclick="document.getElementById('addLoyaltyOfferModal').classList.add('active')">
                        {ICON_PLUS} Добавить
                    </button>
                </div>
                <div class="table-wrap">
                    <table class="my-salon-table">
                        <thead>
                            <tr>
                                <th>Название</th>
                                <th>Скидка</th>
                                <th>Промокод</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {loyalty_offers_rows or '<tr><td colspan="4" class="empty-state">Пока нет именных скидок</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>

            {_render_danger_zone(salon, can_manage_salon, is_creator) if can_manage_salon else ""}

            <!-- Модальное окно: Добавить акцию -->
            <div class="my-salon-modal-overlay" id="addPromoModal">
                <div class="my-salon-modal-box">
                    <button class="my-salon-modal-close" onclick="document.getElementById('addPromoModal').classList.remove('active')">&times;</button>
                    <h2>Добавить акцию</h2>
                    <form action="/api/v1/business/my-salon/promotions/web" method="post">
                        <input type="hidden" name="salon_id" value="{salon.id}">
                        <div class="my-salon-form-group">
                            <label for="promoTitle">Название *</label>
                            <input type="text" id="promoTitle" name="title" required placeholder="Например: Скидка 20%">
                        </div>
                        <div class="my-salon-form-group">
                            <label for="promoDesc">Описание</label>
                            <textarea id="promoDesc" name="description" rows="2" placeholder="Условия акции..."></textarea>
                        </div>
                        <div class="my-salon-form-group">
                            <label for="promoTag">Тег *</label>
                            <input type="text" id="promoTag" name="tag" required placeholder="Новичкам, Выгода, Подарок...">
                        </div>
                        <button type="submit" class="my-salon-btn-primary" style="width:100%">Добавить акцию</button>
                    </form>
                </div>
            </div>

            <!-- Модальное окно: Добавить именную скидку/промокод -->
            <div class="my-salon-modal-overlay" id="addLoyaltyOfferModal">
                <div class="my-salon-modal-box">
                    <button class="my-salon-modal-close" onclick="document.getElementById('addLoyaltyOfferModal').classList.remove('active')">&times;</button>
                    <h2>Добавить скидку</h2>
                    <div class="my-salon-form-group">
                        <label for="loyaltyOfferTitle">Название *</label>
                        <input type="text" id="loyaltyOfferTitle" required placeholder="Например: День рождения">
                    </div>
                    <div class="my-salon-form-group">
                        <label for="loyaltyOfferPercent">Скидка, % *</label>
                        <input type="number" id="loyaltyOfferPercent" min="1" max="99" required>
                    </div>
                    <div class="my-salon-form-group">
                        <label for="loyaltyOfferCode">Промокод</label>
                        <input type="text" id="loyaltyOfferCode" placeholder="Необязательно, например BDAY15">
                    </div>
                    <button type="button" class="my-salon-btn-primary" style="width:100%" onclick="addLoyaltyOffer({salon.id})">Добавить</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        window.salonId = {salon.id};
    </script>
    """
    return html_content