# WB Autoposter

MVP для автопостинга новинок Wildberries в соцсети. Проект сканирует новые карточки продавца WB, сохраняет товары и статусы публикаций в SQLite, генерирует короткие тексты для соцсетей, публикует посты и подтягивает соцметрики.

Текущий рабочий стек:

- WB: browser/public scan страницы продавца, без Seller API токенов.
- VK: browser automation через сохраненную VK-сессию.
- Pinterest: Zernio real publish.
- Instagram: Zernio real publish.
- Тексты: Gemini одним запросом на товар сразу для VK, Instagram и Pinterest, с fallback без падения пайплайна.
- Метрики: Zernio analytics для Pinterest/Instagram.

## Как Это Работает

Обычный цикл:

```text
WB seller page
-> scan newest products
-> save/update products in SQLite
-> create planned posts without duplicates
-> generate/reuse social text
-> publish to selected platforms
-> save post status and external_id
-> sync social metrics from Zernio
```

Один товар публикуется максимум один раз в каждую площадку. Один и тот же товар может иметь отдельные посты VK, Pinterest и Instagram.

Для Instagram ссылка на WB не вставляется как основной CTA, потому что в обычном caption она не работает как нормальная кликабельная ссылка. Вместо этого добавляется `Артикул WB: <nmID>`. Для Pinterest WB-ссылка передается как destination link пина.

## Быстрый Старт

Установить зависимости:

```powershell
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

Проверить тесты:

```powershell
python -m pytest
```

Скопировать env:

```powershell
copy .env.example .env
```

Заполнить `.env` нужными значениями. Секреты и реальные ключи не коммитятся.

## Минимальный `.env`

Базовые поля:

```env
WB_AUTOPOSTER_DB_PATH=out/app.sqlite3
WB_AUTOPOSTER_OUT_DIR=out

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_REQUEST_INTERVAL_SECONDS=6
GEMINI_429_COOLDOWN_SECONDS=60
CONTENT_RULES_PATH=config/content_rules.example.json

ZERNIO_API_KEY=
ZERNIO_ENABLE_REAL_PUBLISH=1
ZERNIO_PINTEREST_ACCOUNT_ID=
ZERNIO_PINTEREST_BOARD_ID=
ZERNIO_INSTAGRAM_ACCOUNT_ID=
ZERNIO_INSTAGRAM_CONTENT_TYPE=feed

VK_OWNER_ID=
VK_GROUP_ID=
VK_BROWSER_GROUP_URL=
VK_BROWSER_ENABLE=1
VK_BROWSER_STATE_PATH=out/vk_browser_state.json
VK_BROWSER_HEADLESS=0
VK_BROWSER_CONFIRM_BEFORE_POST=0

PINTEREST_POST_LIMIT_PER_RUN=1
INSTAGRAM_POST_LIMIT_PER_RUN=1
VK_POST_LIMIT_PER_RUN=1
```

`VK_OWNER_ID` для группы указывается с минусом. Например, для `https://vk.com/club239286699`:

```env
VK_OWNER_ID=-239286699
VK_GROUP_ID=239286699
VK_BROWSER_GROUP_URL=https://vk.com/club239286699
```

## Первичная Настройка

### 1. Проверить Zernio

```powershell
python -m wb_autoposter.cli zernio-check --platform pinterest
python -m wb_autoposter.cli zernio-check --platform instagram
```

Обе команды должны показать подключенный аккаунт и заполненные account/board ID.

### 2. Сохранить VK-сессию

Для реального VK-постинга один раз нужно войти в VK через браузер:

```powershell
python -m wb_autoposter.cli vk-browser-login --start-url "https://vk.com/club239286699" --no-headless
```

После логина должен появиться файл:

```text
out/vk_browser_state.json
```

Если этого файла нет, реальный VK-запуск остановится с ошибкой:

```text
VK browser session not found. Run vk-browser-login first.
```

### 3. Сделать baseline WB

Baseline нужен, чтобы не считать весь текущий ассортимент новинками.

```powershell
python -m wb_autoposter.cli wb-browser-baseline --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --user-data-dir out\wb_chrome_profile_baseline --max-scrolls 350 --idle-scrolls 40 --scroll-delay-ms 2500
```

Для другого продавца заменить `--seller-url`. Если известен примерный размер каталога, можно дополнительно указать `--expected-count` как quality-check.

## Основной Запуск

### Безопасный dry-run

Dry-run проходит весь пайплайн, но не публикует реальные посты:

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --vk --pinterest --instagram --pinterest-zernio --dry-run --vk-limit 1 --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
```

### Реальный запуск Pinterest + Instagram

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --no-vk --pinterest --instagram --pinterest-zernio --no-dry-run --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
```

### Реальный запуск всех соцсетей

Перед этим должен существовать `out\vk_browser_state.json`.

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --vk --vk-browser --pinterest --instagram --pinterest-zernio --no-dry-run --vk-limit 1 --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
```

### Отдельные команды по площадкам

VK:

```powershell
python -m wb_autoposter.cli wb-vk-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --browser --no-dry-run --limit 1
```

Pinterest:

```powershell
python -m wb_autoposter.cli wb-pinterest-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --zernio --no-dry-run --limit 1 --headless --no-manual-ready
```

Instagram:

```powershell
python -m wb_autoposter.cli wb-instagram-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --zernio --no-dry-run --limit 1 --headless --no-manual-ready
```

## Проверка Результата

Посмотреть статусы товаров и постов:

```powershell
python -m wb_autoposter.cli status
python -m wb_autoposter.cli report
```

Синхронизировать соцметрики Pinterest/Instagram:

```powershell
python -m wb_autoposter.cli sync-metrics --platform all --limit 50
python -m wb_autoposter.cli metrics-report --platform all --limit 20
```

Если Zernio возвращает `pending`, это нормально: метрики у свежего поста могут быть еще не готовы. Повторный запуск позже сохранит новый снимок.

## Генерация Текстов

Gemini используется только как улучшение текста. Если ключа нет, JSON не распарсился, ответ не подходит карточке или пришел `429 Too Many Requests`, пайплайн не падает и использует fallback-тексты.

Важные правила:

- один товар = один Gemini-запрос;
- один ответ содержит тексты сразу для `vk`, `instagram`, `pinterest`;
- если текст уже сохранен в payload и товар не изменился, повторный запуск не дергает Gemini заново;
- `GEMINI_REQUEST_INTERVAL_SECONDS` задает паузу между запросами по разным товарам;
- `GEMINI_429_COOLDOWN_SECONDS` задает cooldown после rate limit.

Правила текста можно менять без правки кода через:

```env
CONTENT_RULES_PATH=config/content_rules.example.json
```

В этом файле настраиваются запретные фразы, generic marketplace-бренды, SEO stopwords и заблокированные хэштеги.

## Соцметрики

Сейчас соцметрики считаются через Zernio analytics:

- Pinterest: impressions, clicks, saves и другие доступные поля.
- Instagram: reach/views/likes/comments/saves. Переходы по WB-ссылке из caption честно не считаются кликабельным трафиком.

Redirect tracking сейчас не используется: WB-ссылки остаются прямыми или с UTM, без подозрительного промежуточного домена.

## Регулярный Запуск

Для Windows есть готовые скрипты:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_social_cycle.ps1 -SellerUrl "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" -RealPublish
powershell -ExecutionPolicy Bypass -File scripts\run_social_cycle.ps1 -SellerUrl "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" -RealPublish -IncludeVk
powershell -ExecutionPolicy Bypass -File scripts\sync_metrics.ps1
```

Создать Windows Scheduled Tasks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -SellerUrl "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" -RealPublish -Force
```

`scripts\run_social_cycle.ps1` без `-RealPublish` запускает dry-run. VK в этом скрипте выключен по умолчанию и включается флагом `-IncludeVk`; перед этим должен существовать `out\vk_browser_state.json`.

Для Linux/macOS пример лежит в:

```text
scripts/cron.example
```

## Файлы И Артефакты

Основные файлы:

- `out/app.sqlite3` - локальная SQLite-база.
- `out/wb_browser_new_scan_products.json` - последний результат WB scan.
- `out/zernio_post_*.json` - request/response реальной публикации через Zernio.
- `out/vk_browser_state.json` - сохраненная VK-сессия.
- `out/vk_browser_media/` - скачанные фото перед VK browser publish.
- `out/vk_browser_debug/` - debug-артефакты при ошибках VK automation.
- `config/content_rules.example.json` - пример правил текста.

`out/` можно удалить, но если удалить `out/vk_browser_state.json`, придется снова выполнить `vk-browser-login`.

## Частые Проблемы

### `VK browser session not found`

Нужно один раз выполнить:

```powershell
python -m wb_autoposter.cli vk-browser-login --start-url "https://vk.com/club239286699" --no-headless
```

### Gemini `429 Too Many Requests`

Это rate limit. Проект включит cooldown и продолжит через fallback. Для более мягкого режима увеличить:

```env
GEMINI_REQUEST_INTERVAL_SECONDS=10
GEMINI_429_COOLDOWN_SECONDS=120
```

### Новых товаров нет

Это нормальный результат. Значит WB scan не нашел nmID, которых еще нет в базе:

```text
New nmIDs detected: 0
```

Если нужно проверить публикацию прямо сейчас, можно использовать уже planned-посты в базе или временно снизить baseline/использовать тестовую базу.

### Zernio metrics pending

У свежих постов аналитика может быть еще не готова. Запустить позже:

```powershell
python -m wb_autoposter.cli sync-metrics --platform all --limit 50
```

## Тесты

```powershell
python -m pytest
```

Текущий набор покрывает CLI, WB sources, storage, publishers, Zernio metrics, content generation, SEO/text rules и browser-related контракты.

## Что Осталось Для Production

- Прогнать 3-7 дней регулярного запуска и посмотреть реальные ошибки.
- Решить, где будет жить scheduler: локальный Windows ПК или VPS/сервер.
- При необходимости сделать простой web-admin для просмотра очереди, ошибок и метрик.
- Отполировать `config/content_rules.example.json` по 20-30 реальным публикациям.
