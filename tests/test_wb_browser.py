import wb_autoposter.adapters.wb_browser as wb_browser
import pytest
from wb_autoposter.adapters.wb_browser import extract_nm_ids_from_html, extract_product_cards_from_html


def test_extract_nm_ids_from_html_deduplicates_wb_product_links() -> None:
    html = """
    <a href="/catalog/111222333/detail.aspx">one</a>
    <a href="https://www.wildberries.ru/catalog/444555666/detail.aspx?targetUrl=EX">two</a>
    <a href="/catalog/111222333/detail.aspx">duplicate</a>
    <a href="/catalog/not-a-number/detail.aspx">bad</a>
    """

    assert extract_nm_ids_from_html(html) == [111222333, 444555666]


def test_extract_product_cards_from_html_extracts_basic_card_data() -> None:
    html = """
    <a href="/catalog/111222333/detail.aspx">Пальто шерстяное 7 490 ₽</a>
    <a href="https://www.wildberries.ru/catalog/444555666/detail.aspx?targetUrl=EX">Жакет 5 990 ₽</a>
    <a href="/catalog/111222333/detail.aspx">duplicate</a>
    """

    cards = extract_product_cards_from_html(html)

    assert [card.nm_id for card in cards] == [111222333, 444555666]
    assert cards[0].title == "Пальто шерстяное 7 490 ₽"
    assert cards[0].price == 7490
    assert cards[0].url == "https://www.wildberries.ru/catalog/111222333/detail.aspx"


def test_selenium_nm_id_collection_waits_then_closes_driver(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    class FakeDriver:
        def get(self, url):
            calls.append(f"get:{url}")

        def execute_script(self, script, *args):
            calls.append("execute_script")
            return [111222333]

        def quit(self):
            calls.append("quit")

    monkeypatch.setattr(wb_browser, "_create_undetected_chrome_driver", lambda **kwargs: FakeDriver())
    monkeypatch.setattr(wb_browser, "sleep", lambda seconds: calls.append(f"sleep:{seconds}"))

    result = wb_browser.collect_wb_seller_nm_ids(
        seller_url="https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
        output_path=tmp_path / "nmids.json",
        max_scrolls=1,
        manual_ready=False,
        ready_delay_seconds=2.0,
    )

    assert result.nm_ids == [111222333]
    assert "sleep:2.0" in calls
    assert calls[-1] == "quit"


def test_selenium_product_scan_moves_to_all_products_before_extracting(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    class FakeDriver:
        def get(self, url):
            calls.append(f"get:{url}")

        def execute_script(self, script, *args):
            if "productLinks" in script:
                calls.append("page_metrics")
                return {"height": 1000, "productLinks": 0}
            if "scrollIntoView" in script:
                calls.append("find_all_products")
                return True
            if "cards.push" in script:
                calls.append("extract_cards")
                return [
                    {
                        "nm_id": 222333444,
                        "title": "Платье",
                        "price": 3990,
                        "photo_url": "https://example.com/dress.jpg",
                        "url": "https://www.wildberries.ru/catalog/222333444/detail.aspx",
                    }
                ]
            calls.append("scroll")
            return None

        def quit(self):
            calls.append("quit")

    monkeypatch.setattr(wb_browser, "_create_undetected_chrome_driver", lambda **kwargs: FakeDriver())
    monkeypatch.setattr(wb_browser, "sleep", lambda seconds: calls.append(f"sleep:{seconds}"))

    result = wb_browser.collect_wb_seller_product_cards(
        seller_url="https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
        output_path=tmp_path / "cards.json",
        scan_limit=1,
        max_scrolls=1,
        manual_ready=False,
        ready_delay_seconds=2.0,
    )

    assert result.nm_ids == [222333444]
    assert calls[:4] == [
        "get:https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
        "sleep:2.0",
        "page_metrics",
        "find_all_products",
    ]
    assert "extract_cards" in calls
    assert calls[-1] == "quit"


def test_selenium_product_scan_fails_if_all_products_section_is_missing(monkeypatch) -> None:
    calls: list[str] = []

    class FakeDriver:
        def get(self, url):
            calls.append(f"get:{url}")

        def execute_script(self, script, *args):
            if "productLinks" in script:
                calls.append("page_metrics")
                return {"height": 1000, "productLinks": 0}
            if "scrollIntoView" in script:
                calls.append("find_all_products")
                return False
            calls.append("extract_cards")
            return []

        def quit(self):
            calls.append("quit")

    monkeypatch.setattr(wb_browser, "_create_undetected_chrome_driver", lambda **kwargs: FakeDriver())
    monkeypatch.setattr(wb_browser, "sleep", lambda seconds: None)

    with pytest.raises(ValueError, match="All products"):
        wb_browser.collect_wb_seller_product_cards(
            seller_url="https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            scan_limit=1,
            max_scrolls=1,
            scroll_delay_ms=1,
            manual_ready=False,
        )

    assert "extract_cards" not in calls
    assert calls[-1] == "quit"
