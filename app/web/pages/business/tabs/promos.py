# app/web/pages/business/tabs/promos.py
from app.web.components.hint import hint as _hint
from app.web.components.icons import (
    ICON_PLUS, ICON_TRASH, ICON_EDIT, ICON_SAVE, ICON_COPY,
)
from app.models.models import SalonLoyaltySettings, LoyaltyOffer  # для типов, но данные передаются


def render_promos_tab(
    promotions,
    can_manage: bool = False,
    salon_id: int = None,
    loyalty_settings=None,
    loyalty_offers=None,
    evening_deal_html: str = "",
) -> str:
    """
    Вкладка Акции.
    - can_manage: есть ли право manage_promotions (кнопка добавления и удаления).
    - salon_id: нужен для форм.
    - loyalty_settings: объект SalonLoyaltySettings или None.
    - loyalty_offers: список LoyaltyOffer.
    """
    # ---- Акции (существующий блок) ----
    promos_rows = ""
    for p in promotions:
        delete_btn = ""
        edit_btn = ""
        if can_manage:
            delete_btn = f'''
                <button onclick="deletePromo({p.id}, '{p.title}')" class="delete-btn-icon" title="Удалить акцию">
                    {ICON_TRASH}
                </button>
            '''
            title_js = p.title.replace("'", "\\'")
            desc_js = p.description.replace("'", "\\'") if p.description else ''
            tag_js = p.tag.replace("'", "\\'")
            edit_btn = f'''
                <button onclick="editPromo({p.id}, '{title_js}', '{desc_js}', '{tag_js}')"
                        class="edit-btn-icon" title="Редактировать акцию">
                    {ICON_EDIT}
                </button>
            '''
        actions_cell = f'<td class="promos-actions-cell">{edit_btn} {delete_btn}</td>' if can_manage else ''
        promos_rows += f"""
        <tr>
            <td><strong>{p.title}</strong></td>
            <td><span class="promo-badge">{p.tag}</span></td>
            <td>{p.description or '—'}</td>
            {actions_cell}
        </tr>
        """

    if not promos_rows:
        cols = 3 if not can_manage else 4
        promos_rows = f'<tr><td colspan="{cols}" class="empty-state">Пока нет акций</td></tr>'

    # Кнопка добавления акции (только если есть права)
    add_btn = ""
    if can_manage and salon_id:
        add_btn = f'''
        <button class="promos-btn-primary" id="promosAddBtn">
            {ICON_PLUS} Добавить акцию
        </button>
        '''

    # Модалка добавления акции
    add_modal_html = ""
    if can_manage and salon_id:
        add_modal_html = f'''
        <div class="promos-modal-overlay" id="promosAddModal">
            <div class="promos-modal-box">
                <button class="promos-modal-close" id="promosModalCloseAdd">&times;</button>
                <h2>Добавить акцию</h2>
                <form id="promosAddForm" action="/api/v1/business/my-salon/promotions/web" method="post">
                    <input type="hidden" name="salon_id" value="{salon_id}">
                    <div class="promos-form-group">
                        <label for="promoTitleAdd">Название *</label>
                        <input type="text" id="promoTitleAdd" name="title" required placeholder="Например: Скидка 20%">
                    </div>
                    <div class="promos-form-group">
                        <label for="promoDescAdd">Описание</label>
                        <textarea id="promoDescAdd" name="description" rows="2" placeholder="Условия акции..."></textarea>
                    </div>
                    <div class="promos-form-group">
                        <label for="promoTagAdd">Тег *</label>
                        <input type="text" id="promoTagAdd" name="tag" required placeholder="Новичкам, Выгода, Подарок...">
                    </div>
                    <button type="submit" class="promos-btn-primary promos-submit-btn">Добавить акцию</button>
                </form>
            </div>
        </div>
        '''

    # Модалка редактирования акции
    edit_modal_html = ""
    if can_manage and salon_id:
        edit_modal_html = f'''
        <div class="promos-modal-overlay" id="promosEditModal">
            <div class="promos-modal-box">
                <button class="promos-modal-close" id="promosModalCloseEdit">&times;</button>
                <h2>Редактировать акцию</h2>
                <form id="promosEditForm" action="#" method="post">
                    <input type="hidden" name="promo_id" id="editPromoId">
                    <div class="promos-form-group">
                        <label for="promoTitleEdit">Название *</label>
                        <input type="text" id="promoTitleEdit" name="title" required>
                    </div>
                    <div class="promos-form-group">
                        <label for="promoDescEdit">Описание</label>
                        <textarea id="promoDescEdit" name="description" rows="2"></textarea>
                    </div>
                    <div class="promos-form-group">
                        <label for="promoTagEdit">Тег *</label>
                        <input type="text" id="promoTagEdit" name="tag" required>
                    </div>
                    <div style="display:flex; gap:0.75rem; justify-content:flex-end;">
                        <button type="button" class="promos-btn-outline" id="promosEditCancel">Отмена</button>
                        <button type="submit" class="promos-btn-primary">Сохранить</button>
                    </div>
                </form>
            </div>
        </div>
        '''

    # ---- Блоки лояльности (только если can_manage) ----
    loyalty_html = ""
    if can_manage and salon_id:
        # Настройки лояльности
        settings = loyalty_settings
        offers = loyalty_offers or []

        # Формируем строки таблицы именных скидок
        offers_rows = ""
        for o in offers:
            code_str = o.promo_code or "—"
            offers_rows += f"""
            <tr>
                <td><strong>{o.title}</strong></td>
                <td>{o.discount_percent}%</td>
                <td><code>{code_str}</code></td>
                <td>
                    <button onclick="deleteLoyaltyOffer({o.id}, '{o.title}')" class="delete-btn-icon">{ICON_TRASH}</button>
                </td>
            </tr>
            """
        if not offers_rows:
            offers_rows = '<tr><td colspan="4" class="empty-state">Пока нет именных скидок</td></tr>'

        loyalty_html = f"""
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
                    <input type="number" id="loyaltyRegularPercent" min="0" max="99" value="{settings.regular_client_discount_percent if settings else 0}">
                </div>
                <div class="loyalty-field">
                    <label for="loyaltyVisitsThreshold">Статус «Постоянный клиент»: визитов за год {_hint("Клиенту автоматически присваивается статус «Постоянный клиент», как только он наберёт это число визитов за последние 12 месяцев. Статус лишь открывает администратору возможность выбрать скидку слева при завершении записи в «Расписании» — сама скидка не начисляется автоматически. Оставьте поле пустым, чтобы присваивать статус только вручную.")}</label>
                    <input type="number" id="loyaltyVisitsThreshold" min="1" placeholder="Не задано — только вручную" value="{settings.regular_client_visits_threshold if settings and settings.regular_client_visits_threshold else ''}">
                </div>
            </div>
            <div class="loyalty-field full-width">
                <label for="loyaltyBonusAccrual">Автоначисление баллов после оплаты, % от чека</label>
                <input type="number" id="loyaltyBonusAccrual" min="0" max="99" step="0.1" placeholder="0 — выключено" value="{settings.bonus_accrual_percent if settings else 0}">
            </div>
            <button type="button" class="my-salon-btn-primary" onclick="saveLoyaltySettings({salon_id})">{ICON_SAVE} Сохранить настройки лояльности</button>

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
                        {offers_rows}
                    </tbody>
                </table>
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
                <button type="button" class="my-salon-btn-primary" style="width:100%" onclick="addLoyaltyOffer({salon_id})">Добавить</button>
            </div>
        </div>
        """

    # Заголовок вкладки с подсказкой
    hint_text = "Метки-акции, которые видят клиенты на странице салона (например «Скидка новым клиентам»)."
    if not can_manage:
        hint_text += " У вас нет прав на управление акциями."

    header = f'''
    <div class="promos-header">
        <h2>Акции {_hint(hint_text)}</h2>
        {add_btn}
    </div>
    '''

    table = f'''
    <div class="promos-table-wrap">
        <table class="promos-table">
            <thead>
                <tr>
                    <th>Название</th>
                    <th>Тег</th>
                    <th>Описание</th>
                    {f'<th class="promos-actions-cell">Действия</th>' if can_manage else ''}
                </tr>
            </thead>
            <tbody>
                {promos_rows}
            </tbody>
        </table>
    </div>
    '''

    # Добавляем скрипт для установки window.salonId, чтобы функции лояльности работали
    salon_script = f'<script>window.salonId = {salon_id};</script>'

    return f'''
    <div id="tab-promos" class="tab-content promos-tab">
        {header}
        {evening_deal_html}
        {table}
        {add_modal_html}
        {edit_modal_html}
        {loyalty_html}
        {salon_script}
    </div>
    '''