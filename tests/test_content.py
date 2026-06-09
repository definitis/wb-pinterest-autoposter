from __future__ import annotations

import httpx

from wb_autoposter.content import ProductData, TemplateContentGenerator, generate_social_texts

from helpers import make_product


def test_content_generator_builds_short_russian_sales_copy_from_wb_card() -> None:
    product = make_product(
        nm_id=1002,
        brand="North Atelier",
        title="Шапка женская вязаная",
        description="Теплая шапка с отворотом для прохладной погоды. Подходит для ежедневных образов.",
        price=2500,
    )

    content = TemplateContentGenerator().generate(product)

    assert content.title == "Шапка женская вязаная"
    assert "Теплая шапка с отворотом" in content.description
    assert "Цена: 2 500 руб." in content.description
    assert "Вайлдберриз" in content.description
    assert "#NorthAtelier" in content.hashtags
    assert "#Шапка" in content.hashtags
    assert "#Fashion" not in content.hashtags
    assert len(content.description) <= 500


def test_content_generator_uses_deterministic_variants() -> None:
    generator = TemplateContentGenerator()
    product_a = make_product(nm_id=1001, title="Джемпер женский", description="Мягкий джемпер свободного кроя.")
    product_b = product_a.model_copy(update={"nm_id": 1002})

    content_a = generator.generate(product_a)
    content_b = generator.generate(product_b)

    assert content_a.description != content_b.description
    assert generator.generate(product_a).description == content_a.description


def test_content_generator_localizes_known_english_title() -> None:
    product = make_product(
        nm_id=541142111,
        brand="H&M",
        title="Knit sweater with high neck",
        description="Rib knit sweater from the WB card.",
        price=1680,
    )

    content = TemplateContentGenerator().generate(product)

    assert content.title == "Вязаный свитер с высоким воротом"
    assert "Open on Wildberries" not in content.description
    assert "Цена: 1 680 руб." in content.description
    assert "#Свитер" in content.hashtags


def test_content_generator_does_not_duplicate_wildberries_tag_or_price_dot() -> None:
    product = make_product(
        nm_id=1004,
        brand="Wildberries",
        title="Пиджак джинсовый свободный",
        description="Плотный джинсовый пиджак свободного кроя.",
        price=5895,
    )

    content = TemplateContentGenerator().generate(product)

    assert content.hashtags.count("#Wildberries") == 1
    assert "руб.." not in content.description
    assert "Цена: 5 895 руб." in content.description


def test_content_generator_uses_brand_from_title_when_wb_brand_is_generic() -> None:
    product = make_product(
        nm_id=1005,
        brand="Wildberries",
        title="Леггинсы детские лосины хлопок Mothercare",
        description="",
        price=649,
    )

    content = TemplateContentGenerator().generate(product)

    assert "#Mothercare" in content.hashtags
    assert content.hashtags.count("#Wildberries") == 1
    assert "Бренд: Wildberries" not in content.description
    assert content.platform_texts is not None
    assert "Бренд: Wildberries" not in content.platform_texts["instagram"]


def test_generate_social_texts_uses_fallback_without_gemini_key(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    product = ProductData(
        title="Шапка женская вязаная",
        description="Теплая шапка с отворотом для прохладной погоды.",
        url="https://www.wildberries.ru/catalog/123/detail.aspx",
    )

    result = generate_social_texts(product)

    assert set(result) == {"vk", "instagram", "pinterest"}
    assert "Шапка женская вязаная" in result["vk"]
    assert "Wildberries" in result["pinterest"]


def test_content_generator_uses_one_gemini_response_for_all_platforms() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"vk":"Test product. Посмотрите товар.",'
                                        '"instagram":"Test product. Посмотрите товар.",'
                                        '"pinterest":"Test product. Посмотрите товар."}'
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
        client=httpx.Client(base_url="https://generativelanguage.googleapis.com", transport=httpx.MockTransport(handler)),
    )

    content = generator.generate(make_product())

    assert len(requests) == 1
    assert content.platform_texts == {
        "vk": "Test product. Посмотрите товар.",
        "instagram": "Test product. Посмотрите товар.",
        "pinterest": "Test product. Посмотрите товар.",
    }


def test_content_generator_falls_back_when_gemini_text_is_about_another_product() -> None:
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
                                        '{"vk":"Вешалки Mothercare для детской одежды.",'
                                        '"instagram":"В комплекте 3 вешалки для шкафа.",'
                                        '"pinterest":"Вешалки для хранения детских вещей."}'
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
        client=httpx.Client(base_url="https://generativelanguage.googleapis.com", transport=httpx.MockTransport(handler)),
    )

    product = make_product(
        title="Антицарапки для новорожденных Mothercare",
        description="Мягкие варежки помогают закрыть ручки малыша от случайных царапин.",
    )

    content = generator.generate(product)

    assert content.platform_texts is not None
    assert "Антицарапки" in content.platform_texts["vk"]
    assert "Вешалки" not in content.platform_texts["vk"]


def test_content_generator_falls_back_when_gemini_text_uses_cliche() -> None:
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
                                        '{"vk":"Антицарапки Mothercare. Успейте купить, осталось всего 3 штуки.",'
                                        '"instagram":"Антицарапки Mothercare для малыша. Успейте на Wildberries.",'
                                        '"pinterest":"Антицарапки Mothercare. Посмотрите на Wildberries."}'
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
        client=httpx.Client(base_url="https://generativelanguage.googleapis.com", transport=httpx.MockTransport(handler)),
    )

    product = make_product(
        title="Антицарапки для новорожденных Mothercare",
        description="Мягкие варежки помогают закрыть ручки малыша от случайных царапин.",
    )

    content = generator.generate(product)

    assert content.platform_texts is not None
    assert "Успейте" not in content.platform_texts["vk"]
    assert "Мягкие варежки" in content.platform_texts["vk"]


def test_content_generator_cools_down_after_gemini_rate_limit() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    generator = TemplateContentGenerator(
        gemini_api_key="gemini-key",
        gemini_model="gemini-test",
        gemini_429_cooldown_seconds=60,
        client=httpx.Client(base_url="https://generativelanguage.googleapis.com", transport=httpx.MockTransport(handler)),
    )

    product = make_product(title="Test product", description="Product description.")
    first = generator.generate(product)
    second = generator.generate(product.model_copy(update={"nm_id": product.nm_id + 1}))

    assert len(requests) == 1
    assert first.platform_texts is not None
    assert second.platform_texts is not None
