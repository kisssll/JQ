# app/web/pages/model_dashboard.py
"""Личный кабинет модели: стат-карточки + 3 саб-таба (Приглашения / Кастинги /
История) + сайдбар с профилем и чек-листом заполненности. Списки подтягиваются
JS-ом с /api/v1/model-matching/* — сама страница отдаёт каркас + счётчики."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.model_matching_service import get_history_for_model, get_invitations_for_model
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles


def _profile_checklist(user) -> str:
    items = [
        ("Добавить фото профиля", bool(getattr(user, "model_photo_url", None))),
        ("Заполнить «О себе»", bool(getattr(user, "model_bio", None))),
        ("Указать, что ищете", bool(getattr(user, "model_looking_for", None))),
        ("Указать город", bool(getattr(user, "city", None))),
    ]
    rows = "".join(f"""
        <li style="display:flex;align-items:center;gap:0.6rem;font-size:0.85rem;padding:0.3rem 0">
            <span style="display:flex;height:1.25rem;width:1.25rem;align-items:center;justify-content:center;border-radius:50%;font-size:0.65rem;font-weight:700;flex-shrink:0;{'background:#d1fae5;color:#065f46' if done else 'background:var(--color-surface-alt,#f3f4f6);color:var(--color-muted)'}">{'✓' if done else '·'}</span>
            <span style="{'color:var(--color-muted);text-decoration:line-through' if done else ''}">{label}</span>
        </li>""" for label, done in items)
    return f'<ul style="list-style:none;padding:0;margin:0">{rows}</ul>'


async def render_model_dashboard(db: AsyncSession, user) -> str:
    is_model = bool(getattr(user, "is_model", False))

    if not is_model:
        body = """
        <div class="card" style="padding:2rem;text-align:center">
            <h2 style="margin-bottom:0.75rem">Анкета не заполнена</h2>
            <p class="text-muted" style="margin-bottom:1.5rem">Заведите анкету, чтобы увидеть мастеров, которые ищут моделей для отработки техники.</p>
            <a href="/model/join" class="btn-primary">Стать моделью</a>
        </div>
        """
        return _render_page(user, body)

    moderation = getattr(user, "model_moderation_status", None)
    moderation_value = moderation.value if moderation else "pending"
    approved = moderation_value == "approved"

    status_banner = ""
    if moderation_value == "pending":
        status_banner = '<div class="profile-alert" style="background:#fef3c7;color:#92400e;border:1px solid #fde68a;padding:0.75rem 1rem;border-radius:0.5rem;margin-bottom:1.5rem">⏳ Анкета на модерации — лента и лайки станут доступны после одобрения.</div>'
    elif moderation_value == "rejected":
        reason = getattr(user, "model_rejection_reason", "") or ""
        status_banner = (
            '<div class="profile-alert" style="background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;padding:0.75rem 1rem;border-radius:0.5rem;margin-bottom:1.5rem">'
            '⚠️ Анкета отклонена' + (f' — {reason}' if reason else '') +
            '. Обновите анкету в <a href="/model/join">редактировании</a> и она снова уйдёт на проверку.</div>'
        )

    invitations_count = len(await get_invitations_for_model(db, user.id)) if approved else 0
    history = await get_history_for_model(db, user.id)
    visits_count = len(history)

    stat_cards = f"""
    <div class="models-stat-grid">
        <div class="card" style="padding:1.1rem">
            <p class="text-display" style="font-size:1.6rem;margin:0">{invitations_count}</p>
            <p class="text-muted" style="font-size:0.8rem;margin-top:0.25rem">Приглашений</p>
        </div>
        <div class="card" style="padding:1.1rem">
            <p class="text-display" style="font-size:1.6rem;margin:0">{visits_count}</p>
            <p class="text-muted" style="font-size:0.8rem;margin-top:0.25rem">Визитов</p>
        </div>
    </div>
    """

    deck_tab_html = f"""
    <div id="models-subtab-casting" class="models-dash-panel" style="display:none">
        {"" if approved else '<p class="text-muted" style="padding:2rem;text-align:center">Доступно после модерации анкеты</p>'}
        {'''
        <div class="models-card-stack" id="modelDeckStack">
            <p class="text-muted" style="text-align:center;padding:2rem 0">Загрузка…</p>
        </div>
        <div class="models-swipe-buttons">
            <button type="button" class="models-swipe-btn models-swipe-btn-pass" onclick="window.modelDeckButtonSwipe(false)">✕</button>
            <button type="button" class="models-swipe-btn models-swipe-btn-like" onclick="window.modelDeckButtonSwipe(true)">♥</button>
        </div>
        ''' if approved else ''}
    </div>
    """

    body = f"""
    {status_banner}
    {stat_cards}
    <div class="models-dash-grid">
        <div>
            <div class="models-subtab-nav">
                <button type="button" class="models-subtab-btn active" data-subtab="invitations" onclick="window.modelDashShowSubtab('invitations')">🔔 Приглашения<span class="models-subtab-badge" id="modelInvitationsBadge"></span></button>
                <button type="button" class="models-subtab-btn" data-subtab="casting" onclick="window.modelDashShowSubtab('casting')">🔍 Кастинги</button>
                <button type="button" class="models-subtab-btn" data-subtab="history" onclick="window.modelDashShowSubtab('history')">📅 История</button>
            </div>

            <div id="models-subtab-invitations" class="models-dash-panel">
                {'' if approved else '<p class="text-muted" style="padding:2rem;text-align:center">Доступно после модерации анкеты</p>'}
                <div id="modelInvitationsList"></div>
            </div>

            {deck_tab_html}

            <div id="models-subtab-history" class="models-dash-panel" style="display:none">
                <div id="modelHistoryList"></div>
            </div>
        </div>

        <div>
            <div class="card" style="padding:1.25rem;margin-bottom:1rem">
                <div style="display:flex;align-items:center;gap:0.75rem">
                    {f'<img src="{user.model_photo_url}" alt="" style="width:56px;height:56px;border-radius:50%;object-fit:cover">' if getattr(user, "model_photo_url", None) else '<div style="width:56px;height:56px;border-radius:50%;background:var(--color-surface-alt,#f3f4f6);display:flex;align-items:center;justify-content:center;color:var(--color-muted)">?</div>'}
                    <strong>{user.full_name or "Ваше имя"}</strong>
                </div>
                <a href="/model/join" class="btn-outline" style="display:block;text-align:center;margin-top:1rem;font-size:0.85rem">Редактировать профиль</a>
            </div>
            <div class="card" style="padding:1.25rem">
                <h3 style="margin-bottom:0.75rem;font-size:0.95rem">Как получить больше заявок</h3>
                {_profile_checklist(user)}
            </div>
        </div>
    </div>
    """
    return _render_page(user, body, approved=approved)


def _render_page(user, body: str, approved: bool = False) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Кабинет модели — руми</title>
    {get_base_styles()}
    <style>
        .invite-card {{
            background: var(--color-surface);
            border: 1px solid var(--color-border);
            border-radius: 1rem;
            padding: 1.25rem;
            margin-bottom: 1rem;
        }}
        .status-badge {{ padding: 0.25rem 0.75rem; border-radius: 1rem; font-size: 0.75rem; font-weight: 600; }}
        .status-matched {{ background: #fef3c7; color: #92400e; }}
        .status-booked {{ background: #d1fae5; color: #065f46; }}
        .status-declined {{ background: #fee2e2; color: #991b1b; }}
        .models-stat-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:1rem; max-width:24rem; margin-bottom:1.5rem }}
        .models-dash-grid {{ display:grid; grid-template-columns:1fr; gap:1.5rem }}
        @media (min-width: 1024px) {{ .models-dash-grid {{ grid-template-columns:1fr 300px }} }}
        .models-subtab-nav {{ display:flex; gap:0.25rem; background:var(--color-surface-alt,#f3f4f6); border-radius:0.75rem; padding:0.25rem; margin-bottom:1.25rem; flex-wrap:wrap }}
        .models-subtab-btn {{ flex:1; min-width:8rem; padding:0.6rem; border:none; background:transparent; border-radius:0.5rem; cursor:pointer; font-size:0.85rem; font-weight:500; color:var(--color-muted); position:relative }}
        .models-subtab-btn.active {{ background:var(--color-surface,#fff); color:var(--color-heading); box-shadow:0 1px 2px rgba(0,0,0,0.06) }}
        .models-subtab-badge {{ display:inline-block; min-width:1.1rem; margin-left:0.3rem; padding:0 0.3rem; border-radius:1rem; background:var(--color-primary); color:#fff; font-size:0.65rem; font-weight:700 }}
        .models-card-stack {{ position:relative; width:100%; max-width:340px; margin:0 auto 1rem; aspect-ratio:3/4 }}
        .models-swipe-card {{ position:absolute; inset:0; border:1px solid var(--color-border); border-radius:1rem; overflow:hidden; background:var(--color-surface,#fff); box-shadow:0 10px 25px rgba(0,0,0,0.12) }}
        .models-swipe-card-photo {{ position:relative; height:65%; background-size:cover; background-position:center; background-color:var(--color-surface-alt,#eee) }}
        .models-swipe-card-photo::after {{ content:''; position:absolute; inset:0; background:linear-gradient(to top, rgba(0,0,0,0.6), transparent 60%) }}
        .models-swipe-card-name {{ position:absolute; left:1rem; right:1rem; bottom:0.75rem; color:#fff }}
        .models-swipe-card-body {{ padding:0.9rem 1rem; height:35%; overflow:hidden }}
        .models-swipe-buttons {{ display:flex; justify-content:center; gap:1.25rem; margin-top:1rem }}
        .models-swipe-btn {{ width:3.25rem; height:3.25rem; border-radius:50%; border:2px solid var(--color-border); background:#fff; cursor:pointer; font-size:1.3rem; display:flex; align-items:center; justify-content:center }}
        .models-swipe-btn-like {{ width:3.75rem; height:3.75rem; color:#22c55e; border-color:#bbf7d0 }}
        .models-swipe-btn-pass {{ color:#ef4444; border-color:#fecaca }}
    </style>
</head>
<body>
    {render_header("model")}
    {render_sidebar("model_dashboard", user)}

    <main style="margin-right: 16rem; padding-top: 5.5rem;">
        <div class="section-container">
            <h1 class="text-display" style="font-size:2rem;margin-bottom:1.5rem">Кабинет модели</h1>
            {body}
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
