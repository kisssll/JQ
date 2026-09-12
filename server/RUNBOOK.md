# RUNBOOK — сервер Timeweb (prod + staging)

Схема: один сервер, три compose-проекта — `rumi-prod` (app+arq+redis, БД = managed PostgreSQL Timeweb), `rumi-staging` (то же + свой контейнер Postgres) и `rumi-edge` (один Caddy на 80/443, проксирует оба стека через внешнюю docker-сеть `edge`; staging закрыт basic_auth).

Адреса до появления домена: прод — `https://<IP сервера>` (самоподписанный сертификат), staging — `https://staging.201-24-60-247.sslip.io` (sslip.io = wildcard-DNS, имя публично резолвится в IP; выдуманные хосты типа `.test` не работают у провайдеров с DPI — режут TLS по SNI несуществующих имён). С реальным доменом staging переезжает на `staging.<домен>` (см. §3).

## 1. Первый запуск (один раз)

```bash
# --- под root ---
bash server/bootstrap.sh 'ssh-ed25519 AAAA... artem-rumi-deploy'
# НЕ закрывая сессию, из второго терминала проверить: ssh deploy@<host>

# --- дальше под deploy ---
cd /opt/rumi && git clone https://github.com/YatchenkoArD/be.git && cd be
```

### Секреты (блок 03 — старые скомпрометированы публичной git-историей!)
```bash
cp .env.example .env && cp .env.staging.example .env.staging
chmod 600 .env .env.staging
# в .env:  новый SECRET_KEY (openssl rand -hex 32), креды managed-БД из панели
#          Timeweb, DOMAIN (до домена — IP сервера), STAGING_BASIC_AUTH_HASH
#          (docker run --rm caddy:2-alpine caddy hash-password --plaintext '...';
#           в хеше КАЖДЫЙ $ удвоить до $$ — compose интерполирует $ в .env)
# в .env.staging:  свой SECRET_KEY и пароль БД (НЕ прод-значения)
# пароль managed-БД сменить в панели Timeweb (ротация)

# RS256-ключи: прод и staging — РАЗНЫЕ пары.
# ВАЖНО: контейнер работает под пользователем app (uid 999) — после генерации
# отдать ключи ему, иначе 500 при выпуске JWT (PermissionError):
#   docker run --rm -u 0 -v /opt/rumi/be/keys:/k rumi-app:prod sh -c 'chown -R 999 /k && chmod 600 /k/*.pem'
#   (то же для keys-staging с образом rumi-app:staging)
python3 -m venv /tmp/genkeys && /tmp/genkeys/bin/pip install cryptography
SECRET_KEY=x POSTGRES_PASSWORD=x /tmp/genkeys/bin/python -m app.scripts.gen_keys   # → ./keys (прод)
mkdir keys-staging && mv keys/jwt_*.pem keys-staging/ && \
SECRET_KEY=x POSTGRES_PASSWORD=x /tmp/genkeys/bin/python -m app.scripts.gen_keys   # → ./keys ещё раз
```

### Первые миграции (блок 04)
Живая БД создавалась через `Base.metadata.create_all` — Alembic в ней не инициализирован. Если разворачиваем **существующую** прод-БД, сначала проверьте, что схема содержит все поля текущей модели, и только затем один раз выполните:
```bash
docker compose -p rumi-prod -f docker-compose.prod.yml run --rm app alembic stamp head
```
Нельзя использовать `stamp head`, если в базе отсутствуют новые поля: эта команда только записывает номер ревизии и не меняет таблицы. Для базы, на которой уже был выполнен такой stamp до миграции диапазона цен, восстановите поле и повторите деплой:
```bash
docker compose -p rumi-prod -f docker-compose.prod.yml exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "ALTER TABLE services ADD COLUMN IF NOT EXISTS price_max INTEGER"'
```
После этого создание услуг с фиксированной ценой и диапазоном использует актуальную схему. Для **чистой** БД ничего не нужно — `deploy.sh` сам прогонит `alembic upgrade head`.

### Запуск
```bash
./deploy.sh staging     # свой Postgres поднимется сам; сиды по желанию:
# docker compose -p rumi-staging -f docker-compose.staging.yml --env-file .env.staging \
#     run --rm app python -m app.scripts.seed_data
./deploy.sh prod
```

### Бэкапы (блок 04)
```bash
crontab -e   # под deploy:
0 3 * * * cd /opt/rumi/be && ./backup_to_s3.sh >> /var/log/db_backup.log 2>&1
```
S3-переменные — в `.env` (панель Timeweb → S3 VK Cloud). **Проверить restore**: скачать дамп, развернуть в staging-Postgres, убедиться, что приложение живо, — бэкап без проверенного restore не считается.

### Автодеплой из GitHub (канонический репозиторий — KISLAARR/be)
Модель веток: **`staging` → staging** (deploy-staging.yml), **`main` → прод**
(deploy-prod.yml; можно запустить и руками из вкладки Actions). `deploy.sh`
сам чекаутит нужную ветку — общий чекаут на сервере руками не переключать.

Secrets (Settings → Secrets → Actions, нужна роль Admin): `DEPLOY_HOST`,
`DEPLOY_USER=deploy`, `DEPLOY_SSH_KEY` (ключ staging), `DEPLOY_PROD_SSH_KEY`
(ОТДЕЛЬНЫЙ ключ прода). Оба ключа на сервере ограничены форс-командами:
каждый умеет запустить только свой deploy.sh, ни shell, ни чужой стек.

**Обязательное условие для прод-автодеплоя**: branch protection на `main`
(и желательно `staging`) — изменения только через одобренный PR. Иначе
прод катит любой, у кого есть право пуша в репозиторий.

## 2. Обычная работа

| Действие | Команда |
| --- | --- |
| Деплой прод | пуш/merge в `main` (или Actions → deploy-prod → Run); руками: `./deploy.sh prod` |
| Деплой staging руками | `./deploy.sh staging` |
| Откат | `docker tag rumi-app:prod-prev rumi-app:prod && ./deploy.sh prod --no-pull --no-build` |
| Логи | `docker logs -f rumi-prod-app` (или `-staging-`, `rumi-edge-caddy`) |
| Статус | `docker compose -p rumi-prod -f docker-compose.prod.yml ps` |
| Здоровье воркера | `docker exec rumi-prod-arq arq --check app.core.worker.WorkerSettings` |

## 3. Когда появится домен

1. DNS: A-записи `домен` и `staging.домен` → IP сервера.
2. В `.env`: `DOMAIN=домен`, `STAGING_DOMAIN=staging.домен`, `PROD_TLS=<email>` и `STAGING_TLS=<email>` (включают Let's Encrypt; без них остаётся самоподписанный — на IP-адресах LE не работает вовсе).
3. `docker compose -p rumi-edge -f docker-compose.edge.yml up -d --force-recreate` — Caddy сам получит сертификаты Let's Encrypt.

## 4. Когда юристы подключат SMSC (OTP)

В `.env` и `.env.staging`: `OTP_ENABLED=true`, `SMS_MODE=live`, `SMSC_LOGIN/PASSWORD/SENDER_ID`, убрать `OTP_DISABLED_ACK`. Перезапустить стеки.

## 5. Блок 05 — мониторинг и логи

Приложение уже инструментировано: при заданном `SENTRY_DSN` шлёт ошибки в GlitchTip/Sentry, без него — no-op. Логи в проде/стейдже — JSON в stdout (`LOG_FORMAT=json` в compose), ротация docker-драйвером (10 МБ × 3). Телефоны в телеметрии/логах маскируются (152-ФЗ).

**5.1 Поднять GlitchTip (self-host).** Решить, тянет ли VPS ещё один стек (Django web+worker + свои postgres+redis) — на 4 ГБ рядом с prod+staging+edge может быть тесно; альтернатива — отдельный маленький VPS.
```bash
cp .env.glitchtip.example .env.glitchtip && chmod 600 .env.glitchtip
# заполнить GLITCHTIP_SECRET_KEY (openssl rand -hex 32), GLITCHTIP_DB_PASSWORD,
# GLITCHTIP_DOMAIN=https://glitchtip.rrumi.ru, EMAIL_URL (SMTP Beget для алертов)
docker compose -p rumi-glitchtip -f docker-compose.glitchtip.yml --env-file .env.glitchtip up -d
# первый вход в веб → создать пользователя-владельца, оставить open-registration=false
```

**5.2 Отдать наружу.** DNS: A-запись `glitchtip.rrumi.ru` → IP сервера. В `Caddyfile` добавить хост-блок (по образцу prod), reverse_proxy на `rumi-glitchtip-web:8000`, затем `up -d --force-recreate caddy` (edge).

**5.3 Подключить приложение.** В GlitchTip создать организацию/проект → скопировать **DSN**. Вписать в `.env` и `.env.staging`: `SENTRY_DSN=<dsn>` (по желанию `SENTRY_TRACES_SAMPLE_RATE=0.1`). Пересоздать `app`, `arq-worker` (+ боты) — при старте увидят DSN и начнут слать ошибки. Проверка: `docker exec rumi-staging-app python -c "import sentry_sdk; sentry_sdk.capture_message('test from staging')"` → событие в GlitchTip.

**5.4 Алерт на новые ошибки.** В GlitchTip: проект → Alerts → notification на email (`DEFAULT_FROM_EMAIL`) или webhook в Telegram.

**5.5 Внешний uptime-пинг.** Завести бесплатный монитор (UptimeRobot / healthchecks.io / Уптайм Робот) на `https://rrumi.ru/health` (ожидать `{"status":"ok"}`, интервал 1–5 мин) с оповещением на email/Telegram. Внешний — чтобы поймать и полное падение сервера (self-host мониторинг этого не увидит).
