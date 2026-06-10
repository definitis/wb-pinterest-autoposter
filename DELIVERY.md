# Приемка Проекта

Этот файл нужен, чтобы быстро проверить MVP перед сдачей заказчику. Он не заменяет README, а дает короткий сценарий приемки.

## 1. Установка

```powershell
python -m pip install -e ".[dev]"
python -m playwright install chromium
copy .env.example .env
```

Заполнить `.env` реальными значениями для тех площадок, которые проверяются в реальном режиме. Секреты не коммитятся.

## 2. Быстрая Проверка Без Реальных Публикаций

Запустить delivery smoke-test:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_delivery.ps1
```

Скрипт проверяет:

- импорт Python-пакета и CLI;
- базовую конфигурацию test-mode;
- безопасный dry-run цикл на fixture-товарах;
- генерацию локального dashboard;
- focused pytest-проверки для dashboard/config.

Результаты появятся в:

```text
out/delivery_check/
```

Это безопасная проверка: реальные соцсети не затрагиваются.

## 3. Первичная Настройка Реального Запуска

Проверить Zernio:

```powershell
python -m wb_autoposter.cli zernio-check --platform pinterest
python -m wb_autoposter.cli zernio-check --platform instagram
```

Сохранить VK-сессию, если нужен VK:

```powershell
python -m wb_autoposter.cli vk-browser-login --start-url "https://vk.com/club239286699" --no-headless
```

Сделать baseline WB, чтобы текущий ассортимент не считался новинками:

```powershell
python -m wb_autoposter.cli wb-browser-baseline --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --user-data-dir out\wb_chrome_profile_baseline --max-scrolls 350 --idle-scrolls 40 --scroll-delay-ms 2500
```

Для проекта заказчика заменить `--seller-url` на страницу нужного продавца WB.

Важно по WB-браузеру:

- основной путь проекта для WB scan - Selenium + undetected Chrome, то есть команды без `--browser-engine playwright`;
- `--user-data-dir` должен быть одним и тем же для baseline, dry-run и real publish;
- первый запуск на новом профиле лучше делать в видимом браузере, без `--headless --no-manual-ready`, чтобы пройти cookies/регион/проверку WB;
- после успешного видимого запуска тот же профиль можно использовать в headless-режиме.

## 4. Проверка Реального Цикла

Сначала выполнить видимый dry-run на реальной странице WB. Когда браузер откроется, дождаться товаров, пройти возможные проверки WB и нажать Enter в терминале:

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --vk --pinterest --instagram --pinterest-zernio --dry-run --vk-limit 1 --pinterest-limit 1 --instagram-limit 1
```

После успешного видимого dry-run можно повторить headless dry-run:

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --vk --pinterest --instagram --pinterest-zernio --dry-run --vk-limit 1 --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
```

Если dry-run прошел, можно запускать реальную публикацию Pinterest + Instagram:

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --no-vk --pinterest --instagram --pinterest-zernio --no-dry-run --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
```

Если нужен VK, перед запуском должен существовать `out\vk_browser_state.json`:

```powershell
python -m wb_autoposter.cli wb-social-cycle --seller-url "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1" --scan-limit 100 --user-data-dir out\wb_chrome_profile_baseline --vk --vk-browser --pinterest --instagram --pinterest-zernio --no-dry-run --vk-limit 1 --pinterest-limit 1 --instagram-limit 1 --headless --no-manual-ready
```

## 5. Проверка Результата

```powershell
python -m wb_autoposter.cli status
python -m wb_autoposter.cli report
python -m wb_autoposter.cli sync-metrics --platform all --limit 50
python -m wb_autoposter.cli metrics-report --platform all --limit 20
python -m wb_autoposter.cli export-dashboard
```

Открыть локальный отчет:

```text
out/dashboard.html
```

В отчете должны быть видны статусы публикаций, ошибки, последние посты и метрики, если Zernio уже вернул analytics.
