# app/core/config.py
from pathlib import Path
from typing import List
from urllib.parse import quote

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта (…/be) — чтобы пути к ключам и .env не зависели от cwd
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    PROJECT_NAME: str = "Beauty Platform"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # Окружение: development | production. Влияет на флаги cookie, HSTS и т.п.
    ENVIRONMENT: str = "development"

    # Часовой пояс продукта по умолчанию: запуск — Сибирь (решение Артёма
    # 19.07.2026). Дефолт для зоны новых салонов и всех сравнений «который
    # час»; контейнеры приложения живут в этой же зоне (TZ в compose).
    # Хост и Postgres остаются в UTC — timestamptz-метки от этого не зависят.
    DEFAULT_TIMEZONE: str = "Asia/Novosibirsk"

    # --- Мониторинг и логи (блок 05) ---
    # Трекинг ошибок: GlitchTip (self-host, Sentry-совместим) или Sentry.
    # DSN пуст → SDK не инициализируется (no-op, поведение не меняется).
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0  # perf-трейсинг выключен по умолчанию
    # Формат логов: text (дефолт, читаемо в dev) | json (одна строка на событие).
    LOG_FORMAT: str = "text"
    LOG_LEVEL: str = "INFO"


    # --- Аутентификация (JWT RS256, асимметричная подпись) ---
    ALGORITHM: str = "RS256"
    # Пути к PEM-ключам. Приватным подписываем, публичным проверяем.
    # Генерация: python -m app.scripts.gen_keys  (см. README)
    JWT_PRIVATE_KEY_PATH: str = str(BASE_DIR / "keys" / "jwt_private.pem")
    JWT_PUBLIC_KEY_PATH: str = str(BASE_DIR / "keys" / "jwt_public.pem")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # короткий access-токен (был 24ч)

    # Секрет для подписи CSRF-токенов и прочих HMAC. ОБЯЗАТЕЛЕН из окружения.
    SECRET_KEY: str

    # --- Cookie ---
    # В проде обязательно True (cookie только по HTTPS).
    COOKIE_SECURE: bool = False

    # --- CORS ---
    # Явный список разрешённых origin'ов (FastAPI не закрывает это по умолчанию).
    CORS_ORIGINS: List[str] = ["http://localhost:8000"]

    # --- Redis (rate limiting, блокировка по аккаунту) ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- База данных ---
    POSTGRES_USER: str = "beauty_user"
    POSTGRES_PASSWORD: str  # ОБЯЗАТЕЛЕН из окружения, без дефолта в коде

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "beauty_platform"

    # SQL-эхо в логи. В проде ДОЛЖНО быть False (иначе параметры запросов утекают).
    SQL_ECHO: bool = False

    # --- OTP (подтверждение телефона при регистрации) ---
    # Код и его состояние живут только в Redis (TTL) — своей БД не нужно.
    OTP_METHOD: str = "flash_call"  # flash_call (дешевле) или sms
    OTP_LENGTH: int = 4
    OTP_TTL_MINUTES: int = 5
    MAX_VERIFY_ATTEMPTS: int = 3

    # Провайдер отправки: mock (код никуда не уходит, виден в dev_code ответа
    # и в логах) или live (SMSC.ru, резерв SMS.ru — см. app/services/sms_provider.py).
    SMS_MODE: str = "mock"
    SMSC_LOGIN: str = ""
    SMSC_PASSWORD: str = ""
    SMSC_SENDER_ID: str = ""
    SMSRU_API_ID: str = ""

    # --- Подтверждение телефона через Telegram-бота (блок 18) ---
    # Бесплатная альтернатива СМС: бот просит «Поделиться контактом», номер
    # отдаёт сам Telegram (он его верифицировал при регистрации аккаунта).
    # Токен бота — секрет, только из окружения. Username — без @, нужен для
    # deep link вида https://t.me/<username>?start=<request_id>.
    TG_VERIFY_ENABLED: bool = False
    TG_BOT_TOKEN: str = ""
    TG_BOT_USERNAME: str = ""

    # --- Подтверждение через MAX-бота (блок 18, этап 2) ---
    # Механика зеркальна Telegram: кнопка request_contact, номер отдаёт
    # платформа. Токен — из кабинета dev.max.ru, username — без @.
    MAX_VERIFY_ENABLED: bool = False
    MAX_BOT_TOKEN: str = ""
    MAX_BOT_USERNAME: str = ""
    # Уведомления о записях в Telegram (клиенту/мастеру/бизнесу через того же
    # бота + ARQ). Требует TG_BOT_TOKEN; получают только привязавшие Telegram.
    TG_NOTIFY_ENABLED: bool = False

    # Каталог загруженных изображений (аватары, фото салонов). В docker —
    # volume, переживает деплой. ВРЕМЕННО локально: переезд на S3 Timeweb,
    # когда возьмут креды из панели (см. app/services/uploads.py).
    UPLOADS_DIR: str = "uploads"

    # --- Почта @rrumi.ru (SMTP Beget — домен куплен там, ящики бесплатные) ---
    # EMAIL_MODE=mock — письма в лог (dev/до кредов), live — реальная отправка.
    # Ящики созданы в панели Beget (домен куплен там).
    EMAIL_MODE: str = "mock"
    SMTP_HOST: str = "smtp.beget.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@rrumi.ru"
    EMAIL_FROM_NAME: str = "Руми"
    # Ящик для алертов платформенным админам (новые заявки/жалобы и т.п.).
    ADMIN_ALERT_EMAIL: str = "hello@rrumi.ru"

    # --- Вход через Яндекс (OAuth, стало возможно с доменом rrumi.ru) ---
    # Приложение регистрируется на oauth.yandex.ru (физлицо, без ООО).
    # Scope login:default_phone даёт ПРОВЕРЕННЫЙ Яндексом номер — вход
    # одновременно закрывает подтверждение телефона (третий канал после TG).
    YANDEX_OAUTH_ENABLED: bool = False
    YANDEX_CLIENT_ID: str = ""
    YANDEX_CLIENT_SECRET: str = ""

    # --- Яндекс Карты (подсказки адреса + геокодирование) ---
    # Один ключ типа «JavaScript API и HTTP Геокодер» из developer.tech.yandex.ru
    # закрывает и подсказки/карту на фронте, и серверный геокодер (бэкфилл
    # старых салонов). Пусто (дефолт, локальная разработка/тесты без ключа) —
    # виджет подсказок и карта не подключаются, поля адреса остаются обычным
    # текстом, координаты не обязательны (старое поведение, дефолтные
    # координаты) — иначе без ключа было бы невозможно создать салон локально
    # или прогнать тесты. Как только ключ задан, форма требует выбрать адрес
    # из подсказок и не даёт сохранить без точных координат (см. business.py).
    YANDEX_MAPS_API_KEY: str = ""

    # Временный рубильник: пока нет официального подключения SMS-провайдера,
    # OTP_ENABLED=false пропускает реальную отправку/проверку кода (otp.py
    # возвращает фиктивный request_id и считает любой код верным).
    OTP_ENABLED: bool = True

    # Выключенный OTP в production = регистрация без подтверждения телефона.
    # Чтобы рубильник не дожил до релиза незамеченным, в production такое
    # состояние надо подтверждать явно вторым флагом — иначе приложение
    # не стартует (та же логика, что принудительный COOKIE_SECURE).
    OTP_DISABLED_ACK: bool = False

    @model_validator(mode="after")
    def _otp_guard_in_prod(self) -> "Settings":
        # model_validator (не field_validator): должен срабатывать и на дефолтах
        if (
            self.ENVIRONMENT == "production"
            and not self.OTP_ENABLED
            and not self.OTP_DISABLED_ACK
        ):
            raise ValueError(
                "OTP_ENABLED=false в production: любой код подтверждения будет "
                "принят. Если это осознанно (SMS-провайдер ещё не подключён), "
                "задайте OTP_DISABLED_ACK=true; иначе включите OTP_ENABLED."
            )
        if (
            self.ENVIRONMENT == "production"
            and self.OTP_ENABLED
            and self.SMS_MODE == "mock"
            and not (self.TG_VERIFY_ENABLED or self.MAX_VERIFY_ENABLED)
        ):
            raise ValueError(
                "OTP включён в production, но нет ни одного живого канала "
                "подтверждения: SMS_MODE=mock (коды не уходят на телефон, "
                "а dev_code превращает проверку в бутафорию), Telegram и MAX "
                "выключены. Настройте SMS_MODE=live с кредами SMSC и/или "
                "TG_VERIFY_ENABLED/MAX_VERIFY_ENABLED=true, либо отключите "
                "OTP осознанно (OTP_ENABLED=false + OTP_DISABLED_ACK=true)."
            )
        if self.TG_VERIFY_ENABLED and not (self.TG_BOT_TOKEN and self.TG_BOT_USERNAME):
            raise ValueError(
                "TG_VERIFY_ENABLED=true, но не заданы TG_BOT_TOKEN/TG_BOT_USERNAME — "
                "кнопка на странице вела бы в никуда. Заполните оба или выключите флаг."
            )
        if self.MAX_VERIFY_ENABLED and not (self.MAX_BOT_TOKEN and self.MAX_BOT_USERNAME):
            raise ValueError(
                "MAX_VERIFY_ENABLED=true, но не заданы MAX_BOT_TOKEN/MAX_BOT_USERNAME — "
                "кнопка на странице вела бы в никуда. Заполните оба или выключите флаг."
            )
        return self

    @field_validator("COOKIE_SECURE")
    @classmethod
    def _force_secure_in_prod(cls, v: bool, info) -> bool:
        # Подстраховка: в production cookie всегда secure.
        if info.data.get("ENVIRONMENT") == "production":
            return True
        return v

    @property
    def DATABASE_URL(self) -> str:
        """Строка подключения для asyncpg."""
        # Логин/пароль экранируем: спецсимволы в пароле managed-БД (#, &, { …)
        # иначе ломают разбор URL — например, # обрезает строку как фрагмент.
        return (
            f"postgresql+asyncpg://{quote(self.POSTGRES_USER, safe='')}:{quote(self.POSTGRES_PASSWORD, safe='')}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()

