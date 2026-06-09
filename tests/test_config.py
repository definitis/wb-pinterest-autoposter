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


def test_load_settings_uses_demo_pinterest_board_when_env_is_empty(monkeypatch) -> None:
    monkeypatch.setenv("PINTEREST_BOARD_ID", "")

    settings = load_settings()

    assert settings.pinterest_board_id == "demo-board"


def test_load_settings_reads_zernio_settings(monkeypatch) -> None:
    monkeypatch.setenv("ZERNIO_API_KEY", "token")
    monkeypatch.setenv("ZERNIO_ENABLE_REAL_PUBLISH", "1")
    monkeypatch.setenv("ZERNIO_PINTEREST_ACCOUNT_ID", "acc-pin")
    monkeypatch.setenv("ZERNIO_PINTEREST_BOARD_ID", "board-pin")
    monkeypatch.setenv("ZERNIO_INSTAGRAM_ACCOUNT_ID", "acc-ig")
    monkeypatch.setenv("ZERNIO_INSTAGRAM_CONTENT_TYPE", "story")
    monkeypatch.setenv("INSTAGRAM_ENABLE_REAL_PUBLISH", "1")
    monkeypatch.setenv("INSTAGRAM_POST_LIMIT_PER_RUN", "2")

    settings = load_settings()

    assert settings.zernio_api_key == "token"
    assert settings.zernio_enable_real_publish is True
    assert settings.zernio_pinterest_account_id == "acc-pin"
    assert settings.zernio_pinterest_board_id == "board-pin"
    assert settings.zernio_instagram_account_id == "acc-ig"
    assert settings.zernio_instagram_content_type == "story"
    assert settings.instagram_enable_real_publish is True
    assert settings.instagram_post_limit_per_run == 2


def test_load_settings_reads_gemini_settings(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-token")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("CONTENT_RULES_PATH", "config/content_rules.example.json")
    monkeypatch.setenv("GEMINI_REQUEST_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("GEMINI_429_COOLDOWN_SECONDS", "30")

    settings = load_settings()

    assert settings.gemini_api_key == "gemini-token"
    assert settings.gemini_model == "gemini-test"
    assert settings.content_rules_path == Path("config/content_rules.example.json")
    assert settings.gemini_request_interval_seconds == 2.5
    assert settings.gemini_429_cooldown_seconds == 30


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
