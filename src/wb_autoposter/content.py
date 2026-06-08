from __future__ import annotations

import html
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
    """Deterministic Russian social copy generated only from the WB card data."""

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

        return GeneratedContent(
            title=title,
            description=description,
            cta=cta,
            hashtags=hashtags,
        )


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
    price_sentence = f"Цена: {price}." if price else ""

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
    brand_tag = _hashtag(brand)
    if brand_tag:
        tags.insert(0, brand_tag)

    category_tag = _category_hashtag(text)
    if category_tag and category_tag not in tags:
        tags.append(category_tag)

    return tags[:4]


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
