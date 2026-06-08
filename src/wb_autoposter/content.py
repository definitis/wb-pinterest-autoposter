from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from wb_autoposter.models import Product


@dataclass(frozen=True)
class GeneratedContent:
    title: str
    description: str
    cta: str
    hashtags: list[str]

    def to_dict(self) -> dict[str, str | list[str]]:
        return asdict(self)


class TemplateContentGenerator:
    """Deterministic Pinterest copy generator for the MVP."""

    def generate(self, product: Product) -> GeneratedContent:
        title = _limit(product.title.strip(), 100)
        cta = "Open on Wildberries"
        hashtags = _build_hashtags(product.brand)

        parts = []
        if product.description.strip():
            parts.append(product.description.strip())
        parts.append(f"{product.brand} on Wildberries.")
        if product.price is not None:
            parts.append(f"Price: {_format_price(product.price)}.")
        parts.append(cta + ".")

        description = _limit(" ".join(parts), 420)
        description = f"{description}\n\n{' '.join(hashtags)}"

        return GeneratedContent(
            title=title,
            description=_limit(description, 500),
            cta=cta,
            hashtags=hashtags,
        )


def _build_hashtags(brand: str) -> list[str]:
    brand_tag = re.sub(r"\W+", "", brand, flags=re.UNICODE)
    tags = ["#Wildberries", "#Fashion"]
    if brand_tag:
        tags.insert(0, f"#{brand_tag}")
    return tags[:3]


def _format_price(price: float) -> str:
    return f"{price:,.0f}".replace(",", " ") + " RUB"


def _limit(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "..."
