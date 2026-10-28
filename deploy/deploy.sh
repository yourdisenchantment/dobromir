#!/usr/bin/env bash
# Обновление кода на сервере до тега релиза. Запускать руками из клона, не из cron:
#
#   ./deploy/deploy.sh v0.2.0            # код, зависимости, копия базы, миграции, пробная сборка
#   ./deploy/deploy.sh v0.2.0 --switch   # то же и переключить public_html на новый релиз
#   ./deploy/deploy.sh v0.2.0 --pip      # Python-зависимости через pip, если uv не работает
#   ./deploy/deploy.sh v0.2.0 --npm-ci   # переустановить node_modules, даже если lock не менялся
#
# Шаги: git fetch; переход на тег; Python-зависимости по uv.lock; копия базы; миграции;
# npm ci - только если изменился package-lock.json или нет node_modules; сборка релиза в
# releases/ с проверками. Без --switch public_html не трогается: включить собранный релиз -
# командой, которую скрипт напечатает в конце (python -m pipeline rollback --to <релиз>).
#
# Чего не делает: не удаляет файлы, не трогает .env и cron, не делает git pull по ветке.
# Если в клоне изменены отслеживаемые файлы - отказывается до любых действий.
#
# Не запускать около 17-й минуты часа: в это время cron запускает воркер. Если он идет,
# миграции и сборка откажутся - повторить через несколько минут.
#
# Переменные: PYTHON (по умолчанию /usr/bin/python3), NODE_BIN, DOBROMIR_DATA, REMOTE (origin)
set -euo pipefail

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

TAG=""
SWITCH=0
USE_PIP=0
FORCE_NPM=0
if [ "$#" -eq 0 ]; then
    usage
    exit 2
fi
for arg in "$@"; do
    case "$arg" in
        --switch) SWITCH=1 ;;
        --pip) USE_PIP=1 ;;
        --npm-ci) FORCE_NPM=1 ;;
        -h | --help)
            usage
            exit 0
            ;;
        -*)
            echo "неизвестный ключ: $arg (см. --help)" >&2
            exit 2
            ;;
        *)
            if [ -n "$TAG" ]; then
                echo "тег указан дважды: $TAG и $arg" >&2
                exit 2
            fi
            TAG="$arg"
            ;;
    esac
done
if [ -z "$TAG" ]; then
    echo "не указан тег (см. --help)" >&2
    exit 2
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-/usr/bin/python3}"
NODE_BIN="${NODE_BIN:-$HOME/opt/node/bin}"
DATA_DIR="${DOBROMIR_DATA:-$HOME/dobromir-data}"
REMOTE="${REMOTE:-origin}"
UV="$HOME/.local/share/dobromir-uv/bin/uv"
VENV_PY="$REPO/pipeline/.venv/bin/python"
export PATH="$NODE_BIN:/usr/local/bin:/usr/bin:/bin"
export ASTRO_TELEMETRY_DISABLED=1
# Сборка на сервере содержимое только проверяет, файлы клона не правит.
export CONTENT_CHECK_ONLY=1
export PYTHONIOENCODING=utf-8
export UV_PYTHON_DOWNLOADS=never # только системный Python, свой интерпретатор uv не качает

step() {
    echo
    echo "== $*"
}
die() {
    echo "ОШИБКА: $*" >&2
    exit 1
}

STAGE=""
OLD_NAME=""
OLD_COMMIT=""
finish() {
    local code=$?
    if [ "$code" -ne 0 ] && [ -n "$STAGE" ]; then
        {
            echo
            echo "Деплой прерван на шаге «$STAGE» (код $code). public_html не переключался."
            echo "Клон сейчас на $(git -C "$REPO" rev-parse --short HEAD) (цель $TAG), был $OLD_NAME."
            if [ "$(git -C "$REPO" rev-parse HEAD)" = "$OLD_COMMIT" ]; then
                echo "Версия кода не менялась."
            elif git -C "$REPO" rev-parse -q --verify "refs/tags/$OLD_NAME" >/dev/null; then
                echo "Вернуть прежнюю версию: ./deploy/deploy.sh $OLD_NAME"
            else
                echo "Вернуть прежнюю версию: git checkout --detach $OLD_COMMIT && ./deploy/bootstrap.sh --apply"
            fi
            echo "Копия базы до миграций (если была) - в $DATA_DIR/backup/."
        } >&2
    fi
}
trap finish EXIT

cd "$REPO"

step "Проверки"
git rev-parse --git-dir >/dev/null 2>&1 || die "$REPO - не клон git"
[ -z "$(git status --porcelain --untracked-files=no)" ] ||
    die "в клоне изменены отслеживаемые файлы (git status): деплой их затер бы"
if [ "$USE_PIP" -eq 0 ] && [ ! -x "$UV" ]; then
    die "нет uv ($UV): сначала ./deploy/bootstrap.sh --apply или ключ --pip"
fi
[ -x "$PYTHON" ] || die "нет $PYTHON (задайте PYTHON=путь)"
[ -x "$NODE_BIN/npm" ] || die "нет npm в $NODE_BIN (задайте NODE_BIN=путь)"
OLD_COMMIT="$(git rev-parse HEAD)"
OLD_NAME="$(git describe --tags --exact-match HEAD 2>/dev/null || git rev-parse --short HEAD)"
echo "  ok    клон чистый, сейчас на $OLD_NAME"

step "Код"
git fetch --tags "$REMOTE"
NEW_COMMIT="$(git rev-parse -q --verify "refs/tags/$TAG^{commit}")" ||
    die "нет тега $TAG (имеющиеся: git tag -l)"
STAGE="переход на тег"
git -c advice.detachedHead=false checkout -q --detach "$NEW_COMMIT"
echo "  ok    $OLD_NAME -> $TAG ($(git rev-parse --short HEAD))"

step "Python-зависимости"
STAGE="Python-зависимости"
if [ "$USE_PIP" -eq 1 ]; then
    [ -x "$VENV_PY" ] || "$PYTHON" -m venv "$REPO/pipeline/.venv"
    # requirements.txt начинается с -e ., поэтому из каталога pipeline/.
    (cd pipeline && .venv/bin/pip install -q -r requirements.txt)
    echo "  ok    pip install -r requirements.txt"
else
    (cd pipeline && "$UV" sync --frozen --no-dev --python "$PYTHON")
    echo "  ok    uv sync --frozen --no-dev"
fi
"$VENV_PY" -c 'import pipeline.settings, PIL.features; assert PIL.features.check("webp"), "Pillow без WebP"'

step "Копия базы и миграции"
STAGE="копия базы"
if [ -f "$DATA_DIR/db/dobromir.sqlite" ]; then
    (cd pipeline && "$VENV_PY" -m pipeline backup)
else
    echo "  ok    базы еще нет - копировать нечего"
fi
STAGE="миграции"
(cd pipeline && "$VENV_PY" -m pipeline migrate)

step "Зависимости сайта"
STAGE="npm ci"
if [ "$FORCE_NPM" -eq 1 ] || [ ! -f site/node_modules/.package-lock.json ] ||
    ! git diff --quiet "$OLD_COMMIT" "$NEW_COMMIT" -- site/package-lock.json; then
    (cd site && npm ci --no-fund --no-audit)
    echo "  ok    npm ci"
else
    echo "  ok    package-lock.json не изменился - node_modules остаются"
fi

step "Сборка релиза"
STAGE="сборка"
if [ -f "$DATA_DIR/export/news.json" ]; then
    if [ "$SWITCH" -eq 1 ]; then
        (cd pipeline && "$VENV_PY" -m pipeline build --switch)
    else
        (cd pipeline && "$VENV_PY" -m pipeline build)
    fi
elif [ "$SWITCH" -eq 1 ]; then
    die "нет $DATA_DIR/export/news.json - переключать не на что; сначала ./deploy/run-worker.sh (первый запуск загрузит новости)"
else
    echo "  ok    news.json еще нет - пробная сборка пропущена (его создаст первый запуск ./deploy/run-worker.sh)"
fi

STAGE=""
echo
echo "Готово: клон на $TAG."
