# app/web/pages/business/tabs/interactive.py
"""Вкладка «Интерактивная запись» в бизнес-панели.

Позволяет мастеру и салону настроить интерактивный предварительный опрос клиента
перед выбором времени:
  1. Длина волос (динамическая иллюстрация + ползунок + доплаты и добавочное время).
  2. Тип и структура волос.
  3. Густота волос.
  4. Чекбоксы/вопросы особенностей (с возможностью добавления своих вопросов,
     влияющих на стоимость и тайминг процедуры).
"""
import json
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Master, Salon, SalonMember, User as UserModel
from app.web.components.escaping import e
from app.web.components.icons import (
    ICON_CHECK_SMALL,
    ICON_PLUS_SMALL,
    ICON_SLIDERS,
)

DEFAULT_LENGTH_RULES = [
    {"id": 1, "title": "Очень короткие (пикси)", "sub": "пикси", "cm": "до 15 см", "price": 0, "duration": 0},
    {"id": 2, "title": "Короткие (боб / каре)", "sub": "боб", "cm": "~20 см", "price": 0, "duration": 0},
    {"id": 3, "title": "До плеч", "sub": "до плеч", "cm": "~30 см", "price": 0, "duration": 0},
    {"id": 4, "title": "Средние (до лопаток)", "sub": "до лопаток", "cm": "~40–45 см", "price": 500, "duration": 15},
    {"id": 5, "title": "Длинные (до талии)", "sub": "до талии", "cm": "~55–60 см", "price": 1000, "duration": 30},
    {"id": 6, "title": "Очень длинные (до ягодиц)", "sub": "до ягодиц", "cm": "~70–75 см", "price": 1500, "duration": 45},
    {"id": 7, "title": "Экстремально длинные (ниже бедер)", "sub": "ниже бедер", "cm": "от 80 см", "price": 2000, "duration": 60},
]

DEFAULT_TYPE_RULES = [
    {"id": "straight", "title": "Прямые, гладкие", "desc": "Ровные, легко укладываются", "price": 0, "duration": 0},
    {"id": "wavy", "title": "Легкая волна", "desc": "Пушатся во влажную погоду", "price": 0, "duration": 0},
    {"id": "curly", "title": "Кудрявые / вьющиеся", "desc": "Четкий упругий завиток", "price": 300, "duration": 15},
    {"id": "coarse", "title": "Жесткие, стекловидные", "desc": "Плохо поддаются укладке", "price": 500, "duration": 20},
]

DEFAULT_DENSITY_RULES = [
    {"id": "thin", "title": "Не густые", "desc": "Тонкий хвост", "price": 0, "duration": 0},
    {"id": "medium", "title": "Средняя густота", "desc": "Стандартная", "price": 0, "duration": 0},
    {"id": "thick", "title": "Очень густые", "desc": "Объемный хвост", "price": 500, "duration": 30},
]

DEFAULT_CUSTOM_TAGS = [
    {"name": "Обесцвеченные / блонд", "price": 0, "duration": 0},
    {"name": "Окрашенные", "price": 0, "duration": 0},
    {"name": "Натуральные (неокрашенные)", "price": 0, "duration": 0},
    {"name": "Есть седина", "price": 0, "duration": 0},
    {"name": "Ранее делали кератин / ботокс", "price": 0, "duration": 0},
    {"name": "Наращенные волосы", "price": 500, "duration": 30},
    {"name": "Химическая завивка", "price": 0, "duration": 0},
    {"name": "Поврежденные / секущиеся кончики", "price": 0, "duration": 0},
]


async def render_interactive_tab(
    db: AsyncSession,
    salon: Salon,
    masters: list,
    user: UserModel,
    membership: SalonMember,
    perms: dict,
    query_params: dict,
) -> str:
    """Рендер вкладки «Интерактивная запись»."""
    if not masters:
        return (
            '<div id="tab-interactive" class="tab-content">'
            '<div class="card" style="padding:2rem;text-align:center;color:var(--color-muted);">'
            'В салоне пока нет мастеров для настройки интерактивной записи.'
            '</div></div>'
        )

    # Выбор мастера, если их несколько
    selected_master_id = query_params.get("master_id")
    if selected_master_id and str(selected_master_id).isdigit():
        target_master = next((m for m in masters if m.id == int(selected_master_id)), masters[0])
    else:
        # Пытаемся найти профиль самого пользователя, если он мастер
        user_master = next((m for m in masters if m.user_id == user.id), None)
        target_master = user_master or masters[0]

    master_user = (await db.execute(select(UserModel).where(UserModel.id == target_master.user_id))).scalar_one_or_none()
    master_display_name = master_user.full_name if master_user else target_master.specialization

    # Селектор мастера, если мастеров > 1
    master_selector_html = ""
    if len(masters) > 1:
        master_options = "".join(
            f'<option value="{m.id}" {"selected" if m.id == target_master.id else ""}>'
            f'Мастер #{m.id} — {e(m.specialization)}'
            f'</option>'
            for m in masters
        )
        master_selector_html = f"""
        <div style="margin-bottom:1.25rem;max-width:380px;">
            <label style="font-size:0.85rem;font-weight:600;color:var(--color-muted);display:block;margin-bottom:0.35rem;">
                ВЫБЕРИТЕ МАСТЕРА ДЛЯ НАСТРОЙКИ:
            </label>
            <select class="custom-select" onchange="window.location.href='/business/dashboard?salon_id={salon.id}&tab=interactive&master_id=' + this.value">
                {master_options}
            </select>
        </div>
        """

    is_enabled = bool(target_master.hair_survey_enabled)
    settings = target_master.hair_survey_settings or {}

    q_length_enabled = bool(settings.get("q_length_enabled", True))
    q_density_enabled = bool(settings.get("q_density_enabled", True))
    q_type_enabled = bool(settings.get("q_type_enabled", True))
    q_tags_enabled = bool(settings.get("q_tags_enabled", True))
    custom_questions = settings.get("custom_questions") or []
    custom_questions_json_str = json.dumps(custom_questions, ensure_ascii=False)

    # Загружаем сохраненные правила длины
    saved_length_rules = settings.get("length_rules") or {}
    length_rows = []
    for default_item in DEFAULT_LENGTH_RULES:
        lid = str(default_item["id"])
        saved = saved_length_rules.get(lid) or {}
        price = saved.get("price", default_item["price"])
        duration = saved.get("duration", default_item["duration"])
        length_rows.append({
            "id": default_item["id"],
            "title": default_item["title"],
            "cm": default_item["cm"],
            "price": price,
            "duration": duration,
        })

    # Загружаем сохраненные правила типов
    saved_type_rules = settings.get("type_rules") or {}
    type_rows = []
    for default_item in DEFAULT_TYPE_RULES:
        tid = default_item["id"]
        saved = saved_type_rules.get(tid) or {}
        price = saved.get("price", default_item["price"])
        duration = saved.get("duration", default_item["duration"])
        type_rows.append({
            "id": default_item["id"],
            "title": default_item["title"],
            "desc": default_item["desc"],
            "price": price,
            "duration": duration,
        })

    # Загружаем сохраненные правила густоты
    saved_density_rules = settings.get("density_rules") or {}
    density_rows = []
    for default_item in DEFAULT_DENSITY_RULES:
        did = default_item["id"]
        saved = saved_density_rules.get(did) or {}
        price = saved.get("price", default_item["price"])
        duration = saved.get("duration", default_item["duration"])
        density_rows.append({
            "id": default_item["id"],
            "title": default_item["title"],
            "desc": default_item["desc"],
            "price": price,
            "duration": duration,
        })

    # Загружаем сохраненные вопросы / теги
    saved_tags = settings.get("custom_tags") or settings.get("tags") or DEFAULT_CUSTOM_TAGS
    tag_items = []
    for t in saved_tags:
        if isinstance(t, dict):
            tag_items.append(t)
        elif isinstance(t, str):
            tag_items.append({"name": t, "price": 0, "duration": 0})

    # Оповещение об успешном сохранении
    ok_banner = ""
    if query_params.get("ok"):
        ok_banner = """
        <div class="r-alert r-alert--success" style="padding:0.75rem 1rem;background:var(--color-accent-light);color:var(--color-accent-text);border-radius:var(--radius-8);margin-bottom:1.25rem;">
            ✓ Настройки интерактивной записи успешно сохранены!
        </div>
        """

    # Таблица длины
    length_table_html = "".join(
        f"""
        <tr data-len-id="{r['id']}">
            <td style="padding:0.6rem 0.75rem;font-weight:600;">
                <span class="len-step-badge" style="display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;border-radius:50%;background:var(--color-surface-alt);font-size:12px;margin-right:6px;">{r['id']}</span>
                {e(r['title'])}
            </td>
            <td style="padding:0.6rem 0.75rem;color:var(--color-muted);">{e(r['cm'])}</td>
            <td style="padding:0.6rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="len_price_{r['id']}" value="{r['price']}" min="0" step="50"
                           class="r-input" style="width:90px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>₽</span>
                </div>
            </td>
            <td style="padding:0.6rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="len_duration_{r['id']}" value="{r['duration']}" min="0" step="5"
                           class="r-input" style="width:75px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>мин</span>
                </div>
            </td>
        </tr>
        """
        for r in length_rows
    )

    # Таблица типов
    type_table_html = "".join(
        f"""
        <tr>
            <td style="padding:0.6rem 0.75rem;font-weight:600;">
                {e(r['title'])}
                <div style="font-size:11px;color:var(--color-muted);font-weight:normal;">{e(r['desc'])}</div>
            </td>
            <td style="padding:0.6rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="type_price_{r['id']}" value="{r['price']}" min="0" step="50"
                           class="r-input" style="width:90px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>₽</span>
                </div>
            </td>
            <td style="padding:0.6rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="type_duration_{r['id']}" value="{r['duration']}" min="0" step="5"
                           class="r-input" style="width:75px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>мин</span>
                </div>
            </td>
        </tr>
        """
        for r in type_rows
    )

    # Таблица густоты
    density_table_html = "".join(
        f"""
        <tr>
            <td style="padding:0.6rem 0.75rem;font-weight:600;">
                {e(r['title'])}
                <div style="font-size:11px;color:var(--color-muted);font-weight:normal;">{e(r['desc'])}</div>
            </td>
            <td style="padding:0.6rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="density_price_{r['id']}" value="{r['price']}" min="0" step="50"
                           class="r-input" style="width:90px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>₽</span>
                </div>
            </td>
            <td style="padding:0.6rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="density_duration_{r['id']}" value="{r['duration']}" min="0" step="5"
                           class="r-input" style="width:75px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>мин</span>
                </div>
            </td>
        </tr>
        """
        for r in density_rows
    )

    # Таблица вопросов / особенностей
    tag_rows_html = "".join(
        f"""
        <tr class="custom-tag-row">
            <td style="padding:0.5rem 0.75rem;">
                <input type="text" name="tag_name" value="{e(t['name'])}"
                       class="r-input" style="width:100%;padding:0.35rem 0.5rem;font-size:0.875rem;">
            </td>
            <td style="padding:0.5rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="tag_price" value="{t.get('price', 0)}" min="0" step="50"
                           class="r-input" style="width:85px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>₽</span>
                </div>
            </td>
            <td style="padding:0.5rem 0.75rem;">
                <div style="display:inline-flex;align-items:center;gap:4px;">
                    <span style="color:var(--color-muted);">+</span>
                    <input type="number" name="tag_duration" value="{t.get('duration', 0)}" min="0" step="5"
                           class="r-input" style="width:70px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                    <span>мин</span>
                </div>
            </td>
            <td style="padding:0.5rem 0.75rem;text-align:center;">
                <button type="button" class="btn-outline" onclick="removeTagRow(this)" style="padding:0.25rem 0.6rem;color:var(--color-danger);border-color:var(--color-danger);">
                    ×
                </button>
            </td>
        </tr>
        """
        for t in tag_items
    )

    return f"""
    <div id="tab-interactive" class="tab-content">
        {ok_banner}

        <div style="margin-bottom:1.5rem;">
            <h2 style="margin:0 0 0.4rem;font-size:1.4rem;display:flex;align-items:center;gap:0.6rem;">
                <span>{ICON_SLIDERS}</span>
                <span>Интерактивная запись (анкета перед визитом)</span>
            </h2>
            <p class="text-muted" style="margin:0;font-size:0.95rem;max-width:760px;line-height:1.45;">
                Например, клиент перед выбором времени указывает длину (в см), структуру и историю волос. И Вы заранее знаете точный расход состава, стоимость и тайминг.
            </p>
        </div>

        {master_selector_html}

        <form method="post" action="/api/v1/masters/{target_master.id}/hair-survey" id="interactiveSurveyForm">
            <input type="hidden" name="return_url" value="/business/dashboard?salon_id={salon.id}&tab=interactive&master_id={target_master.id}&ok=1">

            <!-- Главный переключатель -->
            <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;background:var(--color-surface);">
                <div style="display:flex;align-items:center;gap:0.75rem;">
                    <input type="checkbox" id="interactiveToggle" name="enabled" value="1"
                           {"checked" if is_enabled else ""}
                           onchange="document.getElementById('interactiveSettingsBody').style.display = this.checked ? 'block' : 'none';"
                           style="width:1.3rem;height:1.3rem;cursor:pointer;">
                    <label for="interactiveToggle" style="font-weight:600;font-size:1rem;cursor:pointer;">
                        Включить интерактивный опрос перед выбором времени для мастера {e(master_display_name)}
                    </label>
                </div>
            </div>

            <div id="interactiveSettingsBody" style="display:{'block' if is_enabled else 'none'};">
                <input type="hidden" name="custom_questions_json" id="customQuestionsJson" value="">

                <!-- 1. Длина волос -->
                <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;padding-bottom:0.75rem;border-bottom:1px solid var(--color-border);">
                        <div>
                            <h3 style="margin:0 0 0.25rem;font-size:1.15rem;">
                                1. Длина волос (интерактивная шкала с ползунком)
                            </h3>
                            <p class="text-muted" style="margin:0;font-size:0.875rem;">
                                Клиент перемещает ползунок по шкале, и в реальном времени сменяется иллюстрация длины.
                            </p>
                        </div>
                        <label style="display:inline-flex;align-items:center;gap:0.5rem;cursor:pointer;font-weight:600;font-size:0.9rem;background:var(--color-surface-alt);padding:0.4rem 0.75rem;border-radius:var(--radius-8);border:1px solid var(--color-border);">
                            <input type="checkbox" name="q_length_enabled" id="qLengthToggle" value="1"
                                   {"checked" if q_length_enabled else ""}
                                   onchange="toggleQuestionBlock('qLengthBody', this.checked);"
                                   style="width:1.15rem;height:1.15rem;cursor:pointer;">
                            <span>Включить этот вопрос в опрос</span>
                        </label>
                    </div>

                    <div id="qLengthBody" style="opacity:{'1' if q_length_enabled else '0.35'};pointer-events:{'auto' if q_length_enabled else 'none'};transition:opacity 0.2s ease;">
                        <!-- Интерактивное превью шкалы в настройках -->
                        <div style="background:var(--color-surface-alt);border:1px solid var(--color-border);border-radius:var(--radius-16);padding:1rem;margin-bottom:1.25rem;">
                            <div style="font-size:0.8rem;font-weight:700;color:var(--color-muted);text-transform:uppercase;margin-bottom:0.75rem;">
                                Интерактивное превью виджета клиента:
                            </div>
                            <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:1.5rem;margin-bottom:1rem;">
                                <div style="width:130px;height:130px;border-radius:var(--radius-16);overflow:hidden;background:var(--color-surface-alt);border:1px solid var(--color-border);display:flex;align-items:center;justify-content:center;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
                                    <img id="adminLengthPreviewImg" src="/static/images/hair/hair_len_4.webp" alt="Иллюстрация длины" style="max-width:115px;max-height:115px;object-fit:contain;display:block;margin:0 auto;">
                                </div>
                                <div style="flex:1;min-width:240px;max-width:460px;">
                                    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.5rem;">
                                        <strong id="adminLengthPreviewTitle" style="font-size:1rem;color:var(--color-heading);">Средние (до лопаток)</strong>
                                        <span id="adminLengthPreviewCm" style="font-size:0.85rem;color:var(--color-accent-text);font-weight:600;">~40–45 см</span>
                                    </div>
                                    <input type="range" min="1" max="7" step="1" value="4" id="adminLengthSlider"
                                           class="hair-range" style="width:100%;cursor:pointer;"
                                           oninput="updateAdminLengthPreview(this.value);">
                                    <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--color-muted);margin-top:4px;">
                                        <span>Пикси</span>
                                        <span>До плеч</span>
                                        <span>До талии</span>
                                        <span>80+ см</span>
                                    </div>
                                </div>
                            </div>

                            <!-- Полоса со всеми вариантами длины -->
                            <div style="text-align:center;">
                                <div style="font-size:0.75rem;color:var(--color-muted);margin-bottom:4px;">Все варианты длины волос (иллюстрация со шкалой):</div>
                                <img src="/static/images/hair/hair_lengths_strip.webp" alt="Все длины волос" style="max-width:100%;height:auto;border-radius:var(--radius-8);border:1px solid var(--color-border);">
                            </div>
                        </div>

                        <!-- Таблица правил длины -->
                        <div style="overflow-x:auto;">
                            <table style="width:100%;border-collapse:collapse;font-size:0.875rem;">
                                <thead>
                                    <tr style="border-bottom:2px solid var(--color-border);text-align:left;color:var(--color-muted);font-size:0.8rem;text-transform:uppercase;">
                                        <th style="padding:0.5rem 0.75rem;">Длина волос</th>
                                        <th style="padding:0.5rem 0.75rem;">Диапазон</th>
                                        <th style="padding:0.5rem 0.75rem;">Доплата к услуге</th>
                                        <th style="padding:0.5rem 0.75rem;">Добавочное время</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {length_table_html}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- 2. Густота волос (плитка) -->
                <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;padding-bottom:0.75rem;border-bottom:1px solid var(--color-border);">
                        <div>
                            <h3 style="margin:0 0 0.25rem;font-size:1.15rem;">
                                2. Густота волос (плитка выбора вариантов)
                            </h3>
                            <p class="text-muted" style="margin:0;font-size:0.875rem;">
                                Клиент видит каждый вариант в виде наглядной плитки с отдельной иллюстрацией.
                            </p>
                        </div>
                        <label style="display:inline-flex;align-items:center;gap:0.5rem;cursor:pointer;font-weight:600;font-size:0.9rem;background:var(--color-surface-alt);padding:0.4rem 0.75rem;border-radius:var(--radius-8);border:1px solid var(--color-border);">
                            <input type="checkbox" name="q_density_enabled" id="qDensityToggle" value="1"
                                   {"checked" if q_density_enabled else ""}
                                   onchange="toggleQuestionBlock('qDensityBody', this.checked);"
                                   style="width:1.15rem;height:1.15rem;cursor:pointer;">
                            <span>Включить этот вопрос в опрос</span>
                        </label>
                    </div>

                    <div id="qDensityBody" style="opacity:{'1' if q_density_enabled else '0.35'};pointer-events:{'auto' if q_density_enabled else 'none'};transition:opacity 0.2s ease;">
                        <!-- Превью плиток густоты -->
                        <div style="background:var(--color-surface-alt);border:1px solid var(--color-border);border-radius:var(--radius-16);padding:1rem;margin-bottom:1.25rem;">
                            <div style="font-size:0.8rem;font-weight:700;color:var(--color-muted);text-transform:uppercase;margin-bottom:0.75rem;">
                                Превью плиток клиента:
                            </div>
                            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:0.75rem;max-width:560px;">
                                <div style="border:1.5px solid var(--color-border);border-radius:var(--radius-16);padding:0.5rem;text-align:center;background:var(--color-surface);">
                                    <div style="height:90px;display:flex;align-items:center;justify-content:center;background:var(--color-surface-alt);border-radius:var(--radius-8);margin-bottom:0.35rem;">
                                        <img src="/static/images/hair/hair_density_thin.webp" alt="Не густые" style="max-height:80px;max-width:90%;object-fit:contain;">
                                    </div>
                                    <strong style="font-size:0.8rem;display:block;">Не густые</strong>
                                    <small style="font-size:11px;color:var(--color-muted);">Тонкий хвост</small>
                                </div>
                                <div style="border:1.5px solid var(--color-accent);border-radius:var(--radius-16);padding:0.5rem;text-align:center;background:var(--color-accent-light);box-shadow:0 0 0 1px var(--color-accent);">
                                    <div style="height:90px;display:flex;align-items:center;justify-content:center;background:var(--color-surface-alt);border-radius:var(--radius-8);margin-bottom:0.35rem;">
                                        <img src="/static/images/hair/hair_density_medium.webp" alt="Средняя густота" style="max-height:80px;max-width:90%;object-fit:contain;">
                                    </div>
                                    <strong style="font-size:0.8rem;display:block;">Средняя густота</strong>
                                    <small style="font-size:11px;color:var(--color-muted);">Стандартная</small>
                                </div>
                                <div style="border:1.5px solid var(--color-border);border-radius:var(--radius-16);padding:0.5rem;text-align:center;background:var(--color-surface);">
                                    <div style="height:90px;display:flex;align-items:center;justify-content:center;background:var(--color-surface-alt);border-radius:var(--radius-8);margin-bottom:0.35rem;">
                                        <img src="/static/images/hair/hair_density_thick.webp" alt="Очень густые" style="max-height:80px;max-width:90%;object-fit:contain;">
                                    </div>
                                    <strong style="font-size:0.8rem;display:block;">Очень густые</strong>
                                    <small style="font-size:11px;color:var(--color-muted);">Объемный хвост</small>
                                </div>
                            </div>
                        </div>

                        <div style="overflow-x:auto;">
                            <table style="width:100%;border-collapse:collapse;font-size:0.875rem;">
                                <thead>
                                    <tr style="border-bottom:2px solid var(--color-border);text-align:left;color:var(--color-muted);font-size:0.8rem;text-transform:uppercase;">
                                        <th style="padding:0.5rem 0.75rem;">Густота</th>
                                        <th style="padding:0.5rem 0.75rem;">Доплата к услуге</th>
                                        <th style="padding:0.5rem 0.75rem;">Добавочное время</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {density_table_html}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- 3. Тип и структура волос (плитка) -->
                <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;padding-bottom:0.75rem;border-bottom:1px solid var(--color-border);">
                        <div>
                            <h3 style="margin:0 0 0.25rem;font-size:1.15rem;">
                                3. Тип и структура волос (плитка выбора вариантов)
                            </h3>
                            <p class="text-muted" style="margin:0;font-size:0.875rem;">
                                Позволяет клиенту выбрать структуру волос плиткой с иллюстрацией.
                            </p>
                        </div>
                        <label style="display:inline-flex;align-items:center;gap:0.5rem;cursor:pointer;font-weight:600;font-size:0.9rem;background:var(--color-surface-alt);padding:0.4rem 0.75rem;border-radius:var(--radius-8);border:1px solid var(--color-border);">
                            <input type="checkbox" name="q_type_enabled" id="qTypeToggle" value="1"
                                   {"checked" if q_type_enabled else ""}
                                   onchange="toggleQuestionBlock('qTypeBody', this.checked);"
                                   style="width:1.15rem;height:1.15rem;cursor:pointer;">
                            <span>Включить этот вопрос в опрос</span>
                        </label>
                    </div>

                    <div id="qTypeBody" style="opacity:{'1' if q_type_enabled else '0.35'};pointer-events:{'auto' if q_type_enabled else 'none'};transition:opacity 0.2s ease;">
                        <!-- Превью плиток типов волос -->
                        <div style="background:var(--color-surface-alt);border:1px solid var(--color-border);border-radius:var(--radius-16);padding:1rem;margin-bottom:1.25rem;">
                            <div style="font-size:0.8rem;font-weight:700;color:var(--color-muted);text-transform:uppercase;margin-bottom:0.75rem;">
                                Превью плиток клиента:
                            </div>
                            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:0.75rem;max-width:720px;">
                                <div style="border:1.5px solid var(--color-accent);border-radius:var(--radius-16);padding:0.5rem;text-align:center;background:var(--color-accent-light);box-shadow:0 0 0 1px var(--color-accent);">
                                    <div style="height:90px;display:flex;align-items:center;justify-content:center;background:var(--color-surface-alt);border-radius:var(--radius-8);margin-bottom:0.35rem;">
                                        <img src="/static/images/hair/hair_type_straight.webp" alt="Прямые" style="max-height:80px;max-width:90%;object-fit:contain;">
                                    </div>
                                    <strong style="font-size:0.8rem;display:block;">Прямые</strong>
                                    <small style="font-size:11px;color:var(--color-muted);">Гладкие</small>
                                </div>
                                <div style="border:1.5px solid var(--color-border);border-radius:var(--radius-16);padding:0.5rem;text-align:center;background:var(--color-surface);">
                                    <div style="height:90px;display:flex;align-items:center;justify-content:center;background:var(--color-surface-alt);border-radius:var(--radius-8);margin-bottom:0.35rem;">
                                        <img src="/static/images/hair/hair_type_wavy.webp" alt="Легкая волна" style="max-height:80px;max-width:90%;object-fit:contain;">
                                    </div>
                                    <strong style="font-size:0.8rem;display:block;">Легкая волна</strong>
                                    <small style="font-size:11px;color:var(--color-muted);">Пушатся</small>
                                </div>
                                <div style="border:1.5px solid var(--color-border);border-radius:var(--radius-16);padding:0.5rem;text-align:center;background:var(--color-surface);">
                                    <div style="height:90px;display:flex;align-items:center;justify-content:center;background:var(--color-surface-alt);border-radius:var(--radius-8);margin-bottom:0.35rem;">
                                        <img src="/static/images/hair/hair_type_curly.webp" alt="Кудрявые" style="max-height:80px;max-width:90%;object-fit:contain;">
                                    </div>
                                    <strong style="font-size:0.8rem;display:block;">Кудрявые</strong>
                                    <small style="font-size:11px;color:var(--color-muted);">Четкий завиток</small>
                                </div>
                                <div style="border:1.5px solid var(--color-border);border-radius:var(--radius-16);padding:0.5rem;text-align:center;background:var(--color-surface);">
                                    <div style="height:90px;display:flex;align-items:center;justify-content:center;background:var(--color-surface-alt);border-radius:var(--radius-8);margin-bottom:0.35rem;">
                                        <img src="/static/images/hair/hair_type_coarse.webp" alt="Стекловидные" style="max-height:80px;max-width:90%;object-fit:contain;">
                                    </div>
                                    <strong style="font-size:0.8rem;display:block;">Жесткие</strong>
                                    <small style="font-size:11px;color:var(--color-muted);">Стекловидные</small>
                                </div>
                            </div>
                        </div>

                        <div style="overflow-x:auto;">
                            <table style="width:100%;border-collapse:collapse;font-size:0.875rem;">
                                <thead>
                                    <tr style="border-bottom:2px solid var(--color-border);text-align:left;color:var(--color-muted);font-size:0.8rem;text-transform:uppercase;">
                                        <th style="padding:0.5rem 0.75rem;">Тип волос</th>
                                        <th style="padding:0.5rem 0.75rem;">Доплата к услуге</th>
                                        <th style="padding:0.5rem 0.75rem;">Добавочное время</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {type_table_html}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- 4. Вопросы анкеты / особенности и история волос -->
                <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;padding-bottom:0.75rem;border-bottom:1px solid var(--color-border);">
                        <div>
                            <h3 style="margin:0 0 0.25rem;font-size:1.15rem;">
                                4. Особенности и история волос (быстрые теги галочками)
                            </h3>
                            <p class="text-muted" style="margin:0;font-size:0.875rem;">
                                Клиент отмечает подходящие пункты из списка особенностей.
                            </p>
                        </div>
                        <label style="display:inline-flex;align-items:center;gap:0.5rem;cursor:pointer;font-weight:600;font-size:0.9rem;background:var(--color-surface-alt);padding:0.4rem 0.75rem;border-radius:var(--radius-8);border:1px solid var(--color-border);">
                            <input type="checkbox" name="q_tags_enabled" id="qTagsToggle" value="1"
                                   {"checked" if q_tags_enabled else ""}
                                   onchange="toggleQuestionBlock('qTagsBody', this.checked);"
                                   style="width:1.15rem;height:1.15rem;cursor:pointer;">
                            <span>Включить этот вопрос в опрос</span>
                        </label>
                    </div>

                    <div id="qTagsBody" style="opacity:{'1' if q_tags_enabled else '0.35'};pointer-events:{'auto' if q_tags_enabled else 'none'};transition:opacity 0.2s ease;">
                        <div style="overflow-x:auto;margin-bottom:1rem;">
                            <table style="width:100%;border-collapse:collapse;font-size:0.875rem;" id="customTagsTable">
                                <thead>
                                    <tr style="border-bottom:2px solid var(--color-border);text-align:left;color:var(--color-muted);font-size:0.8rem;text-transform:uppercase;">
                                        <th style="padding:0.5rem 0.75rem;">Пункт анкеты (особенность / история)</th>
                                        <th style="padding:0.5rem 0.75rem;">Доплата</th>
                                        <th style="padding:0.5rem 0.75rem;">Добавочное время</th>
                                        <th style="padding:0.5rem 0.75rem;width:40px;"></th>
                                    </tr>
                                </thead>
                                <tbody id="customTagsTbody">
                                    {tag_rows_html}
                                </tbody>
                            </table>
                        </div>

                        <!-- Форма добавления нового тега -->
                        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;background:var(--color-surface-alt);padding:0.75rem;border-radius:var(--radius-8);border:1px dashed var(--color-border);">
                            <input type="text" id="newQuestionName" placeholder="Новый тег (напр. «Была хна»)..."
                                   class="r-input" style="flex:1;min-width:200px;padding:0.4rem 0.6rem;font-size:0.875rem;">
                            <div style="display:inline-flex;align-items:center;gap:4px;">
                                <span>+</span>
                                <input type="number" id="newQuestionPrice" placeholder="0" min="0" step="50"
                                       class="r-input" style="width:85px;padding:0.4rem 0.5rem;font-size:0.875rem;">
                                <span>₽</span>
                            </div>
                            <div style="display:inline-flex;align-items:center;gap:4px;">
                                <span>+</span>
                                <input type="number" id="newQuestionDuration" placeholder="0" min="0" step="5"
                                       class="r-input" style="width:70px;padding:0.4rem 0.5rem;font-size:0.875rem;">
                                <span>мин</span>
                            </div>
                            <button type="button" class="btn-primary" onclick="addCustomQuestionRow();" style="padding:0.4rem 0.9rem;font-size:0.875rem;white-space:nowrap;">
                                {ICON_PLUS_SMALL} Добавить тег
                            </button>
                        </div>
                    </div>
                </div>

                <!-- 5. Конструктор произвольных вопросов (как в Google Формах) -->
                <div class="card" style="padding:1.25rem;margin-bottom:1.5rem;background:var(--color-surface-alt);border:1.5px solid var(--color-border);">
                    <div style="margin-bottom:1.25rem;">
                        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
                            <h3 style="margin:0 0 0.25rem;font-size:1.2rem;display:flex;align-items:center;gap:0.5rem;">
                                <span>📋</span>
                                <span>5. Конструктор вопросов и вариантов ответов (как в Google Формах)</span>
                            </h3>
                            <button type="button" class="btn-primary" onclick="addGoogleQuestion();" style="padding:0.45rem 1rem;font-size:0.875rem;">
                                {ICON_PLUS_SMALL} Добавить вопрос
                            </button>
                        </div>
                        <p class="text-muted" style="margin:0.25rem 0 0;font-size:0.875rem;max-width:780px;">
                            Создавайте любые свои вопросы: один из списка (радиокнопки), несколько из списка (чекбоксы) или текстовый ответ. К каждому варианту ответа можно привязать надбавку к цене и добавочное время визита.
                        </p>
                    </div>

                    <div id="googleQuestionsList" style="display:flex;flex-direction:column;gap:1rem;margin-bottom:1rem;">
                        <!-- Карточки вопросов будут генерироваться скриптом -->
                    </div>

                    <div style="text-align:center;padding:1rem;background:var(--color-surface);border:2px dashed var(--color-border);border-radius:var(--radius-16);">
                        <button type="button" class="btn-outline" onclick="addGoogleQuestion();" style="font-weight:600;padding:0.5rem 1.25rem;">
                            + Добавить ещё один вопрос в опрос
                        </button>
                    </div>
                </div>

                <!-- Кнопка сохранения -->
                <div style="display:flex;justify-content:flex-end;margin-top:1.5rem;">
                    <button type="submit" class="btn-primary" style="padding:0.75rem 2rem;font-size:1rem;font-weight:600;">
                        Сохранить настройки интерактивной записи
                    </button>
                </div>
            </div>
        </form>

        <script>
        const INITIAL_CUSTOM_QUESTIONS = {custom_questions_json_str};
        let googleQuestions = Array.isArray(INITIAL_CUSTOM_QUESTIONS) ? JSON.parse(JSON.stringify(INITIAL_CUSTOM_QUESTIONS)) : [];

        function toggleQuestionBlock(elemId, isChecked) {{
            const el = document.getElementById(elemId);
            if (!el) return;
            el.style.opacity = isChecked ? '1' : '0.35';
            el.style.pointerEvents = isChecked ? 'auto' : 'none';
        }}

        const LENGTH_PREVIEWS = {{
            1: {{ title: "Очень короткие (пикси)", cm: "до 15 см", img: "/static/images/hair/hair_len_1.webp" }},
            2: {{ title: "Короткие (боб / каре)", cm: "~20 см", img: "/static/images/hair/hair_len_2.webp" }},
            3: {{ title: "До плеч", cm: "~30 см", img: "/static/images/hair/hair_len_3.webp" }},
            4: {{ title: "Средние (до лопаток)", cm: "~40–45 см", img: "/static/images/hair/hair_len_4.webp" }},
            5: {{ title: "Длинные (до талии)", cm: "~55–60 см", img: "/static/images/hair/hair_len_5.webp" }},
            6: {{ title: "Очень длинные (до ягодиц)", cm: "~70–75 см", img: "/static/images/hair/hair_len_6.webp" }},
            7: {{ title: "Экстремально длинные (ниже бедер)", cm: "от 80 см", img: "/static/images/hair/hair_len_7.webp" }}
        }};

        function updateAdminLengthPreview(val) {{
            const item = LENGTH_PREVIEWS[val] || LENGTH_PREVIEWS[4];
            document.getElementById('adminLengthPreviewImg').src = item.img;
            document.getElementById('adminLengthPreviewTitle').textContent = item.title;
            document.getElementById('adminLengthPreviewCm').textContent = item.cm;
        }}

        function removeTagRow(btn) {{
            const tr = btn.closest('tr');
            if (tr) tr.remove();
        }}

        function addCustomQuestionRow() {{
            const nameEl = document.getElementById('newQuestionName');
            const priceEl = document.getElementById('newQuestionPrice');
            const durEl = document.getElementById('newQuestionDuration');
            const name = (nameEl.value || '').trim();
            if (!name) {{
                nameEl.focus();
                return;
            }}
            const price = parseInt(priceEl.value, 10) || 0;
            const dur = parseInt(durEl.value, 10) || 0;

            const tbody = document.getElementById('customTagsTbody');
            const tr = document.createElement('tr');
            tr.className = 'custom-tag-row';
            tr.innerHTML = `
                <td style="padding:0.5rem 0.75rem;">
                    <input type="text" name="tag_name" value="${{name.replace(/"/g, '&quot;')}}"
                           class="r-input" style="width:100%;padding:0.35rem 0.5rem;font-size:0.875rem;">
                </td>
                <td style="padding:0.5rem 0.75rem;">
                    <div style="display:inline-flex;align-items:center;gap:4px;">
                        <span style="color:var(--color-muted);">+</span>
                        <input type="number" name="tag_price" value="${{price}}" min="0" step="50"
                               class="r-input" style="width:85px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                        <span>₽</span>
                    </div>
                </td>
                <td style="padding:0.5rem 0.75rem;">
                    <div style="display:inline-flex;align-items:center;gap:4px;">
                        <span style="color:var(--color-muted);">+</span>
                        <input type="number" name="tag_duration" value="${{dur}}" min="0" step="5"
                               class="r-input" style="width:70px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                        <span>мин</span>
                    </div>
                </td>
                <td style="padding:0.5rem 0.75rem;text-align:center;">
                    <button type="button" class="btn-outline" onclick="removeTagRow(this)" style="padding:0.25rem 0.6rem;color:var(--color-danger);border-color:var(--color-danger);">
                        ×
                    </button>
                </td>
            `;
            tbody.appendChild(tr);

            nameEl.value = '';
            priceEl.value = '';
            durEl.value = '';
            nameEl.focus();
        }}

        // ==========================================
        // Конструктор вопросов Google Forms
        // ==========================================
        function syncGoogleQuestionsJson() {{
            const hidden = document.getElementById('customQuestionsJson');
            if (hidden) {{
                hidden.value = JSON.stringify(googleQuestions);
            }}
        }}

        function renderGoogleQuestions() {{
            const list = document.getElementById('googleQuestionsList');
            if (!list) return;
            if (googleQuestions.length === 0) {{
                list.innerHTML = `
                    <div style="text-align:center;padding:1.5rem;color:var(--color-muted);background:var(--color-surface);border-radius:var(--radius-8);border:1px dashed var(--color-border);">
                        Пока нет созданных вопросов. Нажмите «+ Добавить вопрос», чтобы добавить опрос о предыдущих окрашиваниях, аллергии или желаемом результате.
                    </div>
                `;
                syncGoogleQuestionsJson();
                return;
            }}

            list.innerHTML = googleQuestions.map(function (q, qIdx) {{
                const type = q.type || 'single';
                const isSingle = type === 'single';
                const isMulti = type === 'multiple';
                const isText = type === 'text';
                const enabled = q.enabled !== false;
                const required = Boolean(q.required);
                const options = q.options || [];

                let optionsHtml = '';
                if (isSingle || isMulti) {{
                    const icon = isSingle ? '⚪' : '◻️';
                    optionsHtml = `
                        <div style="margin-top:0.75rem;display:flex;flex-direction:column;gap:0.5rem;">
                            <div style="font-size:0.8rem;font-weight:700;color:var(--color-muted);text-transform:uppercase;">
                                Варианты ответов:
                            </div>
                            ${{options.map(function (opt, oIdx) {{
                                return `
                                    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;background:var(--color-surface-alt);padding:0.4rem 0.6rem;border-radius:var(--radius-8);border:1px solid var(--color-border);">
                                        <span style="opacity:0.6;font-size:12px;">${{icon}}</span>
                                        <input type="text" value="${{(opt.title || '').replace(/"/g, '&quot;')}}"
                                               placeholder="Вариант ответа..."
                                               oninput="updateOptionField(${{qIdx}}, ${{oIdx}}, 'title', this.value);"
                                               class="r-input" style="flex:1;min-width:180px;padding:0.35rem 0.5rem;font-size:0.875rem;">
                                        <div style="display:inline-flex;align-items:center;gap:3px;">
                                            <span style="font-size:12px;color:var(--color-muted);">+</span>
                                            <input type="number" value="${{opt.price || 0}}" min="0" step="50"
                                                   placeholder="0"
                                                   oninput="updateOptionField(${{qIdx}}, ${{oIdx}}, 'price', parseInt(this.value, 10) || 0);"
                                                   class="r-input" style="width:75px;padding:0.35rem 0.4rem;font-size:0.875rem;">
                                            <span style="font-size:12px;">₽</span>
                                        </div>
                                        <div style="display:inline-flex;align-items:center;gap:3px;">
                                            <span style="font-size:12px;color:var(--color-muted);">+</span>
                                            <input type="number" value="${{opt.duration || 0}}" min="0" step="5"
                                                   placeholder="0"
                                                   oninput="updateOptionField(${{qIdx}}, ${{oIdx}}, 'duration', parseInt(this.value, 10) || 0);"
                                                   class="r-input" style="width:65px;padding:0.35rem 0.4rem;font-size:0.875rem;">
                                            <span style="font-size:12px;">мин</span>
                                        </div>
                                        <button type="button" class="btn-outline" onclick="deleteOption(${{qIdx}}, ${{oIdx}});"
                                                title="Удалить вариант"
                                                style="padding:0.25rem 0.55rem;color:var(--color-danger);border-color:var(--color-danger);font-size:14px;line-height:1;">
                                            ×
                                        </button>
                                    </div>
                                `;
                            }}).join('')}}
                            <div style="margin-top:0.25rem;">
                                <button type="button" class="btn-outline" onclick="addOptionToQuestion(${{qIdx}});"
                                        style="font-size:0.8125rem;padding:0.3rem 0.75rem;">
                                    + Добавить вариант ответа
                                </button>
                            </div>
                        </div>
                    `;
                }} else {{
                    optionsHtml = `
                        <div style="margin-top:0.75rem;padding:0.6rem 0.75rem;background:var(--color-surface-alt);border-radius:var(--radius-8);border:1px dashed var(--color-border);color:var(--color-muted);font-size:0.85rem;">
                            Клиент сможет ввести произвольный краткий текстовый ответ на этот вопрос.
                        </div>
                    `;
                }}

                return `
                    <div class="card" style="padding:1.1rem;background:var(--color-surface);border:1.5px solid var(--color-border);box-shadow:0 1px 3px rgba(0,0,0,0.04);position:relative;">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;gap:0.5rem;flex-wrap:wrap;">
                            <div style="display:flex;align-items:center;gap:0.5rem;">
                                <span style="font-weight:700;font-size:0.875rem;background:var(--color-surface-alt);padding:0.2rem 0.5rem;border-radius:var(--radius-8);color:var(--color-heading);">
                                    Вопрос #${{qIdx + 1}}
                                </span>
                            </div>
                            <div style="display:flex;align-items:center;gap:1rem;">
                                <label style="display:inline-flex;align-items:center;gap:0.35rem;font-size:0.85rem;cursor:pointer;">
                                    <input type="checkbox" ${{enabled ? 'checked' : ''}}
                                           onchange="updateQuestionField(${{qIdx}}, 'enabled', this.checked);">
                                    <span>Включен</span>
                                </label>
                                <label style="display:inline-flex;align-items:center;gap:0.35rem;font-size:0.85rem;cursor:pointer;">
                                    <input type="checkbox" ${{required ? 'checked' : ''}}
                                           onchange="updateQuestionField(${{qIdx}}, 'required', this.checked);">
                                    <span>Обязательный</span>
                                </label>
                                <button type="button" onclick="deleteGoogleQuestion(${{qIdx}});"
                                        title="Удалить вопрос"
                                        style="background:none;border:none;cursor:pointer;color:var(--color-danger);font-size:1.1rem;padding:0.2rem;"
                                        aria-label="Удалить вопрос">
                                    🗑️
                                </button>
                            </div>
                        </div>

                        <div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:0.6rem;">
                            <div style="flex:1;min-width:260px;">
                                <input type="text" value="${{(q.title || '').replace(/"/g, '&quot;')}}"
                                       placeholder="Текст вопроса (напр. «Какое окрашивание было последним?»)..."
                                       oninput="updateQuestionField(${{qIdx}}, 'title', this.value);"
                                       class="r-input" style="width:100%;font-size:0.95rem;font-weight:600;padding:0.45rem 0.65rem;">
                            </div>
                            <div style="width:200px;">
                                <select class="custom-select" onchange="updateQuestionField(${{qIdx}}, 'type', this.value);" style="width:100%;padding:0.45rem 0.6rem;font-size:0.875rem;">
                                    <option value="single" ${{isSingle ? 'selected' : ''}}>Один из списка (радио)</option>
                                    <option value="multiple" ${{isMulti ? 'selected' : ''}}>Несколько из списка (чекбоксы)</option>
                                    <option value="text" ${{isText ? 'selected' : ''}}>Текстовый ответ</option>
                                </select>
                            </div>
                        </div>

                        <div style="margin-bottom:0.5rem;">
                            <input type="text" value="${{(q.desc || '').replace(/"/g, '&quot;')}}"
                                   placeholder="Подсказка для клиента (необязательно)..."
                                   oninput="updateQuestionField(${{qIdx}}, 'desc', this.value);"
                                   class="r-input" style="width:100%;font-size:0.825rem;padding:0.35rem 0.6rem;color:var(--color-muted);">
                        </div>

                        ${{optionsHtml}}
                    </div>
                `;
            }}).join('');

            syncGoogleQuestionsJson();
        }}

        function addGoogleQuestion() {{
            const newId = 'cq_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
            googleQuestions.push({{
                id: newId,
                title: '',
                desc: '',
                type: 'single',
                enabled: true,
                required: false,
                options: [
                    {{ id: 'opt_1', title: 'Вариант 1', price: 0, duration: 0 }},
                    {{ id: 'opt_2', title: 'Вариант 2', price: 0, duration: 0 }}
                ]
            }});
            renderGoogleQuestions();
        }}

        function deleteGoogleQuestion(qIdx) {{
            if (confirm('Удалить этот вопрос из опроса?')) {{
                googleQuestions.splice(qIdx, 1);
                renderGoogleQuestions();
            }}
        }}

        function updateQuestionField(qIdx, field, value) {{
            if (!googleQuestions[qIdx]) return;
            googleQuestions[qIdx][field] = value;
            if (field === 'type') {{
                if ((value === 'single' || value === 'multiple') && (!googleQuestions[qIdx].options || googleQuestions[qIdx].options.length === 0)) {{
                    googleQuestions[qIdx].options = [
                        {{ id: 'opt_1', title: 'Вариант 1', price: 0, duration: 0 }}
                    ];
                }}
                renderGoogleQuestions();
            }} else {{
                syncGoogleQuestionsJson();
            }}
        }}

        function addOptionToQuestion(qIdx) {{
            if (!googleQuestions[qIdx]) return;
            if (!googleQuestions[qIdx].options) googleQuestions[qIdx].options = [];
            const nextNum = googleQuestions[qIdx].options.length + 1;
            googleQuestions[qIdx].options.push({{
                id: 'opt_' + Date.now() + '_' + nextNum,
                title: 'Вариант ' + nextNum,
                price: 0,
                duration: 0
            }});
            renderGoogleQuestions();
        }}

        function deleteOption(qIdx, oIdx) {{
            if (!googleQuestions[qIdx] || !googleQuestions[qIdx].options) return;
            googleQuestions[qIdx].options.splice(oIdx, 1);
            renderGoogleQuestions();
        }}

        function updateOptionField(qIdx, oIdx, field, value) {{
            if (!googleQuestions[qIdx] || !googleQuestions[qIdx].options || !googleQuestions[qIdx].options[oIdx]) return;
            googleQuestions[qIdx].options[oIdx][field] = value;
            syncGoogleQuestionsJson();
        }}

        document.addEventListener('DOMContentLoaded', function () {{
            renderGoogleQuestions();
            const form = document.getElementById('interactiveSurveyForm');
            if (form) {{
                form.addEventListener('submit', function () {{
                    syncGoogleQuestionsJson();
                }});
            }}
        }});
        if (document.readyState !== 'loading') {{
            renderGoogleQuestions();
            const form = document.getElementById('interactiveSurveyForm');
            if (form) {{
                form.addEventListener('submit', function () {{
                    syncGoogleQuestionsJson();
                }});
            }}
        }}
        </script>
    </div>
    """
