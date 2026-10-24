#!/usr/bin/env bash
# Копия базы из cron раз в сутки, строка - в deploy/crontab.example.
#
# Копии лежат в ~/dobromir-data/backup/, хранятся 7 последних (pipeline/backup.py).
# При успехе ничего не печатает (иначе CronTab шлет письмо каждый день); при ошибке -
# строка в stderr и код 1. Автобэкапы Beget - дополнительная защита, не замена.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/pipeline/.venv/bin/python"

export PATH="/usr/local/bin:/usr/bin:/bin"
export PYTHONIOENCODING=utf-8

if [ ! -x "$PY" ]; then
    echo "Копия базы не сделана: нет $PY. Нужен deploy/bootstrap.sh --apply" >&2
    exit 1
fi

cd "$REPO/pipeline"
"$PY" -m pipeline backup >/dev/null
