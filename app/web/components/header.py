# app/web/components/header.py
from app.web.components.icons import ICON_MENU

def render_header(current_page: str = "home") -> str:
    """Закреплённая шапка с фирменным логотипом.

    Логотип — картинка, а не текст: начертание рукописное, системным шрифтом
    его не набрать. Размеры у <img> проставлены, чтобы шапка не дёргалась,
    пока файл грузится.
    """
    return f"""
    <header id="main-header">
        <div id="header-nav">
            <div id="header-logo-wrapper">
                <a href="/" id="header-logo" aria-label="Руми — на главную">
                    <picture>
                        <source type="image/webp" srcset="/static/images/rumi-logo.webp">
                        <img src="/static/images/rumi-logo.png" alt="Руми"
                             width="480" height="312">
                    </picture>
                </a>
            </div>
            <button id="header-burger" aria-label="Открыть меню">
                {ICON_MENU}
            </button>
        </div>
    </header>
    """