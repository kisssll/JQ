# app/models/models.py
import enum
from datetime import datetime, time, date as date_
from typing import Optional, List, Dict

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, ForeignKey, BigInteger,
    Text, DateTime, Date, Enum, CheckConstraint, Index, UniqueConstraint, JSON, text
)
from sqlalchemy.orm import relationship, declarative_base, Mapped, mapped_column
from sqlalchemy.sql import func

Base = declarative_base()

# --- Enums ---
class UserRole(str, enum.Enum):
    CLIENT = "client"
    MODEL = "model"
    MASTER = "master"
    BUSINESS = "business"
    ADMIN = "admin"

class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"

# Статусы, которые считаются «деньги добавлены» для всей финансовой
# статистики салона (Обзор, Аналитика, Зарплаты, Себестоимость) — единый
# источник, чтобы цифры не расходились между вкладками панели владельца.
# CONFIRMED уже считается доходом (бронь подтверждена/оплачена), не нужно
# дожидаться отметки «Пришёл» (COMPLETED) для признания выручки.
PAID_BOOKING_STATUSES = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)

class SubscriptionTier(str, enum.Enum):
    START = "start"
    PRO = "pro"
    PREMIUM = "premium"

class SalonRole(str, enum.Enum):
    OWNER = "owner"
    # Управляющий: правая рука владельца — шире обычного админа (по
    # умолчанию видит финансы/тариф/склад/зарплаты/аудит, может нанимать
    # админов), но не назначает совладельцев. Назначить/снять/поменять права
    # управляющего может только создатель салона (is_creator) — см.
    # app/api/v1/endpoints/staff.py.
    MANAGER = "manager"
    ADMIN = "admin"
    # MASTER сюда сознательно не входит: у мастера уже есть своя таблица
    # Master с operatonal-доступом, заскоупленным через Master.user_id —
    # ему не нужен настраиваемый словарь прав, который тут нужен owner/admin.

class InventoryMovementType(str, enum.Enum):
    RECEIPT = "receipt"          # приход (закупка)
    CONSUMPTION = "consumption"  # списание по факту после клиента
    ADJUSTMENT = "adjustment"    # корректировка по итогам инвентаризации

class InventoryAuditStatus(str, enum.Enum):
    DRAFT = "draft"          # акт открыт, идёт пересчёт
    CONFIRMED = "confirmed"  # акт закрыт, остатки скорректированы

class EquipmentStatus(str, enum.Enum):
    WORKING = "working"
    BROKEN = "broken"

class WarehouseRequestType(str, enum.Enum):
    CONSUMABLE_LOW = "consumable_low"    # расходник заканчивается (без точного остатка)
    EQUIPMENT_BROKEN = "equipment_broken"  # техника сломалась/нужна замена

class WarehouseRequestStatus(str, enum.Enum):
    PENDING = "pending"      # заявка открыта
    RESOLVED = "resolved"    # админ отреагировал (закупил/заменил)
    DISMISSED = "dismissed"  # отклонена

class LoyaltyStatusSource(str, enum.Enum):
    AUTO = "auto"      # статус выставлен автоматически по числу визитов
    MANUAL = "manual"  # статус выставлен/снят вручную админом

class LoyaltyPointsMovementType(str, enum.Enum):
    ACCRUAL = "accrual"            # автоначисление % от чека после оплаты
    MANUAL_ADD = "manual_add"      # ручное начисление админом
    REDEEMED = "redeemed"          # списание баллов клиентом при оплате
    MANUAL_REMOVE = "manual_remove"  # ручное списание админом (коррекция)

class ReviewTargetType(str, enum.Enum):
    MASTER = "master"  # отзыв о конкретном мастере
    SALON = "salon"    # отзыв о салоне в целом (помещение, сервис)
    STAFF = "staff"    # отзыв об админе/владельце салона (не мастере)

class PhotoReportStatus(str, enum.Enum):
    PENDING = "pending"      # жалоба открыта, ждёт решения
    RESOLVED = "resolved"    # жалоба удовлетворена, фото удалено
    DISMISSED = "dismissed"  # жалоба отклонена, фото осталось


class ModelModerationStatus(str, enum.Enum):
    """Модерация анкеты модели — тот же принцип, что у SalonModerationStatus:
    видна салонам в кандидатах только после APPROVED."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

# Ключи прав салона. Значение — можно ли делать соответствующее действие.
# У создателя салона (SalonMember.is_creator=True) все права всегда True
# независимо от словаря, плюс только он может удалить сам салон.
SALON_PERMISSION_KEYS = (
    "manage_salon",      # настройки, фото, описание, график салона
    "manage_owners",     # приглашать/снимать совладельцев, менять их права
    "manage_admins",     # приглашать/снимать админов
    "manage_masters",    # CRUD мастеров, услуг, графика мастера
    "manage_schedule",   # быстрые записи, отметка выполнено/неявка
    "manage_promotions",
    "manage_reviews",    # ответы на отзывы
    "view_finances",
    "manage_tariff",
    "view_audit_log",
    "manage_inventory",  # склад мастеров: приход, списания, инвентаризация
    "manage_payroll",    # ставки мастеров, ручные бонусы/штрафы
)

OWNER_DEFAULT_PERMISSIONS: Dict[str, bool] = {k: True for k in SALON_PERMISSION_KEYS}
# Управляющий: всё, что у владельца, кроме назначения совладельцев — это
# единственная привилегия, которая остаётся только у создателя салона.
MANAGER_DEFAULT_PERMISSIONS: Dict[str, bool] = {
    **OWNER_DEFAULT_PERMISSIONS,
    "manage_owners": False,
}
ADMIN_DEFAULT_PERMISSIONS: Dict[str, bool] = {
    **OWNER_DEFAULT_PERMISSIONS,
    "view_finances": False,
    "manage_tariff": False,
    "manage_owners": False,
    "view_audit_log": False,
    "manage_inventory": False,
    "manage_payroll": False,
}

# --- Core Tables ---

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone: Mapped[str] = mapped_column(String(15), unique=True, index=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Гость (создан гостевой записью без регистрации): пароль случайный,
    # войти нельзя; при регистрации этим номером аккаунт «забирается»
    # (is_guest=False + пароль). Не блокирует регистрацию.
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.CLIENT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Уровень доступа платформенного модератора (role=ADMIN). Базовый
    # модератор: только заявки на подключение салона + жалобы на фото.
    # Старший модератор (is_senior_admin=True): + пользователи, блокировка
    # салонов, отзывы, аудит-лог, назначение других модераторов. Не имеет
    # смысла для не-ADMIN ролей.
    is_senior_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    # Статус «модель» — дополнение к обычному клиентскому аккаунту (не смена
    # role), открывает доступ к ленте мастеров, ищущих моделей, и мэтчингу.
    is_model: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    model_photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    model_bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_looking_for: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Модерация анкеты модели (как у салона, см. SalonModerationStatus):
    # видна салонам в кандидатах только после APPROVED. Ставится PENDING при
    # первом включении is_model, повторные правки анкеты статус не сбрасывают.
    model_moderation_status: Mapped[ModelModerationStatus] = mapped_column(
        Enum(ModelModerationStatus), default=ModelModerationStatus.PENDING,
        server_default="PENDING", nullable=False,
    )
    model_rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Привязка Telegram для уведомлений (блок 18+): chat_id из бота.
    # BigInteger — телеграмовские id не влезают в int32. NULL = не привязан.
    tg_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    # Личные подписки на темы уведомлений {тема: bool}; NULL/нет ключа =
    # включено. Права салона решают «кто может», это — «кто хочет».
    # Управляется кнопками в боте (/start → «Мои уведомления»).
    tg_notify_prefs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    subscription_tier: Mapped[Optional[SubscriptionTier]] = mapped_column(Enum(SubscriptionTier), nullable=True)
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    master_profile: Mapped[Optional["Master"]] = relationship(back_populates="user", uselist=False)
    created_salons: Mapped[List["Salon"]] = relationship(back_populates="creator")
    salon_memberships: Mapped[List["SalonMember"]] = relationship(back_populates="user", foreign_keys="SalonMember.user_id")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="client", foreign_keys="Booking.client_id")
    reviews: Mapped[List["Review"]] = relationship(back_populates="client", foreign_keys="Review.client_id")
    favorites: Mapped[List["Favorite"]] = relationship(back_populates="user")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class SalonModerationStatus(str, enum.Enum):
    """Статус заявки салона (модерация регистрации бизнеса).

    pending  — заявка подана: салон можно настраивать, но публично НЕ виден и
               запись к нему закрыта, пока платформа не подтвердит договор;
    approved — договор подтверждён, салон работает;
    rejected — отклонён (причина в rejection_reason).
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SalonChain(Base):
    """Сеть салонов одного бренда: несколько независимых салонов (у каждого
    свой владелец/creator_id, сотрудники, брони, фото) показывают друг друга
    на публичной странице как «другой адрес этой же сети». Сама по себе
    ничего не даёт — только группировка + общее имя; формируется исключительно
    через обоюдное согласие ВСЕХ текущих владельцев объединяемых салонов, см.
    SalonChainRequest/SalonChainVote и app/services/salon_chain_service.py.
    """
    __tablename__ = "salon_chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salons: Mapped[List["Salon"]] = relationship(back_populates="chain")


class SalonChainRequestStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SalonChainRequest(Base):
    """Запрос на объединение сети между салоном-инициатором (from_salon) и
    выбранным целевым салоном (to_salon). Если у одного или обоих салонов уже
    есть сеть — запрос фактически объединяет ДВЕ сети целиком, а не только два
    салона: salon_ids фиксирует на момент создания полный список салонов
    обеих сторон, чьё согласие нужно для слияния (по одному голосу от
    создателя каждого салона — см. SalonChainVote)."""
    __tablename__ = "salon_chain_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initiator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    from_salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    to_salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    # Зафиксированный на момент создания запроса список ID салонов, чьё
    # согласие требуется (объединение всех участников обеих сетей). Не
    # пересчитывается позже — если состав сети успел измениться параллельным
    # запросом, голосование просто гасится (см. сервис).
    salon_ids: Mapped[List[int]] = mapped_column(JSON, nullable=False)
    status: Mapped[SalonChainRequestStatus] = mapped_column(
        Enum(SalonChainRequestStatus), default=SalonChainRequestStatus.PENDING,
        server_default="PENDING", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    votes: Mapped[List["SalonChainVote"]] = relationship(back_populates="request", cascade="all, delete-orphan")


class SalonChainVote(Base):
    """Один голос «за/против» слияния от создателя одного из затронутых
    салонов (по голосу на салон, не на человека — если один и тот же
    человек — создатель нескольких затронутых салонов, голосует за каждый
    отдельно). Любой отказ (approved=False) сразу отклоняет весь запрос."""
    __tablename__ = "salon_chain_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("salon_chain_requests.id", ondelete="CASCADE"))
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    voted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    voted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    request: Mapped["SalonChainRequest"] = relationship(back_populates="votes")

    __table_args__ = (
        UniqueConstraint("request_id", "salon_id", name="uq_chain_vote_request_salon"),
    )


class Salon(Base):
    __tablename__ = "salons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Пользователь, создавший карточку салона. Не источник правды для прав —
    # тот источник теперь SalonMember (role=owner, is_creator=True для этого же
    # user_id). creator_id остаётся как исторический/справочный указатель и не
    # уникален: один человек может быть создателем нескольких салонов.
    creator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    creator: Mapped["User"] = relationship(back_populates="created_salons")
    members: Mapped[List["SalonMember"]] = relationship(back_populates="salon", cascade="all, delete-orphan")
    
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    # Контактная почта салона (необязательная): реквизиты новых сотрудников +
    # копии уведомлений о записях/отменах. Не путать с почтой пользователя.
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Принимать записи без регистрации (гостевые по ссылке/QR). По умолчанию вкл.
    guest_booking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    photos: Mapped[List["SalonPhoto"]] = relationship(back_populates="salon")

    rating: Mapped[float] = mapped_column(Float, default=0.0)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)

    working_hours: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Зона продукта по умолчанию — Сибирь (запуск в Новосибирске); салоны в
    # других поясах задают свою явно
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Novosibirsk", server_default="Asia/Novosibirsk", nullable=False)

    masters: Mapped[List["Master"]] = relationship(back_populates="salon")
    promotions: Mapped[List["Promotion"]] = relationship(back_populates="salon")
    reviews: Mapped[List["Review"]] = relationship(back_populates="salon")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Владелец сам скрывает салон с платформы (обратимо, кнопка в настройках) —
    # отдельно от is_active (необратимое для владельца soft-delete). Салон и все
    # его данные остаются нетронутыми, просто не показывается в каталоге/поиске
    # и недоступен для новой записи, пока владелец не включит обратно.
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Сеть салонов (см. SalonChain) — NULL, если салон ни с кем не объединён.
    chain_id: Mapped[Optional[int]] = mapped_column(ForeignKey("salon_chains.id", ondelete="SET NULL"), nullable=True)
    chain: Mapped[Optional["SalonChain"]] = relationship(back_populates="salons")

    # Модерация регистрации бизнеса: новый салон = pending (виден только
    # владельцу для настройки), админ подтверждает договор → approved.
    # server_default=pending — страховка; существующие салоны миграция
    # переводит в approved, чтобы не отрезать текущих владельцев.
    moderation_status: Mapped[SalonModerationStatus] = mapped_column(
        Enum(SalonModerationStatus),
        default=SalonModerationStatus.PENDING,
        server_default="PENDING",  # SQLAlchemy хранит ИМЯ члена (конвенция проекта)
        nullable=False,
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Факт и время принятия оферты при подаче заявки.
    offer_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Публикация после модерации: одобрение админом (moderation_status=approved)
    # больше НЕ выбрасывает салон в каталог автоматически. Владелец сам жмёт
    # «Опубликовать» в шапке панели → проставляется published_at. NULL = прошёл
    # модерацию, но ещё ни разу не публиковался (полностью непубличен: нет в
    # ленте/поиске, карточка/запись/гостевая запись закрыты). Разовый шлюз —
    # назад не сбрасывается; дальнейшей видимостью рулит is_hidden.
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class SalonPhoto(Base):
    __tablename__ = "salon_photos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500))
    salon: Mapped["Salon"] = relationship(back_populates="photos")

class SalonMember(Base):
    """Членство пользователя в бизнес-панели салона (owner/admin) с гибкими правами."""
    __tablename__ = "salon_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    role: Mapped[SalonRole] = mapped_column(Enum(SalonRole), nullable=False)
    is_creator: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    permissions: Mapped[Dict[str, bool]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Личный тумблер: получать ли Telegram-пуш о заявках склада (расходник
    # заканчивается / техника сломалась). По умолчанию включено, каждый
    # владелец/админ переключает только за себя — не общая настройка салона.
    notify_warehouse_requests: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    invited_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salon: Mapped["Salon"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="salon_memberships", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("salon_id", "user_id", name="uq_salon_member"),
        Index("ix_salon_members_user", "user_id"),
        Index(
            "uq_salon_creator", "salon_id", unique=True,
            postgresql_where=text("is_creator = true"),
        ),
    )

class Master(Base):
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id"))

    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rating: Mapped[float] = mapped_column(Float, default=0.0)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    break_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15", nullable=False)

    # Мастер ищет модель для отработки навыка/пополнения портфолио — карточка
    # попадает в городскую ленту свайпов (app/services/model_matching_service.py).
    seeking_models: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    seeking_models_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="master_profile")
    salon: Mapped["Salon"] = relationship(back_populates="masters")
    services: Mapped[List["Service"]] = relationship(back_populates="master")
    schedule: Mapped[List["Schedule"]] = relationship(back_populates="master")
    reviews: Mapped[List["Review"]] = relationship(back_populates="master")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Мягкое удаление: удалённая услуга скрыта из выбора/записи, но брони с ней
    # (история) остаются валидными — Booking.service_id не рвётся.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Спецуслуга для отработки на моделях (своя цена/длительность) — не
    # показывается обычным клиентам, доступна только через мэтчинг моделей.
    is_model_practice: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Квота моделей на эту услугу: сколько BOOKED-мэтчей нужно набрать, прежде
    # чем услуга перестанет предлагаться новым моделям. NULL — квота не задана,
    # тогда открытость управляется только model_seeking_open вручную.
    model_quota: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Ручной рубильник «ищем/не ищем моделей на эту услугу» — салон может
    # закрыть в любой момент независимо от квоты («пока сам не закрою»).
    model_seeking_open: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Желаемая дата отработки (форма «Опубликовать поиск») — чисто информационная,
    # слоты для брони по-прежнему выбираются отдельно в оффере конкретному мэтчу.
    model_desired_date: Mapped[Optional[date_]] = mapped_column(Date, nullable=True)

    master: Mapped["Master"] = relationship(back_populates="services")

class Schedule(Base):
    __tablename__ = "schedule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    day_of_week: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column()
    end_time: Mapped[time] = mapped_column()

    master: Mapped["Master"] = relationship(back_populates="schedule")

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.PENDING)
    # Скидка лояльности салона, применённая админом при завершении записи
    # (0, если не применялась). Считается и пишется в complete_booking —
    # см. app/services/loyalty_service.py.
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    final_price: Mapped[int] = mapped_column(Integer, nullable=True)
    # Гостевая запись (без регистрации): токен управления/отмены по ссылке и
    # опциональный email для уведомлений. У обычных броней — NULL.
    guest_manage_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    guest_email: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Что именно применили: "regular_client" / "personal" / текст промокода / NULL.
    loyalty_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bonus_points_redeemed: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Мастер отчитался о фактически потраченных расходниках по этому визиту
    # (форма склада после клиента). Флаг для напоминаний мастеру/админу —
    # сам факт списания хранится в InventoryMovement(booking_id=...).
    consumption_reported: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Мастер явно отметил, что видел плановую запись в своём расписании
    # (кнопка «Видел», не влияет на status). NULL — ещё не отмечал; чисто
    # информационный флаг для владельца/админа салона.
    master_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped["User"] = relationship(back_populates="bookings", foreign_keys=[client_id])
    master: Mapped["Master"] = relationship()
    service: Mapped["Service"] = relationship()

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_bookings_master_start', 'master_id', 'start_time'),
    )

class Promotion(Base):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id"))
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    tag: Mapped[str] = mapped_column(String(30), nullable=False)

    salon: Mapped["Salon"] = relationship(back_populates="promotions")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id"))

    # Цель отзыва: конкретный мастер / салон в целом / сотрудник (не мастер).
    # master_id/staff_user_id заполняется в зависимости от target_type — оба
    # nullable, ровно один из них задан при target_type=master/staff.
    target_type: Mapped[ReviewTargetType] = mapped_column(
        Enum(ReviewTargetType), default=ReviewTargetType.MASTER, server_default="MASTER", nullable=False
    )
    # nullable: если мастер уходит из салона (Master.is_active=False),
    # привязка снимается (см. toggle_master_web) — отзыв остаётся в общем
    # списке салона, но перестаёт быть отзывом «про конкретного мастера».
    master_id: Mapped[Optional[int]] = mapped_column(ForeignKey("masters.id", ondelete="SET NULL"), nullable=True)
    # Цель отзыва при target_type=staff — user_id участника SalonMember
    # (владелец/админ), не мастера.
    staff_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Подтверждение реальным визитом: заполняется автоматически при создании
    # отзыва по факту COMPLETED-записи этого клиента (см. ReviewService) —
    # никогда не принимается со стороны клиента как есть. booking_id хранит
    # конкретную запись-доказательство (для аудита), is_verified — сам факт,
    # переживает удаление записи (ondelete=SET NULL не трогает is_verified).
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)

    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    client: Mapped["User"] = relationship(back_populates="reviews", foreign_keys=[client_id])
    master: Mapped[Optional["Master"]] = relationship(back_populates="reviews")
    salon: Mapped["Salon"] = relationship(back_populates="reviews")
    staff_user: Mapped[Optional["User"]] = relationship(foreign_keys=[staff_user_id])
    booking: Mapped[Optional["Booking"]] = relationship()
    photos: Mapped[List["ReviewPhoto"]] = relationship(back_populates="review", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint('rating >= 1 AND rating <= 5', name='check_rating_range'),
        Index("ix_reviews_master", "master_id"),
        Index("ix_reviews_salon", "salon_id"),
    )

class ReviewPhoto(Base):
    """Фото, приложенное клиентом к отзыву — доказательство результата работы."""
    __tablename__ = "review_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    review: Mapped["Review"] = relationship(back_populates="photos")

class MasterPhoto(Base):
    """Фото портфолио, которое мастер выкладывает сам (не из отзывов)."""
    __tablename__ = "master_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelPhoto(Base):
    """Галерея фото модели (помимо обложки User.model_photo_url)."""
    __tablename__ = "model_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PhotoReport(Base):
    """Жалоба на фото (из портфолио мастера или из отзыва) — модерация."""
    __tablename__ = "photo_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # SET NULL, не CASCADE: при разрешении жалобы (resolve) фото удаляется —
    # если бы тут был CASCADE, тот же delete() стёр бы саму запись жалобы
    # вместе с фото, уничтожив историю модерации в момент её создания.
    master_photo_id: Mapped[Optional[int]] = mapped_column(ForeignKey("master_photos.id", ondelete="SET NULL"), nullable=True)
    review_photo_id: Mapped[Optional[int]] = mapped_column(ForeignKey("review_photos.id", ondelete="SET NULL"), nullable=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[PhotoReportStatus] = mapped_column(
        Enum(PhotoReportStatus), default=PhotoReportStatus.PENDING, server_default="PENDING", nullable=False
    )
    resolved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    master_photo: Mapped[Optional["MasterPhoto"]] = relationship()
    review_photo: Mapped[Optional["ReviewPhoto"]] = relationship()
    reporter: Mapped["User"] = relationship(foreign_keys=[reporter_id])
    resolved_by: Mapped[Optional["User"]] = relationship(foreign_keys=[resolved_by_id])

    __table_args__ = (
        # На создании (см. create_photo_report) — ровно одна цель. После
        # resolve обе могут стать NULL (SET NULL при удалении фото) — поэтому
        # <= 1, а не строго = 1, иначе разрешённая жалоба не смогла бы
        # физически существовать в БД.
        CheckConstraint(
            "(master_photo_id IS NOT NULL)::int + (review_photo_id IS NOT NULL)::int <= 1",
            name="check_photo_report_at_most_one_target",
        ),
        Index("ix_photo_reports_status", "status"),
    )

# ========== НОВАЯ МОДЕЛЬ: Избранное ==========
class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    salon_id: Mapped[Optional[int]] = mapped_column(ForeignKey("salons.id"), nullable=True)
    master_id: Mapped[Optional[int]] = mapped_column(ForeignKey("masters.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="favorites")
    salon: Mapped[Optional["Salon"]] = relationship()
    master: Mapped[Optional["Master"]] = relationship()

    __table_args__ = (
        # Один салон/мастер — один раз в избранном пользователя. Частичные
        # уникальные индексы (salon_id/master_id взаимоисключающе NULL);
        # страховка от гонки двух параллельных toggle-запросов.
        Index(
            "uq_favorite_user_salon", "user_id", "salon_id", unique=True,
            postgresql_where=text("salon_id IS NOT NULL"),
        ),
        Index(
            "uq_favorite_user_master", "user_id", "master_id", unique=True,
            postgresql_where=text("master_id IS NOT NULL"),
        ),
    )

# ========== Аудит действий администратора ==========
class AdminAudit(Base):
    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))   # кто совершил действие
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # change_role, toggle_active, delete_user, …
    target_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # user / salon / review
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # человекочитаемое описание
    # NULL = платформенное действие (суперадмин). Заполнено — действие внутри
    # конкретного салона (приглашение/снятие сотрудника, удаление салона и т.п.).
    # ondelete=SET NULL: при удалении салона лог остаётся, просто теряет привязку.
    salon_id: Mapped[Optional[int]] = mapped_column(ForeignKey("salons.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped["User"] = relationship()

    __table_args__ = (
        Index("ix_admin_audit_created", "created_at"),
        Index("ix_admin_audit_salon", "salon_id"),
    )

# ========== Склад расходников (мини-склад на каждого мастера) ==========
class InventoryItem(Base):
    """Позиция номенклатуры на мини-складе конкретного мастера."""
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)  # мл / г / шт / уп
    # Текущий остаток — денормализованная сумма всех InventoryMovement.delta
    # по этой позиции; движения остаются источником истины и историей.
    quantity: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    cost_per_unit: Mapped[int] = mapped_column(Integer, nullable=False)  # для себестоимости
    min_quantity: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    master: Mapped["Master"] = relationship()

class InventoryMovement(Base):
    """Журнал движений по складу — единый источник истины для остатка и COGS."""
    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"))
    type: Mapped[InventoryMovementType] = mapped_column(Enum(InventoryMovementType), nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False)  # знак = направление движения
    # Цена за единицу на момент движения — чтобы себестоимость прошлых
    # периодов не «плыла» при изменении текущей цены позиции.
    unit_cost_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped["InventoryItem"] = relationship()
    booking: Mapped[Optional["Booking"]] = relationship()
    created_by: Mapped["User"] = relationship()

    __table_args__ = (
        Index("ix_inventory_movements_item", "item_id"),
        Index("ix_inventory_movements_booking", "booking_id"),
    )

class InventoryAudit(Base):
    """Акт инвентаризации мини-склада мастера."""
    __tablename__ = "inventory_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    status: Mapped[InventoryAuditStatus] = mapped_column(
        Enum(InventoryAuditStatus), default=InventoryAuditStatus.DRAFT, nullable=False
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    master: Mapped["Master"] = relationship()
    created_by: Mapped["User"] = relationship()
    items: Mapped[List["InventoryAuditItem"]] = relationship(back_populates="audit", cascade="all, delete-orphan")

class InventoryAuditItem(Base):
    """Строка акта: системный остаток на старте пересчёта vs фактический."""
    __tablename__ = "inventory_audit_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("inventory_audits.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"))
    expected_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    actual_quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    audit: Mapped["InventoryAudit"] = relationship(back_populates="items")
    item: Mapped["InventoryItem"] = relationship()

# ========== Техника и инструменты (общий склад салона) ==========
class Equipment(Base):
    """Единица техники/инструментов салона (кресла, фены и т.п.) — общий
    склад на весь салон, не привязан к конкретному мастеру (в отличие от
    расходников в InventoryItem)."""
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    status: Mapped[EquipmentStatus] = mapped_column(
        Enum(EquipmentStatus), default=EquipmentStatus.WORKING, server_default="WORKING", nullable=False
    )
    purchased_at: Mapped[Optional[date_]] = mapped_column(Date, nullable=True)
    service_life_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_per_unit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salon: Mapped["Salon"] = relationship()

# ========== Заявки склада: расходник заканчивается / техника сломалась ==========
class WarehouseRequest(Base):
    """Единая «заявка» мастера администратору салона — по расходнику
    (заканчивается, без точного остатка) или по технике (сломалась,
    нужна замена). Обе ветки решает один и тот же админ-воркфлоу."""
    __tablename__ = "warehouse_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    type: Mapped[WarehouseRequestType] = mapped_column(Enum(WarehouseRequestType), nullable=False)
    # SET NULL, не CASCADE — та же логика, что у PhotoReport: разрешённая
    # заявка должна пережить исчезновение позиции, иначе теряется история.
    item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True)
    equipment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[WarehouseRequestStatus] = mapped_column(
        Enum(WarehouseRequestStatus), default=WarehouseRequestStatus.PENDING, server_default="PENDING", nullable=False
    )
    resolved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salon: Mapped["Salon"] = relationship()
    item: Mapped[Optional["InventoryItem"]] = relationship()
    equipment: Mapped[Optional["Equipment"]] = relationship()
    created_by: Mapped["User"] = relationship(foreign_keys=[created_by_id])
    resolved_by: Mapped[Optional["User"]] = relationship(foreign_keys=[resolved_by_id])

    __table_args__ = (
        CheckConstraint(
            "(item_id IS NOT NULL)::int + (equipment_id IS NOT NULL)::int <= 1",
            name="check_warehouse_request_at_most_one_target",
        ),
        Index("ix_warehouse_requests_salon_status", "salon_id", "status"),
    )

# ========== Зарплаты: ставка мастера + ручные бонусы/штрафы ==========
class MasterPayrollSettings(Base):
    """Ставка мастера: оклад за период + % от выручки. 1–1 с Master."""
    __tablename__ = "master_payroll_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), unique=True)
    base_salary: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    commission_percent: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    master: Mapped["Master"] = relationship()

class PayrollAdjustment(Base):
    """Ручное начисление админом: бонус (amount > 0) или штраф (amount < 0)."""
    __tablename__ = "payroll_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    period_month: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)  # 1-е число месяца
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    master: Mapped["Master"] = relationship()
    created_by: Mapped["User"] = relationship()

    __table_args__ = (
        Index("ix_payroll_adjustments_master_period", "master_id", "period_month"),
    )

# ========== Promo-модели салона (роль UserRole.MODEL, отдельно от мастеров) ==========
class SalonModel(Base):
    """Привязка пользователя с ролью MODEL к салону (кастинг/сотрудничество для контента)."""
    __tablename__ = "salon_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stage_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salon: Mapped["Salon"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint("salon_id", "user_id", name="uq_salon_model"),
    )

# ========== Заметки на карточке клиента ==========
class ClientNote(Base):
    """Заметка владельца/админа салона на карточке клиента."""
    __tablename__ = "client_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salon: Mapped["Salon"] = relationship()
    client: Mapped["User"] = relationship(foreign_keys=[client_id])
    author: Mapped["User"] = relationship(foreign_keys=[author_id])

    __table_args__ = (
        Index("ix_client_notes_salon_client", "salon_id", "client_id"),
    )

# ========== Лояльность салона: статус, персональные скидки, бонусы ==========
class SalonLoyaltySettings(Base):
    """Настройки программы лояльности салона (1–1 с Salon)."""
    __tablename__ = "salon_loyalty_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"), unique=True)
    regular_client_discount_percent: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Автоприсвоение статуса «постоянный клиент» после N визитов за 12 мес.
    # NULL = только вручную админом.
    regular_client_visits_threshold: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # % от final_price, автоматически зачисляемый баллами после оплаты. 0 = выключено.
    bonus_accrual_percent: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    salon: Mapped["Salon"] = relationship()

class LoyaltyOffer(Base):
    """Именная скидка/промокод, который салон создаёт сам («позиция»)."""
    __tablename__ = "loyalty_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    promo_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salon: Mapped["Salon"] = relationship()

    __table_args__ = (
        UniqueConstraint("salon_id", "promo_code", name="uq_loyalty_offer_promo_code"),
    )

class ClientLoyalty(Base):
    """Состояние лояльности клиента в конкретном салоне."""
    __tablename__ = "client_loyalty"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_regular_client: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    regular_client_source: Mapped[Optional[LoyaltyStatusSource]] = mapped_column(Enum(LoyaltyStatusSource), nullable=True)
    # Персональная скидка этому конкретному клиенту, отдельно от статуса «постоянный клиент».
    personal_discount_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bonus_points: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    salon: Mapped["Salon"] = relationship()
    client: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint("salon_id", "client_id", name="uq_client_loyalty"),
    )

class LoyaltyPointsMovement(Base):
    """Журнал изменений бонусного баланса клиента (начисление/списание)."""
    __tablename__ = "loyalty_points_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_loyalty_id: Mapped[int] = mapped_column(ForeignKey("client_loyalty.id", ondelete="CASCADE"))
    type: Mapped[LoyaltyPointsMovementType] = mapped_column(Enum(LoyaltyPointsMovementType), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # знак = направление
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    client_loyalty: Mapped["ClientLoyalty"] = relationship()
    booking: Mapped[Optional["Booking"]] = relationship()
    created_by: Mapped["User"] = relationship()

    __table_args__ = (
        Index("ix_loyalty_points_movements_client_loyalty", "client_loyalty_id"),
    )

# ========== Закрытые даты (весь салон или конкретный мастер) ==========
class ScheduleClosure(Base):
    """Дата, закрытая для записи — на весь салон (master_id=NULL) либо на
    одного мастера (отпуск/больничный). Отдельно от Salon.working_hours,
    который описывает только повторяющийся по дням недели график."""
    __tablename__ = "schedule_closures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))
    master_id: Mapped[Optional[int]] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"), nullable=True)
    date: Mapped[date_] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    salon: Mapped["Salon"] = relationship()
    master: Mapped[Optional["Master"]] = relationship()
    created_by: Mapped["User"] = relationship()

    __table_args__ = (
        # Одно закрытие "всего салона" на дату
        Index(
            "uq_schedule_closure_salon", "salon_id", "date", unique=True,
            postgresql_where=text("master_id IS NULL"),
        ),
        # Одно закрытие конкретного мастера на дату
        Index(
            "uq_schedule_closure_master", "salon_id", "master_id", "date", unique=True,
            postgresql_where=text("master_id IS NOT NULL"),
        ),
    )


class ModelMatchStatus(str, enum.Enum):
    PENDING = "pending"     # свайпнула только одна сторона
    MATCHED = "matched"     # взаимный лайк — цена/услуга уже известны из Service, ждём выбор времени моделью
    BOOKED = "booked"       # модель выбрала слот — создана запись
    DECLINED = "declined"   # любая сторона отказалась


class ModelMatch(Base):
    """Мэтчинг «модель ↔ конкретный опубликованный поиск (Service с
    is_model_practice=True)» — одна строка на пару (модель, услуга),
    совмещает и факт свайпа с каждой стороны, и состояние последующей
    брони. Цена/длительность/мастер берутся из Service — оффера как
    отдельного шага нет: мэтч сразу даёт право выбрать реальный свободный
    слот в расписании мастера (см. accept-slot)."""
    __tablename__ = "model_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))  # денормализовано из service.master_id
    salon_id: Mapped[int] = mapped_column(ForeignKey("salons.id", ondelete="CASCADE"))  # денормализовано для выборок со стороны салона

    model_liked: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    model_liked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    salon_liked: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    salon_liked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    salon_liked_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    status: Mapped[ModelMatchStatus] = mapped_column(
        Enum(ModelMatchStatus), default=ModelMatchStatus.PENDING,
        server_default="PENDING", nullable=False,
    )
    matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    chosen_slot: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)

    declined_by: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "model" | "salon"
    declined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    model_user: Mapped["User"] = relationship(foreign_keys=[model_user_id])
    service: Mapped["Service"] = relationship()
    master: Mapped["Master"] = relationship()
    salon: Mapped["Salon"] = relationship()

    __table_args__ = (
        UniqueConstraint("model_user_id", "service_id", name="uq_model_match_pair"),
        Index("ix_model_matches_model_status", "model_user_id", "status"),
        Index("ix_model_matches_salon_status", "salon_id", "status"),
    )