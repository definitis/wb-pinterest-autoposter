from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import httpx

from wb_autoposter.models import ProductPrice


class WBPricesApiClient:
    """Wildberries Prices and Discounts API client layer.

    This client fetches actual seller prices by nmID. The MVP does not call it
    yet; it is the future enrichment layer for Product.price.
    """

    base_url = "https://discounts-prices-api.wildberries.ru"
    max_nm_ids_per_request = 1000

    def __init__(self, api_token: str, *, client: httpx.Client | None = None) -> None:
        self.api_token = api_token
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30)

    def fetch_prices(self, nm_ids: Sequence[int]) -> dict[int, ProductPrice]:
        prices: dict[int, ProductPrice] = {}
        for chunk in _chunks(_unique_nm_ids(nm_ids), self.max_nm_ids_per_request):
            response = self.client.post(
                "/api/v2/list/goods/filter",
                headers={"Authorization": self.api_token},
                json={"nmList": chunk},
            )
            response.raise_for_status()
            body = response.json()
            _raise_for_wb_error(body, "WB Prices API")
            prices.update(map_wb_prices_response(body))

        return prices


def map_wb_prices_response(body: dict[str, Any]) -> dict[int, ProductPrice]:
    data = body.get("data") or {}
    goods = data.get("listGoods") or []
    prices = [_map_wb_price_item(item) for item in goods]
    return {price.nm_id: price for price in prices}


def _map_wb_price_item(item: dict[str, Any]) -> ProductPrice:
    sizes = item.get("sizes") or []
    return ProductPrice(
        nm_id=int(item["nmID"]),
        price=_min_number(size.get("price") for size in sizes),
        discounted_price=_min_number(size.get("discountedPrice") for size in sizes),
        club_discounted_price=_min_number(size.get("clubDiscountedPrice") for size in sizes),
        currency=_optional_str(item.get("currencyIsoCode4217")),
        discount=_optional_float(item.get("discount")),
        club_discount=_optional_float(item.get("clubDiscount")),
    )


def _chunks(items: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _unique_nm_ids(nm_ids: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for nm_id in nm_ids:
        normalized = int(nm_id)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _min_number(values: Iterable[Any]) -> float | None:
    numbers = [_optional_float(value) for value in values]
    numbers = [number for number in numbers if number is not None]
    return min(numbers) if numbers else None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _raise_for_wb_error(body: dict[str, Any], service_name: str) -> None:
    if body.get("error") is True:
        message = body.get("errorText") or body.get("additionalErrors") or body
        raise ValueError(f"{service_name} error: {message}")
