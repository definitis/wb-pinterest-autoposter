from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import httpx

from wb_autoposter.models import ProductFunnelMetrics, ProductStock


DEFAULT_AVAILABILITY_FILTERS = [
    "deficient",
    "actual",
    "balanced",
    "nonActual",
    "nonLiquid",
    "invalidData",
]


class WBAnalyticsApiClient:
    """Wildberries Analytics API client layer for stocks and sales funnel data.

    This client is intentionally separate from WBApiSource because WB Content,
    Prices, and Analytics use different API hosts, limits, and token scopes.
    """

    base_url = "https://seller-analytics-api.wildberries.ru"

    def __init__(self, api_token: str, *, client: httpx.Client | None = None) -> None:
        self.api_token = api_token
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30)

    def fetch_product_stocks(
        self,
        *,
        start_date: date | str,
        end_date: date | str,
        nm_ids: Sequence[int] | None = None,
        brand_name: str | None = None,
        stock_type: str = "",
        limit: int = 1000,
        skip_deleted: bool = True,
    ) -> dict[int, ProductStock]:
        stocks: dict[int, ProductStock] = {}
        offset = 0

        while True:
            payload = build_stock_report_request(
                start_date=start_date,
                end_date=end_date,
                nm_ids=nm_ids,
                brand_name=brand_name,
                stock_type=stock_type,
                limit=limit,
                offset=offset,
                skip_deleted=skip_deleted,
            )
            response = self.client.post(
                "/api/v2/stocks-report/products/products",
                headers={"Authorization": self.api_token},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            _raise_for_wb_error(body, "WB Analytics stocks API")

            items = _stock_items(body)
            stocks.update(map_wb_stocks_response(body, stock_type=stock_type))
            if len(items) < limit:
                break
            offset += limit

        return stocks

    def fetch_sales_funnel(
        self,
        *,
        start_date: date | str,
        end_date: date | str,
        nm_ids: Sequence[int] | None = None,
        brand_names: Sequence[str] | None = None,
        limit: int = 1000,
        skip_deleted: bool = True,
    ) -> dict[int, ProductFunnelMetrics]:
        metrics: dict[int, ProductFunnelMetrics] = {}
        offset = 0

        while True:
            payload = build_sales_funnel_request(
                start_date=start_date,
                end_date=end_date,
                nm_ids=nm_ids,
                brand_names=brand_names,
                limit=limit,
                offset=offset,
                skip_deleted=skip_deleted,
            )
            response = self.client.post(
                "/api/analytics/v3/sales-funnel/products",
                headers={"Authorization": self.api_token},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            _raise_for_wb_error(body, "WB Analytics sales funnel API")

            products = _sales_funnel_products(body)
            metrics.update(map_wb_sales_funnel_response(body))
            if len(products) < limit:
                break
            offset += limit

        return metrics


def build_stock_report_request(
    *,
    start_date: date | str,
    end_date: date | str,
    nm_ids: Sequence[int] | None = None,
    brand_name: str | None = None,
    stock_type: str = "",
    limit: int = 1000,
    offset: int = 0,
    skip_deleted: bool = True,
    availability_filters: Sequence[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "nmIDs": [int(nm_id) for nm_id in nm_ids or []],
        "currentPeriod": {"start": _date_to_str(start_date), "end": _date_to_str(end_date)},
        "stockType": stock_type,
        "skipDeletedNm": skip_deleted,
        "orderBy": {"field": "avgOrders", "mode": "desc"},
        "availabilityFilters": list(availability_filters or DEFAULT_AVAILABILITY_FILTERS),
        "limit": limit,
        "offset": offset,
    }
    if brand_name:
        payload["brandName"] = brand_name
    return payload


def build_sales_funnel_request(
    *,
    start_date: date | str,
    end_date: date | str,
    nm_ids: Sequence[int] | None = None,
    brand_names: Sequence[str] | None = None,
    limit: int = 1000,
    offset: int = 0,
    skip_deleted: bool = True,
) -> dict[str, Any]:
    return {
        "selectedPeriod": {"start": _date_to_str(start_date), "end": _date_to_str(end_date)},
        "nmIds": [int(nm_id) for nm_id in nm_ids or []],
        "brandNames": list(brand_names or []),
        "subjectIds": [],
        "tagIds": [],
        "skipDeletedNm": skip_deleted,
        "orderBy": {"field": "openCard", "mode": "desc"},
        "limit": limit,
        "offset": offset,
    }


def map_wb_stocks_response(body: dict[str, Any], *, stock_type: str = "") -> dict[int, ProductStock]:
    data = body.get("data") or {}
    currency = _optional_str(data.get("currency"))
    stocks = [_map_stock_item(item, stock_type=stock_type, currency=currency) for item in _stock_items(body)]
    return {stock.nm_id: stock for stock in stocks}


def map_wb_sales_funnel_response(body: dict[str, Any]) -> dict[int, ProductFunnelMetrics]:
    data = body.get("data") or {}
    currency = _optional_str(data.get("currency"))
    metrics = [_map_sales_funnel_item(item, currency=currency) for item in _sales_funnel_products(body)]
    return {item.nm_id: item for item in metrics}


def _map_stock_item(item: dict[str, Any], *, stock_type: str, currency: str | None) -> ProductStock:
    metrics = item.get("metrics") or {}
    return ProductStock(
        nm_id=int(item["nmID"]),
        stock=max(_optional_int(metrics.get("stockCount")) or 0, 0),
        stock_sum=_optional_float(metrics.get("stockSum")),
        stock_type=stock_type,
        availability=_optional_str(metrics.get("availability")),
        currency=currency,
    )


def _map_sales_funnel_item(item: dict[str, Any], *, currency: str | None) -> ProductFunnelMetrics:
    product = item.get("product") or {}
    statistic = item.get("statistic") or {}
    selected = statistic.get("selected") or item.get("selected") or {}
    conversions = selected.get("conversions") or {}
    nm_id = product.get("nmId") or product.get("nmID") or item.get("nmID")

    return ProductFunnelMetrics(
        nm_id=int(nm_id),
        open_count=_optional_int(selected.get("openCount")) or 0,
        cart_count=_optional_int(selected.get("cartCount")) or 0,
        order_count=_optional_int(selected.get("orderCount")) or 0,
        buyout_count=_optional_int(selected.get("buyoutCount")) or 0,
        order_sum=_optional_float(selected.get("orderSum")) or 0.0,
        buyout_sum=_optional_float(selected.get("buyoutSum")) or 0.0,
        add_to_cart_percent=_optional_float(conversions.get("addToCartPercent")),
        cart_to_order_percent=_optional_float(conversions.get("cartToOrderPercent")),
        buyout_percent=_optional_float(conversions.get("buyoutPercent")),
        currency=currency,
    )


def _stock_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data") or {}
    return list(data.get("items") or [])


def _sales_funnel_products(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data") or {}
    return list(data.get("products") or [])


def _date_to_str(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


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
