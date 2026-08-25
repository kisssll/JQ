# app/web/pages/business/tabs/chat.py
from app.web.components.escaping import e
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Master, User as UserModel
from app.web.components.icons import (
    ICON_FILE_TEXT,
    ICON_MESSAGE_CIRCLE,
)


async def render_chat_tab(db: AsyncSession, salon, user) -> str:
    """Вкладка Чат — внутренняя переписка салона (владелец + мастера + админы)."""
    
    # Получаем всех мастеров салона
    masters_result = await db.execute(
        select(Master).where(Master.salon_id == salon.id)
    )
    masters = masters_result.scalars().all()
    
    # Собираем список участников чата: владелец + все мастера + все админы
    chat_members = []
    added_ids = set()  # Чтобы не дублировать участников
    
    # Создатель салона (полный список совладельцев/админов — в вкладке «Сотрудники»)
    # Явный запрос, а не salon.creator: у AsyncSession нет implicit lazy load
    # для relationship — обращение к непрогретой связи роняет запрос с
    # MissingGreenlet, если нужный User ещё не оказался в identity map сессии.
    owner = None
    if salon.creator_id:
        owner = (await db.execute(select(UserModel).where(UserModel.id == salon.creator_id))).scalar_one_or_none()
    if owner and owner.id not in added_ids:
        added_ids.add(owner.id)
        chat_members.append({
            "id": owner.id,
            "name": owner.full_name or "Владелец",
            "role": "Владелец",
            "avatar": (owner.full_name or "В")[0].upper(),
            "online": True
        })
    
    # Мастера салона
    for m in masters:
        master_user_result = await db.execute(select(UserModel).where(UserModel.id == m.user_id))
        master_user = master_user_result.scalar_one_or_none()
        if master_user and master_user.id not in added_ids:
            added_ids.add(master_user.id)
            chat_members.append({
                "id": master_user.id,
                "name": master_user.full_name or "Мастер",
                "role": m.specialization,
                "avatar": (master_user.full_name or "М")[0].upper(),
                "online": m.is_active
            })
    
    # Все администраторы (роль ADMIN)
    admins_result = await db.execute(
        select(UserModel).where(UserModel.role == "admin", UserModel.is_active == True)
    )
    admins = admins_result.scalars().all()
    for admin in admins:
        if admin.id not in added_ids:
            added_ids.add(admin.id)
            chat_members.append({
                "id": admin.id,
                "name": admin.full_name or "Админ",
                "role": "Администратор",
                "avatar": (admin.full_name or "А")[0].upper(),
                "online": True
            })
    
    # Убираем текущего пользователя из списка
    other_members = [m for m in chat_members if m["id"] != user.id]
    
    # Формируем список чатов
    chat_list = ""
    for member in other_members:
        online_dot = '<span style="width:8px;height:8px;background:#22c55e;border-radius:50%;position:absolute;bottom:0;right:0;border:2px solid white"></span>' if member["online"] else '<span style="width:8px;height:8px;background:#9ca3af;border-radius:50%;position:absolute;bottom:0;right:0;border:2px solid white"></span>'
        
        chat_list += f"""
        <div class="chat-item" onclick="openChat({member['id']}, '{e(member['name'])}', '{member['role']}')" data-chat-id="{member['id']}">
            <div class="chat-avatar">
                {member['avatar']}
                {online_dot}
            </div>
            <div class="chat-info">
                <div class="chat-name">{e(member['name'])}</div>
                <div class="chat-last-msg" style="font-size:0.75rem;color:var(--color-muted)">{member['role']}</div>
            </div>
            <div class="chat-time" style="color:#22c55e">{'● В сети' if member['online'] else '○ Не в сети'}</div>
        </div>"""
    
    return f"""
    <div id="tab-chat" class="tab-content">
        <div style="display:flex;height:calc(100vh - 250px);min-height:400px;border:1px solid var(--color-border);border-radius:1rem;overflow:hidden">
            <!-- Список чатов -->
            <div style="width:320px;border-right:1px solid var(--color-border);background:var(--color-surface-alt);overflow-y:auto">
                <div style="padding:1rem;border-bottom:1px solid var(--color-border);background:var(--color-surface)">
                    <h3 style="margin:0;font-size:1rem">{ICON_MESSAGE_CIRCLE} Чат салона</h3>
                    <p style="margin:0.25rem 0 0;font-size:0.75rem;color:var(--color-muted)">{len(other_members)} участников</p>
                </div>
                <div id="chatList">
                    {chat_list or '<div style="text-align:center;padding:2rem;color:var(--color-muted)">Нет других участников</div>'}
                </div>
            </div>
            
            <!-- Окно переписки -->
            <div style="flex:1;display:flex;flex-direction:column" id="chatWindow">
                <div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--color-muted);font-size:0.9rem">
                    <div style="text-align:center">
                        <div style="font-size:3rem;margin-bottom:1rem">{ICON_MESSAGE_CIRCLE}</div>
                        <p>Выберите сотрудника, чтобы начать переписку</p>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <style>
        .chat-item {{
            display:flex;
            align-items:center;
            gap:0.75rem;
            padding:0.75rem 1rem;
            cursor:pointer;
            transition:background 0.2s;
            border-bottom:1px solid var(--color-border);
        }}
        .chat-item:hover {{
            background:var(--color-surface);
        }}
        .chat-item.active {{
            background:var(--color-accent-light);
            border-left:3px solid var(--color-primary);
        }}
        .chat-avatar {{
            width:2.75rem;
            height:2.75rem;
            border-radius:50%;
            background:linear-gradient(135deg, var(--color-primary), var(--color-accent));
            display:flex;
            align-items:center;
            justify-content:center;
            color:white;
            font-weight:700;
            font-size:1rem;
            flex-shrink:0;
            position:relative;
        }}
        .chat-info {{
            flex:1;
            min-width:0;
        }}
        .chat-name {{
            font-weight:600;
            font-size:0.9rem;
            color:var(--color-heading);
        }}
        .chat-time {{
            font-size:0.7rem;
            flex-shrink:0;
        }}
        .message-bubble {{
            max-width:70%;
            padding:0.6rem 0.9rem;
            border-radius:1rem;
            margin-bottom:0.3rem;
            font-size:0.9rem;
            line-height:1.4;
        }}
        .message-bubble.sent {{
            background:linear-gradient(135deg, var(--color-primary), var(--color-accent));
            color:white;
            align-self:flex-end;
            border-bottom-right-radius:0.25rem;
        }}
        .message-bubble.received {{
            background:var(--color-surface-alt);
            color:var(--color-body);
            align-self:flex-start;
            border-bottom-left-radius:0.25rem;
        }}
    </style>
    
    <script>
        function openChat(userId, userName, userRole) {{
            document.querySelectorAll('.chat-item').forEach(item => item.classList.remove('active'));
            const chatItem = document.querySelector(`[data-chat-id="${{userId}}"]`);
            if (chatItem) chatItem.classList.add('active');
            
            const chatWindow = document.getElementById('chatWindow');
            chatWindow.innerHTML = `
                <div style="padding:0.75rem 1rem;border-bottom:1px solid var(--color-border);display:flex;align-items:center;gap:0.75rem;background:var(--color-surface)">
                    <div class="chat-avatar" style="width:2.25rem;height:2.25rem;font-size:0.85rem">${{userName[0]}}</div>
                    <div>
                        <strong style="font-size:0.9rem">${{userName}}</strong>
                        <div style="font-size:0.75rem;color:var(--color-muted)">${{userRole}}</div>
                    </div>
                </div>
                <div style="flex:1;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:0.5rem;background:var(--color-surface-alt)" id="messages-${{userId}}">
                    <div style="text-align:center;color:var(--color-muted);font-size:0.75rem;margin-bottom:1rem">
                        Начало переписки с ${{userName}}
                    </div>
                    <div style="text-align:center;color:var(--color-muted);font-size:0.8rem;margin-top:2rem">
                        {ICON_FILE_TEXT} Здесь будут ваши сообщения
                    </div>
                </div>
                <div style="padding:0.75rem;border-top:1px solid var(--color-border);display:flex;gap:0.5rem;background:var(--color-surface)">
                    <input type="text" placeholder="Введите сообщение..." id="msgInput-${{userId}}" 
                        style="flex:1;padding:0.6rem 0.75rem;border:1px solid var(--color-border);border-radius:2rem;font-size:0.85rem"
                        onkeydown="if(event.key==='Enter')sendMessage(${{userId}})">
                    <button onclick="sendMessage(${{userId}})" class="btn-primary" style="padding:0.5rem 1rem;border-radius:2rem;font-size:0.85rem">Отправить</button>
                </div>
            `;
        }}
        
        function sendMessage(userId) {{
            const input = document.getElementById('msgInput-' + userId);
            const msg = input.value.trim();
            if (!msg) return;
            
            const container = document.getElementById('messages-' + userId);
            const placeholder = container.querySelector('div[style*="margin-top:2rem"]');
            if (placeholder) placeholder.remove();
            
            const now = new Date();
            const time = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0');
            
            container.innerHTML += `
                <div style="display:flex;flex-direction:column;align-items:flex-end;margin-bottom:0.5rem">
                    <div class="message-bubble sent">${{msg}}</div>
                    <div style="font-size:0.65rem;color:var(--color-muted);margin-top:0.1rem">${{time}}</div>
                </div>
            `;
            container.scrollTop = container.scrollHeight;
            input.value = '';
        }}
    </script>"""