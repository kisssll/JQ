# app/web/pages/guest_booking.py
"""Публичные страницы записи без регистрации: /book/{salon_id} и /guest-booking/{token}.

Оформлены в брендинг Руми (лого + дизайн-токены приложения), чтобы выглядеть
как основная запись, а не сырая форма.
"""
import json

from sqlalchemy import select

from app.models.models import (
    Salon, Master, Service, User, Booking,
    SalonModerationStatus, BookingStatus,
)
from app.web.components.styles import get_base_styles


_STYLE = """
<style>
    .gb-body{background:var(--color-bg,#f6f5f8);min-height:100vh}
    .gb-header{display:flex;align-items:center;justify-content:space-between;
        padding:0.9rem 1.25rem;background:var(--color-surface,#fff);
        border-bottom:1px solid var(--color-border,#ececec);position:sticky;top:0;z-index:5}
    .gb-header a#header-logo{font-size:1.4rem;font-weight:700;text-decoration:none;color:var(--color-primary,#7c3aed)}
    .gb-header .gb-login{font-size:0.9rem;color:var(--color-muted,#888);text-decoration:none}
    .gb-wrap{max-width:560px;margin:1.5rem auto;padding:0 1rem}
    .gb-panel{background:var(--color-surface,#fff);border:1px solid var(--color-border,#ececec);
        border-radius:18px;padding:1.5rem;box-shadow:0 2px 14px rgba(20,10,40,0.04)}
    .gb-title{font-size:1.5rem;font-weight:700;margin:0 0 0.25rem}
    .gb-sub{color:var(--color-muted,#888);margin:0 0 1.25rem;font-size:0.95rem}
    .gb-step-h{display:flex;align-items:center;gap:0.6rem;margin:0 0 1rem}
    .gb-step-num{width:26px;height:26px;border-radius:50%;background:var(--color-primary,#7c3aed);
        color:#fff;font-size:0.85rem;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0}
    .gb-step-h h2{font-size:1.1rem;margin:0;font-weight:600}
    .gb-list{display:flex;flex-direction:column;gap:0.6rem}
    .gb-card{display:flex;align-items:center;gap:0.85rem;text-align:left;padding:0.9rem 1rem;
        border:1px solid var(--color-border,#ececec);border-radius:14px;background:var(--color-surface,#fff);
        cursor:pointer;width:100%;transition:border-color .15s,box-shadow .15s}
    .gb-card:hover{border-color:var(--color-primary,#7c3aed);box-shadow:0 2px 10px rgba(124,58,237,0.08)}
    .gb-ava{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#a78bfa,#7c3aed);
        color:#fff;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:1.1rem}
    .gb-card-body{flex:1;min-width:0}
    .gb-card-body strong{display:block;font-size:0.98rem}
    .gb-card-body small{color:var(--color-muted,#888);font-size:0.85rem}
    .gb-card-price{font-weight:700;color:var(--color-primary,#7c3aed);white-space:nowrap}
    .gb-slots{display:grid;grid-template-columns:repeat(auto-fill,minmax(80px,1fr));gap:0.5rem}
    .gb-slot{padding:0.55rem 0;border:1px solid var(--color-border,#ececec);border-radius:10px;
        background:var(--color-surface,#fff);cursor:pointer;font-size:0.95rem;transition:.15s}
    .gb-slot:hover{border-color:var(--color-primary,#7c3aed);background:rgba(124,58,237,0.05)}
    .gb-back{background:none;border:none;color:var(--color-muted,#888);cursor:pointer;
        padding:0;margin-bottom:0.9rem;font-size:0.9rem}
    .gb-back:hover{color:var(--color-primary,#7c3aed)}
    .gb-field{margin-bottom:0.85rem}
    .gb-field label{display:block;font-size:0.85rem;color:var(--color-muted,#888);margin-bottom:0.3rem}
    .gb-input{width:100%;padding:0.7rem 0.85rem;border:1px solid var(--color-border,#ddd);
        border-radius:11px;font-size:1rem;background:var(--color-surface,#fff);box-sizing:border-box}
    .gb-input:focus{outline:none;border-color:var(--color-primary,#7c3aed)}
    .gb-summary{background:rgba(124,58,237,0.06);border-radius:12px;padding:0.8rem 1rem;
        margin-bottom:1rem;font-size:0.92rem}
    .gb-primary{width:100%;padding:0.85rem;border:none;border-radius:12px;background:var(--color-primary,#7c3aed);
        color:#fff;font-size:1rem;font-weight:600;cursor:pointer;transition:.15s}
    .gb-primary:hover{filter:brightness(1.05)}
    .gb-primary:disabled{opacity:.5;cursor:not-allowed}
    .gb-error{color:#c0392b;font-size:0.9rem;min-height:1.2em;margin:0.3rem 0 0.6rem}
    .gb-date{margin-bottom:0.9rem}
    .gb-done{text-align:center;padding:1.5rem 0.5rem}
    .gb-done-check{width:64px;height:64px;border-radius:50%;background:rgba(39,174,96,0.12);
        color:#27ae60;font-size:2rem;display:flex;align-items:center;justify-content:center;margin:0 auto 1rem}
    .gb-manage-link{display:inline-block;margin-top:0.75rem;padding:0.6rem 1rem;border:1px solid var(--color-border,#ececec);
        border-radius:10px;word-break:break-all;font-size:0.85rem;color:var(--color-primary,#7c3aed);text-decoration:none}
    .gb-muted{color:var(--color-muted,#888)}
</style>
"""


def _shell(title: str, inner: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — руми</title>
    {get_base_styles()}
    {_STYLE}
</head>
<body class="gb-body">
    <header class="gb-header">
        <a href="/" id="header-logo">руми.</a>
        <a href="/login" class="gb-login">Войти</a>
    </header>
    <div class="gb-wrap">
        {inner}
    </div>
</body>
</html>"""


def _notice(title: str, text: str) -> str:
    return _shell(title, f"""
        <div class="gb-panel" style="text-align:center">
            <h1 class="gb-title">{title}</h1>
            <p class="gb-sub" style="margin-bottom:0">{text}</p>
            <p style="margin-top:1.25rem"><a href="/" class="gb-manage-link">На главную руми</a></p>
        </div>""")


async def render_guest_booking_page(db, salon_id: int) -> str:
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if (
        not salon
        or not salon.is_active
        or salon.moderation_status != SalonModerationStatus.APPROVED
        or salon.published_at is None
        or not salon.guest_booking_enabled
    ):
        return _notice("Запись недоступна", "Этот салон сейчас не принимает записи без регистрации.")

    masters = (await db.execute(
        select(Master).where(Master.salon_id == salon_id, Master.is_active == True)
    )).scalars().all()

    data = []
    for m in masters:
        muser = (await db.execute(select(User).where(User.id == m.user_id))).scalar_one_or_none()
        services = (await db.execute(
            select(Service).where(
                Service.master_id == m.id, Service.is_active == True, Service.is_model_practice == False,
            ).order_by(Service.price)
        )).scalars().all()
        if not services:
            continue
        data.append({
            "id": m.id,
            "name": (muser.full_name if muser else None) or "Мастер",
            "spec": m.specialization or "",
            "services": [{"id": s.id, "name": s.name, "price": s.price, "duration": s.duration_minutes} for s in services],
        })

    if not data:
        return _notice("Пока нельзя записаться", "У салона нет доступных мастеров или услуг.")

    masters_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    inner = f"""
        <h1 class="gb-title">Запись в «{salon.name}»</h1>
        <p class="gb-sub">Без регистрации — оставьте имя и телефон, салон подтвердит запись.</p>

        <div id="guest-book" data-salon-id="{salon.id}" data-masters='{masters_json}'>

            <div class="gb-panel gb-step" data-step="master">
                <div class="gb-step-h"><span class="gb-step-num">1</span><h2>Выберите мастера</h2></div>
                <div id="gb-masters" class="gb-list"></div>
            </div>

            <div class="gb-panel gb-step" data-step="service" style="display:none">
                <button class="gb-back" data-to="master">← Назад к мастерам</button>
                <div class="gb-step-h"><span class="gb-step-num">2</span><h2>Услуга</h2></div>
                <div id="gb-services" class="gb-list"></div>
            </div>

            <div class="gb-panel gb-step" data-step="slot" style="display:none">
                <button class="gb-back" data-to="service">← Назад к услугам</button>
                <div class="gb-step-h"><span class="gb-step-num">3</span><h2>Дата и время</h2></div>
                <input type="date" id="gb-date" class="gb-input gb-date">
                <div id="gb-slots" class="gb-slots"></div>
            </div>

            <div class="gb-panel gb-step" data-step="details" style="display:none">
                <button class="gb-back" data-to="slot">← Назад ко времени</button>
                <div class="gb-step-h"><span class="gb-step-num">4</span><h2>Ваши данные</h2></div>
                <div id="gb-summary" class="gb-summary"></div>
                <div class="gb-field"><label>Имя *</label>
                    <input type="text" id="gb-name" class="gb-input" autocomplete="name" required></div>
                <div class="gb-field"><label>Телефон *</label>
                    <input type="tel" id="gb-phone" class="gb-input phone-input" value="+7" placeholder="+7 (___) ___-__-__" required></div>
                <div class="gb-field"><label>Email — для уведомлений, необязательно</label>
                    <input type="email" id="gb-email" class="gb-input" autocomplete="email" placeholder="example@mail.ru"></div>
                <p id="gb-error" class="gb-error"></p>
                <button id="gb-submit" class="gb-primary">Записаться</button>
            </div>

            <div class="gb-panel gb-step" data-step="done" style="display:none">
                <div class="gb-done">
                    <div class="gb-done-check">✓</div>
                    <h2 class="gb-title" style="font-size:1.25rem">Заявка отправлена</h2>
                    <p class="gb-muted">Салон подтвердит запись. Сохраните ссылку — по ней можно посмотреть или отменить бронь:</p>
                    <a id="gb-manage-link" class="gb-manage-link" href="#"></a>
                </div>
            </div>
        </div>
    """
    return _shell(f"Запись в {salon.name}", inner)


async def render_guest_manage_page(db, token: str) -> str:
    booking = (await db.execute(
        select(Booking).where(Booking.guest_manage_token == token)
    )).scalar_one_or_none()
    if not booking:
        return _notice("Бронь не найдена", "Ссылка недействительна или устарела.")

    service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
    master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
    muser = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none() if master else None
    salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none() if master else None

    status_ru = {
        BookingStatus.PENDING: ("Ожидает подтверждения салона", "#e67e22"),
        BookingStatus.CONFIRMED: ("Подтверждена ✅", "#27ae60"),
        BookingStatus.COMPLETED: ("Выполнена", "#888"),
        BookingStatus.CANCELLED: ("Отменена", "#c0392b"),
        BookingStatus.NO_SHOW: ("Неявка", "#c0392b"),
    }.get(booking.status, (str(booking.status), "#888"))

    when = booking.start_time.strftime("%d.%m.%Y в %H:%M") if booking.start_time else ""
    can_cancel = booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
    cancel_btn = (
        f'<button id="gb-cancel" class="gb-primary" data-token="{token}" '
        f'style="background:#fff;color:#c0392b;border:1px solid #c0392b;margin-top:1rem">Отменить запись</button>'
        if can_cancel else ""
    )

    inner = f"""
        <div class="gb-panel">
            <h1 class="gb-title">Ваша запись</h1>
            <p class="gb-sub">«{salon.name if salon else ""}»</p>
            <div class="gb-card" style="cursor:default">
                <div class="gb-ava">{((muser.full_name if muser else "М") or "М")[0]}</div>
                <div class="gb-card-body">
                    <strong>{(muser.full_name if muser else "") or "Мастер"}</strong>
                    <small>{service.name if service else ""}</small>
                </div>
            </div>
            <p style="margin:1rem 0 0.25rem">🗓 <strong>{when}</strong></p>
            <p style="margin:0.5rem 0">Статус: <strong style="color:{status_ru[1]}">{status_ru[0]}</strong></p>
            {cancel_btn}
            <p id="gb-cancel-msg" class="gb-error" style="color:inherit"></p>
        </div>
        <p style="margin-top:1.25rem;text-align:center"><a href="/" class="gb-muted" style="text-decoration:none">На главную руми</a></p>
    """
    return _shell("Ваша запись", inner)
