# Первый запуск и старт сайта

Для кого: разработчик, который впервые разворачивает проект на новой машине или на хостинге.
Порядок шагов от пустой папки до работающего сайта.

## Обзор

Сайт состоит из двух частей:
1. **Пайплайн** (`pipeline/`) — Python-скрипт, который забирает новости из VK, хранит в SQLite, экспортирует `news.json` и собирает сайт
2. **Сайт** (`site/`) — Astro-проект, который собирается из `news.json` и ручного содержимого

## Шаг 1: Клонирование репозитория

```bash
git clone git@gitverse.ru:yourdisenchantment/dobromir.git
cd dobromir
```

## Шаг 2: Настройка окружения пайплайна

```bash
cd pipeline
uv sync                    # создает .venv, ставит зависимости
```

Проверка:
```bash
uv run ruff check src tests
uv run mypy
uv run pytest
```

## Шаг 3: Настройка окружения сайта

```bash
cd ../site
npm ci                     # воспроизводимая установка по package-lock.json
```

Проверка:
```bash
npm run lint
npm run format:check
npm run check
npm test
```

## Шаг 4: Создание каталога данных

```bash
mkdir -p ~/dobromir-data
cp .env.example ~/dobromir-data/.env
```

Заполнить `~/dobromir-data/.env`:
```
SITE_ROOT=/абсолютный/путь/к/site
SITE_ENV=staging (или production)
VK_SERVICE_TOKEN=ваш_сервисный_ключ
VK_GROUP_ID=49938199   # боевая (dobromir.crimea); тестовая 242263522 (antarctic.test)
NEWS_RETENTION_DAYS=90
```

**Важно:** `SITE_ROOT` — абсолютный путь (без `~`). `SITE_ENV` без значения по умолчанию.

## Шаг 5: Первичная загрузка новостей (backfill)

```bash
cd pipeline
DOBROMIR_DATA=~/dobromir-data uv run python -m pipeline backfill
```

Что делает:
- Листает стену VK, пока не встретит пост старше срока хранения (90 дней)
- Сохраняет посты в SQLite (`~/dobromir-data/db/dobromir.sqlite`)
- Скачивает фото в `~/dobromir-data/site/media/photos/`
- Ставит отметку `backfill_done_at` — повторно не запустится

Проверка:
```bash
DOBROMIR_DATA=~/dobromir-data uv run python -m pipeline sync
# В логе: "посты: ...; без изменений" (не "первичная загрузка")
```

## Шаг 6: Экспорт news.json

```bash
cd pipeline
DOBROMIR_DATA=~/dobromir-data uv run python -m pipeline export
```

Создает `~/dobromir-data/export/news.json` — файл, из которого Astro собирает новости.

## Шаг 7: Сборка сайта

```bash
cd site
MEDIA_DIR=~/dobromir-data/site/media NEWS_JSON=~/dobromir-data/export/news.json SITE_ENV=staging npm run build
```

Что делает:
1. `prepare-content.ts` — обрабатывает фото (WebP, 800 px, без метаданных) и тексты (типографика)
2. `astro build` — собирает статические страницы в `site/dist/`

Проверка: `site/dist/index.html` существует, `site/dist/news/` содержит страницы новостей.

## Шаг 8: Запуск сервера разработки

```bash
cd site
MEDIA_DIR=~/dobromir-data/site/media NEWS_JSON=~/dobromir-data/export/news.json npm run dev
```

Сайт доступен на http://localhost:4321/

## Шаг 9: Запуск воркера (полный цикл)

```bash
cd pipeline
DOBROMIR_DATA=~/dobromir-data uv run python -m pipeline worker
```

Что делает:
1. Блокировка (fcntl) — защита от параллельных запусков
2. Синк: окно VK (50 постов), суточная сверка, фото, news.json
3. Сборка (если есть изменения) в `releases/<ts>/`
4. Переключение `public_html` -> новый релиз
5. Чистка медиа (если сайт не устарел)
6. Запись `status.json`

При успехе — вывод 0 байт (cron шлет письмо на любой вывод).

## Диагностика

### Проверить настройки
```bash
cd pipeline && DOBROMIR_DATA=~/dobromir-data uv run python -c "
from pipeline.settings import load_settings
s = load_settings()
print(f'VK_GROUP_ID: {s.vk_group_id}')
print(f'TOKEN_PRESENT: {\"Yes\" if s.vk_service_token else \"No\"}')
print(f'RETENTION: {s.news_retention_days}')
print(f'SITE_ROOT: {s.site.root}')
print(f'SITE_ENV: {s.site_env}')
"
```

### Проверить базу
```bash
cd pipeline && DOBROMIR_DATA=~/dobromir-data uv run python -c "
from pipeline.store.db import open_db
from pipeline.store.state import Store
from pathlib import Path
conn = open_db(Path.home() / 'dobromir-data' / 'db' / 'dobromir.sqlite')
store = Store(conn)
posts = store.posts(include_deleted=False)
print(f'Живых постов: {len(posts)}')
for p in posts[:3]:
    print(f'  ID: {p.post.id}, Date: {p.post.timestamp}')
"
```

### Проверить news.json
```bash
python3 -c "
import json
with open('~/dobromir-data/export/news.json') as f:
    data = json.load(f)
print(f'Версия: {data[\"version\"]}')
print(f'Постов: {len(data[\"posts\"])}')
print(f'Сгенерирован: {data[\"generated_at\"]}')
"
```

### Проверить лог воркера
```bash
tail -n 20 ~/dobromir-data/logs/worker.log
```

### Проверить статус
```bash
cat ~/dobromir-data/status.json
```

## На хостинге (Beget)

Полная инструкция: `docs/server.md`, раздел «Первая установка».

Кратко:
1. `./deploy/bootstrap.sh` (проверки)
2. `./deploy/bootstrap.sh --apply` (выполнение)
3. Заполнить `~/dobromir-data/.env` (SITE_ENV, VK_SERVICE_TOKEN, VK_GROUP_ID)
4. `./deploy/run-worker.sh` (первый запуск: загрузка новостей + сборка)
5. Заменить `public_html` на ссылку на релиз (вручную, один раз)
6. Настроить cron по `deploy/crontab.example`

## Команды для работы с содержимым

```bash
# Проверить содержимое без сборки
npm run content:check

# Собрать с настоящими данными
MEDIA_DIR=~/dobromir-data/site/media NEWS_JSON=~/dobromir-data/export/news.json npm run build

# Запустить dev-сервер
MEDIA_DIR=~/dobromir-data/site/media NEWS_JSON=~/dobromir-data/export/news.json npm run dev

# Полная проверка перед коммитом
npm run lint && npm run format:check && npm run check && npm test
```
