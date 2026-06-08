from __future__ import annotations

from collections.abc import Mapping, Sequence

from wb_autoposter.models import Product, ProductPrice, ProductStock


def enrich_products_with_wb_data(
    products: Sequence[Product],
    *,
    prices: Mapping[int, ProductPrice] | None = None,
    stocks: Mapping[int, ProductStock] | None = None,
) -> list[Product]:
    """Apply WB Prices/Analytics data to Product objects.

    This keeps the future real sync flow explicit:
    Content API builds product cards, Prices API fills price, Analytics fills stock.
    """

    enriched: list[Product] = []
    for product in products:
        price = prices.get(product.nm_id) if prices else None
        stock = stocks.get(product.nm_id) if stocks else None
        enriched.append(
            product.model_copy(
                update={
                    "price": price.effective_price if price and price.effective_price is not None else product.price,
                    "stock": stock.stock if stock else product.stock,
                }
            )
        )
    return enriched
