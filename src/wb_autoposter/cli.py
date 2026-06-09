from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from wb_autoposter.adapters import FakeWBSource, WBEnrichedProductSource, WBPublicCatalogSource
from wb_autoposter.adapters.wb_browser import SOURCE_NAME as WB_BROWSER_SOURCE_NAME
from wb_autoposter.adapters.wb_browser import collect_wb_seller_product_cards
from wb_autoposter.adapters.wb_browser import collect_wb_seller_nm_ids
from wb_autoposter.config import Settings, load_settings
from wb_autoposter.dashboard import export_dashboard as export_dashboard_html
from wb_autoposter.models import PlannedPost, PostStatus, SocialPostMetrics
from wb_autoposter.publishers import (
    InstagramApiPublisher,
    InstagramDryRunPublisher,
    PinterestApiPublisher,
    PinterestDryRunPublisher,
    VKApiPublisher,
    VKBrowserPublisher,
    VKDryRunPublisher,
    ZernioInstagramPublisher,
    ZernioPinterestPublisher,
    ZernioPublisher,
)
from wb_autoposter.publishers.instagram import validate_instagram_payload
from wb_autoposter.publishers.pinterest import validate_pinterest_payload
from wb_autoposter.publishers.vk import build_vk_oauth_url, validate_vk_payload
from wb_autoposter.publishers.vk_browser import save_vk_browser_login
from wb_autoposter.storage import Store

app = typer.Typer(help="WB новинки -> VK/Pinterest autoposter MVP.")


APP_MODES = {"test", "real-ready"}
SOURCES = {"fake", "wb-api", "wb-public"}
PLATFORMS = {"instagram", "pinterest", "vk"}
ZERNIO_METRICS_PLATFORMS = {"instagram", "pinterest"}


def _resolve_source(settings: Settings, mode: str | None, source: str | None) -> tuple[str, str]:
    if source is not None:
        if source not in SOURCES:
            raise typer.BadParameter("source must be 'fake', 'wb-api', or 'wb-public'.")
        resolved_mode = mode or ("test" if source == "fake" else "real-ready")
        if resolved_mode not in APP_MODES:
            raise typer.BadParameter("mode must be 'test' or 'real-ready'.")
        return resolved_mode, source

    resolved_mode = mode or settings.mode
    if resolved_mode not in APP_MODES:
        raise typer.BadParameter("mode must be 'test' or 'real-ready'.")

    return resolved_mode, "fake" if resolved_mode == "test" else "wb-api"


def _sync_products(store: Store, source: str, fixture_path: Path, settings: Settings) -> dict[str, int]:
    if source == "fake":
        product_source = FakeWBSource(fixture_path)
    elif source == "wb-api":
        _validate_wb_api_settings(settings)
        period_start, period_end = _wb_analytics_period(settings)
        product_source = WBEnrichedProductSource(
            content_api_token=settings.wb_api_token or "",
            prices_api_token=settings.wb_prices_api_token or "",
            analytics_api_token=settings.wb_analytics_api_token or "",
            brand_filter=settings.wb_brand_filter or None,
            stock_type=settings.wb_stock_type,
            period_start=period_start,
            period_end=period_end,
        )
    elif source == "wb-public":
        if store.baseline_at() is None:
            raise typer.BadParameter("WB public baseline is missing. Run baseline-sync --source wb-public first.")
        product_source = _build_wb_public_source(settings, limit=settings.wb_public_scan_limit)
        nm_ids = product_source.fetch_nm_ids()
        seen_result = store.upsert_seen_nm_ids(nm_ids, source=WBPublicCatalogSource.SOURCE_NAME)
        target_nm_ids = store.list_seen_nm_ids_pending_details(source=WBPublicCatalogSource.SOURCE_NAME)
        product_result = store.upsert_products(product_source.fetch_products(target_nm_ids))
        top_window = store.set_source_top_window(
            source=WBPublicCatalogSource.SOURCE_NAME,
            nm_ids=nm_ids,
            window_size=settings.wb_public_top_window_size,
        )
        return {
            **product_result,
            "discovered_nm_ids": seen_result["total"],
            "seen_created": seen_result["created"],
            "seen_updated": seen_result["updated"],
            "details_requested": len(target_nm_ids),
            "top_window_saved": len(top_window),
        }
    else:
        raise typer.BadParameter("source must be 'fake', 'wb-api', or 'wb-public'.")

    return store.upsert_products(product_source.fetch_products())


def _build_wb_public_source(settings: Settings, *, limit: int | None = None) -> WBPublicCatalogSource:
    if not settings.wb_public_query:
        raise typer.BadParameter("WB_PUBLIC_QUERY is required for source=wb-public.")
    return WBPublicCatalogSource(
        query=settings.wb_public_query,
        supplier_id=settings.wb_public_supplier_id,
        brand=settings.wb_public_brand,
        pages=settings.wb_public_pages,
        limit=limit if limit is not None else settings.wb_public_limit,
        dest=settings.wb_public_dest,
        sort=settings.wb_public_sort,
    )


def _validate_wb_api_settings(settings: Settings) -> None:
    missing: list[str] = []
    if not settings.wb_api_token:
        missing.append("WB_CONTENT_API_TOKEN")
    if not settings.wb_prices_api_token:
        missing.append("WB_PRICES_API_TOKEN")
    if not settings.wb_analytics_api_token:
        missing.append("WB_ANALYTICS_API_TOKEN")

    if missing:
        raise typer.BadParameter(
            "mode=real-ready requires "
            + ", ".join(missing)
            + " or one WB_API_TOKEN with all required WB categories."
        )

    if settings.wb_stock_type not in {"", "wb", "mp"}:
        raise typer.BadParameter("WB_STOCK_TYPE must be empty, 'wb', or 'mp'.")


def _wb_analytics_period(settings: Settings) -> tuple[str, str]:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=settings.wb_analytics_period_days - 1)
    return start.isoformat(), end.isoformat()


def _pinterest_tracking_params(settings: Settings) -> dict[str, str] | None:
    if not settings.pinterest_utm_enabled:
        return None
    return {
        "utm_source": settings.pinterest_utm_source,
        "utm_medium": settings.pinterest_utm_medium,
        "utm_campaign": settings.pinterest_utm_campaign,
    }


def _vk_tracking_params(settings: Settings) -> dict[str, str] | None:
    if not settings.vk_utm_enabled:
        return None
    return {
        "utm_source": settings.vk_utm_source,
        "utm_medium": settings.vk_utm_medium,
        "utm_campaign": settings.vk_utm_campaign,
    }


def _tracking_params(settings: Settings, platform: str) -> dict[str, str] | None:
    if platform == "pinterest":
        return _pinterest_tracking_params(settings)
    if platform == "vk":
        return _vk_tracking_params(settings)
    if platform == "instagram":
        return None
    raise typer.BadParameter("platform must be 'instagram', 'pinterest', or 'vk'.")


def _publish_limit(settings: Settings, platform: str, override: int | None = None) -> int | None:
    if override is not None:
        if override < 1:
            raise typer.BadParameter("limit must be greater than zero.")
        return override
    if platform == "pinterest":
        return settings.pinterest_post_limit_per_run
    if platform == "instagram":
        return settings.instagram_post_limit_per_run
    if platform == "vk":
        return settings.vk_post_limit_per_run
    raise typer.BadParameter("platform must be 'instagram', 'pinterest', or 'vk'.")


def _validate_platform(platform: str) -> None:
    if platform not in PLATFORMS:
        raise typer.BadParameter("platform must be 'instagram', 'pinterest', or 'vk'.")


def _validate_metrics_platform(platform: str) -> None:
    if platform != "all" and platform not in ZERNIO_METRICS_PLATFORMS:
        raise typer.BadParameter("platform must be 'all', 'instagram', or 'pinterest'.")


def _zernio_account_id_for_metrics(settings: Settings, platform: str) -> str | None:
    if platform == "pinterest":
        return settings.zernio_pinterest_account_id
    if platform == "instagram":
        return settings.zernio_instagram_account_id
    return None


def _build_social_publisher(
    settings: Settings,
    platform: str,
    dry_run: bool,
    out_dir: Path,
    browser: bool = False,
    zernio: bool = False,
):
    _validate_platform(platform)
    if platform == "pinterest":
        if browser:
            raise typer.BadParameter("--browser is only supported for VK publishing.")
        if zernio and not dry_run:
            return _build_zernio_pinterest_publisher(settings, out_dir)
        return _build_pinterest_publisher(settings, dry_run, out_dir)
    if platform == "instagram":
        if browser:
            raise typer.BadParameter("--browser is only supported for VK publishing.")
        if zernio and not dry_run:
            return _build_zernio_instagram_publisher(settings, out_dir)
        return _build_instagram_publisher(settings, dry_run, out_dir)
    if zernio:
        raise typer.BadParameter("--zernio is currently supported only for Pinterest/Instagram publishing.")
    return _build_vk_publisher(settings, dry_run, out_dir, browser=browser)


def _build_pinterest_publisher(settings: Settings, dry_run: bool, out_dir: Path):
    if dry_run:
        return PinterestDryRunPublisher(out_dir)
    if not settings.pinterest_enable_real_publish:
        raise typer.BadParameter(
            "Real Pinterest publishing is disabled. Set PINTEREST_ENABLE_REAL_PUBLISH=1 to enable it."
        )
    if not settings.pinterest_access_token:
        raise typer.BadParameter("PINTEREST_ACCESS_TOKEN is required for real Pinterest publishing.")
    return PinterestApiPublisher(settings.pinterest_access_token)


def _build_zernio_pinterest_publisher(settings: Settings, out_dir: Path):
    if not settings.zernio_enable_real_publish:
        raise typer.BadParameter(
            "Real Zernio publishing is disabled. Set ZERNIO_ENABLE_REAL_PUBLISH=1 to enable it."
        )
    if not settings.zernio_api_key:
        raise typer.BadParameter("ZERNIO_API_KEY is required for real Zernio publishing.")
    if not settings.zernio_pinterest_account_id:
        raise typer.BadParameter("ZERNIO_PINTEREST_ACCOUNT_ID is required for Zernio Pinterest publishing.")
    if not settings.zernio_pinterest_board_id:
        raise typer.BadParameter("ZERNIO_PINTEREST_BOARD_ID is required for Zernio Pinterest publishing.")
    return ZernioPinterestPublisher(
        settings.zernio_api_key,
        account_id=settings.zernio_pinterest_account_id,
        board_id=settings.zernio_pinterest_board_id,
        out_dir=out_dir,
    )


def _build_instagram_publisher(settings: Settings, dry_run: bool, out_dir: Path):
    if dry_run:
        return InstagramDryRunPublisher(out_dir)
    if not settings.instagram_enable_real_publish:
        raise typer.BadParameter(
            "Real Instagram publishing is disabled. Set INSTAGRAM_ENABLE_REAL_PUBLISH=1 to enable it."
        )
    if not settings.instagram_access_token:
        raise typer.BadParameter("INSTAGRAM_ACCESS_TOKEN is required for direct Instagram publishing.")
    if not settings.instagram_user_id:
        raise typer.BadParameter("INSTAGRAM_USER_ID is required for direct Instagram publishing.")
    return InstagramApiPublisher(settings.instagram_access_token, settings.instagram_user_id)


def _build_zernio_instagram_publisher(settings: Settings, out_dir: Path):
    if not settings.zernio_enable_real_publish:
        raise typer.BadParameter(
            "Real Zernio publishing is disabled. Set ZERNIO_ENABLE_REAL_PUBLISH=1 to enable it."
        )
    if not settings.zernio_api_key:
        raise typer.BadParameter("ZERNIO_API_KEY is required for real Zernio publishing.")
    if not settings.zernio_instagram_account_id:
        raise typer.BadParameter("ZERNIO_INSTAGRAM_ACCOUNT_ID is required for Zernio Instagram publishing.")
    return ZernioInstagramPublisher(
        settings.zernio_api_key,
        account_id=settings.zernio_instagram_account_id,
        content_type=settings.zernio_instagram_content_type,
        out_dir=out_dir,
    )


def _build_vk_publisher(settings: Settings, dry_run: bool, out_dir: Path, *, browser: bool = False):
    if browser:
        if dry_run:
            raise typer.BadParameter("Use --no-dry-run with --browser.")
        if not settings.vk_browser_enable:
            raise typer.BadParameter("VK browser publishing is disabled. Set VK_BROWSER_ENABLE=1 to enable it.")
        if not settings.vk_owner_id:
            raise typer.BadParameter("VK_OWNER_ID is required for VK browser publishing.")
        return VKBrowserPublisher(
            state_path=settings.vk_browser_state_path,
            out_dir=out_dir,
            group_url=settings.vk_browser_group_url,
            headless=settings.vk_browser_headless,
            confirm_before_post=settings.vk_browser_confirm_before_post,
        )
    if dry_run:
        return VKDryRunPublisher(out_dir)
    if not settings.vk_enable_real_publish:
        raise typer.BadParameter("Real VK publishing is disabled. Set VK_ENABLE_REAL_PUBLISH=1 to enable it.")
    if not settings.vk_access_token:
        raise typer.BadParameter("VK_ACCESS_TOKEN is required for real VK publishing.")
    if not settings.vk_owner_id:
        raise typer.BadParameter("VK_OWNER_ID is required for real VK publishing.")
    return VKApiPublisher(
        settings.vk_access_token,
        owner_id=settings.vk_owner_id,
        group_id=settings.vk_group_id,
        api_version=settings.vk_api_version,
    )


def _vk_owner_id_for_planning(settings: Settings, override: str | None = None) -> str:
    return override or settings.vk_owner_id or "-100000000"


def _pinterest_board_id_for_planning(
    settings: Settings,
    override: str | None = None,
    *,
    prefer_zernio: bool = False,
) -> str:
    if override and override.strip():
        return override
    if settings.pinterest_board_id.strip() and settings.pinterest_board_id != "demo-board":
        return settings.pinterest_board_id
    if prefer_zernio and settings.zernio_pinterest_board_id:
        return settings.zernio_pinterest_board_id
    return settings.pinterest_board_id


def _publish_planned_posts(store: Store, publisher, platform: str, limit: int | None = None) -> dict[str, int]:
    posts = store.list_posts(platform=platform, status=PostStatus.PLANNED)
    if limit is not None:
        posts = posts[:limit]
    published = 0
    failed = 0

    should_close = False
    if hasattr(publisher, "open"):
        publisher.open()
        should_close = hasattr(publisher, "close")

    try:
        for post in posts:
            try:
                store.mark_post_publishing(post.id)
            except ValueError as exc:
                failed += 1
                typer.echo(f"Skipped post #{post.id}: {exc}")
                continue

            try:
                result = publisher.publish(post.id, post.payload)
                store.update_post_result(post.id, result.status, result.external_id, result.error)
                published += 1
                if result.payload_path:
                    typer.echo(f"Publish artifact saved: {result.payload_path}")
            except Exception as exc:  # pragma: no cover - defensive CLI boundary
                error = _friendly_publish_error(platform, str(exc))
                store.update_post_result(post.id, PostStatus.FAILED, None, error)
                failed += 1
                typer.echo(f"Failed post #{post.id} nmID={post.product_nm_id}: {error}")
    finally:
        if should_close:
            publisher.close()

    return {"processed": len(posts), "published": published, "failed": failed}


def _publish_platform_after_scan(
    *,
    store: Store,
    settings: Settings,
    platform: str,
    dry_run: bool,
    limit: int | None,
    out_dir: Path,
    board_id: str | None = None,
    vk_owner_id: str | None = None,
    browser: bool = False,
    zernio: bool = False,
) -> dict[str, int]:
    retry_result = _retry_failed_for_publish(
        store,
        settings,
        platform=platform,
        board_id=board_id,
        vk_owner_id=vk_owner_id,
    )
    if retry_result["retried"] or retry_result["skipped_ineligible"] or retry_result["skipped_missing_product"]:
        typer.echo(
            f"Auto-retried {retry_result['retried']} failed {platform} posts. "
            f"Skipped ineligible: {retry_result['skipped_ineligible']}. "
            f"Skipped missing products: {retry_result['skipped_missing_product']}."
        )

    planned_posts = store.list_posts(platform=platform, status=PostStatus.PLANNED)
    if not planned_posts:
        typer.echo(f"No planned {platform} posts. Nothing to publish.")
        return {"processed": 0, "published": 0, "failed": 0}

    publisher = _build_social_publisher(
        settings,
        platform,
        dry_run=dry_run,
        out_dir=out_dir,
        browser=browser,
        zernio=zernio,
    )
    result = _publish_planned_posts(
        store,
        publisher,
        platform,
        limit=_publish_limit(settings, platform, limit),
    )
    typer.echo(
        f"Processed {result['processed']} planned posts: "
        f"{result['published']} ok, {result['failed']} failed."
    )
    return result


def _friendly_publish_error(platform: str, error: str) -> str:
    if platform != "vk":
        return error
    hints = []
    normalized = error.lower()
    if "post editor" in normalized or "publish button" in normalized or "could not find vk" in normalized:
        hints.append(
            "Check that VK browser session is logged into an account with permission to post in the target community."
        )
        hints.append("If needed, run: python -m wb_autoposter.cli vk-browser-login")
    if "session is missing" in normalized:
        hints.append("Run: python -m wb_autoposter.cli vk-browser-login")
    if not hints:
        return error
    return error + " " + " ".join(hints)


def _print_report(
    store: Store,
    platform: str | None = "pinterest",
) -> None:
    summary = store.summary()
    posts = store.list_posts(platform=platform) if platform else store.list_posts()

    typer.echo("Project report")
    typer.echo(f"Last sync: {summary['last_sync_at'] or 'never'}")
    typer.echo(f"Baseline: {summary['baseline_at'] or 'not set'}")
    typer.echo(f"Products total: {summary['products_total']}")
    typer.echo(f"Products publishable: {summary['products_publishable']}")
    typer.echo(f"Posts total: {summary['posts_total']}")
    typer.echo(f"Posts by status: {summary['posts_by_status']}")

    if posts:
        label = platform.upper() if platform else "Social"
        typer.echo(f"\n{label} posts:")
        for post in posts:
            typer.echo(
                f"- #{post.id} nmID={post.product_nm_id} "
                f"status={post.status.value} external_id={post.external_id or '-'}"
            )


def _sync_zernio_metrics(
    *,
    store: Store,
    settings: Settings,
    platform: str,
    from_date: str | None,
    to_date: str | None,
    limit: int | None,
) -> dict[str, int]:
    _validate_metrics_platform(platform)
    if not settings.zernio_api_key:
        raise typer.BadParameter("ZERNIO_API_KEY is required for sync-metrics.")

    platforms = sorted(ZERNIO_METRICS_PLATFORMS) if platform == "all" else [platform]
    posts = [
        post
        for post in store.list_posts(status=PostStatus.PUBLISHED)
        if post.platform in platforms and post.external_id
    ]
    posts.sort(key=lambda post: (post.published_at or post.created_at, post.id), reverse=True)
    if limit is not None:
        posts = posts[:limit]

    client = ZernioPublisher(settings.zernio_api_key)
    synced = 0
    pending = 0
    failed = 0
    skipped = 0

    for post in posts:
        account_id = _zernio_account_id_for_metrics(settings, post.platform)
        if not account_id:
            skipped += 1
            typer.echo(f"Skipped post #{post.id}: missing Zernio account ID for {post.platform}.")
            continue
        try:
            body = client.get_post_analytics(
                post_id=post.external_id,
                platform=post.platform,
                account_id=account_id,
                from_date=from_date,
                to_date=to_date,
            )
            if body.get("_http_status") == 202:
                pending += 1
                typer.echo(f"Pending metrics for post #{post.id} external_id={post.external_id}.")
                continue
            metrics = _social_metrics_from_zernio(post, body)
            saved = store.save_post_metrics(metrics)
            synced += 1
            typer.echo(
                f"Synced {post.platform} post #{post.id} nmID={post.product_nm_id}: "
                f"impressions={saved.impressions or 0} reach={saved.reach or 0} "
                f"clicks={saved.clicks or 0} likes={saved.likes or 0} saves={saved.saves or 0}."
            )
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            failed += 1
            typer.echo(f"Failed metrics for post #{post.id} external_id={post.external_id}: {exc}")

    return {"processed": len(posts), "synced": synced, "pending": pending, "failed": failed, "skipped": skipped}


def _social_metrics_from_zernio(post: PlannedPost, body: dict[str, object]) -> SocialPostMetrics:
    return SocialPostMetrics(
        post_id=post.id,
        product_nm_id=post.product_nm_id,
        platform=post.platform,
        external_id=post.external_id,
        source="zernio",
        captured_at=datetime.now(UTC),
        impressions=_metric_value(body, "impressions", "impressionCount", "impressionsCount"),
        reach=_metric_value(body, "reach", "reachCount"),
        clicks=_metric_value(body, "clicks", "clickCount", "linkClicks", "outboundClicks"),
        likes=_metric_value(body, "likes", "likeCount", "likesCount"),
        comments=_metric_value(body, "comments", "commentCount", "commentsCount"),
        saves=_metric_value(body, "saves", "saveCount", "savesCount"),
        shares=_metric_value(body, "shares", "shareCount", "sharesCount"),
        views=_metric_value(body, "views", "viewCount", "videoViews", "videoViewCount"),
        engagement=_metric_value(body, "engagement", "engagements", "engagementCount"),
        raw=body,
    )


def _metric_value(body: object, *keys: str) -> int | None:
    lowered_keys = {key.lower() for key in keys}
    if isinstance(body, dict):
        for key, value in body.items():
            if str(key).lower() in lowered_keys:
                parsed = _optional_metric_int(value)
                if parsed is not None:
                    return parsed
        for value in body.values():
            parsed = _metric_value(value, *keys)
            if parsed is not None:
                return parsed
    elif isinstance(body, list):
        for item in body:
            parsed = _metric_value(item, *keys)
            if parsed is not None:
                return parsed
    return None


def _optional_metric_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "")
        if cleaned.isdigit():
            return int(cleaned)
    return None


def _print_metrics_report(store: Store, *, platform: str, limit: int | None) -> None:
    _validate_metrics_platform(platform)
    resolved_platform = None if platform == "all" else platform
    summary = store.metrics_summary(platform=resolved_platform)
    metrics = store.latest_post_metrics(platform=resolved_platform, limit=limit)

    typer.echo("Social metrics report")
    typer.echo(f"Platform: {platform}")
    typer.echo(f"Posts with metrics: {summary['posts_with_metrics']}")
    typer.echo(
        "Totals: "
        f"impressions={summary['impressions']} reach={summary['reach']} clicks={summary['clicks']} "
        f"likes={summary['likes']} comments={summary['comments']} saves={summary['saves']} "
        f"shares={summary['shares']} views={summary['views']} engagement={summary['engagement']}"
    )
    if not metrics:
        typer.echo("No metrics saved yet. Run sync-metrics first.")
        return

    typer.echo("\nLatest per post:")
    for item in metrics:
        typer.echo(
            f"- {item.platform} post #{item.post_id} nmID={item.product_nm_id} "
            f"external_id={item.external_id or '-'} captured_at={item.captured_at.isoformat()} "
            f"impressions={item.impressions or 0} reach={item.reach or 0} clicks={item.clicks or 0} "
            f"likes={item.likes or 0} comments={item.comments or 0} saves={item.saves or 0} "
            f"shares={item.shares or 0} views={item.views or 0}"
        )


def _print_plan_result(result: dict[str, int]) -> None:
    message = (
        f"Planned {result['planned']} posts. "
        f"Skipped existing: {result['skipped_existing']}. "
        f"Skipped ineligible: {result['skipped_ineligible']}."
    )
    if "skipped_baseline" in result:
        message += f" Skipped baseline: {result['skipped_baseline']}."
    typer.echo(message)


def _plan_platform_posts(
    store: Store,
    settings: Settings,
    *,
    platform: str,
    board_id: str | None = None,
    vk_owner_id: str | None = None,
) -> dict[str, int]:
    return store.plan_posts(
        platform=platform,
        board_id=_pinterest_board_id_for_planning(settings, board_id, prefer_zernio=platform == "pinterest"),
        vk_owner_id=_vk_owner_id_for_planning(settings, vk_owner_id),
        vk_from_group=settings.vk_from_group,
        vk_upload_photo=settings.vk_upload_photo,
        tracking_params=_tracking_params(settings, platform),
        only_after_baseline=True,
    )


def _retry_failed_for_publish(
    store: Store,
    settings: Settings,
    *,
    platform: str,
    board_id: str | None = None,
    vk_owner_id: str | None = None,
) -> dict[str, int]:
    return store.retry_failed_posts(
        platform=platform,
        board_id=_pinterest_board_id_for_planning(settings, board_id, prefer_zernio=platform == "pinterest"),
        vk_owner_id=_vk_owner_id_for_planning(settings, vk_owner_id),
        vk_from_group=settings.vk_from_group,
        vk_upload_photo=settings.vk_upload_photo,
        tracking_params=_tracking_params(settings, platform),
    )


def _ensure_wb_browser_baseline(
    store: Store,
    *,
    error_message: str = "Baseline not found. Run wb-browser-baseline first.",
) -> None:
    if store.baseline_at() is None or store.count_seen_products(source=WB_BROWSER_SOURCE_NAME) == 0:
        raise typer.BadParameter(error_message)


def _ensure_vk_browser_ready_for_real_publish(settings: Settings, *, browser: bool) -> None:
    if not browser:
        raise typer.BadParameter("Real VK publish in this MVP requires --browser.")
    if not settings.vk_browser_enable:
        raise typer.BadParameter("VK browser publishing is disabled. Set VK_BROWSER_ENABLE=1 to enable it.")
    if not settings.vk_browser_state_path.exists():
        raise typer.BadParameter("VK browser session not found. Run vk-browser-login first.")


def _sync_wb_browser_new_products(
    *,
    settings: Settings,
    store: Store,
    seller_url: str,
    browser_engine: str,
    scan_limit: int,
    platform: str,
    board_id: str | None,
    vk_owner_id: str | None,
    output_path: Path | None,
    state_path: Path | None,
    browser_channel: str | None,
    user_data_dir: Path | None,
    cdp_url: str | None,
    chrome_binary: Path | None,
    chromedriver_path: Path | None,
    auto_install_driver: bool,
    headless: bool,
    manual_ready: bool,
    ready_delay_seconds: float,
    max_scrolls: int,
    idle_scrolls: int,
    scroll_delay_ms: int,
    scroll_pixels: int,
    plan: bool = True,
    baseline_error_message: str = "Baseline not found. Run wb-browser-baseline first.",
) -> dict[str, object]:
    _ensure_wb_browser_baseline(store, error_message=baseline_error_message)
    try:
        scan_result = collect_wb_seller_product_cards(
            seller_url=seller_url,
            browser_engine=browser_engine,
            scan_limit=scan_limit,
            output_path=output_path,
            state_path=state_path,
            browser_channel=browser_channel or None,
            user_data_dir=user_data_dir,
            cdp_url=cdp_url,
            chrome_binary=chrome_binary,
            chromedriver_path=chromedriver_path,
            auto_install_driver=auto_install_driver,
            headless=headless,
            manual_ready=manual_ready,
            ready_delay_seconds=ready_delay_seconds,
            max_scrolls=max_scrolls,
            idle_scrolls=idle_scrolls,
            scroll_delay_ms=scroll_delay_ms,
            scroll_pixels=scroll_pixels,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not scan_result.nm_ids:
        raise typer.BadParameter(
            "WB browser new scan found 0 nmIDs. Refusing to sync; "
            "make sure the seller page loaded and product cards are visible."
        )

    seen_result = store.upsert_seen_nm_ids(scan_result.nm_ids, source=WB_BROWSER_SOURCE_NAME)
    target_nm_ids = set(store.list_seen_nm_ids_pending_details(source=WB_BROWSER_SOURCE_NAME))
    new_products = [product for product in scan_result.products if product.nm_id in target_nm_ids]
    product_result = store.upsert_products(new_products)
    top_window = store.set_source_top_window(
        source=WB_BROWSER_SOURCE_NAME,
        nm_ids=scan_result.nm_ids,
        window_size=settings.wb_public_top_window_size,
    )

    plan_result: dict[str, int] | None = None
    if plan:
        try:
            plan_result = store.plan_posts(
                platform=platform,
                board_id=_pinterest_board_id_for_planning(settings, board_id, prefer_zernio=platform == "pinterest"),
                vk_owner_id=_vk_owner_id_for_planning(settings, vk_owner_id),
                vk_from_group=settings.vk_from_group,
                vk_upload_photo=settings.vk_upload_photo,
                tracking_params=_tracking_params(settings, platform),
                only_after_baseline=True,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    return {
        "scan_result": scan_result,
        "seen_result": seen_result,
        "product_result": product_result,
        "top_window_saved": len(top_window),
        "plan_result": plan_result,
    }


def _print_wb_browser_sync_result(result: dict[str, object]) -> None:
    scan_result = result["scan_result"]
    seen_result = result["seen_result"]
    product_result = result["product_result"]

    typer.echo(f"Source: {WB_BROWSER_SOURCE_NAME}")
    typer.echo(f"Scanned {seen_result['total']} newest WB nmIDs in {scan_result.iterations} scroll iterations.")
    typer.echo(f"Known before scan: {seen_result['updated']} nmIDs.")
    typer.echo(f"New nmIDs detected: {seen_result['created']}.")
    typer.echo(
        f"Synced {product_result['total']} new product cards: "
        f"{product_result['created']} created, {product_result['updated']} updated."
    )
    typer.echo(f"Top window saved: {result['top_window_saved']} nmIDs.")
    typer.echo(f"Scan artifact saved: {scan_result.output_path}")
    plan_result = result.get("plan_result")
    if plan_result is not None:
        _print_plan_result(plan_result)


@app.command()
def check_config(
    mode: str | None = typer.Option(None, help="Run mode: test or real-ready."),
    source: str | None = typer.Option(None, help="Manual source override: fake or wb-api."),
) -> None:
    """Validate local settings required for a source without calling external APIs."""
    settings = load_settings()
    resolved_mode, resolved_source = _resolve_source(settings, mode, source)
    if resolved_source == "fake":
        typer.echo(f"Configuration OK for mode={resolved_mode}.")
        typer.echo("Resolved source: fake")
        typer.echo(f"Fixture path: {settings.fake_products_path}")
        return
    if resolved_source == "wb-public":
        _build_wb_public_source(settings)
        typer.echo(f"Configuration OK for mode={resolved_mode}.")
        typer.echo("Resolved source: wb-public")
        typer.echo(f"WB public query: {settings.wb_public_query}")
        typer.echo(f"WB public supplier ID: {settings.wb_public_supplier_id or 'any'}")
        typer.echo(f"WB public brand: {settings.wb_public_brand or 'any'}")
        typer.echo(f"WB public pages: {settings.wb_public_pages}")
        typer.echo(f"WB public limit: {settings.wb_public_limit or 'none'}")
        typer.echo(f"WB public baseline limit: {settings.wb_public_baseline_limit or 'none'}")
        typer.echo(f"WB public scan limit: {settings.wb_public_scan_limit}")
        typer.echo(f"WB public top window size: {settings.wb_public_top_window_size}")
        return

    _validate_wb_api_settings(settings)
    typer.echo(f"Configuration OK for mode={resolved_mode}.")
    typer.echo("Resolved source: wb-api")
    typer.echo(f"WB brand filter: {settings.wb_brand_filter or 'all'}")
    typer.echo(f"WB stock type: {settings.wb_stock_type or 'all'}")
    typer.echo(f"WB analytics period days: {settings.wb_analytics_period_days}")


@app.command()
def pinterest_check(
    api: bool = typer.Option(False, help="Call Pinterest API to verify board access."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Validate Pinterest settings and locally prepared payloads."""
    settings = load_settings()
    if not settings.pinterest_board_id.strip():
        raise typer.BadParameter("PINTEREST_BOARD_ID is required.")

    typer.echo("Pinterest local configuration")
    typer.echo(f"Board ID: {settings.pinterest_board_id}")
    typer.echo(f"Real publish enabled: {settings.pinterest_enable_real_publish}")
    typer.echo(f"UTM enabled: {settings.pinterest_utm_enabled}")

    store = Store(db_path or settings.db_path)
    store.init_db()
    posts = store.list_posts(platform="pinterest")
    invalid = 0
    for post in posts:
        try:
            validate_pinterest_payload(post.payload)
        except ValueError as exc:
            invalid += 1
            typer.echo(f"Invalid post #{post.id}: {exc}")

    typer.echo(f"Pinterest payloads checked: {len(posts)}")
    if invalid:
        raise typer.BadParameter(f"{invalid} Pinterest payloads are invalid.")

    if api:
        if not settings.pinterest_access_token:
            raise typer.BadParameter("PINTEREST_ACCESS_TOKEN is required for --api.")
        board = PinterestApiPublisher(settings.pinterest_access_token).get_board(settings.pinterest_board_id)
        typer.echo(f"Pinterest API board check OK: {board.get('id')}")
    else:
        typer.echo("Pinterest API board check skipped. Use --api after setting PINTEREST_ACCESS_TOKEN.")


@app.command()
def zernio_check(
    platform: str = typer.Option("pinterest", help="Zernio platform to inspect: pinterest or instagram."),
) -> None:
    """Check Zernio API access and list connected accounts without publishing."""
    settings = load_settings()
    if platform not in {"pinterest", "instagram"}:
        raise typer.BadParameter("platform must be 'pinterest' or 'instagram'.")

    typer.echo("Zernio local configuration")
    typer.echo(f"API key configured: {bool(settings.zernio_api_key)}")
    typer.echo(f"Real publish enabled: {settings.zernio_enable_real_publish}")
    if platform == "pinterest":
        typer.echo(f"Pinterest account ID configured: {settings.zernio_pinterest_account_id or '-'}")
        typer.echo(f"Pinterest board ID configured: {settings.zernio_pinterest_board_id or '-'}")
    else:
        typer.echo(f"Instagram account ID configured: {settings.zernio_instagram_account_id or '-'}")
        typer.echo(f"Instagram content type: {settings.zernio_instagram_content_type}")

    if not settings.zernio_api_key:
        raise typer.BadParameter("ZERNIO_API_KEY is required for zernio-check.")

    try:
        body = ZernioPublisher(settings.zernio_api_key).list_accounts(platform=platform)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        raise typer.BadParameter(f"Zernio API check failed: {exc}") from exc

    accounts = body.get("accounts")
    if not isinstance(accounts, list):
        accounts = []
    typer.echo(f"Connected {platform} accounts: {len(accounts)}")
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_id = account.get("_id") or account.get("accountId") or account.get("id") or "-"
        username = account.get("username") or account.get("displayName") or "-"
        is_active = account.get("isActive")
        typer.echo(f"- id={account_id} username={username} active={is_active}")


@app.command()
def instagram_check(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Validate Instagram settings and locally prepared payloads."""
    settings = load_settings()

    typer.echo("Instagram local configuration")
    typer.echo(f"Direct API user ID configured: {bool(settings.instagram_user_id)}")
    typer.echo(f"Direct API token configured: {bool(settings.instagram_access_token)}")
    typer.echo(f"Direct real publish enabled: {settings.instagram_enable_real_publish}")
    typer.echo(f"Zernio API key configured: {bool(settings.zernio_api_key)}")
    typer.echo(f"Zernio real publish enabled: {settings.zernio_enable_real_publish}")
    typer.echo(f"Zernio Instagram account ID configured: {settings.zernio_instagram_account_id or '-'}")
    typer.echo(f"Zernio Instagram content type: {settings.zernio_instagram_content_type}")

    store = Store(db_path or settings.db_path)
    store.init_db()
    posts = store.list_posts(platform="instagram")
    invalid = 0
    for post in posts:
        try:
            validate_instagram_payload(post.payload)
        except ValueError as exc:
            invalid += 1
            typer.echo(f"Invalid Instagram post #{post.id}: {exc}")

    typer.echo(f"Instagram payloads checked: {len(posts)}")
    if invalid:
        raise typer.BadParameter(f"{invalid} Instagram payloads are invalid.")


@app.command()
def vk_check(
    api: bool = typer.Option(False, help="Call VK API to verify wall access."),
    photo_upload: bool = typer.Option(False, help="Also verify photos.getWallUploadServer access."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Validate VK settings and locally prepared payloads."""
    settings = load_settings()
    if not settings.vk_owner_id:
        raise typer.BadParameter("VK_OWNER_ID is required for VK publishing.")

    typer.echo("VK local configuration")
    typer.echo(f"Owner ID: {settings.vk_owner_id}")
    typer.echo(f"Group ID: {settings.vk_group_id or 'derived from owner_id'}")
    typer.echo(f"Real publish enabled: {settings.vk_enable_real_publish}")
    typer.echo(f"Upload photo: {settings.vk_upload_photo}")
    typer.echo(f"UTM enabled: {settings.vk_utm_enabled}")

    store = Store(db_path or settings.db_path)
    store.init_db()
    posts = store.list_posts(platform="vk")
    invalid = 0
    for post in posts:
        try:
            validate_vk_payload(post.payload)
        except ValueError as exc:
            invalid += 1
            typer.echo(f"Invalid VK post #{post.id}: {exc}")

    typer.echo(f"VK payloads checked: {len(posts)}")
    if invalid:
        raise typer.BadParameter(f"{invalid} VK payloads are invalid.")

    if api:
        if not settings.vk_access_token:
            raise typer.BadParameter("VK_ACCESS_TOKEN is required for --api.")
        publisher = VKApiPublisher(
            settings.vk_access_token,
            owner_id=settings.vk_owner_id,
            group_id=settings.vk_group_id,
            api_version=settings.vk_api_version,
        )
        response = publisher.check_wall_access()
        if response.get("check") == "wall":
            typer.echo(f"VK API wall check OK: count={(response.get('response') or {}).get('count', 0)}")
        else:
            typer.echo("VK API group token check OK. wall.get is unavailable for this token type.")

        if photo_upload:
            try:
                publisher.check_photo_upload_access()
            except ValueError as exc:
                raise typer.BadParameter(
                    "VK photo upload check failed. "
                    "For posts with images, use a VK user OAuth token with wall/photos access. "
                    f"Details: {exc}"
                ) from exc
            typer.echo("VK API photo upload check OK.")
    else:
        typer.echo("VK API wall check skipped. Use --api after setting VK_ACCESS_TOKEN.")


@app.command()
def vk_auth_url(
    app_id: str | None = typer.Option(None, help="VK application ID. Falls back to VK_APP_ID."),
    scope: str = typer.Option("wall,photos,groups", help="VK OAuth scopes."),
    display: str = typer.Option("page", help="VK OAuth display mode: page, popup, mobile."),
    redirect_uri: str = typer.Option("https://oauth.vk.com/blank.html", help="VK OAuth redirect URI."),
    no_redirect_uri: bool = typer.Option(False, help="Build URL without redirect_uri."),
) -> None:
    """Print a VK OAuth URL for a user token that can upload wall photos."""
    settings = load_settings()
    resolved_app_id = app_id or settings.vk_app_id
    if not resolved_app_id:
        raise typer.BadParameter("VK_APP_ID is required. Create a VK app and put its ID in .env.")
    typer.echo(
        build_vk_oauth_url(
            resolved_app_id,
            api_version=settings.vk_api_version,
            scope=scope,
            display=display,
            redirect_uri=None if no_redirect_uri else redirect_uri,
        )
    )


@app.command()
def vk_browser_login(
    state_path: Path | None = typer.Option(None, help="Path where VK browser session will be saved."),
    start_url: str = typer.Option("https://vk.com/", help="URL opened for manual VK login."),
    headless: bool | None = typer.Option(None, help="Run browser headless. Defaults to VK_BROWSER_HEADLESS."),
) -> None:
    """Open VK in a browser and save a reusable local login session."""
    settings = load_settings()
    resolved_state_path = state_path or settings.vk_browser_state_path
    resolved_headless = settings.vk_browser_headless if headless is None else headless
    result = save_vk_browser_login(
        state_path=resolved_state_path,
        start_url=start_url,
        headless=resolved_headless,
    )
    typer.echo(f"VK browser session saved: {result.state_path}")


@app.command()
def wb_browser_baseline(
    seller_url: str = typer.Option(..., help="WB seller URL, e.g. https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1."),
    browser_engine: str = typer.Option(
        "selenium",
        help="Browser engine: selenium or playwright. Selenium uses undetected_chromedriver.",
    ),
    expected_count: int | None = typer.Option(
        None,
        help="Expected full catalog size. Used as a quality check, not an exact hard limit.",
    ),
    min_expected_ratio: float = typer.Option(
        0.95,
        help="Reject baseline only if collected/expected is below this ratio.",
    ),
    supplier_id: int | None = typer.Option(
        None,
        help="Optional WB supplierId. If set, baseline uses WB catalog JSON through the browser.",
    ),
    catalog_dest: str = typer.Option("-1257786", help="WB catalog dest parameter for --supplier-id mode."),
    catalog_sort: str = typer.Option("newly", help="WB catalog sort parameter for --supplier-id mode."),
    catalog_max_pages: int = typer.Option(100, help="Maximum WB catalog pages for --supplier-id mode."),
    catalog_request_delay_ms: int = typer.Option(
        1200,
        help="Delay between WB catalog requests in --supplier-id mode.",
    ),
    catalog_retries: int = typer.Option(3, help="Retries per WB catalog page in --supplier-id mode."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    output_path: Path | None = typer.Option(None, help="Where to save collected nmIDs JSON."),
    state_path: Path | None = typer.Option(None, help="Optional WB browser storage state path."),
    browser_channel: str | None = typer.Option(
        "chrome",
        help="Browser channel for Playwright launch, e.g. chrome or msedge. Empty uses bundled Chromium.",
    ),
    user_data_dir: Path | None = typer.Option(
        None,
        help="Persistent browser profile directory. Recommended for WB antibot checks.",
    ),
    cdp_url: str | None = typer.Option(
        None,
        help="Connect to an already running Chrome via CDP, e.g. http://127.0.0.1:9222.",
    ),
    chrome_binary: Path | None = typer.Option(
        None,
        help="Path to chrome.exe for Selenium/undetected_chromedriver.",
    ),
    chromedriver_path: Path | None = typer.Option(
        None,
        help="Explicit chromedriver path for Selenium/undetected_chromedriver.",
    ),
    auto_install_driver: bool = typer.Option(
        True,
        "--auto-install-driver/--no-auto-install-driver",
        help="Let chromedriver-autoinstaller install a matching driver when no explicit path is provided.",
    ),
    headless: bool = typer.Option(False, help="Run browser headless. Visible mode is recommended for WB checks."),
    manual_ready: bool = typer.Option(
        False,
        "--manual-ready/--no-manual-ready",
        help="Wait for Enter before scrolling. Disabled by default; use only for manual WB checks.",
    ),
    ready_delay_seconds: float = typer.Option(2.0, help="Delay before scanning when --no-manual-ready is used."),
    max_scrolls: int = typer.Option(250, help="Maximum scroll attempts."),
    idle_scrolls: int = typer.Option(12, help="Stop after this many scrolls without new nmIDs."),
    scroll_delay_ms: int = typer.Option(1400, help="Delay between scrolls in milliseconds."),
    scroll_pixels: int = typer.Option(1800, help="Vertical pixels per scroll step."),
) -> None:
    """Create a one-time baseline by collecting nmIDs from a rendered WB seller page."""
    settings = load_settings()
    resolved_output_path = output_path or settings.out_dir / "wb_browser_baseline_nmids.json"
    resolved_state_path = state_path or settings.out_dir / "wb_browser_state.json"
    store = Store(db_path or settings.db_path)
    store.init_db()

    try:
        result = collect_wb_seller_nm_ids(
            seller_url=seller_url,
            browser_engine=browser_engine,
            expected_count=expected_count,
            supplier_id=supplier_id,
            catalog_dest=catalog_dest,
            catalog_sort=catalog_sort,
            catalog_max_pages=catalog_max_pages,
            catalog_request_delay_ms=catalog_request_delay_ms,
            catalog_retries=catalog_retries,
            output_path=resolved_output_path,
            state_path=resolved_state_path,
            browser_channel=browser_channel or None,
            user_data_dir=user_data_dir,
            cdp_url=cdp_url,
            chrome_binary=chrome_binary,
            chromedriver_path=chromedriver_path,
            auto_install_driver=auto_install_driver,
            headless=headless,
            manual_ready=manual_ready,
            ready_delay_seconds=ready_delay_seconds,
            max_scrolls=max_scrolls,
            idle_scrolls=idle_scrolls,
            scroll_delay_ms=scroll_delay_ms,
            scroll_pixels=scroll_pixels,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not result.nm_ids:
        raise typer.BadParameter(
            "WB browser baseline found 0 nmIDs. Refusing to mark an empty baseline; "
            "make sure the seller page loaded and product cards are visible."
        )
    if min_expected_ratio <= 0 or min_expected_ratio > 1:
        raise typer.BadParameter("--min-expected-ratio must be greater than 0 and less than or equal to 1.")
    if expected_count is not None and len(result.nm_ids) < expected_count * min_expected_ratio:
        raise typer.BadParameter(
            f"WB browser baseline collected only {len(result.nm_ids)} of expected {expected_count} nmIDs. "
            f"This is below the minimum ratio {min_expected_ratio:.0%}. Refusing to mark an incomplete baseline."
        )
    if expected_count is not None and len(result.nm_ids) < expected_count:
        typer.echo(
            f"Warning: collected {len(result.nm_ids)} of expected {expected_count} nmIDs. "
            "Baseline is accepted because it is within the configured tolerance."
        )

    seen_result = store.upsert_seen_nm_ids(
        result.nm_ids,
        source=WB_BROWSER_SOURCE_NAME,
        mark_baseline=True,
    )
    top_window = store.set_source_top_window(
        source=WB_BROWSER_SOURCE_NAME,
        nm_ids=result.nm_ids,
        window_size=settings.wb_public_top_window_size,
    )

    typer.echo(f"Source: {WB_BROWSER_SOURCE_NAME}")
    typer.echo(f"Collected {seen_result['total']} WB nmIDs in {result.iterations} scroll iterations.")
    typer.echo(f"Baseline marked for {seen_result['baseline_marked']} nmIDs.")
    typer.echo(f"Already known before this run: {seen_result['updated']} nmIDs.")
    typer.echo(f"Top window saved: {len(top_window)} nmIDs.")
    typer.echo(f"nmID artifact saved: {result.output_path}")
    typer.echo("No product details were fetched and no posts were planned.")


@app.command()
def wb_browser_sync_new(
    seller_url: str = typer.Option(..., help="WB seller URL sorted by newness."),
    browser_engine: str = typer.Option(
        "selenium",
        help="Browser engine: selenium or playwright. Selenium uses undetected_chromedriver.",
    ),
    scan_limit: int = typer.Option(100, help="How many top seller products to scan as newest candidates."),
    plan: bool = typer.Option(
        True,
        "--plan/--no-plan",
        help="Create planned social posts for detected new products after syncing.",
    ),
    platform: str = typer.Option("vk", help="Target platform for planning: vk or pinterest."),
    board_id: str | None = typer.Option(None, help="Pinterest board ID used when planning Pinterest posts."),
    vk_owner_id: str | None = typer.Option(None, help="VK wall owner ID used when planning VK posts."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    output_path: Path | None = typer.Option(None, help="Where to save scanned product cards JSON."),
    state_path: Path | None = typer.Option(None, help="Optional WB browser storage state path."),
    browser_channel: str | None = typer.Option(
        "chrome",
        help="Browser channel for Playwright launch, e.g. chrome or msedge. Empty uses bundled Chromium.",
    ),
    user_data_dir: Path | None = typer.Option(
        None,
        help="Persistent browser profile directory. Recommended for WB antibot checks.",
    ),
    cdp_url: str | None = typer.Option(
        None,
        help="Connect to an already running Chrome via CDP, e.g. http://127.0.0.1:9222.",
    ),
    chrome_binary: Path | None = typer.Option(
        None,
        help="Path to chrome.exe for Selenium/undetected_chromedriver.",
    ),
    chromedriver_path: Path | None = typer.Option(
        None,
        help="Explicit chromedriver path for Selenium/undetected_chromedriver.",
    ),
    auto_install_driver: bool = typer.Option(
        True,
        "--auto-install-driver/--no-auto-install-driver",
        help="Let chromedriver-autoinstaller install a matching driver when no explicit path is provided.",
    ),
    headless: bool = typer.Option(False, help="Run browser headless. Visible mode is not recommended for WB checks."),
    manual_ready: bool = typer.Option(
        False,
        "--manual-ready/--no-manual-ready",
        help="Wait for Enter before scanning. Disabled by default; use only for manual WB checks.",
    ),
    ready_delay_seconds: float = typer.Option(2.0, help="Delay before scanning when --no-manual-ready is used."),
    max_scrolls: int = typer.Option(80, help="Maximum scroll attempts."),
    idle_scrolls: int = typer.Option(8, help="Stop after this many scrolls without new nmIDs."),
    scroll_delay_ms: int = typer.Option(1400, help="Delay between scrolls in milliseconds."),
    scroll_pixels: int = typer.Option(1800, help="Vertical pixels per scroll step."),
) -> None:
    """Scan newest WB seller cards through a browser and create planned posts for unknown nmIDs."""
    settings = load_settings()
    _validate_platform(platform)
    resolved_output_path = output_path or settings.out_dir / "wb_browser_new_scan_products.json"
    resolved_state_path = state_path or settings.out_dir / "wb_browser_state.json"
    store = Store(db_path or settings.db_path)
    store.init_db()

    result = _sync_wb_browser_new_products(
        settings=settings,
        store=store,
        seller_url=seller_url,
        browser_engine=browser_engine,
        scan_limit=scan_limit,
        platform=platform,
        board_id=board_id,
        vk_owner_id=vk_owner_id,
        output_path=resolved_output_path,
        state_path=resolved_state_path,
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        cdp_url=cdp_url,
        chrome_binary=chrome_binary,
        chromedriver_path=chromedriver_path,
        auto_install_driver=auto_install_driver,
        headless=headless,
        manual_ready=manual_ready,
        ready_delay_seconds=ready_delay_seconds,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
        scroll_delay_ms=scroll_delay_ms,
        scroll_pixels=scroll_pixels,
        plan=plan,
        baseline_error_message="WB browser baseline is missing. Run wb-browser-baseline first.",
    )
    _print_wb_browser_sync_result(result)
    if not plan:
        typer.echo("No posts were planned because --no-plan was used.")
        return
    typer.echo("Posts are planned only. Use publish --dry-run to preview or publish --browser --no-dry-run for VK.")


@app.command()
def wb_vk_cycle(
    seller_url: str = typer.Option(..., help="WB seller URL sorted by newness."),
    scan_limit: int = typer.Option(100, help="How many top seller products to scan as newest candidates."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Dry-run is the safe default. Use --no-dry-run only for real VK publishing.",
    ),
    browser: bool = typer.Option(False, "--browser", help="Publish real VK posts through browser automation."),
    limit: int | None = typer.Option(None, help="Maximum number of VK posts to process."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    user_data_dir: Path | None = typer.Option(
        None,
        help="Persistent WB browser profile directory. Use the same profile as wb-browser-baseline.",
    ),
    browser_engine: str = typer.Option(
        "selenium",
        help="WB browser engine: selenium or playwright. Selenium uses undetected_chromedriver.",
    ),
    output_path: Path | None = typer.Option(None, help="Where to save scanned WB product cards JSON."),
    state_path: Path | None = typer.Option(None, help="Optional WB browser storage state path."),
    browser_channel: str | None = typer.Option("chrome", help="Browser channel for Playwright launch."),
    cdp_url: str | None = typer.Option(None, help="Connect to an already running Chrome via CDP."),
    chrome_binary: Path | None = typer.Option(None, help="Path to chrome.exe for Selenium/undetected_chromedriver."),
    chromedriver_path: Path | None = typer.Option(None, help="Explicit chromedriver path for Selenium."),
    auto_install_driver: bool = typer.Option(
        True,
        "--auto-install-driver/--no-auto-install-driver",
        help="Let chromedriver-autoinstaller install a matching driver when no explicit path is provided.",
    ),
    headless: bool = typer.Option(False, help="Run WB browser headless. Visible mode is recommended for WB checks."),
    manual_ready: bool = typer.Option(
        False,
        "--manual-ready/--no-manual-ready",
        help="Wait for Enter before scanning. Disabled by default.",
    ),
    ready_delay_seconds: float = typer.Option(2.0, help="Delay before scanning when --no-manual-ready is used."),
    max_scrolls: int = typer.Option(80, help="Maximum WB scroll attempts."),
    idle_scrolls: int = typer.Option(8, help="Stop WB scan after this many scrolls without new nmIDs."),
    scroll_delay_ms: int = typer.Option(1400, help="Maximum wait for WB products to load after each scroll."),
    scroll_pixels: int = typer.Option(1800, help="Vertical pixels per WB scroll step."),
    out_dir: Path | None = typer.Option(None, help="Output directory for dry-run payloads and media artifacts."),
) -> None:
    """Run the regular WB -> VK cycle after baseline: scan, plan, publish/dry-run, status."""
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    store.init_db()
    _ensure_wb_browser_baseline(store)
    if not dry_run:
        _ensure_vk_browser_ready_for_real_publish(settings, browser=browser)

    resolved_output_path = output_path or settings.out_dir / "wb_browser_new_scan_products.json"
    resolved_state_path = state_path or settings.out_dir / "wb_browser_state.json"

    typer.echo("Step 1/3: scan WB new products")
    sync_result = _sync_wb_browser_new_products(
        settings=settings,
        store=store,
        seller_url=seller_url,
        browser_engine=browser_engine,
        scan_limit=scan_limit,
        platform="vk",
        board_id=None,
        vk_owner_id=None,
        output_path=resolved_output_path,
        state_path=resolved_state_path,
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        cdp_url=cdp_url,
        chrome_binary=chrome_binary,
        chromedriver_path=chromedriver_path,
        auto_install_driver=auto_install_driver,
        headless=headless,
        manual_ready=manual_ready,
        ready_delay_seconds=ready_delay_seconds,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
        scroll_delay_ms=scroll_delay_ms,
        scroll_pixels=scroll_pixels,
        plan=True,
    )
    _print_wb_browser_sync_result(sync_result)

    planned_posts = store.list_posts(platform="vk", status=PostStatus.PLANNED)
    if not planned_posts:
        typer.echo("No new products found. Nothing to publish.")
        _print_wb_vk_cycle_summary(
            store=store,
            sync_result=sync_result,
            publish_result={"processed": 0, "published": 0, "failed": 0},
        )
        return

    typer.echo("\nStep 2/3: publish VK dry-run" if dry_run else "\nStep 2/3: publish VK real browser")
    publish_result = _publish_platform_after_scan(
        store=store,
        settings=settings,
        platform="vk",
        dry_run=dry_run,
        out_dir=out_dir or settings.out_dir,
        limit=limit,
        browser=False if dry_run else browser,
    )

    typer.echo("\nStep 3/3: status")
    _print_wb_vk_cycle_summary(store=store, sync_result=sync_result, publish_result=publish_result)


@app.command()
def wb_pinterest_cycle(
    seller_url: str = typer.Option(..., help="WB seller URL sorted by newness."),
    scan_limit: int = typer.Option(100, help="How many top seller products to scan as newest candidates."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Dry-run is the safe default. Use --no-dry-run only for real Pinterest publishing.",
    ),
    zernio: bool = typer.Option(
        True,
        "--zernio/--direct-api",
        help="Use Zernio for real Pinterest publishing. --direct-api uses Pinterest API settings.",
    ),
    limit: int | None = typer.Option(None, help="Maximum number of Pinterest posts to process."),
    board_id: str | None = typer.Option(None, help="Pinterest board ID used for planning."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    user_data_dir: Path | None = typer.Option(
        None,
        help="Persistent WB browser profile directory. Use the same profile as wb-browser-baseline.",
    ),
    browser_engine: str = typer.Option(
        "selenium",
        help="WB browser engine: selenium or playwright. Selenium uses undetected_chromedriver.",
    ),
    output_path: Path | None = typer.Option(None, help="Where to save scanned WB product cards JSON."),
    state_path: Path | None = typer.Option(None, help="Optional WB browser storage state path."),
    browser_channel: str | None = typer.Option("chrome", help="Browser channel for Playwright launch."),
    cdp_url: str | None = typer.Option(None, help="Connect to an already running Chrome via CDP."),
    chrome_binary: Path | None = typer.Option(None, help="Path to chrome.exe for Selenium/undetected_chromedriver."),
    chromedriver_path: Path | None = typer.Option(None, help="Explicit chromedriver path for Selenium."),
    auto_install_driver: bool = typer.Option(
        True,
        "--auto-install-driver/--no-auto-install-driver",
        help="Let chromedriver-autoinstaller install a matching driver when no explicit path is provided.",
    ),
    headless: bool = typer.Option(False, help="Run WB browser headless. Visible mode is recommended for WB checks."),
    manual_ready: bool = typer.Option(
        False,
        "--manual-ready/--no-manual-ready",
        help="Wait for Enter before scanning. Disabled by default.",
    ),
    ready_delay_seconds: float = typer.Option(2.0, help="Delay before scanning when --no-manual-ready is used."),
    max_scrolls: int = typer.Option(80, help="Maximum WB scroll attempts."),
    idle_scrolls: int = typer.Option(8, help="Stop WB scan after this many scrolls without new nmIDs."),
    scroll_delay_ms: int = typer.Option(1400, help="Maximum wait for WB products to load after each scroll."),
    scroll_pixels: int = typer.Option(1800, help="Vertical pixels per WB scroll step."),
    out_dir: Path | None = typer.Option(None, help="Output directory for dry-run payloads and Zernio artifacts."),
) -> None:
    """Run the regular WB -> Pinterest cycle after baseline: scan, plan, publish/dry-run, status."""
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    store.init_db()
    _ensure_wb_browser_baseline(store)

    resolved_output_path = output_path or settings.out_dir / "wb_browser_new_scan_products.json"
    resolved_state_path = state_path or settings.out_dir / "wb_browser_state.json"
    planning_board_id = _pinterest_board_id_for_planning(settings, board_id, prefer_zernio=zernio)

    typer.echo("Step 1/3: scan WB new products")
    sync_result = _sync_wb_browser_new_products(
        settings=settings,
        store=store,
        seller_url=seller_url,
        browser_engine=browser_engine,
        scan_limit=scan_limit,
        platform="pinterest",
        board_id=planning_board_id,
        vk_owner_id=None,
        output_path=resolved_output_path,
        state_path=resolved_state_path,
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        cdp_url=cdp_url,
        chrome_binary=chrome_binary,
        chromedriver_path=chromedriver_path,
        auto_install_driver=auto_install_driver,
        headless=headless,
        manual_ready=manual_ready,
        ready_delay_seconds=ready_delay_seconds,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
        scroll_delay_ms=scroll_delay_ms,
        scroll_pixels=scroll_pixels,
        plan=True,
    )
    _print_wb_browser_sync_result(sync_result)

    planned_posts = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)
    if not planned_posts:
        typer.echo("No new products found. Nothing to publish.")
        _print_wb_pinterest_cycle_summary(
            store=store,
            sync_result=sync_result,
            publish_result={"processed": 0, "published": 0, "failed": 0},
        )
        return

    if dry_run:
        typer.echo("\nStep 2/3: publish Pinterest dry-run")
    elif zernio:
        typer.echo("\nStep 2/3: publish Pinterest real Zernio")
    else:
        typer.echo("\nStep 2/3: publish Pinterest real direct API")

    publish_result = _publish_platform_after_scan(
        store=store,
        settings=settings,
        platform="pinterest",
        dry_run=dry_run,
        out_dir=out_dir or settings.out_dir,
        limit=limit,
        board_id=planning_board_id,
        zernio=zernio,
    )

    typer.echo("\nStep 3/3: status")
    _print_wb_pinterest_cycle_summary(store=store, sync_result=sync_result, publish_result=publish_result)


@app.command()
def wb_instagram_cycle(
    seller_url: str = typer.Option(..., help="WB seller URL sorted by newness."),
    scan_limit: int = typer.Option(100, help="How many top seller products to scan as newest candidates."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Dry-run is the safe default. Use --no-dry-run only for real Instagram publishing.",
    ),
    zernio: bool = typer.Option(
        True,
        "--zernio/--direct-api",
        help="Use Zernio for real Instagram publishing. --direct-api uses Instagram Graph API settings.",
    ),
    limit: int | None = typer.Option(None, help="Maximum number of Instagram posts to process."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    user_data_dir: Path | None = typer.Option(
        None,
        help="Persistent WB browser profile directory. Use the same profile as wb-browser-baseline.",
    ),
    browser_engine: str = typer.Option(
        "selenium",
        help="WB browser engine: selenium or playwright. Selenium uses undetected_chromedriver.",
    ),
    output_path: Path | None = typer.Option(None, help="Where to save scanned WB product cards JSON."),
    state_path: Path | None = typer.Option(None, help="Optional WB browser storage state path."),
    browser_channel: str | None = typer.Option("chrome", help="Browser channel for Playwright launch."),
    cdp_url: str | None = typer.Option(None, help="Connect to an already running Chrome via CDP."),
    chrome_binary: Path | None = typer.Option(None, help="Path to chrome.exe for Selenium/undetected_chromedriver."),
    chromedriver_path: Path | None = typer.Option(None, help="Explicit chromedriver path for Selenium."),
    auto_install_driver: bool = typer.Option(
        True,
        "--auto-install-driver/--no-auto-install-driver",
        help="Let chromedriver-autoinstaller install a matching driver when no explicit path is provided.",
    ),
    headless: bool = typer.Option(False, help="Run WB browser headless. Visible mode is recommended for WB checks."),
    manual_ready: bool = typer.Option(
        False,
        "--manual-ready/--no-manual-ready",
        help="Wait for Enter before scanning. Disabled by default.",
    ),
    ready_delay_seconds: float = typer.Option(2.0, help="Delay before scanning when --no-manual-ready is used."),
    max_scrolls: int = typer.Option(80, help="Maximum WB scroll attempts."),
    idle_scrolls: int = typer.Option(8, help="Stop WB scan after this many scrolls without new nmIDs."),
    scroll_delay_ms: int = typer.Option(1400, help="Maximum wait for WB products to load after each scroll."),
    scroll_pixels: int = typer.Option(1800, help="Vertical pixels per WB scroll step."),
    out_dir: Path | None = typer.Option(None, help="Output directory for dry-run payloads and Zernio artifacts."),
) -> None:
    """Run the regular WB -> Instagram cycle after baseline: scan, plan, publish/dry-run, status."""
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    store.init_db()
    _ensure_wb_browser_baseline(store)

    resolved_output_path = output_path or settings.out_dir / "wb_browser_new_scan_products.json"
    resolved_state_path = state_path or settings.out_dir / "wb_browser_state.json"

    typer.echo("Step 1/3: scan WB new products")
    sync_result = _sync_wb_browser_new_products(
        settings=settings,
        store=store,
        seller_url=seller_url,
        browser_engine=browser_engine,
        scan_limit=scan_limit,
        platform="instagram",
        board_id=None,
        vk_owner_id=None,
        output_path=resolved_output_path,
        state_path=resolved_state_path,
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        cdp_url=cdp_url,
        chrome_binary=chrome_binary,
        chromedriver_path=chromedriver_path,
        auto_install_driver=auto_install_driver,
        headless=headless,
        manual_ready=manual_ready,
        ready_delay_seconds=ready_delay_seconds,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
        scroll_delay_ms=scroll_delay_ms,
        scroll_pixels=scroll_pixels,
        plan=True,
    )
    _print_wb_browser_sync_result(sync_result)

    planned_posts = store.list_posts(platform="instagram", status=PostStatus.PLANNED)
    if not planned_posts:
        typer.echo("No new products found. Nothing to publish.")
        _print_wb_instagram_cycle_summary(
            store=store,
            sync_result=sync_result,
            publish_result={"processed": 0, "published": 0, "failed": 0},
        )
        return

    if dry_run:
        typer.echo("\nStep 2/3: publish Instagram dry-run")
    elif zernio:
        typer.echo("\nStep 2/3: publish Instagram real Zernio")
    else:
        typer.echo("\nStep 2/3: publish Instagram real direct API")

    publish_result = _publish_platform_after_scan(
        store=store,
        settings=settings,
        platform="instagram",
        dry_run=dry_run,
        out_dir=out_dir or settings.out_dir,
        limit=limit,
        zernio=zernio,
    )

    typer.echo("\nStep 3/3: status")
    _print_wb_instagram_cycle_summary(store=store, sync_result=sync_result, publish_result=publish_result)


@app.command()
def wb_social_cycle(
    seller_url: str = typer.Option(..., help="WB seller URL sorted by newness."),
    scan_limit: int = typer.Option(100, help="How many top seller products to scan as newest candidates."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Dry-run is the safe default. Use --no-dry-run only after platform checks pass.",
    ),
    vk: bool = typer.Option(True, "--vk/--no-vk", help="Plan and publish VK posts."),
    pinterest: bool = typer.Option(True, "--pinterest/--no-pinterest", help="Plan and publish Pinterest posts."),
    instagram: bool = typer.Option(False, "--instagram/--no-instagram", help="Plan and publish Instagram posts."),
    vk_browser: bool = typer.Option(False, "--vk-browser", help="Publish real VK posts through browser automation."),
    pinterest_zernio: bool = typer.Option(
        True,
        "--pinterest-zernio/--pinterest-direct-api",
        help="Use Zernio for real Pinterest publishing. Direct API uses Pinterest API settings.",
    ),
    vk_limit: int | None = typer.Option(None, help="Maximum number of VK posts to process."),
    pinterest_limit: int | None = typer.Option(None, help="Maximum number of Pinterest posts to process."),
    instagram_limit: int | None = typer.Option(None, help="Maximum number of Instagram posts to process."),
    board_id: str | None = typer.Option(None, help="Pinterest board ID used for planning."),
    vk_owner_id: str | None = typer.Option(None, help="VK wall owner ID used for planning VK posts."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    user_data_dir: Path | None = typer.Option(
        None,
        help="Persistent WB browser profile directory. Use the same profile as wb-browser-baseline.",
    ),
    browser_engine: str = typer.Option(
        "selenium",
        help="WB browser engine: selenium or playwright. Selenium uses undetected_chromedriver.",
    ),
    output_path: Path | None = typer.Option(None, help="Where to save scanned WB product cards JSON."),
    state_path: Path | None = typer.Option(None, help="Optional WB browser storage state path."),
    browser_channel: str | None = typer.Option("chrome", help="Browser channel for Playwright launch."),
    cdp_url: str | None = typer.Option(None, help="Connect to an already running Chrome via CDP."),
    chrome_binary: Path | None = typer.Option(None, help="Path to chrome.exe for Selenium/undetected_chromedriver."),
    chromedriver_path: Path | None = typer.Option(None, help="Explicit chromedriver path for Selenium."),
    auto_install_driver: bool = typer.Option(
        True,
        "--auto-install-driver/--no-auto-install-driver",
        help="Let chromedriver-autoinstaller install a matching driver when no explicit path is provided.",
    ),
    headless: bool = typer.Option(False, help="Run WB browser headless. Visible mode is recommended for WB checks."),
    manual_ready: bool = typer.Option(
        False,
        "--manual-ready/--no-manual-ready",
        help="Wait for Enter before scanning. Disabled by default.",
    ),
    ready_delay_seconds: float = typer.Option(2.0, help="Delay before scanning when --no-manual-ready is used."),
    max_scrolls: int = typer.Option(80, help="Maximum WB scroll attempts."),
    idle_scrolls: int = typer.Option(8, help="Stop WB scan after this many scrolls without new nmIDs."),
    scroll_delay_ms: int = typer.Option(1400, help="Maximum wait for WB products to load after each scroll."),
    scroll_pixels: int = typer.Option(1800, help="Vertical pixels per WB scroll step."),
    out_dir: Path | None = typer.Option(None, help="Output directory for dry-run payloads and media artifacts."),
) -> None:
    """Run one WB scan, then post new products sequentially to selected social networks."""
    if not vk and not pinterest and not instagram:
        raise typer.BadParameter("At least one platform must be enabled.")
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    store.init_db()
    _ensure_wb_browser_baseline(store)
    if vk and not dry_run:
        _ensure_vk_browser_ready_for_real_publish(settings, browser=vk_browser)

    resolved_output_path = output_path or settings.out_dir / "wb_browser_new_scan_products.json"
    resolved_state_path = state_path or settings.out_dir / "wb_browser_state.json"
    resolved_out_dir = out_dir or settings.out_dir
    planning_board_id = _pinterest_board_id_for_planning(settings, board_id, prefer_zernio=pinterest_zernio)

    typer.echo("Step 1/4: scan WB new products")
    sync_result = _sync_wb_browser_new_products(
        settings=settings,
        store=store,
        seller_url=seller_url,
        browser_engine=browser_engine,
        scan_limit=scan_limit,
        platform="vk" if vk else "pinterest",
        board_id=planning_board_id,
        vk_owner_id=vk_owner_id,
        output_path=resolved_output_path,
        state_path=resolved_state_path,
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        cdp_url=cdp_url,
        chrome_binary=chrome_binary,
        chromedriver_path=chromedriver_path,
        auto_install_driver=auto_install_driver,
        headless=headless,
        manual_ready=manual_ready,
        ready_delay_seconds=ready_delay_seconds,
        max_scrolls=max_scrolls,
        idle_scrolls=idle_scrolls,
        scroll_delay_ms=scroll_delay_ms,
        scroll_pixels=scroll_pixels,
        plan=False,
    )
    _print_wb_browser_sync_result(sync_result)

    typer.echo("\nStep 2/4: plan social posts")
    plan_results: dict[str, dict[str, int]] = {}
    if vk:
        try:
            plan_results["vk"] = _plan_platform_posts(
                store,
                settings,
                platform="vk",
                vk_owner_id=vk_owner_id,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo("VK:")
        _print_plan_result(plan_results["vk"])
    if pinterest:
        try:
            plan_results["pinterest"] = _plan_platform_posts(
                store,
                settings,
                platform="pinterest",
                board_id=planning_board_id,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo("Pinterest:")
        _print_plan_result(plan_results["pinterest"])
    if instagram:
        try:
            plan_results["instagram"] = _plan_platform_posts(
                store,
                settings,
                platform="instagram",
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo("Instagram:")
        _print_plan_result(plan_results["instagram"])

    typer.echo("\nStep 3/4: publish social posts")
    publish_results: dict[str, dict[str, int]] = {}
    if vk:
        typer.echo("VK dry-run" if dry_run else "VK real browser")
        publish_results["vk"] = _publish_platform_after_scan(
            store=store,
            settings=settings,
            platform="vk",
            dry_run=dry_run,
            out_dir=resolved_out_dir,
            limit=vk_limit,
            vk_owner_id=vk_owner_id,
            browser=False if dry_run else vk_browser,
        )
    if pinterest:
        if dry_run:
            typer.echo("Pinterest dry-run")
        elif pinterest_zernio:
            typer.echo("Pinterest real Zernio")
        else:
            typer.echo("Pinterest real direct API")
        publish_results["pinterest"] = _publish_platform_after_scan(
            store=store,
            settings=settings,
            platform="pinterest",
            dry_run=dry_run,
            out_dir=resolved_out_dir,
            limit=pinterest_limit,
            board_id=planning_board_id,
            zernio=pinterest_zernio,
        )
    if instagram:
        typer.echo("Instagram dry-run" if dry_run else "Instagram real Zernio")
        publish_results["instagram"] = _publish_platform_after_scan(
            store=store,
            settings=settings,
            platform="instagram",
            dry_run=dry_run,
            out_dir=resolved_out_dir,
            limit=instagram_limit,
            zernio=True,
        )

    typer.echo("\nStep 4/4: status")
    _print_wb_social_cycle_summary(
        store=store,
        sync_result=sync_result,
        plan_results=plan_results,
        publish_results=publish_results,
    )


def _print_wb_vk_cycle_summary(
    *,
    store: Store,
    sync_result: dict[str, object],
    publish_result: dict[str, int],
) -> None:
    seen_result = sync_result["seen_result"]
    plan_result = sync_result.get("plan_result") or {}
    summary = store.summary()
    typer.echo("WB -> VK cycle summary")
    typer.echo(f"Scanned products: {seen_result['total']}")
    typer.echo(f"New nmIDs found: {seen_result['created']}")
    typer.echo(f"Planned posts created: {plan_result.get('planned', 0)}")
    typer.echo(f"Published / dry-run published: {publish_result['published']}")
    typer.echo(f"Failed: {publish_result['failed']}")
    typer.echo(f"Posts by status: {summary['posts_by_status']}")


def _print_wb_pinterest_cycle_summary(
    *,
    store: Store,
    sync_result: dict[str, object],
    publish_result: dict[str, int],
) -> None:
    seen_result = sync_result["seen_result"]
    plan_result = sync_result.get("plan_result") or {}
    summary = store.summary()
    typer.echo("WB -> Pinterest cycle summary")
    typer.echo(f"Scanned products: {seen_result['total']}")
    typer.echo(f"New nmIDs found: {seen_result['created']}")
    typer.echo(f"Planned posts created: {plan_result.get('planned', 0)}")
    typer.echo(f"Published / dry-run published: {publish_result['published']}")
    typer.echo(f"Failed: {publish_result['failed']}")
    typer.echo(f"Posts by status: {summary['posts_by_status']}")


def _print_wb_instagram_cycle_summary(
    *,
    store: Store,
    sync_result: dict[str, object],
    publish_result: dict[str, int],
) -> None:
    seen_result = sync_result["seen_result"]
    plan_result = sync_result.get("plan_result") or {}
    summary = store.summary()
    typer.echo("WB -> Instagram cycle summary")
    typer.echo(f"Scanned products: {seen_result['total']}")
    typer.echo(f"New nmIDs found: {seen_result['created']}")
    typer.echo(f"Planned posts created: {plan_result.get('planned', 0)}")
    typer.echo(f"Published / dry-run published: {publish_result['published']}")
    typer.echo(f"Failed: {publish_result['failed']}")
    typer.echo(f"Posts by status: {summary['posts_by_status']}")


def _print_wb_social_cycle_summary(
    *,
    store: Store,
    sync_result: dict[str, object],
    plan_results: dict[str, dict[str, int]],
    publish_results: dict[str, dict[str, int]],
) -> None:
    seen_result = sync_result["seen_result"]
    summary = store.summary()
    typer.echo("WB -> social cycle summary")
    typer.echo(f"Scanned products: {seen_result['total']}")
    typer.echo(f"New nmIDs found: {seen_result['created']}")
    for platform in ("vk", "pinterest", "instagram"):
        if platform not in plan_results and platform not in publish_results:
            continue
        plan_result = plan_results.get(platform, {})
        publish_result = publish_results.get(platform, {})
        typer.echo(
            f"{platform}: planned={plan_result.get('planned', 0)} "
            f"published={publish_result.get('published', 0)} "
            f"failed={publish_result.get('failed', 0)}"
        )
    typer.echo(f"Posts by status: {summary['posts_by_status']}")


@app.command()
def sync(
    mode: str | None = typer.Option(None, help="Run mode: test or real-ready."),
    source: str | None = typer.Option(None, help="Manual source override: fake or wb-api."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    fixture_path: Path | None = typer.Option(None, help="Fake WB products JSON path."),
) -> None:
    """Load product cards from a source into SQLite."""
    settings = load_settings()
    resolved_mode, resolved_source = _resolve_source(settings, mode, source)
    store = Store(db_path or settings.db_path)
    store.init_db()
    try:
        result = _sync_products(store, resolved_source, fixture_path or settings.fake_products_path, settings)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Mode: {resolved_mode}")
    typer.echo(f"Source: {resolved_source}")
    typer.echo(
        f"Synced {result['total']} products: "
        f"{result['created']} new, {result['updated']} updated."
    )
    if resolved_source == "wb-public":
        typer.echo(
            f"Public WB scan: discovered {result['discovered_nm_ids']} nmIDs, "
            f"details requested: {result['details_requested']}, "
            f"top window saved: {result['top_window_saved']}."
        )


@app.command()
def baseline_sync(
    mode: str | None = typer.Option(None, help="Run mode: test or real-ready."),
    source: str | None = typer.Option(None, help="Manual source override: fake or wb-api."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    fixture_path: Path | None = typer.Option(None, help="Fake WB products JSON path."),
) -> None:
    """Sync current assortment and mark it as already known without creating posts."""
    settings = load_settings()
    resolved_mode, resolved_source = _resolve_source(settings, mode, source)
    store = Store(db_path or settings.db_path)
    store.init_db()
    if resolved_source == "wb-public":
        product_source = _build_wb_public_source(settings, limit=settings.wb_public_baseline_limit)
        try:
            nm_ids = product_source.fetch_nm_ids()
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if not nm_ids:
            raise typer.BadParameter(
                "WB public baseline found 0 nmIDs. Refusing to mark an empty baseline; "
                "check WB_PUBLIC_QUERY/SUPPLIER_ID/BRAND or retry later."
            )
        seen_result = store.upsert_seen_nm_ids(
            nm_ids,
            source=WBPublicCatalogSource.SOURCE_NAME,
            mark_baseline=True,
        )
        top_window = store.set_source_top_window(
            source=WBPublicCatalogSource.SOURCE_NAME,
            nm_ids=nm_ids,
            window_size=settings.wb_public_top_window_size,
        )
        typer.echo(f"Mode: {resolved_mode}")
        typer.echo(f"Source: {resolved_source}")
        typer.echo(
            f"Discovered {seen_result['total']} public WB nmIDs: "
            f"{seen_result['created']} new, {seen_result['updated']} seen before."
        )
        typer.echo(f"Baseline marked for {seen_result['baseline_marked']} nmIDs.")
        typer.echo(f"Top window saved: {len(top_window)} nmIDs.")
        typer.echo("No product details were fetched and no posts were planned.")
        return

    sync_result = _sync_products(store, resolved_source, fixture_path or settings.fake_products_path, settings)
    baseline_result = store.mark_baseline()
    typer.echo(f"Mode: {resolved_mode}")
    typer.echo(f"Source: {resolved_source}")
    typer.echo(
        f"Synced {sync_result['total']} products: "
        f"{sync_result['created']} new, {sync_result['updated']} updated."
    )
    typer.echo(
        f"Baseline set at {baseline_result['baseline_at']} "
        f"for {baseline_result['products']} known products."
    )
    typer.echo("No posts were planned. Future planning can use --only-after-baseline.")


@app.command()
def plan_posts(
    platform: str = typer.Option("pinterest", help="Target platform: instagram, pinterest, or vk."),
    board_id: str | None = typer.Option(None, help="Pinterest board ID."),
    vk_owner_id: str | None = typer.Option(None, help="VK wall owner ID, e.g. -123456 for a group."),
    only_after_baseline: bool = typer.Option(
        False,
        "--only-after-baseline",
        help="Plan only products first seen after baseline-sync.",
    ),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Create planned social posts for publishable products not posted before."""
    settings = load_settings()
    _validate_platform(platform)

    store = Store(db_path or settings.db_path)
    store.init_db()
    try:
        result = store.plan_posts(
            platform=platform,
            board_id=_pinterest_board_id_for_planning(settings, board_id, prefer_zernio=platform == "pinterest"),
            vk_owner_id=_vk_owner_id_for_planning(settings, vk_owner_id),
            vk_from_group=settings.vk_from_group,
            vk_upload_photo=settings.vk_upload_photo,
            tracking_params=_tracking_params(settings, platform),
            only_after_baseline=only_after_baseline,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print_plan_result(result)


@app.command()
def retry_failed(
    platform: str = typer.Option("pinterest", help="Target platform: instagram, pinterest, or vk."),
    board_id: str | None = typer.Option(None, help="Pinterest board ID."),
    vk_owner_id: str | None = typer.Option(None, help="VK wall owner ID, e.g. -123456 for a group."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Move failed posts back to planned with fresh payloads."""
    settings = load_settings()
    _validate_platform(platform)

    store = Store(db_path or settings.db_path)
    store.init_db()
    result = store.retry_failed_posts(
        platform=platform,
        board_id=_pinterest_board_id_for_planning(settings, board_id, prefer_zernio=platform == "pinterest"),
        vk_owner_id=_vk_owner_id_for_planning(settings, vk_owner_id),
        vk_from_group=settings.vk_from_group,
        vk_upload_photo=settings.vk_upload_photo,
        tracking_params=_tracking_params(settings, platform),
    )
    typer.echo(
        f"Retried {result['retried']} failed posts. "
        f"Skipped ineligible: {result['skipped_ineligible']}. "
        f"Skipped missing products: {result['skipped_missing_product']}."
    )


@app.command()
def recover_publishing(
    action: str = typer.Option("fail", help="Recovery action: fail or retry."),
    platform: str = typer.Option("pinterest", help="Target platform: instagram, pinterest, or vk."),
    board_id: str | None = typer.Option(None, help="Pinterest board ID used when action=retry."),
    vk_owner_id: str | None = typer.Option(None, help="VK wall owner ID used when action=retry."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Recover posts stuck in publishing after an interrupted process."""
    settings = load_settings()
    _validate_platform(platform)
    if action not in {"fail", "retry"}:
        raise typer.BadParameter("action must be 'fail' or 'retry'.")

    store = Store(db_path or settings.db_path)
    store.init_db()
    result = store.recover_publishing_posts(
        platform=platform,
        action=action,
        board_id=_pinterest_board_id_for_planning(settings, board_id, prefer_zernio=platform == "pinterest"),
        vk_owner_id=_vk_owner_id_for_planning(settings, vk_owner_id),
        vk_from_group=settings.vk_from_group,
        vk_upload_photo=settings.vk_upload_photo,
        tracking_params=_tracking_params(settings, platform),
    )
    typer.echo(
        f"Recovered {result['recovered']} publishing posts. "
        f"Skipped ineligible: {result['skipped_ineligible']}. "
        f"Skipped missing products: {result['skipped_missing_product']}."
    )


@app.command()
def publish(
    dry_run: bool = typer.Option(True, help="Write social payloads to out/ instead of calling API."),
    platform: str = typer.Option("pinterest", help="Target platform: instagram, pinterest, or vk."),
    browser: bool = typer.Option(False, "--browser", help="Publish VK posts through a logged-in browser session."),
    zernio: bool = typer.Option(False, "--zernio", help="Publish Pinterest/Instagram posts through Zernio."),
    limit: int | None = typer.Option(None, help="Maximum number of planned posts to process."),
    retry_failed: bool = typer.Option(
        True,
        "--retry-failed/--no-retry-failed",
        help="Move publishable failed posts back to planned before publishing.",
    ),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    out_dir: Path | None = typer.Option(None, help="Output directory for dry-run payloads."),
) -> None:
    """Publish planned posts or simulate publishing in dry-run mode."""
    settings = load_settings()
    _validate_platform(platform)

    store = Store(db_path or settings.db_path)
    store.init_db()
    if retry_failed:
        retry_result = _retry_failed_for_publish(store, settings, platform=platform)
        if retry_result["retried"] or retry_result["skipped_ineligible"] or retry_result["skipped_missing_product"]:
            typer.echo(
                f"Auto-retried {retry_result['retried']} failed posts. "
                f"Skipped ineligible: {retry_result['skipped_ineligible']}. "
                f"Skipped missing products: {retry_result['skipped_missing_product']}."
            )
    resolved_limit = _publish_limit(settings, platform, limit)
    publisher = _build_social_publisher(
        settings,
        platform,
        dry_run,
        out_dir or settings.out_dir,
        browser=browser,
        zernio=zernio,
    )
    result = _publish_planned_posts(store, publisher, platform, limit=resolved_limit)

    typer.echo(
        f"Processed {result['processed']} planned posts: "
        f"{result['published']} ok, {result['failed']} failed."
    )


@app.command()
def report(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    platform: str | None = typer.Option("pinterest", help="Platform filter: instagram, pinterest, vk, or empty for all."),
) -> None:
    """Print product/post status."""
    settings = load_settings()
    if platform:
        _validate_platform(platform)
    store = Store(db_path or settings.db_path)
    store.init_db()
    _print_report(store, platform)


@app.command()
def status(
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Print product/post status for all platforms."""
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    store.init_db()
    _print_report(store, platform=None)


@app.command()
def sync_metrics(
    platform: str = typer.Option("all", help="Platform filter: all, pinterest, or instagram."),
    from_date: str | None = typer.Option(None, help="Analytics start date YYYY-MM-DD. Defaults to Zernio API default."),
    to_date: str | None = typer.Option(None, help="Analytics end date YYYY-MM-DD. Defaults to today in Zernio."),
    limit: int | None = typer.Option(None, help="Maximum number of published posts to sync."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Fetch social metrics from Zernio for published Pinterest/Instagram posts."""
    if limit is not None and limit < 1:
        raise typer.BadParameter("limit must be greater than zero.")
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    store.init_db()
    result = _sync_zernio_metrics(
        store=store,
        settings=settings,
        platform=platform,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    typer.echo(
        f"Metrics sync complete: processed={result['processed']} synced={result['synced']} "
        f"pending={result['pending']} failed={result['failed']} skipped={result['skipped']}."
    )


@app.command()
def metrics_report(
    platform: str = typer.Option("all", help="Platform filter: all, pinterest, or instagram."),
    limit: int | None = typer.Option(20, help="Maximum number of latest post metric rows to show."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Print latest saved social metrics."""
    if limit is not None and limit < 1:
        raise typer.BadParameter("limit must be greater than zero.")
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    store.init_db()
    _print_metrics_report(store, platform=platform, limit=limit)


@app.command()
def export_dashboard(
    output: Path = typer.Option(Path("out/dashboard.html"), help="Where to write the static HTML dashboard."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
) -> None:
    """Export a static local HTML dashboard for the current database state."""
    settings = load_settings()
    store = Store(db_path or settings.db_path)
    path = export_dashboard_html(store, output)
    typer.echo(f"Dashboard exported: {path}")


@app.command()
def mvp_demo(
    platform: str = typer.Option("vk", help="Target platform for safe dry-run: vk or pinterest."),
    mode: str | None = typer.Option("test", help="Run mode: test or real-ready."),
    source: str | None = typer.Option(None, help="Manual source override: fake or wb-api."),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    fixture_path: Path | None = typer.Option(None, help="Fake WB products JSON path."),
    out_dir: Path | None = typer.Option(None, help="Output directory for dry-run payloads."),
) -> None:
    """Run a safe end-to-end MVP demo without real social publishing."""
    settings = load_settings()
    _validate_platform(platform)
    resolved_mode, resolved_source = _resolve_source(settings, mode, source)
    _run_pipeline(
        settings=settings,
        mode=resolved_mode,
        source=resolved_source,
        platform=platform,
        dry_run=True,
        browser=False,
        db_path=db_path,
        fixture_path=fixture_path,
        out_dir=out_dir,
    )


@app.command()
def vk_real_cycle(
    mode: str | None = typer.Option("test", help="Run mode: test or real-ready."),
    source: str | None = typer.Option(None, help="Manual source override: fake or wb-api."),
    limit: int | None = typer.Option(None, help="Maximum number of VK posts to publish."),
    include_current: bool = typer.Option(
        False,
        "--include-current",
        help="In real-ready mode, allow planning current assortment instead of only products after baseline.",
    ),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    fixture_path: Path | None = typer.Option(None, help="Fake WB products JSON path."),
    out_dir: Path | None = typer.Option(None, help="Output directory for downloaded media/debug artifacts."),
) -> None:
    """Run sync, plan, real VK browser publish, and VK report."""
    settings = load_settings()
    resolved_mode, resolved_source = _resolve_source(settings, mode, source)
    _run_pipeline(
        settings=settings,
        mode=resolved_mode,
        source=resolved_source,
        platform="vk",
        dry_run=False,
        browser=True,
        limit=limit,
        only_after_baseline=resolved_mode == "real-ready" and not include_current,
        db_path=db_path,
        fixture_path=fixture_path,
        out_dir=out_dir,
    )


@app.command()
def run_cycle(
    mode: str | None = typer.Option(None, help="Run mode: test or real-ready."),
    source: str | None = typer.Option(None, help="Manual source override: fake or wb-api."),
    platform: str = typer.Option("pinterest", help="Target platform: instagram, pinterest, or vk."),
    board_id: str | None = typer.Option(None, help="Pinterest board ID."),
    vk_owner_id: str | None = typer.Option(None, help="VK wall owner ID, e.g. -123456 for a group."),
    include_current: bool = typer.Option(
        False,
        "--include-current",
        help="In real-ready mode, allow planning current assortment instead of only products after baseline.",
    ),
    db_path: Path | None = typer.Option(None, help="SQLite database path."),
    fixture_path: Path | None = typer.Option(None, help="Fake WB products JSON path."),
    out_dir: Path | None = typer.Option(None, help="Output directory for dry-run payloads."),
) -> None:
    """Run the whole local MVP cycle: sync, plan, dry-run publish, report."""
    settings = load_settings()
    _validate_platform(platform)
    resolved_mode, resolved_source = _resolve_source(settings, mode, source)
    _run_pipeline(
        settings=settings,
        mode=resolved_mode,
        source=resolved_source,
        platform=platform,
        dry_run=True,
        browser=False,
        only_after_baseline=resolved_mode == "real-ready" and not include_current,
        db_path=db_path,
        fixture_path=fixture_path,
        out_dir=out_dir,
        board_id=board_id,
        vk_owner_id=vk_owner_id,
    )


def _run_pipeline(
    *,
    settings: Settings,
    mode: str,
    source: str,
    platform: str,
    dry_run: bool,
    browser: bool,
    limit: int | None = None,
    only_after_baseline: bool = False,
    db_path: Path | None = None,
    fixture_path: Path | None = None,
    out_dir: Path | None = None,
    board_id: str | None = None,
    vk_owner_id: str | None = None,
) -> None:
    _validate_platform(platform)
    store = Store(db_path or settings.db_path)
    store.init_db()

    publish_label = "publish --dry-run" if dry_run else "publish --real"
    typer.echo(f"Mode: {mode}")
    typer.echo(f"Source: {source}")
    typer.echo(f"Platform: {platform}")
    typer.echo("Step 1/4: sync")
    sync_result = _sync_products(
        store,
        source,
        fixture_path or settings.fake_products_path,
        settings,
    )
    typer.echo(
        f"Synced {sync_result['total']} products: "
        f"{sync_result['created']} new, {sync_result['updated']} updated."
    )

    typer.echo("\nStep 2/4: plan-posts")
    try:
        plan_result = store.plan_posts(
            platform=platform,
            board_id=_pinterest_board_id_for_planning(settings, board_id, prefer_zernio=platform == "pinterest"),
            vk_owner_id=_vk_owner_id_for_planning(settings, vk_owner_id),
            vk_from_group=settings.vk_from_group,
            vk_upload_photo=settings.vk_upload_photo,
            tracking_params=_tracking_params(settings, platform),
            only_after_baseline=only_after_baseline,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print_plan_result(plan_result)

    typer.echo(f"\nStep 3/4: {publish_label}")
    publish_result = _publish_planned_posts(
        store,
        _build_social_publisher(settings, platform, dry_run=dry_run, out_dir=out_dir or settings.out_dir, browser=browser),
        platform,
        limit=_publish_limit(settings, platform, limit),
    )
    typer.echo(
        f"Processed {publish_result['processed']} planned posts: "
        f"{publish_result['published']} ok, {publish_result['failed']} failed."
    )

    typer.echo("\nStep 4/4: report")
    _print_report(store, platform)


if __name__ == "__main__":
    app()
