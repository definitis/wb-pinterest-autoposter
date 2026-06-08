from __future__ import annotations

from wb_autoposter.adapters.wb_enrichment import enrich_products_with_wb_data
from wb_autoposter.models import ProductPrice, ProductStock

from helpers import make_product


def test_enrich_products_with_wb_data_applies_price_and_stock() -> None:
    product = make_product(nm_id=123, price=None, stock=0)

    enriched = enrich_products_with_wb_data(
        [product],
        prices={123: ProductPrice(nm_id=123, price=1200, discounted_price=990, currency="RUB")},
        stocks={123: ProductStock(nm_id=123, stock=7, stock_type="wb")},
    )

    assert enriched[0].price == 990
    assert enriched[0].stock == 7


def test_enrich_products_with_wb_data_keeps_existing_values_when_data_missing() -> None:
    product = make_product(nm_id=123, price=1200, stock=3)

    enriched = enrich_products_with_wb_data([product], prices={}, stocks={})

    assert enriched[0].price == 1200
    assert enriched[0].stock == 3
