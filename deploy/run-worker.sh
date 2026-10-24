#!/usr/bin/env bash
# Запуск воркера из cron (панель CronTab Beget), строка - в deploy/crontab.example.
#
# При успехе ничего не печатает: CronTab присылает письмо на любой вывод. При ошибке -
# 1-2 строки по-русски в stderr и код выхода воркера: 0 успех или воркер уже идет,
# 1 общая ошибка, 2 ключ VK, 3 защита от массового удаления.
#
# Настройки и ключи воркер читает сам из ~/dobromir-data/.env; этот скрипт их не читает
# и не печатает. Параллельные запуски исключает блокировка внутри воркера.
#
# Переменные (для проверки на ноутбуке): NODE_BIN
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
NODE_BIN="${NODE_BIN:-$HOME/opt/node/bin}"
PY="$REPO/pipeline/.venv/bin/python"

# У cron свое, почти пустое окружение: PATH задается явно (Node для сборки сайта).
export PATH="$NODE_BIN:/usr/local/bin:/usr/bin:/bin"
export ASTRO_TELEMETRY_DISABLED=1
export PYTHONIOENCODING=utf-8

if [ ! -x "$PY" ]; then
    echo "Воркер не запущен: нет $PY. Нужен deploy/bootstrap.sh --apply" >&2
    exit 1
fi

cd "$REPO/pipeline"
exec "$PY" -m pipeline worker
