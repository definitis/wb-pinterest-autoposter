from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    mode: str
    db_path: Path
    fake_products_path: Path
    out_dir: Path
    pinterest_board_id: str
    pinterest_enable_real_publish: bool
    pinterest_utm_enabled: bool
    pinterest_utm_source: str
    pinterest_utm_medium: str
    pinterest_utm_campaign: str
    pinterest_post_limit_per_run: int | None
    wb_api_token: str | None
    wb_prices_api_token: str | None
    wb_analytics_api_token: str | None
    wb_brand_filter: list[str]
    wb_stock_type: str
    wb_analytics_period_days: int
    wb_public_query: str | None
    wb_public_supplier_id: int | None
    wb_public_brand: str | None
    wb_public_pages: int
    wb_public_limit: int | None
    wb_public_baseline_limit: int | None
    wb_public_scan_limit: int
    wb_public_top_window_size: int
    wb_public_dest: str
    wb_public_sort: str
    pinterest_access_token: str | None
    vk_access_token: str | None
    vk_app_id: str | None
    vk_owner_id: str | None
    vk_group_id: int | None
    vk_api_version: str
    vk_enable_real_publish: bool
    vk_from_group: bool
    vk_upload_photo: bool
    vk_browser_enable: bool
    vk_browser_state_path: Path
    vk_browser_group_url: str | None
    vk_browser_headless: bool
    vk_browser_confirm_before_post: bool
    vk_utm_enabled: bool
    vk_utm_source: str
    vk_utm_medium: str
    vk_utm_campaign: str
    vk_post_limit_per_run: int | None
    instagram_access_token: str | None
    instagram_user_id: str | None
    zernio_api_key: str | None
    zernio_enable_real_publish: bool
    zernio_pinterest_account_id: str | None
    zernio_pinterest_board_id: str | None
    zernio_instagram_account_id: str | None
    zernio_instagram_content_type: str


def load_settings() -> Settings:
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)
    legacy_wb_token = os.getenv("WB_API_TOKEN") or None
    return Settings(
        mode=os.getenv("WB_AUTOPOSTER_MODE", "test").strip() or "test",
        db_path=Path(os.getenv("WB_AUTOPOSTER_DB_PATH", "out/app.sqlite3")),
        fake_products_path=Path(os.getenv("WB_FAKE_PRODUCTS_PATH", "data/fake_wb_products.json")),
        out_dir=Path(os.getenv("WB_AUTOPOSTER_OUT_DIR", "out")),
        pinterest_board_id=os.getenv("PINTEREST_BOARD_ID") or "demo-board",
        pinterest_enable_real_publish=_parse_bool(os.getenv("PINTEREST_ENABLE_REAL_PUBLISH"), default=False),
        pinterest_utm_enabled=_parse_bool(os.getenv("PINTEREST_UTM_ENABLED"), default=False),
        pinterest_utm_source=os.getenv("PINTEREST_UTM_SOURCE", "pinterest"),
        pinterest_utm_medium=os.getenv("PINTEREST_UTM_MEDIUM", "social"),
        pinterest_utm_campaign=os.getenv("PINTEREST_UTM_CAMPAIGN", "wb_new_arrivals"),
        pinterest_post_limit_per_run=_parse_optional_positive_int(os.getenv("PINTEREST_POST_LIMIT_PER_RUN")),
        wb_api_token=os.getenv("WB_CONTENT_API_TOKEN") or legacy_wb_token,
        wb_prices_api_token=os.getenv("WB_PRICES_API_TOKEN") or legacy_wb_token,
        wb_analytics_api_token=os.getenv("WB_ANALYTICS_API_TOKEN") or legacy_wb_token,
        wb_brand_filter=_parse_csv(os.getenv("WB_BRAND_FILTER")),
        wb_stock_type=os.getenv("WB_STOCK_TYPE", "").strip(),
        wb_analytics_period_days=_parse_positive_int(os.getenv("WB_ANALYTICS_PERIOD_DAYS"), default=1),
        wb_public_query=os.getenv("WB_PUBLIC_QUERY") or None,
        wb_public_supplier_id=_parse_optional_int(os.getenv("WB_PUBLIC_SUPPLIER_ID")),
        wb_public_brand=os.getenv("WB_PUBLIC_BRAND") or None,
        wb_public_pages=_parse_positive_int(os.getenv("WB_PUBLIC_PAGES"), default=1),
        wb_public_limit=_parse_optional_positive_int(os.getenv("WB_PUBLIC_LIMIT")),
        wb_public_baseline_limit=(
            _parse_optional_positive_int(os.getenv("WB_PUBLIC_BASELINE_LIMIT"))
            or _parse_optional_positive_int(os.getenv("WB_PUBLIC_LIMIT"))
        ),
        wb_public_scan_limit=_parse_positive_int(os.getenv("WB_PUBLIC_SCAN_LIMIT"), default=50),
        wb_public_top_window_size=_parse_positive_int(
            os.getenv("WB_PUBLIC_TOP_WINDOW_SIZE") or os.getenv("WB_PUBLIC_CHECKPOINT_SIZE"),
            default=10,
        ),
        wb_public_dest=os.getenv("WB_PUBLIC_DEST", "-1257786"),
        wb_public_sort=os.getenv("WB_PUBLIC_SORT", "newly"),
        pinterest_access_token=os.getenv("PINTEREST_ACCESS_TOKEN") or None,
        vk_access_token=os.getenv("VK_ACCESS_TOKEN") or None,
        vk_app_id=os.getenv("VK_APP_ID") or None,
        vk_owner_id=os.getenv("VK_OWNER_ID") or None,
        vk_group_id=_parse_optional_int(os.getenv("VK_GROUP_ID")),
        vk_api_version=os.getenv("VK_API_VERSION", "5.199"),
        vk_enable_real_publish=_parse_bool(os.getenv("VK_ENABLE_REAL_PUBLISH"), default=False),
        vk_from_group=_parse_bool(os.getenv("VK_FROM_GROUP"), default=True),
        vk_upload_photo=_parse_bool(os.getenv("VK_UPLOAD_PHOTO"), default=True),
        vk_browser_enable=_parse_bool(os.getenv("VK_BROWSER_ENABLE"), default=False),
        vk_browser_state_path=Path(os.getenv("VK_BROWSER_STATE_PATH", "out/vk_browser_state.json")),
        vk_browser_group_url=os.getenv("VK_BROWSER_GROUP_URL") or None,
        vk_browser_headless=_parse_bool(os.getenv("VK_BROWSER_HEADLESS"), default=False),
        vk_browser_confirm_before_post=_parse_bool(os.getenv("VK_BROWSER_CONFIRM_BEFORE_POST"), default=True),
        vk_utm_enabled=_parse_bool(os.getenv("VK_UTM_ENABLED"), default=False),
        vk_utm_source=os.getenv("VK_UTM_SOURCE", "vk"),
        vk_utm_medium=os.getenv("VK_UTM_MEDIUM", "social"),
        vk_utm_campaign=os.getenv("VK_UTM_CAMPAIGN", "wb_new_arrivals"),
        vk_post_limit_per_run=_parse_optional_positive_int(os.getenv("VK_POST_LIMIT_PER_RUN")),
        instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN") or None,
        instagram_user_id=os.getenv("INSTAGRAM_USER_ID") or None,
        zernio_api_key=os.getenv("ZERNIO_API_KEY") or None,
        zernio_enable_real_publish=_parse_bool(os.getenv("ZERNIO_ENABLE_REAL_PUBLISH"), default=False),
        zernio_pinterest_account_id=os.getenv("ZERNIO_PINTEREST_ACCOUNT_ID") or None,
        zernio_pinterest_board_id=os.getenv("ZERNIO_PINTEREST_BOARD_ID") or None,
        zernio_instagram_account_id=os.getenv("ZERNIO_INSTAGRAM_ACCOUNT_ID") or None,
        zernio_instagram_content_type=os.getenv("ZERNIO_INSTAGRAM_CONTENT_TYPE", "feed").strip() or "feed",
    )


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_positive_int(value: str | None, *, default: int) -> int:
    if not value:
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError("Expected a positive integer.")
    return parsed


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_optional_positive_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError("Expected a positive integer.")
    return parsed


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Expected a boolean value, got {value!r}.")
