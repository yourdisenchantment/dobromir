# Справочник по VK API для группы «Добромир» (vk.com/dobromir.crimea)

Составлено 2026-10-06 по официальной документации dev.vk.ru (страницы методов, объектов, access-token, versions, errors). Код не писался, запросов к API не делалось (токена нет). Всё ниже - то, что написано в документации, а не проверено на живой группе.

Как читать пометки:
- **[док]** - прямо написано на странице метода/раздела.
- **[?]** - не нашли в документации или страница отдала противоречие; нужно проверить спайком.

Ограничение метода работы: страницы читались через WebFetch, который отдаёт пересказ, а не сырой текст, а на сайте висел баннер «Технические работы». Поэтому цифры вроде `count max` и списки токенов стоит перепроверить глазами по ссылкам в конце.

---

## 1. Общее

| Что | Значение |
|---|---|
| Хост | `https://api.vk.ru/method/<метод>` [док] |
| Передача токена | заголовок `Authorization: Bearer <ключ>` [док] |
| Версия API | параметр `v` обязателен; последняя по странице versions - **5.199** (в 5.199 изменений методов нет) [док]. В примере quick start стоит 5.131. Рекомендация: явно слать `v=5.199` и зафиксировать в settings |
| Формат | JSON, ответ в `response`, ошибка в `error` |
| Лимит по объёму | **С 7 сентября 2026**, на один аккаунт в «Кабинете для бизнеса VK ID»: без верификации бизнес-профиля **10 000 вызовов в месяц**, после верификации 100 000 000; выше - письмо на devsupport@corp.vk.com [док]. Дата уже наступила - это главный практический лимит для нас |
| Лимит в секунду | [док, api/api-requests] пользовательский ключ **3 запроса/сек**, ключ сообщества **20/сек**, сервисный ключ **5-60/сек** (зависит от числа пользователей приложения). Превышение - ошибка 6 |
| Запрос | GET и POST равнозначны; `Content-Type` form-urlencoded (до 2 КБ) или multipart; **JSON-тело не поддерживается**; необязательные `lang` (ru, uk, be, en, es, fi, de, it) и `test_mode=1` [док] |
| `execute` | Страница метода есть, допустим **только пользовательский ключ**, лимит вызовов внутри не указан [док]. Для сервисного ключа ускорять через `execute` нельзя |

### Что значит 10 000 вызовов в месяц для нас

Один вызов `wall.get` отдаёт до 100 постов. Стена на 5 000 постов - 50 вызовов. Фото: неизвестно, сколько их; `photos.get` с `count` ~1000 [?] - единицы вызовов на альбом. Полная первичная выкачка помещается в лимит с большим запасом, дельта-синки раз в сутки тоже (≈ 30-100 вызовов в месяц). Опасное место - комментарии и лайки по каждому посту (по вызову на пост), их брать только если реально нужны.

## 2. Типы токенов

| Токен | Кто | Срок | Где можно | Как получить |
|---|---|---|---|---|
| **Сервисный ключ** | приложение (игра/мини-приложение/Standalone) | не ограничен [док] | только сервер, не светить [док] | настройки приложения, поле «Сервисный ключ доступа» [док по спайку, на странице access-token деталей не видели] |
| **Ключ сообщества** | сообщество | не ограничен [док] | клиент или сервер | админ группы: Управление → Работа с API → Ключи доступа [док] |
| **Ключ пользователя** | пользователь | **1 час** [док] | клиент или сервер | OAuth 2.1 через VK ID. Authorization Code Flow и Implicit Flow для пользовательских токенов **отключены 25.06.2024**, ранее выданные бессрочные продолжают жить [док] |

Права доступа (scopes) пользовательского токена по странице access-rights [док]:
- «доступны всем»: `friends, photos, video, stories, pages, menu, status, notes, wall, docs, groups, notifications, email` и др.;
- «только через запрос в поддержку»: `messages, ads, offline, stats, market, phone`.

**Противоречие в документации [?]:** на страницах методов (`video.get`, `docs.get`, `market.get`, `wall.getComments`, `photos.getAll`, `pages.get`) право `wall/video/photos/docs/market/pages/groups/stories` названо «выдаётся в исключительных случаях через запрос в поддержку», хотя на странице access-rights эти права в списке «доступны всем». Считаем, что реально пользовательский токен с этими правами получить трудно. Это ещё одна причина строить всё на сервисном ключе.

Права ключа сообщества [док]: `stories, photos, app_widget, messages, docs, manage`. Метод `groups.getTokenPermissions` покажет, что именно выдано конкретному ключу.

## 3. Таблица методов

Столбцы токена: **С** - сервисный, **К** - сообщества, **П** - пользовательский. «+» - указан в документации как допустимый, «-» - не указан. Права для П - в примечании.

### 3.1 Информация о группе

| Метод | Что даёт | С | К | П | Лимиты / нюансы |
|---|---|---|---|---|---|
| `groups.getById` | Поля группы: `activity, ban_info, can_post, can_see_all_posts, city, contacts, counters, country, cover, description, finish_date, fixed_post, links, market, members_count, place, site, start_date, status, verified, wiki_page` | + | + | + | до **500** групп за запрос; часть полей требует права `groups` [док]. В объекте группы есть ещё `main_album_id, main_section, wall, age_limits, addresses, is_closed, type, photo_50/100/200, crop_photo` [док] |
| `groups.getMembers` | Список участников, фильтры `friends, unsure, managers, donut, unsure_friends, invites`, до 27 полей профиля | + | + | + | `count` ≤ **1000** (по умолчанию 1000) [схема]; `managers` и сортировка по времени только с токеном админа/модератора [док]; ошибка 125 - неверный ID |
| `groups.getAddresses` | Адреса, координаты, контакты, **расписание** (`timetable`: open_time/close_time/break по дням в минутах) | + | - | + | `count` по умолчанию 10, максимум не указан [?]; ошибки 125, 260 |
| `groups.getTagList` | Метки сообщества | - | + | + (право `groups`) | |
| `groups.getBanned` | Чёрный список | - | + | + (право `groups`) | служебное, для сайта не нужно |
| `groups.get` | Группы пользователя | + | - | + | до 1000; нам не нужно |
| `groups.getTokenPermissions` | Что разрешено ключу сообщества | - | + | - | полезно проверить ключ |
| `groups.getCatalogInfo` | Каталог сообществ | - | - | + | не для нас |
| `groups.getInvites`, `getInvitedUsers`, `getRequests`, `getOnlineStatus`, `getLongPollServer`, `getCallbackSettings` и др. | Админские/событийные | [?] | [?] | [?] | управление, не данные; не проверяли |
| `utils.resolveScreenName` | `dobromir.crimea` → числовой id и тип | + | + | + | для получения `group_id` |

Чего нет как отдельных методов [док по списку методов]: меню группы (есть только поле `main_section` и `menu` как право пользователя), контакты (поле `contacts` в `getById`), ссылки (`links`). Отдельных методов `articles.*`, `clips.*`, `events.*`, `playlists.*`, `audio.*` в актуальном списке методов **нет** (есть только `podcasts.searchPodcast`). События - это группы с `type=event`. Клипы и статьи доступны только как вложения постов (см. 3.2).

### 3.2 Стена

| Метод | Что даёт | С | К | П | Лимиты / нюансы |
|---|---|---|---|---|---|
| `wall.get` | Посты, `domain` или `owner_id=-<id>`; `filter`: `all, owner, others, suggests, postponed, donut` | + | **-** | + | `count` ≤ **100** [док и схема], `offset`; `extended=1` добавляет `profiles`, `groups`; ошибка 19 «контент заблокирован» [док]. Закреп приходит первым вне порядка дат |
| `wall.getById` | Посты по `owner_id_post_id` | + | - | + | до **100** id; `copy_history_depth` задаёт глубину репостов; ошибка 104 |
| `wall.search` | Поиск по стене | + | - | + | `count` ≤ 100, запрос ≤ 9000 символов |
| `wall.getComments` | Комментарии к посту, ветки (`thread_items_count`) | + | - | + (право `wall`) | `count` ≤ **100**; `start_comment_id`, `sort`, `need_likes`, `extended` |
| `wall.getComment` | Один комментарий | [?] | [?] | [?] | не проверяли |
| `wall.getReposts` | Кто репостнул | + | - | + | `count` 20 по умолчанию, ≤ **1000** [схема] |
| `likes.getList` | Кто лайкнул пост/фото/видео/комментарий/товар | + | - | + | `count` ≤ **1000** (100 при `friends_only`); `type`: post, comment, photo, video, note, market и др. |

Поля поста [док по reference/objects/post]: `id, owner_id, from_id, created_by, date, text, attachments, geo, comments, likes, reposts, views, post_type (post/copy/reply/postpone/suggest), is_pinned, marked_as_ads, is_favorite, copy_history, donut, postponed_id, signer_id`. Типы вложений: фото, видео, аудио, документ, ссылка, опрос, wiki-страница, альбом, товар, **статья, подкаст, клип** [док]. Поле `edited` в справочнике не описано [?], в реальных ответах обычно есть [?]. Страницу с подробной структурой вложений (`reference/objects/attachments-post`) открыть не удалось (404) - структуру каждого типа проверять на живых ответах.

### 3.3 Фото и альбомы

| Метод | Что даёт | С | К | П | Лимиты / нюансы |
|---|---|---|---|---|---|
| `photos.getAlbums` | Альбомы: `id, title, description, created, updated, size, thumb_id`, `need_covers=1` даёт `thumb_src`, `need_system=1` системные | + | - | + | `count` без максимума [схема]; поля приватности только для админа [док] |
| `photos.get` | Фото альбома; `album_id` числом или `wall`, `profile`, `saved`(только П); `rev`, `extended` (лайки, комменты, репосты), `photo_sizes=1` | + | **-** | + | `count` ≤ **1000**, по умолчанию 50 [схема]; `offset` |
| `photos.getAll` | Все фото владельца разом | - | - | + только с правом `photos` по запросу в поддержку | `count` 20 по умолчанию, ≤ **200** [схема]; отдаёт новые сначала |
| `photos.getById` | Фото по `owner_photo`; для закрытых нужен `access_key` | + | - | + | до **500** фото за запрос [схема] |
| `photos.getComments` | Комментарии к фото | - | - | + (право `photos` по поддержке) | `count` 20 по умолчанию, ≤ **100** [схема] |
| `photos.getAlbumsCount` | Число альбомов | [?] | [?] | [?] | не проверяли |

Объект фото [док]: `id, album_id, owner_id, user_id (100 для постов от имени группы), text, date, has_tags, sizes[] (type,url,width,height), width, height, thumb_hash`; при локации `lat`/`long`. Типы размеров [док, reference/objects/photo-sizes]: `s` 75px, `m` 130px, `x` 604px, `y` 807px, `z` до 1080x1024, `w` до **2560x2048** (все пропорциональные по большей стороне); `o, p, q, r` - 130/200/320/510px с обрезкой до 3:2 для широких. Значит максимум, который отдаёт VK, - `w` 2560x2048, и «оригинал» на сайте будет именно им (если `w` есть у фото; поле `orig_photo` в документации не нашли [?]).

### 3.4 Видео

| Метод | Что даёт | С | К | П | Лимиты / нюансы |
|---|---|---|---|---|---|
| `video.get` | Видео владельца/альбома: `player`, превью, просмотры, лайки; в схеме есть `files` (mp4_144...mp4_2160) | **-** | **-** | + только с правом `video` | `count` 100 по умолчанию, ≤ **200**, «может вернуться меньше» [док, схема]. **Сервисный и сообщества ключи не допустимы** [страница метода и схема совпадают] |
| `video.getAlbums` | Альбомы видео | - | - | + (право `video`, по поддержке) | `count` ≤ **100**, по умолчанию 50 |
| `video.getComments` | Комментарии к видео | [?] | [?] | [?] | не проверяли |
| `video.search` | Поиск | [?] | [?] | [?] | не проверяли |

Объект видео [док, reference/objects/video]: `id, owner_id, title, description, duration, image[], first_frame[], player, width, height, type, date, adding_date, platform, access_key, views, local_views, comments, likes, reposts, live, live_status, live_start_time, can_*`. Полей с mp4-файлами в документации **нет**: есть только `player` (страница с плеером). Скачать видео через API нельзя, только встроить плеер. Срок жизни ссылок на видео и превью в документации не указан [?].

### 3.5 Прочее содержимое

| Метод | Что даёт | С | К | П | Лимиты / нюансы |
|---|---|---|---|---|---|
| `board.getTopics` | Обсуждения: темы, закреп первым, превью первого/последнего сообщения | + | - | + (`groups` для закрытых групп) | `count` ≤ **100** (по умолчанию 40), `topic_ids` ≤ 100 |
| `board.getComments` | Сообщения в теме | + | - | + | `count` ≤ **100** (по умолчанию 20), `start_comment_id`, `sort` |
| `docs.get` | Документы группы | - | - | + (право `docs` по поддержке) | `count` ≤ **2000**, `offset` ≤ 1999 |
| `market.get` | Товары/услуги | - | - | + (право `market` по поддержке) | `count` ≤ **200** (по умолчанию 100) |
| `market.getAlbums` | Подборки товаров | - | - | + (`market` по поддержке) | `count` 50 по умолчанию, ≤ **100** [схема] |
| `market.getById`, `getComments`, `getCategories`, `getCommunityReviews` | Товар, отзывы | [?] | [?] | [?] | не проверяли |
| `stories.get` | Актуальные истории | - | + (право `stories`) | + (право `stories`) | истории живут ограниченное время (24 ч - общее знание, в документации не нашли [?]); сервисный не указан |
| `pages.get` | Wiki-страницы | - | - | + (право `pages` по поддержке) | `need_html=1`, `need_source=1` (с проверкой админских прав) |
| `status.get` | Статус | [?] | [?] | [?] | для группы статус лежит в поле `status` объекта группы |
| `donut.*` | Платные подписки | [?] | [?] | [?] | не нужно |
| `stats.get`, `stats.getPostReach` | Статистика | [?] | [?] | [?] | право `stats` по поддержке; статистику группы можно смотреть и в самом ВК |
| `newsfeed.*`, `search.getHints` | Лента, поиск | [?] | [?] | [?] | не нужно |

## 4. Что реально можно вытащить без особых прав (сервисный ключ)

Подтверждено документацией, что сервисный ключ допустим:
- группа: `groups.getById`, `groups.getMembers`, `groups.getAddresses` (адреса + расписание), `utils.resolveScreenName`;
- стена: `wall.get`, `wall.getById`, `wall.search`, `wall.getComments`, `wall.getReposts`, `likes.getList`;
- фото: `photos.getAlbums`, `photos.get`, `photos.getById`;
- обсуждения: `board.getTopics`, `board.getComments`.

Только пользовательским ключом с правом (из документации - «по запросу в поддержку»): видео (`video.*`), документы (`docs.get`), товары (`market.*`), wiki-страницы (`pages.get`), `photos.getAll`, `photos.getComments`, `groups.getTagList/getBanned`.

Только ключом сообщества: `groups.getTokenPermissions`, истории (при праве `stories`).

Вывод для сайта: **посты, альбомы, фото, обсуждения, контакты, адреса, расписание, описание, ссылки, обложка** - достижимы одним сервисным ключом. **Видео, документы, товары/услуги, wiki, комментарии к фото** - потребуют пользовательский токен с правами, а это (см. раздел 2) сейчас тяжело получить.

## 5. Рекомендация по токену

1. **Создать приложение и взять сервисный ключ** (Standalone-приложение, настройки → «Сервисный ключ доступа»; приложения теперь привязаны к аккаунту в «Кабинете для бизнеса VK ID» [?]). Это основной токен: бессрочный, не привязан к личному аккаунту, закрывает всё из пункта 4. Права выдавать не нужно, их у сервисного ключа нет.
2. **Дополнительно выпустить ключ сообщества** (Управление → Работа с API → Ключи доступа) с правами `photos, docs, stories` (из доступных: `stories, photos, app_widget, messages, docs, manage`). `messages`, `manage`, `app_widget` не выдавать: они нужны для бота/управления, на сайте не нужны. Польза ключа - в основном `groups.getTokenPermissions`, `stories.get` и как запасной вариант для `groups.getById/getMembers`. Для `wall.get` и `photos.get` ключ сообщества по документации **не подходит**, что совпадает с замечанием из спайка.
3. **Пользовательский токен админа** - только если понадобятся видео, документы, товары. Учитывать: токен живёт 1 час, Implicit Flow закрыт, получение идёт через OAuth 2.1 / VK ID; нужные права могут потребовать письма на devsupport@corp.vk.com. Не делать до результатов спайка.
4. **Верификация бизнес-профиля** в Кабинете для бизнеса VK ID нужна только если 10 000 вызовов/мес окажется мало (по расчёту из раздела 1 - не окажется).

Токены: только в `VK_TOKEN` в окружении, не в чат и не в репозиторий (как и в `tmp/OVERVIEW.md`).

## 6. Что проверить спайком (и что менять в `spike/README.md`)

1. Работает ли сервисный ключ на `wall.get`, `photos.get`, `photos.getAlbums`, `board.getTopics`, `groups.getAddresses` для открытого паблика `dobromir.crimea` (получить `group_id` через `utils.resolveScreenName`).
2. Пробный вызов `video.get` с сервисным ключом: по странице метода и схеме он недоступен (ожидаем ошибку 7/15/27). Видео брать из вложений постов и через `video.getOembed`.
3. Максимумы `count` теперь известны из схемы (см. 8.2): `photos.get` 1000, `groups.getMembers` 1000, `wall.get` 100; проверить только, что живой API так отвечает.
4. Есть ли у реальных фото размер `w` (2560) и поле `orig_photo`.
5. Срок жизни URL картинок: в документации не нашли. Предположение (не проверено): ссылки вида `sun*.userapi.com/...?...&sign=...` могут протухать, поэтому скачивать фото сразу при синке - решение плана остаётся в силе.
6. Сколько всего вызовов тратит полный синк (в рамки 10 000 в месяц).
7. Поведение закрепа (`is_pinned`, `fixed_post` в `groups.getById`), поле `edited`, вложения-клипы и статьи в постах, `copy_history`.
8. Расписание: есть ли у паблика адреса и `timetable`.

Замечание к `spike/README.md` (не менял, файл не мой): пункт 3 «пользовательский токен с `wall,photos`» по новой документации выполнить сложнее, чем там написано, а пункт «ключ сообщества пробуем вторым» стоит поставить после сервисного ключа, как уже и сделано. Хост для скрипта должен быть `api.vk.ru`, токен - в заголовке `Authorization`.

## 7. Источники (dev.vk.ru)

- /ru/api/overview, /ru/api/getting-started, /ru/api/access-token/getting-started
- /ru/reference/access-rights, /ru/reference/versions, /ru/reference/errors
- /ru/method (список) и страницы методов: groups.getById, groups.getMembers, groups.getAddresses, groups.get, groups.getTagList, groups.getBanned, groups.getTokenPermissions, groups.getCatalogInfo, wall.get, wall.getById, wall.search, wall.getComments, wall.getReposts, likes.getList, photos.get, photos.getAlbums, photos.getAll, photos.getById, photos.getComments, video.get, video.getAlbums, board.getTopics, board.getComments, docs.get, market.get, market.getAlbums, stories.get, pages.get, utils.resolveScreenName
- /ru/reference/objects/post, group, photo, photo-sizes, video; /ru/method/execute

Не открылись или не проверялись: /ru/reference/objects/attachments-post (404), `wall.getComment`, `video.getComments`, `market.getById`, `stats.*`, `donut.*`, `newsfeed.*`.

---

## 8. Дополнение от 2026-10-07: официальная JSON-схема и обход справочника

### 8.1 Машиночитаемая схема есть

Репозиторий `github.com/VKCOM/vk-api-schema` (лицензия MIT), схема помечена **версией API 5.199**, JSON Schema draft-07, на dev.vk.ru ссылка на неё есть на странице /ru/reference/json-schema. Клонировался без проблем (`git clone --depth 1`). Файлы лежат по папкам-разделам, единый `methods.json`/`objects.json`/`responses.json` собирается скриптом `combine.sh` (нужен jq). Собранные файлы сохранены здесь:

- `schema/methods.json` (569 методов), `schema/objects.json`, `schema/responses.json`, `schema/errors.json`
- `schema/methods-access.tsv` - таблица «метод / допустимые токены / count default/max / лимиты списков id»

Оговорка: последний коммит в репозитории от 14 апреля 2025, при этом версия в схеме 5.199 совпадает с последней на dev.vk.ru. Расхождений со страницами методов нашлось немного (ниже), но схема может отставать от сайта, поэтому при конфликте пишу оба источника.

Допустимые токены в схеме называются `user`, `group` (ключ сообщества), `service`.

### 8.2 Уточнения по методам (схема, если не сказано иное)

| Метод | Токены | count default/max | Прочее |
|---|---|---|---|
| `wall.get` | user, service | max 100 | |
| `wall.getById` | user, service | - | `posts` ≤ 100 (док) |
| `wall.getComment` | user | - | |
| `wall.getComments` | user, service | max 100 | |
| `photos.get` | user, service | 50 / **1000** | |
| `photos.getAlbums` | user, service | без max | `album_ids` ≤ 1000 |
| `photos.getById` | user, service | - | `photos` ≤ 500 |
| `photos.search` | user, service | 100 / 1000 | |
| `photos.getAll` | user | 20 / 200 | |
| `groups.getById` | user, group, service | - | |
| `groups.getMembers` | user, group, service | 1000 / **1000** | |
| `groups.isMember` | user, group, service | - | `user_ids` |
| `groups.getAddresses` | user, service | 10 / без max | `address_ids` ≤ 100 |
| `groups.getTagList`, `getBanned` (20/200) | user, group | | |
| `board.getTopics` / `getComments` | user, service | 40/100, 20/100 | |
| `docs.get` | user | без max | |
| `docs.getById`, `docs.search` (20/-) | user, **group** | | ключ сообщества может читать документы по id |
| `video.get` | **только user** | 100 / 200 | |
| `video.getComments` (20/100), `getAlbums` (50/100) | user | | |
| `video.getOembed` | user, service, open | | oEmbed-плеер для видео; единственный видео-метод с сервисным ключом |
| `market.*` | user (часть заказов - user+group) | `market.get` 100/200, `getById` ≤100 id | |
| `stories.get`, `getById` | user, group | | |
| `pages.get` | user | | |
| `likes.getList` | user, service | max 1000 | |
| `newsfeed.search` | user, service | 30 / 200 | |
| `users.get` | user, group, service | - | `user_ids` ≤ 1000 |
| `storage.get`, `getKeys` | user, group, service | 100 / 1000 | |
| `utils.resolveScreenName` | user, group, service | - | |

Расхождений схемы и страниц методов, влияющих на выбор токена, не найдено.

### 8.3 Объект группы (`groups.getById`, то, что можно запросить через `fields`)

Схема перечисляет **самые важные для нас поля**: `activity, addresses, age_limits, ban_info, city, clips_count, contacts, counters, cover, crop_photo, description, fixed_post, links, main_album_id, main_section, secondary_section, market, members_count, photo_50/100/200/400/max/max_orig, site, start_date, finish_date, status, verified, videos_count, wall, wiki_page, can_post, can_see_all_posts, can_upload_story, can_upload_doc, can_upload_video, can_upload_clip, textlives_count, stories_archive_count`.

`counters` содержит: `addresses, albums, articles, audio_playlists, audios, clips, clips_followers, clips_likes, clips_views, docs, market, market_services, narratives, photos, podcasts, topics, video_playlists, videos, videos_followers`. По ним видно, какие разделы у группы вообще заполнены (хороший первый вызов спайка: сколько альбомов, фото, видео, статей, клипов).

`main_section` (какой раздел главный) - число с расшифровкой: none, photos, topics, audios, videos, market, stories, apps, followers, links, events, places, contacts, docs, albums, addresses, podcast, articles, menu, fixed_post, clips, market_services и другие. «Меню» как раздел существует только как значение `main_section`/`secondary_section`, содержимого меню отдельным методом нет.

`contacts[]`: `user_id, desc, phone, email`. `links[]`: `id, name, desc, url, photo_50, photo_100`. Адрес (`groups.getAddresses`): `id, title, address, additional_address, city_id, latitude, longitude, phone, time_offset, metro_station_id, work_info_status` (`no_information`, `temporarily_closed`, `always_opened`, `forever_closed`, `timetable`) и `timetable` по дням (`open_time`, `close_time`, `break_open_time`, `break_close_time` в минутах от полуночи).

### 8.4 Пост и вложения

Поля поста в схеме: `id, owner_id, from_id, created_by, date, text, edited, is_pinned, post_type, post_source, signer_id, attachments, copy_history, geo, likes, comments, reposts, views, donut, marked_as_ads, is_favorite, topic_id, is_archived, copyright, short_text_rate, inner_type`. Поле `edited` в схеме есть. Закреп - `is_pinned`.

**Типы вложений** (`attachments[].type`, схема): `photo, photos_list, posted_photo, audio, audio_playlist, video, clip, video_playlist, doc, link, graffiti, note, app, poll, page, album, market_album, market, event, donut_link, article, textlive, textpost, textpost_publish, situational_theme, group, sticker, podcast`. Структура: `{type: "<тип>", <тип>: {объект}}`; у приватных объектов есть `access_key`. Страница справочника перечисляет 17 типов (без clip, article, textpost, podcast, donut_link и т.д.) - схема полнее.

Поля объектов вложений:
- фото: `id, album_id, owner_id, user_id, text, date, sizes[], images[], width, height, lat, long, place, access_key, has_tags, thumb_hash, square_crop`;
- ссылка: `url, title, caption, description, photo, button, product, preview_page, preview_url`;
- документ: `id, owner_id, title, size, ext, url, date, type, preview (photo.sizes, graffiti, audio_message), tags, access_key`;
- видео: см. 8.5;
- статья, клип: в справочнике на dev.vk.ru отдельной страницы объекта нет, структуру надо смотреть по `objects.json` и живому ответу [?].

### 8.5 Фото и видео: что подтвердилось

- Типы размеров фото (`sizes[].type`): страница photo-sizes описывает `s m x o p q r y z w` (максимум `w` 2560x2048). Схема допускает больше: `t, s, m, x, o, p, q, r, k, l, y, z, c, w, a, b, e, i, d, j, temp, h, g, n, f, max, base, u, v, orig`. Что из этого реально приходит для фото паблика - вопрос спайка. Предлагаемое правило для контента: брать элемент `sizes` с наибольшей площадью (`width*height`), а не угадывать по букве.
- Ссылки на фото (`url`) - обычные HTTPS-ссылки на CDN VK; **срок жизни в документации и схеме не указан** [?]. Подписанные ссылки могут протухать, поэтому фото нужно скачивать при синке, а в базе хранить исходный `owner_id_photo_id`, а не URL (как и задумано в плане).
- Видео: объект `video_video_full` в схеме содержит `files` (`mp4_144 ... mp4_2160`, `flv_320`, `external`), `player`, `image[]`, `first_frame[]`, `duration`, `live`, `content_restricted`; но на странице объекта video на dev.vk.ru полей с файлами нет. Это вторая причина, по которой скачивание видео из ВК нельзя считать гарантированным. Сервисным ключом `video.get` недоступен, поэтому безопасный путь для сайта - встраивать `player`/oEmbed, а информацию о видео брать из вложений постов (`wall.get`), и проверить на живых ответах, что там есть `player` и превью [?].

### 8.6 Истории и документы

Объект истории: `id, owner_id, date, expires_at, is_expired, type (photo/video), photo, video, link, views, replies, access_key`. Истории временные (`expires_at`), архив через API не получить; поле группы `stories_archive_count` показывает только число.
Ключ сообщества с правом `docs` может читать документы через `docs.getById` и `docs.search` (но не `docs.get`) - нужны ID документов.

### 8.7 Страницы справочника, которые я обошёл

dev.vk.ru/ru/guide и /ru/reference (карта ссылок), /ru/api/api-requests, /ru/api/privacy, /ru/api/posts, /ru/reference/json-schema, /ru/reference/objects (44 объекта), объекты attachments-wall, doc, link, address, topic, story, market-item. Раздел `/ru/api/...` по ботам, VK Pay, рекламе, мини-приложениям и т.п. не читал: он не про выгрузку данных группы.

### 8.8 Что всё ещё не закрыто

1. Срок жизни ссылок на фото/видео-превью - в документации нет.
2. Есть ли `player` и какие превью у видео внутри вложений поста (проверять на живом `wall.get`).
3. Какие типы размеров фото реально приходят и есть ли `orig`.
4. Работает ли сервисный ключ на практике так, как написано (особенно `photos.get` для закрытых альбомов, `board.*`).
5. Статья и клип в вложениях: нет страницы объекта.
6. Требования к созданию приложения/получению сервисного ключа в «Кабинете для бизнеса VK ID» на странице access-token описаны кратко: шаги получения не проверены.

---

## 9. Как получить токен (проверено по документации 2026-10-07)

Источники: dev.vk.ru/ru/api/access-token/{getting-started, community-token, user-token}, dev.vk.ru/ru/general/app-types, документация VK ID «Создание приложения». Страница service-token отдала баннер «Технические работы», поэтому детали про сервисный ключ взяты со страницы создания приложения VK ID.

**Сервисный ключ** [док]
1. Standalone-приложения с 10 апреля 2026 создаются и редактируются **только в сервисе авторизации VK ID** (кабинет для бизнеса VK ID), в старом «Мои приложения» на vk.ru - нет.
2. Кабинет VK ID → «Мои приложения» → «Добавить приложение»: название, платформа (Web / iOS / Android; для сервера выбирать Web), иконка, базовый домен и доверенный redirect URL (допускается localhost; для продакшена HTTPS).
3. После создания выдаются три параметра: `client_id`, `client_secret` («защищённый ключ») и **`service_token` («сервисный ключ доступа») - он нужен для запросов API «сервер-сервер»**.
4. Тип приложения: публичное (обмен кода на токен на фронте) или **конфиденциальное** (обмен на бэкенде, «повышает лимиты запросов к API», требует указать IP бэкенда).
5. В течение 60 дней после создания первого приложения нужна **верификация бизнес-профиля** для полного доступа; без верификации квота API 10 000 вызовов в месяц.

**Ключ сообщества** [док]: нужны права администратора группы. Группа → Управление → Дополнительно → Работа с API → вкладка «Ключи доступа» → «Создать ключ», отметить права (для нас `photos`, `docs`, `stories`). Ключей может быть несколько; удаляются там же.

**Пользовательский токен** [док]: 1 час; Implicit Flow и Authorization Code Flow закрыты с 25.06.2024; получают через VK ID SDK или прямыми HTTP-запросами к VK ID, scope передаётся в параметре `scope`. Расширенные права выдаются после верификации бизнес-профиля или по согласованию с поддержкой.

Не проверено [?]: точный адрес кабинета (в новостях встречается id.vk.com/about/business, для .ru-домена id.vk.ru адрес не подтверждён), кому доступна верификация (физлицо/самозанятый/юрлицо), нужен ли для чтения открытой группы конфиденциальный тип приложения, видит ли сервисный ключ закрытые альбомы.

### 9.1 Уточнения (повторный обход, 2026-10-07)

- Страница `/ru/api/access-token/service-token` по-прежнему закрыта баннером «Технические работы». Шаги получения сервисного ключа подтверждаются только документацией VK ID (id.vk.ru, «Создание приложения»): после создания приложения выдаются «ID приложения (client_id), защищённый ключ, сервисный ключ доступа» [док].
- **Верификация обязательна:** «если вы не верифицируете профиль в течение 60 дней с момента создания первого приложения, ваши приложения будут заблокированы». Условие относится к зарегистрировавшимся после 15.12.2025 [док]. Т.е. не просто «нужно для полного доступа», а иначе приложение, а с ним и сервисный ключ, блокируется.
- Конфиденциальное приложение: обмен кода на токен на бэкенде, «повышенные лимиты запросов к API», нужно указать IP сервера; для обмена кода обязателен параметр `service_token` [док]. Для простого чтения публичных данных сервисным ключом это не нужно [вывод, не проверено].
- Ключ сообщества: страница community-token не утверждает, какие методы он может вызывать, а лишь показывает пример «для фото сообщества нужен ключ с правом `photos`» и отсылает к странице прав. Допустимые токены определяются блоком «Для вызова метода можно использовать» на странице метода: у `wall.get` и `photos.get` там пользовательский и сервисный ключи, ключ сообщества не назван, схема тоже. Пример с правом `photos` относится к методам, где ключ сообщества указан допустимым (например, `docs.getById`, `stories.get`). Итог не изменился: для постов и альбомов по документации ключ сообщества не годится, но живым вызовом не проверено.
- Пользовательский токен: через VK ID SDK или HTTP; базовые права (имя, фото, пол, дата рождения, email) сразу, расширенные (в т.ч. телефон) после верификации бизнес-профиля [док]. Права `wall`, `photos`, `video` на странице user-token не обсуждаются.
- id.vk.com с этой песочницы сейчас блокируется, id.vk.ru читается; документацию VK ID брать с id.vk.ru.

### 9.2 Три страницы токенов, повторное чтение (2026-10-07, позже)

- `service-token`: снова только баннер «Технические работы», содержимое недоступно. Остаётся единственным пробелом; шаги получения сервисного ключа подтверждены лишь документацией VK ID (см. 9, 9.1).
- `community-token`: ключ сообщества получают четырьмя способами: (1) настройки сообщества (любой тип приложения, сервер), (2) OAuth Authorization Code Flow (сервер), (3) Implicit Flow (клиент), (4) событие VK Bridge `VKWebAppGetCommunityToken` (мини-приложения). Создать может только администратор, без срока действия, можно несколько с разными правами, отзыв там же (Управление → Дополнительно → Работа с API → «Ключи доступа»). Какие методы доступны ключу, на странице не сказано.
- `user-token`: 1 час; мини-приложения - `VKWebAppGetAuthToken`, остальные - VK ID SDK или HTTP-запросы. Базовые права (имя, фамилия, фото, пол, дата рождения, почта) доступны сразу после создания приложения, расширенные - после верификации бизнес-профиля, некоторые - по согласованию с поддержкой. Права `wall`, `photos`, `video` здесь не упомянуты.
