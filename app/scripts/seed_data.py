# app/scripts/seed_data.py
import asyncio
import json
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.models import (
    Salon, Master, User, Service, Promotion, UserRole, Base,
    SalonMember, SalonRole, OWNER_DEFAULT_PERMISSIONS,
    Booking, BookingStatus, Review,
    SalonLoyaltySettings, LoyaltyOffer, ClientLoyalty, LoyaltyStatusSource,
    InventoryItem, MasterPayrollSettings, SalonModerationStatus, ModelModerationStatus,
)
from app.core.config import settings
from app.core.security import get_password_hash

# График работы: слоты записи считаются от него (schedule_utils) — без графика
# ни один салон не покажет ни одного слота.
WORK_WEEK = json.dumps({
    "mon": "10:00-21:00", "tue": "10:00-21:00", "wed": "10:00-21:00",
    "thu": "10:00-21:00", "fri": "10:00-21:00", "sat": "11:00-19:00",
    "sun": "выходной",
})
WORK_DAILY = json.dumps({
    d: "10:00-20:00" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
})
WORK_SHORT = json.dumps({
    "mon": "10:00-18:00", "tue": "10:00-18:00", "wed": "10:00-18:00",
    "thu": "10:00-18:00", "fri": "10:00-18:00", "sat": "10:00-15:00",
    "sun": "выходной",
})

# Единый dev-пароль для всех сидовых пользователей (Argon2id). Только для локалки.
DEV_PASSWORD = "Seedpass1"

def _at(day_shift: int, hour: int, minute: int = 0) -> datetime:
    """Возвращает datetime с заданным смещением относительно текущего дня."""
    return (datetime.now() + timedelta(days=day_shift)).replace(hour=hour, minute=minute, second=0, microsecond=0)

async def seed_database():
    engine = create_async_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Создаём таблицы (если их ещё нет)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with async_session() as session:
        # Проверяем, есть ли уже салоны в базе
        existing_salons = await session.execute(select(func.count(Salon.id)))
        salon_count = existing_salons.scalar()
        
        if salon_count > 0:
            print(f"✅ База уже содержит {salon_count} салонов. Seed не требуется.")
            return
        
        print("🔄 База пуста. Заполняем тестовыми данными...")
        
        # ========== САЛОНЫ ==========
        s1 = Salon(name="Брутальный", description="Мужские стрижки, борода, уход", address="Москва, ул. Тверская, 15", city="Москва", latitude=55.761859, longitude=37.606138, phone="+79991234567", rating=0.0, reviews_count=0, moderation_status=SalonModerationStatus.APPROVED, timezone="Europe/Moscow", working_hours=WORK_WEEK)
        s2 = Salon(name="Classic", description="Классические мужские стрижки", address="Санкт-Петербург, Невский пр., 22", city="Санкт-Петербург", latitude=59.934280, longitude=30.335099, phone="+78121234567", rating=0.0, reviews_count=0, moderation_status=SalonModerationStatus.APPROVED, timezone="Europe/Moscow", working_hours=WORK_DAILY)
        s3 = Salon(name="Имидж", description="Женские и мужские стрижки, окрашивание", address="Москва, пр. Мира, 45", city="Москва", latitude=55.779438, longitude=37.636928, phone="+74959876543", rating=0.0, reviews_count=0, moderation_status=SalonModerationStatus.APPROVED, timezone="Europe/Moscow", working_hours=WORK_WEEK)
        s4 = Salon(name="Гламур", description="Маникюр, педикюр, наращивание", address="Санкт-Петербург, Большой пр. П.С., 10", city="Санкт-Петербург", latitude=59.962264, longitude=30.308452, phone="+78123334455", rating=0.0, reviews_count=0, moderation_status=SalonModerationStatus.APPROVED, timezone="Europe/Moscow", working_hours=WORK_DAILY)
        s5 = Salon(name="Элегант", description="Стрижки, укладки, уход за волосами", address="Казань, ул. Баумана, 33", city="Казань", latitude=55.792752, longitude=49.121467, phone="+78432987654", rating=0.0, reviews_count=0, moderation_status=SalonModerationStatus.APPROVED, timezone="Europe/Moscow", working_hours=WORK_WEEK)
        s6 = Salon(name="Стиль", description="Современные стрижки и окрашивание", address="Екатеринбург, ул. Ленина, 10", city="Екатеринбург", latitude=56.838926, longitude=60.605704, phone="+73432987654", rating=0.0, reviews_count=0, moderation_status=SalonModerationStatus.APPROVED, timezone="Asia/Yekaterinburg", working_hours=WORK_DAILY)
        s7 = Salon(name="Эстетика", description="Услуги бровиста и визажиста", address="Новосибирск, пр. Красный, 20", city="Новосибирск", latitude=55.030204, longitude=82.920430, phone="+73832987654", rating=0.0, reviews_count=0, moderation_status=SalonModerationStatus.APPROVED, timezone="Asia/Novosibirsk", working_hours=WORK_SHORT)
        session.add_all([s1, s2, s3, s4, s5, s6, s7])
        await session.flush()
        
        # ========== МАСТЕРА ==========
        # Брутальный (s1)
        u1 = User(phone="+79991112233", full_name="Александр Петров", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u1)
        await session.flush()
        m1 = Master(user_id=u1.id, salon_id=s1.id, specialization="барбер-стилист", experience_years=5, rating=0.0)
        session.add(m1)
        await session.flush()
        session.add_all([
            Service(master_id=m1.id, name="Стрижка машинкой", price=1500, duration_minutes=30),
            Service(master_id=m1.id, name="Стрижка + борода", price=2400, duration_minutes=60),
            Service(master_id=m1.id, name="Моделирование бороды", price=1200, duration_minutes=30)
        ])
        
        u2 = User(phone="+79992223344", full_name="Дмитрий Волков", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u2)
        await session.flush()
        m2 = Master(user_id=u2.id, salon_id=s1.id, specialization="барбер-колорист", experience_years=3, rating=0.0)
        session.add(m2)
        await session.flush()
        session.add_all([
            Service(master_id=m2.id, name="Стрижка ножницами", price=2000, duration_minutes=45),
            Service(master_id=m2.id, name="Камуфляж седины", price=1800, duration_minutes=40),
            Service(master_id=m2.id, name="Окрашивание бороды", price=1500, duration_minutes=30)
        ])
        
        # Classic (s2)
        u3 = User(phone="+78121112233", full_name="Сергей Козлов", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u3)
        await session.flush()
        m3 = Master(user_id=u3.id, salon_id=s2.id, specialization="стилист-парикмахер", experience_years=7, rating=0.0)
        session.add(m3)
        await session.flush()
        session.add_all([
            Service(master_id=m3.id, name="Классическая стрижка", price=1800, duration_minutes=40),
            Service(master_id=m3.id, name="Укладка", price=1200, duration_minutes=30),
            Service(master_id=m3.id, name="Спа-уход", price=2500, duration_minutes=60)
        ])
        
        # Имидж (s3)
        u4 = User(phone="+74951113344", full_name="Елена Смирнова", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u4)
        await session.flush()
        m4 = Master(user_id=u4.id, salon_id=s3.id, specialization="стилист-колорист", experience_years=8, rating=0.0)
        session.add(m4)
        await session.flush()
        session.add_all([
            Service(master_id=m4.id, name="Окрашивание", price=4500, duration_minutes=120),
            Service(master_id=m4.id, name="Стрижка женская", price=3000, duration_minutes=60),
            Service(master_id=m4.id, name="Тонирование", price=2800, duration_minutes=90),
            Service(master_id=m4.id, name="Мелирование", price=4000, duration_minutes=100)
        ])
        
        # Гламур (s4)
        u5 = User(phone="+78124445566", full_name="Ольга Иванова", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u5)
        await session.flush()
        m5 = Master(user_id=u5.id, salon_id=s4.id, specialization="мастер маникюра", experience_years=6, rating=0.0)
        session.add(m5)
        await session.flush()
        session.add_all([
            Service(master_id=m5.id, name="Маникюр классический", price=1800, duration_minutes=60),
            Service(master_id=m5.id, name="Педикюр", price=2500, duration_minutes=90),
            Service(master_id=m5.id, name="Наращивание ногтей", price=3500, duration_minutes=120),
            Service(master_id=m5.id, name="Дизайн ногтей", price=800, duration_minutes=30)
        ])
        
        u5b = User(phone="+78124445567", full_name="Наталья Соколова", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u5b)
        await session.flush()
        m5b = Master(user_id=u5b.id, salon_id=s4.id, specialization="мастер педикюра", experience_years=4, rating=0.0)
        session.add(m5b)
        await session.flush()
        session.add_all([
            Service(master_id=m5b.id, name="Педикюр аппаратный", price=3000, duration_minutes=90),
            Service(master_id=m5b.id, name="Педикюр+покрытие", price=4000, duration_minutes=120)
        ])
        
        # Элегант (s5)
        u6 = User(phone="+78431112233", full_name="Марина Попова", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u6)
        await session.flush()
        m6 = Master(user_id=u6.id, salon_id=s5.id, specialization="стилист-визажист", experience_years=4, rating=0.0)
        session.add(m6)
        await session.flush()
        session.add_all([
            Service(master_id=m6.id, name="Стрижка + укладка", price=2500, duration_minutes=60),
            Service(master_id=m6.id, name="Окрашивание бровей", price=1200, duration_minutes=30),
            Service(master_id=m6.id, name="Ламинирование ресниц", price=2000, duration_minutes=60),
            Service(master_id=m6.id, name="Макияж", price=3500, duration_minutes=90)
        ])
        
        # Стиль (s6)
        u7 = User(phone="+73431112233", full_name="Анна Ковалева", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u7)
        await session.flush()
        m7 = Master(user_id=u7.id, salon_id=s6.id, specialization="стилист-парикмахер", experience_years=5, rating=0.0)
        session.add(m7)
        await session.flush()
        session.add_all([
            Service(master_id=m7.id, name="Стрижка женская", price=2800, duration_minutes=60),
            Service(master_id=m7.id, name="Окрашивание", price=4200, duration_minutes=120),
            Service(master_id=m7.id, name="Укладка", price=1500, duration_minutes=30)
        ])
        
        # Эстетика (s7) – бровист
        u8 = User(phone="+73831112233", full_name="Екатерина Лебедева", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.MASTER, is_active=True)
        session.add(u8)
        await session.flush()
        m8 = Master(user_id=u8.id, salon_id=s7.id, specialization="бровист-визажист", experience_years=3, rating=0.0)
        session.add(m8)
        await session.flush()
        session.add_all([
            Service(master_id=m8.id, name="Коррекция бровей", price=1000, duration_minutes=30),
            Service(master_id=m8.id, name="Окрашивание бровей", price=1200, duration_minutes=30),
            Service(master_id=m8.id, name="Ламинирование бровей", price=2500, duration_minutes=60),
            Service(master_id=m8.id, name="Макияж", price=3000, duration_minutes=60)
        ])
        
        # ========== АКЦИИ (больше) ==========
        promos = [
            (s1.id, "Первый визит −20%", "Скидка 20% на все услуги для новых клиентов", "Новичкам"),
            (s1.id, "Комбо стрижка + борода", "Стрижка и моделирование бороды за 2200₽ вместо 2400₽", "Выгода"),
            (s2.id, "Приведи друга", "Получите скидку 500₽ за каждого приведённого друга", "Друзьям"),
            (s2.id, "Счастливые часы", "Скидка 15% на все услуги с 09:00 до 12:00", "−15%"),
            (s3.id, "Окрашивание + укладка", "При окрашивании — укладка в подарок", "Подарок"),
            (s3.id, "Студентам −15%", "Скидка 15% на стрижки по студенческому", "Студентам"),
            (s4.id, "Маникюр + педикюр", "Комбо со скидкой 10% при заказе двух услуг", "−10%"),
            (s4.id, "День рождения", "Скидка 25% на любые услуги в день рождения и 3 дня после", "🎂"),
            (s5.id, "Брови + ресницы", "Коррекция и окрашивание бровей + ламинирование ресниц за 2500₽", "Комбо"),
            (s5.id, "Скидка 20% на первое посещение", "При первом визите скидка 20% на любую услугу", "Новичкам"),
            (s6.id, "Окрашивание со скидкой", "При окрашивании — скидка 15% на вторую услугу", "Экономия"),
            (s7.id, "Брови+макияж", "Комплекс брови + макияж за 3500₽", "Комбо"),
        ]
        for sid, title, desc, tag in promos:
            session.add(Promotion(salon_id=sid, title=title, description=desc, tag=tag))
        
        # ========== ПОЛЬЗОВАТЕЛИ (много клиентов) ==========
        test_users = [
            User(phone="+79990000001", full_name="Анна Клиент", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000002", full_name="Игорь Владелец", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.BUSINESS, is_active=True),
            User(
                phone="+79990000003", full_name="Мария Модель", hashed_password=get_password_hash(DEV_PASSWORD),
                role=UserRole.CLIENT, is_active=True, is_model=True,
                model_bio="Ищу мастеров для практики окрашивания и стрижек.",
                model_looking_for="Окрашивание, стрижка",
                model_moderation_status=ModelModerationStatus.APPROVED,
            ),
            User(phone="+79990000010", full_name="Дмитрий Смирнов", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000011", full_name="Екатерина Иванова", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000012", full_name="Сергей Петров", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000013", full_name="Ольга Соколова", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000014", full_name="Алексей Кузнецов", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000015", full_name="Наталья Морозова", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000016", full_name="Максим Васильев", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000017", full_name="Виктория Зайцева", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
            User(phone="+79990000018", full_name="Андрей Новиков", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True),
        ]
        
        for tu in test_users:
            existing = await session.execute(select(User).where(User.phone == tu.phone))
            if not existing.scalar_one_or_none():
                session.add(tu)
        await session.flush()
        
        # ========== ВЛАДЕЛЬЦЫ САЛОНОВ ==========
        owner = await session.execute(select(User).where(User.phone == "+79990000002"))
        owner = owner.scalar_one_or_none()
        owner2 = await session.execute(select(User).where(User.phone == "+79990000004"))
        owner2 = owner2.scalar_one_or_none()
        if not owner2:
            owner2 = User(phone="+79990000004", full_name="Светлана Хозяйка", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.BUSINESS, is_active=True)
            session.add(owner2)
            await session.flush()
        
        # Привязываем владельцев
        if owner:
            s1.creator_id = owner.id
            session.add(SalonMember(salon_id=s1.id, user_id=owner.id, role=SalonRole.OWNER,
                                    is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True))
            s2.creator_id = owner.id
            session.add(SalonMember(salon_id=s2.id, user_id=owner.id, role=SalonRole.OWNER,
                                    is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True))
        if owner2:
            s3.creator_id = owner2.id
            session.add(SalonMember(salon_id=s3.id, user_id=owner2.id, role=SalonRole.OWNER,
                                    is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True))
            s4.creator_id = owner2.id
            session.add(SalonMember(salon_id=s4.id, user_id=owner2.id, role=SalonRole.OWNER,
                                    is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True))
            s5.creator_id = owner2.id
            session.add(SalonMember(salon_id=s5.id, user_id=owner2.id, role=SalonRole.OWNER,
                                    is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True))
            s6.creator_id = owner2.id
            session.add(SalonMember(salon_id=s6.id, user_id=owner2.id, role=SalonRole.OWNER,
                                    is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True))
            s7.creator_id = owner2.id
            session.add(SalonMember(salon_id=s7.id, user_id=owner2.id, role=SalonRole.OWNER,
                                    is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True))
        
        # Добавляем админа в s1 с ограниченными правами
        staff1 = await session.execute(select(User).where(User.phone == "+79990000005"))
        staff1 = staff1.scalar_one_or_none()
        if not staff1:
            staff1 = User(phone="+79990000005", full_name="Тимур Администратор", hashed_password=get_password_hash(DEV_PASSWORD), role=UserRole.CLIENT, is_active=True)
            session.add(staff1)
            await session.flush()
        session.add(SalonMember(salon_id=s1.id, user_id=staff1.id, role=SalonRole.ADMIN,
                                is_creator=False, is_active=True,
                                permissions={"manage_inventory": True, "manage_schedule": True}))
        
        # ========== ЗАПИСИ (много, на разные дни и статусы) ==========
        client_user = await session.execute(select(User).where(User.phone == "+79990000001"))
        client_user = client_user.scalar_one_or_none()
        client2 = await session.execute(select(User).where(User.phone == "+79990000010"))
        client2 = client2.scalar_one_or_none()
        client3 = await session.execute(select(User).where(User.phone == "+79990000011"))
        client3 = client3.scalar_one_or_none()
        client4 = await session.execute(select(User).where(User.phone == "+79990000012"))
        client4 = client4.scalar_one_or_none()
        client5 = await session.execute(select(User).where(User.phone == "+79990000013"))
        client5 = client5.scalar_one_or_none()
        client6 = await session.execute(select(User).where(User.phone == "+79990000014"))
        client6 = client6.scalar_one_or_none()
        
        # Услуги для разных мастеров
        svc_m1_1 = await session.execute(select(Service).where(Service.master_id == m1.id, Service.name == "Стрижка машинкой"))
        svc_m1_1 = svc_m1_1.scalar_one_or_none()
        svc_m1_2 = await session.execute(select(Service).where(Service.master_id == m1.id, Service.name == "Стрижка + борода"))
        svc_m1_2 = svc_m1_2.scalar_one_or_none()
        svc_m2_1 = await session.execute(select(Service).where(Service.master_id == m2.id, Service.name == "Стрижка ножницами"))
        svc_m2_1 = svc_m2_1.scalar_one_or_none()
        svc_m3_1 = await session.execute(select(Service).where(Service.master_id == m3.id, Service.name == "Классическая стрижка"))
        svc_m3_1 = svc_m3_1.scalar_one_or_none()
        svc_m4_1 = await session.execute(select(Service).where(Service.master_id == m4.id, Service.name == "Окрашивание"))
        svc_m4_1 = svc_m4_1.scalar_one_or_none()
        svc_m5_1 = await session.execute(select(Service).where(Service.master_id == m5.id, Service.name == "Маникюр классический"))
        svc_m5_1 = svc_m5_1.scalar_one_or_none()
        svc_m6_1 = await session.execute(select(Service).where(Service.master_id == m6.id, Service.name == "Стрижка + укладка"))
        svc_m6_1 = svc_m6_1.scalar_one_or_none()
        svc_m7_1 = await session.execute(select(Service).where(Service.master_id == m7.id, Service.name == "Стрижка женская"))
        svc_m7_1 = svc_m7_1.scalar_one_or_none()
        svc_m8_1 = await session.execute(select(Service).where(Service.master_id == m8.id, Service.name == "Коррекция бровей"))
        svc_m8_1 = svc_m8_1.scalar_one_or_none()

        # Создаём много записей: 14 дней назад до +14 дней вперёд, с разными статусами
        bookings = []
        clients = [client_user, client2, client3, client4, client5, client6]
        masters_services = [
            (m1, svc_m1_1),
            (m1, svc_m1_2),
            (m2, svc_m2_1),
            (m3, svc_m3_1),
            (m4, svc_m4_1),
            (m5, svc_m5_1),
            (m6, svc_m6_1),
            (m7, svc_m7_1),
            (m8, svc_m8_1),
        ]
        
        # Добавляем записи за последние 30 дней, чтобы была статистика
        for day_offset in range(-14, 15):
            day = datetime.now() + timedelta(days=day_offset)
            # Пропускаем выходные (суббота 5, воскресенье 6)
            if day.weekday() in (5, 6):
                continue
            # Для каждого дня создаём 3-5 записей
            num_bookings = 3 + (day_offset % 3)  # 3-5 записей в день
            for i in range(num_bookings):
                client = clients[i % len(clients)]
                master, service = masters_services[(i + day_offset) % len(masters_services)]
                
                # Время: с 10 до 19, шаг 1 час
                start_hour = 10 + (i * 2) % 9
                start_time = day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
                end_time = start_time + timedelta(minutes=service.duration_minutes if service else 30)
                
                # Статус: для прошедших дней - COMPLETED, для будущих - CONFIRMED или PENDING
                if day_offset < 0:
                    status = BookingStatus.COMPLETED
                    final_price = service.price if service else 1500
                elif day_offset == 0:
                    # Сегодня: смесь статусов
                    if i % 3 == 0:
                        status = BookingStatus.COMPLETED
                    elif i % 3 == 1:
                        status = BookingStatus.CONFIRMED
                    else:
                        status = BookingStatus.PENDING
                    final_price = service.price if service else 1500
                else:
                    # Будущие
                    if i % 4 == 0:
                        status = BookingStatus.CANCELLED
                    else:
                        status = BookingStatus.CONFIRMED if i % 2 == 0 else BookingStatus.PENDING
                    final_price = service.price if service else 1500
                
                bookings.append(Booking(
                    client_id=client.id,
                    master_id=master.id,
                    service_id=service.id,
                    start_time=start_time,
                    end_time=end_time,
                    status=status,
                    final_price=final_price
                ))
        
        # Добавляем ещё несколько специальных записей для лояльности и отзывов
        # Для клиента Анна (client_user) добавляем 5 завершённых визитов в s1
        for i in range(5):
            day = datetime.now() - timedelta(days=30 + i*3)
            start_time = day.replace(hour=12 + i, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(minutes=60)
            bookings.append(Booking(
                client_id=client_user.id,
                master_id=m1.id,
                service_id=svc_m1_1.id,
                start_time=start_time,
                end_time=end_time,
                status=BookingStatus.COMPLETED,
                final_price=1500
            ))
        
        # ========== ЗАПИСИ ДЛЯ ИГОРЯ ВЛАДЕЛЬЦА ==========
        # Игорь – владелец салона, но также может иметь свои записи как клиент.
        # Добавим ему 3 завершённых и 2 отменённых записи в салоне "Брутальный" (s1)
        user_igor = await session.execute(select(User).where(User.phone == "+79990000002"))
        user_igor = user_igor.scalar_one_or_none()
        if user_igor:
            # Завершённые записи (COMPLETED)
            completed_dates = [
                (datetime.now() - timedelta(days=5), 14, svc_m1_1, m1),
                (datetime.now() - timedelta(days=10), 15, svc_m1_2, m1),
                (datetime.now() - timedelta(days=15), 16, svc_m2_1, m2),
            ]
            for day, hour, service, master in completed_dates:
                start_time = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                end_time = start_time + timedelta(minutes=service.duration_minutes if service else 30)
                bookings.append(Booking(
                    client_id=user_igor.id,
                    master_id=master.id,
                    service_id=service.id,
                    start_time=start_time,
                    end_time=end_time,
                    status=BookingStatus.COMPLETED,
                    final_price=service.price if service else 1500
                ))
            
            # Отменённые записи (CANCELLED)
            cancelled_dates = [
                (datetime.now() - timedelta(days=3), 12, svc_m1_1, m1),
                (datetime.now() - timedelta(days=7), 13, svc_m2_1, m2),
            ]
            for day, hour, service, master in cancelled_dates:
                start_time = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                end_time = start_time + timedelta(minutes=service.duration_minutes if service else 30)
                bookings.append(Booking(
                    client_id=user_igor.id,
                    master_id=master.id,
                    service_id=service.id,
                    start_time=start_time,
                    end_time=end_time,
                    status=BookingStatus.CANCELLED,
                    final_price=None  # отменённые записи не имеют цены
                ))
        
        session.add_all(bookings)
        await session.flush()
        
        # ========== ОТЗЫВЫ (много) ==========
        # Получаем все завершённые записи
        completed_bookings = await session.execute(
            select(Booking).where(Booking.status == BookingStatus.COMPLETED)
        )
        completed_bookings = completed_bookings.scalars().all()
        
        reviews_data = [
            "Отличный мастер, всё супер!",
            "Хорошо, но немного долго.",
            "Очень понравилось, приду ещё!",
            "Спасибо, всё отлично!",
            "Нормально, но можно лучше.",
            "Мастер профессионал, рекомендую!",
            "Всё понравилось, красиво сделали!",
            "Немного не совпало с ожиданиями, но хорошо.",
            "Лучший мастер в городе!",
            "Отлично, быстро и качественно.",
        ]
        
        reviews = []
        for i, booking in enumerate(completed_bookings[:30]):  # Берём первые 30 записей
            rating = 4 + (i % 2)  # 4 или 5 звёзд
            comment = reviews_data[i % len(reviews_data)]
            review = Review(
                client_id=booking.client_id,
                master_id=booking.master_id,
                salon_id=(await session.execute(select(Master.salon_id).where(Master.id == booking.master_id))).scalar_one(),
                rating=rating,
                comment=comment,
                created_at=booking.start_time
            )
            reviews.append(review)
        session.add_all(reviews)
        await session.flush()
        
        # Обновляем рейтинг салонов и мастеров
        for salon in [s1, s2, s3, s4, s5, s6, s7]:
            avg = await session.execute(
                select(func.avg(Review.rating)).where(Review.salon_id == salon.id)
            )
            salon.rating = round(avg.scalar() or 0.0, 1)
            cnt = await session.execute(
                select(func.count(Review.id)).where(Review.salon_id == salon.id)
            )
            salon.reviews_count = cnt.scalar() or 0
        
        for master in [m1, m2, m3, m4, m5, m5b, m6, m7, m8]:
            avg = await session.execute(
                select(func.avg(Review.rating)).where(Review.master_id == master.id)
            )
            master.rating = round(avg.scalar() or 0.0, 1)
        
        # ========== ЛОЯЛЬНОСТЬ (для s1) ==========
        session.add(SalonLoyaltySettings(
            salon_id=s1.id,
            regular_client_discount_percent=5,
            regular_client_visits_threshold=5,
            bonus_accrual_percent=5.0
        ))
        session.add(LoyaltyOffer(
            salon_id=s1.id,
            title="День рождения",
            discount_percent=15,
            promo_code="BDAY15",
            is_active=True
        ))
        session.add(LoyaltyOffer(
            salon_id=s1.id,
            title="Скидка постоянному клиенту",
            discount_percent=10,
            promo_code="REGULAR10",
            is_active=True
        ))
        
        # Клиент Анна становится постоянным клиентом s1
        session.add(ClientLoyalty(
            salon_id=s1.id,
            client_id=client_user.id,
            is_regular_client=True,
            regular_client_source=LoyaltyStatusSource.MANUAL,
            bonus_points=150
        ))
        
        # Клиент2 тоже постоянный клиент s1
        if client2:
            session.add(ClientLoyalty(
                salon_id=s1.id,
                client_id=client2.id,
                is_regular_client=True,
                regular_client_source=LoyaltyStatusSource.AUTO,
                bonus_points=50
            ))
        
        # ========== СКЛАД И ЗАРПЛАТА ==========
        # Для мастера m1 (Александр)
        session.add_all([
            InventoryItem(master_id=m1.id, name="Шампунь профессиональный", unit="мл",
                          quantity=1500.0, cost_per_unit=2, min_quantity=300.0),
            InventoryItem(master_id=m1.id, name="Воск для укладки", unit="г",
                          quantity=200.0, cost_per_unit=8, min_quantity=50.0),
            InventoryItem(master_id=m1.id, name="Лезвия для бритвы", unit="шт",
                          quantity=18.0, cost_per_unit=45, min_quantity=20.0),
            InventoryItem(master_id=m1.id, name="Гель для бороды", unit="мл",
                          quantity=300.0, cost_per_unit=5, min_quantity=100.0),
        ])
        session.add(MasterPayrollSettings(master_id=m1.id, base_salary=40000, commission_percent=30.0))
        
        # Для мастера m4 (Елена)
        session.add_all([
            InventoryItem(master_id=m4.id, name="Краска для волос", unit="мл",
                          quantity=500.0, cost_per_unit=15, min_quantity=100.0),
            InventoryItem(master_id=m4.id, name="Окислитель", unit="мл",
                          quantity=800.0, cost_per_unit=8, min_quantity=200.0),
        ])
        session.add(MasterPayrollSettings(master_id=m4.id, base_salary=50000, commission_percent=25.0))
        
        # Для мастера m5 (Ольга)
        session.add_all([
            InventoryItem(master_id=m5.id, name="База под гель-лак", unit="мл",
                          quantity=100.0, cost_per_unit=20, min_quantity=30.0),
            InventoryItem(master_id=m5.id, name="Топ-покрытие", unit="мл",
                          quantity=80.0, cost_per_unit=25, min_quantity=20.0),
        ])
        session.add(MasterPayrollSettings(master_id=m5.id, base_salary=35000, commission_percent=20.0))
        
        await session.commit()
        print("✅ База заполнена: 7 салонов, 9 мастеров, 25+ услуг, 12+ акций, "
              "множество записей на разные даты, отзывы, лояльность, склад, зарплаты!")
        print(f"   - Создано {len(bookings)} записей за последние 30 дней.")
        print(f"   - Добавлено {len(reviews)} отзывов.")
        print("   - Игорю Владельцу добавлены 3 завершённых и 2 отменённых записи.")

if __name__ == "__main__":
    asyncio.run(seed_database())