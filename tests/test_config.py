from __future__ import annotations

from pathlib import Path

import pytest

from wb_autoposter.config import load_settings


def test_load_settings_can_use_one_wb_api_token_for_all_wb_scopes(monkeypatch) -> None:
    for name in ("WB_CONTENT_API_TOKEN", "WB_PRICES_API_TOKEN", "WB_ANALYTICS_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WB_API_TOKEN", "shared-token")
    monkeypatch.setenv("WB_BRAND_FILTER", "North Atelier, Second Brand")
    monkeypatch.setenv("WB_STOCK_TYPE", "wb")
    monkeypatch.setenv("WB_ANALYTICS_PERIOD_DAYS", "3")

    settings = load_settings()

    assert settings.mode == "test"
    assert settings.wb_api_token == "shared-token"
    assert settings.wb_prices_api_token == "shared-token"
    assert settings.wb_analytics_api_token == "shared-token"
    assert settings.wb_brand_filter == ["North Atelier", "Second Brand"]
    assert settings.wb_stock_type == "wb"
    assert settings.wb_analytics_period_days == 3


def test_load_settings_rejects_non_positive_analytics_period(monkeypatch) -> None:
    monkeypatch.setenv("WB_ANALYTICS_PERIOD_DAYS", "0")

    with pytest.raises(ValueError, match="positive integer"):
        load_settings()


def test_load_settings_reads_local_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VK_OWNER_ID", raising=False)
    monkeypatch.delenv("VK_GROUP_ID", raising=False)
    (tmp_path / ".env").write_text("VK_OWNER_ID=-123\nVK_GROUP_ID=123\n", encoding="utf-8")

    settings = load_settings()

    assert settings.vk_owner_id == "-123"
    assert settings.vk_group_id == 123


def test_load_settings_reads_post_limits(monkeypatch) -> None:
    monkeypatch.setenv("PINTEREST_POST_LIMIT_PER_RUN", "10")
    monkeypatch.setenv("VK_POST_LIMIT_PER_RUN", "3")

    settings = load_settings()

    assert settings.pinterest_post_limit_per_run == 10
    assert settings.vk_post_limit_per_run == 3


def test_load_settings_reads_wb_public_limits(monkeypatch) -> None:
    monkeypatch.setenv("WB_PUBLIC_QUERY", "hm")
    monkeypatch.setenv("WB_PUBLIC_BASELINE_LIMIT", "500")
    monkeypatch.setenv("WB_PUBLIC_SCAN_LIMIT", "50")
    monkeypatch.setenv("WB_PUBLIC_TOP_WINDOW_SIZE", "10")
    monkeypatch.setenv("WB_PUBLIC_SORT", "newly")

    settings = load_settings()

    assert settings.wb_public_query == "hm"
    assert settings.wb_public_baseline_limit == 500
    assert settings.wb_public_scan_limit == 50
    assert settings.wb_public_top_window_size == 10
    assert settings.wb_public_sort == "newly"


def test_load_settings_rejects_non_positive_post_limit(monkeypatch) -> None:
    monkeypatch.setenv("VK_POST_LIMIT_PER_RUN", "0")

    with pytest.raises(ValueError, match="positive integer"):
        load_settings()
