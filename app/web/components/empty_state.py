# app/web/components/empty_state.py
"""Единое пустое состояние.

До этого каждая страница писала свой блок: /salons — иконка в круге, заголовок,
пояснение и кнопка сброса; записи — иконка и действие; избранное — просто серый
текст со ссылкой, причём два пустых блока подряд. Здесь один вид на всё.

Стили — static/src/css/empty-state.css.
"""
import html


def render_empty_state(
    title: str,
    text: str = "",
    icon: str = "",
    action_href: str = "",
    action_label: str = "",
    element_id: str = "",
) -> str:
    """Пустое состояние. С иконкой — развёрнутый вид (.is-rich), без неё —
    компактная строка, как во вложенных списках панели.

    action_href/action_label — следующее действие. Пустое состояние это
    приглашение действовать, а не сообщение о том, что данных нет.
    """
    attrs = f' id="{html.escape(element_id, quote=True)}"' if element_id else ""
    rich = " is-rich" if icon else ""

    icon_html = f'<div class="empty-state-icon" aria-hidden="true">{icon}</div>' if icon else ""
    text_html = f'<p class="empty-state-text">{html.escape(text)}</p>' if text else ""
    action_html = ""
    if action_href and action_label:
        action_html = (
            f'<a href="{html.escape(action_href, quote=True)}" '
            f'class="btn-outline empty-state-action">{html.escape(action_label)}</a>'
        )

    return f"""
    <div class="empty-state{rich}"{attrs}>
        {icon_html}
        <p class="empty-state-title">{html.escape(title)}</p>
        {text_html}
        {action_html}
    </div>
    """
