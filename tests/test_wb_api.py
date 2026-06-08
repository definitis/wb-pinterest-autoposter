from __future__ import annotations

import json

import httpx

from wb_autoposter.adapters.wb_api import WBApiSource, map_wb_cards_to_products


def test_map_wb_card_to_product() -> None:
    products = map_wb_cards_to_products([_wb_card(nm_id=123, price=2490)])

    product = products[0]
    assert product.nm_id == 123
    assert product.brand == "North Atelier"
    assert product.title == "Пальто"
    assert product.description == "Описание"
    assert product.photos == ["https://basket.example/big.webp"]
    assert product.price == 2490
    assert product.stock == 0
    assert product.url == "https://www.wildberries.ru/catalog/123/detail.aspx"


def test_wb_api_source_fetches_paginated_cards() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = request.read().decode("utf-8")
        if "updatedAt" in payload:
            return httpx.Response(
                200,
                json={
                    "cards": [_wb_card(nm_id=2, price=2000)],
                    "cursor": {"total": 1, "updatedAt": "2026-05-21T00:00:00Z", "nmID": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "cards": [_wb_card(nm_id=1, price=1000)],
                "cursor": {"total": 2, "updatedAt": "2026-05-20T00:00:00Z", "nmID": 1},
            },
        )

    client = httpx.Client(base_url=WBApiSource.base_url, transport=httpx.MockTransport(handler))
    source = WBApiSource("token", client=client, limit=2, brand_filter=["North Atelier"])

    products = source.fetch_products()

    assert [product.nm_id for product in products] == [1, 2]
    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == "token"
    assert requests[0].url.path == "/content/v2/get/cards/list"
    first_payload = json.loads(requests[0].content.decode("utf-8"))
    assert first_payload["settings"]["filter"]["brands"] == ["North Atelier"]


def test_wb_api_source_raises_for_http_errors() -> None:
    client = httpx.Client(
        base_url=WBApiSource.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": True})),
    )
    source = WBApiSource("bad-token", client=client)

    try:
        source.fetch_products()
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 401
    else:
        raise AssertionError("Expected HTTPStatusError")


def _wb_card(nm_id: int, price: int | None) -> dict[str, object]:
    return {
        "nmID": nm_id,
        "brand": "North Atelier",
        "title": "Пальто",
        "description": "Описание",
        "photos": [{"big": "https://basket.example/big.webp"}],
        "sizes": [{"price": price}] if price is not None else [],
        "createdAt": "2026-05-20T09:00:00Z",
        "updatedAt": "2026-05-21T09:00:00Z",
    }
