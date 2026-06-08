from __future__ import annotations

from wb_autoposter.adapters.wb_real_source import WBEnrichedProductSource
from wb_autoposter.models import ProductPrice, ProductStock

from helpers import make_product


class FakeContentSource:
    def __init__(self, products):
        self.products = products

    def fetch_products(self):
        return self.products


class FakePricesClient:
    def __init__(self) -> None:
        self.requested_nm_ids: list[int] | None = None

    def fetch_prices(self, nm_ids):
        self.requested_nm_ids = list(nm_ids)
        return {123: ProductPrice(nm_id=123, price=1200, discounted_price=990, currency="RUB")}


class FakeAnalyticsClient:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def fetch_product_stocks(self, **kwargs):
        self.request = dict(kwargs)
        return {123: ProductStock(nm_id=123, stock=8, stock_type=str(kwargs["stock_type"]))}


def test_wb_enriched_product_source_combines_content_prices_and_stocks() -> None:
    product = make_product(nm_id=123, price=None, stock=0)
    prices_client = FakePricesClient()
    analytics_client = FakeAnalyticsClient()

    source = WBEnrichedProductSource(
        content_api_token="content",
        prices_api_token="prices",
        analytics_api_token="analytics",
        stock_type="wb",
        period_start="2026-06-01",
        period_end="2026-06-02",
        content_source=FakeContentSource([product]),
        prices_client=prices_client,
        analytics_client=analytics_client,
    )

    products = source.fetch_products()

    assert products[0].price == 990
    assert products[0].stock == 8
    assert prices_client.requested_nm_ids == [123]
    assert analytics_client.request == {
        "start_date": "2026-06-01",
        "end_date": "2026-06-02",
        "nm_ids": [123],
        "stock_type": "wb",
    }


def test_wb_enriched_product_source_skips_enrichment_when_content_is_empty() -> None:
    prices_client = FakePricesClient()
    analytics_client = FakeAnalyticsClient()
    source = WBEnrichedProductSource(
        content_api_token="content",
        prices_api_token="prices",
        analytics_api_token="analytics",
        content_source=FakeContentSource([]),
        prices_client=prices_client,
        analytics_client=analytics_client,
    )

    assert source.fetch_products() == []
    assert prices_client.requested_nm_ids is None
    assert analytics_client.request is None
