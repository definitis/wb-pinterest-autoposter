from __future__ import annotations

import json

import httpx
import pytest

from wb_autoposter.adapters.wb_prices import WBPricesApiClient, map_wb_prices_response


def test_map_wb_prices_response_uses_lowest_size_price() -> None:
    prices = map_wb_prices_response(
        {
            "data": {
                "listGoods": [
                    {
                        "nmID": 123,
                        "currencyIsoCode4217": "RUB",
                        "discount": 20,
                        "clubDiscount": 5,
                        "sizes": [
                            {"price": 1200, "discountedPrice": 1000, "clubDiscountedPrice": 950},
                            {"price": 1100, "discountedPrice": 900, "clubDiscountedPrice": 870},
                        ],
                    }
                ]
            },
            "error": False,
        }
    )

    price = prices[123]
    assert price.price == 1100
    assert price.discounted_price == 900
    assert price.club_discounted_price == 870
    assert price.effective_price == 900
    assert price.currency == "RUB"


def test_wb_prices_client_fetches_in_chunks_and_deduplicates_nm_ids() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        nm_ids = json.loads(request.content.decode("utf-8"))["nmList"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "listGoods": [
                        {
                            "nmID": nm_id,
                            "currencyIsoCode4217": "RUB",
                            "sizes": [{"price": nm_id * 10, "discountedPrice": nm_id * 9}],
                        }
                        for nm_id in nm_ids
                    ]
                },
                "error": False,
            },
        )

    client = httpx.Client(base_url=WBPricesApiClient.base_url, transport=httpx.MockTransport(handler))
    api = WBPricesApiClient("token", client=client)
    api.max_nm_ids_per_request = 2

    prices = api.fetch_prices([1, 2, 2, 3])

    assert sorted(prices) == [1, 2, 3]
    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == "token"
    assert json.loads(requests[0].content.decode("utf-8")) == {"nmList": [1, 2]}
    assert json.loads(requests[1].content.decode("utf-8")) == {"nmList": [3]}


def test_wb_prices_client_raises_for_api_error_flag() -> None:
    client = httpx.Client(
        base_url=WBPricesApiClient.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"error": True, "errorText": "bad"})),
    )

    with pytest.raises(ValueError, match="WB Prices API error: bad"):
        WBPricesApiClient("token", client=client).fetch_prices([1])


def test_wb_prices_client_raises_for_http_errors() -> None:
    client = httpx.Client(
        base_url=WBPricesApiClient.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": True})),
    )

    with pytest.raises(httpx.HTTPStatusError):
        WBPricesApiClient("bad-token", client=client).fetch_prices([1])
