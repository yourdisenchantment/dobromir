# Где что менять

Карта для правок кода: «хочу изменить X - вот файл, вот что обновить рядом, вот чем
проверить». Для человека и для нейросети одинаково. Если работаете с нейросетью - дайте
ей этот файл вместе с `AGENTS.md`.

Тексты, блоки главной, специалисты, телефоны - это не код, они описаны отдельно:
[HOWTO-add-content.md](HOWTO-add-content.md). Начинайте с него: большая часть правок
сайта делается там, без программирования.

## Как устроено

```txt
группа VK --(cron раз в час)--> pipeline/ (Python) --> SQLite --> news.json + фото
                                                                      |
site/content/ (ручное: блоки, специалисты) ---------> site/ (Astro) --+--> releases/<время>/
                                                                      |
                                                 public_html -> текущий релиз
```

- `pipeline/` - воркер: забирает посты из VK, хранит в SQLite, пишет `news.json`, качает
  фото, собирает и включает релиз сайта.
- `site/` - сам сайт: статичные страницы из `site/content/` и `news.json`.
- `deploy/` - скрипты для хостинга Beget.
- Связь между ними - только файл `news.json`, его формат - [content-contract.md](content-contract.md).

## Сайт: внешний вид

| Хочу изменить | Где | Что еще обновить |
|---|---|---|
| Цвет, размер шрифта, отступы, скругления, ширину страницы | `site/src/styles/tokens.css` - единственное место цветов и размеров | проверить контраст текста (в комментариях у цветов указан), посмотреть стайлбук `/stylebook/` |
| Общие правила: ссылки, заголовки, «черепица» `.masonry`, фокус | `site/src/styles/base.css` | - |
| Шрифт | `site/src/assets/fonts/` и `site/src/styles/fonts.css` | лицензия шрифта рядом с файлами |
| Иконку (новую или другую) | файл `<имя>.svg` (Material Symbols, стиль Rounded, с fonts.google.com/icons) в `site/src/assets/icons/`; встраивает `src/lib/icons.ts`, выводит `components/Icon.astro` | список иконок в `docs/content/facts.md` |
| Логотип, фавиконки | `site/public/` | вырезать метаданные (C2PA, EXIF) перед тем, как класть |
| Шапку, меню, порог «Меню» под кнопкой | `site/src/components/SiteHeader.astro` | пункты меню - не здесь, а полем `menu` у блока (`docs/content/menu-and-order.md`) |
| Подвал | `site/src/components/SiteFooter.astro` | адрес и телефоны - не здесь, а в блоке `contacts` |
| Кнопку «Наверх» | `site/src/components/ToTop.astro` | - |
| Карточку (рамка фото, текст, ссылка) | `site/src/components/Card.astro` | - |
| Карусель (новости, специалисты, отзывы) | `site/src/components/Carousel.astro` | `docs/pages.md` |
| Всплывающее окно карточки | `site/src/components/Modal.astro` | - |
| Вид одного блока главной | `site/src/components/blocks/<Тип>Block.astro`; цифры - `components/Facts.astro`, специалисты - прямо в `src/pages/index.astro` | `docs/pages.md` |
| Общую обертку страницы: `<head>`, мета-теги, подключение стилей | `site/src/layouts/Base.astro` | - |

## Сайт: содержимое и страницы

| Хочу | Где | Что еще обновить |
|---|---|---|
| Новое поле у существующего блока | схема блока в `site/src/lib/content.ts` (`z.strictObject`: без записи в схеме поле - ошибка сборки), затем компонент блока | документ раздела в `docs/content/` (таблица полей), `docs/pages.md` |
| Новый тип блока | 1) схема в `content.ts` и в общем списке типов (там же текст ошибки «неизвестный тип блока»); 2) компонент `site/src/components/blocks/<Тип>Block.astro`; 3) строка выбора в `site/src/pages/index.astro`; 4) пример `block.json` в `site/content/blocks/` | `HOWTO-add-content.md` (таблица разделов), новый `docs/content/<раздел>.md`, `docs/pages.md` |
| Что сборка доводит в содержимом сама: размер и качество фото, какие форматы принимает | `site/scripts/prepare-content.ts` (`MAX_SIDE`, `QUALITY`, `SOURCES`; первый шаг `npm run build`, режим проверки - `--check` и `CONTENT_CHECK_ONLY=1` на сервере) | `docs/content/specialists.md`, `HOWTO-add-content.md` («Что сборка делает сама»); исходники фото в `.gitignore` |
| Правила типографики (пробелы, тире, кавычки) и поля, которые она не трогает | `site/src/lib/typography.ts` (`RAW_KEYS` - ссылки, телефоны, имена файлов) | тест `typography.test.ts`, `HOWTO-add-content.md` |
| Новую страницу | файл в `site/src/pages/` (адрес = путь, со слэшем в конце) | попадет в sitemap сама; ссылку на нее - в шапку или подвал |
| Страницу специалиста | `site/src/pages/specialisty/[slug].astro`, `components/SpecialistArticle.astro` | - |
| Архив и страницу новости | `site/src/pages/news/index.astro`, `news/[slug].astro`, `components/PostArticle.astro`, `PostContent.astro` (фото, ссылки, документы), общие классы - `styles/post.css` | - |
| Как текст поста из VK превращается в абзацы и ссылки (`[club1\|текст]`, хэштеги) | `site/src/lib/vktext.ts` - здесь же защита от XSS (`safeHref`: только http/https) | тест `vktext.test.ts` |
| Заголовок и выдержку карточки новости | на сайте - `site/src/lib/news.ts` (`displayTitle`, `summary`, `newsCard`) и `cardtext.ts`; сам заголовок придумывает воркер - `make_title` в `pipeline/src/pipeline/parse/posts.py` | тесты `cardtext.test.ts`, `pipeline/tests/test_parse.py` |
| Формат даты | `site/src/lib/date.ts` (только абсолютные даты, пояс Europe/Simferopol) | тест `date.test.ts` |
| SEO: заголовок, описание, canonical, `noindex` для тестовой копии | `site/src/layouts/Base.astro`, адрес сайта - `SITE_URL` (`site/astro.config.mjs`) | - |
| `robots.txt`, RSS | `site/src/pages/robots.txt.ts`, `rss.xml.ts` | - |
| Редиректы со старого сайта | `deploy/htaccess.example` | тест `site/src/lib/redirects.test.ts` |

## Воркер (`pipeline/`)

| Хочу | Где | Что еще обновить |
|---|---|---|
| Новую настройку (переменную окружения) | `pipeline/src/pipeline/settings.py` | **сразу** `.env.example` и тест в `tests/test_settings.py` (правило `AGENTS.md`) |
| Срок хранения новостей, окно, лимит сборок | значения по умолчанию - `settings.py`; на сервере - `~/dobromir-data/.env` | `.env.example`, `docs/README-for-hosting-admin.md`, если меняется поведение |
| Запросы к VK, повторы, ошибки ключа | `pipeline/src/pipeline/vk/client.py` | `tests/test_vk_client.py`; ключ и адреса с ключом не должны попасть в лог |
| Какие посты считаются новостями, разбор полей, репосты | `pipeline/src/pipeline/parse/posts.py`, модель - `parse/model.py` | `tests/test_parse.py` |
| Что входит в хэш (от него зависит, будет ли сборка) | `pipeline/src/pipeline/parse/hash.py` - только то, что видно на сайте; лайки и просмотры не входят | `tests/test_hash.py` |
| Окно, суточная сверка, удаления, защита от массового удаления | `pipeline/src/pipeline/reconcile.py` | `tests/test_reconcile.py` |
| Порядок одного запуска (первичная загрузка, окно, сверка, фото, `news.json`, решение о сборке) | `pipeline/src/pipeline/run.py` | `tests/test_reconcile.py`, `test_worker.py` |
| Коды выхода, текст писем об ошибках, `status.json`, лог | `pipeline/src/pipeline/worker.py` | `tests/test_worker.py`, **`docs/README-for-hosting-admin.md`** (она описывает эти письма) |
| Формат `news.json` | `pipeline/src/pipeline/export/news.py` и чтение на сайте `site/src/lib/news.ts` - всегда вместе | `docs/content-contract.md`, пример `site/src/sample/news.example.json` |
| Обработку фото (размеры WebP, чистка метаданных) | `pipeline/src/pipeline/media/photos.py`; удаление ненужных - `media/cleanup.py` | `tests/test_media_cleanup.py` |
| Структуру базы | **новый** файл `pipeline/src/pipeline/store/migrations/NNNN_что.sql` (следующий номер); старые миграции не править - на сервере они уже применены | код в `store/state.py`, `tests/test_store.py` |
| Сборку релиза, проверки релиза, переключение и откат | `pipeline/src/pipeline/release.py` | `tests/test_release.py` |
| Команду `python -m pipeline ...` | `pipeline/src/pipeline/__main__.py` | список команд в `AGENTS.md` (раздел «Статус»), `tests/test_cli.py` |
| Зависимость Python или npm | `pipeline/pyproject.toml` / `site/package.json` - порядок и ловушки в `AGENTS.md` («Ловушки») и `docs/dependencies.md` | lock-файл в том же коммите; для сервера заново породить `pipeline/requirements.txt` |

## Сервер (`deploy/`)

| Хочу | Где | Что еще обновить |
|---|---|---|
| Первичную подготовку хостинга | `deploy/bootstrap.sh` (без `--apply` только проверяет) | `docs/README-for-hosting-admin.md` |
| Выкладку новой версии | `deploy/deploy.sh <тег>` | то же |
| Расписание cron | `deploy/crontab.example` (сами строки вставляются в панели Beget) | `AGENTS.md` («Воркер и сервер») |
| Резервную копию базы | `deploy/backup-db.sh`, `pipeline/src/pipeline/backup.py` | `tests/test_backup.py` |
| Раскладку каталогов на сервере | `deploy/*.sh` и `settings.py` вместе | `AGENTS.md` («Раскладка на сервере»), README для администратора |

## После любой правки

1. Проверки (команды - `AGENTS.md`, раздел «Команды»):
   - `pipeline/`: `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy`, `uv run pytest`;
   - `site/`: `npm run lint`, `npm run format:check`, `npm run check`, `npm test`, `npm run build`.
2. Посмотреть глазами: `npm run dev` в `site/`. Сборка не видит склеенных слов и съехавшей
   верстки (ловушка с пробелом перед тегом - `AGENTS.md`).
3. Обновить документ из колонки «Что еще обновить». Новое решение - записать в
   `AGENTS.md` или `plan-razrabotki.md` с датой и причиной.
4. Коммит - по правилам [CONTRIBUTING.md](../CONTRIBUTING.md).

## Чего не делать

- Не класть в репозиторий ключи VK, базу, ответы VK и фото из группы: это данные о детях,
  они живут вне репозитория: в `$DOBROMIR_DATA` (по умолчанию `~/dobromir-data`) и в
  `<SITE_ROOT>/media`.
- Не грузить на сайт ничего с чужих серверов (шрифты, иконки, счетчики): все лежит в проекте.
- Не поднимать TypeScript до 7 (`AGENTS.md`, «Ловушки»).
- Не запускать на хостинге фоновые процессы: Beget разрешает только короткие запуски из cron.
