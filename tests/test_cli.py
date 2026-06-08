from __future__ import annotations

from pathlib import Path
from time import sleep

from typer.testing import CliRunner

import wb_autoposter.cli as cli_module
from wb_autoposter.adapters.fake_wb import FakeWBSource
from wb_autoposter.cli import app
from wb_autoposter.models import PostStatus, PublishResult
from wb_autoposter.storage import Store

from helpers import make_product


def test_run_cycle_cli_executes_full_dry_run(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PINTEREST_POST_LIMIT_PER_RUN", "")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run-cycle",
            "--mode",
            "test",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--fixture-path",
            str(fixture_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Step 1/4: sync" in result.output
    assert "Step 4/4: report" in result.output
    assert "Planned 4 posts." in result.output
    assert "Processed 4 planned posts: 4 ok, 0 failed." in result.output
    assert len(list((tmp_path / "out").glob("pinterest_pin_*.json"))) == 4


def test_run_cycle_cli_repeat_does_not_duplicate_posts(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PINTEREST_POST_LIMIT_PER_RUN", "")
    runner = CliRunner()
    args = [
        "run-cycle",
        "--mode",
        "test",
        "--db-path",
        str(tmp_path / "app.sqlite3"),
        "--fixture-path",
        str(fixture_path),
        "--out-dir",
        str(tmp_path / "out"),
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Planned 0 posts. Skipped existing: 4. Skipped ineligible: 3." in second.output
    assert "Processed 0 planned posts: 0 ok, 0 failed." in second.output
    assert len(list((tmp_path / "out").glob("pinterest_pin_*.json"))) == 4


def test_run_cycle_cli_can_publish_vk_dry_run(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VK_POST_LIMIT_PER_RUN", "")
    result = CliRunner().invoke(
        app,
        [
            "run-cycle",
            "--mode",
            "test",
            "--platform",
            "vk",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--fixture-path",
            str(fixture_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Platform: vk" in result.output
    assert "Planned 4 posts." in result.output
    assert "Processed 4 planned posts: 4 ok, 0 failed." in result.output
    assert len(list((tmp_path / "out").glob("vk_wall_post_*.json"))) == 4


def test_mvp_demo_cli_runs_safe_vk_dry_run(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VK_POST_LIMIT_PER_RUN", "")

    result = CliRunner().invoke(
        app,
        [
            "mvp-demo",
            "--platform",
            "vk",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--fixture-path",
            str(fixture_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Step 3/4: publish --dry-run" in result.output
    assert "Processed 4 planned posts: 4 ok, 0 failed." in result.output
    assert len(list((tmp_path / "out").glob("vk_wall_post_*.json"))) == 4


def test_status_cli_reports_all_platforms(tmp_path: Path, fixture_path: Path) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="vk", vk_owner_id="-100")
    store.plan_posts(platform="pinterest", board_id="demo-board")

    result = CliRunner().invoke(app, ["status", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "Posts total: 2" in result.output
    assert "Social posts:" in result.output


def test_publish_cli_with_no_planned_posts_is_noop(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "publish",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Processed 0 planned posts: 0 ok, 0 failed." in result.output
    assert not (tmp_path / "out").exists()


def test_publish_cli_limit_processes_only_requested_number(tmp_path: Path, fixture_path: Path) -> None:
    db_path = tmp_path / "app.sqlite3"
    out_dir = tmp_path / "out"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products(products)
    store.plan_posts(platform="vk", vk_owner_id="-100")

    result = CliRunner().invoke(
        app,
        [
            "publish",
            "--platform",
            "vk",
            "--limit",
            "1",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert len(store.list_posts(platform="vk", status=PostStatus.PLANNED)) == 3
    assert len(list(out_dir.glob("vk_wall_post_*.json"))) == 1


def test_publish_cli_uses_platform_limit_from_env(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VK_POST_LIMIT_PER_RUN", "2")
    db_path = tmp_path / "app.sqlite3"
    out_dir = tmp_path / "out"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products(products)
    store.plan_posts(platform="vk", vk_owner_id="-100")

    result = CliRunner().invoke(
        app,
        [
            "publish",
            "--platform",
            "vk",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Processed 2 planned posts: 2 ok, 0 failed." in result.output
    assert len(store.list_posts(platform="vk", status=PostStatus.PLANNED)) == 2


def test_publish_cli_explicit_limit_overrides_env_limit(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VK_POST_LIMIT_PER_RUN", "2")
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products(products)
    store.plan_posts(platform="vk", vk_owner_id="-100")

    result = CliRunner().invoke(
        app,
        [
            "publish",
            "--platform",
            "vk",
            "--limit",
            "1",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert len(store.list_posts(platform="vk", status=PostStatus.PLANNED)) == 3


def test_publish_cli_blocks_unknown_platform(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["publish", "--platform", "telegram", "--db-path", str(tmp_path / "app.sqlite3")])

    assert result.exit_code != 0
    assert "platform must be 'pinterest' or 'vk'" in result.output


def test_plan_posts_cli_blocks_unknown_platform(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["plan-posts", "--platform", "telegram", "--db-path", str(tmp_path / "app.sqlite3")])

    assert result.exit_code != 0
    assert "platform must be 'pinterest' or 'vk'" in result.output


def test_non_dry_run_publish_is_blocked_without_mutating_posts(tmp_path: Path, fixture_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products(products)
    store.plan_posts(platform="pinterest", board_id="demo-board")

    assert len(store.list_posts(platform="pinterest", status=PostStatus.PLANNED)) == 4

    result = runner.invoke(app, ["publish", "--no-dry-run", "--db-path", str(db_path)])

    assert result.exit_code != 0
    assert "Real Pinterest publishing is disabled" in result.output
    assert len(store.list_posts(platform="pinterest", status=PostStatus.PLANNED)) == 4
    assert store.list_posts(platform="pinterest", status=PostStatus.FAILED) == []
    assert store.list_posts(platform="pinterest", status=PostStatus.DRY_RUN_PUBLISHED) == []


def test_zernio_publish_is_blocked_without_safety_flag(
    tmp_path: Path,
    fixture_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ZERNIO_API_KEY", "token")
    monkeypatch.setenv("ZERNIO_PINTEREST_ACCOUNT_ID", "acc-1")
    monkeypatch.setenv("ZERNIO_PINTEREST_BOARD_ID", "board-1")
    monkeypatch.setenv("ZERNIO_ENABLE_REAL_PUBLISH", "0")
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_products(FakeWBSource(fixture_path).fetch_products())
    store.plan_posts(platform="pinterest", board_id="demo-board")

    result = CliRunner().invoke(
        app,
        ["publish", "--platform", "pinterest", "--zernio", "--no-dry-run", "--db-path", str(db_path)],
    )

    assert result.exit_code != 0
    assert "Real Zernio publishing is disabled" in result.output
    assert len(store.list_posts(platform="pinterest", status=PostStatus.PLANNED)) == 4


def test_publish_cli_can_use_zernio_pinterest_publisher(
    tmp_path: Path,
    fixture_path: Path,
    monkeypatch,
) -> None:
    class FakeZernioPinterestPublisher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs

        def publish(self, post_id: int, payload: dict[str, object]):
            return PublishResult(status=PostStatus.PUBLISHED, external_id=f"zernio-{post_id}")

    monkeypatch.setattr(cli_module, "ZernioPinterestPublisher", FakeZernioPinterestPublisher)
    monkeypatch.setenv("ZERNIO_API_KEY", "token")
    monkeypatch.setenv("ZERNIO_PINTEREST_ACCOUNT_ID", "acc-1")
    monkeypatch.setenv("ZERNIO_PINTEREST_BOARD_ID", "board-1")
    monkeypatch.setenv("ZERNIO_ENABLE_REAL_PUBLISH", "1")
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_products([FakeWBSource(fixture_path).fetch_products()[0]])
    store.plan_posts(platform="pinterest", board_id="demo-board")

    result = CliRunner().invoke(
        app,
        ["publish", "--platform", "pinterest", "--zernio", "--no-dry-run", "--db-path", str(db_path)],
    )

    assert result.exit_code == 0
    published_posts = store.list_posts(platform="pinterest", status=PostStatus.PUBLISHED)
    assert len(published_posts) == 1
    assert published_posts[0].external_id == "zernio-1"


def test_failed_publish_does_not_leave_post_planned(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    class FailingPublisher:
        def __init__(self, out_dir: Path) -> None:
            self.out_dir = out_dir

        def publish(self, post_id: int, payload: dict[str, object]):
            raise RuntimeError("simulated publisher failure")

    store = Store(tmp_path / "app.sqlite3")
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="pinterest", board_id="demo-board")

    monkeypatch.setattr(cli_module, "PinterestDryRunPublisher", FailingPublisher)
    result = cli_module._publish_planned_posts(store, FailingPublisher(tmp_path / "out"), "pinterest")

    assert result == {"processed": 1, "published": 0, "failed": 1}
    assert store.list_posts(platform="pinterest", status=PostStatus.PLANNED) == []
    failed_posts = store.list_posts(platform="pinterest", status=PostStatus.FAILED)
    assert len(failed_posts) == 1
    assert failed_posts[0].error == "simulated publisher failure"


def test_publish_cli_prints_failed_post_reason(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    class FailingVKPublisher:
        def __init__(self, out_dir: Path) -> None:
            self.out_dir = out_dir

        def publish(self, post_id: int, payload: dict[str, object]):
            raise RuntimeError("Could not find VK post editor.")

    monkeypatch.setattr(cli_module, "VKDryRunPublisher", FailingVKPublisher)
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="vk", vk_owner_id="-100")

    result = CliRunner().invoke(
        app,
        [
            "publish",
            "--platform",
            "vk",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Failed post #1" in result.output
    assert "Could not find VK post editor." in result.output
    assert "vk-browser-login" in result.output
    assert "Processed 1 planned posts: 0 ok, 1 failed." in result.output


def test_retry_failed_cli_restores_failed_posts(tmp_path: Path, fixture_path: Path) -> None:
    runner = CliRunner()
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="pinterest", board_id="demo-board")
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)
    store.update_post_result(post.id, PostStatus.FAILED, None, "temporary failure")

    result = runner.invoke(app, ["retry-failed", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "Retried 1 failed posts." in result.output
    assert len(store.list_posts(platform="pinterest", status=PostStatus.PLANNED)) == 1


def test_publish_cli_auto_retries_failed_posts_before_publishing(
    tmp_path: Path,
    fixture_path: Path,
) -> None:
    db_path = tmp_path / "app.sqlite3"
    out_dir = tmp_path / "out"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="vk", vk_owner_id="-100")
    post = store.list_posts(platform="vk", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)
    store.update_post_result(post.id, PostStatus.FAILED, None, "temporary VK failure")

    result = CliRunner().invoke(
        app,
        [
            "publish",
            "--platform",
            "vk",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(out_dir),
        ],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "Auto-retried 1 failed posts." in result.output
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert len(store.list_posts(platform="vk", status=PostStatus.DRY_RUN_PUBLISHED)) == 1


def test_publish_cli_can_skip_auto_retry_failed(
    tmp_path: Path,
    fixture_path: Path,
) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="vk", vk_owner_id="-100")
    post = store.list_posts(platform="vk", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)
    store.update_post_result(post.id, PostStatus.FAILED, None, "temporary VK failure")

    result = CliRunner().invoke(
        app,
        [
            "publish",
            "--platform",
            "vk",
            "--no-retry-failed",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "Auto-retried" not in result.output
    assert "Processed 0 planned posts: 0 ok, 0 failed." in result.output
    assert len(store.list_posts(platform="vk", status=PostStatus.FAILED)) == 1


def test_recover_publishing_cli_marks_stuck_posts_failed(tmp_path: Path, fixture_path: Path) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="pinterest", board_id="demo-board")
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)

    result = CliRunner().invoke(app, ["recover-publishing", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "Recovered 1 publishing posts." in result.output
    assert len(store.list_posts(platform="pinterest", status=PostStatus.FAILED)) == 1


def test_pinterest_check_validates_local_payloads(tmp_path: Path, fixture_path: Path) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="pinterest", board_id="demo-board")

    result = CliRunner().invoke(app, ["pinterest-check", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "Pinterest payloads checked: 1" in result.output
    assert "Pinterest API board check skipped" in result.output


def test_vk_check_validates_local_payloads(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="vk", vk_owner_id="-100")
    monkeypatch.setenv("VK_OWNER_ID", "-100")

    result = CliRunner().invoke(app, ["vk-check", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "VK payloads checked: 1" in result.output
    assert "VK API wall check skipped" in result.output


def test_vk_auth_url_requires_app_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VK_APP_ID", raising=False)

    result = CliRunner().invoke(app, ["vk-auth-url"])

    assert result.exit_code != 0
    assert "VK_APP_ID is required" in result.output


def test_vk_auth_url_prints_oauth_url(monkeypatch) -> None:
    monkeypatch.setenv("VK_APP_ID", "123")

    result = CliRunner().invoke(app, ["vk-auth-url"])

    assert result.exit_code == 0
    assert "https://oauth.vk.com/authorize?" in result.output
    assert "client_id=123" in result.output


def test_wb_browser_baseline_cli_marks_collected_nm_ids_as_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids = [1003, 1001, 1003, 1002]
        output_path = tmp_path / "nmids.json"
        iterations = 7

    def fake_collect(**kwargs):
        assert kwargs["seller_url"] == "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1"
        assert kwargs["browser_engine"] == "selenium"
        assert kwargs["expected_count"] == 3
        assert kwargs["supplier_id"] == 1335952
        assert kwargs["catalog_dest"] == "-1257786"
        assert kwargs["manual_ready"] is False
        assert kwargs["ready_delay_seconds"] == 2.0
        assert kwargs["output_path"] == tmp_path / "nmids.json"
        return FakeResult()

    monkeypatch.setattr(cli_module, "collect_wb_seller_nm_ids", fake_collect)
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(
        app,
        [
            "wb-browser-baseline",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--expected-count",
            "3",
            "--supplier-id",
            "1335952",
            "--db-path",
            str(db_path),
            "--output-path",
            str(tmp_path / "nmids.json"),
        ],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "Collected 3 WB nmIDs in 7 scroll iterations." in result.output
    assert "Baseline marked for 3 nmIDs." in result.output
    assert store.baseline_at() is not None
    assert store.list_new_seen_nm_ids(source="wb-browser") == []
    assert store.get_source_top_window(source="wb-browser") == [1003, 1001, 1002]


def test_wb_browser_baseline_cli_rejects_empty_collection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids: list[int] = []
        output_path = tmp_path / "nmids.json"
        iterations = 12

    monkeypatch.setattr(cli_module, "collect_wb_seller_nm_ids", lambda **kwargs: FakeResult())
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(
        app,
        [
            "wb-browser-baseline",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code != 0
    assert "found 0 nmIDs" in result.output
    assert Store(db_path).baseline_at() is None


def test_wb_browser_baseline_cli_rejects_expected_count_below_tolerance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids = [1001, 1002, 1003]
        output_path = tmp_path / "nmids.json"
        iterations = 18

    monkeypatch.setattr(cli_module, "collect_wb_seller_nm_ids", lambda **kwargs: FakeResult())
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(
        app,
        [
            "wb-browser-baseline",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--expected-count",
            "1887",
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code != 0
    assert "collected only 3 of expected 1887" in result.output
    assert Store(db_path).baseline_at() is None
    assert Store(db_path).list_new_seen_nm_ids(source="wb-browser") == []


def test_wb_browser_baseline_cli_accepts_expected_count_within_tolerance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids = [1001, 1002, 1003, 1004]
        output_path = tmp_path / "nmids.json"
        iterations = 18

    monkeypatch.setattr(cli_module, "collect_wb_seller_nm_ids", lambda **kwargs: FakeResult())
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(
        app,
        [
            "wb-browser-baseline",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--expected-count",
            "5",
            "--min-expected-ratio",
            "0.8",
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code == 0
    assert "Warning: collected 4 of expected 5 nmIDs" in result.output
    assert Store(db_path).baseline_at() is not None
    assert Store(db_path).list_new_seen_nm_ids(source="wb-browser") == []


def test_wb_browser_sync_new_cli_saves_only_unknown_products_after_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids = [1002, 1001]
        products = [
            make_product(nm_id=1002, title="New browser product", price=1490, stock=1),
            make_product(nm_id=1001, title="Old browser product", price=990, stock=1),
        ]
        output_path = tmp_path / "scan.json"
        iterations = 3

    def fake_collect(**kwargs):
        assert kwargs["scan_limit"] == 100
        assert kwargs["browser_engine"] == "selenium"
        assert kwargs["manual_ready"] is False
        assert kwargs["ready_delay_seconds"] == 2.0
        return FakeResult()

    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", fake_collect)
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001], source="wb-browser", mark_baseline=True)

    result = CliRunner().invoke(
        app,
        [
            "wb-browser-sync-new",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
            "--output-path",
            str(tmp_path / "scan.json"),
        ],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "Scanned 2 newest WB nmIDs in 3 scroll iterations." in result.output
    assert "Known before scan: 1 nmIDs." in result.output
    assert "New nmIDs detected: 1." in result.output
    assert "Synced 1 new product cards: 1 created, 0 updated." in result.output
    assert "Planned 1 posts." in result.output
    assert store.summary()["products_total"] == 1
    assert len(store.list_posts(platform="vk", status=PostStatus.PLANNED)) == 1
    assert store.list_new_seen_nm_ids(source="wb-browser") == [1002]


def test_wb_browser_sync_new_cli_can_skip_planning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids = [1002, 1001]
        products = [
            make_product(nm_id=1002, title="New browser product", price=1490, stock=1),
            make_product(nm_id=1001, title="Old browser product", price=990, stock=1),
        ]
        output_path = tmp_path / "scan.json"
        iterations = 3

    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: FakeResult())
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001], source="wb-browser", mark_baseline=True)

    result = CliRunner().invoke(
        app,
        [
            "wb-browser-sync-new",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--no-plan",
            "--db-path",
            str(db_path),
        ],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "No posts were planned because --no-plan was used." in result.output
    assert store.summary()["products_total"] == 1
    assert store.list_posts(platform="vk") == []


def test_wb_browser_sync_new_cli_requires_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: None)

    result = CliRunner().invoke(
        app,
        [
            "wb-browser-sync-new",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
        ],
    )

    assert result.exit_code != 0
    assert "baseline is missing" in result.output


def test_wb_vk_cycle_requires_baseline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: None)

    result = CliRunner().invoke(
        app,
        [
            "wb-vk-cycle",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
        ],
    )

    assert result.exit_code != 0
    assert "Baseline not found. Run wb-browser-baseline first." in result.output


def test_wb_vk_cycle_no_new_products_is_successful_noop(tmp_path: Path, monkeypatch) -> None:
    class FakeResult:
        nm_ids = [1001, 1002]
        products = [
            make_product(nm_id=1001, title="Known 1", price=1490, stock=1),
            make_product(nm_id=1002, title="Known 2", price=2490, stock=1),
        ]
        output_path = tmp_path / "scan.json"
        iterations = 2

    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: FakeResult())
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001, 1002], source="wb-browser", mark_baseline=True)

    result = CliRunner().invoke(
        app,
        [
            "wb-vk-cycle",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code == 0
    assert "No new products found. Nothing to publish." in result.output
    assert "New nmIDs found: 0" in result.output
    assert Store(db_path).list_posts(platform="vk") == []


def test_wb_vk_cycle_dry_run_plans_and_publishes_new_products(tmp_path: Path, monkeypatch) -> None:
    class FakeResult:
        nm_ids = [1002, 1001]
        products = [
            make_product(nm_id=1002, title="New browser product", price=1490, stock=1),
            make_product(nm_id=1001, title="Old browser product", price=990, stock=1),
        ]
        output_path = tmp_path / "scan.json"
        iterations = 3

    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: FakeResult())
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001], source="wb-browser", mark_baseline=True)

    result = CliRunner().invoke(
        app,
        [
            "wb-vk-cycle",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(tmp_path / "out"),
            "--dry-run",
        ],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "Planned 1 posts." in result.output
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert len(store.list_posts(platform="vk", status=PostStatus.DRY_RUN_PUBLISHED)) == 1
    assert len(list((tmp_path / "out").glob("vk_wall_post_*.json"))) == 1


def test_wb_pinterest_cycle_dry_run_plans_and_publishes_new_products(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids = [1002, 1001]
        products = [
            make_product(
                nm_id=1002,
                title="Шапка женская вязаная",
                description="Теплая шапка с отворотом для прохладной погоды.",
                price=1490,
                stock=1,
            ),
            make_product(nm_id=1001, title="Old browser product", price=990, stock=1),
        ]
        output_path = tmp_path / "scan.json"
        iterations = 3

    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: FakeResult())
    monkeypatch.setenv("ZERNIO_PINTEREST_BOARD_ID", "zernio-board-1")
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001], source="wb-browser", mark_baseline=True)

    result = CliRunner().invoke(
        app,
        [
            "wb-pinterest-cycle",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(tmp_path / "out"),
            "--dry-run",
        ],
    )

    store = Store(db_path)
    posts = store.list_posts(platform="pinterest", status=PostStatus.DRY_RUN_PUBLISHED)
    assert result.exit_code == 0
    assert "Step 2/3: publish Pinterest dry-run" in result.output
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert len(posts) == 1
    assert posts[0].payload["pinterest"]["board_id"] == "zernio-board-1"
    assert "Теплая шапка" in posts[0].payload["pinterest"]["description"]
    assert len(list((tmp_path / "out").glob("pinterest_pin_*.json"))) == 1


def test_wb_pinterest_cycle_real_publish_can_use_zernio(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeResult:
        nm_ids = [1002, 1001]
        products = [
            make_product(
                nm_id=1002,
                title="Шапка женская вязаная",
                description="Теплая шапка с отворотом для прохладной погоды.",
                price=1490,
                stock=1,
            ),
            make_product(nm_id=1001, title="Old browser product", price=990, stock=1),
        ]
        output_path = tmp_path / "scan.json"
        iterations = 3

    class FakeZernioPinterestPublisher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs

        def publish(self, post_id: int, payload: dict[str, object]):
            return PublishResult(status=PostStatus.PUBLISHED, external_id=f"zernio-{post_id}")

    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: FakeResult())
    monkeypatch.setattr(cli_module, "ZernioPinterestPublisher", FakeZernioPinterestPublisher)
    monkeypatch.setenv("ZERNIO_API_KEY", "token")
    monkeypatch.setenv("ZERNIO_ENABLE_REAL_PUBLISH", "1")
    monkeypatch.setenv("ZERNIO_PINTEREST_ACCOUNT_ID", "acc-1")
    monkeypatch.setenv("ZERNIO_PINTEREST_BOARD_ID", "zernio-board-1")
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001], source="wb-browser", mark_baseline=True)

    result = CliRunner().invoke(
        app,
        [
            "wb-pinterest-cycle",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
            "--no-dry-run",
            "--limit",
            "1",
        ],
    )

    posts = Store(db_path).list_posts(platform="pinterest", status=PostStatus.PUBLISHED)
    assert result.exit_code == 0
    assert "Step 2/3: publish Pinterest real Zernio" in result.output
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert len(posts) == 1
    assert posts[0].external_id == "zernio-1"


def test_wb_vk_cycle_real_publish_requires_browser(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001], source="wb-browser", mark_baseline=True)
    monkeypatch.setattr(cli_module, "collect_wb_seller_product_cards", lambda **kwargs: None)

    result = CliRunner().invoke(
        app,
        [
            "wb-vk-cycle",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
            "--no-dry-run",
        ],
    )

    assert result.exit_code != 0
    assert "Real VK publish in this MVP requires --browser." in result.output


def test_wb_vk_cycle_real_browser_requires_saved_session(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_seen_nm_ids([1001], source="wb-browser", mark_baseline=True)
    monkeypatch.setenv("VK_BROWSER_ENABLE", "1")
    monkeypatch.setenv("VK_OWNER_ID", "-100")
    monkeypatch.setenv("VK_BROWSER_STATE_PATH", str(tmp_path / "missing_vk_state.json"))

    result = CliRunner().invoke(
        app,
        [
            "wb-vk-cycle",
            "--seller-url",
            "https://www.wildberries.ru/seller/trendsetter?sort=newly&page=1",
            "--db-path",
            str(db_path),
            "--browser",
            "--no-dry-run",
        ],
    )

    assert result.exit_code != 0
    assert "VK browser session not found. Run vk-browser-login first." in result.output


def test_publish_cli_can_use_real_pinterest_publisher_when_explicitly_enabled(
    tmp_path: Path,
    fixture_path: Path,
    monkeypatch,
) -> None:
    class FakePinterestApiPublisher:
        def __init__(self, access_token: str) -> None:
            self.access_token = access_token

        def publish(self, post_id: int, payload: dict[str, object]):
            from wb_autoposter.models import PublishResult

            return PublishResult(status=PostStatus.PUBLISHED, external_id=f"pin-{post_id}")

    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="pinterest", board_id="demo-board")
    monkeypatch.setattr(cli_module, "PinterestApiPublisher", FakePinterestApiPublisher)
    monkeypatch.setenv("PINTEREST_ENABLE_REAL_PUBLISH", "1")
    monkeypatch.setenv("PINTEREST_ACCESS_TOKEN", "token")

    result = CliRunner().invoke(app, ["publish", "--no-dry-run", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert store.list_posts(platform="pinterest", status=PostStatus.PUBLISHED)[0].external_id == "pin-1"


def test_publish_cli_blocks_vk_browser_when_not_enabled(tmp_path: Path, fixture_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VK_OWNER_ID", "-100")
    monkeypatch.delenv("VK_BROWSER_ENABLE", raising=False)
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="vk", vk_owner_id="-100")

    result = CliRunner().invoke(app, ["publish", "--platform", "vk", "--browser", "--no-dry-run", "--db-path", str(db_path)])

    assert result.exit_code != 0
    assert "VK browser publishing is disabled" in result.output
    assert len(store.list_posts(platform="vk", status=PostStatus.PLANNED)) == 1


def test_publish_cli_can_use_vk_browser_publisher_when_enabled(
    tmp_path: Path,
    fixture_path: Path,
    monkeypatch,
) -> None:
    class FakeVKBrowserPublisher:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def publish(self, post_id: int, payload: dict[str, object]):
            from wb_autoposter.models import PublishResult

            return PublishResult(status=PostStatus.PUBLISHED, external_id=f"vk-browser-{post_id}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "VKBrowserPublisher", FakeVKBrowserPublisher)
    monkeypatch.setenv("VK_BROWSER_ENABLE", "1")
    monkeypatch.setenv("VK_OWNER_ID", "-100")
    monkeypatch.setenv("VK_BROWSER_GROUP_URL", "https://vk.com/club100")
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products([products[0]])
    store.plan_posts(platform="vk", vk_owner_id="-100")

    result = CliRunner().invoke(
        app,
        ["publish", "--platform", "vk", "--browser", "--no-dry-run", "--db-path", str(db_path), "--limit", "1"],
    )

    assert result.exit_code == 0
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert store.list_posts(platform="vk", status=PostStatus.PUBLISHED)[0].external_id == "vk-browser-1"


def test_publish_cli_reuses_vk_browser_publisher_for_batch(
    tmp_path: Path,
    fixture_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, int]] = []

    class FakeVKBrowserPublisher:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def open(self) -> None:
            calls.append(("open", 0))

        def close(self) -> None:
            calls.append(("close", 0))

        def publish(self, post_id: int, payload: dict[str, object]):
            from wb_autoposter.models import PublishResult

            calls.append(("publish", post_id))
            return PublishResult(status=PostStatus.PUBLISHED, external_id=f"vk-browser-{post_id}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "VKBrowserPublisher", FakeVKBrowserPublisher)
    monkeypatch.setenv("VK_BROWSER_ENABLE", "1")
    monkeypatch.setenv("VK_OWNER_ID", "-100")
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    products = FakeWBSource(fixture_path).fetch_products()
    store.upsert_products(products[:2])
    store.plan_posts(platform="vk", vk_owner_id="-100")

    result = CliRunner().invoke(
        app,
        ["publish", "--platform", "vk", "--browser", "--no-dry-run", "--db-path", str(db_path), "--limit", "2"],
    )

    assert result.exit_code == 0
    assert "Processed 2 planned posts: 2 ok, 0 failed." in result.output
    assert calls == [("open", 0), ("publish", 1), ("publish", 2), ("close", 0)]


def test_vk_real_cycle_cli_runs_real_browser_pipeline_with_fake_publisher(
    tmp_path: Path,
    fixture_path: Path,
    monkeypatch,
) -> None:
    class FakeVKBrowserPublisher:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def publish(self, post_id: int, payload: dict[str, object]):
            from wb_autoposter.models import PublishResult

            return PublishResult(status=PostStatus.PUBLISHED, external_id=f"vk-real-{post_id}")

    monkeypatch.setenv("VK_BROWSER_ENABLE", "1")
    monkeypatch.setenv("VK_OWNER_ID", "-100")
    monkeypatch.setenv("VK_POST_LIMIT_PER_RUN", "2")
    monkeypatch.setattr(cli_module, "VKBrowserPublisher", FakeVKBrowserPublisher)

    result = CliRunner().invoke(
        app,
        [
            "vk-real-cycle",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--fixture-path",
            str(fixture_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Step 3/4: publish --real" in result.output
    assert "Processed 2 planned posts: 2 ok, 0 failed." in result.output
    posts = Store(tmp_path / "app.sqlite3").list_posts(platform="vk", status=PostStatus.PUBLISHED)
    assert len(posts) == 2


def test_publish_cli_rejects_browser_dry_run_combo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VK_BROWSER_ENABLE", "1")
    monkeypatch.setenv("VK_OWNER_ID", "-100")

    result = CliRunner().invoke(
        app,
        ["publish", "--platform", "vk", "--browser", "--db-path", str(tmp_path / "app.sqlite3")],
        terminal_width=160,
    )

    assert result.exit_code != 0
    assert "Use --no-dry-run with --browser" in result.output


def test_sync_cli_missing_fixture_returns_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "sync",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--fixture-path",
            str(tmp_path / "missing.json"),
        ],
    )

    assert result.exit_code != 0
    assert "Fake WB fixture not found" in str(result.exception)


def test_sync_cli_wb_api_without_token_is_blocked(tmp_path: Path, monkeypatch) -> None:
    for name in ("WB_API_TOKEN", "WB_CONTENT_API_TOKEN", "WB_PRICES_API_TOKEN", "WB_ANALYTICS_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    result = CliRunner().invoke(app, ["sync", "--mode", "real-ready", "--db-path", str(tmp_path / "app.sqlite3")])

    assert result.exit_code != 0
    assert "mode=real-ready requires" in result.output
    assert "WB_CONTENT_API_TOKEN" in result.output
    assert "WB_PRICES_API_TOKEN" in result.output
    assert "WB_ANALYTICS_API_TOKEN" in result.output


def test_check_config_wb_api_accepts_shared_wb_token(monkeypatch) -> None:
    for name in ("WB_CONTENT_API_TOKEN", "WB_PRICES_API_TOKEN", "WB_ANALYTICS_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WB_API_TOKEN", "shared-token")

    result = CliRunner().invoke(app, ["check-config", "--mode", "real-ready"])

    assert result.exit_code == 0
    assert "Configuration OK for mode=real-ready." in result.output
    assert "Resolved source: wb-api" in result.output


def test_check_config_test_mode_uses_fake_source() -> None:
    result = CliRunner().invoke(app, ["check-config", "--mode", "test"])

    assert result.exit_code == 0
    assert "Configuration OK for mode=test." in result.output
    assert "Resolved source: fake" in result.output


def test_sync_cli_wb_api_uses_enriched_source_when_tokens_are_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeEnrichedSource:
        init_kwargs: dict[str, object] = {}

        def __init__(self, **kwargs: object) -> None:
            FakeEnrichedSource.init_kwargs = kwargs

        def fetch_products(self):
            return [make_product(nm_id=321, price=990, stock=4)]

    monkeypatch.setattr(cli_module, "WBEnrichedProductSource", FakeEnrichedSource)
    monkeypatch.setenv("WB_CONTENT_API_TOKEN", "content-token")
    monkeypatch.setenv("WB_PRICES_API_TOKEN", "prices-token")
    monkeypatch.setenv("WB_ANALYTICS_API_TOKEN", "analytics-token")
    monkeypatch.setenv("WB_BRAND_FILTER", "North Atelier, Second Brand")
    monkeypatch.setenv("WB_STOCK_TYPE", "mp")
    monkeypatch.setenv("WB_ANALYTICS_PERIOD_DAYS", "2")
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(app, ["sync", "--mode", "real-ready", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "Mode: real-ready" in result.output
    assert "Source: wb-api" in result.output
    assert "Synced 1 products: 1 new, 0 updated." in result.output
    assert FakeEnrichedSource.init_kwargs["content_api_token"] == "content-token"
    assert FakeEnrichedSource.init_kwargs["prices_api_token"] == "prices-token"
    assert FakeEnrichedSource.init_kwargs["analytics_api_token"] == "analytics-token"
    assert FakeEnrichedSource.init_kwargs["brand_filter"] == ["North Atelier", "Second Brand"]
    assert FakeEnrichedSource.init_kwargs["stock_type"] == "mp"
    assert Store(db_path).summary()["products_publishable"] == 1


def test_baseline_sync_cli_marks_current_assortment_without_posts(
    tmp_path: Path,
    fixture_path: Path,
) -> None:
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(
        app,
        [
            "baseline-sync",
            "--mode",
            "test",
            "--db-path",
            str(db_path),
            "--fixture-path",
            str(fixture_path),
        ],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "Baseline set at" in result.output
    assert "No posts were planned" in result.output
    assert store.summary()["products_total"] == 7
    assert store.summary()["posts_total"] == 0
    assert store.baseline_at() is not None


def test_public_baseline_sync_stores_only_seen_nm_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakePublicSource:
        SOURCE_NAME = "wb-public"

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def fetch_nm_ids(self):
            return [1001, 1002]

    monkeypatch.setattr(cli_module, "WBPublicCatalogSource", FakePublicSource)
    monkeypatch.setenv("WB_PUBLIC_QUERY", "hm")
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(
        app,
        ["baseline-sync", "--source", "wb-public", "--db-path", str(db_path)],
    )

    store = Store(db_path)
    assert result.exit_code == 0
    assert "Discovered 2 public WB nmIDs" in result.output
    assert "Top window saved: 2 nmIDs." in result.output
    assert "No product details were fetched" in result.output
    assert store.summary()["products_total"] == 0
    assert store.list_new_seen_nm_ids(source="wb-public") == []
    assert store.get_source_top_window(source="wb-public") == [1001, 1002]


def test_public_baseline_sync_rejects_empty_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakePublicSource:
        SOURCE_NAME = "wb-public"

        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch_nm_ids(self):
            return []

    monkeypatch.setattr(cli_module, "WBPublicCatalogSource", FakePublicSource)
    monkeypatch.setenv("WB_PUBLIC_QUERY", "hm")
    db_path = tmp_path / "app.sqlite3"

    result = CliRunner().invoke(app, ["baseline-sync", "--source", "wb-public", "--db-path", str(db_path)])

    assert result.exit_code != 0
    assert "found 0 nmIDs" in result.output
    assert Store(db_path).baseline_at() is None


def test_public_sync_requires_public_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakePublicSource:
        SOURCE_NAME = "wb-public"

        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch_nm_ids(self):
            return [1001]

    monkeypatch.setattr(cli_module, "WBPublicCatalogSource", FakePublicSource)
    monkeypatch.setenv("WB_PUBLIC_QUERY", "hm")

    result = CliRunner().invoke(app, ["sync", "--source", "wb-public", "--db-path", str(tmp_path / "app.sqlite3")])

    assert result.exit_code != 0
    assert "baseline is missing" in result.output


def test_public_sync_after_baseline_fetches_details_only_for_new_seen_nm_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    class FakePublicSource:
        SOURCE_NAME = "wb-public"

        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch_nm_ids(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                return [1001]
            return [1002, 1001]

        def fetch_products(self, nm_ids):
            assert nm_ids == [1002]
            return [make_product(nm_id=1002, title="Public new product")]

    monkeypatch.setattr(cli_module, "WBPublicCatalogSource", FakePublicSource)
    monkeypatch.setenv("WB_PUBLIC_QUERY", "hm")
    db_path = tmp_path / "app.sqlite3"

    baseline = CliRunner().invoke(app, ["baseline-sync", "--source", "wb-public", "--db-path", str(db_path)])
    sync = CliRunner().invoke(app, ["sync", "--source", "wb-public", "--db-path", str(db_path)])
    plan = CliRunner().invoke(
        app,
        [
            "plan-posts",
            "--platform",
            "vk",
            "--vk-owner-id",
            "-100",
            "--only-after-baseline",
            "--db-path",
            str(db_path),
        ],
    )

    store = Store(db_path)
    assert baseline.exit_code == 0
    assert sync.exit_code == 0
    assert "Synced 1 products: 1 new, 0 updated." in sync.output
    assert "top window saved: 2" in sync.output
    assert plan.exit_code == 0
    assert "Planned 1 posts." in plan.output
    assert store.summary()["products_total"] == 1
    assert [post.product_nm_id for post in store.list_posts(platform="vk")] == [1002]
    assert store.get_source_top_window(source="wb-public") == [1002, 1001]


def test_public_sync_scans_past_old_items_inside_scan_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    class FakePublicSource:
        SOURCE_NAME = "wb-public"

        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch_nm_ids(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                return [1001, 1000]
            return [1002, 1001, 1003, 1000]

        def fetch_products(self, nm_ids):
            assert nm_ids == [1002, 1003]
            return [make_product(nm_id=nm_id, title=f"Public product {nm_id}") for nm_id in nm_ids]

    monkeypatch.setattr(cli_module, "WBPublicCatalogSource", FakePublicSource)
    monkeypatch.setenv("WB_PUBLIC_QUERY", "hm")
    monkeypatch.setenv("WB_PUBLIC_TOP_WINDOW_SIZE", "4")
    db_path = tmp_path / "app.sqlite3"

    baseline = CliRunner().invoke(app, ["baseline-sync", "--source", "wb-public", "--db-path", str(db_path)])
    sync = CliRunner().invoke(app, ["sync", "--source", "wb-public", "--db-path", str(db_path)])

    store = Store(db_path)
    assert baseline.exit_code == 0
    assert sync.exit_code == 0
    assert "Synced 2 products: 2 new, 0 updated." in sync.output
    assert store.get_source_top_window(source="wb-public") == [1002, 1001, 1003, 1000]
    assert sorted(post.product_nm_id for post in store.list_posts(platform="vk")) == []


def test_plan_posts_cli_can_plan_only_after_baseline(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    existing = make_product(nm_id=1001, title="Existing")
    store.upsert_products([existing])
    store.mark_baseline()
    sleep(0.02)
    store.upsert_products([existing, make_product(nm_id=1002, title="New")])

    result = CliRunner().invoke(
        app,
        [
            "plan-posts",
            "--platform",
            "vk",
            "--vk-owner-id",
            "-100",
            "--only-after-baseline",
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code == 0
    assert "Planned 1 posts." in result.output
    assert "Skipped baseline: 1." in result.output
    assert [post.product_nm_id for post in store.list_posts(platform="vk")] == [1002]


def test_plan_posts_cli_requires_baseline_when_only_after_baseline(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite3"
    store = Store(db_path)
    store.init_db()
    store.upsert_products([make_product()])

    result = CliRunner().invoke(
        app,
        [
            "plan-posts",
            "--platform",
            "vk",
            "--vk-owner-id",
            "-100",
            "--only-after-baseline",
            "--db-path",
            str(db_path),
        ],
    )

    assert result.exit_code != 0
    assert "Baseline is missing" in result.output


def test_run_cycle_real_ready_mode_uses_wb_source_and_dry_run_publisher(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeEnrichedSource:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def fetch_products(self):
            return [make_product(nm_id=654, price=1490, stock=5)]

    monkeypatch.setattr(cli_module, "WBEnrichedProductSource", FakeEnrichedSource)
    monkeypatch.setenv("WB_API_TOKEN", "shared-token")

    result = CliRunner().invoke(
        app,
        [
            "run-cycle",
            "--mode",
            "real-ready",
            "--include-current",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert "Mode: real-ready" in result.output
    assert "Source: wb-api" in result.output
    assert "Planned 1 posts." in result.output
    assert "Processed 1 planned posts: 1 ok, 0 failed." in result.output
    assert len(list((tmp_path / "out").glob("pinterest_pin_*.json"))) == 1


def test_run_cycle_real_ready_requires_baseline_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeEnrichedSource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch_products(self):
            return [make_product(nm_id=654, price=1490, stock=5)]

    monkeypatch.setattr(cli_module, "WBEnrichedProductSource", FakeEnrichedSource)
    monkeypatch.setenv("WB_API_TOKEN", "shared-token")

    result = CliRunner().invoke(
        app,
        [
            "run-cycle",
            "--mode",
            "real-ready",
            "--db-path",
            str(tmp_path / "app.sqlite3"),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code != 0
    assert "Baseline is missing" in result.output


def test_run_cycle_real_ready_uses_baseline_to_plan_only_later_products(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    class FakeEnrichedSource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch_products(self):
            nonlocal calls
            calls += 1
            existing = make_product(nm_id=1001, title="Existing", price=1490, stock=5)
            if calls == 1:
                return [existing]
            return [existing, make_product(nm_id=1002, title="New", price=1990, stock=7)]

    monkeypatch.setattr(cli_module, "WBEnrichedProductSource", FakeEnrichedSource)
    monkeypatch.setenv("WB_API_TOKEN", "shared-token")
    monkeypatch.setenv("PINTEREST_POST_LIMIT_PER_RUN", "")
    db_path = tmp_path / "app.sqlite3"
    out_dir = tmp_path / "out"

    baseline = CliRunner().invoke(app, ["baseline-sync", "--mode", "real-ready", "--db-path", str(db_path)])
    result = CliRunner().invoke(
        app,
        [
            "run-cycle",
            "--mode",
            "real-ready",
            "--db-path",
            str(db_path),
            "--out-dir",
            str(out_dir),
        ],
    )

    assert baseline.exit_code == 0
    assert result.exit_code == 0
    assert "Planned 1 posts." in result.output
    assert "Skipped baseline: 1." in result.output
    assert len(list(out_dir.glob("pinterest_pin_*.json"))) == 1
    posts = Store(db_path).list_posts(platform="pinterest", status=PostStatus.DRY_RUN_PUBLISHED)
    assert [post.product_nm_id for post in posts] == [1002]


def test_report_cli_on_empty_database(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["report", "--db-path", str(tmp_path / "app.sqlite3")])

    assert result.exit_code == 0
    assert "Products total: 0" in result.output
    assert "Posts total: 0" in result.output
