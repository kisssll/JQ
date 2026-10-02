import json

from app.web.components.escaping import e


def render_inventory_audit_flow(audit, rows, *, return_url: str, title: str = "Инвентаризация") -> str:
    """Render a resumable one-card-at-a-time stocktake."""
    cards = []
    for audit_item, product in rows:
        if product is None:
            continue
        cards.append(f"""
        <article class="audit-step-card" data-audit-item-id="{audit_item.id}"
            data-reviewed="{'true' if audit_item.is_reviewed else 'false'}" hidden>
            <div style="color:var(--color-muted);font-size:.9rem;margin-bottom:.5rem">
                Системный остаток: {audit_item.expected_quantity:g} {e(product.unit)}
            </div>
            <h3 style="font-size:1.4rem;margin-bottom:1rem">{e(product.name)}</h3>
            <label style="display:block;margin-bottom:1rem">
                Фактическое количество, {e(product.unit)}
                <input class="audit-step-quantity" type="number" min="0" step="0.01"
                    value="{audit_item.expected_quantity:g}"
                    style="display:block;width:100%;margin-top:.4rem">
            </label>
            <div style="display:flex;flex-wrap:wrap;gap:.6rem">
                <button type="button" class="btn-outline" data-audit-action="correct">Всё правильно</button>
                <button type="button" class="btn-primary" data-audit-action="adjust">Сохранить количество</button>
                <button type="button" class="btn-outline" data-audit-action="archive">В архив</button>
            </div>
        </article>""")

    if not cards:
        return """
        <div class="card warehouse-audit-card">
            <h3>В этом акте нет позиций</h3>
        </div>"""

    return_url_json = json.dumps(return_url, ensure_ascii=True)
    return f"""
    <div class="inventory-audit-launcher" id="inventoryAuditLauncher">
        <button type="button" class="btn-primary" id="openInventoryAudit">
            Продолжить инвентаризацию
        </button>
    </div>
    <dialog class="inventory-audit-dialog" id="inventoryAuditDialog" aria-labelledby="inventoryAuditTitle">
        <section class="card warehouse-audit-card inventory-audit-modal" id="inventoryAuditFlow"
            data-audit-id="{audit.id}">
            <header class="inventory-audit-modal-header">
                <div>
                    <h2 id="inventoryAuditTitle">{e(title)}</h2>
                    <p class="warehouse-audit-description">
                        Проверяйте позиции по одной. Изменения применятся после завершения акта.
                    </p>
                </div>
                <button type="button" class="btn-outline inventory-audit-minimize"
                    id="minimizeInventoryAudit" aria-label="Свернуть окно инвентаризации">
                    Свернуть
                </button>
            </header>
            <p id="auditStepProgress" style="font-weight:600;margin-bottom:1rem"></p>
            {''.join(cards)}
            <div id="auditStepComplete" hidden>
                <p>Все позиции проверены. Завершите инвентаризацию, чтобы применить изменения.</p>
                <button type="button" class="btn-primary" id="finishInventoryAudit">Завершить инвентаризацию</button>
            </div>
        </section>
    </dialog>
    <style>
        .inventory-audit-launcher {{
            position:fixed;right:1.5rem;bottom:1.5rem;z-index:1000;
        }}
        .inventory-audit-launcher button {{
            min-height:3rem;padding:.8rem 1.25rem;border:0;border-radius:9999px;
            background:var(--color-primary);color:#fff;font:inherit;font-weight:650;
            box-shadow:0 8px 24px color-mix(in srgb,var(--color-primary) 30%,transparent);
            transition:transform .18s ease,box-shadow .18s ease;
        }}
        .inventory-audit-launcher button:hover {{
            transform:translateY(-2px);
            box-shadow:0 12px 30px color-mix(in srgb,var(--color-primary) 38%,transparent);
        }}
        .inventory-audit-launcher button:focus-visible,
        .inventory-audit-modal button:focus-visible {{
            outline:3px solid color-mix(in srgb,var(--color-primary) 35%,transparent);
            outline-offset:2px;
        }}
        .inventory-audit-dialog {{
            position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);
            width:min(560px,calc(100% - 2rem));max-width:none;max-height:calc(100dvh - 2rem);
            padding:0;border:1px solid color-mix(in srgb,var(--color-primary) 18%,var(--color-border));border-radius:24px;
            background:var(--color-surface,#fff);color:var(--color-text,inherit);
            box-shadow:0 28px 90px rgba(40,20,30,.22);overflow:auto;
        }}
        .inventory-audit-dialog::backdrop {{ background:rgba(36,20,31,.48);backdrop-filter:blur(5px); }}
        .inventory-audit-modal {{
            margin:0;border:0;border-radius:inherit;box-shadow:none;
            padding:clamp(1.35rem,4vw,2rem);background:var(--color-surface);
        }}
        .inventory-audit-modal-header {{
            display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;margin-bottom:1.25rem;
        }}
        .inventory-audit-modal-header h2 {{
            margin:0 0 .55rem;color:var(--color-heading);font-size:1.4rem;font-weight:700;letter-spacing:-.02em;
        }}
        .inventory-audit-modal-header .warehouse-audit-description {{
            margin:0;color:var(--color-muted);font-size:.92rem;line-height:1.6;
        }}
        .inventory-audit-minimize {{ flex-shrink:0; }}
        .inventory-audit-modal #auditStepProgress {{
            display:inline-flex;padding:.35rem .8rem;border-radius:9999px;
            background:color-mix(in srgb,var(--color-primary) 10%,var(--color-surface));
            color:var(--color-primary);font-size:.82rem;font-weight:700;
        }}
        .inventory-audit-modal .audit-step-card {{
            padding:1.15rem;border:1px solid var(--color-border);border-radius:1rem;
            background:var(--color-surface-alt);
        }}
        .inventory-audit-modal .audit-step-card h3 {{
            color:var(--color-heading);font-size:1.3rem;font-weight:700;
        }}
        .inventory-audit-modal .audit-step-card label {{
            color:var(--color-heading);font-size:.88rem;font-weight:600;
        }}
        .inventory-audit-modal .audit-step-quantity {{
            box-sizing:border-box;min-height:3rem;padding:.7rem .85rem;
            border:1px solid var(--color-border);border-radius:.75rem;
            background:var(--color-surface);color:var(--color-heading);
            font:inherit;outline:none;transition:border-color .18s ease,box-shadow .18s ease;
        }}
        .inventory-audit-modal .audit-step-quantity:focus {{
            border-color:var(--color-primary);
            box-shadow:0 0 0 3px color-mix(in srgb,var(--color-primary) 16%,transparent);
        }}
        .inventory-audit-modal .audit-step-card button,
        .inventory-audit-modal #auditStepComplete button {{
            min-height:2.75rem;padding:.65rem 1rem;border-radius:9999px;
            font:inherit;font-size:.88rem;font-weight:650;cursor:pointer;transition:.18s ease;
        }}
        .inventory-audit-modal .audit-step-card button[data-audit-action="adjust"],
        .inventory-audit-modal #auditStepComplete button {{
            border:1px solid var(--color-primary);background:var(--color-primary);color:#fff;
        }}
        .inventory-audit-modal .audit-step-card button[data-audit-action="correct"],
        .inventory-audit-modal .audit-step-card button[data-audit-action="archive"],
        .inventory-audit-minimize {{
            border:1px solid var(--color-border);background:var(--color-surface);color:var(--color-heading);
        }}
        .inventory-audit-modal .audit-step-card button:hover,
        .inventory-audit-modal #auditStepComplete button:hover,
        .inventory-audit-minimize:hover {{
            border-color:var(--color-primary);filter:brightness(.98);
        }}
        .inventory-audit-modal #auditStepComplete {{
            padding:1rem;border:1px solid color-mix(in srgb,#16a34a 25%,var(--color-border));
            border-radius:1rem;background:color-mix(in srgb,#16a34a 7%,var(--color-surface));
        }}
        .inventory-audit-modal #auditStepComplete p {{
            margin:0 0 1rem;color:var(--color-heading);line-height:1.55;
        }}
        @media (max-width:600px) {{
            .inventory-audit-launcher {{ right:1rem;bottom:1rem; }}
            .inventory-audit-modal-header {{ flex-direction:column-reverse; }}
            .inventory-audit-minimize {{ align-self:flex-end; }}
        }}
    </style>
    <script>
    (function() {{
        const flow = document.getElementById('inventoryAuditFlow');
        if (!flow) return;
        const dialog = document.getElementById('inventoryAuditDialog');
        const openButton = document.getElementById('openInventoryAudit');
        const minimizeButton = document.getElementById('minimizeInventoryAudit');
        const auditId = flow.dataset.auditId;
        const cards = Array.from(flow.querySelectorAll('.audit-step-card'));
        const progress = document.getElementById('auditStepProgress');
        const completed = document.getElementById('auditStepComplete');
        const returnUrl = {return_url_json};
        let busy = false;

        openButton.addEventListener('click', () => {{
            if (!dialog.open) dialog.showModal();
        }});
        minimizeButton.addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => openButton.focus());

        function showNext() {{
            const next = cards.find(card => card.dataset.reviewed !== 'true');
            cards.forEach(card => {{ card.hidden = card !== next; }});
            progress.textContent = next
                ? 'Позиция ' + (cards.indexOf(next) + 1) + ' из ' + cards.length
                : 'Проверено позиций: ' + cards.length;
            completed.hidden = Boolean(next);
        }}

        async function review(card, action) {{
            if (busy) return;
            if (action === 'archive' && !window.confirm('Переместить эту позицию в архив после завершения акта?')) return;
            const payload = {{ action }};
            if (action === 'adjust') {{
                const input = card.querySelector('.audit-step-quantity');
                const quantity = Number(input.value);
                if (!Number.isFinite(quantity) || quantity < 0) {{
                    alert('Введите количество не меньше нуля');
                    input.focus();
                    return;
                }}
                payload.actual_quantity = quantity;
            }}
            busy = true;
            const buttons = card.querySelectorAll('button');
            buttons.forEach(button => button.disabled = true);
            try {{
                const res = await fetch('/api/v1/inventory/audit/' + auditId + '/items/' + card.dataset.auditItemId, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (!res.ok) {{
                    const data = await res.json().catch(() => ({{}}));
                    alert(data.detail || 'Не удалось сохранить результат пересчёта');
                    return;
                }}
                card.dataset.reviewed = 'true';
                showNext();
            }} catch (error) {{
                alert('Ошибка соединения с сервером');
            }} finally {{
                busy = false;
                buttons.forEach(button => button.disabled = false);
            }}
        }}

        cards.forEach(card => card.querySelectorAll('[data-audit-action]').forEach(button => {{
            button.addEventListener('click', () => review(card, button.dataset.auditAction));
        }}));

        document.getElementById('finishInventoryAudit').addEventListener('click', async function() {{
            if (busy) return;
            busy = true;
            this.disabled = true;
            try {{
                const res = await fetch('/api/v1/inventory/audit/' + auditId + '/confirm', {{ method: 'POST' }});
                if (!res.ok) {{
                    const data = await res.json().catch(() => ({{}}));
                    alert(data.detail || 'Не удалось завершить инвентаризацию');
                    this.disabled = false;
                    return;
                }}
                window.location.href = returnUrl;
            }} catch (error) {{
                alert('Ошибка соединения с сервером');
                this.disabled = false;
            }} finally {{
                busy = false;
            }}
        }});
        showNext();
        dialog.showModal();
    }})();
    </script>"""
