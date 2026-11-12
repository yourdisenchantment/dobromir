# Добромир

Сайт Республиканского центра коррекционной педагогики «Добромир» (Симферополь) -
`добромир-крым.рф`. Главная страница рассказывает о центре, услугах и специалистах,
новости сами приходят из группы [ВКонтакте](https://vk.com/dobromir.crimea).

## Демо

Работающий сайт собирается на Beget и пока не запущен; до запуска центр можно
показывать по демо-адресам. В демо новости - примеры из `site/src/sample/`, все
страницы закрыты от поисковиков (`noindex`). Инструкция - [docs/demo.md](docs/demo.md).

- [GitVerse Pages](https://yourdisenchantment.gitverse.site/dobromir)
- [GitHub Pages](https://yourdisenchantment.github.io/dobromir/)
- [Cloudflare Pages](https://dobromir.pages.dev)

## Как это работает

- **`site/`** - статичный сайт на [Astro](https://astro.build/). Тексты, блоки главной и
  специалисты лежат в JSON-файлах `site/content/`, новости - в `news.json`.
- **`pipeline/`** - воркер на Python. Cron на хостинге запускает его раз в час: он
  забирает новые и измененные посты из VK, хранит их в SQLite, качает фото, пишет
  `news.json` и, если что-то изменилось, собирает и включает новую версию сайта. Новости
  хранятся за последние 90 дней.
- **`deploy/`** - скрипты для хостинга Beget (shared, без фоновых процессов).

Сайт не загружает ничего с чужих серверов, на нем нет форм, комментариев и счетчиков.

## Быстрый старт

Нужны Node.js 24 (npm), для воркера - Python 3.10 и [uv](https://docs.astral.sh/uv/).

```bash
cd site
npm ci
npm run dev        # http://localhost:4321/, новости - из примера site/src/sample/
```

Сборка - `npm run build`, результат в `site/dist/`. Воркер, проверки и хуки - в
[CONTRIBUTING.md](CONTRIBUTING.md).

## Документация

| Что нужно | Где |
|---|---|
| Поменять тексты, блоки, специалистов, телефоны (без программирования) | [docs/HOWTO-add-content.md](docs/HOWTO-add-content.md) |
| Поменять код: какой файл за что отвечает | [docs/HOWTO-change.md](docs/HOWTO-change.md) |
| Демо-адреса для показа и как их включить | [docs/demo.md](docs/demo.md) |
| Как предложить правку, проверки, коммиты | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Правила работы и принятые решения (главный документ, в том числе для нейросетей) | [AGENTS.md](AGENTS.md) |
| Страницы и блоки сайта | [docs/pages.md](docs/pages.md) |
| Формат `news.json` | [docs/content-contract.md](docs/content-contract.md) |
| Памятка для того, кто следит за хостингом (без технических знаний) | [docs/README-for-hosting-admin.md](docs/README-for-hosting-admin.md) |
| План и обоснования решений | [plan-razrabotki.md](plan-razrabotki.md) |
| Порядок работ и открытые вопросы | [docs/BACKLOG.md](docs/BACKLOG.md), [docs/OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md) |

## Связь

Вопросы и ошибки - задача (issue) в репозитории. Уязвимости - не в задачу, а по
[SECURITY.md](SECURITY.md). Почта: mpave@duck.com.

## Лицензия

См. [LICENSE](LICENSE). Шрифт Inter - SIL Open Font License (`site/src/assets/fonts/OFL.txt`),
иконки Material Symbols - Apache 2.0 (`site/src/assets/icons/LICENSE`).
