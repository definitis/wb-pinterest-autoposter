from __future__ import annotations

import html
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from wb_autoposter.config import load_settings
from wb_autoposter.models import Product

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedContent:
    title: str
    description: str
    cta: str
    hashtags: list[str]
    platform_texts: dict[str, str] | None = None

    def to_dict(self) -> dict[str, str | list[str] | dict[str, str] | None]:
        return asdict(self)


@dataclass(frozen=True)
class ProductData:
    title: str
    description: str = ""
    features: str = ""
    url: str = ""


def generate_social_texts(product: ProductData) -> dict[str, str]:
    """Generate VK/Instagram/Pinterest text in one Gemini request, with template fallback."""

    settings = load_settings()
    api_key = settings.gemini_api_key
    model = settings.gemini_model
    fallback = _fallback_social_texts(product)
    if not api_key:
        logger.info("Gemini content generation skipped: GEMINI_API_KEY is not configured; using fallback.")
        return fallback

    logger.info("Gemini content generation started for product title=%r.", product.title)
    try:
        response = _post_gemini_request(
            model,
            api_key,
            _gemini_request_body(product),
            client=None,
        )
        result = _parse_gemini_social_texts(response.json())
        logger.info("Gemini content generation succeeded for product title=%r.", product.title)
        return result
    except Exception as exc:
        logger.warning("Gemini content generation fallback used: %s", exc)
        return fallback


def create_content_generator() -> "TemplateContentGenerator":
    settings = load_settings()
    return TemplateContentGenerator(gemini_api_key=settings.gemini_api_key, gemini_model=settings.gemini_model)


class TemplateContentGenerator:
    """Deterministic Russian social copy generated only from the WB card data."""

    def __init__(
        self,
        *,
        gemini_api_key: str | None = None,
        gemini_model: str = "gemini-2.5-flash",
        client: httpx.Client | None = None,
    ) -> None:
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.client = client

    def generate(self, product: Product) -> GeneratedContent:
        brand = _clean_text(product.brand)
        source_title = _clean_text(product.title)
        title = _limit(_localize_title(source_title), 100)
        card_fact = _extract_card_fact(product.description)
        price = _format_price(product.price)
        cta = _cta_for_product(product.nm_id)
        hashtags = _build_hashtags(brand, f"{source_title} {card_fact}")

        description_body = _build_description(
            variant=product.nm_id % len(_DESCRIPTION_VARIANTS),
            title=title,
            brand=brand,
            fact=card_fact,
            price=price,
            cta=cta,
        )
        tag_line = " ".join(hashtags)
        body_limit = min(430, max(120, 498 - len(tag_line)))
        description = f"{_limit(description_body, body_limit)}\n\n{tag_line}"
        fallback_texts = _fallback_social_texts(
            ProductData(
                title=title,
                description=card_fact or product.description,
                features=_product_features(product),
                url=product.url,
            )
        )
        platform_texts = self._generate_platform_texts(product, title=title, description=card_fact)

        return GeneratedContent(
            title=title,
            description=description,
            cta=cta,
            hashtags=hashtags,
            platform_texts=platform_texts or fallback_texts,
        )

    def _generate_platform_texts(self, product: Product, *, title: str, description: str) -> dict[str, str] | None:
        if not self.gemini_api_key:
            logger.info("Gemini content generation skipped: GEMINI_API_KEY is not configured; using fallback.")
            return None

        product_data = ProductData(
            title=title,
            description=description or product.description,
            features=_product_features(product),
            url=product.url,
        )
        logger.info("Gemini content generation started for product nmID=%s.", product.nm_id)
        try:
            if self.client is None:
                response = _post_gemini_request(
                    self.gemini_model,
                    self.gemini_api_key,
                    _gemini_request_body(product_data),
                    client=None,
                )
            else:
                response = _post_gemini_request(
                    self.gemini_model,
                    self.gemini_api_key,
                    _gemini_request_body(product_data),
                    client=self.client,
                )
            result = _parse_gemini_social_texts(response.json())
            logger.info("Gemini content generation succeeded for product nmID=%s.", product.nm_id)
            return result
        except Exception as exc:
            logger.warning("Gemini content generation fallback used for product nmID=%s: %s", product.nm_id, exc)
            return None


def _build_description(
    *,
    variant: int,
    title: str,
    brand: str,
    fact: str,
    price: str,
    cta: str,
) -> str:
    title_sentence = _sentence(title)
    brand_part = _brand_phrase(brand)
    fact_sentence = _sentence(fact) if fact else ""
    price_sentence = f"Цена: {price.rstrip('.')}." if price else ""

    if variant == 0:
        parts = [title_sentence, fact_sentence, price_sentence, cta + "."]
    elif variant == 1:
        parts = [brand_part, title_sentence, price_sentence, fact_sentence, cta + "."]
    elif variant == 2:
        parts = [title_sentence, price_sentence, fact_sentence, "Подробнее в карточке на Вайлдберриз."]
    else:
        intro = f"{title.rstrip('.')} в наличии на Вайлдберриз."
        parts = [intro, fact_sentence, price_sentence, cta + "."]

    return _clean_text(" ".join(part for part in parts if part))


def _gemini_request_body(product: ProductData) -> dict[str, Any]:
    return {
        "contents": [{"role": "user", "parts": [{"text": _gemini_prompt(product)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "vk": {"type": "string"},
                    "instagram": {"type": "string"},
                    "pinterest": {"type": "string"},
                },
                "required": ["vk", "instagram", "pinterest"],
            },
            "thinkingConfig": {
                "thinkingBudget": 0,
            },
            "temperature": 0.7,
            "maxOutputTokens": 1200,
        },
    }


def _post_gemini_request(
    model: str,
    api_key: str,
    body: dict[str, Any],
    *,
    client: httpx.Client | None,
) -> httpx.Response:
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    path = f"/v1beta/models/{model}:generateContent"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            if client is None:
                response = httpx.post(
                    f"https://generativelanguage.googleapis.com{path}",
                    headers=headers,
                    json=body,
                    timeout=30,
                )
            else:
                response = client.post(path, headers=headers, json=body)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(1 + attempt)
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Gemini request failed without response.")


def _gemini_prompt(product: ProductData) -> str:
    return f"""Ты маркетолог для e-commerce.

На основе карточки товара Wildberries создай короткие тексты для публикации в соцсетях.

Верни строго JSON без markdown:
{{
"vk": "короткий текст для VK",
"instagram": "короткий текст для Instagram",
"pinterest": "короткий текст для Pinterest"
}}

Требования:

- каждый текст 2-4 предложения
- простой живой русский язык
- не выдумывай характеристик, которых нет во входных данных
- без чрезмерных обещаний
- без канцелярита
- добавь мягкий призыв посмотреть товар
- адаптируй стиль под площадку

Для VK:

- чуть более информативно
- акцент на пользу товара

Для Instagram:

- более живо и визуально
- можно чуть эмоциональнее, но без кринжа

Для Pinterest:

- коротко
- акцент на идею, стиль, применение или визуальную привлекательность

Данные товара:
Название: {product.title}
Описание: {product.description}
Характеристики: {product.features}
Ссылка: {product.url}
"""


def _parse_gemini_social_texts(body: dict[str, Any]) -> dict[str, str]:
    text = _extract_gemini_text(body)
    parsed = json.loads(_strip_json_markdown(text))
    if not isinstance(parsed, dict):
        raise ValueError("Gemini response JSON is not an object.")

    result: dict[str, str] = {}
    for platform in ("vk", "instagram", "pinterest"):
        value = parsed.get(platform)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Gemini response missing text for {platform}.")
        result[platform] = _limit_platform_text(value)
    return result


def _extract_gemini_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini response does not include candidates.")
    parts = ((candidates[0].get("content") or {}).get("parts") if isinstance(candidates[0], dict) else None) or []
    texts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    text = "\n".join(texts).strip()
    if not text:
        raise ValueError("Gemini response does not include text.")
    return text


def _strip_json_markdown(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _limit_platform_text(text: str) -> str:
    cleaned = _clean_text(text)
    return _limit(cleaned, 700)


def _fallback_social_texts(product: ProductData) -> dict[str, str]:
    title = _sentence(_localize_title(product.title)).rstrip(".")
    fact = _extract_card_fact(product.description)
    features = _clean_text(product.features.replace("Бренд: ", ""))
    link = product.url.strip()

    features_sentence = _sentence(features) if features else ""
    vk_parts = [title + ".", fact, features_sentence, "Посмотрите карточку товара на Wildberries."]
    instagram_parts = [title + ".", fact, features_sentence, "Можно найти на Wildberries по ссылке в карточке товара."]
    pinterest_parts = [title + ".", fact, features_sentence, "Идея для подборки с новинками Wildberries."]
    if link:
        vk_parts.append(link)
        pinterest_parts.append(link)

    return {
        "vk": _clean_text(" ".join(part for part in vk_parts if part)),
        "instagram": _clean_text(" ".join(part for part in instagram_parts if part)),
        "pinterest": _clean_text(" ".join(part for part in pinterest_parts if part)),
    }


def _product_features(product: Product) -> str:
    values = []
    if product.brand:
        values.append(f"Бренд: {product.brand}")
    if product.price is not None:
        values.append(f"Цена: {_format_price(product.price)}")
    if product.stock > 0:
        values.append(f"Остаток: {product.stock}")
    return "; ".join(values)


def _extract_card_fact(description: str) -> str:
    cleaned = _clean_text(_strip_html(description))
    if not cleaned:
        return ""

    candidates = _split_sentences(cleaned)
    for sentence in candidates:
        normalized = sentence.strip(" .")
        if not normalized or _looks_like_noise(normalized):
            continue
        localized = _localize_snippet(normalized)
        if _mostly_latin(localized):
            continue
        return _limit(_sentence(localized), 170)

    localized = _localize_snippet(cleaned)
    if _mostly_latin(localized):
        return ""
    return _limit(_sentence(localized), 170)


def _split_sentences(value: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    if len(sentences) == 1:
        sentences = re.split(r"\s{2,}|;\s+", normalized)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _looks_like_noise(value: str) -> bool:
    lowered = value.lower()
    if len(value) < 18:
        return True
    if lowered.count("#") > 1 or lowered.count("http") > 0:
        return True
    noisy_phrases = {
        "идеальный выбор",
        "лучший подарок",
        "must have",
        "must-have",
        "хит продаж",
        "топ продаж",
        "самая низкая цена",
    }
    return any(phrase in lowered for phrase in noisy_phrases)


def _localize_title(title: str) -> str:
    cleaned = _clean_text(title)
    if not cleaned:
        return "Новинка на Вайлдберриз"

    localized = _known_english_title(cleaned)
    if localized:
        return localized

    return _sentence_case(cleaned)


def _localize_snippet(value: str) -> str:
    localized = _known_english_title(value)
    return localized or value


def _known_english_title(title: str) -> str:
    lowered = title.lower().strip()
    phrase_map = {
        "knit sweater with high neck": "Вязаный свитер с высоким воротом",
        "knitted sweater with high neck": "Вязаный свитер с высоким воротом",
        "high neck sweater": "Свитер с высоким воротом",
        "beanie hat": "Вязаная шапка",
        "knit hat": "Вязаная шапка",
        "t-shirt": "Футболка",
        "hoodie": "Худи",
        "sweatshirt": "Свитшот",
        "dress": "Платье",
        "shirt": "Рубашка",
        "trousers": "Брюки",
        "pants": "Брюки",
    }
    for phrase, translation in phrase_map.items():
        if lowered == phrase:
            return translation
        if lowered.endswith(" " + phrase):
            prefix = title[: -len(phrase)].strip(" :-")
            if prefix:
                return f"{prefix}: {translation}"
            return translation

    replacements = [
        (r"\bknitted\b", "вязаный"),
        (r"\bknit\b", "вязаный"),
        (r"\bhigh neck\b", "с высоким воротом"),
        (r"\bsweater\b", "свитер"),
        (r"\bbeanie\b", "шапка"),
        (r"\bhat\b", "шапка"),
        (r"\bt-shirt\b", "футболка"),
        (r"\bhoodie\b", "худи"),
        (r"\bsweatshirt\b", "свитшот"),
        (r"\bdress\b", "платье"),
        (r"\bshirt\b", "рубашка"),
        (r"\btrousers\b", "брюки"),
        (r"\bpants\b", "брюки"),
        (r"\bwith\b", "с"),
        (r"\bfor\b", "для"),
        (r"\band\b", "и"),
    ]
    result = lowered
    replacements_applied = 0
    for pattern, replacement in replacements:
        result, count = re.subn(pattern, replacement, result)
        replacements_applied += count

    if replacements_applied == 0:
        return ""

    result = result.replace("с с высоким", "с высоким")
    result = _clean_text(result)
    return _sentence_case(result)


def _mostly_latin(value: str) -> bool:
    latin = len(re.findall(r"[A-Za-z]", value))
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", value))
    return latin > 3 and latin > cyrillic


def _build_hashtags(brand: str, text: str) -> list[str]:
    tags = ["#Wildberries", "#ВБНовинки"]
    brand_tag = _hashtag(_display_brand(brand, text))
    if brand_tag and brand_tag.lower() not in {tag.lower() for tag in tags}:
        tags.insert(0, brand_tag)

    category_tag = _category_hashtag(text)
    if category_tag and category_tag not in tags:
        tags.append(category_tag)

    return tags[:4]


def _display_brand(brand: str, text: str) -> str:
    if brand.strip().lower() not in {"wildberries", "wb", "вб", "вайлдберриз"}:
        return brand

    latin_tokens = re.findall(r"\b[A-Z][A-Za-z0-9&-]{2,}\b", text)
    ignored = {"WB", "Wildberries"}
    for token in reversed(latin_tokens):
        if token not in ignored:
            return token
    return brand


def _category_hashtag(text: str) -> str:
    lowered = text.lower()
    categories = [
        (("свитер", "джемпер", "кофта", "sweater"), "#Свитер"),
        (("шапка", "beanie", "hat"), "#Шапка"),
        (("платье", "dress"), "#Платье"),
        (("футболка", "t-shirt"), "#Футболка"),
        (("брюки", "trousers", "pants"), "#Брюки"),
        (("рубашка", "shirt"), "#Рубашка"),
        (("худи", "hoodie"), "#Худи"),
        (("обувь", "кроссовки", "ботинки", "туфли"), "#Обувь"),
        (("сумка", "рюкзак"), "#Сумка"),
    ]
    for needles, tag in categories:
        if any(needle in lowered for needle in needles):
            return tag
    return ""


def _hashtag(value: str) -> str:
    tag = re.sub(r"[^\w]+", "", value, flags=re.UNICODE)
    if not tag:
        return ""
    return "#" + tag[:40]


def _cta_for_product(nm_id: int) -> str:
    ctas = [
        "Смотреть на Вайлдберриз",
        "Открыть карточку на Вайлдберриз",
        "Перейти к товару на Вайлдберриз",
    ]
    return ctas[nm_id % len(ctas)]


def _brand_phrase(brand: str) -> str:
    if not brand:
        return ""
    return f"Бренд: {brand}."


def _format_price(price: float | None) -> str:
    if price is None:
        return ""
    return f"{price:,.0f}".replace(",", " ") + " руб."


def _sentence(value: str) -> str:
    cleaned = _sentence_case(_clean_text(value)).rstrip(".")
    if not cleaned:
        return ""
    return cleaned + "."


def _sentence_case(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(without_tags)


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


_DESCRIPTION_VARIANTS = (0, 1, 2, 3)
