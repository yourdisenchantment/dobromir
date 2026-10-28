"""Запустить команду под блокировкой воркера (deploy.sh, решено 2026-10-28).

    python3 deploy/locked.py <файл блокировки> <команда> [аргументы...]

Та же fcntl-блокировка (lockf), что у воркера (`pipeline.worker.single_instance`), а не
shell-flock: flock и lockf друг друга не видят. Пока команда идет, воркер из cron и
команды `python -m pipeline build/migrate/rollback` вне ее ждут следующего запуска.
Команде передается DOBROMIR_LOCK_HELD=1: ее собственные вызовы pipeline блокировку уже
не берут (дочерний процесс не наследует lockf и иначе сам себе бы мешал).

Только стандартная библиотека и системный Python: запускается и до того, как есть venv.
Код выхода - код команды; 75, если блокировка занята.
"""

import fcntl
import os
import subprocess
import sys

BUSY = 75  # EX_TEMPFAIL: повторить позже


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    lock, command = argv[1], argv[2:]
    os.makedirs(os.path.dirname(os.path.abspath(lock)), exist_ok=True)
    with open(lock, "a") as fh:
        try:
            fcntl.lockf(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return BUSY
        env = {**os.environ, "DOBROMIR_LOCK_HELD": "1"}
        return subprocess.call(command, env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
