# app/web/pages/business/tabs/my_salon.py
from app.web.components.escaping import e
import html
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import (
    Salon, SalonPhoto,
    SalonChain, SalonChainRequest, SalonChainRequestStatus,
)
from app.services.salon_chain_service import pending_requests_for_salon_ids
from app.web.components.yandex_maps import yandex_maps_enabled
from app.web.cities import RUSSIAN_CITIES

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
    ICON_CHECK,
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
        photo_html = f'<img src="{salon.logo_url}" alt="{e(salon.name)}" class="salon-edit-photo" loading="lazy">'
    else:
        photo_html = f'<div class="salon-edit-photo-placeholder">{e(salon.name[0].upper())}</div>'

    static_html = f"""
        <div class="salon-edit-static">
            <div class="salon-edit-photo-wrapper">
                {photo_html}
            </div>
            <div class="salon-edit-info">
                <h2 class="salon-edit-name" id="salonEditNameDisplay">{e(salon.name)}</h2>
                <div class="salon-edit-rating">
                    {ICON_STAR_FILLED}
                    <span>{rating:.1f}</span>
                    <span class="rating-count">({reviews} отзывов)</span>
                </div>
                <p class="salon-edit-address">
                    {ICON_MAP_PIN} <span id="salonEditAddressDisplay">{e(salon.address or 'Адрес не указан')}</span>
                </p>
                <p class="salon-edit-phone">
                    {ICON_PHONE} <span id="salonEditPhoneDisplay">{e(salon.phone or '')}</span>
                </p>
                <p class="salon-edit-desc" id="salonEditDescDisplay">{e(salon.description or '')}</p>
            </div>
        </div>
    """

    def _photo_card(p) -> str:
        is_cover = salon.logo_url == p.url
        border_class = "cover-border" if is_cover else "default-border"
        cover_badge = (
            f'<span class="cover-badge">{ICON_STAR_FILLED} Обложка</span>'
            if is_cover else
            f'''<form method="post" action="/api/v1/upload/salon/{salon.id}/photo/{p.id}/cover" style="margin:0;position:absolute;bottom:0.25rem;left:0.25rem">
                    <button type="submit" title="Показывать это фото на карточке салона в общем списке" class="cover-btn">Сделать обложкой</button>
                </form>'''
        )
        return f'''
        <div class="my-salon-photo-item">
            <img src="{p.url}" alt="" class="{border_class}" loading="lazy">
            <form method="post" action="/api/v1/upload/salon/{salon.id}/photo/{p.id}/delete" data-confirm="Удалить фото?" data-confirm-label="Удалить" style="margin:0;position:absolute;top:0.25rem;right:0.25rem">
                <button type="submit" title="Удалить фото" class="delete-btn">&times;</button>
            </form>
            {cover_badge}
        </div>'''

    photo_cards = "".join(_photo_card(p) for p in photos)

    inputs_html = f"""
        <div class="salon-edit-inputs" style="display:none;">
            <!-- Блок фото салона -->
            <div class="salon-edit-photos-block">
                <div class="salon-edit-photos-label">Фото салона</div>
                <button type="button" id="photoDropZone" data-upload-url="/api/v1/upload/salon/{salon.id}/photo" class="my-salon-dropzone">
                    <p>Перетащите фото сюда или нажмите, чтобы выбрать</p>
                    <p class="hint">Можно несколько сразу · JPG/PNG до 5 МБ · появятся на странице салона</p>
                </button>
                <input type="file" id="photoFileInputMySalon" accept="image/*" multiple style="display:none">
                <div id="photoUploadStatus"></div>
                <div class="my-salon-photos">
                    {photo_cards or '<p style="color:var(--color-muted);margin:0">Пока нет фотографий</p>'}
                </div>
            </div>

            <!-- Поля ввода -->
            <div class="salon-edit-fields" style="margin-top: 1.5rem; border-top: 1px solid var(--color-border); padding-top: 1.5rem;">
                <div class="salon-edit-field">
                    <label>Название</label>
                    <input type="text" id="salonEditNameInput" value="{e(salon.name)}" class="salon-edit-input">
                </div>
                <div class="salon-edit-field">
                    <label>Телефон</label>
                    <input type="tel" id="salonEditPhoneInput" value="{e(salon.phone or '+7')}" class="salon-edit-input phone-input">
                </div>
                <div class="salon-edit-field">
                    <label>Город</label>
                    <select id="salonEditCityInput" class="salon-edit-input custom-select">
                        {"".join(f'<option value="{c}"{" selected" if c == salon.city else ""}>{c}</option>' for c in RUSSIAN_CITIES)}
                    </select>
                </div>
                <div class="salon-edit-field">
                    <label>Адрес</label>
                    <input type="text" id="salonEditAddressInput" value="{e(salon.address or '')}"
                           class="salon-edit-input{' address-geocode' if yandex_maps_enabled() else ''}"
                           {'data-lat-field="salonEditLat" data-lon-field="salonEditLon" data-map-id="salonEditAddressMap" data-confirmed="1" autocomplete="off"' if yandex_maps_enabled() else ''}>
                    {'<p class="my-salon-card-hint" style="margin-top:0.35rem">Если меняете адрес — выберите новый вариант из подсказок, иначе сохранить не получится.</p>' if yandex_maps_enabled() else ''}
                    {'<div id="salonEditAddressMap" style="display:none;height:200px;border-radius:0.75rem;margin-top:0.5rem;overflow:hidden"></div>' if yandex_maps_enabled() else ''}
                    {f'<input type="hidden" id="salonEditLat" value="{salon.latitude}"><input type="hidden" id="salonEditLon" value="{salon.longitude}">' if yandex_maps_enabled() else ''}
                </div>
                <div class="salon-edit-field">
                    <label>Почта салона</label>
                    <input type="email" id="salonEditEmailInput" value="{salon.email or ''}" placeholder="salon@example.com (для реквизитов и уведомлений)" class="salon-edit-input">
                </div>
                <div class="salon-edit-field">
                    <label>Описание</label>
                    <textarea id="salonEditDescInput" class="salon-edit-input salon-edit-textarea">{e(salon.description or '')}</textarea>
                </div>
            </div>
        </div>
    """

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
    """Блок «Видимость и удаление»: скрыть салон (обратимо) / удалить салон (безвозвратно, только создатель)."""
    if salon.is_hidden:
        hide_hint = "Салон скрыт: его не видно в каталоге, поиске и записи. Включите обратно в любой момент."
        hide_btn = f'<button type="button" class="my-salon-btn-primary" id="salonVisibilityBtn" data-salon-id="{salon.id}" data-hidden="1">{ICON_EYE} Показать салон</button>'
    else:
        hide_hint = (
            "Сейчас салон не скрыт — он виден клиентам в каталоге, поиске и доступен для записи. "
            "Если нажмёте «Скрыть салон», он пропадёт из каталога и не будет виден пользователям в общем доступе."
        )
        hide_btn = f'<button type="button" class="my-salon-btn-outline" id="salonVisibilityBtn" data-salon-id="{salon.id}" data-hidden="0">{ICON_EYE} Скрыть салон</button>'

    delete_block = ""
    if is_creator:
        delete_block = f"""
        <div style="margin-top:1.5rem;padding-top:1.5rem;border-top:1px solid var(--color-border)">
            <h3 style="margin:0 0 0.5rem;font-size:1rem">Удалить салон</h3>
            <p class="my-salon-card-hint">
                В таком случае салон уйдёт из каталога и записи безвозвратно (для вас — без возможности
                восстановить самостоятельно). Брони, отзывы и история клиентов сохранятся в панели бизнеса —
                салон можно будет отслеживать, но записаться в него или увидеть его в каталоге больше никто
                не сможет, и вернуть салон будет нельзя.
            </p>
            <button type="button" class="my-salon-btn-outline" id="salonDeleteBtn" data-salon-id="{salon.id}"
                    style="color:#dc2626;border-color:#dc2626">
                {ICON_TRASH} Удалить салон
            </button>
        </div>
        """

    return f"""
    <div class="my-salon-card">
        <h2 class="my-salon-card-title">Видимость и удаление</h2>
        <h3 style="margin:0 0 0.5rem;font-size:1rem">Скрыть салон</h3>
        <p class="my-salon-card-hint" id="salonVisibilityHint">{hide_hint}</p>
        {hide_btn}
        {delete_block}
    </div>
    """


async def _render_chain_section(db: AsyncSession, salon: Salon, is_creator: bool) -> str:
    """Блок «Сеть салонов»: текущая сеть (если есть) + поиск партнёра и запрос
    на объединение + входящие/исходящие запросы на решение. Только для
    создателя — это решение о бренде салона, не операционное право."""
    if not is_creator:
        return ""

    chain_block = ""
    if salon.chain_id is not None:
        chain = (await db.execute(select(SalonChain).where(SalonChain.id == salon.chain_id))).scalar_one_or_none()
        siblings = (await db.execute(
            select(Salon).where(Salon.chain_id == salon.chain_id, Salon.id != salon.id).order_by(Salon.name)
        )).scalars().all()
        siblings_html = "".join(
            f'<li>{ICON_MAP_PIN} <a href="/salons/{s.id}" target="_blank" class="text-link">{e(s.name)}</a> — {e(s.address or "адрес не указан")}</li>'
            for s in siblings
        ) or '<li class="text-muted">Пока больше никого нет</li>'
        chain_block = f"""
        <p class="my-salon-card-hint">Салон в сети «{chain.name if chain else "?"}» вместе с {len(siblings)} другими:</p>
        <ul class="chain-siblings-list">{siblings_html}</ul>
        <button type="button" class="my-salon-btn-outline" id="chainLeaveBtn" data-salon-id="{salon.id}"
                style="color:#dc2626;border-color:#dc2626;margin-top:0.75rem">
            Покинуть сеть
        </button>
        """
    else:
        chain_block = f"""
        <p class="my-salon-card-hint">
            Салон пока не в сети. Найдите салон-партнёра и отправьте запрос на объединение —
            сработает, только когда согласятся владельцы всех затронутых салонов.
        </p>
        <div class="chain-search-box">
            <input type="text" id="chainSearchInput" placeholder="Начните вводить название салона…" autocomplete="off">
            <div id="chainSearchResults" class="chain-search-results"></div>
        </div>
        <button type="button" class="my-salon-btn-primary" id="chainSendRequestBtn" data-salon-id="{salon.id}" disabled>
            {ICON_PLUS} Отправить запрос на объединение
        </button>
        """

    outgoing = (await db.execute(
        select(SalonChainRequest).where(
            SalonChainRequest.from_salon_id == salon.id,
            SalonChainRequest.status == SalonChainRequestStatus.PENDING,
        )
    )).scalars().all()
    outgoing_html = ""
    if outgoing:
        rows = ""
        for req in outgoing:
            to_salon = (await db.execute(select(Salon).where(Salon.id == req.to_salon_id))).scalar_one_or_none()
            rows += f"""
            <li>
                Ждём решения от «{to_salon.name if to_salon else "?"}» ({len(req.salon_ids)} салон(ов) затронуто)
                <button type="button" class="chain-cancel-btn" data-request-id="{req.id}">Отменить</button>
            </li>"""
        outgoing_html = f"""
        <h3 style="margin:1.5rem 0 0.5rem;font-size:1rem">Исходящие запросы</h3>
        <ul class="chain-requests-list">{rows}</ul>
        """

    incoming = await pending_requests_for_salon_ids(db, [salon.id])
    incoming_html = ""
    if incoming:
        rows = ""
        for req in incoming:
            from_salon = (await db.execute(select(Salon).where(Salon.id == req.from_salon_id))).scalar_one_or_none()
            rows += f"""
            <li>
                «{from_salon.name if from_salon else "?"}» предлагает объединиться в сеть
                ({len(req.salon_ids)} салон(ов) затронуто)
                <button type="button" class="chain-vote-btn chain-vote-accept" data-request-id="{req.id}" data-salon-id="{salon.id}" data-approve="1">{ICON_CHECK} Согласиться</button>
                <button type="button" class="chain-vote-btn chain-vote-reject" data-request-id="{req.id}" data-salon-id="{salon.id}" data-approve="0">{ICON_X} Отклонить</button>
            </li>"""
        incoming_html = f"""
        <h3 style="margin:1.5rem 0 0.5rem;font-size:1rem">Входящие запросы — нужно ваше решение</h3>
        <ul class="chain-requests-list">{rows}</ul>
        """

    return f"""
    <div class="my-salon-card">
        <h2 class="my-salon-card-title">Сеть салонов</h2>
        {chain_block}
        {outgoing_html}
        {incoming_html}
    </div>
    """


async def render_my_salon_tab(
    db: AsyncSession, salon: Salon, user=None, query_params=None,
    can_manage_salon: bool = False, is_creator: bool = False,
) -> str:
    """Вкладка «Редактировать салон» для бизнес-панели."""
    query_params = query_params or {}

    photos = (
        await db.execute(select(SalonPhoto).where(SalonPhoto.salon_id == salon.id).order_by(SalonPhoto.id))
    ).scalars().all()

    chain_section_html = await _render_chain_section(db, salon, is_creator)

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
            <input type="time" id="wh-start-{key}" class="custom-date" value="{start_val}" {disabled}>
            <span class="time-sep">—</span>
            <input type="time" id="wh-end-{key}" class="custom-date" value="{end_val}" {disabled}>
        </div>"""

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
                    <h1>{e(salon.name)}</h1>
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
                    <img src="/book/{salon.id}/qr" alt="QR-код записи" loading="lazy" style="width:150px;height:150px;border:1px solid var(--color-border,#eee);border-radius:8px">
                    <a href="/book/{salon.id}/qr" download="rumi-qr-{salon.id}.png" class="my-salon-btn-outline">Скачать QR</a>
                </div>
            </div>

            {chain_section_html}

            {_render_danger_zone(salon, can_manage_salon, is_creator) if can_manage_salon else ""}

        </div>
    </div>

    <script>
        window.salonId = {salon.id};
    </script>
    """
    return html_content