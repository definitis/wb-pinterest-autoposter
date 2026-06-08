from __future__ import annotations

from datetime import UTC, datetime

from wb_autoposter.models import Product


def make_product(
    *,
    nm_id: int = 999001,
    brand: str = "Test Brand",
    title: str = "Test product",
    description: str = "Test description",
    photo: str = "https://example.com/photo.jpg",
    photos: list[str] | None = None,
    price: float | None = 1000,
    stock: int = 3,
    url: str = "https://www.wildberries.ru/catalog/999001/detail.aspx",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Product:
    now = datetime(2026, 5, 20, tzinfo=UTC)
    return Product(
        nm_id=nm_id,
        brand=brand,
        title=title,
        description=description,
        photos=photos if photos is not None else [photo],
        price=price,
        stock=stock,
        created_at=created_at or now,
        updated_at=updated_at or now,
        url=url,
    )
