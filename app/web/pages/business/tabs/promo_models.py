# app/web/pages/business/tabs/promo_models.py
"""Вкладка «Модели»: два саб-таба — «Свайп моделей» (карточка-стек по
конкретной опубликованной услуге + живой список мэтчей, ждущих выбора
времени моделью) и «Опубликовать поиск» (мастер+услуга+квота+дата в одной
форме, список опубликованных поисков с числом откликов). Мэтч сразу даёт
право модели выбрать реальный свободный слот — оффера как отдельного шага
нет, цена/длительность уже зафиксированы услугой.
См. app/services/model_matching_service.py и app/api/v1/endpoints/model_matching.py."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ModelMatch, Service
from app.services.model_matching_service import count_booked_for_service, is_service_open_for_models


async def render_promo_models_tab(db: AsyncSession, salon, masters) -> str:
    """masters — список Master салона (уже загружен на уровне дашборда)."""

    practice_cards_html = ""
    service_options_swipe = ""
    for m in masters:
        rows = (await db.execute(
            select(Service).where(Service.master_id == m.id, Service.is_active == True, Service.is_model_practice == True)  # noqa: E712
        )).scalars().all()
        for s in rows:
            booked_count = await count_booked_for_service(db, s.id)
            is_open = is_service_open_for_models(s, booked_count)
            responses_count = (await db.execute(
                select(func.count(ModelMatch.id)).where(
                    ModelMatch.service_id == s.id, ModelMatch.model_liked == True,  # noqa: E712
                )
            )).scalar() or 0
            quota_label = f"{booked_count}/{s.model_quota}" if s.model_quota else f"{booked_count}/∞"
            date_label = s.model_desired_date.strftime("%d.%m.%Y") if s.model_desired_date else ""
            status_badge = (
                '<span class="badge-tag" style="background:#d1fae5;color:#065f46">открыт</span>' if is_open else
                '<span class="badge-tag" style="background:#fee2e2;color:#991b1b">закрыт</span>'
            )
            toggle_label = "Закрыть" if s.model_seeking_open else "Открыть"
            practice_cards_html += f"""
            <div class="card" style="padding:1rem;margin-bottom:0.75rem">
                <div style="display:flex;justify-content:space-between;align-items:start;gap:0.5rem;flex-wrap:wrap">
                    <div>
                        <strong>{s.name}</strong>
                        <span class="badge-tag" style="margin-left:0.4rem;background:#d1fae5;color:#065f46">{responses_count} откликов</span>
                    </div>
                    {status_badge}
                </div>
                <p class="text-muted" style="font-size:0.8rem;margin:0.35rem 0">Мастер: {m.specialization}</p>
                {f'<p class="text-muted" style="font-size:0.8rem;margin:0.25rem 0">📅 {date_label}</p>' if date_label else ''}
                <p style="font-size:0.85rem;margin:0.35rem 0">{s.description or ''}</p>
                <p class="text-muted" style="font-size:0.8rem">{s.duration_minutes} мин · {s.price:,} ₽ · набрано {quota_label}</p>
                <div style="margin-top:0.5rem;display:flex;gap:0.5rem">
                    <button type="button" class="btn-outline" style="font-size:0.75rem;padding:0.3rem 0.7rem" onclick="window.modelsToggleServiceOpen({s.id}, {str(not s.model_seeking_open).lower()}, {s.model_quota if s.model_quota is not None else 'null'})">{toggle_label}</button>
                    <button type="button" class="btn-outline" style="font-size:0.75rem;padding:0.3rem 0.7rem" onclick="window.modelsDeletePracticeService({s.id})">Удалить</button>
                </div>
            </div>"""
            if is_open:
                service_options_swipe += f'<option value="{s.id}">{s.name} — {m.specialization} ({s.price:,} ₽)</option>'

    master_options_publish = "".join(f'<option value="{m.id}">{m.specialization}</option>' for m in masters)

    return f"""
    <div id="tab-models" class="tab-content">
        <div class="models-subtab-nav">
            <button type="button" class="models-subtab-btn active" data-subtab="swipe" onclick="window.modelsShowSubtab('swipe')">♥ Свайп моделей</button>
            <button type="button" class="models-subtab-btn" data-subtab="publish" onclick="window.modelsShowSubtab('publish')">+ Опубликовать поиск</button>
        </div>

        <div id="models-subtab-swipe" class="models-subtab-panel">
            <div class="models-swipe-grid">
                <div class="card" style="padding:1.5rem">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem">
                        <h3 style="margin:0">Найти модель</h3>
                        <div style="display:flex;gap:0.75rem;font-size:0.8rem" class="text-muted">
                            <span>♥ <span id="modelsLikeCount">0</span></span>
                            <span>✕ <span id="modelsPassCount">0</span></span>
                        </div>
                    </div>
                    {f'<select id="modelsServiceSelect" class="custom-select" onchange="window.modelsLoadCandidates()" style="margin-bottom:1rem">{service_options_swipe}</select>' if service_options_swipe else '<p class="text-muted">Опубликуйте поиск во вкладке «Опубликовать поиск», чтобы смотреть анкеты</p>'}
                    <div class="models-card-stack" id="modelsCardStack">
                        <p class="text-muted" style="text-align:center;padding:2rem 0">Загрузка…</p>
                    </div>
                    <div class="models-swipe-buttons">
                        <button type="button" class="models-swipe-btn models-swipe-btn-pass" onclick="window.modelsButtonSwipe(false)">✕</button>
                        <button type="button" class="models-swipe-btn models-swipe-btn-like" onclick="window.modelsButtonSwipe(true)">♥</button>
                        <button type="button" class="models-swipe-btn models-swipe-btn-eye" onclick="window.modelsShowDetails()">👁</button>
                    </div>
                </div>

                <div class="card" style="padding:1.25rem">
                    <h3 style="margin-bottom:1rem;font-size:1rem">💌 Мои мэтчи</h3>
                    <div id="modelsMatchesList"><p class="text-muted">Загрузка…</p></div>
                </div>
            </div>
        </div>

        <div id="models-subtab-publish" class="models-subtab-panel" style="display:none">
            <div class="card" style="margin-bottom:1.5rem;padding:1.5rem">
                <h3 style="margin-bottom:1rem">Опубликовать поиск модели</h3>
                <p class="text-muted" style="font-size:0.85rem;margin-bottom:1rem">Модели увидят вашу заявку в ленте и смогут откликнуться — цена и время уже зафиксированы здесь, дополнительно согласовывать после мэтча не нужно.</p>
                <form action="/api/v1/services/create" method="post" style="max-width:32rem;display:flex;flex-direction:column;gap:0.75rem">
                    <div>
                        <label class="text-muted" style="font-size:0.8rem;display:block;margin-bottom:0.3rem">Мастер</label>
                        <select name="master_id" class="custom-select" required>
                            <option value="">Выберите мастера</option>
                            {master_options_publish}
                        </select>
                    </div>
                    <div>
                        <label class="text-muted" style="font-size:0.8rem;display:block;margin-bottom:0.3rem">Услуга</label>
                        <input name="name" placeholder="Например: балаяж" required style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem">
                    </div>
                    <div style="display:flex;gap:0.75rem">
                        <div style="flex:1">
                            <label class="text-muted" style="font-size:0.8rem;display:block;margin-bottom:0.3rem">Цена, ₽ (0 — бесплатно)</label>
                            <input name="price" type="number" min="0" required style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem">
                        </div>
                        <div style="flex:1">
                            <label class="text-muted" style="font-size:0.8rem;display:block;margin-bottom:0.3rem">Минут</label>
                            <input name="duration_minutes" type="number" min="1" required style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem">
                        </div>
                    </div>
                    <div style="display:flex;gap:0.75rem">
                        <div style="flex:1">
                            <label class="text-muted" style="font-size:0.8rem;display:block;margin-bottom:0.3rem">Нужно моделей (необязательно)</label>
                            <input name="model_quota" type="number" min="1" style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem">
                        </div>
                        <div style="flex:1">
                            <label class="text-muted" style="font-size:0.8rem;display:block;margin-bottom:0.3rem">Дата (необязательно)</label>
                            <input name="model_desired_date" type="date" style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem">
                        </div>
                    </div>
                    <div>
                        <label class="text-muted" style="font-size:0.8rem;display:block;margin-bottom:0.3rem">Описание / требования</label>
                        <textarea name="description" rows="3" placeholder="Что хотите отработать, пожелания к модели..." style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem;resize:vertical"></textarea>
                    </div>
                    <input type="hidden" name="is_model_practice" value="true">
                    <button type="submit" class="btn-primary">Опубликовать поиск</button>
                </form>
            </div>

            <div>
                <h3 style="margin-bottom:1rem">Опубликованные поиски</h3>
                {practice_cards_html or '<p class="text-muted">Пока ничего не опубликовано</p>'}
            </div>
        </div>
    </div>

    <style>
        .models-subtab-nav {{ display:flex; gap:0.5rem; background:var(--color-surface-alt,#f3f4f6); border-radius:0.75rem; padding:0.25rem; margin-bottom:1.5rem; max-width:32rem }}
        .models-subtab-btn {{ flex:1; padding:0.6rem; border:none; background:transparent; border-radius:0.5rem; cursor:pointer; font-size:0.85rem; font-weight:500; color:var(--color-muted) }}
        .models-subtab-btn.active {{ background:var(--color-surface,#fff); color:var(--color-heading); box-shadow:0 1px 2px rgba(0,0,0,0.06) }}
        .models-swipe-grid {{ display:grid; grid-template-columns:1fr; gap:1.5rem }}
        @media (min-width: 1024px) {{ .models-swipe-grid {{ grid-template-columns:1fr 320px }} }}
        .models-card-stack {{ position:relative; width:100%; max-width:340px; margin:0 auto; aspect-ratio:3/4; }}
        .models-swipe-card {{ position:absolute; inset:0; border:1px solid var(--color-border); border-radius:1rem; overflow:hidden; background:var(--color-surface,#fff); box-shadow:0 10px 25px rgba(0,0,0,0.12); cursor:grab; touch-action:pan-y; user-select:none }}
        .models-swipe-card.dragging {{ transition:none }}
        .models-swipe-card-photo {{ position:relative; height:65%; background-size:cover; background-position:center; background-color:var(--color-surface-alt,#eee) }}
        .models-swipe-card-photo::after {{ content:''; position:absolute; inset:0; background:linear-gradient(to top, rgba(0,0,0,0.6), transparent 60%) }}
        .models-swipe-card-name {{ position:absolute; left:1rem; right:1rem; bottom:0.75rem; color:#fff; z-index:1 }}
        .models-swipe-card-body {{ padding:0.9rem 1rem; height:35%; overflow:hidden }}
        .models-swipe-overlay {{ position:absolute; top:1.5rem; padding:0.4rem 1rem; border:3px solid; border-radius:0.5rem; font-weight:900; font-size:1.4rem; opacity:0; pointer-events:none }}
        .models-swipe-overlay-like {{ left:1rem; color:#22c55e; border-color:#22c55e; transform:rotate(-15deg) }}
        .models-swipe-overlay-nope {{ right:1rem; color:#ef4444; border-color:#ef4444; transform:rotate(15deg) }}
        .models-swipe-buttons {{ display:flex; justify-content:center; gap:1.25rem; margin-top:1.25rem }}
        .models-swipe-btn {{ width:3.25rem; height:3.25rem; border-radius:50%; border:2px solid var(--color-border); background:#fff; cursor:pointer; font-size:1.3rem; display:flex; align-items:center; justify-content:center }}
        .models-swipe-btn-like {{ width:3.75rem; height:3.75rem; color:#22c55e; border-color:#bbf7d0 }}
        .models-swipe-btn-pass {{ color:#ef4444; border-color:#fecaca }}
        .models-swipe-btn-eye {{ color:#3b82f6; border-color:#bfdbfe }}
    </style>

    <script>
    (function() {{
        const salonId = {salon.id};
        let candidateQueue = [];
        let likeCount = 0, passCount = 0;

        window.modelsShowSubtab = function(name) {{
            document.querySelectorAll('.models-subtab-btn').forEach(b => b.classList.toggle('active', b.dataset.subtab === name));
            document.getElementById('models-subtab-swipe').style.display = name === 'swipe' ? '' : 'none';
            document.getElementById('models-subtab-publish').style.display = name === 'publish' ? '' : 'none';
        }};

        window.modelsToggleServiceOpen = async function(serviceId, newOpenState, quota) {{
            try {{
                const res = await fetch('/api/v1/model-matching/services/' + serviceId + '/seeking', {{
                    method: 'PATCH',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ model_seeking_open: newOpenState, model_quota: quota }})
                }});
                if (res.ok) {{ location.reload(); }} else {{ alert('Не удалось изменить статус'); }}
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
            }}
        }};

        window.modelsDeletePracticeService = async function(serviceId) {{
            if (!confirm('Удалить эту спецуслугу для моделей?')) return;
            try {{
                const res = await fetch('/api/v1/services/' + serviceId + '/delete', {{ method: 'POST' }});
                if (res.ok || res.redirected) {{ location.reload(); }} else {{ alert('Не удалось удалить'); }}
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
            }}
        }};

        function renderCardHtml(c) {{
            const sub = c.city || '';
            const photoCount = (c.photos || []).length + (c.photo_url ? 1 : 0);
            return '<div class="models-swipe-card">' +
                '<div class="models-swipe-overlay models-swipe-overlay-like">LIKE</div>' +
                '<div class="models-swipe-overlay models-swipe-overlay-nope">NOPE</div>' +
                '<div class="models-swipe-card-photo" style="background-image:url(\\'' + (c.photo_url || '') + '\\')">' +
                '<div class="models-swipe-card-name"><h3 style="margin:0;font-size:1.3rem;font-weight:700">' + c.name + '</h3>' +
                (sub ? '<p style="margin:0.2rem 0 0;font-size:0.8rem;opacity:0.9">' + sub + '</p>' : '') + '</div></div>' +
                '<div class="models-swipe-card-body">' +
                (c.bio ? '<p style="font-size:0.85rem;margin:0;line-height:1.4;max-height:3.6em;overflow:hidden">' + c.bio + '</p>' : '<p class="text-muted" style="font-size:0.85rem">Без описания</p>') +
                (photoCount ? '<p class="text-muted" style="font-size:0.75rem;margin-top:0.5rem">📷 ' + photoCount + ' фото</p>' : '') +
                '</div></div>';
        }}

        function renderStack() {{
            const stack = document.getElementById('modelsCardStack');
            if (!candidateQueue.length) {{
                stack.innerHTML = '<p class="text-muted" style="text-align:center;padding:2rem 0">Анкет пока нет</p>';
                return;
            }}
            stack.innerHTML = candidateQueue.slice(0, 2).reverse().map(renderCardHtml).join('');
            attachDrag();
        }}

        function attachDrag() {{
            const cards = document.querySelectorAll('#modelsCardStack .models-swipe-card');
            const top = cards[cards.length - 1];
            if (!top) return;
            let startX = 0, startY = 0, dx = 0, dragging = false;

            top.addEventListener('pointerdown', function(e) {{
                dragging = true;
                startX = e.clientX; startY = e.clientY;
                top.classList.add('dragging');
                top.setPointerCapture(e.pointerId);
            }});
            top.addEventListener('pointermove', function(e) {{
                if (!dragging) return;
                dx = e.clientX - startX;
                const dy = e.clientY - startY;
                const rotate = dx / 12;
                top.style.transform = 'translate(' + dx + 'px,' + dy + 'px) rotate(' + rotate + 'deg)';
                const likeOverlay = top.querySelector('.models-swipe-overlay-like');
                const nopeOverlay = top.querySelector('.models-swipe-overlay-nope');
                likeOverlay.style.opacity = Math.max(0, Math.min(1, dx / 100));
                nopeOverlay.style.opacity = Math.max(0, Math.min(1, -dx / 100));
            }});
            function endDrag() {{
                if (!dragging) return;
                dragging = false;
                top.classList.remove('dragging');
                if (Math.abs(dx) > 100) {{
                    commitSwipe(dx > 0);
                }} else {{
                    top.style.transform = '';
                }}
                dx = 0;
            }}
            top.addEventListener('pointerup', endDrag);
            top.addEventListener('pointercancel', endDrag);
        }}

        function commitSwipe(like) {{
            const card = candidateQueue.shift();
            if (like) {{ likeCount++; document.getElementById('modelsLikeCount').textContent = likeCount; }}
            else {{ passCount++; document.getElementById('modelsPassCount').textContent = passCount; }}
            renderStack();
            window.modelsSwipeCandidate(card.model_user_id, like);
        }}

        window.modelsButtonSwipe = function(like) {{
            if (!candidateQueue.length) return;
            commitSwipe(like);
        }};

        window.modelsShowDetails = function() {{
            const c = candidateQueue[0];
            if (!c) return;
            const photos = (c.photos && c.photos.length) ? c.photos : (c.photo_url ? [c.photo_url] : []);
            alert((c.name || '') + (c.city ? ' · ' + c.city : '') + '\\n\\n' + (c.bio || 'Без описания') +
                (c.looking_for ? '\\n\\nИщет: ' + c.looking_for : '') +
                (photos.length ? '\\n\\nФото: ' + photos.join('\\n') : ''));
        }};

        window.modelsLoadCandidates = async function() {{
            const select = document.getElementById('modelsServiceSelect');
            if (!select || !select.value) return;
            const stack = document.getElementById('modelsCardStack');
            stack.innerHTML = '<p class="text-muted" style="text-align:center;padding:2rem 0">Загрузка…</p>';
            try {{
                const res = await fetch('/api/v1/model-matching/services/' + select.value + '/candidates');
                candidateQueue = res.ok ? await res.json() : [];
            }} catch (err) {{
                candidateQueue = [];
            }}
            likeCount = 0; passCount = 0;
            document.getElementById('modelsLikeCount').textContent = 0;
            document.getElementById('modelsPassCount').textContent = 0;
            renderStack();
        }};

        window.modelsSwipeCandidate = async function(modelUserId, like) {{
            const select = document.getElementById('modelsServiceSelect');
            try {{
                await fetch('/api/v1/model-matching/services/' + select.value + '/candidates/' + modelUserId + '/swipe', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ like: like }})
                }});
            }} catch (err) {{ /* карточку всё равно уже убрали из очереди */ }}
            window.modelsLoadMatches();
        }};

        function statusLabel(status) {{
            return {{waiting: 'Ждём ответа модели', matched: 'Ждём выбор времени', booked: 'Забронировано', declined: 'Отклонено'}}[status] || status;
        }}

        function matchCardHtml(m) {{
            let actions = '';
            if (m.status === 'waiting') {{
                actions = '<p class="text-muted" style="font-size:0.85rem;margin-top:0.5rem">' + m.service_name + ' · ' + (m.price ? m.price + ' ₽' : 'бесплатно') + ' — вы лайкнули, ждём ответа модели</p>';
            }} else if (m.status === 'matched') {{
                actions = '<p class="text-muted" style="font-size:0.85rem;margin-top:0.5rem">' + m.service_name + ' · ' + (m.price ? m.price + ' ₽' : 'бесплатно') + ' — модель выбирает время сама</p>';
            }} else if (m.status === 'booked') {{
                actions = '<p style="margin-top:0.5rem;color:var(--color-success,#065f46)">Запись создана' + (m.chosen_slot ? ' на ' + new Date(m.chosen_slot).toLocaleString('ru-RU', {{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}}) : '') + '</p>';
            }}
            return '<div class="card" style="padding:1rem;margin-bottom:0.75rem">' +
                '<div style="display:flex;justify-content:space-between;align-items:start">' +
                '<strong style="font-size:0.85rem">' + m.model_name + ' → ' + m.master_name + '</strong>' +
                '<span class="badge-tag">' + statusLabel(m.status) + '</span>' +
                '</div>' + actions + '</div>';
        }}

        window.modelsLoadMatches = async function() {{
            const list = document.getElementById('modelsMatchesList');
            try {{
                const res = await fetch('/api/v1/model-matching/salon/' + salonId + '/matches');
                const matches = res.ok ? await res.json() : [];
                list.innerHTML = matches.length ? matches.map(matchCardHtml).join('') : '<p class="text-muted">Мэтчей пока нет</p>';
            }} catch (err) {{
                list.innerHTML = '<p class="text-muted">Не удалось загрузить мэтчи</p>';
            }}
        }};

        if (document.getElementById('modelsServiceSelect')) {{ window.modelsLoadCandidates(); }}
        window.modelsLoadMatches();
    }})();
    </script>"""
