from __future__ import annotations

from typing import Protocol

from wb_autoposter.models import Product


class ProductSource(Protocol):
    def fetch_products(self) -> list[Product]:
        """Return normalized product cards."""
