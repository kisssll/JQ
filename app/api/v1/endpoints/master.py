# app/api/v1/endpoints/master.py
from urllib.parse import quote
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import secrets

from app.db.session import get_db
from app.models.models import User, Master, Booking, Salon, UserRole, BookingStatus, Review, ReviewTargetType
from app.api.deps import (
    get_current_user, require_is_master, check_salon_permission,
)
from app.core.security import get_password_hash
from app.schemas.user import try_normalize_phone
from app.services import panel_sections

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/schedule")
async def get_my_schedule(
    current_user: User = Depends(require_is_master),
    db: AsyncSession = Depends(get_db)
):
    """Своё расписание — у кого есть активная карточка мастера (не по role)."""
    
    result = await db.execute(
        select(Master).where(Master.user_id == current_user.id)
    )
    master = result.scalar_one_or_none()
    
    if not master:
        raise HTTPException(status_code=404, detail="Профиль мастера не найден")
    
    bookings_result = await db.execute(
        select(Booking)
        .where(
            Booking.master_id == master.id,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
        )
        .order_by(Booking.start_time)
    )
    bookings = bookings_result.scalars().all()
    
    return {
        "master_id": master.id,
        "specialization": master.specialization,
        "bookings": [
            {
                "id": b.id,
                "start_time": b.start_time.isoformat(),
                "end_time": b.end_time.isoformat(),
                "status": b.status.value,
                "client_name": f"Клиент #{b.client_id}"
            }
            for b in bookings
        ]
    }


async def _sync_billing_headcount(db, salon_id: int) -> None:
    """Пересчитать «планку» оплаченного штата салона после изменений в составе.

    Штат вырос сверх оплаченного — начисляем доплату за остаток месяца (она
    попадёт в следующий счёт, сейчас денег не берём). Сокращение штата планку
    не опускает: возвратов нет, а повторное включение того же мастера не
    должно начислять второй раз (см. services/subscription.register_headcount).
    """
    from sqlalchemy import func as _func
    from app.models.models import Salon as _Salon
    from app.services.subscription import register_headcount

    salon = await db.get(_Salon, salon_id)
    if salon is None:
        return
    active = (await db.execute(
        select(_func.count(Master.id)).where(
            Master.salon_id == salon_id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0
    charged = register_headcount(salon, active)
    await db.commit()

    # Счёт вырастет — предупреждаем сразу, а не постфактум при списании
    if charged > 0:
        try:
            from app.services.notifications import notify_subscription
            from app.services.tariffs import TARIFF_CATALOG
            tariff = TARIFF_CATALOG.get(salon.business_tier)
            plan_str = f"тариф «{tariff.name}», " if tariff else ""
            await notify_subscription(
                db, salon,
                f"в салоне теперь {active} активных мастеров: {plan_str}"
                f"доплата за остаток месяца {int(round(float(charged)))} ₽ войдёт в следующий счёт.",
            )
        except Exception:
            logger.exception("уведомление о росте тарифа не отправлено (salon=%s)", salon_id)


@router.post("/create-web")
async def create_master_web(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(...),
    specialization: str = Form(...),
    experience_years: int = Form(0),
    salon_id: int = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Добавление мастера владельцем/админом. Возвращает JSON; при создании
    НОВОГО аккаунта — реквизиты для попапа (пароль не уходит в URL)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"status": "error", "detail": "Требуется вход"}, status_code=401)

    try:
        await check_salon_permission(db, user, salon_id, "manage_masters")
    except HTTPException:
        return JSONResponse({"status": "error", "detail": "Недостаточно прав для управления мастерами"}, status_code=403)
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        return JSONResponse({"status": "error", "detail": "Салон не найден"}, status_code=404)

    # В режиме «работаю один» найма нет (решение 0007, дополнение 30.09).
    # Кнопки в панели там и нет — но кнопка это удобство, а запрет правило:
    # страницу можно держать открытой в двух вкладках и сменить режим в одной
    # из них, а форму — послать и без панели.
    if panel_sections.is_solo(salon):
        return JSONResponse({
            "status": "error", "code": "solo_mode",
            "detail": "Сначала переключитесь на режим «у меня команда» в настройках салона.",
        }, status_code=409)

    # Телефон нормализуем к +7XXXXXXXXXX — это же логин мастера.
    norm_phone = try_normalize_phone(phone)
    if norm_phone is None:
        return JSONResponse({"status": "error", "detail": "Некорректный номер телефона"}, status_code=400)

    temp_password = None
    existing_user = (await db.execute(select(User).where(User.phone == norm_phone))).scalar_one_or_none()
    if existing_user:
        existing_master = (await db.execute(select(Master).where(Master.user_id == existing_user.id))).scalar_one_or_none()
        if existing_master:
            return JSONResponse({"status": "error", "detail": "Мастер с таким телефоном уже добавлен"}, status_code=400)
        master_user = existing_user
    else:
        # Уникальный временный пароль — показываем в попапе один раз.
        temp_password = secrets.token_urlsafe(9)
        master_user = User(
            phone=norm_phone, full_name=full_name,
            hashed_password=get_password_hash(temp_password),
            role=UserRole.MASTER, is_active=True,
        )
        db.add(master_user)
        await db.flush()

    master = Master(
        user_id=master_user.id, salon_id=salon.id,
        specialization=specialization, experience_years=experience_years, rating=0.0,
    )
    db.add(master)
    await db.commit()
    await _sync_billing_headcount(db, salon.id)

    # Реквизиты возвращаем только для НОВОГО аккаунта (у существующего — свой пароль).
    creds = None
    if temp_password:
        creds = {"name": full_name, "login": norm_phone, "password": temp_password}
    return JSONResponse({"status": "ok", "credentials": creds})


@router.post("/{master_id}/reset-password")
async def reset_master_password(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Сброс пароля мастера: генерит новый временный пароль и возвращает
    реквизиты для попапа (на случай «упустил окно» / забытого пароля)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"status": "error", "detail": "Требуется вход"}, status_code=401)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if master is None:
        return JSONResponse({"status": "error", "detail": "Мастер не найден"}, status_code=404)
    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return JSONResponse({"status": "error", "detail": "Недостаточно прав"}, status_code=403)

    master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
    if master_user is None:
        return JSONResponse({"status": "error", "detail": "Аккаунт мастера не найден"}, status_code=404)
    salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
    if salon is not None and salon.creator_id == master_user.id:
        return JSONResponse({"status": "error", "detail": "Нельзя сбросить пароль создателя салона"}, status_code=400)

    new_password = secrets.token_urlsafe(9)
    master_user.hashed_password = get_password_hash(new_password)
    await db.commit()
    return JSONResponse({"status": "ok", "credentials": {
        "name": master_user.full_name, "login": master_user.phone, "password": new_password,
    }})


@router.post("/{master_id}/update")
async def update_master_web(
    master_id: int,
    request: Request,
    full_name: str = Form(...),
    specialization: str = Form(...),
    experience_years: int = Form(0),
    db: AsyncSession = Depends(get_db)
):
    """Обновление данных мастера владельцем/админом салона."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления мастерами", status_code=403)
    
    # Обновляем имя пользователя
    master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
    if master_user:
        master_user.full_name = full_name
    
    # Обновляем данные мастера
    master.specialization = specialization
    master.experience_years = experience_years
    await db.commit()
    
    return RedirectResponse(url="/business/my-salon?updated=1", status_code=302)


@router.post("/{master_id}/delete")
async def delete_master_web(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Удаление мастера владельцем/админом салона."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления мастерами", status_code=403)

    # Мягкое удаление: мастер скрывается (is_active=False), но его услуги,
    # брони и отзывы (история записей клиентов) сохраняются. Hard-delete ронял
    # 500 (ORM обнулял services.master_id NOT NULL) и снёс бы историю клиентов.
    master.is_active = False
    await db.commit()

    return RedirectResponse(url="/business/my-salon?deleted=1", status_code=302)


@router.post("/{master_id}/toggle")
async def toggle_master_web(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Включение/отключение мастера."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления мастерами", status_code=403)

    master.is_active = not master.is_active

    if not master.is_active:
        # Мастер ушёл из салона — отзывы «про него» остаются в общем списке
        # салона, но перестают быть привязаны к конкретному (уже неактивному)
        # мастеру. Фото в этих отзывах не трогаем — они относятся к отзыву,
        # не к мастеру напрямую.
        await db.execute(
            update(Review)
            .where(Review.master_id == master.id, Review.target_type == ReviewTargetType.MASTER)
            .values(master_id=None)
        )

    await db.commit()
    await _sync_billing_headcount(db, master.salon_id)

    return RedirectResponse(url="/business/dashboard?tab=employees", status_code=302)


DEFAULT_HAIR_SURVEY_TAGS = [
    "Обесцвеченные / блонд",
    "Окрашенные",
    "Натуральные (неокрашенные)",
    "Есть седина",
    "Ранее делали кератин / ботокс",
    "Наращенные волосы",
    "Химическая завивка",
    "Поврежденные / секущиеся кончики",
]


@router.post("/{master_id}/hair-survey")
async def update_master_hair_survey(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Настройка консультационного опроса перед записью (параметры волос)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            from app.api.deps import get_current_user
            try:
                user = await get_current_user(request=request, token=auth_header.split(" ")[1], db=db)
            except Exception:
                pass
    if not user:
        if (
            "application/json" in request.headers.get("accept", "")
            or request.headers.get("content-type", "").startswith("application/json")
        ):
            raise HTTPException(status_code=401, detail="Не авторизован")
        return RedirectResponse(url="/login", status_code=302)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=404, detail="Мастер не найден")

    # Проверка прав: сам мастер или управляющий салоном
    if master.user_id != user.id:
        try:
            await check_salon_permission(db, user, master.salon_id, "manage_masters")
        except HTTPException:
            raise HTTPException(status_code=403, detail="Недостаточно прав")

    is_json = request.headers.get("content-type", "").startswith("application/json")
    return_url = None
    length_rules = {}
    type_rules = {}
    density_rules = {}
    custom_tags = []

    q_length_enabled = True
    q_type_enabled = True
    q_density_enabled = True
    q_tags_enabled = True
    custom_questions = []

    if is_json:
        body = await request.json()
        enabled = bool(body.get("enabled", False))
        q_length_enabled = bool(body.get("q_length_enabled", True))
        q_type_enabled = bool(body.get("q_type_enabled", True))
        q_density_enabled = bool(body.get("q_density_enabled", True))
        q_tags_enabled = bool(body.get("q_tags_enabled", True))
        custom_questions = body.get("custom_questions") or []
        length_rules = body.get("length_rules") or {}
        type_rules = body.get("type_rules") or {}
        density_rules = body.get("density_rules") or {}
        custom_tags = body.get("custom_tags") or body.get("tags")
        if custom_tags is None:
            custom_tags = list(DEFAULT_HAIR_SURVEY_TAGS)
    else:
        form = await request.form()
        enabled = form.get("enabled") in ("1", "true", "on")
        return_url = form.get("return_url")

        q_length_enabled = form.get("q_length_enabled") in ("1", "true", "on")
        q_type_enabled = form.get("q_type_enabled") in ("1", "true", "on")
        q_density_enabled = form.get("q_density_enabled") in ("1", "true", "on")
        q_tags_enabled = form.get("q_tags_enabled") in ("1", "true", "on")

        cq_json = form.get("custom_questions_json")
        if cq_json:
            try:
                parsed_cq = json.loads(cq_json)
                if isinstance(parsed_cq, list):
                    custom_questions = parsed_cq
            except Exception:
                custom_questions = []

        # Парсинг правил длины
        for i in range(1, 8):
            lp = form.get(f"len_price_{i}")
            ld = form.get(f"len_duration_{i}")
            if lp is not None or ld is not None:
                length_rules[str(i)] = {
                    "price": int(lp) if lp and str(lp).isdigit() else 0,
                    "duration": int(ld) if ld and str(ld).isdigit() else 0,
                }

        # Парсинг правил типов
        for tid in ("straight", "wavy", "curly", "coarse"):
            tp = form.get(f"type_price_{tid}")
            td = form.get(f"type_duration_{tid}")
            if tp is not None or td is not None:
                type_rules[tid] = {
                    "price": int(tp) if tp and str(tp).isdigit() else 0,
                    "duration": int(td) if td and str(td).isdigit() else 0,
                }

        # Парсинг правил густоты
        for did in ("thin", "medium", "thick"):
            dp = form.get(f"density_price_{did}")
            dd = form.get(f"density_duration_{did}")
            if dp is not None or dd is not None:
                density_rules[did] = {
                    "price": int(dp) if dp and str(dp).isdigit() else 0,
                    "duration": int(dd) if dd and str(dd).isdigit() else 0,
                }

        # Парсинг вопросов анкеты с доплатами и добавочным временем
        tag_names = form.getlist("tag_name")
        tag_prices = form.getlist("tag_price")
        tag_durations = form.getlist("tag_duration")
        if tag_names:
            for idx, name in enumerate(tag_names):
                name = name.strip()
                if not name:
                    continue
                p = int(tag_prices[idx]) if idx < len(tag_prices) and str(tag_prices[idx]).isdigit() else 0
                d = int(tag_durations[idx]) if idx < len(tag_durations) and str(tag_durations[idx]).isdigit() else 0
                custom_tags.append({"name": name, "price": p, "duration": d})
        else:
            raw_tags = form.getlist("tags")
            if not raw_tags:
                custom_tags_str = form.get("custom_tags", "")
                if custom_tags_str:
                    raw_tags = [t.strip() for t in custom_tags_str.split(",") if t.strip()]
            if raw_tags:
                custom_tags = [t if isinstance(t, dict) else {"name": str(t), "price": 0, "duration": 0} for t in raw_tags]
            else:
                custom_tags = list(DEFAULT_HAIR_SURVEY_TAGS)

    simple_tag_names = [t["name"] if isinstance(t, dict) else str(t) for t in custom_tags]

    master.hair_survey_enabled = enabled
    master.hair_survey_settings = {
        "q_length_enabled": q_length_enabled,
        "q_type_enabled": q_type_enabled,
        "q_density_enabled": q_density_enabled,
        "q_tags_enabled": q_tags_enabled,
        "custom_questions": custom_questions,
        "tags": simple_tag_names,
        "custom_tags": custom_tags,
        "length_rules": length_rules,
        "type_rules": type_rules,
        "density_rules": density_rules,
        "require_length": q_length_enabled,
        "require_type": q_type_enabled,
        "require_density": q_density_enabled,
    }
    await db.commit()

    if is_json:
        return {
            "ok": True,
            "enabled": master.hair_survey_enabled,
            "settings": master.hair_survey_settings,
        }
    return RedirectResponse(
        url=return_url or f"/business/dashboard?salon_id={master.salon_id}&tab=interactive&ok=survey_saved",
        status_code=302,
    )
