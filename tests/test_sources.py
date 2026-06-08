from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from wb_autoposter.adapters.fake_wb import FakeWBSource


def test_fake_source_loads_fixture_products(fixture_path: Path) -> None:
    products = FakeWBSource(fixture_path).fetch_products()

    assert len(products) == 7
    assert products[0].nm_id == 101000001
    assert products[0].photos[0].startswith("https://")


def test_fake_source_missing_file_fails_clearly(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match="Fake WB fixture not found"):
        FakeWBSource(missing_path).fetch_products()


def test_fake_source_malformed_json_fails(tmp_path: Path) -> None:
    fixture = tmp_path / "broken.json"
    fixture.write_text("{not-json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        FakeWBSource(fixture).fetch_products()


def test_fake_source_rejects_unknown_product_fields(tmp_path: Path) -> None:
    fixture = tmp_path / "products.json"
    fixture.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "nm_id": 1,
                        "brand": "Brand",
                        "title": "Title",
                        "description": "Description",
                        "photos": ["https://example.com/photo.jpg"],
                        "price": 100,
                        "stock": 1,
                        "created_at": "2026-05-20T09:00:00Z",
                        "updated_at": "2026-05-20T09:00:00Z",
                        "url": "https://www.wildberries.ru/catalog/1/detail.aspx",
                        "unexpected": "field",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        FakeWBSource(fixture).fetch_products()
