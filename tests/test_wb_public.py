from __future__ import annotations

import httpx
import pytest

from wb_autoposter.adapters.wb_public import WBPublicCatalogSource


def _response(status_code: int, **kwargs) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("GET", "https://example.test"), **kwargs)


def test_wb_public_source_filters_supplier_and_maps_product_details() -> None:
    class FakeClient:
        def get(self, url: str, params: dict[str, object] | None = None):
            if "search.wb.ru" in url:
                return _response(
                    200,
                    json={
                        "products": [
                            {
                                "id": 541142111,
                                "brand": "H&M",
                                "supplier": "Trendsetter",
                                "supplierId": 1335952,
                                "name": "Свитер вязаный",
                                "pics": 2,
                                "totalQuantity": 7,
                                "sizes": [{"price": {"product": 16800}}],
                            },
                            {
                                "id": 663252965,
                                "brand": "Zolla",
                                "supplier": "Zolla",
                                "supplierId": 53719,
                                "name": "Футболка",
                                "pics": 1,
                                "totalQuantity": 54,
                                "sizes": [{"price": {"product": 99900}}],
                            },
                        ]
                    },
                )
            if "541142111/info/ru/card.json" in url:
                return _response(
                    200,
                    json={
                        "nm_id": 541142111,
                        "imt_name": "Свитер вязаный с горлом",
                        "description": "Теплый свитер из публичной карточки WB.",
                        "media": {"photo_count": 2},
                    },
                )
            return _response(404, text="not found")

    source = WBPublicCatalogSource(
        query="hm",
        supplier_id=1335952,
        pages=1,
        client=FakeClient(),
    )

    assert source.fetch_nm_ids() == [541142111]
    products = source.fetch_products([541142111])

    assert len(products) == 1
    product = products[0]
    assert product.nm_id == 541142111
    assert product.brand == "H&M"
    assert product.title == "Свитер вязаный"
    assert product.description == "Теплый свитер из публичной карточки WB."
    assert product.price == 168
    assert product.stock == 7
    assert product.url == "https://www.wildberries.ru/catalog/541142111/detail.aspx"
    assert product.photos[0].endswith("/541142111/images/big/1.webp")


def test_wb_public_source_can_use_brand_filter() -> None:
    class FakeClient:
        def get(self, url: str, params: dict[str, object] | None = None):
            if "search.wb.ru" in url:
                return _response(
                    200,
                    json={
                        "products": [
                            {"id": 1, "brand": "H&M", "supplierId": 1, "name": "One"},
                            {"id": 2, "brand": "Zolla", "supplierId": 1, "name": "Two"},
                        ]
                    },
                )
            return _response(404, text="not found")

    source = WBPublicCatalogSource(query="hm", brand="h&m", client=FakeClient())

    assert source.fetch_nm_ids() == [1]


def test_wb_public_source_fetch_nm_ids_respects_scan_limit_without_stopping_on_old_items() -> None:
    class FakeClient:
        def get(self, url: str, params: dict[str, object] | None = None):
            if "search.wb.ru" in url:
                return _response(
                    200,
                    json={
                        "products": [
                            {"id": 1003, "brand": "H&M", "supplierId": 1, "name": "Newest"},
                            {"id": 1002, "brand": "H&M", "supplierId": 1, "name": "New"},
                            {"id": 1001, "brand": "H&M", "supplierId": 1, "name": "Old item"},
                            {"id": 1000, "brand": "H&M", "supplierId": 1, "name": "Old"},
                        ]
                    },
                )
            return _response(404, text="not found")

    source = WBPublicCatalogSource(query="hm", brand="h&m", limit=10, client=FakeClient())

    assert source.fetch_nm_ids() == [1003, 1002, 1001, 1000]

    limited_source = WBPublicCatalogSource(query="hm", brand="h&m", limit=2, client=FakeClient())

    assert limited_source.fetch_nm_ids() == [1003, 1002]


def test_wb_public_source_reports_rate_limit_after_retries() -> None:
    class FakeClient:
        def get(self, url: str, params: dict[str, object] | None = None):
            return _response(429, text="too many requests")

    source = WBPublicCatalogSource(
        query="hm",
        retry_attempts=1,
        retry_delay_seconds=0,
        client=FakeClient(),
    )

    with pytest.raises(ValueError, match="rate-limited"):
        source.fetch_nm_ids()
