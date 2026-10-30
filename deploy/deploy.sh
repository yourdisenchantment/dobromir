#!/usr/bin/env bash
# Обновление сайта на сервере из GitVerse (ветка main), решено 2026-10-28. Руками по SSH
# или из cron - одинаково; инструкция - docs/server.md.
#
#   ./deploy/deploy.sh                # забрать новое из main, собрать, проверить, включить
#   ./deploy/deploy.sh --cron         # то же для cron: молчит, если нового нет
#   ./deploy/deploy.sh --to <коммит>  # поставить код на этот коммит (откат кода); cron
#                                     # его не трогает, пока не запустить deploy.sh без --to
#   ./deploy/deploy.sh --no-switch    # собрать и проверить, но не включать
#   ./deploy/deploy.sh --pip          # Python-зависимости через pip, если uv не работает
#   ./deploy/deploy.sh --npm-ci       # переустановить node_modules, даже если lock не менялся
#
# Шаги: git fetch; переход на новый коммит (только вперед, без слияний); зависимости
# Python и сайта (npm ci - только при новом package-lock.json); пробная сборка релиза в
# releases/ с проверками; копия базы и миграции; переключение public_html на новый релиз.
#
# Ошибка на любом шаге: public_html не переключается - сайт остается на прежнем
# релизе. До миграций код и зависимости возвращаются к прежнему коммиту (воркер
# работает на проверенном коде); после начала миграций код остается новым, чтобы не
# запускать старый код на новой схеме базы. Письмо (stderr): шаг, причина, что делать.
# Коммит, на котором упало, запоминается в <данные>/deploy-state: --cron его больше не
# пробует (одно письмо на сломанный push), запуск руками - пробует.
#
# Успех: одна сводка в stdout (из cron приходит письмом): какие коммиты вышли и как
# откатить. Журнал - <данные>/logs/deploy.log (из cron - весь ход, руками - итог).
#
# Под той же блокировкой, что воркер (deploy/locked.py): пока идет одно, другое ждет.
# Если в клоне изменены отслеживаемые файлы - отказ до любых действий. Не удаляет файлы,
# не трогает .env и cron.
#
# Переменные: PYTHON (по умолчанию /usr/bin/python3), NODE_BIN, DOBROMIR_DATA,
# REMOTE (origin), BRANCH (main)
set -euo pipefail

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

CRON=0
TO=""
SWITCH=1
USE_PIP=0
FORCE_NPM=0
ARGS=("$@")
while [ "$#" -gt 0 ]; do
    case "$1" in
        --cron) CRON=1 ;;
        --to)
            [ "$#" -ge 2 ] || {
                echo "--to: нужен коммит" >&2
                exit 2
            }
            TO="$2"
            shift
            ;;
        --no-switch) SWITCH=0 ;;
        --pip) USE_PIP=1 ;;
        --npm-ci) FORCE_NPM=1 ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            echo "неизвестный аргумент: $1 (см. --help)" >&2
            exit 2
            ;;
    esac
    shift
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-/usr/bin/python3}"
NODE_BIN="${NODE_BIN:-$HOME/opt/node/bin}"
DATA_DIR="${DOBROMIR_DATA:-$HOME/dobromir-data}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
UV="$HOME/.local/share/dobromir-uv/bin/uv"
VENV_PY="$REPO/pipeline/.venv/bin/python"
STATE="$DATA_DIR/deploy-state"
LOG="$DATA_DIR/logs/deploy.log"
export PATH="$NODE_BIN:/usr/local/bin:/usr/bin:/bin"
export ASTRO_TELEMETRY_DISABLED=1
# Сборка на сервере содержимое только проверяет, файлы клона не правит.
export CONTENT_CHECK_ONLY=1
export PYTHONIOENCODING=utf-8
export UV_PYTHON_DOWNLOADS=never # только системный Python, свой интерпретатор uv не качает
umask 077 # файлы в DATA_DIR (логи, бэкапы, deploy-state) - только для владельца

[ -x "$PYTHON" ] || {
    echo "Обновление не запущено: нет $PYTHON (задайте PYTHON=путь)" >&2
    exit 1
}

# Весь деплой - под блокировкой воркера: перезапуск себя через locked.py.
if [ "${DOBROMIR_LOCK_HELD:-}" != "1" ]; then
    code=0
    "$PYTHON" "$REPO/deploy/locked.py" "$DATA_DIR/worker.lock" "$0" ${ARGS[@]+"${ARGS[@]}"} || code=$?
    if [ "$code" -eq 75 ]; then
        # Воркер собирает сайт: из cron - тихо, следующий запуск через час.
        [ "$CRON" -eq 1 ] && exit 0
        echo "Сейчас работает воркер или другое обновление - повторите через несколько минут." >&2
        exit 1
    fi
    exit "$code"
fi

mkdir -p "$(dirname "$LOG")"
LOG_START=1
[ ! -f "$LOG" ] || LOG_START=$(($(wc -l <"$LOG") + 1)) # в письмо - строки только этого запуска
printf '\n=== %s deploy.sh %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${ARGS[*]:-}" >>"$LOG"
# fd 3/4 - настоящие stdout/stderr (из cron - письмо). Из cron ход работы - только в
# журнал; руками - на экран, в журнал - итог.
exec 3>&1 4>&2
[ "$CRON" -eq 0 ] || exec >>"$LOG" 2>&1

step() {
    echo
    echo "== $*"
}
die() {
    echo "ОШИБКА: $*" >&2
    exit 1
}
short() { git -C "$REPO" rev-parse --short "$1"; }
state_get() { [ -f "$STATE" ] && sed -n "s/^$1=//p" "$STATE" | tail -n 1 || true; }
state_set() { printf 'failed=%s\n' "$1" >"$STATE"; }
lock_changed() { [ "$OLD" != "$NEW" ] && ! git -C "$REPO" diff --quiet "$OLD" "$NEW" -- "$@"; }

STAGE=""
OLD=""
OLD_BRANCH=""
NEW=""
MIGRATING=0

python_deps() {
    if [ "$USE_PIP" -eq 1 ]; then
        [ -x "$VENV_PY" ] || "$PYTHON" -m venv "$REPO/pipeline/.venv"
        # requirements.txt начинается с -e ., поэтому из каталога pipeline/.
        (cd "$REPO/pipeline" && .venv/bin/pip install -q -r requirements.txt)
        echo "  ok    pip install -r requirements.txt"
    else
        (cd "$REPO/pipeline" && "$UV" sync --frozen --no-dev --python "$PYTHON")
        echo "  ok    uv sync --frozen --no-dev"
    fi
}

site_deps() {
    if [ "$FORCE_NPM" -eq 1 ] || [ ! -f "$REPO/site/node_modules/.package-lock.json" ] ||
        lock_changed site/package-lock.json; then
        (cd "$REPO/site" && npm ci --ignore-scripts --no-fund --no-audit)
        echo "  ok    npm ci --ignore-scripts"
    else
        echo "  ok    package-lock.json не изменился - node_modules остаются"
    fi
}

# Вернуть код и зависимости к прежнему коммиту. Печатает, что не удалось.
revert_code() {
    local ok=1
    if [ -n "$OLD_BRANCH" ]; then
        git -C "$REPO" checkout -q -B "$OLD_BRANCH" "$OLD" || ok=0
    else
        git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$OLD" || ok=0
    fi
    if [ "$ok" -eq 1 ]; then
        python_deps >/dev/null 2>&1 || ok=0
        if lock_changed site/package-lock.json; then
            (cd "$REPO/site" && npm ci --ignore-scripts --no-fund --no-audit >/dev/null 2>&1) || ok=0
        fi
    fi
    if [ "$ok" -eq 1 ]; then
        echo "Код и зависимости возвращены к $(short "$OLD")."
    else
        echo "Вернуть код не удалось - сделайте руками: ./deploy/deploy.sh --to $(short "$OLD")"
    fi
}

finish() {
    local code=$?
    [ "$code" -eq 0 ] || [ -z "$STAGE" ] && return
    local tail_log=""
    [ "$CRON" -eq 1 ] && tail_log="$(tail -n "+$LOG_START" "$LOG" | tail -n 15)"
    {
        echo "Сайт не обновлен: ошибка на шаге «${STAGE}» (код $code)."
        echo "Сайт работает на прежнем релизе, public_html не переключался."
        if [ -n "$NEW" ] && [ "$NEW" != "$OLD" ]; then
            echo "Пробовали: $(short "$OLD") -> $(short "$NEW") ($(git -C "$REPO" log -1 --format=%s "$NEW"))."
            if [ "$MIGRATING" -eq 1 ]; then
                echo "Миграции базы уже начались, поэтому код оставлен на $(short "$NEW")."
                echo "Копия базы до миграций - последняя в $DATA_DIR/backup/ (docs/server.md, «Восстановить базу»)."
            else
                revert_code
            fi
            state_set "$NEW"
            echo "Автообновление этот коммит больше не пробует: исправьте в репозитории и сделайте push"
            echo "или повторите руками: ./deploy/deploy.sh"
        fi
        echo "Что делать при ошибках - docs/server.md; весь ход - $LOG."
        if [ -n "$tail_log" ]; then
            echo
            echo "Последние строки журнала:"
            echo "$tail_log"
        fi
    } | tee -a "$LOG" >&4
}
trap finish EXIT

cd "$REPO"

STAGE="проверки"
git rev-parse --git-dir >/dev/null 2>&1 || die "$REPO - не клон git"
[ -z "$(git status --porcelain --untracked-files=no)" ] ||
    die "в клоне на сервере изменены файлы (git status) - обновление их затерло бы. Правки делаются у себя и приходят через GitVerse"
if [ "$USE_PIP" -eq 0 ] && [ ! -x "$UV" ]; then
    die "нет uv ($UV): сначала ./deploy/bootstrap.sh --apply или ключ --pip"
fi
[ -x "$NODE_BIN/npm" ] || die "нет npm в $NODE_BIN (задайте NODE_BIN=путь)"
OLD="$(git rev-parse HEAD)"
OLD_BRANCH="$(git symbolic-ref -q --short HEAD || true)"

STAGE="получение кода"
git fetch -q --tags "$REMOTE" "$BRANCH"
if [ -n "$TO" ]; then
    NEW="$(git rev-parse -q --verify "$TO^{commit}")" || die "нет коммита $TO (git log --oneline $REMOTE/$BRANCH)"
else
    NEW="$(git rev-parse "$REMOTE/$BRANCH")"
fi

if [ "$CRON" -eq 1 ]; then
    # Тихие причины ничего не делать: письма из cron нужны только по делу.
    if [ -z "$OLD_BRANCH" ]; then
        echo "  код закреплен на $(short "$OLD") (--to) - автообновление ждет запуска руками"
        STAGE=""
        exit 0
    fi
    if [ "$NEW" = "$OLD" ] || [ "$NEW" = "$(state_get failed)" ]; then
        echo "  нового нет ($(short "$NEW"))"
        STAGE=""
        exit 0
    fi
elif [ -z "$TO" ] && [ -n "$OLD_BRANCH" ] && [ "$NEW" = "$OLD" ]; then
    echo "Новых изменений нет: сервер на $(short "$OLD"), как $REMOTE/$BRANCH." >&3
    STAGE=""
    exit 0
fi
if [ -z "$TO" ] && ! git merge-base --is-ancestor "$OLD" "$NEW"; then
    NEW_TMP="$NEW"
    NEW=""
    die "история $REMOTE/$BRANCH ($(short "$NEW_TMP")) не продолжает версию на сервере ($(short "$OLD")) - похоже, ее переписали (force push). Разберитесь в репозитории; поставить код на нужный коммит: ./deploy/deploy.sh --to <коммит>"
fi

step "Код: $(short "$OLD") -> $(short "$NEW")"
STAGE="переход на новый код"
if [ -n "$TO" ]; then
    git -c advice.detachedHead=false checkout -q --detach "$NEW"
else
    git checkout -q -B "$BRANCH" "$NEW"
fi
echo "  ok    $(git log -1 --format='%h %s')"

step "Зависимости"
STAGE="Python-зависимости"
python_deps
"$VENV_PY" -c 'import pipeline.settings, PIL.features; assert PIL.features.check("webp"), "Pillow без WebP"'
STAGE="зависимости сайта (npm ci)"
site_deps

step "Пробная сборка"
STAGE="сборка"
RELEASE=""
if [ -f "$DATA_DIR/export/news.json" ]; then
    out="$(cd pipeline && "$VENV_PY" -m pipeline build)"
    echo "$out"
    RELEASE="$(printf '%s\n' "$out" | sed -n 's/.* --to //p' | tail -n 1)"
    [ -n "$RELEASE" ] || die "сборка не назвала релиз"
else
    echo "  ok    news.json еще нет - сборка пропущена (его создаст первый запуск ./deploy/run-worker.sh)"
fi

step "Копия базы и миграции"
STAGE="копия базы"
if [ -f "$DATA_DIR/db/dobromir.sqlite" ]; then
    (cd pipeline && "$VENV_PY" -m pipeline backup)
else
    echo "  ok    базы еще нет - копировать нечего"
fi
STAGE="миграции"
MIGRATING=1
(cd pipeline && "$VENV_PY" -m pipeline migrate)

STAGE="включение релиза"
if [ -z "$RELEASE" ]; then
    SWITCHED="релиз не собирался (нет news.json)"
elif [ "$SWITCH" -eq 0 ]; then
    SWITCHED="релиз $RELEASE собран, не включен (--no-switch). Включить: $VENV_PY -m pipeline rollback --to $RELEASE"
else
    step "Включение"
    (cd pipeline && "$VENV_PY" -m pipeline rollback --to "$RELEASE")
    SWITCHED="включен релиз $RELEASE"
fi

STAGE=""
state_set ""
{
    if [ "$NEW" = "$OLD" ]; then
        echo "Сайт пересобран на $(short "$NEW"): $SWITCHED."
    else
        echo "Сайт обновлен: $(short "$OLD") -> $(short "$NEW"), $SWITCHED."
        if git merge-base --is-ancestor "$OLD" "$NEW"; then
            echo "Что вышло:"
            git log --format='  %h %s' "$OLD..$NEW" | head -n 20
        else
            echo "Код поставлен на $(short "$NEW") (откат); автообновление ждет запуска ./deploy/deploy.sh без --to."
        fi
    fi
    echo "Откатить сайт: $VENV_PY -m pipeline rollback; код: ./deploy/deploy.sh --to $(short "$OLD")"
} | tee -a "$LOG" >&3
