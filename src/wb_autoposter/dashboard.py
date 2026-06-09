from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from wb_autoposter.models import PlannedPost, PostStatus, SocialPostMetrics
from wb_autoposter.storage import Store

TRACKED_STATUSES = (
    PostStatus.PLANNED,
    PostStatus.PUBLISHED,
    PostStatus.FAILED,
    PostStatus.DRY_RUN_PUBLISHED,
)
TRACKED_PLATFORMS = ("vk", "pinterest", "instagram")
METRIC_FIELDS = ("impressions", "clicks", "saves", "likes", "comments", "reach", "views")


def export_dashboard(store: Store, output_path: Path) -> Path:
    """Write a static dashboard HTML file for the current local database state."""

    store.init_db()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary = store.summary()
    posts = store.list_posts()
    latest_metrics = {metrics.post_id: metrics for metrics in store.latest_post_metrics()}
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    output_path.write_text(
        _render_dashboard(
            summary=summary,
            posts=posts,
            latest_metrics=latest_metrics,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )
    return output_path


def _render_dashboard(
    *,
    summary: dict[str, Any],
    posts: list[PlannedPost],
    latest_metrics: dict[int, SocialPostMetrics],
    generated_at: str,
) -> str:
    by_status = Counter(post.status.value for post in posts)
    failed_posts = [post for post in posts if post.status == PostStatus.FAILED]
    last_posts = sorted(posts, key=_post_sort_key, reverse=True)[:50]
    latest_metrics_rows = sorted(
        [item for item in latest_metrics.values() if item.platform in {"pinterest", "instagram"}],
        key=lambda item: item.captured_at,
        reverse=True,
    )[:30]

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WB Autoposter Dashboard</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #1f2933; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; }}
    .muted {{ color: #657282; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
    .card {{ background: white; border: 1px solid #dfe4ea; border-radius: 8px; padding: 14px; }}
    .metric {{ font-size: 26px; font-weight: 700; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #dfe4ea; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf0f3; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #eef2f6; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    .status {{ display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .planned {{ background: #fff4cc; color: #7a5300; }}
    .published {{ background: #dff7e8; color: #146c37; }}
    .dry_run_published {{ background: #e6f0ff; color: #1c4f9c; }}
    .failed {{ background: #fde2e1; color: #9b1c1c; }}
    .empty {{ background: white; border: 1px dashed #b8c2cc; border-radius: 8px; padding: 18px; color: #657282; }}
    .error {{ max-width: 360px; white-space: pre-wrap; }}
  </style>
</head>
<body>
<main>
  <h1>WB Autoposter Dashboard</h1>
  <div class="muted">Generated at {escape(generated_at)}. Last sync: {escape(str(summary.get("last_sync_at") or "never"))}. Baseline: {escape(str(summary.get("baseline_at") or "not set"))}.</div>

  <h2>Summary</h2>
  <section class="grid">
    {_summary_card("Products", summary.get("products_total", 0))}
    {_summary_card("Posts", summary.get("posts_total", 0))}
    {_summary_card("Planned", by_status[PostStatus.PLANNED.value])}
    {_summary_card("Published", by_status[PostStatus.PUBLISHED.value])}
    {_summary_card("Dry-run published", by_status[PostStatus.DRY_RUN_PUBLISHED.value])}
    {_summary_card("Failed", by_status[PostStatus.FAILED.value])}
    {_summary_card("Last updated", generated_at)}
  </section>

  <h2>Posts by Platform</h2>
  {_render_platform_table(posts)}

  <h2>Last Posts</h2>
  {_render_posts_table(last_posts, latest_metrics, empty_message="No posts saved yet.")}

  <h2>Failed Posts</h2>
  {_render_failed_table(failed_posts)}

  <h2>Metrics</h2>
  {_render_metrics_block(latest_metrics_rows)}
</main>
</body>
</html>
"""


def _summary_card(label: str, value: object) -> str:
    return f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{escape(str(value))}</div></div>'


def _render_platform_table(posts: list[PlannedPost]) -> str:
    rows = []
    for platform in TRACKED_PLATFORMS:
        platform_posts = [post for post in posts if post.platform == platform]
        counts = Counter(post.status for post in platform_posts)
        rows.append(
            "<tr>"
            f"<td>{escape(platform)}</td>"
            f"<td>{counts[PostStatus.PLANNED]}</td>"
            f"<td>{counts[PostStatus.PUBLISHED]}</td>"
            f"<td>{counts[PostStatus.FAILED]}</td>"
            f"<td>{counts[PostStatus.DRY_RUN_PUBLISHED]}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Platform</th><th>Planned</th><th>Published</th><th>Failed</th>"
        "<th>Dry-run published</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_posts_table(
    posts: list[PlannedPost],
    latest_metrics: dict[int, SocialPostMetrics],
    *,
    empty_message: str,
) -> str:
    if not posts:
        return f'<div class="empty">{escape(empty_message)}</div>'
    rows = []
    for post in posts:
        metrics = latest_metrics.get(post.id)
        rows.append(
            "<tr>"
            f"<td>{escape(post.platform)}</td>"
            f"<td>{post.product_nm_id}</td>"
            f"<td>{escape(_post_title(post))}</td>"
            f"<td>{_status_badge(post.status)}</td>"
            f"<td>{escape(post.external_id or '-')}</td>"
            f"<td>{escape(_post_time(post))}</td>"
            f"<td class=\"error\">{escape(post.error or '')}</td>"
            f"<td>{escape(_metrics_summary(metrics))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Platform</th><th>nmID</th><th>Product title</th><th>Status</th>"
        "<th>External ID</th><th>Published/updated at</th><th>Error</th><th>Metrics</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_failed_table(posts: list[PlannedPost]) -> str:
    if not posts:
        return '<div class="empty">No failed posts.</div>'
    rows = []
    for post in sorted(posts, key=_post_sort_key, reverse=True):
        rows.append(
            "<tr>"
            f"<td>{escape(post.platform)}</td>"
            f"<td>{post.product_nm_id}</td>"
            f"<td>{escape(_post_title(post))}</td>"
            f"<td class=\"error\">{escape(post.error or '')}</td>"
            f"<td>{escape(_post_time(post))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Platform</th><th>nmID</th><th>Product title</th>"
        "<th>Error message</th><th>Updated at</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_metrics_block(metrics: list[SocialPostMetrics]) -> str:
    if not metrics:
        return '<div class="empty">No metrics synced yet. Run sync-metrics first.</div>'
    rows = []
    for item in metrics:
        rows.append(
            "<tr>"
            f"<td>{escape(item.platform)}</td>"
            f"<td>{item.product_nm_id}</td>"
            f"<td>{escape(item.external_id or '-')}</td>"
            f"<td>{escape(item.captured_at.isoformat())}</td>"
            f"<td>{item.impressions or 0}</td>"
            f"<td>{item.clicks or 0}</td>"
            f"<td>{item.saves or 0}</td>"
            f"<td>{item.likes or 0}</td>"
            f"<td>{item.comments or 0}</td>"
            f"<td>{item.reach or 0}</td>"
            f"<td>{item.views or 0}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Platform</th><th>nmID</th><th>External ID</th><th>Captured at</th>"
        "<th>Impressions</th><th>Clicks</th><th>Saves</th><th>Likes</th><th>Comments</th>"
        "<th>Reach</th><th>Views</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _post_title(post: PlannedPost) -> str:
    snapshot = post.payload.get("content_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("title"), str):
        return snapshot["title"]
    generated = post.payload.get("generated_content")
    if isinstance(generated, dict) and isinstance(generated.get("title"), str):
        return generated["title"]
    return "-"


def _post_time(post: PlannedPost) -> str:
    value = post.published_at or post.created_at
    return value.isoformat() if value else "-"


def _post_sort_key(post: PlannedPost) -> datetime:
    return post.published_at or post.created_at


def _status_badge(status: PostStatus) -> str:
    value = status.value
    return f'<span class="status {escape(value)}">{escape(value)}</span>'


def _metrics_summary(metrics: SocialPostMetrics | None) -> str:
    if metrics is None:
        return "-"
    parts = []
    for field in METRIC_FIELDS:
        value = getattr(metrics, field)
        if value is not None:
            parts.append(f"{field}={value}")
    return " ".join(parts) if parts else "-"
