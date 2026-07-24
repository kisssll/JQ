# app/web/pages/business/tabs/promos.py
from app.web.components.hint import hint as _hint
from app.web.components.icons import ICON_PLUS, ICON_TRASH, ICON_EDIT


def render_promos_tab(promotions, can_manage: bool = False, salon_id: int = None) -> str:
    """
    Вкладка Акции.
    - can_manage: есть ли право manage_promotions (кнопка добавления и удаления).
    - salon_id: нужен для формы добавления.
    """
    # Строим таблицу
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

    # Кнопка добавления только если есть права
    add_btn = ""
    if can_manage and salon_id:
        add_btn = f'''
        <button class="promos-btn-primary" id="promosAddBtn">
            {ICON_PLUS} Добавить акцию
        </button>
        '''

    # Модалка добавления
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

    # Модалка редактирования
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

    # Заголовок с подсказкой
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

    return f'''
    <div id="tab-promos" class="tab-content promos-tab">
        {header}
        {table}
        {add_modal_html}
        {edit_modal_html}
    </div>
    '''