# Демо сайта

Боевой сайт собирается на Beget и запускается отдельно; здесь описаны три
демо-адреса для показа заказчику. В демо новости - примеры из
`site/src/sample/news.example.json` (настоящие данные VK не нужны), сборка идет с
`SITE_ENV=staging`, поэтому все страницы демо имеют `noindex, nofollow` и закрыты
от поисковой индексации. Ничего из этого не затрагивает деплой на Beget.

| Платформа | Адрес | Как обновляется |
|---|---|---|
| [GitVerse Pages](https://yourdisenchantment.gitverse.site/dobromir) - основная | `yourdisenchantment.gitverse.site/dobromir` | Само, на каждый push в `main` |
| [GitHub Pages](https://yourdisenchantment.github.io/dobromir/) | `yourdisenchantment.github.io/dobromir/` | На push в зеркальный репозиторий GitHub |
| [Cloudflare Pages](https://dobromir.pages.dev) | `dobromir.pages.dev` | На push в зеркальный репозиторий GitHub |

GitVerse и GitHub публикуют сайт проекта по подпапке `/dobromir` (путь в поддомене
равен имени репозитория): подпапку для сборки задает `SITE_BASE`. Cloudflare отдает
демо из корня своего поддомена, поэтому там `SITE_BASE` не нужен.

## Зеркальный репозиторий GitHub

Cloudflare Pages и GitHub Actions подключаются только к GitHub и GitLab, поэтому
зеркальный репозиторий нужен только ради этих сборок; GitVerse остается единственным
местом правок, боевой деплой на Beget не меняется.

1. создать пустой публичный репозиторий `dobromir` на GitHub. Публичность нужна:
   GitHub Pages бесплатно работает только в публичных репозиториях, а код и так
   открыт в GitVerse - зеркалом ничего не раскрываем нового;
2. добавить remote и отправить один раз:

   ```bash
   cd ~/projects/dobromir
   git remote add github git@github.com:yourdisenchantment/dobromir.git
   git push github main
   ```

3. дальше после каждого `git push` в GitVerse повторять `git push github main`.

Промежуточная проверка: `git fetch github` не должен показывать расхождение
с `origin/main`.

## GitVerse Pages

1. Push в `main` с `.gitverse/workflows/pages.yml`.
2. Репозиторий GitVerse: **Настройки -> Страницы -> Источник -> Воркфлоу**.
3. Workflow **Demo Pages** запустится на push или вручную (`workflow_dispatch`).

Пока источник не переключен на **Воркфлоу**, шаг `deploy-pages` отдает ошибку.

## GitHub Pages

1. Push в зеркальный репозиторий GitHub с `.github/workflows/pages.yaml`.
2. В GitHub: **Settings -> Pages -> Build and deployment -> Source: GitHub Actions**.
3. Workflow **Demo on GitHub Pages** запустится после следующего `git push github main`.

Адрес: `https://yourdisenchantment.github.io/dobromir/` - `SITE_BASE=/dobromir`
у этой сборки. GitHub Pages бесплатно работает в публичных репозиториях: зеркальный
репозиторий оставлять публичным, это не открывает ничего нового против GitVerse.

## Cloudflare Pages

1. Cloudflare Dashboard: **Workers & Pages -> Create -> Pages -> Connect to Git**.
2. Выбрать GitHub-репозиторий `dobromir`.
3. Настройки: Project name `dobromir`, Production branch `main`,
   Root directory `/site`, Build command `npm ci && npm run build`,
   Build output directory `dist`, Branch deployments включены.
4. Environment variables (Production и Preview):
   - `NODE_VERSION` = `24`;
   - `SITE_ENV` = `staging`;
   - `SITE_URL` = `https://dobromir.pages.dev`;
   - `ASTRO_TELEMETRY_DISABLED` = `1`.

`SITE_BASE` здесь не задавать: Cloudflare отдает сайт из корня своего поддомена.
Адрес появится после первого деплоя: `https://dobromir.pages.dev`.

## Снятие с публикации

- GitVerse: **Настройки -> Страницы -> выключить Pages**.
- GitHub: **Settings -> Pages** - «unpublish site» либо удалить workflow.
- Cloudflare: удалить проект `dobromir` (Settings -> Delete project).

Все эти действия не затрагивают боевой сайт на Beget и ветку `main`.
