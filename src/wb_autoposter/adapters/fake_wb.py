from __future__ import annotations

import json
from pathlib import Path

from wb_autoposter.models import Product


class FakeWBSource:
    """Local fixture-backed source used until real WB API access is available."""

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def fetch_products(self) -> list[Product]:
        if not self.fixture_path.exists():
            raise FileNotFoundError(f"Fake WB fixture not found: {self.fixture_path}")

        raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        items = raw["products"] if isinstance(raw, dict) else raw
        return [Product.model_validate(item) for item in items]
