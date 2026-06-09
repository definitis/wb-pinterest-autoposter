from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nm_id: int
    brand: str
    title: str
    description: str = ""
    photos: list[str] = Field(default_factory=list)
    price: float | None = None
    stock: int = 0
    created_at: datetime
    updated_at: datetime
    url: str


class ProductPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nm_id: int
    price: float | None = None
    discounted_price: float | None = None
    club_discounted_price: float | None = None
    currency: str | None = None
    discount: float | None = None
    club_discount: float | None = None

    @property
    def effective_price(self) -> float | None:
        return self.discounted_price if self.discounted_price is not None else self.price


class ProductStock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nm_id: int
    stock: int = 0
    stock_sum: float | None = None
    stock_type: str = ""
    availability: str | None = None
    currency: str | None = None


class ProductFunnelMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nm_id: int
    open_count: int = 0
    cart_count: int = 0
    order_count: int = 0
    buyout_count: int = 0
    order_sum: float = 0.0
    buyout_sum: float = 0.0
    add_to_cart_percent: float | None = None
    cart_to_order_percent: float | None = None
    buyout_percent: float | None = None
    currency: str | None = None


class PostStatus(StrEnum):
    PLANNED = "planned"
    PUBLISHING = "publishing"
    DRY_RUN_PUBLISHED = "dry_run_published"
    PUBLISHED = "published"
    FAILED = "failed"


class PublishResult(BaseModel):
    status: PostStatus
    external_id: str | None = None
    payload_path: str | None = None
    error: str | None = None


class PlannedPost(BaseModel):
    id: int
    product_nm_id: int
    platform: str
    status: PostStatus
    payload: dict[str, Any]
    external_id: str | None = None
    error: str | None = None
    created_at: datetime
    published_at: datetime | None = None


class SocialPostMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    post_id: int
    product_nm_id: int
    platform: str
    external_id: str | None = None
    source: str = "zernio"
    captured_at: datetime
    impressions: int | None = None
    reach: int | None = None
    clicks: int | None = None
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    views: int | None = None
    engagement: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
