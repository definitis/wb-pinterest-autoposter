from __future__ import annotations

import json
import re
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from wb_autoposter.models import Product


SOURCE_NAME = "wb-browser"


@dataclass(frozen=True)
class WBBrowserBaselineResult:
    nm_ids: list[int]
    output_path: Path | None
    iterations: int


@dataclass(frozen=True)
class WBBrowserProductCard:
    nm_id: int
    title: str
    price: float | None
    photo_url: str | None
    url: str


@dataclass(frozen=True)
class WBBrowserProductScanResult:
    nm_ids: list[int]
    products: list[Product]
    output_path: Path | None
    iterations: int


def collect_wb_seller_nm_ids(
    *,
    seller_url: str,
    browser_engine: str = "selenium",
    expected_count: int | None = None,
    supplier_id: int | None = None,
    catalog_dest: str = "-1257786",
    catalog_sort: str = "newly",
    catalog_max_pages: int = 100,
    catalog_request_delay_ms: int = 1200,
    catalog_retries: int = 3,
    output_path: Path | None = None,
    state_path: Path | None = None,
    browser_channel: str | None = None,
    user_data_dir: Path | None = None,
    cdp_url: str | None = None,
    chrome_binary: Path | None = None,
    chromedriver_path: Path | None = None,
    auto_install_driver: bool = True,
    headless: bool = False,
    manual_ready: bool = False,
    ready_delay_seconds: float = 2.0,
    max_scrolls: int = 250,
    idle_scrolls: int = 12,
    scroll_delay_ms: int = 1400,
    scroll_pixels: int = 1800,
) -> WBBrowserBaselineResult:
    """Collect nmIDs from a WB seller page rendered in a real browser.

    This is a public fallback for one-time baseline creation. WB can show
    antibot checks, so visible browser mode with manual confirmation is the
    default.
    """
    _validate_collect_options(
        browser_engine=browser_engine,
        expected_count=expected_count,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
    )

    if browser_engine == "selenium":
        return _collect_wb_seller_nm_ids_with_selenium(
            seller_url=seller_url,
            expected_count=expected_count,
            supplier_id=supplier_id,
            catalog_dest=catalog_dest,
            catalog_sort=catalog_sort,
            catalog_max_pages=catalog_max_pages,
            catalog_request_delay_ms=catalog_request_delay_ms,
            catalog_retries=catalog_retries,
            output_path=output_path,
            user_data_dir=user_data_dir,
            chrome_binary=chrome_binary,
            chromedriver_path=chromedriver_path,
            auto_install_driver=auto_install_driver,
            headless=headless,
            manual_ready=manual_ready,
            ready_delay_seconds=ready_delay_seconds,
            max_scrolls=max_scrolls,
            idle_scrolls=idle_scrolls,
            scroll_delay_ms=scroll_delay_ms,
            scroll_pixels=scroll_pixels,
        )
    return _collect_wb_seller_nm_ids_with_playwright(
        seller_url=seller_url,
        expected_count=expected_count,
        supplier_id=supplier_id,
        catalog_dest=catalog_dest,
        catalog_sort=catalog_sort,
        catalog_max_pages=catalog_max_pages,
        catalog_request_delay_ms=catalog_request_delay_ms,
        catalog_retries=catalog_retries,
        output_path=output_path,
        state_path=state_path,
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        cdp_url=cdp_url,
        headless=headless,
        manual_ready=manual_ready,
        ready_delay_seconds=ready_delay_seconds,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
        scroll_delay_ms=scroll_delay_ms,
        scroll_pixels=scroll_pixels,
    )


def collect_wb_seller_product_cards(
    *,
    seller_url: str,
    browser_engine: str = "selenium",
    scan_limit: int = 100,
    output_path: Path | None = None,
    state_path: Path | None = None,
    browser_channel: str | None = None,
    user_data_dir: Path | None = None,
    cdp_url: str | None = None,
    chrome_binary: Path | None = None,
    chromedriver_path: Path | None = None,
    auto_install_driver: bool = True,
    headless: bool = False,
    manual_ready: bool = False,
    ready_delay_seconds: float = 2.0,
    max_scrolls: int = 80,
    idle_scrolls: int = 8,
    scroll_delay_ms: int = 1400,
    scroll_pixels: int = 1800,
) -> WBBrowserProductScanResult:
    """Collect top product cards from a WB seller page sorted by newness."""
    if scan_limit < 1:
        raise ValueError("scan_limit must be greater than zero.")
    _validate_collect_options(
        browser_engine=browser_engine,
        expected_count=None,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
    )

    if browser_engine == "selenium":
        return _collect_wb_seller_product_cards_with_selenium(
            seller_url=seller_url,
            scan_limit=scan_limit,
            output_path=output_path,
            user_data_dir=user_data_dir,
            chrome_binary=chrome_binary,
            chromedriver_path=chromedriver_path,
            auto_install_driver=auto_install_driver,
            headless=headless,
            manual_ready=manual_ready,
            ready_delay_seconds=ready_delay_seconds,
            max_scrolls=max_scrolls,
            idle_scrolls=idle_scrolls,
            scroll_delay_ms=scroll_delay_ms,
            scroll_pixels=scroll_pixels,
        )
    return _collect_wb_seller_product_cards_with_playwright(
        seller_url=seller_url,
        scan_limit=scan_limit,
        output_path=output_path,
        state_path=state_path,
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        cdp_url=cdp_url,
        headless=headless,
        manual_ready=manual_ready,
        ready_delay_seconds=ready_delay_seconds,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
        scroll_delay_ms=scroll_delay_ms,
        scroll_pixels=scroll_pixels,
    )


def _collect_wb_seller_nm_ids_with_playwright(
    *,
    seller_url: str,
    expected_count: int | None,
    supplier_id: int | None,
    catalog_dest: str,
    catalog_sort: str,
    catalog_max_pages: int,
    catalog_request_delay_ms: int,
    catalog_retries: int,
    output_path: Path | None,
    state_path: Path | None,
    browser_channel: str | None,
    user_data_dir: Path | None,
    cdp_url: str | None,
    headless: bool,
    manual_ready: bool,
    ready_delay_seconds: float,
    max_scrolls: int,
    idle_scrolls: int,
    scroll_delay_ms: int,
    scroll_pixels: int,
) -> WBBrowserBaselineResult:
    sync_playwright = _load_sync_playwright()

    if state_path is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
    if user_data_dir is not None:
        user_data_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1365, "height": 900},
            "locale": "ru-RU",
        }
        if state_path is not None and state_path.exists() and user_data_dir is None and cdp_url is None:
            context_kwargs["storage_state"] = str(state_path)

        browser = None
        context = None
        if cdp_url:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context(**context_kwargs)
        elif user_data_dir is not None:
            launch_kwargs: dict[str, Any] = {"headless": headless, **context_kwargs}
            if browser_channel:
                launch_kwargs["channel"] = browser_channel
            context = playwright.chromium.launch_persistent_context(str(user_data_dir), **launch_kwargs)
        else:
            launch_kwargs = {"headless": headless}
            if browser_channel:
                launch_kwargs["channel"] = browser_channel
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(**context_kwargs)

        page = context.new_page()
        page.goto(seller_url, wait_until="domcontentloaded", timeout=60000)

        if manual_ready:
            input(
                "Open WB page in the browser, pass checks/select sorting if needed, "
                "then press Enter here to start collecting nmIDs..."
            )
        else:
            page.wait_for_timeout(int(ready_delay_seconds * 1000))

        if supplier_id is not None:
            found, iterations = _collect_catalog_nm_ids_with_playwright(
                page,
                supplier_id=supplier_id,
                dest=catalog_dest,
                sort=catalog_sort,
                expected_count=expected_count,
                max_pages=catalog_max_pages,
                request_delay_ms=catalog_request_delay_ms,
                retries=catalog_retries,
            )
        else:
            if not _ensure_all_products_section_playwright(page, scroll_pixels, scroll_delay_ms):
                raise ValueError("Could not find the WB seller 'All products' section.")
            found, iterations = _scroll_and_collect(
                extract=lambda: _extract_nm_ids_from_page(page),
                scroll=lambda: _playwright_scroll(page, scroll_pixels, scroll_delay_ms),
                expected_count=expected_count,
                max_scrolls=max_scrolls,
                idle_scrolls=idle_scrolls,
            )
            found = _merge_nm_ids(found, _extract_nm_ids_from_page(page))
        if state_path is not None:
            context.storage_state(path=str(state_path))
        if cdp_url:
            page.close()
        else:
            context.close()
        if browser is not None and not cdp_url:
            browser.close()

    _write_nm_ids(output_path, found)
    return WBBrowserBaselineResult(nm_ids=found, output_path=output_path, iterations=iterations)


def _collect_wb_seller_nm_ids_with_selenium(
    *,
    seller_url: str,
    expected_count: int | None,
    supplier_id: int | None,
    catalog_dest: str,
    catalog_sort: str,
    catalog_max_pages: int,
    catalog_request_delay_ms: int,
    catalog_retries: int,
    output_path: Path | None,
    user_data_dir: Path | None,
    chrome_binary: Path | None,
    chromedriver_path: Path | None,
    auto_install_driver: bool,
    headless: bool,
    manual_ready: bool,
    ready_delay_seconds: float,
    max_scrolls: int,
    idle_scrolls: int,
    scroll_delay_ms: int,
    scroll_pixels: int,
) -> WBBrowserBaselineResult:
    driver = _create_undetected_chrome_driver(
        user_data_dir=user_data_dir,
        chrome_binary=chrome_binary,
        chromedriver_path=chromedriver_path,
        auto_install_driver=auto_install_driver,
        headless=headless,
    )
    try:
        driver.get(seller_url)
        if manual_ready:
            input(
                "Open WB page in Chrome, pass checks/select sorting if needed, "
                "then press Enter here to start collecting nmIDs..."
            )
        else:
            sleep(ready_delay_seconds)

        if supplier_id is not None:
            found, iterations = _collect_catalog_nm_ids_with_selenium(
                driver,
                supplier_id=supplier_id,
                dest=catalog_dest,
                sort=catalog_sort,
                expected_count=expected_count,
                max_pages=catalog_max_pages,
                request_delay_ms=catalog_request_delay_ms,
                retries=catalog_retries,
            )
        else:
            if not _ensure_all_products_section_selenium(driver, scroll_pixels, scroll_delay_ms):
                raise ValueError("Could not find the WB seller 'All products' section.")
            found, iterations = _scroll_and_collect(
                extract=lambda: _extract_nm_ids_from_selenium(driver),
                scroll=lambda: _selenium_scroll(driver, scroll_pixels, scroll_delay_ms),
                expected_count=expected_count,
                max_scrolls=max_scrolls,
                idle_scrolls=idle_scrolls,
            )
            found = _merge_nm_ids(found, _extract_nm_ids_from_selenium(driver))
    finally:
        driver.quit()

    _write_nm_ids(output_path, found)
    return WBBrowserBaselineResult(nm_ids=found, output_path=output_path, iterations=iterations)


def _collect_wb_seller_product_cards_with_playwright(
    *,
    seller_url: str,
    scan_limit: int,
    output_path: Path | None,
    state_path: Path | None,
    browser_channel: str | None,
    user_data_dir: Path | None,
    cdp_url: str | None,
    headless: bool,
    manual_ready: bool,
    ready_delay_seconds: float,
    max_scrolls: int,
    idle_scrolls: int,
    scroll_delay_ms: int,
    scroll_pixels: int,
) -> WBBrowserProductScanResult:
    sync_playwright = _load_sync_playwright()

    if state_path is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
    if user_data_dir is not None:
        user_data_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1365, "height": 900},
            "locale": "ru-RU",
        }
        if state_path is not None and state_path.exists() and user_data_dir is None and cdp_url is None:
            context_kwargs["storage_state"] = str(state_path)

        browser = None
        if cdp_url:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context(**context_kwargs)
        elif user_data_dir is not None:
            launch_kwargs: dict[str, Any] = {"headless": headless, **context_kwargs}
            if browser_channel:
                launch_kwargs["channel"] = browser_channel
            context = playwright.chromium.launch_persistent_context(str(user_data_dir), **launch_kwargs)
        else:
            launch_kwargs = {"headless": headless}
            if browser_channel:
                launch_kwargs["channel"] = browser_channel
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(**context_kwargs)

        page = context.new_page()
        page.goto(seller_url, wait_until="domcontentloaded", timeout=60000)
        if manual_ready:
            input(
                "Open WB page in the browser, pass checks/select sorting if needed, "
                "then press Enter here to scan new product cards..."
            )
        else:
            page.wait_for_timeout(int(ready_delay_seconds * 1000))
        if not _ensure_all_products_section_playwright(page, scroll_pixels, scroll_delay_ms):
            raise ValueError("Could not find the WB seller 'All products' section.")

        cards, iterations = _scroll_and_collect_cards(
            extract=lambda: _extract_product_cards_from_page(page),
            scroll=lambda: _playwright_scroll(page, scroll_pixels, scroll_delay_ms),
            scan_limit=scan_limit,
            max_scrolls=max_scrolls,
            idle_scrolls=idle_scrolls,
        )
        cards = _merge_product_cards(cards, _extract_product_cards_from_page(page))[:scan_limit]
        if state_path is not None:
            context.storage_state(path=str(state_path))
        if cdp_url:
            page.close()
        else:
            context.close()
        if browser is not None and not cdp_url:
            browser.close()

    return _product_scan_result(cards, output_path, iterations)


def _collect_wb_seller_product_cards_with_selenium(
    *,
    seller_url: str,
    scan_limit: int,
    output_path: Path | None,
    user_data_dir: Path | None,
    chrome_binary: Path | None,
    chromedriver_path: Path | None,
    auto_install_driver: bool,
    headless: bool,
    manual_ready: bool,
    ready_delay_seconds: float,
    max_scrolls: int,
    idle_scrolls: int,
    scroll_delay_ms: int,
    scroll_pixels: int,
) -> WBBrowserProductScanResult:
    driver = _create_undetected_chrome_driver(
        user_data_dir=user_data_dir,
        chrome_binary=chrome_binary,
        chromedriver_path=chromedriver_path,
        auto_install_driver=auto_install_driver,
        headless=headless,
    )
    try:
        driver.get(seller_url)
        if manual_ready:
            input(
                "Open WB page in Chrome, pass checks/select sorting if needed, "
                "then press Enter here to scan new product cards..."
            )
        else:
            sleep(ready_delay_seconds)
        if not _ensure_all_products_section_selenium(driver, scroll_pixels, scroll_delay_ms):
            raise ValueError("Could not find the WB seller 'All products' section.")

        cards, iterations = _scroll_and_collect_cards(
            extract=lambda: _extract_product_cards_from_selenium(driver),
            scroll=lambda: _selenium_scroll(driver, scroll_pixels, scroll_delay_ms),
            scan_limit=scan_limit,
            max_scrolls=max_scrolls,
            idle_scrolls=idle_scrolls,
        )
        cards = _merge_product_cards(cards, _extract_product_cards_from_selenium(driver))[:scan_limit]
    finally:
        driver.quit()

    return _product_scan_result(cards, output_path, iterations)


def extract_nm_ids_from_html(html: str) -> list[int]:
    """Extract WB nmIDs from rendered HTML snippets for tests/import helpers."""
    matches = re.findall(r"/catalog/(\d+)/detail\.aspx", html)
    return _merge_nm_ids([], [int(match) for match in matches])


def extract_product_cards_from_html(html: str) -> list[WBBrowserProductCard]:
    """Extract basic WB product cards from rendered HTML snippets for tests."""
    cards: list[WBBrowserProductCard] = []
    pattern = re.compile(
        r"<a[^>]+href=[\"'](?P<href>[^\"']*/catalog/(?P<nm_id>\d+)/detail\.aspx[^\"']*)[\"'][^>]*>"
        r"(?P<body>.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        body = re.sub(r"<[^>]+>", " ", match.group("body"))
        title = " ".join(body.split()) or f"WB товар {match.group('nm_id')}"
        cards.append(
            WBBrowserProductCard(
                nm_id=int(match.group("nm_id")),
                title=title,
                price=_parse_price_from_text(body),
                photo_url=None,
                url=_normalize_wb_product_url(match.group("href")),
            )
        )
    return _merge_product_cards([], cards)


def _validate_collect_options(
    *,
    browser_engine: str,
    expected_count: int | None,
    max_scrolls: int,
    idle_scrolls: int,
) -> None:
    if browser_engine not in {"selenium", "playwright"}:
        raise ValueError("browser_engine must be 'selenium' or 'playwright'.")
    if max_scrolls < 1:
        raise ValueError("max_scrolls must be greater than zero.")
    if idle_scrolls < 1:
        raise ValueError("idle_scrolls must be greater than zero.")
    if expected_count is not None and expected_count < 1:
        raise ValueError("expected_count must be greater than zero.")


def _write_nm_ids(output_path: Path | None, nm_ids: list[int]) -> None:
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(nm_ids, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_product_cards(output_path: Path | None, cards: list[WBBrowserProductCard]) -> None:
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([asdict(card) for card in cards], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _product_scan_result(
    cards: list[WBBrowserProductCard],
    output_path: Path | None,
    iterations: int,
) -> WBBrowserProductScanResult:
    _write_product_cards(output_path, cards)
    return WBBrowserProductScanResult(
        nm_ids=[card.nm_id for card in cards],
        products=[_product_from_card(card) for card in cards],
        output_path=output_path,
        iterations=iterations,
    )


def _scroll_and_collect(
    *,
    extract,
    scroll,
    expected_count: int | None,
    max_scrolls: int,
    idle_scrolls: int,
) -> tuple[list[int], int]:
    found: list[int] = []
    previous_count = 0
    idle_count = 0
    iterations = 0
    for iterations in range(1, max_scrolls + 1):
        found = _merge_nm_ids(found, extract())
        current_count = len(found)

        if expected_count is not None and current_count >= expected_count:
            break

        if current_count == previous_count:
            idle_count += 1
        else:
            idle_count = 0
            previous_count = current_count

        if idle_count >= idle_scrolls:
            break

        scroll()
    return found, iterations


def _scroll_and_collect_cards(
    *,
    extract,
    scroll,
    scan_limit: int,
    max_scrolls: int,
    idle_scrolls: int,
) -> tuple[list[WBBrowserProductCard], int]:
    found: list[WBBrowserProductCard] = []
    previous_count = 0
    idle_count = 0
    iterations = 0
    for iterations in range(1, max_scrolls + 1):
        found = _merge_product_cards(found, extract())[:scan_limit]
        current_count = len(found)

        if current_count >= scan_limit:
            break

        if current_count == previous_count:
            idle_count += 1
        else:
            idle_count = 0
            previous_count = current_count

        if idle_count >= idle_scrolls:
            break

        scroll()
    return found, iterations


def _collect_catalog_nm_ids_with_selenium(
    driver: Any,
    *,
    supplier_id: int,
    dest: str,
    sort: str,
    expected_count: int | None,
    max_pages: int,
    request_delay_ms: int,
    retries: int,
) -> tuple[list[int], int]:
    found: list[int] = []
    iterations = 0
    for page_number in range(1, max_pages + 1):
        result = _fetch_catalog_page_with_selenium(
            driver,
            supplier_id=supplier_id,
            dest=dest,
            sort=sort,
            page_number=page_number,
            retries=retries,
            request_delay_ms=request_delay_ms,
        )
        iterations = page_number
        page_ids = result["ids"]
        if not page_ids:
            break
        found = _merge_nm_ids(found, page_ids)
        if expected_count is not None and len(found) >= expected_count:
            break
        sleep(request_delay_ms / 1000)
    return found, iterations


def _collect_catalog_nm_ids_with_playwright(
    page: Any,
    *,
    supplier_id: int,
    dest: str,
    sort: str,
    expected_count: int | None,
    max_pages: int,
    request_delay_ms: int,
    retries: int,
) -> tuple[list[int], int]:
    found: list[int] = []
    iterations = 0
    for page_number in range(1, max_pages + 1):
        result = _fetch_catalog_page_with_playwright(
            page,
            supplier_id=supplier_id,
            dest=dest,
            sort=sort,
            page_number=page_number,
            retries=retries,
            request_delay_ms=request_delay_ms,
        )
        iterations = page_number
        page_ids = result["ids"]
        if not page_ids:
            break
        found = _merge_nm_ids(found, page_ids)
        if expected_count is not None and len(found) >= expected_count:
            break
        page.wait_for_timeout(request_delay_ms)
    return found, iterations


def _fetch_catalog_page_with_selenium(
    driver: Any,
    *,
    supplier_id: int,
    dest: str,
    sort: str,
    page_number: int,
    retries: int,
    request_delay_ms: int,
) -> dict[str, Any]:
    last_error = "unknown catalog fetch error"
    attempts = max(1, retries)
    for _ in range(attempts):
        result = driver.execute_async_script(_CATALOG_FETCH_ASYNC_JS, supplier_id, dest, sort, page_number)
        if isinstance(result, dict) and result.get("ok"):
            ids = result.get("ids") if isinstance(result.get("ids"), list) else []
            return {"ids": [int(value) for value in ids if isinstance(value, int | float)]}
        if isinstance(result, dict):
            last_error = str(result.get("error") or result.get("text") or result.get("status") or last_error)
        sleep(request_delay_ms / 1000)
    raise ValueError(f"WB catalog page {page_number} fetch failed: {last_error}")


def _fetch_catalog_page_with_playwright(
    page: Any,
    *,
    supplier_id: int,
    dest: str,
    sort: str,
    page_number: int,
    retries: int,
    request_delay_ms: int,
) -> dict[str, Any]:
    last_error = "unknown catalog fetch error"
    attempts = max(1, retries)
    for _ in range(attempts):
        result = page.evaluate(
            _CATALOG_FETCH_PLAYWRIGHT_JS,
            {"supplierId": supplier_id, "dest": dest, "sort": sort, "page": page_number},
        )
        if isinstance(result, dict) and result.get("ok"):
            ids = result.get("ids") if isinstance(result.get("ids"), list) else []
            return {"ids": [int(value) for value in ids if isinstance(value, int | float)]}
        if isinstance(result, dict):
            last_error = str(result.get("error") or result.get("text") or result.get("status") or last_error)
        page.wait_for_timeout(request_delay_ms)
    raise ValueError(f"WB catalog page {page_number} fetch failed: {last_error}")


def _extract_nm_ids_from_page(page: Any) -> list[int]:
    values = page.evaluate(
        """
        () => {
          const ids = new Set();
          const add = (value) => {
            if (!value) return;
            const text = String(value);
            const hrefMatch = text.match(/\\/catalog\\/(\\d+)\\/detail\\.aspx/);
            if (hrefMatch) ids.add(Number(hrefMatch[1]));
            const numericMatch = text.match(/^\\d{5,}$/);
            if (numericMatch) ids.add(Number(text));
          };

          document.querySelectorAll('a[href]').forEach((node) => add(node.getAttribute('href')));
          document.querySelectorAll('[data-nm-id], [data-nmid], [data-nm]').forEach((node) => {
            add(node.getAttribute('data-nm-id'));
            add(node.getAttribute('data-nmid'));
            add(node.getAttribute('data-nm'));
          });

          return Array.from(ids);
        }
        """
    )
    return _merge_nm_ids([], [int(value) for value in values if isinstance(value, int | float)])


def _extract_product_cards_from_page(page: Any) -> list[WBBrowserProductCard]:
    values = page.evaluate(f"() => {{ {_PRODUCT_CARD_JS} }}")
    return _product_cards_from_js_values(values)


def _extract_nm_ids_from_selenium(driver: Any) -> list[int]:
    values = driver.execute_script(
        """
        const ids = new Set();
        const add = (value) => {
          if (!value) return;
          const text = String(value);
          const hrefMatch = text.match(/\\/catalog\\/(\\d+)\\/detail\\.aspx/);
          if (hrefMatch) ids.add(Number(hrefMatch[1]));
          const numericMatch = text.match(/^\\d{5,}$/);
          if (numericMatch) ids.add(Number(text));
        };

        document.querySelectorAll('a[href]').forEach((node) => add(node.getAttribute('href')));
        document.querySelectorAll('[data-nm-id], [data-nmid], [data-nm]').forEach((node) => {
          add(node.getAttribute('data-nm-id'));
          add(node.getAttribute('data-nmid'));
          add(node.getAttribute('data-nm'));
        });

        return Array.from(ids);
        """
    )
    if not isinstance(values, list):
        return []
    return _merge_nm_ids([], [int(value) for value in values if isinstance(value, int | float)])


def _extract_product_cards_from_selenium(driver: Any) -> list[WBBrowserProductCard]:
    values = driver.execute_script(_PRODUCT_CARD_JS)
    return _product_cards_from_js_values(values)


def _product_cards_from_js_values(values: Any) -> list[WBBrowserProductCard]:
    if not isinstance(values, list):
        return []
    cards: list[WBBrowserProductCard] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        nm_id = value.get("nm_id")
        if not isinstance(nm_id, int | float):
            continue
        title = str(value.get("title") or f"WB товар {int(nm_id)}").strip()
        price = value.get("price")
        cards.append(
            WBBrowserProductCard(
                nm_id=int(nm_id),
                title=title,
                price=float(price) if isinstance(price, int | float) and price > 0 else None,
                photo_url=str(value.get("photo_url")).strip() if value.get("photo_url") else None,
                url=_normalize_wb_product_url(str(value.get("url") or "")),
            )
        )
    return _merge_product_cards([], cards)


_CATALOG_FETCH_ASYNC_JS = """
const supplierId = arguments[0];
const dest = arguments[1];
const sort = arguments[2];
const page = arguments[3];
const done = arguments[4];
const url = `https://catalog.wb.ru/sellers/v4/catalog?appType=1&curr=rub&dest=${encodeURIComponent(dest)}&sort=${encodeURIComponent(sort)}&spp=30&supplier=${encodeURIComponent(supplierId)}&page=${encodeURIComponent(page)}`;
fetch(url, {credentials: 'include'})
  .then(async (response) => {
    const text = await response.text();
    if (!response.ok) {
      done({ok: false, status: response.status, text: text.slice(0, 200)});
      return;
    }
    const data = JSON.parse(text);
    const products = data.products || (data.data && data.data.products) || [];
    done({ok: true, status: response.status, ids: products.map((product) => product.id).filter(Boolean)});
  })
  .catch((error) => done({ok: false, error: String(error)}));
"""


_CATALOG_FETCH_PLAYWRIGHT_JS = """
async (args) => {
  const url = `https://catalog.wb.ru/sellers/v4/catalog?appType=1&curr=rub&dest=${encodeURIComponent(args.dest)}&sort=${encodeURIComponent(args.sort)}&spp=30&supplier=${encodeURIComponent(args.supplierId)}&page=${encodeURIComponent(args.page)}`;
  try {
    const response = await fetch(url, {credentials: 'include'});
    const text = await response.text();
    if (!response.ok) {
      return {ok: false, status: response.status, text: text.slice(0, 200)};
    }
    const data = JSON.parse(text);
    const products = data.products || (data.data && data.data.products) || [];
    return {ok: true, status: response.status, ids: products.map((product) => product.id).filter(Boolean)};
  } catch (error) {
    return {ok: false, error: String(error)};
  }
}
"""


_ALL_PRODUCTS_HELPER_JS = """
const allProductsRe = /(?:^|\\b)\\u0432\\u0441\\u0435\\s+\\u0442\\u043e\\u0432\\u0430\\u0440\\u044b(?:\\b|$)/i;
const cleanNodeText = (node) => String((node && (node.innerText || node.textContent)) || '')
  .replace(/\\s+/g, ' ')
  .trim();
const findAllProductsHeading = () => {
  const marked = document.querySelector('[data-wb-autoposter-all-products-heading="1"]');
  if (marked) return marked;
  const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,button,a,span,div'));
  const heading = nodes.find((node) => {
    const text = cleanNodeText(node);
    return text.length > 0 && text.length <= 80 && allProductsRe.test(text);
  }) || null;
  if (heading) heading.dataset.wbAutoposterAllProductsHeading = '1';
  return heading;
};
const isAfterAllProductsHeading = (node) => {
  const heading = findAllProductsHeading();
  if (!heading) return document.documentElement.dataset.wbAutoposterAllProductsSeen === '1';
  return Boolean(heading.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING);
};
"""


_NM_ID_JS = (
    _ALL_PRODUCTS_HELPER_JS
    + """
const ids = new Set();
const add = (value) => {
  if (!value) return;
  const text = String(value);
  const hrefMatch = text.match(/\\/catalog\\/(\\d+)\\/detail\\.aspx/);
  if (hrefMatch) ids.add(Number(hrefMatch[1]));
  const numericMatch = text.match(/^\\d{5,}$/);
  if (numericMatch) ids.add(Number(text));
};

document.querySelectorAll('a[href]').forEach((node) => {
  if (isAfterAllProductsHeading(node)) add(node.getAttribute('href'));
});
document.querySelectorAll('[data-nm-id], [data-nmid], [data-nm]').forEach((node) => {
  if (!isAfterAllProductsHeading(node)) return;
  add(node.getAttribute('data-nm-id'));
  add(node.getAttribute('data-nmid'));
  add(node.getAttribute('data-nm'));
});

return Array.from(ids);
"""
)


_PRODUCT_CARD_JS = """
const cards = [];
const seen = new Set();
""" + _ALL_PRODUCTS_HELPER_JS + """
const parsePrice = (text) => {
  if (!text) return null;
  const match = String(text).replace(/\\u00a0/g, ' ').match(/([0-9][0-9\\s]{1,12})\\s*(?:₽|руб)/i);
  if (!match) return null;
  const value = Number(match[1].replace(/\\s/g, ''));
  return Number.isFinite(value) && value > 0 ? value : null;
};
const cleanTitle = (text) => {
  if (!text) return '';
  return String(text)
    .replace(/\\s+/g, ' ')
    .replace(/\\b\\d[\\d\\s]*\\s*(?:₽|руб).*$/i, '')
    .trim();
};
const normalizeUrl = (href) => {
  try { return new URL(href, location.origin).href; } catch (e) { return href || ''; }
};
document.querySelectorAll('a[href*="/catalog/"][href*="/detail.aspx"]').forEach((anchor) => {
  if (!isAfterAllProductsHeading(anchor)) return;
  const href = anchor.getAttribute('href') || anchor.href || '';
  const match = href.match(/\\/catalog\\/(\\d+)\\/detail\\.aspx/);
  if (!match) return;
  const nmId = Number(match[1]);
  if (!Number.isFinite(nmId) || seen.has(nmId)) return;
  seen.add(nmId);

  const card = anchor.closest('[data-nm-id], [data-nmid], article, li, .product-card, .product-card__wrapper, .j-card-item, div') || anchor;
  const img = card.querySelector('img') || anchor.querySelector('img');
  const rawText = card.innerText || anchor.innerText || '';
  const imageUrl = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('src')) : null;
  const title =
    cleanTitle(anchor.getAttribute('aria-label')) ||
    cleanTitle(anchor.getAttribute('title')) ||
    cleanTitle(img && img.getAttribute('alt')) ||
    cleanTitle(rawText) ||
    `WB товар ${nmId}`;

  cards.push({
    nm_id: nmId,
    title,
    price: parsePrice(rawText),
    photo_url: imageUrl,
    url: normalizeUrl(href),
  });
});
return cards;
"""


_FIND_ALL_PRODUCTS_SECTION_JS = """
const allProductsRe = /(?:^|\\b)\\u0432\\u0441\\u0435\\s+\\u0442\\u043e\\u0432\\u0430\\u0440\\u044b(?:\\b|$)/i;
const cleanNodeText = (node) => String((node && (node.innerText || node.textContent)) || '')
  .replace(/\\s+/g, ' ')
  .trim();
const marked = document.querySelector('[data-wb-autoposter-all-products-heading="1"]');
if (marked) {
  marked.scrollIntoView({block: 'start', inline: 'nearest'});
  document.documentElement.dataset.wbAutoposterAllProductsSeen = '1';
  return true;
}
const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,button,a,span,div'));
const heading = nodes.find((node) => {
  const text = cleanNodeText(node);
  return text.length > 0 && text.length <= 80 && allProductsRe.test(text);
}) || null;
if (heading) {
  heading.dataset.wbAutoposterAllProductsHeading = '1';
  heading.scrollIntoView({block: 'start', inline: 'nearest'});
  document.documentElement.dataset.wbAutoposterAllProductsSeen = '1';
  return true;
}
window.scrollBy(0, arguments[0]);
return false;
"""


def _ensure_all_products_section_playwright(page: Any, scroll_pixels: int, scroll_delay_ms: int) -> bool:
    for _ in range(20):
        before = _page_metrics_playwright(page)
        found = page.evaluate(_FIND_ALL_PRODUCTS_SECTION_JS, scroll_pixels)
        if found:
            return True
        _wait_for_page_change_playwright(page, before, scroll_delay_ms)
    return False


def _ensure_all_products_section_selenium(driver: Any, scroll_pixels: int, scroll_delay_ms: int) -> bool:
    for _ in range(20):
        before = _page_metrics_selenium(driver)
        found = driver.execute_script(_FIND_ALL_PRODUCTS_SECTION_JS, scroll_pixels)
        if found:
            return True
        _wait_for_page_change_selenium(driver, before, scroll_delay_ms)
    return False


def _playwright_scroll(page: Any, scroll_pixels: int, scroll_delay_ms: int) -> None:
    before = _page_metrics_playwright(page)
    page.mouse.wheel(0, scroll_pixels)
    _wait_for_page_change_playwright(page, before, scroll_delay_ms)


def _selenium_scroll(driver: Any, scroll_pixels: int, scroll_delay_ms: int) -> None:
    before = _page_metrics_selenium(driver)
    driver.execute_script("window.scrollBy(0, arguments[0]);", scroll_pixels)
    _wait_for_page_change_selenium(driver, before, scroll_delay_ms)


_PAGE_METRICS_JS = """
return {
  height: Math.max(document.documentElement.scrollHeight || 0, document.body ? document.body.scrollHeight || 0 : 0),
  productLinks: document.querySelectorAll('a[href*="/catalog/"][href*="/detail.aspx"]').length
};
"""


def _page_metrics_playwright(page: Any) -> dict[str, int]:
    value = page.evaluate(f"() => {{ {_PAGE_METRICS_JS} }}")
    return _normalize_page_metrics(value)


def _page_metrics_selenium(driver: Any) -> dict[str, int]:
    value = driver.execute_script(_PAGE_METRICS_JS)
    return _normalize_page_metrics(value)


def _normalize_page_metrics(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"height": 0, "productLinks": 0}
    return {
        "height": int(value.get("height") or 0),
        "productLinks": int(value.get("productLinks") or 0),
    }


def _page_changed(before: dict[str, int], after: dict[str, int]) -> bool:
    return after["height"] > before["height"] or after["productLinks"] > before["productLinks"]


def _wait_for_page_change_playwright(page: Any, before: dict[str, int], timeout_ms: int) -> None:
    deadline = monotonic() + max(timeout_ms, 0) / 1000
    while monotonic() < deadline:
        page.wait_for_timeout(100)
        if _page_changed(before, _page_metrics_playwright(page)):
            return


def _wait_for_page_change_selenium(driver: Any, before: dict[str, int], timeout_ms: int) -> None:
    deadline = monotonic() + max(timeout_ms, 0) / 1000
    while monotonic() < deadline:
        sleep(0.1)
        if _page_changed(before, _page_metrics_selenium(driver)):
            return


def _create_undetected_chrome_driver(
    *,
    user_data_dir: Path | None,
    chrome_binary: Path | None,
    chromedriver_path: Path | None,
    auto_install_driver: bool,
    headless: bool,
) -> Any:
    try:
        import chromedriver_autoinstaller
        import undetected_chromedriver as uc
    except ImportError as exc:  # pragma: no cover - depends on local install
        raise RuntimeError(
            "Selenium WB browser baseline requires selenium, undetected-chromedriver, "
            "and chromedriver-autoinstaller. Run: python -m pip install -e \".[dev]\""
        ) from exc

    if auto_install_driver and chromedriver_path is None:
        installed_path = chromedriver_autoinstaller.install()
        chromedriver_path = Path(installed_path) if installed_path else None

    options = uc.ChromeOptions()
    options.add_argument("--lang=ru-RU")
    options.add_argument("--window-size=1365,900")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if user_data_dir is not None:
        user_data_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data_dir.resolve()}")
    if chrome_binary is not None:
        options.binary_location = str(chrome_binary)
    if headless:
        options.add_argument("--headless=new")

    kwargs: dict[str, Any] = {"options": options, "use_subprocess": True}
    if chromedriver_path is not None:
        kwargs["driver_executable_path"] = str(chromedriver_path)
    if chrome_binary is not None:
        kwargs["browser_executable_path"] = str(chrome_binary)

    try:
        return uc.Chrome(**kwargs)
    except Exception as exc:  # pragma: no cover - depends on local Chrome state
        profile_hint = f" Profile: {user_data_dir.resolve()}." if user_data_dir is not None else ""
        raise RuntimeError(
            "Could not start Chrome for WB browser automation. "
            "Close previous WB Chrome windows/processes that use the same --user-data-dir, "
            "or retry with a fresh profile directory."
            + profile_hint
            + f" Original error: {exc}"
        ) from exc


def _merge_nm_ids(existing: list[int], new_values: list[int]) -> list[int]:
    seen = set(existing)
    merged = list(existing)
    for value in new_values:
        nm_id = int(value)
        if nm_id <= 0 or nm_id in seen:
            continue
        seen.add(nm_id)
        merged.append(nm_id)
    return merged


def _merge_product_cards(
    existing: list[WBBrowserProductCard],
    new_values: list[WBBrowserProductCard],
) -> list[WBBrowserProductCard]:
    seen = {card.nm_id for card in existing}
    merged = list(existing)
    for card in new_values:
        if card.nm_id <= 0 or card.nm_id in seen:
            continue
        seen.add(card.nm_id)
        merged.append(card)
    return merged


def _product_from_card(card: WBBrowserProductCard) -> Product:
    now = datetime.now(UTC)
    return Product(
        nm_id=card.nm_id,
        brand="Wildberries",
        title=card.title,
        description="",
        photos=[card.photo_url] if card.photo_url else [],
        price=card.price,
        stock=1,
        created_at=now,
        updated_at=now,
        url=card.url or f"https://www.wildberries.ru/catalog/{card.nm_id}/detail.aspx",
    )


def _normalize_wb_product_url(value: str) -> str:
    match = re.search(r"/catalog/(\d+)/detail\.aspx", value)
    if match:
        return f"https://www.wildberries.ru/catalog/{match.group(1)}/detail.aspx"
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return ""


def _parse_price_from_text(value: str) -> float | None:
    match = re.search(r"([0-9][0-9\s]{1,12})\s*(?:₽|руб)", value, flags=re.IGNORECASE)
    if not match:
        return None
    parsed = int(match.group(1).replace(" ", ""))
    return float(parsed) if parsed > 0 else None


def _load_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on local install
        raise RuntimeError(
            "Playwright is required for WB browser baseline. "
            "Run: python -m pip install -e \".[dev]\" && python -m playwright install chromium"
        ) from exc
    return sync_playwright
