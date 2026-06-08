from __future__ import annotations

import json

import httpx
import pytest

from wb_autoposter.adapters.wb_analytics import (
    WBAnalyticsApiClient,
    build_sales_funnel_request,
    build_stock_report_request,
    map_wb_sales_funnel_response,
    map_wb_stocks_response,
)


def test_build_stock_report_request_uses_wb_field_names() -> None:
    payload = build_stock_report_request(
        start_date="2026-05-01",
        end_date="2026-05-31",
        nm_ids=[1, 2],
        brand_name="North Atelier",
        stock_type="mp",
        limit=100,
        offset=50,
    )

    assert payload["nmIDs"] == [1, 2]
    assert payload["brandName"] == "North Atelier"
    assert payload["currentPeriod"] == {"start": "2026-05-01", "end": "2026-05-31"}
    assert payload["stockType"] == "mp"
    assert payload["limit"] == 100
    assert payload["offset"] == 50


def test_build_sales_funnel_request_uses_wb_field_names() -> None:
    payload = build_sales_funnel_request(
        start_date="2026-05-01",
        end_date="2026-05-31",
        nm_ids=[1],
        brand_names=["North Atelier"],
        limit=100,
        offset=0,
    )

    assert payload["selectedPeriod"] == {"start": "2026-05-01", "end": "2026-05-31"}
    assert payload["nmIds"] == [1]
    assert payload["brandNames"] == ["North Atelier"]
    assert payload["orderBy"] == {"field": "openCard", "mode": "desc"}


def test_map_wb_stocks_response() -> None:
    stocks = map_wb_stocks_response(
        {
            "data": {
                "currency": "RUB",
                "items": [
                    {
                        "nmID": 123,
                        "metrics": {
                            "stockCount": 7,
                            "stockSum": 49000,
                            "availability": "actual",
                        },
                    }
                ],
            }
        },
        stock_type="wb",
    )

    stock = stocks[123]
    assert stock.stock == 7
    assert stock.stock_sum == 49000
    assert stock.stock_type == "wb"
    assert stock.availability == "actual"
    assert stock.currency == "RUB"


def test_map_wb_sales_funnel_response() -> None:
    metrics = map_wb_sales_funnel_response(
        {
            "data": {
                "currency": "RUB",
                "products": [
                    {
                        "product": {"nmId": 123},
                        "statistic": {
                            "selected": {
                                "openCount": 100,
                                "cartCount": 20,
                                "orderCount": 8,
                                "buyoutCount": 6,
                                "orderSum": 24000,
                                "buyoutSum": 18000,
                                "conversions": {
                                    "addToCartPercent": 20,
                                    "cartToOrderPercent": 40,
                                    "buyoutPercent": 75,
                                },
                            }
                        },
                    }
                ],
            }
        }
    )

    item = metrics[123]
    assert item.open_count == 100
    assert item.cart_count == 20
    assert item.order_count == 8
    assert item.buyout_count == 6
    assert item.add_to_cart_percent == 20
    assert item.cart_to_order_percent == 40
    assert item.buyout_percent == 75
    assert item.currency == "RUB"


def test_wb_analytics_client_fetches_paginated_stocks() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        if payload["offset"] >= 2:
            items = []
        else:
            nm_id = 1 if payload["offset"] == 0 else 2
            items = [{"nmID": nm_id, "metrics": {"stockCount": nm_id}}]
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": items,
                    "currency": "RUB",
                }
            },
        )

    client = httpx.Client(base_url=WBAnalyticsApiClient.base_url, transport=httpx.MockTransport(handler))
    stocks = WBAnalyticsApiClient("token", client=client).fetch_product_stocks(
        start_date="2026-05-01",
        end_date="2026-05-31",
        nm_ids=[1, 2],
        limit=1,
    )

    assert sorted(stocks) == [1, 2]
    assert len(requests) == 3
    assert requests[0].url.path == "/api/v2/stocks-report/products/products"
    assert requests[0].headers["Authorization"] == "token"


def test_wb_analytics_client_fetches_sales_funnel() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "products": [
                        {
                            "product": {"nmId": 10},
                            "statistic": {"selected": {"openCount": 33, "conversions": {}}},
                        }
                    ],
                    "currency": "RUB",
                }
            },
        )

    client = httpx.Client(base_url=WBAnalyticsApiClient.base_url, transport=httpx.MockTransport(handler))
    metrics = WBAnalyticsApiClient("token", client=client).fetch_sales_funnel(
        start_date="2026-05-01",
        end_date="2026-05-31",
        nm_ids=[10],
    )

    assert metrics[10].open_count == 33
    assert requests[0].url.path == "/api/analytics/v3/sales-funnel/products"


def test_wb_analytics_client_raises_for_api_error_flag() -> None:
    client = httpx.Client(
        base_url=WBAnalyticsApiClient.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"error": True, "errorText": "bad"})),
    )

    with pytest.raises(ValueError, match="WB Analytics stocks API error: bad"):
        WBAnalyticsApiClient("token", client=client).fetch_product_stocks(
            start_date="2026-05-01",
            end_date="2026-05-31",
            nm_ids=[1],
        )


def test_wb_analytics_client_raises_for_http_errors() -> None:
    client = httpx.Client(
        base_url=WBAnalyticsApiClient.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"error": True})),
    )

    with pytest.raises(httpx.HTTPStatusError):
        WBAnalyticsApiClient("bad-token", client=client).fetch_sales_funnel(
            start_date="2026-05-01",
            end_date="2026-05-31",
            nm_ids=[1],
        )
