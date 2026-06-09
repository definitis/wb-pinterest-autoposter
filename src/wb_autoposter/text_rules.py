from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ContentRules:
    forbidden_phrases: set[str] = field(default_factory=set)
    generic_marketplace_brands: set[str] = field(default_factory=set)
    seo_stopwords: set[str] = field(default_factory=set)
    blocked_hashtags: set[str] = field(default_factory=set)


DEFAULT_FORBIDDEN_PHRASES = {
    "акция",
    "бренд wildberries",
    "бренд wb",
    "бренд вайлдберриз",
    "в наличии всего",
    "всего осталось",
    "закажите",
    "защитит нежную",
    "защитят нежную",
    "идеальн",
    "лучший",
    "нежную кожу",
    "незаменим",
    "наслаждайтесь",
    "откройте для себя",
    "подарит комфорт",
    "полная безопасность",
    "с любовью",
    "купите",
    "оформите",
    "срочно",
    "топ продаж",
    "успейте",
    "хит продаж",
    "must-have",
}

DEFAULT_GENERIC_MARKETPLACE_BRANDS = {"wildberries", "wb", "вб", "вайлдберриз"}

DEFAULT_SEO_STOPWORDS = {
    "wildberries",
    "вайлдберриз",
    "товар",
    "товара",
    "товары",
    "карточка",
    "карточке",
    "ссылка",
    "бренд",
    "цена",
    "руб",
    "рублей",
    "остаток",
    "посмотрите",
    "подробнее",
    "новинка",
    "новинки",
    "комплект",
    "набор",
    "штуки",
    "есть",
    "для",
    "или",
    "при",
    "под",
    "над",
    "без",
    "как",
    "это",
    "the",
    "and",
    "for",
    "with",
}

DEFAULT_BLOCKED_HASHTAGS = {"#wildberries", "#wb", "#вб"}


def load_content_rules(path: Path | None = None) -> ContentRules:
    config_path = path or _env_rules_path()
    overrides = _read_rules_file(config_path) if config_path else {}
    return ContentRules(
        forbidden_phrases=_merge_strings(DEFAULT_FORBIDDEN_PHRASES, overrides.get("forbidden_phrases")),
        generic_marketplace_brands=_merge_strings(
            DEFAULT_GENERIC_MARKETPLACE_BRANDS,
            overrides.get("generic_marketplace_brands"),
        ),
        seo_stopwords=_merge_strings(DEFAULT_SEO_STOPWORDS, overrides.get("seo_stopwords")),
        blocked_hashtags=_merge_strings(DEFAULT_BLOCKED_HASHTAGS, overrides.get("blocked_hashtags")),
    )


def _env_rules_path() -> Path | None:
    value = os.getenv("CONTENT_RULES_PATH")
    if not value:
        return None
    return Path(value)


def _read_rules_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


def _merge_strings(defaults: set[str], override: object) -> set[str]:
    values = {item.strip().lower() for item in defaults if item.strip()}
    if isinstance(override, list):
        for item in override:
            if isinstance(item, str) and item.strip():
                values.add(item.strip().lower())
    return values
