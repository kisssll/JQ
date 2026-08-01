# app/web/components/sidebar.py
from app.web.components.icons import (
    ICON_HOUSE,
    ICON_BUILDING2,
    ICON_BRIEFCASE,
    ICON_FILE_TEXT,
    ICON_USER,
    ICON_MODEL,
    ICON_HEART,
    ICON_LOGOUT,
    ICON_CALENDAR_DAYS_SIDEBAR,
)

def render_sidebar(current_page: str = "home", user=None) -> str:
    def is_active(page: str) -> str:
        return "active" if current_page == page else ""

    # Блок пользователя (профиль)
    if user:
        name = user.full_name or user.phone or "Пользователь"
        if user.avatar_url:
            avatar_html = f'<img src="{user.avatar_url}" alt="{name}" class="sidebar-avatar-img">'
        else:
            avatar_html = f'<span class="sidebar-avatar-placeholder">{name[0].upper()}</span>'
        user_block = f"""
        <a class="sidebar-user" href="/profile">
            <div class="sidebar-avatar">
                {avatar_html}
            </div>
            <span class="sidebar-username">{name}</span>
        </a>
        """
    else:
        user_block = f"""
        <a class="sidebar-user sidebar-user-login" href="/login">
            {ICON_USER} Войти
        </a>
        """

    # Ролевые разделы (админка и панель бизнеса)
    role_items = ""
    role = getattr(getattr(user, "role", None), "value", None)
    if role == "admin":
        role_items += f"""
                    <a class="sidebar-link {is_active('admin')}" href="/admin">
                        {ICON_USER} Админ-панель
                    </a>"""
    if (
        role == "business" or role == "master"
        or getattr(user, "has_salon_access", False) or getattr(user, "has_master_profile", False)
    ):
        role_items += f"""
                    <a class="sidebar-link {is_active('business_dashboard')}" href="/business/dashboard">
                        {ICON_BRIEFCASE} Панель бизнеса
                    </a>"""
    if getattr(user, "is_model", False):
        role_items += f"""
                    <a class="sidebar-link {is_active('model_dashboard')}" href="/model/dashboard">
                        {ICON_MODEL} Мои мэтчи
                    </a>"""
    role_links = ""
    if role_items:
        role_links = f"""
                <div class="space-y-1" style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid var(--color-border,#E5E7EB)">
                    {role_items}
                </div>"""

    # Пользовательские пункты (только для авторизованных)
    user_menu = ""
    if user:
        user_menu = f"""
                <div class="sidebar-divider" style="margin-top: 0.75rem;"></div>
                <div class="space-y-1" style="margin-top: 0.75rem;">
                    <a class="sidebar-link {is_active('bookings')}" href="/bookings">
                        {ICON_CALENDAR_DAYS_SIDEBAR} Мои записи
                    </a>
                    <a class="sidebar-link {is_active('favorites')}" href="/favorites">
                        {ICON_HEART} Избранное
                    </a>
                    <a class="sidebar-link sidebar-logout" href="/logout">
                        {ICON_LOGOUT} Выход
                    </a>
                </div>
        """

    return f"""
    <!-- Оверлей для затемнения -->
    <div class="sidebar-overlay" id="sidebar-overlay"></div>

    <!-- Сайдбар -->
    <aside class="sidebar-container" id="sidebar">
        <div class="sidebar-inner">
            <div class="sidebar-header">
                {user_block}
            </div>
            <div class="sidebar-divider"></div>
            <nav class="sidebar-nav">
                <div class="space-y-1">
                    <a class="sidebar-link {is_active('home')}" href="/">
                        {ICON_HOUSE} Главная
                    </a>
                    <a class="sidebar-link {is_active('salons')}" href="/salons">
                        {ICON_BUILDING2} Салоны
                    </a>
                    <a class="sidebar-link {is_active('business')}" href="/business">
                        {ICON_BRIEFCASE} Для бизнеса
                    </a>
                    <a class="sidebar-link {is_active('model')}" href="/model">
                        {ICON_MODEL} Стать моделью
                    </a>
                    <a class="sidebar-link {is_active('manifest')}" href="/about">
                        {ICON_FILE_TEXT} Манифест
                    </a>
                </div>

                {user_menu}

                {role_links}
            </nav>
        </div>
    </aside>
    """