from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from wb_autoposter.text_rules import ContentRules, load_content_rules


@dataclass(frozen=True)
class ProductSeo:
    title: str
    pinterest_title: str
    keywords: list[str]
    hashtags: list[str]

    def to_dict(self) -> dict[str, str | list[str]]:
        return asdict(self)


def build_product_seo(
    *,
    title: str,
    description: str = "",
    features: str = "",
    brand: str = "",
    rules: ContentRules | None = None,
) -> ProductSeo:
    active_rules = rules or load_content_rules()
    cleaned_title = _clean_text(title)
    keywords = _extract_keywords(
        f"{cleaned_title} {description} {features} {brand}",
        stopwords=active_rules.seo_stopwords,
    )
    seo_title = _limit(_join_title_parts([brand, cleaned_title]), 90)
    pinterest_title = _limit(cleaned_title, 100)
    hashtags = _build_seo_hashtags(keywords, brand=brand, blocked=active_rules.blocked_hashtags)
    return ProductSeo(
        title=seo_title or cleaned_title,
        pinterest_title=pinterest_title or seo_title or cleaned_title,
        keywords=keywords,
        hashtags=hashtags,
    )


def _extract_keywords(text: str, *, stopwords: set[str], limit: int = 12) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9&-]{3,}", text)
    seen: set[str] = set()
    result: list[str] = []
    for word in words:
        normalized = word.lower().replace("ё", "е").strip("-")
        if not normalized or normalized in stopwords:
            continue
        if normalized.isdigit():
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(_display_keyword(word))
        if len(result) >= limit:
            break
    return result


def _build_seo_hashtags(keywords: list[str], *, brand: str, blocked: set[str], limit: int = 6) -> list[str]:
    candidates = []
    if brand:
        candidates.append(brand)
    candidates.extend(keywords)

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        tag = "#" + re.sub(r"[^\w]+", "", candidate, flags=re.UNICODE)[:40]
        if len(tag) <= 1:
            continue
        normalized = tag.lower()
        if normalized in blocked or normalized in seen:
            continue
        seen.add(normalized)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def _display_keyword(word: str) -> str:
    return word.strip(" .,;:!?").lower()


def _join_title_parts(parts: list[str]) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = _clean_text(part)
        if not cleaned:
            continue
        normalized = cleaned.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(cleaned)
    return " ".join(result)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def _limit(value: str, max_length: int) -> str:
    value = _clean_text(value)
    if len(value) <= max_length:
        return value
    trimmed = value[: max_length - 1].rstrip()
    if " " in trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0].rstrip()
    return trimmed.rstrip(".,;:") + "..."
