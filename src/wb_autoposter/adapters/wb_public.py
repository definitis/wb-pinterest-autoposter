from __future__ import annotations

from datetime import UTC, datetime
from time import sleep
from typing import Any

import httpx

from wb_autoposter.models import Product


class WBPublicCatalogSource:
    """Public Wildberries catalog fallback.

    It is intentionally separate from Seller API sources: public WB endpoints can
    change or rate-limit callers, so this source is a fallback for MVP/baseline
    discovery when Seller API access is unavailable.
    """

    SEARCH_ENDPOINT = "https://search.wb.ru/exactmatch/ru/common/v4/search"
    SOURCE_NAME = "wb-public"

    def __init__(
        self,
        *,
        query: str,
        supplier_id: int | None = None,
        brand: str | None = None,
        pages: int = 1,
        limit: int | None = None,
        dest: str = "-1257786",
        sort: str = "popular",
        retry_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not query.strip():
            raise ValueError("WB public source requires a search query.")
        if pages < 1:
            raise ValueError("pages must be greater than zero.")
        if limit is not None and limit < 1:
            raise ValueError("limit must be greater than zero.")

        self.query = query.strip()
        self.supplier_id = supplier_id
        self.brand = brand.strip() if brand else None
        self.pages = pages
        self.limit = limit
        self.dest = dest
        self.sort = sort
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.client = client or httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.wildberries.ru/",
            },
        )

    def fetch_nm_ids(self) -> list[int]:
        return [int(product["id"]) for product in self._fetch_catalog_products()]

    def fetch_products(self, nm_ids: list[int] | None = None) -> list[Product]:
        catalog_products = self._fetch_catalog_products()
        catalog_by_id = {int(product["id"]): product for product in catalog_products}
        target_nm_ids = list(dict.fromkeys(nm_ids if nm_ids is not None else catalog_by_id.keys()))

        products: list[Product] = []
        for nm_id in target_nm_ids:
            catalog_product = catalog_by_id.get(int(nm_id))
            detail = self._fetch_card_detail(int(nm_id))
            if catalog_product is None and detail is None:
                continue
            products.append(_map_public_product(int(nm_id), catalog_product, detail))
        return products

    def _fetch_catalog_products(self) -> list[dict[str, Any]]:
        return list(self._iter_catalog_products())

    def _iter_catalog_products(self):
        products: list[dict[str, Any]] = []
        seen: set[int] = set()

        for page in range(1, self.pages + 1):
            response = self._get_with_retries(
                self.SEARCH_ENDPOINT,
                params={
                    "appType": 1,
                    "curr": "rub",
                    "dest": self.dest,
                    "query": self.query,
                    "resultset": "catalog",
                    "sort": self.sort,
                    "spp": 0,
                    "page": page,
                },
            )
            data = response.json()
            page_products = _extract_products(data)
            if not page_products:
                break

            for product in page_products:
                nm_id = product.get("id")
                if not isinstance(nm_id, int) or nm_id in seen:
                    continue
                if not self._matches_filters(product):
                    continue

                seen.add(nm_id)
                products.append(product)
                yield product
                if self.limit is not None and len(products) >= self.limit:
                    return

    def _fetch_card_detail(self, nm_id: int) -> dict[str, Any] | None:
        for host in _candidate_basket_hosts(nm_id):
            url = _basket_card_url(nm_id, host)
            response = self._get_with_retries(url)
            if response.status_code == 404:
                continue
            return response.json()
        return None

    def _matches_filters(self, product: dict[str, Any]) -> bool:
        if self.supplier_id is not None and product.get("supplierId") != self.supplier_id:
            return False
        if self.brand is not None and str(product.get("brand", "")).casefold() != self.brand.casefold():
            return False
        return True

    def _get_with_retries(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(1, self.retry_attempts + 1):
            response = self.client.get(url, params=params)
            last_response = response
            if response.status_code == 404:
                return response
            if response.status_code not in {429, 498, 503}:
                response.raise_for_status()
                return response
            if attempt < self.retry_attempts:
                sleep(self.retry_delay_seconds * attempt)

        status = last_response.status_code if last_response is not None else "unknown"
        raise ValueError(
            f"WB public endpoint is temporarily unavailable or rate-limited: HTTP {status}. "
            "Reduce WB_PUBLIC_SCAN_LIMIT/WB_PUBLIC_PAGES or retry later."
        )


def _extract_products(data: dict[str, Any]) -> list[dict[str, Any]]:
    products = data.get("products")
    if isinstance(products, list):
        return [product for product in products if isinstance(product, dict)]
    nested_products = (data.get("data") or {}).get("products") if isinstance(data.get("data"), dict) else None
    if isinstance(nested_products, list):
        return [product for product in nested_products if isinstance(product, dict)]
    return []


def _map_public_product(
    nm_id: int,
    catalog_product: dict[str, Any] | None,
    detail: dict[str, Any] | None,
) -> Product:
    catalog_product = catalog_product or {}
    detail = detail or {}
    now = datetime.now(UTC)
    title = str(catalog_product.get("name") or detail.get("imt_name") or f"WB товар {nm_id}").strip()
    brand = str(catalog_product.get("brand") or (detail.get("selling") or {}).get("brand_name") or "Wildberries").strip()
    photo_count = int(catalog_product.get("pics") or (detail.get("media") or {}).get("photo_count") or 0)

    return Product(
        nm_id=nm_id,
        brand=brand,
        title=title,
        description=str(detail.get("description") or "").strip(),
        photos=_image_urls(nm_id, photo_count),
        price=_price_from_catalog_product(catalog_product),
        stock=int(catalog_product.get("totalQuantity") or 0),
        created_at=now,
        updated_at=now,
        url=f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx",
    )


def _price_from_catalog_product(product: dict[str, Any]) -> float | None:
    sizes = product.get("sizes")
    if not isinstance(sizes, list):
        return None
    for size in sizes:
        if not isinstance(size, dict):
            continue
        price = size.get("price")
        if not isinstance(price, dict):
            continue
        value = price.get("product") or price.get("basic")
        if isinstance(value, int | float) and value > 0:
            return float(value) / 100
    return None


def _image_urls(nm_id: int, photo_count: int) -> list[str]:
    if photo_count < 1:
        return []
    host = _candidate_basket_hosts(nm_id)[0]
    vol = nm_id // 100000
    part = nm_id // 1000
    return [
        f"https://basket-{host}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/{index}.webp"
        for index in range(1, photo_count + 1)
    ]


def _basket_card_url(nm_id: int, host: str) -> str:
    vol = nm_id // 100000
    part = nm_id // 1000
    return f"https://basket-{host}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/info/ru/card.json"


def _candidate_basket_hosts(nm_id: int) -> list[str]:
    primary = _basket_host(nm_id)
    hosts = [primary]
    for index in range(1, 36):
        host = f"{index:02d}"
        if host not in hosts:
            hosts.append(host)
    return hosts


def _basket_host(nm_id: int) -> str:
    vol = nm_id // 100000
    ranges = [
        (143, "01"),
        (287, "02"),
        (431, "03"),
        (719, "04"),
        (1007, "05"),
        (1061, "06"),
        (1115, "07"),
        (1169, "08"),
        (1313, "09"),
        (1601, "10"),
        (1655, "11"),
        (1919, "12"),
        (2045, "13"),
        (2189, "14"),
        (2405, "15"),
        (2621, "16"),
        (2837, "17"),
        (3053, "18"),
        (3269, "19"),
        (3485, "20"),
        (3701, "21"),
        (3917, "22"),
        (4133, "23"),
        (4349, "24"),
        (4565, "25"),
        (4781, "26"),
        (4997, "27"),
        (5411, "28"),
        (5627, "29"),
        (5843, "30"),
        (6059, "31"),
        (6725, "32"),
    ]
    for max_vol, host in ranges:
        if vol <= max_vol:
            return host
    return "33"
