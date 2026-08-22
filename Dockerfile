# ─────────────────────────────────────────────────────────────
# Stage 0 — frontend-builder: vite build → static/dist/ (main.js/main.css).
# static/dist/ в .gitignore и не лежит в репозитории — без этого стейджа
# get_base_styles() ссылается на несуществующие файлы (404 без стилей/JS).
# ─────────────────────────────────────────────────────────────
FROM node:22-alpine AS frontend-builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY vite.config.js ./
COPY static/src ./static/src
RUN npm run build

# ─────────────────────────────────────────────────────────────
# Stage 1 — builder: ставим зависимости в изолированный venv
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# build-essential нужен на случай сборки колёс (asyncpg/argon2-cffi/cryptography);
# на slim (glibc) чаще есть готовые wheels, но подстрахуемся.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    # Убираем build-тулинг из venv — в рантайме не нужен, а именно он тянет
    # HIGH-CVE (wheel, jaraco.context). Удаляем явно по имени (надёжнее find).
    && pip uninstall -y jaraco.context wheel setuptools pip \
    && rm -rf /opt/venv/lib/python*/site-packages/pkg_resources \
              /opt/venv/lib/python*/site-packages/_distutils_hack

# ─────────────────────────────────────────────────────────────
# Stage 2 — runtime: только venv + код, без компиляторов, non-root
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Пакеты ОС (util-linux и т.п.) в базовом слое python:3.11-slim фиксируются
# на момент публикации тега и со временем накапливают исправленные апстримом
# HIGH-CVE (Trivy-гейт в CI: ignore-unfixed=true — падаем именно на тех, для
# которых патч уже есть). apt upgrade подтягивает патчи Debian на момент
# сборки, не дожидаясь, пока Docker Hub перевыпустит сам тег.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# непривилегированный пользователь
RUN groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

# Базовый python:3.11-slim несёт СВОЙ pip/setuptools/wheel в /usr/local —
# в рантайме не нужны и тянут HIGH-CVE (wheel, jaraco.context). Вычищаем.
# Приложение работает из /opt/venv, поэтому это безопасно.
RUN rm -rf /usr/local/lib/python3.11/site-packages/setuptools* \
           /usr/local/lib/python3.11/site-packages/pip* \
           /usr/local/lib/python3.11/site-packages/wheel* \
           /usr/local/lib/python3.11/site-packages/pkg_resources \
           /usr/local/lib/python3.11/site-packages/_distutils_hack \
           /usr/local/lib/python3.11/site-packages/jaraco* \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11 /usr/local/bin/wheel

COPY --from=builder /opt/venv /opt/venv
COPY . .
COPY --from=frontend-builder /app/static/dist ./static/dist

# .env и keys/ НЕ копируются (см. .dockerignore) — секреты монтируются в рантайме
# /app/uploads создаётся заранее с владельцем app: docker инициализирует новый
# volume правами каталога из образа — иначе mountpoint был бы root:root и
# приложение (uid app) ловило PermissionError на первой загрузке фото
RUN mkdir -p /app/uploads && chown -R app:app /app
USER app

EXPOSE 8000

# Liveness: /health (починен — регистрируется до catch-all веб-роутера)
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# Прод-запуск: gunicorn с uvicorn-воркерами. Кол-во воркеров — через env WEB_CONCURRENCY.
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:8000 --access-logfile - --error-logfile -"]
