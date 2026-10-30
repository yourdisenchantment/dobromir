# 03. Архитектура проекта, структура и принятые решения

**Источник:** чаты «Добромир», «Новый сайт и репозиторий», BACKLOG, OPEN-QUESTIONS (2026-10-05 — 2026-10-28)
**Тема:** Структура проекта, архитектура, технические решения, стек

---

## Резюме

Проект — статичный сайт центра коррекционной педагогики «Добромир» (Симферополь) на Astro + Python-воркер. Данные тянутся из VK-паблика `vk.com/dobromir.crimea` через cron-скрипт. Сайт полностью статичный, входящих эндпоинтов нет. Один `AGENTS.md` на весь репозиторий. Коммиты идут в `main` напрямую (одна ветка).

## Стек

- **Фронтенд:** Astro + npm (Node 24 на сервере). TypeScript 6 (не 7!). Стили: CSS-токены, компоненты `.astro`
- **Бэкенд:** Python 3.10, uv (локально), pip на сервере. SQLite для хранения постов
- **Сборка:** Astro с `NEWS_JSON`, `SITE_URL`, `ASTRO_OUT_DIR`, `SITE_ENV`
- **Хостинг:** Beget Blog (shared), cron раз в час
- **Репозиторий:** GitVerse (приватный), ветки `main` и `dev`

## Архитектура (синк в три стадии)

```
fetch → parse → export
```

1. **fetch:** `wall.get` окна последних постов (VK_WINDOW=50), раз в сутки полная сверка через `wall.getById`
2. **parse:** разбор постов, подсчет хэша (только от показываемого контента), скачивание фото
3. **export:** запись `news.json` для сборки сайта

Сырой JSON поста хранится в SQLite вместе с разобранными полями.

## Структура каталогов

```
pipeline/          Python 3.10 (uv локально, pip на сервере)
    src/pipeline/
        vk/            клиент VK API
        parse/         разбор постов, хэш
        export/        экспорт news.json
        store/         SQLite, миграции
        media/         скачивание и обработка фото
        reconcile.py   сверка с VK
        builds.py      лимит сборок
        run.py         run_sync, backfill
        worker.py      точка входа для cron
        release.py     сборка релиза
        settings.py    настройки
    tests/             pytest (217 passed)
    pyproject.toml

site/              Astro + npm
    src/
        components/    компоненты (blocks/, Modal, PostArticle, etc.)
        layouts/       Base.astro
        lib/           env, news, date, vktext, content, typography
        pages/         index, news/, specialisty/, 404, rss, robots
        styles/        tokens.css, base.css, post.css
    content/           page.json, blocks/<блок>/block.json
    scripts/           prepare-content.ts
    public/            логотип, фавиконки
    astro.config.mjs
    package.json

deploy/            серверные скрипты
    bootstrap.sh       первичная подготовка
    deploy.sh          обновление из main
    run-worker.sh      для cron
    backup-db.sh       бэкап SQLite
    locked.py          блокировка воркера
    crontab.example    строки для CronTab
    htaccess.example   шаблон .htaccess

docs/              документация
    BACKLOG.md         порядок работ
    OPEN-QUESTIONS.md  открытые вопросы
    content-contract.md формат news.json
    pages.md           структура сайта
    HOWTO-change.md    карта правок
    HOWTO-add-content.md как добавить контент
    server.md          инструкция для сервера
    README-for-hosting-admin.md памятка админу
```

## Ключевые технические решения

### Хэш поста
Считается только от того, что показывается на сайте: текст, состав вложений, идентификаторы медиа, поле `edited`. Лайки, просмотры, комментарии, репосты НЕ входят. Изменились только счетчики — сборки нет.

### Удаление постов
- Мягкое: `deleted_at`, физически не удалять до конца срока хранения
- Пост исчезает из экспорта, страниц, sitemap, RSS
- Если снова появился в VK — пометка снимается
- Ошибка VK, пустой ответ, ошибка токена — НЕ считаются удалением
- Защита: если к удалению > max(3, 20% сохраненных) — не применять, SyncError

### Лимит сборок
- `MAX_BUILDS_PER_DAY = 4` — страховка
- При исчерпании — изменения остаются в статусе `pending` в базе
- Собираются первым запуском после смены суток
- Сборка в `releases/<ts>/`, проверки, атомарное переключение `public_html`

### Срок хранения новостей
- `NEWS_RETENTION_DAYS` = 90 (по умолчанию, было 30, изменено 2026-10-27)
- Старые посты удаляются из базы целиком
- Фото, на которое не ссылается ни один пост, удаляется в первом запуске на свежем сайте

### Фото
- Воркер делает WebP-копии: 1600 px (для страницы) и 800 px (для карточки)
- Исходник не хранится (решение Павла 2026-10-25)
- Ориентация впекается, EXIF/GPS чистится
- `news.json` версии 2: у фото поле `preview`

### Даты
- Только абсолютные: «12 октября 2026»
- Часовой пояс `Europe/Simferopol`
- `<time datetime="...+03:00">`
- «Обновлено ...» только если дата правки отличается от даты публикации

### Текст поста
- Экранировать; разметку VK (`[club123|текст]`, хэштеги, ссылки) преобразовывать отдельно (XSS)
- Только http(s) становится ссылкой

### Настройки
- Только через `pipeline.settings.load_settings()`
- Источники: `<каталог данных>/.env` + окружение процесса (второй сильнее)
- Каталог данных: `DOBROMIR_DATA` из окружения или `~/dobromir-data`
- Обязательны: `SITE_ROOT` (абсолютный путь) и `SITE_ENV` (production/staging, без дефолта)
- Ключи VK проверяются в `Settings.vk()`, не при загрузке
- Ключи не попадают в `repr`

### Типографика (site/scripts/prepare-content.ts)
- Фото: WebP до 800 px, без метаданных
- Тексты: пробелы, тире, «ёлочки»
- На сервере и в хуке (`CONTENT_CHECK_ONLY=1`) только проверяет

## Принятые решения (не пересматривать)

- Сайт полностью статичный, входящих эндпоинтов нет
- Только русский язык, без i18n
- Фронтенд на npm (не bun) — на сервере Node 24, bun не документирован
- Синк в три стадии fetch/parse/export с хранилищем между ними
- Сырой JSON поста хранится в SQLite
- Объем: только новости за последние N дней (90 по умолчанию)
- Фото: WebP 1600+800, без исходника
- Видео вне MVP
- MVP — работающий функционал, а не список разделов
- Один `AGENTS.md` на весь репозиторий
- Домен `добромир-крым.рф` без `www`
- Язык: коммиты, комментарии, докстринги — русские. Идентификаторы и имена файлов — английские
- Одна ветка `main`, коммиты напрямую
- Сервер на `main`, обновление через `deploy/deploy.sh`
- Альбомы и галерея исключены (нужна смена хостинга)
- Меню оператора не делаем — документация вместо меню
- Форма обратной связи и багрепорты убраны
- Яндекс.Метрика, комментарии, формы не нужны; SEO нужен
- Фото уже публичны в VK, согласие родителей не ведем
- Репосты показываем
- Оператор: контент добавляется вручную с помощью нейросети
- Правки только у админа на своем устройстве, push в GitVerse
- Роль базы: SQLite — внутренняя кухня воркера, сайт читает `export/news.json`
- Стену читает сервисный ключ насовсем

## Открытые вопросы (OPEN-QUESTIONS)

1. Ключ сообщества не читает стену — решено: сервисный ключ насовсем
2. Содержание страниц — структура принята 2026-10-25
3. Читает ли `astro:assets` фото по внешнему пути — снято
4. Есть ли CI на gitverse — неизвестно
5. Не проверено на хосте: доступность api.vk.com/api.vk.ru/gitverse.ru, CP на сборку, venv/pip в cron, ссылка public_html, .htaccess, срок жизни сервисного ключа, поле edited, максимальный count, закрепленный пост, удаленный пост в wall.getById

## Ловушки (Gotchas)

- TypeScript 7 нельзя — astro check не работает, ESLint падает
- Версии библиотек не хардкодить, кроме TypeScript 6
- Astro съедает пробел перед тегом, если между ними перевод строки — ставить `{" "}`
- `overrides` для `eslint-plugin-jsx-a11y` в package.json
- Репозиторий на gitverse, не на GitHub
- В bash-скриптах переменная перед кириллицей — только `${VAR}`
- Python 3.10 — на хосте Beget Python 3.10.12
- Beget запрещает демоны
- Настройки только через `load_settings()`
- В `.env` не должно быть `~` в путях — только абсолютные
- `SITE_ROOT` и `SITE_ENV` обязательны, без дефолта
- `NEWS_RETENTION_DAYS` по умолчанию 90
- `MAX_BUILDS_PER_DAY` = 4
- `VK_WINDOW` = 50, `VK_PAGE_SIZE` = 100, `VK_BY_ID_BATCH` = 100
- `RECONCILE_AFTER_HOUR` = 3
- `BUILD_TIMEOUT` = 600 (10 мин)
- `YANDEX_VERIFICATION`, `GOOGLE_VERIFICATION` — пусто = тег не выводится
- `NODE_BIN` = `~/opt/node/bin` по умолчанию
- `DEFAULT_SITE_URL` = punycode `добромир-крым.рф`
- `DEFAULT_VK_API_URL` = `https://api.vk.ru/method/`
- `DEFAULT_TZ_NAME` = `Europe/Simferopol`
- `SITE_ENVS` = `("production", "staging")`
- Логи: `RotatingFileHandler`, 5 файлов по 1 МБ
- Локаль на хосте C — bash считает байты UTF-8 частью имени
- Pillow пишет WebP — проверяется в bootstrap.sh и deploy.sh
- `overrides` для `eslint-plugin-jsx-a11y`: `"eslint": "$eslint"`
- TypeScript 6.0.3 последняя 6.x на 2026-10-05
- `typescript-eslint` и `@astrojs/check` не поддерживают TS 7
- Ключи не попадают в `repr` (поле `repr=False`)
- `SITE_ROOT` должен быть абсолютным путем
- `SITE_ENV` без дефолта — ошибка в любую сторону вредна
- `VK_SERVICE_TOKEN` проверяется в `Settings.vk()`, не при загрузке
- `VK_GROUP_ID` проверяется как число без минуса
- `NEWS_RETENTION_DAYS` от 1 до без верхней границы
- `MAX_BUILDS_PER_DAY` от 1
- `RECONCILE_AFTER_HOUR` от 0 до 23
- `BUILD_TIMEOUT` от 30
- `VK_WINDOW` от 1
- `VK_PAGE_SIZE` от 1 до 100
- `VK_BY_ID_BATCH` от 1 до 100
- `SITE_URL` должен начинаться с `https://`
- `TZ_NAME` проверяется через `ZoneInfo`
- `node_bin` по умолчанию `~/opt/node/bin`
- `DataDirs` и `SiteDirs` — frozen dataclasses
- `VkSettings` — token скрыт из repr
- `Store` — класс для работы с SQLite
- `Change` enum: NEW, CHANGED, RESTORED, SAME
- `PhotoRecord` — запись о скачанном фото
- `StoredPost` — пост из базы
- Миграции: `0001_init.sql`, `0002_photo_preview.sql`
- `open_db` — открывает и мигрирует базу
- `expire_posts` — физическое удаление старых постов
- `mark_deleted` — мягкое удаление
- `touch_photos` — отметка фото как используемых
- `forget_photo` — удаление записи о фото
- `photo_info` — информация о фото
- `record_photo` — запись о скачанном фото
- `photo_records` — все записи о фото
- `live_keys` / `live_keys_since` — живые посты
- `counts` — количество живых и удаленных
- `posts` — посты из базы
- `upsert` — запись поста с определением изменения
- `get_meta` / `set_meta` / `delete_meta` — работа с мета-таблицей
- `read_env_file` — парсинг .env файла
- `load_env` — сводит .env и окружение
- `default_data_root` — `~/dobromir-data`
- `load_settings` — читает и проверяет все настройки
