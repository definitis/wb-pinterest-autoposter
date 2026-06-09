from __future__ import annotations

import json
from pathlib import Path

import httpx

from wb_autoposter.content import TemplateContentGenerator, sanitize_social_text
from wb_autoposter.seo import build_product_seo
from wb_autoposter.text_rules import load_content_rules

from helpers import make_product


def test_load_content_rules_merges_json_overrides(tmp_path: Path) -> None:
    rules_path = tmp_path / "content_rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "forbidden_phrases": ["bad phrase"],
                "generic_marketplace_brands": ["marketplace"],
                "seo_stopwords": ["ignoreme"],
                "blocked_hashtags": ["#blocked"],
            }
        ),
        encoding="utf-8",
    )

    rules = load_content_rules(rules_path)

    assert "bad phrase" in rules.forbidden_phrases
    assert "marketplace" in rules.generic_marketplace_brands
    assert "ignoreme" in rules.seo_stopwords
    assert "#blocked" in rules.blocked_hashtags
    assert "wildberries" in rules.generic_marketplace_brands


def test_sanitize_social_text_removes_generic_marketplace_brand_phrase() -> None:
    text = "Антицарапки Mothercare. Бренд: Wildberries. Посмотрите на Wildberries."

    cleaned = sanitize_social_text(text)

    assert "Бренд" not in cleaned
    assert "Бренд: Wildberries" not in cleaned
    assert "Антицарапки Mothercare" in cleaned


def test_build_product_seo_uses_keywords_and_blocks_marketplace_hashtags() -> None:
    seo = build_product_seo(
        title="Антицарапки для новорожденных Mothercare",
        description="Мягкие варежки из хлопка для малыша.",
        features="Цена: 649 руб.",
        brand="Mothercare",
    )

    assert seo.pinterest_title
    assert "антицарапки" in seo.keywords
    assert "#Mothercare" in seo.hashtags
    assert "#Wildberries" not in seo.hashtags


def test_generator_falls_back_when_custom_rules_reject_gemini_text(tmp_path: Path) -> None:
    rules_path = tmp_path / "content_rules.json"
    rules_path.write_text(json.dumps({"forbidden_phrases": ["bad phrase"]}), encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"vk":"Test product. bad phrase.",'
                                        '"instagram":"Test product. bad phrase.",'
                                        '"pinterest":"Test product. bad phrase."}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    generator = TemplateContentGenerator(
        gemini_api_key="gemini-key",
        gemini_model="gemini-test",
        content_rules_path=rules_path,
        client=httpx.Client(base_url="https://generativelanguage.googleapis.com", transport=httpx.MockTransport(handler)),
    )

    content = generator.generate(make_product(title="Test product", description="Product description."))

    assert content.platform_texts is not None
    assert "bad phrase" not in content.platform_texts["vk"]
    assert "Test product" in content.platform_texts["vk"]
