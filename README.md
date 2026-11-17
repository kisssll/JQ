# Beauty Platform API

## Установка и запуск

> Требуется **Python ≥ 3.10** (на 3.9 не устанавливаются security-фиксы starlette/fastapi).

1. Создание и активация виртуального окружения:
```bash
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
```

2. Установка зависимостей:
```bash
pip install -r requirements.txt
```

3. Секреты и ключи (НЕ коммитятся, см. .gitignore):
```bash
cp .env.example .env              # заполнить SECRET_KEY и POSTGRES_PASSWORD
python -m app.scripts.gen_keys    # сгенерировать пару RS256-ключей в keys/
```
Сгенерировать SECRET_KEY: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

4. Инфраструктура и запуск:
```bash
docker compose up -d db redis     # PostgreSQL + Redis
alembic upgrade head              # миграции
uvicorn app.main:app --reload
```

> SMS-подтверждение телефона (SMSC.ru/SMS.ru) пока официально не подключено —
> `OTP_ENABLED=false` в `.env.example` временно пропускает проверку кода при
> регистрации (в `production` это состояние нужно подтвердить явно, см.
> `OTP_DISABLED_ACK` там же). Код и его состояние живут в Redis (TTL) —
> `app/services/otp.py` + `app/services/sms_provider.py`, отдельного сервиса
> для этого не заводим. Когда провайдер будет настроен — `SMS_MODE=live`,
> `OTP_ENABLED=true`.

Dev-данные (`python -m app.scripts.seed_data`) создаются с паролем `Seedpass1`.

## Спортивный каталог (MVP)

После `alembic upgrade head` каталог спортивных залов, клубов и секций
доступен по `/sport/`: список поддерживает поиск и фильтр по городу, а
«Спарта Плюс» — одна из карточек каталога (`/sport/sparta`). Расписание и
заявки используют API:

- `GET /api/v1/sport/organizations`
- `GET /api/v1/sport/organizations/{slug}`
- `GET /api/v1/sport/organizations/{slug}/schedule`
- `POST /api/v1/sport/organizations/{slug}/bookings`

Миграция `a2f6d18b4c90` создаёт таблицы спортивного каталога и добавляет
начальные данные «Спарты Плюс». Перед публикацией проверьте актуальность
расписания и адресов залов. В этом этапе администрирование расписания,
абонементы и кабинет участника не подключены.

## Прод-деплой (Timeweb, один VPS, два стека)

На сервере живут **три compose-проекта**: `rumi-prod` (docker-compose.prod.yml:
app + arq-worker + redis; PostgreSQL — **управляемая БД Timeweb**), `rumi-staging`
(docker-compose.staging.yml: то же + свой контейнер Postgres, конфиг из
`.env.staging`) и `rumi-edge` (docker-compose.edge.yml: один Caddy на 80/443,
проксирует оба стека через внешнюю docker-сеть `edge`; staging закрыт basic_auth).
Подтверждение телефона (SMS/flash-call через SMSC.ru, резерв SMS.ru) — часть
самого приложения (Redis TTL), отдельного сервиса/БД под это не поднимаем.

**Полная инструкция первого запуска — [server/RUNBOOK.md](server/RUNBOOK.md)**
(первичная настройка хоста — `server/bootstrap.sh`: deploy-user, SSH-hardening,
ufw, fail2ban). Коротко:
```bash
sudo bash server/bootstrap.sh '<публичный ssh-ключ>'   # один раз, под root
cp .env.example .env && cp .env.staging.example .env.staging   # заполнить, chmod 600
python -m app.scripts.gen_keys                # прод-ключи; для staging — отдельная пара
./deploy.sh staging && ./deploy.sh prod       # build + миграции + up + health-check
```
Staging обновляется автоматически по пушу в main (`.github/workflows/deploy-staging.yml`,
нужны secrets `DEPLOY_HOST`/`DEPLOY_USER`/`DEPLOY_SSH_KEY`); прод — только руками
`./deploy.sh prod`. Откат: `docker tag rumi-app:prod-prev rumi-app:prod && ./deploy.sh prod --no-pull --no-build`.

### Бэкапы в S3 (доп. подстраховка)

Managed PostgreSQL Timeweb уже делает ежедневные бэкапы сам. `backup_to_s3.sh`
дублирует дампы обеих БД в S3 (VK Cloud, подключается в панели Timeweb) —
на случай проблем с самим Timeweb. Настройка:

```bash
chmod +x backup_to_s3.sh
crontab -e
# добавить строку (ежедневно в 03:00):
0 3 * * * cd /opt/beauty_platform && ./backup_to_s3.sh >> /var/log/db_backup.log 2>&1
```

Требует `postgresql-client` и `awscli` на хосте (`apt install postgresql-client awscli`)
и заполненные `S3_ENDPOINT`/`S3_BUCKET`/`S3_ACCESS_KEY`/`S3_SECRET_KEY` в `.env`.

## Безопасность

Что сделано по итогам аудита ИБ (см. конспект «Комментарии по ИБ»):

- **Секреты** — `SECRET_KEY`, креды БД и URL alembic вынесены в `.env`; ключи RS256 — в `keys/` (gitignore). Скомпрометированный публикацией ключ при деплое **обязательно ротировать**.
- **JWT** — RS256 (асимметрично) на `PyJWT` вместо `python-jose`; короткий access-токен (60 мин).
- **Пароли** — единый модуль `app/core/security.py`, Argon2id (passlib); старые bcrypt/pbkdf2 переподписываются при логине; сырой sha256 больше не принимается; политика сложности.
- **Доступ (A01)** — роль при регистрации назначает сервер (нет privilege escalation); отзыв только при завершённой записи (`ReviewService`); уникальный пароль создаваемому мастеру.
- **Rate limiting** — slowapi (Redis-backend) на login + блокировка по телефону; пример Nginx ниже.
- **CSRF / заголовки / CORS** — проверка Origin/Referer для cookie-мутаций, security-заголовки, явный CORS-список; cookie `Secure` в проде.
- **SCA** — `requirements.txt` обновлён, `pip-audit` чист. Драйвер БД — `asyncpg` (psycopg2 убран).

### Nginx — грубый лимит флуда по IP (уровень до приложения)
```nginx
limit_req_zone $binary_remote_addr zone=login_zone:10m rate=10r/s;

location ~ ^/api/v1/auth/(login|login-web)$ {
    limit_req zone=login_zone burst=5 nodelay;
    limit_req_status 429;
    proxy_pass http://app;
}
```

## DevSecOps-пайплайн (Shift Left)

Проверки безопасности встроены в два слоя — на каждый коммит и на каждый push.

### 1. pre-commit (локально, на `git commit`)
Не пускает незашифрованные секреты и явные ошибки в репозиторий.
```bash
pip install pre-commit
pre-commit install            # активировать git-хук
pre-commit run --all-files    # разовый прогон по всему репо
```
Хуки: Gitleaks (secret detection), detect-private-key, check-added-large-files,
check-merge-conflict, check-yaml/json. Конфиг — [.pre-commit-config.yaml](.pre-commit-config.yaml),
allowlist dev-плейсхолдеров — [.gitleaks.toml](.gitleaks.toml).

### 2. GitHub Actions (на push / PR в main)
Workflow [.github/workflows/devsecops.yml](.github/workflows/devsecops.yml), стратегия Defense in Depth:

| Этап | Инструмент | Что проверяет |
| :--- | :--- | :--- |
| **Secrets** | Gitleaks | утёкшие ключи/токены (по всей истории) — блокирующий |
| **SCA** | Trivy (fs) + pip-audit | известные CVE в зависимостях (`pip-audit` — gate) |
| **SAST** | Semgrep + Bandit | опасные паттерны в коде (инъекции, слабая крипта и т.д.) |
| **IaC** | Trivy config | мисконфиги в `docker-compose.yml` / Dockerfile |
| **Container** | Trivy image | CVE в собранном образе; gate по исправимым HIGH/CRITICAL (`--ignore-unfixed`) |
| **DAST** | OWASP ZAP baseline | живое приложение: CI поднимает стек (db+redis+app) и сканирует его |
| **ASPM** | DefectDojo | централизованный сбор и дедупликация находок |

Находки агрегируются в **DefectDojo** (как в `secure-ci-cd-pipeline`). Загрузка включается,
только если заданы GitHub Secrets — иначе шаги пропускаются, пайплайн не падает:
- `DEFECTDOJO_URL` — адрес инстанса (например, через ngrok);
- `DEFECTDOJO_TOKEN` — API-токен.

> Для DAST staging не требуется: джоба `dast-zap` собирает образ, поднимает стек
> (Postgres + Redis + приложение с сидовыми данными) прямо в CI и гоняет ZAP baseline
> по нему. Когда появится staging — добавим его вторым target'ом.

## API Endpoints 
- GET /api/v1/users/ - список пользователей 
- GET /api/v1/services/ - список услуг 
- GET /api/v1/appointments/ - список записей 
## надо будет сделать Конвертации времени сейчас у нас строка