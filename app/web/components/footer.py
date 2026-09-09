# app/web/components/footer.py
import html

from app.core.config import settings
from app.web.components.icons import ICON_MAIL, ICON_MESSAGE_CIRCLE

SUPPORT_EMAIL = "hello@rrumi.ru"


def _support_block() -> str:
    """Три способа задать вопрос: почта и оба бота.

    Ссылки на ботов ведут не на их главное меню, а сразу на выбор темы
    обращения (?start=support): человек идёт по ним с вопросом, лишний шаг
    здесь — потерянный вопрос. Обработчики этой метки есть в обоих ботах.

    Бот показывается, только если его имя задано в окружении: иначе ссылка
    вела бы на несуществующий адрес мессенджера.
    """
    options = [(
        "Почта", f"mailto:{SUPPORT_EMAIL}", SUPPORT_EMAIL, "", ICON_MAIL,
    )]
    tg = (settings.TG_BOT_USERNAME or "").strip().lstrip("@")
    if tg:
        options.append((
            "Telegram", f"https://t.me/{html.escape(tg, quote=True)}?start=support",
            f"@{tg}", ' target="_blank" rel="noopener"', ICON_MESSAGE_CIRCLE,
        ))
    mx = (settings.MAX_BOT_USERNAME or "").strip().lstrip("@")
    if mx:
        options.append((
            "MAX", f"https://max.ru/{html.escape(mx, quote=True)}?start=support",
            f"@{mx}", ' target="_blank" rel="noopener"', ICON_MESSAGE_CIRCLE,
        ))

    # Иконка есть у каждого варианта — это опознавательный знак, а не выделение
    # одного из них: у обоих ботов она одна и та же.
    links = "".join(
        f'<a class="footer-support-link" href="{href}"{attrs}>'
        f'<span class="footer-support-icon" aria-hidden="true">{icon}</span>'
        f'<span class="footer-support-text">'
        f'<span class="footer-support-name">{name}</span>'
        f'<span class="footer-support-addr">{html.escape(addr)}</span>'
        f'</span></a>'
        for name, href, addr, attrs, icon in options
    )
    # Подсказка про чат — только если чат вообще предложен: без ботов она
    # обещала ответ в мессенджере, которого на экране нет.
    bots = [name for name, *_ in options if name != "Почта"]
    hint = (
        f'<p class="footer-support-hint">В {" и ".join(bots)} ответим в том же '
        f'чате — регистрация не нужна.</p>'
    ) if bots else ""

    return f"""
            <div class="footer-support">
                <p class="footer-support-title">Есть вопрос?</p>
                <div class="footer-support-links">{links}</div>
                {hint}
            </div>"""


def render_footer(user=None) -> str:
    """
    Рендерит футер с адаптивными ссылками в зависимости от роли пользователя.
    """
    # Ссылки общие для всех
    client_links = [("Салоны", "/salons")]
    about_links = [("Манифест", "/about")]

    # Партнёрские предложения Т-Банка — видны всем, независимо от роли.
    tbank_links = [
        ("Подключение РКО", "/business/tbank/rko"),
        ("Регистрация бизнеса", "/business/tbank/registration"),
        ("Кредиты для развития бизнеса", "/business/tbank/credit"),
    ]

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

    business_links = business_links + tbank_links

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
                        <li><a class="footer-link" href="/offer">Оферта для клиентов</a></li>
                        <li><a class="footer-link" href="/license">Оферта для салонов</a></li>
                        <li><a class="footer-link" href="/cookies">Политика cookie</a></li>
                        <li><a class="footer-link" href="/legal">Все документы</a></li>
                    </ul>
                </div>
            </div>

            {_support_block()}

            <!-- Контакты оператора. Статья 10 149-ФЗ обязывает владельца сайта
                 разместить наименование, место нахождения с адресом и адрес
                 электронной почты; ОГРН и ИНН добавлены для полноты реквизитов. -->
            <address class="footer-contacts">
                <p class="footer-contacts-title">ООО «РУМИ»</p>
                <p>Россия, Томская область, г. Томск</p>
                <p>ОГРН 1267000004370 · ИНН 7000036144</p>
                <p><a class="footer-link" href="mailto:hello@rrumi.ru">hello@rrumi.ru</a></p>
            </address>
            <div class="footer-meta footer-meta-flex">
                <span>© 2026 руми. Все права защищены.</span>
                <span>30 секунд · 4 клика · 0 звонков</span>
            </div>
        </div>
    </footer>
    """