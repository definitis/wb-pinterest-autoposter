from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from wb_autoposter.models import Product


class WBApiSource:
    """Wildberries Seller API product source.

    It implements the Content API card-list pagination and response mapping, but
    the MVP still uses FakeWBSource until real credentials and test goods exist.
    """

    base_url = "https://content-api.wildberries.ru"

    def __init__(
        self,
        api_token: str,
        *,
        client: httpx.Client | None = None,
        limit: int = 100,
        brand_filter: list[str] | None = None,
    ) -> None:
        self.api_token = api_token
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30)
        self.limit = limit
        self.brand_filter = brand_filter

    def fetch_products(self) -> list[Product]:
        products: list[Product] = []
        cursor: dict[str, Any] = {"limit": self.limit}

        while True:
            payload = self._build_cards_request(cursor)
            response = self.client.post(
                "/content/v2/get/cards/list",
                headers={"Authorization": self.api_token},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

            cards = body.get("cards", [])
            products.extend(map_wb_cards_to_products(cards))

            response_cursor = body.get("cursor") or {}
            total = int(response_cursor.get("total") or len(cards))
            if total < self.limit or not cards:
                break

            cursor = {
                "limit": self.limit,
                "updatedAt": response_cursor.get("updatedAt"),
                "nmID": response_cursor.get("nmID"),
            }

        return products

    def _build_cards_request(self, cursor: dict[str, Any]) -> dict[str, Any]:
        filter_settings: dict[str, Any] = {"withPhoto": -1}
        if self.brand_filter:
            filter_settings["brands"] = self.brand_filter

        return {
            "settings": {
                "sort": {"ascending": True},
                "cursor": {key: value for key, value in cursor.items() if value is not None},
                "filter": filter_settings,
            }
        }


def map_wb_cards_to_products(cards: list[dict[str, Any]]) -> list[Product]:
    return [_map_wb_card_to_product(card) for card in cards]


def _map_wb_card_to_product(card: dict[str, Any]) -> Product:
    nm_id = int(card["nmID"])
    photos = [_photo_url(photo) for photo in card.get("photos", [])]
    photos = [photo for photo in photos if photo]
    sizes = card.get("sizes", [])
    price = _extract_price(sizes)
    updated_at = _parse_datetime(card.get("updatedAt"))
    created_at = _parse_datetime(card.get("createdAt")) or updated_at

    return Product(
        nm_id=nm_id,
        brand=str(card.get("brand") or ""),
        title=str(card.get("title") or ""),
        description=str(card.get("description") or ""),
        photos=photos,
        price=price,
        stock=0,
        created_at=created_at or datetime.now(UTC),
        updated_at=updated_at or datetime.now(UTC),
        url=f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx",
    )


def _photo_url(photo: dict[str, Any]) -> str | None:
    for key in ("big", "c516x688", "tm"):
        value = photo.get(key)
        if value:
            return str(value)
    return None


def _extract_price(sizes: list[dict[str, Any]]) -> float | None:
    for size in sizes:
        price = size.get("price")
        if price is not None:
            return float(price)
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
