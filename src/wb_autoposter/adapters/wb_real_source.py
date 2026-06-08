from __future__ import annotations

from datetime import UTC, date, datetime

from wb_autoposter.adapters.wb_analytics import WBAnalyticsApiClient
from wb_autoposter.adapters.wb_api import WBApiSource
from wb_autoposter.adapters.wb_enrichment import enrich_products_with_wb_data
from wb_autoposter.adapters.wb_prices import WBPricesApiClient
from wb_autoposter.models import Product


class WBEnrichedProductSource:
    """Real WB product source composed from Content, Prices, and Analytics APIs."""

    def __init__(
        self,
        *,
        content_api_token: str,
        prices_api_token: str,
        analytics_api_token: str,
        brand_filter: list[str] | None = None,
        stock_type: str = "",
        period_start: date | str | None = None,
        period_end: date | str | None = None,
        content_source: WBApiSource | None = None,
        prices_client: WBPricesApiClient | None = None,
        analytics_client: WBAnalyticsApiClient | None = None,
    ) -> None:
        self.content_source = content_source or WBApiSource(content_api_token, brand_filter=brand_filter)
        self.prices_client = prices_client or WBPricesApiClient(prices_api_token)
        self.analytics_client = analytics_client or WBAnalyticsApiClient(analytics_api_token)
        self.stock_type = stock_type
        today = datetime.now(UTC).date()
        self.period_start = period_start or today
        self.period_end = period_end or today

    def fetch_products(self) -> list[Product]:
        products = self.content_source.fetch_products()
        nm_ids = [product.nm_id for product in products]
        if not nm_ids:
            return []

        prices = self.prices_client.fetch_prices(nm_ids)
        stocks = self.analytics_client.fetch_product_stocks(
            start_date=self.period_start,
            end_date=self.period_end,
            nm_ids=nm_ids,
            stock_type=self.stock_type,
        )
        return enrich_products_with_wb_data(products, prices=prices, stocks=stocks)
