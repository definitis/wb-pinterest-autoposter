# WB Новинки -> VK Autoposter MVP

MVP для автопостинга новых товаров бренда с Wildberries в соцсети. Проект показывает полный рабочий процесс: товар попадает в систему, проходит валидацию, по нему создается пост под выбранную соцсеть, дубли блокируются, статус сохраняется в SQLite, результат проверяется через `report`/`status`.

**Кратко:**

- Основной MVP: реальный автопостинг новинок WB во VK с картинкой через browser automation.
- Безопасный demo-режим: VK dry-run без реальной публикации.
- WB API режим подготовлен: после токенов можно переключить источник с локального JSON на WB API.
- Для реальной работы есть baseline: первый sync фиксирует текущий ассортимент как уже известный, чтобы не постить старые товары.
- Pinterest и Instagram не входят в основной сценарий показа. Они оставлены как дополнительные API-ready направления.
- Zernio изучен как практичный путь для Pinterest/Instagram без отдельных developer apps на стороне проекта.
- Тесты: `python -m pytest`.


## Как лучше проверять проект

Рекомендуемый порядок проверки:

1. Для безопасной проверки без реальной публикации можно сразу перейти к `Быстрая Проверка`.

2. Для реальной VK-публикации сначала заполнить `.env` по разделу “Настройка VK и WB”.
   Нужна VK-группа и аккаунт с правом публикации в ней.

3. Перейти к разделу “Главный Сценарий MVP”, затем к разделу “Полный Регулярный Цикл WB -> VK”.

4. Остальные разделы README — это технические подробности: режимы работы, артефакты, API-ready направления, экономика и roadmap.

В проекте приложена подготовленная SQLite-база с реальными данными продавца TRENDSETTER. Это демонстрационный каталог, собранный через browser-baseline на момент 03.06.2026 около 21:00.

Для наглядной проверки из baseline намеренно удалены первые 10 товаров. Поэтому при запуске регулярного цикла система увидит их как “новинки”, создаст VK-посты и сможет показать полный путь: WB scan -> planned posts -> dry-run или реальная VK-публикация.

Важно: количество и порядок товаров WB могли измениться после сборки БД. Поэтому число найденных “новинок” при проверке может отличаться от 10, если WB поменял выдачу продавца.

Тестовая VK-группа, где проверялась публикация:
https://vk.com/club239286699


## Быстрая Проверка

Установить зависимости:

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

В `pyproject.toml` уже включены зависимости для WB browser-baseline:

```text
selenium==4.19.0
undetected-chromedriver==3.5.4
chromedriver-autoinstaller
```

Запустить тесты:

```bash
python -m pytest
```

Запустить безопасное VK demo без реального поста:

```bash
python -m wb_autoposter.cli mvp-demo --platform vk
```

Проверить общий статус:

```bash
python -m wb_autoposter.cli status
```

Посмотреть результат dry-run:

```text
out/vk_wall_post_*.json
out/app.sqlite3
```

Если Python Scripts добавлен в `PATH`, можно заменить `python -m wb_autoposter.cli` на `wb-autoposter`.

## Главный Сценарий MVP

Основной сценарий показа: WB -> VK. Pinterest и Instagram не участвуют в основном MVP; они оставлены ниже как дополнительные API-ready направления.

```text
Первичная настройка:
wb-browser-baseline -> seen_products в SQLite
vk-browser-login -> сохраненная VK-сессия

Регулярная работа:
wb-vk-cycle -> scan WB -> planned VK posts -> dry-run или real VK publish -> status
```

1. Один раз собрать baseline текущего каталога WB. (Сейчас в проекте уже лежит база данных с товарами реального продавца, 10 последних товаров специально удалены. Можно удалить эту БД и запустить команду для нового создания БД с артикулами, снизу команда готова, но можно изменить по желанию. Если тестировать с готовой БД, то можно перейти к шагу 2, а затем к следующему разделу)

```powershell
python -m wb_autoposter.cli wb-browser-baseline --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --expected-count 1924 --min-expected-ratio 0.95 --user-data-dir out\wb_chrome_profile_baseline --max-scrolls 350 --idle-scrolls 40 --scroll-delay-ms 2500
```

Что заменить под себя:

- `--seller-url` - ссылка на страницу продавца/бренда WB, лучше с сортировкой по новинкам: `?sort=newly&page=1`;
- `--expected-count` - примерное количество товаров, которое WB показывает на странице продавца;
- `--user-data-dir` - отдельный профиль Chrome для WB, можно оставить `out\wb_chrome_profile_baseline`;
- `--max-scrolls`, `--idle-scrolls`, `--scroll-delay-ms` - защитные настройки прокрутки и догрузки каталога.

2. Один раз войти во VK и сохранить браузерную сессию.

```powershell
python -m wb_autoposter.cli vk-browser-login
```

3. Дальше регулярно запускать одну команду `wb-vk-cycle`.

`wb-browser-baseline` и `vk-browser-login` не запускаются каждый час. Они нужны только при первичном подключении продавца/аккаунта.

## Полный Регулярный Цикл WB -> VK

Безопасный цикл без реальной публикации:

```powershell
python -m wb_autoposter.cli wb-vk-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --dry-run
```

Важно: dry-run не публикует пост во VK, но переводит обработанные записи из `planned` в `dry_run_published`. Если после dry-run запустить реальную публикацию, она возьмет следующие посты со статусом `planned`, а не те же самые записи.

Реальная публикация через VK browser automation:

```powershell
python -m wb_autoposter.cli wb-vk-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --browser --no-dry-run --limit 3
```

Публикация идет последовательно: один товар = один пост. За один запуск можно обработать до N постов; N задается параметром `--limit`, а значение по умолчанию берется из `VK_POST_LIMIT_PER_RUN`.

Команда делает:

```text
1. Проверяет, что baseline уже есть.
2. Сканирует верхние товары продавца WB.
3. Находит новые nmID.
4. Создает planned VK-посты.
5. В dry-run режиме сохраняет payload без публикации.
6. В real режиме публикует во VK через сохраненную браузерную сессию.
7. Печатает краткий status: scanned, new nmID, planned, published/dry-run, failed.
```

Если baseline не найден, команда остановится:

```text
Baseline not found. Run wb-browser-baseline first.
```

Если новых товаров нет, это нормальный результат:

```text
No new products found. Nothing to publish.
```

## Что Реально Работает

**VK:**

- dry-run payload для проверки без публикации;
- реальная публикация поста с текстом и картинкой через Playwright/browser automation;
- последовательная публикация до N товаров за один запуск в одной браузерной сессии;
- защита от повторной публикации одного товара в VK;
- статусы `planned`, `publishing`, `published`, `failed`, `dry_run_published`.

**WB:**

- локальный fake-источник для MVP;
- real-ready источник через WB Content API + Prices and Discounts API + Analytics Stocks;
- browser fallback без Seller API: baseline полного каталога продавца и регулярный scan верхних товаров по `sort=newly`;
- публичный WB fallback без Seller API: поиск товаров по query/supplier/brand и детали через публичный card JSON;
- baseline-sync для фиксации текущего ассортимента без публикации старых товаров;
- фильтрация товаров без фото, цены, остатка или ссылки.

## Дополнительные Каналы

Pinterest и Instagram не входят в основной сценарий показа MVP.

**Pinterest:** подготовлены dry-run payload, validation и API-ready publisher для `POST /v5/pins`. Реальная публикация требует approved Pinterest Developer App, сайта/privacy policy и OAuth token с правами `pins:write`/`boards:write`.

**Instagram:** подготовлен skeleton под Meta Graph API, но реальный запуск требует Instagram Business/Creator, связку с Facebook Page и Meta app permissions.

**Zernio:** по публичной документации Zernio подходит как альтернативный слой реальной публикации для Pinterest и Instagram. Он дает единый API `https://zernio.com/api/v1`, авторизацию через `ZERNIO_API_KEY`, OAuth-подключение аккаунтов, `POST /posts` для публикации/планирования, `mediaItems` для изображений/видео и analytics API. Важно: реальный прогон все равно требует зарегистрировать Zernio-аккаунт, получить API key и подключить Pinterest/Instagram аккаунты через OAuth. На 08.06.2026 в документации указано, что первые 2 подключенных аккаунта бесплатны, без карты, с полным API-доступом.

Как это отработать в проекте:

1. Создать Zernio profile и сохранить его ID.
2. Подключить Pinterest/Instagram через `GET /connect/{platform}`; для Pinterest выбрать board и сохранить `accountId`/`boardId`.
3. Добавить отдельный `ZernioPublisher`, который принимает уже готовый post payload из текущей системы.
4. Для Pinterest отправлять `content`, `mediaItems: [{type: "image", url: "..."}]`, `platforms: [{platform: "pinterest", accountId, platformSpecificData: {boardId, title, link}}]`, `publishNow: true`.
5. Для Instagram отправлять `content`, `mediaItems`, `platforms: [{platform: "instagram", accountId, platformSpecificData: {contentType}}]`, `publishNow: true`; ссылку на WB лучше дублировать в `firstComment` или вести через UTM/redirect, потому что Instagram плохо подходит для кликабельного внешнего трафика.
6. Оставить safety-флаг: реальная публикация через Zernio должна запускаться только при `ZERNIO_ENABLE_REAL_PUBLISH=1`, наличии `ZERNIO_API_KEY` и нужных account/board IDs.

Документация Zernio:

- Quickstart: https://docs.zernio.com/
- Create post: https://docs.zernio.com/posts/create-post
- Connecting accounts: https://docs.zernio.com/guides/connecting-accounts
- Pinterest: https://docs.zernio.com/platforms/pinterest
- Instagram: https://docs.zernio.com/platforms/instagram
- Pricing: https://docs.zernio.com/pricing

## Настройка VK И WB

Минимально для VK нужны:

```text
WB_AUTOPOSTER_DB_PATH=out/app.sqlite3
WB_AUTOPOSTER_OUT_DIR=out

VK_OWNER_ID=-239286699
VK_GROUP_ID=239286699
VK_BROWSER_GROUP_URL=https://vk.com/club239286699
VK_BROWSER_ENABLE=1
VK_BROWSER_STATE_PATH=out/vk_browser_state.json
VK_BROWSER_HEADLESS=0
VK_BROWSER_CONFIRM_BEFORE_POST=0
VK_POST_LIMIT_PER_RUN=3
```

`VK_OWNER_ID` для группы пишется с минусом. Например, для `club239286699` это `-239286699`. `VK_GROUP_ID` пишется без минуса.

`VK_BROWSER_CONFIRM_BEFORE_POST=0` означает, что скрипт сам нажмет кнопки публикации. Если нужно сначала вручную проверять каждый пост перед отправкой, поставь `1`.

Что означает каждое поле:

| Поле | Что указать | Где взять |
| --- | --- | --- |
| `WB_AUTOPOSTER_DB_PATH` | Путь к SQLite-базе проекта. Обычно `out/app.sqlite3`. | Оставить как в примере. |
| `WB_AUTOPOSTER_OUT_DIR` | Папка для dry-run JSON, скачанных картинок и служебных файлов. Обычно `out`. | Оставить как в примере. |
| `VK_OWNER_ID` | ID стены VK, куда публикуем. Для группы обязательно с минусом. | Из ссылки `vk.com/club239286699` получается `-239286699`. |
| `VK_GROUP_ID` | ID группы без минуса. | Из ссылки `vk.com/club239286699` получается `239286699`. |
| `VK_BROWSER_GROUP_URL` | Ссылка на группу VK. | Открытая ссылка сообщества, например `https://vk.com/club239286699`. |
| `VK_BROWSER_ENABLE` | Разрешает реальную browser-публикацию. | Для MVP поставить `1`. |
| `VK_BROWSER_STATE_PATH` | Файл, куда сохранится VK-сессия после логина. | Оставить `out/vk_browser_state.json`. |
| `VK_BROWSER_HEADLESS` | Показывать браузер или запускать скрыто. | Для локального MVP оставить `0`, чтобы видеть процесс. |
| `VK_BROWSER_CONFIRM_BEFORE_POST` | Нужно ли ручное подтверждение перед публикацией. | `0` - публиковать автоматически, `1` - остановиться перед отправкой. |
| `VK_POST_LIMIT_PER_RUN` | Сколько постов максимум публиковать за один запуск. | Для теста удобно `1-3`, для пилота можно увеличить. |

Перед реальной публикацией нужно один раз выполнить `vk-browser-login`. Откроется браузер: нужно войти в VK аккаунтом с правом публикации в группе, затем вернуться в консоль и нажать Enter. Сессия сохранится в `out/vk_browser_state.json`.

Baseline нужен, чтобы текущие товары продавца не считались новинками. `--expected-count` в команде baseline - ориентир, а не жесткое равенство. Если WB показывает 1924 товара, а скрипт собрал 1922, baseline принимается, потому что это в пределах `--min-expected-ratio 0.95`. Если собрал сильно меньше, например 115 или 842, baseline не сохраняется.

`--scroll-delay-ms` сейчас работает как максимальное ожидание догрузки после прокрутки: если карточки появились раньше, скрипт продолжает раньше.

Если публикация упала, пост получает статус `failed`. При следующем `publish` или `wb-vk-cycle` failed-посты автоматически возвращаются в очередь, если товар все еще подходит для публикации.

## Частая Ошибка Chrome

Если появляется ошибка вида:

```text
Could not start Chrome for WB browser automation
session not created: cannot connect to chrome
```

значит профиль `--user-data-dir` уже занят зависшим Chrome-процессом. Закрой окна Chrome с этим профилем или используй свежий профиль, например:

```powershell
python -m wb_autoposter.cli wb-browser-sync-new --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_2
```

## Регулярный Запуск По Расписанию

### Windows Task Scheduler

Для browser automation лучше Windows Task Scheduler или Windows VPS, потому что WB/VK-сценарий открывает Chrome и зависит от пользовательской браузерной сессии.

1. Один раз выполнить baseline:

```powershell
python -m wb_autoposter.cli wb-browser-baseline --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --expected-count 1924 --min-expected-ratio 0.95 --user-data-dir out\wb_chrome_profile_baseline --max-scrolls 350 --idle-scrolls 40 --scroll-delay-ms 2500
```

2. Один раз сохранить VK-сессию:

```powershell
python -m wb_autoposter.cli vk-browser-login
```

3. Создать `.bat` файл, например `run_wb_vk_cycle.bat`:

```bat
cd /d C:\path\to\wb-autoposter
call .venv\Scripts\activate
python -m wb_autoposter.cli wb-vk-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --browser --no-dry-run --limit 3
```

4. В Windows Task Scheduler:

- `Create Task`;
- `Trigger`: каждые 1-3 часа;
- `Action`: запуск `run_wb_vk_cycle.bat`;
- `Start in`: папка проекта;
- для browser automation лучше `Run only when user is logged on`, чтобы браузер мог нормально открываться.

После запуска проверить статус:

```powershell
python -m wb_autoposter.cli status
```

### Linux Cron / Systemd Timer

Linux VPS лучше использовать для будущей API-версии без browser automation. В этом режиме браузер не нужен, поэтому cron/systemd timer надежнее и дешевле.

Пример cron для безопасного dry-run/API-style запуска:

```bash
0 */2 * * * cd /opt/wb-autoposter && /opt/wb-autoposter/.venv/bin/python -m wb_autoposter.cli wb-vk-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --dry-run >> /var/log/wb-autoposter.log 2>&1
```

Для текущего browser fallback на Linux понадобится Chrome, графическая сессия или headless-настройка. Это возможно, но для MVP проще и прозрачнее запускать browser-сценарий на Windows-машине, где пользователь может видеть и контролировать браузер.

## Как Сдавать Проект С Данными

Проект можно сдавать не только “пустым”, но и с подготовленной SQLite-базой. Это удобно, если проверяющий хочет быстро увидеть реальный сценарий на карточках WB и не собирать baseline с нуля.

### Вариант 1. Подготовленная БД Для Быстрой Проверки

В проекте можно оставить:

```text
out/app.sqlite3
out/wb_browser_baseline_nmids.json
out/wb_browser_new_scan_products.json
```

Что это дает:

```text
out/app.sqlite3                  -> baseline, товары, посты и статусы
out/wb_browser_baseline_nmids.json -> список nmID, найденных при полном baseline продавца
out/wb_browser_new_scan_products.json -> последний scan верхних карточек продавца
```

Если нужно, чтобы проверяющий сразу увидел “новинки”, БД готовится так:

```text
1. Сначала делается baseline продавца.
2. Из таблицы seen_products удаляются несколько верхних nmID из текущего top-window.
3. Таблицы products/posts для этих nmID должны быть пустыми или очищенными.
4. Проверяющий запускает wb-browser-sync-new.
5. Эти товары определяются как новые и получают статус planned.
```

Важно: количество и порядок товаров WB могут измениться со временем. Поэтому подготовленная БД является демонстрационным срезом на момент сдачи. Если WB поменял выдачу, число найденных “новинок” может отличаться.

### Вариант 2. История Успешной Публикации

Можно оставить БД, в которой уже есть опубликованные посты. Это показывает, что реальная VK-публикация отработала.

Но такую БД нельзя использовать для повторной публикации тех же товаров: защита от дублей увидит, что посты уже `published`, и не создаст новые посты по этим `nmID`.

Проверить состояние:

```powershell
python -m wb_autoposter.cli status
```

### Вариант 3. Полностью Чистый Запуск

Если подготовленная БД не подходит, ее можно удалить. При следующем запуске проект создаст новую SQLite-базу сам.

```powershell
Remove-Item out\app.sqlite3
```

После этого нужно пройти обычный путь из разделов `Главный Сценарий MVP` и `Полный Регулярный Цикл WB -> VK`: baseline, VK login, затем `wb-vk-cycle`.

## Генерация Текстов Через Gemini

Проект умеет генерировать короткие тексты для VK, Instagram и Pinterest на основе карточки Wildberries. Генерация встроена в этап `plan-posts`: когда для нового товара создается planned-пост, система сначала получает тексты, затем кладет нужный вариант в payload конкретной площадки.

В `.env` можно включить Gemini:

```env
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-2.5-flash
GEMINI_REQUEST_INTERVAL_SECONDS=6
GEMINI_429_COOLDOWN_SECONDS=60
CONTENT_RULES_PATH=config/content_rules.example.json
```

Один товар обрабатывается одним запросом к Gemini. В одном ответе модель возвращает JSON сразу для трех площадок:

```json
{
  "vk": "короткий текст для VK",
  "instagram": "короткий текст для Instagram",
  "pinterest": "короткий текст для Pinterest"
}
```

Это экономит лимиты бесплатного API: не нужно делать отдельный запрос для VK, отдельный для Instagram и отдельный для Pinterest. Если сначала планируется Pinterest, а потом Instagram/VK для того же товара, уже сохраненный `generated_content.platform_texts` переиспользуется из payload.

Если `GEMINI_API_KEY` не задан или Gemini вернул невалидный JSON, пайплайн не падает. В лог пишется, что использован fallback, а тексты собираются локальными шаблонами из названия, описания, характеристик и ссылки.

Чтобы не ловить `429 Too Many Requests`, генератор не отправляет запросы чаще, чем `GEMINI_REQUEST_INTERVAL_SECONDS`, а после ответа 429 включает cooldown на `GEMINI_429_COOLDOWN_SECONDS`. Один запрос по-прежнему возвращает тексты сразу для VK, Instagram и Pinterest; throttling работает между разными товарами, а не между площадками.

Правила текста можно менять без правки кода через `CONTENT_RULES_PATH`. Пример лежит в `config/content_rules.example.json`: туда добавляются запретные фразы, generic marketplace-бренды вроде `wildberries/wb/вб`, SEO stopwords и заблокированные хэштеги. Эти правила используются при валидации ответа Gemini, fallback-текстах, SEO-ключах и чистке фразы вида `Бренд: Wildberries`.

## Fake/Dry-Run Проверка Без Реальных WB И VK

Если проверяющий не хочет трогать реальные карточки WB и VK-группу, можно показать проект на fake-данных:

```powershell
python -m wb_autoposter.cli mvp-demo --platform vk
```

Dry-run - это безопасный режим, в котором проект делает все кроме реальной публикации в соцсеть. Он загружает товары, создает посты, валидирует payload, сохраняет статус в БД и пишет готовый JSON в `out/`.

Зачем нужен dry-run:

- показать полный сценарий без API-ключей;
- проверить текст, ссылку, фото и структуру payload;
- убедиться, что не создаются дубли;
- безопасно демонстрировать проект проверяющему.

Пример результата для VK:

```text
out/vk_wall_post_12_101000001.json
```

## Реальный VK

VK API с community token может публиковать текст, но часто не дает загрузить фото через `photos.getWallUploadServer`. Поэтому для MVP добавлен browser fallback: скрипт открывает VK через Playwright, использует сохраненную сессию, скачивает фото товара, вставляет текст, прикрепляет картинку и публикует пост в группе.

Safety-настройки:

```text
VK_BROWSER_ENABLE=1
VK_BROWSER_CONFIRM_BEFORE_POST=1
```

- `VK_BROWSER_ENABLE=1` разрешает browser-публикацию.
- `VK_BROWSER_CONFIRM_BEFORE_POST=1` заполняет пост и ждет ручного подтверждения перед публикацией.
- `VK_BROWSER_CONFIRM_BEFORE_POST=0` публикует без дополнительного подтверждения.

Browser fallback подходит для MVP, пилота и временного боевого запуска, когда API-доступ недоступен. Для стабильного production предпочтительнее официальный VK API с корректным OAuth-доступом к публикации фото. Если VK изменит интерфейс, селекторы Playwright может понадобиться поправить.

## Как Работает Пайплайн

```text
sync -> plan-posts -> publish -> report
```

`sync` загружает товары из источника: сейчас из `data/fake_wb_products.json`, в `real-ready` режиме из WB API, в `wb-public` режиме из публичной выдачи WB.

`plan-posts` выбирает товары для публикации и создает planned-посты.

`publish` публикует или делает dry-run для выбранной платформы.

`report` показывает товары, посты и статусы. Экономика проекта описана отдельным текстовым разделом README и не считается внутри CLI.

Для demo/test первый запуск может сразу планировать товары из фикстуры, чтобы проект было легко показать. Для реального сценария используется baseline:

```text
baseline-sync -> сохраняем текущий ассортимент как уже известный
следующий sync -> видим новые nm_id
plan-posts --only-after-baseline -> планируем только товары после baseline
publish -> публикуем только реальные новинки
```

Для `source=wb-public` baseline хранит только найденные `nm_id` в таблице `seen_products`. Детали старых товаров не загружаются. Полные карточки (`products`) создаются только для новых `nm_id`, появившихся после baseline.

Платформы запускаются отдельно: `--platform vk` или `--platform pinterest`. Для MVP это осознанное решение: так проще контролировать лимиты, статусы и ошибки. В будущем можно добавить общий `run-all`, но внутри он все равно должен идти по платформам последовательно.

## Что Считается Новинкой

Товар идентифицируется по `nm_id`. Пост уникален по паре:

```text
product_nm_id + platform
```

Это значит:

- один и тот же товар не будет повторно опубликован в VK;
- тот же товар можно отдельно опубликовать в Pinterest;
- повторный запуск `sync -> plan-posts -> publish` не создает дубль для уже запланированного или опубликованного товара.

Для демонстрации без API логика простая:

```text
если для товара еще нет поста в выбранной платформе, его можно планировать
```

Для реального проекта логика строже:

```text
1. baseline-sync сохраняет текущие товары как старый ассортимент;
2. новые sync-запуски добавляют товары с новым first_seen_at;
3. plan-posts --only-after-baseline берет только товары, впервые увиденные после baseline;
4. антидубли по product_nm_id + platform все равно остаются включенными.
```

Это защищает от ситуации, когда при первом подключении WB API весь старый ассортимент внезапно считается новинками.

В публикацию попадает только товар, у которого:

- есть бренд и название;
- есть публичное `http/https` фото;
- цена больше нуля;
- остаток больше нуля;
- есть валидная ссылка на WB;
- для этой платформы еще нет поста.

## Файлы И Артефакты

Исходники:

- `src/wb_autoposter/` - код приложения;
- `tests/` - автотесты;
- `data/fake_wb_products.json` - базовые demo-товары;
- `data/vk_batch_products_2026_06_02.json` - отдельная фикстура для проверки последовательной публикации нескольких VK-постов;
- `.env.example` - пример настроек без секретов;
- `.env` - локальные настройки и токены, не должен попадать в репозиторий.

Файлы, которые появляются после запуска:

- `out/*.sqlite3` - SQLite-БД с товарами, постами и статусами;
- `out/vk_wall_post_*.json` - VK dry-run payload;
- `out/pinterest_pin_*.json` - Pinterest dry-run payload;
- `out/vk_browser_media/*.jpg` - фото, скачанные перед реальной VK browser-публикацией;
- `out/vk_browser_debug/` - скриншоты/HTML/текст страницы при ошибках VK automation;
- `out/vk_browser_state.json` - сохраненная VK-сессия после `vk-browser-login`.
- `out/wb_browser_baseline_nmids.json` - nmID, собранные browser-baseline со страницы продавца WB;
- `out/wb_browser_state.json` - сохраненное состояние WB-браузера для повторного baseline-сбора.

`out/` можно удалить: проект создаст его заново. Исключение - `out/vk_browser_state.json`; если удалить этот файл, нужно снова выполнить `vk-browser-login`.

Служебный мусор, который не является частью проекта:

- `__pycache__/`;
- `.pytest_cache/`;
- `*.egg-info/`;
- временные `*.sqlite3` вне `out/`.

Эти файлы добавлены в `.gitignore`.

База хранит товары по первичному ключу `nm_id`, а посты защищены уникальной парой `product_nm_id + platform`. Для большого ассортимента добавлены две разные сущности:

- `seen_products` - легкая таблица только для `nm_id`, source, first_seen/last_seen и baseline-флага;
- `products` - полные карточки только для товаров, которые реально нужны для публикации.

Это нужно, чтобы публичный WB fallback мог запомнить тысячи старых артикулов без загрузки всех описаний, фото и payload.

## Режимы Работы

### `test`

Режим по умолчанию. Полностью локальный и бесплатный: товары берутся из `data/fake_wb_products.json`, публикация работает как VK dry-run, результат сохраняется в SQLite и `out/`.

### `real-ready` - не готов к использованию

Почти реальный режим под официальный WB API. Для защиты от публикации старого ассортимента сначала выполняется baseline, после чего `sync` берет только актуальные карточки через WB API и создает посты только для товаров, впервые увиденных после baseline.

В `real-ready` режиме `sync` использует:

```text
WB Content API -> карточки, фото, название, описание
WB Prices and Discounts API -> актуальная цена
WB Analytics Stocks Report -> остаток
SQLite -> сохранение товаров и защита от дублей
```

### `wb-browser-baseline`

Одноразовый fallback для создания baseline полного каталога продавца через видимый браузер. Нужен, когда WB Seller API еще нет, а public search не подходит, потому что он ищет по `query`, а не забирает все товары продавца.

Как работает:

```text
1. Открывается видимый Google Chrome через Selenium + undetected_chromedriver.
2. Скрипт ждет первичную отрисовку страницы.
3. Если WB показывает проверку, можно перезапустить команду с --manual-ready и пройти ее вручную.
4. Скрипт скроллит страницу и адаптивно ждет догрузку карточек.
5. Найденные nmID сохраняются в out/wb_browser_baseline_nmids.json.
6. Эти nmID помечаются в SQLite как baseline, без загрузки полных карточек и без публикаций.
```

Фактический тест на Trendsetter:

```text
Warning: collected 1922 of expected 1924 nmIDs. Baseline is accepted because it is within the configured tolerance.
Collected 1922 WB nmIDs in 163 scroll iterations.
Baseline marked for 1922 nmIDs.
Already known before this run: 0 nmIDs.
No product details were fetched and no posts were planned.
```

`--expected-count` не требует идеального совпадения. Это ориентир для контроля качества baseline. Если результат ниже `--min-expected-ratio`, baseline не сохраняется. Это защищает от ситуации, когда WB отдал только верхнюю часть каталога.

По умолчанию команда использует Selenium + `undetected_chromedriver`, то есть запускает Google Chrome не через Playwright. Playwright оставлен как запасной режим через `--browser-engine playwright`.

`--user-data-dir` включает постоянный профиль: cookies, localStorage и результат ручной проверки WB сохраняются между запусками. Если Chrome обновился, а `chromedriver-autoinstaller` нашел старый драйвер, укажи актуальный `--chromedriver-path` или оставь `--auto-install-driver`, чтобы проект попробовал поставить подходящий драйвер сам.

Один и тот же `--user-data-dir` нельзя использовать параллельно в нескольких запусках. Если Chrome не стартует с ошибкой `cannot connect to chrome`, закрой зависшие Chrome-процессы этого профиля или укажи новый профиль.

По умолчанию WB-команды не ждут Enter. Если нужна ручная пауза перед началом скролла, можно добавить `--manual-ready`. Запасной Playwright-режим доступен через `--browser-engine playwright`.

Если нужно подключиться к уже открытому обычному Chrome, его можно запустить с remote debugging:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$PWD\out\wb_chrome_profile_baseline"
```

Потом в другом терминале нужно запустить baseline-команду с `--cdp-url http://127.0.0.1:9222`.

Если собрано `0` nmID, baseline не сохраняется. Это защита от ситуации, когда WB открыл антибот-страницу или карточки не успели появиться.

Как работает `wb-browser-sync-new`:

```text
1. Открывает страницу продавца с sort=newly.
2. Переходит к блоку "Все товары", чтобы не брать "Бестселлеры" и промо-блоки.
3. Собирает верхние scan-limit карточек из DOM, например первые 100.
4. Сравнивает nmID с таблицей seen_products.
5. Уже известные baseline-товары пропускает.
6. Неизвестные nmID считает новинками.
7. По неизвестным карточкам сохраняет минимальные product-данные: nmID, title, price, photo, url.
8. Сразу создает planned-посты для выбранной платформы, по умолчанию VK.
```

После скана посты находятся в статусе `planned`. В обычном сценарии их обрабатывает `wb-vk-cycle`. `publish` по умолчанию сначала возвращает publishable `failed`-посты обратно в `planned`, поэтому отдельный `retry-failed` обычно не нужен.

`--scan-limit 100` - рабочая настройка для регулярной проверки. Если ожидается крупная загрузка коллекции, лимит можно поднять до 200-300. Скан не останавливается на первом старом товаре: старые карточки могут подняться вверх после обновления, поэтому команда просматривает заданное верхнее окно целиком.

Если нужно только просканировать товары без создания planned-постов, у `wb-browser-sync-new` есть флаг `--no-plan`.

Ограничение: это не стабильный production-источник. Это полуавтоматический способ один раз заполнить стартовый список старых товаров. Для стабильной регулярной работы приоритет остается за WB Seller API или выгрузкой из кабинета продавца.

## API Готовность

**WB API**

Подготовлен `WBEnrichedProductSource`, подключенный к `sync --mode real-ready`. Он использует:

```text
POST https://content-api.wildberries.ru/content/v2/get/cards/list
POST https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter
POST https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products
```

В коде уже есть cursor pagination, brand filter, маппинг WB card response в локальную модель, сбор фото, построение WB-ссылки, обогащение ценой и остатками. Если WB даст один токен со всеми категориями доступа, достаточно заполнить `WB_API_TOKEN`; если токены раздельные, используются `WB_CONTENT_API_TOKEN`, `WB_PRICES_API_TOKEN`, `WB_ANALYTICS_API_TOKEN`.

Официальная документация WB: https://dev.wildberries.ru/docs/openapi/work-with-products

**Pinterest API**

Подготовлен `PinterestApiPublisher` и dry-run payload под Pinterest API v5. Реальная публикация требует approved Pinterest Developer App, сайта/privacy policy, OAuth token и scopes `pins:write`/`boards:write`, поэтому канал оставлен в roadmap.

**Zernio для Pinterest/Instagram**

Zernio выглядит более быстрым путем для пилота Pinterest/Instagram, чем прямое подключение официальных API в этом проекте:

- Zernio сам закрывает developer apps/approvals платформ и дает единый `POST /api/v1/posts`;
- аккаунты подключаются через OAuth, а после подключения проект работает с Zernio `accountId`;
- картинки можно передавать как публичные media URLs или через presigned upload Zernio;
- Pinterest требует `boardId`; его можно выбрать во время подключения или получить из Zernio после подключения;
- Instagram поддерживает feed, stories, reels и carousel, но для товарных ссылок лучше использовать UTM/redirect и/или первый комментарий;
- `POST /posts` возвращает Zernio post `_id` и статус, а опубликованные посты можно затем читать через list/get posts; analytics API покрывает impressions/clicks/saves для Pinterest и reach/likes/comments/saves/views для Instagram.

Минимальные env-поля для будущей интеграции:

```text
ZERNIO_API_KEY=
ZERNIO_ENABLE_REAL_PUBLISH=0
ZERNIO_PROFILE_ID=
ZERNIO_PINTEREST_ACCOUNT_ID=
ZERNIO_PINTEREST_BOARD_ID=
ZERNIO_INSTAGRAM_ACCOUNT_ID=
ZERNIO_INSTAGRAM_CONTENT_TYPE=feed
```

Доступный CLI без ломки текущей архитектуры:

```bash
python -m wb_autoposter.cli zernio-check --platform pinterest
python -m wb_autoposter.cli publish --platform pinterest --zernio --no-dry-run
```

**Соцметрики через Zernio**

После реальной публикации Pinterest/Instagram пост получает `external_id`. По этому ID можно подтягивать аналитику Zernio и сохранять ее в локальную SQLite-базу:

```bash
python -m wb_autoposter.cli sync-metrics --platform all
python -m wb_autoposter.cli sync-metrics --platform pinterest
python -m wb_autoposter.cli sync-metrics --platform instagram
python -m wb_autoposter.cli metrics-report --platform all
```

`sync-metrics` читает опубликованные посты со статусом `published`, берет их `external_id`, вызывает `GET /api/v1/analytics` в Zernio и сохраняет снимок в таблицу `post_metrics`. Сохраняются нормализованные поля `impressions`, `reach`, `clicks`, `likes`, `comments`, `saves`, `shares`, `views`, `engagement`, плюс полный raw JSON ответа.

Если Zernio возвращает `202`, это значит, что синхронизация аналитики еще не готова; команда помечает такой пост как `pending` и не ломает общий прогон. Повторный запуск позже сохранит новый снимок метрик.

Для Instagram клики на WB из caption честно не считаются как кликабельная ссылка, поэтому основной смысл метрик там - охват и вовлеченность: `reach`, `views`, `likes`, `comments`, `saves`. Для Pinterest можно смотреть еще и `clicks`, потому что ссылка на товар передается как destination link пина.

Реальный Zernio-publish для Pinterest и Instagram добавлен отдельными publisher-классами и заблокирован safety-флагом. Он запускается только при `ZERNIO_ENABLE_REAL_PUBLISH=1`, заполненном `ZERNIO_API_KEY` и нужных account/board ID для выбранной площадки.

**VK API**

Подготовлен `VKApiPublisher` для `wall.post` и цепочки загрузки фото. Также есть `vk-check --api` и `vk-check --api --photo-upload`.

Для проверки:

```bash
python -m wb_autoposter.cli vk-check --api
python -m wb_autoposter.cli vk-check --api --photo-upload
```

Если `vk-check --api` проходит, а `--photo-upload` падает с `Group authorization failed`, нужен user OAuth token от пользователя с правами администратора/редактора сообщества.

Документация VK API schema: https://github.com/VKCOM/vk-api-schema

**Instagram**

Добавлен подготовительный `InstagramApiPublisher` под Meta Graph API: создание media container и `media_publish`. Instagram не подключен к основному MVP, потому что для реального запуска нужны бизнес-аккаунт, связка Instagram Business/Creator + Facebook Page и Meta app permissions.

## Переменные Окружения

`.env` загружается автоматически при запуске CLI. Для основного сценария WB -> VK достаточно скопировать `.env.example` в `.env` и заполнить только VK-группу:

```text
WB_AUTOPOSTER_DB_PATH=out/app.sqlite3
WB_AUTOPOSTER_OUT_DIR=out

# пример для тестовой VK-группы https://vk.com/club239286699
VK_OWNER_ID=-239286699
VK_GROUP_ID=239286699
VK_BROWSER_ENABLE=1
VK_BROWSER_STATE_PATH=out/vk_browser_state.json
VK_BROWSER_GROUP_URL=https://vk.com/club239286699
VK_BROWSER_HEADLESS=0
VK_BROWSER_CONFIRM_BEFORE_POST=0
VK_POST_LIMIT_PER_RUN=3
```

### Какие Поля Заполняет Заказчик

Для текущего MVP WB -> VK заказчику обычно нужно заполнить только VK-блок:

| Поле | Обязательно | Значение |
| --- | --- | --- |
| `VK_OWNER_ID` | Да | ID стены. Для группы с минусом: `-239286699`. |
| `VK_GROUP_ID` | Да | ID группы без минуса: `239286699`. |
| `VK_BROWSER_GROUP_URL` | Да | Ссылка на группу: `https://vk.com/club239286699`. |
| `VK_BROWSER_ENABLE` | Да | `1`, иначе browser-публикация будет заблокирована. |
| `VK_BROWSER_STATE_PATH` | Да | Куда сохранить VK-сессию, обычно `out/vk_browser_state.json`. |
| `VK_BROWSER_HEADLESS` | Нет | `0` для видимого браузера. |
| `VK_BROWSER_CONFIRM_BEFORE_POST` | Нет | `0` для автопубликации, `1` для ручной проверки перед отправкой. |
| `VK_POST_LIMIT_PER_RUN` | Нет | Лимит публикаций за запуск, например `3`. |

Поля `WB_AUTOPOSTER_DB_PATH` и `WB_AUTOPOSTER_OUT_DIR` можно оставить как в примере. Они отвечают только за локальное хранение базы и файлов.

Поля для WB API, VK API, Pinterest, Instagram и `wb-public` не нужны для текущего реального VK MVP. Они поддержаны в коде как roadmap/API-ready направления, но не входят в основной сценарий показа и не добавлены в `.env.example`.

Для Zernio-пилота дополнительно понадобятся `ZERNIO_API_KEY`, ID подключенных аккаунтов и `ZERNIO_PINTEREST_BOARD_ID`. Пока этих доступов нет, dry-run Pinterest/Instagram остается безопасным локальным режимом.

## Что Запросить У Заказчика

Для пилота VK:

- VK-группа или тестовая группа;
- аккаунт с правами публикации в группе;
- 3-10 реальных `nmID` товаров;
- URL продавца/бренда на WB для browser baseline.

Для стабильного запуска через API:

- WB Seller API token с доступом к Content;
- доступ к Prices and Discounts;
- доступ к Analytics/Reports или токен, который покрывает эти категории;
- VK user OAuth/API-доступ для публикации с фото;
- VPS/Docker/scheduler, если нужен регулярный запуск без ноутбука;
- Pinterest approved app, рабочий сайт и privacy policy, если Pinterest остается в плане.

Для Zernio-пилота Pinterest/Instagram:

- Zernio account и API key;
- подключенный Pinterest account и board ID;
- подключенный Instagram account;
- публично доступные URL изображений товаров или разрешение использовать Zernio media upload;
- подтверждение, какие платформы запускать в real publish и какой лимит постов за запуск использовать.

## Экономика

Базовая формула:

```text
прибыль = клики * конверсия WB * маржа_за_заказ - месячные_затраты
точка_окупаемости_по_кликам = месячные_затраты / (конверсия * маржа_за_заказ)
```

Для бизнес-оценки можно использовать примерный расчет:

```text
месячные затраты = 500 ₽
маржа за заказ = 600 ₽
конверсия клика в заказ = 1%
ожидаемая маржа с клика = 6 ₽
точка окупаемости = около 84 кликов/мес
```

Вывод: запуск имеет смысл, если бренд регулярно добавляет новые товары и готов системно развивать внешний трафик. При марже 600 ₽ и конверсии 1% один клик в среднем приносит 6 ₽ ожидаемой маржи. Чтобы окупить 500 ₽/мес поддержки, нужно около 84 переходов в месяц.

Если постить 50 новинок в месяц, нужно в среднем около 2 перехода с каждого поста. Это достижимо только при нормальном визуале, регулярности публикаций и UTM/redirect-аналитике.

Дополнительно автопостинг экономит ручное время команды. Если вручную публикация одной новинки занимает 5-10 минут, то при 50 новинках в месяц это около 4-8 часов работы. При стоимости часа сотрудника 500 ₽ это 2000-4000 ₽/мес экономии только на рутине, без учета дополнительных переходов на WB.

### Инфраструктура

Для пилота есть два варианта запуска.

#### 1. API-вариант: Linux VPS

Если WB и соцсети подключены через API, браузер не нужен. Достаточно легкого Linux VPS:

- 1 vCPU;
- 1 ГБ RAM;
- 10-20 ГБ SSD;
- cron/systemd timer.

Для тестового пилота можно использовать REG.RU Free Tier: 1 vCPU / 1 ГБ RAM / 10 ГБ SSD - 0 ₽/мес на период до 6 месяцев.

Для стабильного production с API лучше закладывать платный VPS: примерно 300-1000 ₽/мес. Например, недорогие Linux VPS на 1 CPU / 1 ГБ RAM обычно начинаются с 250-300 ₽/мес.

#### 2. Browser fallback: Windows/Linux машина с браузером

Если используется browser automation для WB/VK, нужен запас по памяти:

- 2 vCPU;
- 4 ГБ RAM;
- 40-60 ГБ SSD;
- Chrome;
- планировщик задач.

Ориентир по стоимости: 1000-2500 ₽/мес. Этот вариант дороже и менее надежен, потому что зависит от браузера и интерфейсов WB/VK, но подходит для MVP, пилота и временного боевого запуска без полноценного API-доступа.

Для текущего MVP инфраструктурные затраты равны нулю, потому что проект запускается локально. VPS, домен, HTTPS и регулярный scheduler относятся к следующему этапу.

Для пилота browser fallback подходит. Для стабильного production приоритет - WB Seller API и официальные API соцсетей.

## Тесты

```bash
python -m pytest
```

Покрытие включает:

- happy path для dry-run и CLI;
- отсутствие дублей;
- bad fixture и malformed JSON;
- невалидные товары;
- failed publish, retry failed и recover publishing;
- блокировку real publish без safety-флагов;
- baseline-sync и планирование только товаров после baseline;
- public WB fallback: baseline только по `nm_id`, scan-limit, `seen_products`, детали только для неизвестных карточек;
- WB API pagination/mapping и enrichment через цены/остатки;
- Pinterest payload validation, board check, UTM и API request/error handling;
- VK dry-run, payload validation, wall check, UTM, API request/error handling и photo upload chain;
- VK browser routing, safety switches и media download.

## Текущее Состояние Проекта

На текущем этапе проект работает как MVP автопостинга новинок WB:

- сканирует новые товары продавца WB через browser/public fallback и сохраняет антидубли в SQLite;
- перед публикацией генерирует короткие тексты для VK, Instagram и Pinterest одним запросом к Gemini;
- дополнительно строит SEO-данные карточки: keywords, hashtags, общий title и `pinterest_title`;
- применяет настраиваемые правила текста из `CONTENT_RULES_PATH`, чтобы убирать фразы вроде `Бренд: Wildberries`, запрещать клише и не тащить marketplace-бренд как бренд товара;
- публикует VK отдельной командой, Pinterest отдельной командой, Instagram отдельной командой или последовательно через `wb-social-cycle`;
- для Instagram не вставляет WB-ссылку в caption как основной CTA, а добавляет `Артикул WB: <nmID>`, потому что внешние ссылки в Instagram-постах не работают как нормальный кликабельный канал;
- для Pinterest передает WB-ссылку как destination link;
- соцметрики считаются через Zernio analytics по опубликованным Pinterest/Instagram постам, без redirect-ссылок.

Быстрый ручной прогон:

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/..." --scan-limit 100 --no-vk --pinterest --instagram --pinterest-zernio --dry-run --headless --no-manual-ready
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/..." --scan-limit 100 --no-vk --pinterest --instagram --pinterest-zernio --no-dry-run --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
python -m wb_autoposter.cli sync-metrics --platform all --limit 50
python -m wb_autoposter.cli metrics-report --platform all --limit 20
```

Если нужен полный прогон со всеми соцсетями, перед первым VK-постингом один раз сохраняется VK browser session:

```powershell
python -m wb_autoposter.cli vk-browser-login --start-url "https://vk.com/club239286699" --no-headless
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/..." --scan-limit 100 --vk --vk-browser --pinterest --instagram --pinterest-zernio --no-dry-run --vk-limit 1 --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
```

Для регулярного запуска на Windows есть готовые скрипты:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_social_cycle.ps1 -SellerUrl "https://www.wildberries.ru/seller/..." -RealPublish
powershell -ExecutionPolicy Bypass -File scripts\run_social_cycle.ps1 -SellerUrl "https://www.wildberries.ru/seller/..." -RealPublish -IncludeVk
powershell -ExecutionPolicy Bypass -File scripts\sync_metrics.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -SellerUrl "https://www.wildberries.ru/seller/..." -RealPublish -Force
```

`scripts\run_social_cycle.ps1` без `-RealPublish` запускает dry-run. VK в этом скрипте выключен по умолчанию и включается флагом `-IncludeVk`; перед этим должен существовать `out\vk_browser_state.json`. Для Linux/macOS пример cron лежит в `scripts/cron.example`.

## Roadmap

1. Локальный dry-run MVP - готово.
2. Реальная VK-публикация с картинкой через browser automation - готово.
3. Baseline-логика для реальных новинок - готово.
4. Public WB fallback без Seller API - готово и проверено на реальных публичных данных WB.
5. WB API режим через `WBEnrichedProductSource` - готово на уровне кода, нужны токены и тестовый прогон.
6. Добавить импорт выгрузки из кабинета WB (`seller-export`) как отдельный источник: CSV/XLSX с `nmID`, артикулами, статусом, ценой, остатками и датами. Использовать его для первичного baseline вместо browser-сбора, а при регулярной выгрузке - как источник новинок.
7. Протестировать `baseline-sync --mode real-ready` и последующий `run-cycle --mode real-ready` на реальном кабинете WB.
8. Redirect tracking не обязателен для MVP: соцметрики считаются через Zernio analytics, а WB-ссылки остаются прямыми/с UTM без подозрительного промежуточного домена.
9. Scheduler/autostart - добавлены Windows scheduled task scripts и cron example; VPS/Docker остается отдельным шагом, если нужен запуск без локального ПК.
10. Добавить простой web-admin.
11. Zernio publisher для Pinterest - добавлен и проверен реальной публикацией.
12. Zernio publisher для Instagram - добавлен и проверен реальной публикацией; в caption используется артикул WB вместо некликабельной ссылки.
13. Pinterest direct API: оставить как альтернативу, если заказчик хочет свой approved Pinterest Developer App, сайт/домен, privacy policy и OAuth token.
14. Instagram direct API: подключать только если бизнесу важнее охват, чем кликабельный внешний трафик, либо если Zernio не подходит.
