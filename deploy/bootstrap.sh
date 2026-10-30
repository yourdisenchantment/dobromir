#!/usr/bin/env bash
# Первичная подготовка сервера Beget к работе проекта. Запускать из корня клона:
#
#   ./deploy/bootstrap.sh            # только проверки и план, ничего не меняет
#   ./deploy/bootstrap.sh --apply    # выполнить
#   ./deploy/bootstrap.sh --apply --pip   # зависимости через pip, если uv не работает
#
# Что делает с --apply (повторный запуск безопасен, существующее не трогает):
#   1. создает каталоги данных и сайта (раскладка - docs/hosting-report-2026-10-18.md, разд. 7);
#   2. создает <данные>/.env из .env.example с правами 600, если его еще нет;
#   3. ставит uv в свой venv (~/.local/share/dobromir-uv) и Python-зависимости по
#      uv.lock на системном Python;
#   4. ставит npm-зависимости сайта по package-lock.json и проверяет сборку.
#
# Чего не делает никогда: не удаляет файлы, не трогает public_html, не правит
# существующий .env, не ставит cron (его ставит человек по deploy/crontab.example), не пишет
# секреты в вывод.
#
# Пути можно переопределить переменными (для проверки на ноутбуке):
#   DATA_DIR  SITE_DIR  PYTHON  NODE_BIN
set -euo pipefail

APPLY=0
USE_PIP=0
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        --pip) USE_PIP=1 ;;
        -h | --help)
            # Справка - это шапка из комментариев в начале файла.
            awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
            exit 0
            ;;
        *)
            echo "неизвестный аргумент: $arg (см. --help)" >&2
            exit 2
            ;;
    esac
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$HOME/dobromir-data}"
SITE_DIR="${SITE_DIR:-$HOME/a978879k.beget.tech}"
PYTHON="${PYTHON:-/usr/bin/python3}"
NODE_BIN="${NODE_BIN:-$HOME/opt/node/bin}"
# uv живет в отдельном venv, а не в pip --user: на системах с PEP 668
# (externally-managed) pip --user запрещен, а venv работает везде.
UV_HOME="$HOME/.local/share/dobromir-uv"
UV="$UV_HOME/bin/uv"
export PATH="$NODE_BIN:/usr/local/bin:/usr/bin:/bin"
export ASTRO_TELEMETRY_DISABLED=1
# Сборка на сервере содержимое только проверяет, файлы клона не правит.
export CONTENT_CHECK_ONLY=1

errors=0
ok() { echo "  ok    $*"; }
warn() { echo "  !     $*"; }
fail() {
    echo "  ОШИБКА $*"
    errors=$((errors + 1))
}
step() { echo; echo "== $*"; }
run() {
    if [ "$APPLY" -eq 1 ]; then
        echo "  >     $*"
        "$@"
    else
        echo "  план  $*"
    fi
}

echo "Репозиторий: $REPO"
echo "Данные:      $DATA_DIR"
echo "Сайт:        $SITE_DIR"
[ "$APPLY" -eq 1 ] && echo "Режим:       ВЫПОЛНЕНИЕ" || echo "Режим:       только проверка (добавьте --apply)"

step "Проверки"
if [ -d "$REPO/pipeline" ] && [ -d "$REPO/site" ]; then ok "клон репозитория на месте"; else fail "нет pipeline/ или site/ в $REPO"; fi
case "$DATA_DIR" in "$REPO" | "$REPO"/*) fail "каталог данных внутри клона: данные о детях попадут под git" ;; esac
case "$SITE_DIR" in "$REPO" | "$REPO"/*) fail "папка сайта внутри клона" ;; esac
if command -v git >/dev/null; then ok "git $(git --version | awk '{print $3}')"; else fail "нет git"; fi

if [ -x "$PYTHON" ]; then
    pyver="$("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
    if "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        ok "Python $pyver ($PYTHON)"
    else
        fail "Python $pyver: нужен 3.10 или новее"
    fi
else
    fail "нет $PYTHON (задайте PYTHON=путь)"
fi

if [ -x "$NODE_BIN/node" ]; then
    nodever="$("$NODE_BIN/node" --version)"
    major="${nodever#v}"
    major="${major%%.*}"
    if [ "$major" -ge 22 ]; then ok "Node $nodever ($NODE_BIN)"; else fail "Node $nodever: нужен 22.12 или новее"; fi
    if [ -x "$NODE_BIN/npm" ]; then ok "npm $("$NODE_BIN/npm" --version)"; else fail "нет npm в $NODE_BIN"; fi
else
    fail "нет node в $NODE_BIN (задайте NODE_BIN=путь)"
fi

# venv нужен и для uv, и для запасного пути --pip. На Ubuntu он бывает в отдельном пакете.
if [ -x "$PYTHON" ] && "$PYTHON" -c 'import venv, ensurepip' 2>/dev/null; then
    ok "модуль venv есть"
else
    fail "у $PYTHON нет модуля venv/ensurepip (на Ubuntu - пакет python3-venv, root у Beget нет: писать в поддержку)"
fi
[ -x "$UV" ] && ok "uv уже стоит: $("$UV" --version)"

if [ -L "$SITE_DIR/public_html" ]; then
    ok "public_html уже ссылка на $(readlink "$SITE_DIR/public_html")"
elif [ -d "$SITE_DIR/public_html" ]; then
    warn "public_html - обычный каталог (старый сайт). Скрипт его не трогает; замена на ссылку - вручную"
fi

if [ "$errors" -gt 0 ]; then
    echo
    echo "Остановлено: ошибок проверки - $errors. Ничего не изменено."
    exit 1
fi

step "Каталоги"
for d in "$DATA_DIR" "$DATA_DIR/db" "$DATA_DIR/export" "$DATA_DIR/logs" "$SITE_DIR/media" "$SITE_DIR/releases"; do
    if [ -d "$d" ]; then ok "есть $d"; else run mkdir -p "$d"; fi
done
run chmod 700 "$DATA_DIR"

step "Настройки ($DATA_DIR/.env)"
if [ -e "$DATA_DIR/.env" ]; then
    run chmod 600 "$DATA_DIR/.env"
    ok "уже есть, не трогаю (права 600 проверены)"
else
    if [ "$APPLY" -eq 1 ]; then
        umask 077
        # Папку сайта знаем - подставляем; ключи VK и SITE_ENV остаются пустыми - их вносит человек.
        # DOBROMIR_DATA в файл не пишем: каталог данных код берет из окружения или по умолчанию.
        # Экранируем \, & и | в пути, чтобы sed не сломался на нестандартных путях.
        escaped_site_dir="$(printf '%s' "$SITE_DIR" | sed 's/[\\&|]/\\&/g')"
        sed -e "s|^SITE_ROOT=.*|SITE_ROOT=$escaped_site_dir|" "$REPO/.env.example" >"$DATA_DIR/.env"
        chmod 600 "$DATA_DIR/.env"
        echo "  >     создан из .env.example (права 600). Заполнить: SITE_ENV, VK_SERVICE_TOKEN, VK_GROUP_ID"
    else
        echo "  план  создать из .env.example с правами 600"
    fi
fi

step "Python-зависимости"
if [ "$USE_PIP" -eq 1 ]; then
    [ -x "$REPO/pipeline/.venv/bin/python" ] || run "$PYTHON" -m venv "$REPO/pipeline/.venv"
    # requirements.txt начинается с -e ., поэтому из каталога pipeline/.
    if [ "$APPLY" -eq 1 ]; then
        (cd "$REPO/pipeline" && .venv/bin/pip install -q -r requirements.txt)
        echo "  >     pip install -r requirements.txt"
    else
        echo "  план  pip install -r requirements.txt (в pipeline/.venv)"
    fi
else
    if [ ! -x "$UV" ]; then
        run "$PYTHON" -m venv "$UV_HOME"
        run "$UV_HOME/bin/pip" install --quiet uv
    fi
    if [ "$APPLY" -eq 1 ]; then
        (cd "$REPO/pipeline" && "$UV" sync --frozen --no-dev --python "$PYTHON")
        echo "  >     uv sync --frozen --no-dev --python $PYTHON"
    else
        echo "  план  uv sync --frozen --no-dev --python $PYTHON (в pipeline/)"
    fi
fi
if [ "$APPLY" -eq 1 ]; then
    "$REPO/pipeline/.venv/bin/python" -c 'import httpx, PIL.features, pydantic, zoneinfo, pipeline.settings; zoneinfo.ZoneInfo("Europe/Simferopol"); assert PIL.features.check("webp"), "Pillow без WebP"'
    ok "пакеты импортируются, часовой пояс Europe/Simferopol найден, Pillow пишет WebP"
fi

step "Сайт"
if [ "$APPLY" -eq 1 ]; then
    (cd "$REPO/site" && npm ci --ignore-scripts --no-fund --no-audit)
    echo "  >     npm ci --ignore-scripts"
    (cd "$REPO/site" && npm run build >/dev/null)
    ok "пробная сборка прошла (в site/dist, не в public_html)"
else
    echo "  план  npm ci, затем пробная сборка в site/dist"
fi

echo
if [ "$APPLY" -eq 1 ]; then
    echo "Готово. Дальше вручную:"
    echo "  1. заполнить $DATA_DIR/.env: SITE_ENV, VK_SERVICE_TOKEN, VK_GROUP_ID"
    echo "  2. ./deploy/run-worker.sh: первый запуск сам загрузит новости за срок хранения и соберет релиз"
    echo "  3. замена public_html ссылкой на релиз, затем cron по deploy/crontab.example"
    echo "  Подробно - docs/server.md, «Первая установка»."
else
    echo "Проверки пройдены. Для выполнения: ./deploy/bootstrap.sh --apply"
fi
