# app/web/pages/business/tabs/services.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.models import Service, Master, User as UserModel
from app.web.components.icons import ICON_EDIT, ICON_TRASH, ICON_CHEVRON_DOWN, ICON_CHEVRON_UP, ICON_FILTER


async def render_services_tab(
    db: AsyncSession,
    salon,
    masters,
    can_manage: bool = False,
    filter_master_id: int = None,
    filter_service_name: str = None,
) -> str:
    """Вкладка Услуги — управление услугами мастеров."""

    master_ids = [m.id for m in masters]

    # Базовый запрос
    query = (
        select(Service, Master)
        .join(Master, Service.master_id == Master.id)
        .where(
            Service.master_id.in_(master_ids), Service.is_active == True,
            Service.is_model_practice == False,  # noqa: E712
        )
    )

    # Применяем фильтры
    if filter_master_id:
        query = query.where(Service.master_id == filter_master_id)
    if filter_service_name:
        query = query.where(Service.name.ilike(f'%{filter_service_name}%'))

    query = query.order_by(Master.id, Service.price)
    services_result = await db.execute(query)
    services_data = services_result.all()

    total_services = len(services_data)

    # --- Десктопная таблица ---
    services_rows = ""
    for service, master in services_data:
        user_result = await db.execute(select(UserModel).where(UserModel.id == master.user_id))
        master_user = user_result.scalar_one_or_none()
        master_name = master_user.full_name if master_user else "—"

        actions_cell = ""
        if can_manage:
            name_js = service.name.replace("'", "\\'")
            desc_js = service.description.replace("'", "\\'") if service.description else ''
            actions_cell = f"""
            <td class="services-actions-cell">
                <button class="services-edit-btn" onclick="openEditModal({service.id}, '{name_js}', {service.price}, {service.duration_minutes}, '{desc_js}', {service.master_id})" title="Редактировать">
                    {ICON_EDIT}
                </button>
                <form method="post" action="/api/v1/services/{service.id}/delete" style="display:inline-block; margin:0;">
                    <button type="submit" class="services-delete-btn" title="Удалить" onclick="return confirm('Удалить услугу «{name_js}»?')">
                        {ICON_TRASH}
                    </button>
                </form>
            </td>
            """

        services_rows += f"""
        <tr>
            <td><strong>{service.name}</strong></td>
            <td>{master_name}</td>
            <td>{service.duration_minutes} мин</td>
            <td><strong>{service.price:,} ₽</strong></td>
            <td class="services-desc">{service.description or '—'}</td>
            {actions_cell}
        </tr>"""

    if not services_rows:
        services_rows = '<tr><td colspan="6" class="services-empty">Пока нет услуг</td></tr>'

    # --- Мобильные карточки ---
    cards_html = ""
    for service, master in services_data:
        user_result = await db.execute(select(UserModel).where(UserModel.id == master.user_id))
        master_user = user_result.scalar_one_or_none()
        master_name = master_user.full_name if master_user else "—"

        actions = ""
        if can_manage:
            name_js = service.name.replace("'", "\\'")
            desc_js = service.description.replace("'", "\\'") if service.description else ''
            actions = f"""
            <button class="services-edit-btn" onclick="openEditModal({service.id}, '{name_js}', {service.price}, {service.duration_minutes}, '{desc_js}', {service.master_id})" title="Редактировать">
                {ICON_EDIT}
            </button>
            <form method="post" action="/api/v1/services/{service.id}/delete" style="display:inline-block; margin:0;">
                <button type="submit" class="services-delete-btn" title="Удалить" onclick="return confirm('Удалить услугу «{name_js}»?')">
                    {ICON_TRASH}
                </button>
            </form>
            """

        cards_html += f"""
        <div class="service-card" data-service-id="{service.id}">
            <div class="service-card-header" onclick="toggleServiceCard(this)">
                <div class="service-card-main">
                    <div class="service-card-top">
                        <span class="service-card-name">{service.name}</span>
                        <span class="service-card-price">{service.price:,} ₽</span>
                    </div>
                    <div class="service-card-bottom">
                        <span class="service-card-master">{master_name}</span>
                        <span class="service-card-chevron">{ICON_CHEVRON_DOWN}</span>
                    </div>
                </div>
            </div>
            <div class="service-card-body" style="display:none;">
                <div class="service-card-row"><span class="service-card-label">Длительность:</span> {service.duration_minutes} мин</div>
                <div class="service-card-row"><span class="service-card-label">Описание:</span> {service.description or '—'}</div>
                {f'<div class="service-card-actions">{actions}</div>' if can_manage else ''}
            </div>
        </div>"""

    if not cards_html:
        cards_html = '<div class="services-empty">Пока нет услуг</div>'

    # --- Фильтры ---
    master_options = ""
    for m in masters:
        user_result = await db.execute(select(UserModel).where(UserModel.id == m.user_id))
        master_user = user_result.scalar_one_or_none()
        master_name = master_user.full_name if master_user else "—"
        selected = " selected" if filter_master_id == m.id else ""
        master_options += f'<option value="{m.id}"{selected}>{master_name} — {m.specialization}</option>'

    filters_form = f"""
    <form method="get" action="/business/dashboard" class="services-filters">
        <input type="hidden" name="salon_id" value="{salon.id}">
        <input type="hidden" name="tab" value="services">

        <div class="filter-group">
            <label for="service_search">Поиск</label>
            <input type="text" id="service_search" name="service_search" placeholder="Название услуги..." value="{filter_service_name or ''}">
        </div>
        <div class="filter-group">
            <label for="service_master">Мастер</label>
            <select id="service_master" name="service_master" class="custom-select">
                <option value="">Все мастера</option>
                {master_options}
            </select>
        </div>
        <button type="submit" class="btn-outline services-apply-btn">{ICON_FILTER} Применить</button>
    </form>
    """

    # --- Аккордеон для мобильных фильтров ---
    filters_mobile = f"""
    <div class="services-filters-mobile">
        <button class="services-filters-toggle" onclick="toggleFiltersMobile()">
            {ICON_FILTER} Фильтры <span class="filters-toggle-chevron">{ICON_CHEVRON_DOWN}</span>
        </button>
        <div class="services-filters-collapse" style="display:none;">
            {filters_form}
        </div>
    </div>
    """

    # Кнопка добавления (только если есть права)
    add_btn = ""
    if can_manage:
        add_btn = f'''
        <button class="services-add-btn" id="servicesAddBtn">
            + Добавить услугу
        </button>
        '''

    # Заголовок с количеством услуг и кнопкой
    header_html = f"""
    <div class="services-header">
        <div class="services-stats">
            <span class="services-count">{total_services}</span>
            <span class="services-label">Всего услуг</span>
        </div>
        {add_btn}
    </div>
    """

    # Таблица (десктоп)
    table_html = f"""
    <div class="services-table-desktop">
        <div class="services-table-wrap">
            <table class="services-table">
                <thead>
                    <tr>
                        <th>Услуга</th>
                        <th>Мастер</th>
                        <th>Длительность</th>
                        <th>Цена</th>
                        <th>Описание</th>
                        {f'<th class="services-actions-header">Действия</th>' if can_manage else ''}
                    </tr>
                </thead>
                <tbody>
                    {services_rows}
                </tbody>
            </table>
        </div>
    </div>
    """

    # Модальное окно
    modal_html = ""
    if can_manage:
        modal_html = f"""
        <div class="services-modal-overlay" id="servicesModal">
            <div class="services-modal-box">
                <button class="services-modal-close" id="servicesModalClose">&times;</button>
                <h2 id="servicesModalTitle">Добавить услугу</h2>
                <form id="servicesForm" method="post" action="/api/v1/services/create">
                    <input type="hidden" name="service_id" id="serviceId">
                    <div class="services-form-group">
                        <label for="serviceMaster">Мастер *</label>
                        <select name="master_id" id="serviceMaster" class="custom-select" required>
                            <option value="">Выберите мастера</option>
                            {master_options}
                        </select>
                    </div>
                    <div class="services-form-group">
                        <label for="serviceName">Название услуги *</label>
                        <input type="text" name="name" id="serviceName" required placeholder="Например: Стрижка машинкой">
                    </div>
                    <div class="services-form-row">
                        <div class="services-form-group">
                            <label for="servicePrice">Цена (₽) *</label>
                            <input type="number" name="price" id="servicePrice" required placeholder="1500">
                        </div>
                        <div class="services-form-group">
                            <label for="serviceDuration">Длительность (мин) *</label>
                            <input type="number" name="duration_minutes" id="serviceDuration" required placeholder="30">
                        </div>
                    </div>
                    <div class="services-form-group">
                        <label for="serviceDescription">Описание</label>
                        <textarea name="description" id="serviceDescription" rows="2" placeholder="Подробнее об услуге..."></textarea>
                    </div>
                    <div class="services-modal-actions">
                        <button type="button" class="services-btn-cancel" id="servicesModalCancel">Отмена</button>
                        <button type="submit" class="services-btn-save">Сохранить</button>
                    </div>
                </form>
            </div>
        </div>
        """

    return f"""
    <div id="tab-services" class="tab-content services-tab">
        <!-- Десктопные фильтры -->
        <div class="services-filters-desktop">
            {filters_form}
        </div>

        <!-- Мобильные фильтры (аккордеон) -->
        {filters_mobile}

        <!-- Заголовок -->
        {header_html}

        <!-- Десктопная таблица -->
        {table_html}

        <!-- Мобильные карточки -->
        <div class="services-mobile">
            {cards_html}
        </div>

        <!-- Модальное окно -->
        {modal_html}
    </div>

    <script>
        function toggleServiceCard(header) {{
            const body = header.nextElementSibling;
            const chevron = header.querySelector('.service-card-chevron');
            if (body.style.display === 'none') {{
                body.style.display = 'block';
                chevron.innerHTML = `{ICON_CHEVRON_UP}`;
            }} else {{
                body.style.display = 'none';
                chevron.innerHTML = `{ICON_CHEVRON_DOWN}`;
            }}
        }}

        function toggleFiltersMobile() {{
            const collapse = document.querySelector('.services-filters-collapse');
            const chevron = document.querySelector('.filters-toggle-chevron');
            if (collapse.style.display === 'none') {{
                collapse.style.display = 'block';
                chevron.innerHTML = `{ICON_CHEVRON_UP}`;
            }} else {{
                collapse.style.display = 'none';
                chevron.innerHTML = `{ICON_CHEVRON_DOWN}`;
            }}
        }}
    </script>
    """