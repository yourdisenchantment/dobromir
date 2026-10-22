# Зависимости: как обновить

## Python (`pipeline/`)

Целевая версия - Python 3.10: на хосте Beget 3.10.12, свой интерпретатор там
не ставим. Локально разработка идет на той же версии через `uv`.

Источник истины - `pipeline/uv.lock`.

**На сервере - uv с системным Python** (решено 2026-10-22). Без root, из
каталога `pipeline/` клона:

```bash
python3 -m venv ~/.local/share/dobromir-uv
~/.local/share/dobromir-uv/bin/pip install uv
~/.local/share/dobromir-uv/bin/uv sync --frozen --no-dev --python /usr/bin/python3
```

Все это делает `deploy/bootstrap.sh`. uv ставится в свой venv, а не через
`pip install --user`: на системах с PEP 668 (externally-managed) тот
запрещен - так и упало при проверке 2026-10-22. uv ставит ровно то, что в `uv.lock`, и не скачивает свой интерпретатор
(`--python` указывает на системный 3.10.12). Проверить на хосте в P1-7: что
модуль `venv` есть у системного Python, что uv запускается из cron с
явным `PATH`, сколько места занимает кэш `~/.cache/uv`.

**Запасной путь - pip**, если uv на хосте не заработает: `python3 -m venv` и
`pip install -r requirements.txt`. Поэтому `pipeline/requirements.txt`
продолжаем порождать из `uv.lock` и коммитить вместе с ним, пока P1-7 не
подтвердит uv. После подтверждения файл и команду `uv export` можно убрать.

Обновить все до свежих версий (из каталога `pipeline/`):

```bash
uv lock --upgrade
uv sync
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest
uv export --frozen --no-dev --no-hashes -o requirements.txt
```

Добавить зависимость: дописать голое имя в `dependencies` в `pyproject.toml`,
затем `uv lock`, `uv sync`, проверки и `uv export` как выше. После `uv add`
удалить дописанную им границу `>=` (правило версий в `AGENTS.md`).

`pyproject.toml`, `uv.lock` и `requirements.txt` коммитятся одним коммитом:
расхождение между ними не видно до установки на сервере.

Что учесть:

- `requirements.txt` начинается с `-e .` - это сам пакет `pipeline`. Значит,
  `pip install -r requirements.txt` нужно запускать **из каталога
  `pipeline/`**, и pip скачает с PyPI сборщик `hatchling`, чтобы поставить
  пакет. Проверено локально 2026-10-20: чистый venv на 3.10.22, pip 23.0.1 -
  ставится, `python -m pipeline --help` работает. На хосте не проверено
  (задача P1-7 в BACKLOG).
- Колеса `pillow` под Linux x86_64 требуют glibc не ниже 2.28. Версию glibc
  на хосте проверить в P1-7.
- Не поднимать `requires-python` выше 3.10, пока хост на 3.10: `uv lock` тогда
  может выбрать версии пакетов, у которых нет колес под 3.10.

## Node (`site/`)

Источник истины - `site/package-lock.json` (с 2026-10-20, P0-3; bun больше не
используется). На сервере ставить только `npm ci`: он берет версии строго из
lock-файла, а `npm install` при `latest` в `package.json` подтянул бы новые.

Обновить все до свежих версий (из каталога `site/`):

```bash
npm update
npm run lint && npm run format:check && npm run check && npm run build
npm audit
```

`package.json` и `package-lock.json` коммитятся одним коммитом.

Что учесть:

- TypeScript держать на 6, override для `eslint-plugin-jsx-a11y` не убирать
  без проверки (`AGENTS.md`, «Ловушки»).
- `package-lock.json` содержит нативные пакеты для всех платформ, в том числе
  `linux-x64` (компилятор Astro, rolldown, lightningcss, sharp) - проверено
  2026-10-20. Если после обновления сборка на хосте падает на нативном модуле,
  первым делом проверить, что lock-файл сгенерирован npm, а не другим
  менеджером.
- npm 11 печатает `npm warn install-scripts`. На 2026-10-20 `npm
  install-scripts ls` показывает, что непроверенных скриптов нет, то есть
  ничего не заблокировано.
