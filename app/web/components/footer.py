# app/web/components/footer.py

def render_footer(user=None) -> str:
    """
    Рендерит футер с адаптивными ссылками в зависимости от роли пользователя.
    """
    # Ссылки общие для всех
    client_links = [("Салоны", "/salons")]
    about_links = [("Манифест", "/about")]

    if user is None:
        # Неавторизованный пользователь
        client_links.append(("Стать моделью", "/model"))
        business_links = [("Подключить салон", "/business")]
    else:
        # Авторизованный
        role = user.role.value if hasattr(user, 'role') else None

        # Все авторизованные видят Мои записи, Избранное, Настройки
        client_links.append(("Мои записи", "/bookings"))
        client_links.append(("Избранное", "/favorites"))

        # Ролевые особенности
        if role in ('client', 'admin'):
            client_links.append(("Стать моделью", "/model"))

        if role == 'business':
            business_links = [("Панель салона", "/business/dashboard")]
        else:
            business_links = [("Подключить салон", "/business")]
            if role == 'admin':
                business_links.append(("Панель салона", "/business/dashboard"))

        # Для админа доступно все

    client_items = ''.join(
        f'<li><a class="footer-link" href="{url}">{text}</a></li>'
        for text, url in client_links
    )
    business_items = ''.join(
        f'<li><a class="footer-link" href="{url}">{text}</a></li>'
        for text, url in business_links
    )
    about_items = ''.join(
        f'<li><a class="footer-link" href="{url}">{text}</a></li>'
        for text, url in about_links
    )

    return f"""
    <footer class="comp-footer">
        <div class="section-container footer-bottom-section">
            <div class="footer-links-grid">
                <div>
                    <h3 class="footer-logo">руми<span>.</span></h3>
                    <p class="footer-desc">Запись в салон за 4 клика. Управление салоном — в одном окне.</p>
                </div>
                <div>
                    <h4 class="footer-col-title">Клиентам</h4>
                    <ul class="footer-nav-list">
                        {client_items}
                    </ul>
                </div>
                <div>
                    <h4 class="footer-col-title">Бизнесу</h4>
                    <ul class="footer-nav-list">
                        {business_items}
                    </ul>
                </div>
                <div>
                    <h4 class="footer-col-title">О сервисе</h4>
                    <ul class="footer-nav-list">
                        {about_items}
                    </ul>
                </div>
                <div>
                    <h4 class="footer-col-title">Документы</h4>
                    <ul class="footer-nav-list">
                        <li><a class="footer-link" href="/terms">Пользовательское соглашение</a></li>
                        <li><a class="footer-link" href="/privacy">Политика обработки ПДн</a></li>
                        <li><a class="footer-link" href="/consent">Согласие на обработку ПДн</a></li>
                    </ul>
                </div>
            </div>

            <!-- Контакты оператора. Статья 10 149-ФЗ обязывает владельца сайта
                 разместить наименование, место нахождения с адресом и адрес
                 электронной почты; ОГРН и ИНН добавлены для полноты реквизитов. -->
            <address class="footer-contacts">
                <p class="footer-contacts-title">ООО «РУМИ»</p>
                <p>634021, Россия, Томская обл., г. Томск, ул. Шевченко, д. 21, кв. 20</p>
                <p>ОГРН 1267000004370 · ИНН 7000036144</p>
                <p><a class="footer-link" href="mailto:hello@rrumi.ru">hello@rrumi.ru</a></p>
            </address>
            <div class="footer-meta footer-meta-flex">
                <span>© 2026 руми. Все права защищены.</span>
                <span>4 клика · 30 секунд · 0 звонков</span>
            </div>
        </div>
    </footer>
    """