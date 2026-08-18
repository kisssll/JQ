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

# Если предыдущий деплой оборвался, compose оставляет переименованные
# контейнеры вида <хеш>_rumi-staging-arq в статусе created — они занимают имя
# и следующий up -d падает с «container name is already in use». Это не
# «осиротевшие» в смысле --remove-orphans (они принадлежат сервисам проекта),
# поэтому чистим сами.
# Ловим два признака: (1) статус created — контейнер создан и не запущен;
# (2) имя вида <12 hex>_<сервис> — так compose переименовывает старый
# контейнер перед пересозданием. Второй признак снимаем в любом состоянии,
# включая running: под таким именем compose ничего не оставляет намеренно, а
# «работающий переименованный» — как раз тот случай, когда каноническое имя
# свободно и следующий up -d падает с «No such container: rumi-staging-app».
STALE=$(
    {
        docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" \
                     --filter "status=created" --format '{{.ID}}'
        docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" \
                     --format '{{.ID}} {{.Names}}' \
            | awk '$2 ~ /^[0-9a-f]{12}_/ {print $1}'
    } | sort -u
)
if [ -n "${STALE}" ]; then
    echo "[deploy:${ENV_NAME}] убираю недозапущенные контейнеры прошлого деплоя..."
    # shellcheck disable=SC2086
    docker rm -f ${STALE} >/dev/null || true
    # rm -f возвращается раньше, чем демон закончил удаление, и следующий шаг
    # спотыкался об «removal of container is already in progress». Ждём.
    for _ in $(seq 1 20); do
        left=""
        for id in ${STALE}; do
            docker inspect "${id}" >/dev/null 2>&1 && left="${left} ${id}"
        done
        [ -z "${left}" ] && break
        sleep 0.5
    done
fi

echo "[deploy:${ENV_NAME}] миграции..."
# На staging БД-контейнер должен подняться до миграций
if [ "${ENV_NAME}" = "staging" ]; then
    "${COMPOSE[@]}" up -d db redis
fi
# Первый запуск на живой БД, созданной через create_all: см. RUNBOOK.md
# (разово `alembic stamp head` вместо upgrade)
"${COMPOSE[@]}" run --rm app alembic upgrade head

echo "[deploy:${ENV_NAME}] запуск стека..."
# Без --remove-orphans: он пересекался с чисткой выше на одном и том же
# контейнере и давал ту же ошибку про «removal already in progress».
#
# Пересоздание отдельного сервиса (чаще всего max-bot) периодически падает с
# «No such container» / «container name is already in use»: compose переименует
# старый контейнер, а дальше теряет его. Остаток вида <хеш>_<сервис> в статусе
# created появляется уже ВНУТРИ up -d, поэтому чистка выше его не застаёт. До
# сих пор это лечилось руками; делаем то же автоматически — снести остатки и
# повторить один раз. Если и вторая попытка падает, выходим с ошибкой.
if ! "${COMPOSE[@]}" up -d; then
    # Точечная чистка между попытками не помогает: она обнуляет кэш compose, и
    # повторный up -d ссылается на уже удалённый контейнер («No such container:
    # rumi-staging-app»). Поэтому в ветке восстановления опускаем стек целиком и
    # поднимаем с чистого листа — на пару секунд дольше, зато детерминированно.
    # Данные в томах, БД это не задевает.
    echo "[deploy:${ENV_NAME}] up -d не удался, поднимаю стек с чистого листа..." >&2
    "${COMPOSE[@]}" down --remove-orphans || true
    # down возвращается раньше, чем демон снял все контейнеры, и следующий up -d
    # падал на «container name /rumi-staging-redis is already in use». Ждём, пока
    # от проекта не останется ни одного контейнера, и добиваем упрямые вручную.
    for _ in $(seq 1 30); do
        REST=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" \
                            --format '{{.ID}}')
        [ -z "${REST}" ] && break
        sleep 1
    done
    REST=$(docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.ID}}')
    if [ -n "${REST}" ]; then
        # shellcheck disable=SC2086
        docker rm -f ${REST} >/dev/null 2>&1 || true
        sleep 2
    fi
    "${COMPOSE[@]}" up -d
fi

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
