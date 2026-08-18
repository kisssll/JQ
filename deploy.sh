#!/usr/bin/env bash
# deploy.sh — деплой одного стека: ./deploy.sh staging|prod
#
# Что делает: git pull → тег текущего образа как *-prev (для отката) →
# build → миграции alembic → up -d → ожидание /health → edge-Caddy up.
# Staging обновляется автоматически GitHub Actions'ом по пушу в main
# (.github/workflows/deploy-staging.yml); прод — только руками этим скриптом.
#
# Откат при неудаче:
#   docker tag rumi-app:<env>-prev rumi-app:<env> && ./deploy.sh <env> --no-pull --no-build
set -euo pipefail
cd "$(dirname "$0")"

ENV_NAME="${1:?Использование: ./deploy.sh staging|prod [--no-pull] [--no-build]}"
shift || true
NO_PULL=0; NO_BUILD=0
for arg in "$@"; do
    case "$arg" in
        --no-pull)  NO_PULL=1 ;;
        --no-build) NO_BUILD=1 ;;
        *) echo "Неизвестный флаг: $arg" >&2; exit 1 ;;
    esac
done

case "${ENV_NAME}" in
    prod)
        COMPOSE=(docker compose -p rumi-prod -f docker-compose.prod.yml)
        PROJECT="rumi-prod"
        APP_CONTAINER="rumi-prod-app"
        IMAGE="rumi-app:prod"
        BRANCH="main"
        ;;
    staging)
        COMPOSE=(docker compose -p rumi-staging -f docker-compose.staging.yml --env-file .env.staging)
        PROJECT="rumi-staging"
        APP_CONTAINER="rumi-staging-app"
        IMAGE="rumi-app:staging"
        BRANCH="staging"
        ;;
    *)
        echo "Использование: ./deploy.sh staging|prod" >&2; exit 1 ;;
esac

# Каждое окружение жёстко привязано к своей ветке (staging → staging,
# prod → main): общий чекаут больше не нужно переключать руками, и деплой
# не зависит от того, на какой ветке сервер оставили в прошлый раз.
echo "[deploy:${ENV_NAME}] обновление кода (ветка ${BRANCH})..."
if [ "${NO_PULL}" -eq 0 ]; then
    git fetch origin
    git checkout "${BRANCH}"
    git pull --ff-only
fi

# Внешняя сеть edge нужна стекам и Caddy (создаётся один раз)
docker network inspect edge >/dev/null 2>&1 || docker network create edge

# Текущий образ — в *-prev, чтобы был путь назад
if docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    docker tag "${IMAGE}" "${IMAGE}-prev"
fi

if [ "${NO_BUILD}" -eq 0 ]; then
    echo "[deploy:${ENV_NAME}] сборка образа..."
    "${COMPOSE[@]}" build app
fi

echo "[deploy:${ENV_NAME}] миграции..."
# На staging БД-контейнер должен подняться до миграций
if [ "${ENV_NAME}" = "staging" ]; then
    "${COMPOSE[@]}" up -d db redis
fi
# Первый запуск на живой БД, созданной через create_all: см. RUNBOOK.md
# (разово `alembic stamp head` вместо upgrade)
"${COMPOSE[@]}" run --rm app alembic upgrade head

# Если предыдущий деплой оборвался, compose оставляет переименованные
# контейнеры вида <хеш>_rumi-staging-arq в статусе created — они занимают имя
# и следующий up -d падает с «container name is already in use». Это не
# «осиротевшие» в смысле --remove-orphans (они принадлежат сервисам проекта),
# поэтому чистим сами. Статус created = ни разу не запускался, живое не трогаем.
STALE=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" \
                     --filter "status=created" --format '{{.ID}}')
if [ -n "${STALE}" ]; then
    echo "[deploy:${ENV_NAME}] убираю недозапущенные контейнеры прошлого деплоя..."
    # shellcheck disable=SC2086
    docker rm -f ${STALE}
fi

echo "[deploy:${ENV_NAME}] запуск стека..."
"${COMPOSE[@]}" up -d --remove-orphans

echo "[deploy:${ENV_NAME}] ожидание /health (до 60с)..."
for i in $(seq 1 30); do
    if docker exec "${APP_CONTAINER}" python -c \
        "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)" \
        2>/dev/null; then
        HEALTHY=1; break
    fi
    HEALTHY=0; sleep 2
done
if [ "${HEALTHY}" -ne 1 ]; then
    echo "[deploy:${ENV_NAME}] ПРОВАЛ health-check. Логи:" >&2
    docker logs "${APP_CONTAINER}" 2>&1 | tail -30 >&2
    echo "Откат: docker tag ${IMAGE}-prev ${IMAGE} && ./deploy.sh ${ENV_NAME} --no-pull --no-build" >&2
    exit 1
fi

echo "[deploy:${ENV_NAME}] edge-Caddy..."
docker compose -p rumi-edge -f docker-compose.edge.yml up -d

echo "[deploy:${ENV_NAME}] готово:"
"${COMPOSE[@]}" ps
