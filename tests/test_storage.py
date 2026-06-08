from __future__ import annotations

import json
from datetime import UTC, datetime
from time import sleep

import pytest

from wb_autoposter.adapters.fake_wb import FakeWBSource
from wb_autoposter.models import PostStatus
from wb_autoposter.storage import (
    PostRecord,
    Store,
    build_pinterest_payload,
    build_tracked_link,
    build_vk_payload,
    is_publishable,
)

from helpers import make_product


def test_end_to_end_storage_dry_run_flow(store: Store, fixture_path) -> None:
    products = FakeWBSource(fixture_path).fetch_products()
    sync_result = store.upsert_products(products)

    assert sync_result == {"total": 7, "created": 7, "updated": 0}

    plan_result = store.plan_posts(platform="pinterest", board_id="demo-board")
    assert plan_result == {"planned": 4, "skipped_existing": 0, "skipped_ineligible": 3}

    planned_posts = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)
    assert len(planned_posts) == 4
    assert planned_posts[0].payload["pinterest"]["board_id"] == "demo-board"
    assert planned_posts[0].payload["pinterest"]["media_source"]["source_type"] == "image_url"
    assert planned_posts[0].payload["pinterest"]["media_source"]["url"] == products[0].photos[0]
    assert planned_posts[0].payload["generated_content"]["cta"].endswith("Вайлдберриз")

    for post in planned_posts:
        store.mark_post_publishing(post.id)
        store.update_post_result(post.id, PostStatus.DRY_RUN_PUBLISHED, f"dryrun-{post.id}", None)

    assert len(store.list_posts(platform="pinterest", status=PostStatus.DRY_RUN_PUBLISHED)) == 4

    second_plan = store.plan_posts(platform="pinterest", board_id="demo-board")
    assert second_plan == {"planned": 0, "skipped_existing": 4, "skipped_ineligible": 3}


def test_baseline_blocks_current_assortment_and_allows_later_new_products(store: Store) -> None:
    existing = make_product(nm_id=1001, title="Existing product")
    store.upsert_products([existing])
    baseline = store.mark_baseline()

    assert baseline["products"] == 1
    assert store.baseline_at() is not None

    blocked = store.plan_posts(platform="vk", vk_owner_id="-100", only_after_baseline=True)

    assert blocked == {
        "planned": 0,
        "skipped_existing": 0,
        "skipped_ineligible": 0,
        "skipped_baseline": 1,
    }

    sleep(0.02)
    new_product = make_product(nm_id=1002, title="New product")
    store.upsert_products([existing, new_product])
    planned = store.plan_posts(platform="vk", vk_owner_id="-100", only_after_baseline=True)

    assert planned == {
        "planned": 1,
        "skipped_existing": 0,
        "skipped_ineligible": 0,
        "skipped_baseline": 1,
    }
    posts = store.list_posts(platform="vk", status=PostStatus.PLANNED)
    assert [post.product_nm_id for post in posts] == [1002]


def test_seen_products_top_window_and_pending_details(store: Store) -> None:
    store.upsert_seen_nm_ids([1001, 1002], source="wb-public", mark_baseline=True)
    store.upsert_seen_nm_ids([1003, 1002], source="wb-public")
    top_window = store.set_source_top_window(source="wb-public", nm_ids=[1003, 1002, 1001], window_size=2)

    assert top_window == [1003, 1002]
    assert store.get_source_top_window(source="wb-public") == [1003, 1002]
    assert store.list_seen_nm_ids_pending_details(source="wb-public") == [1003]

    store.upsert_products([make_product(nm_id=1003)])

    assert store.list_seen_nm_ids_pending_details(source="wb-public") == []


def test_plan_posts_only_after_baseline_requires_baseline(store: Store) -> None:
    store.upsert_products([make_product()])

    with pytest.raises(ValueError, match="Baseline is missing"):
        store.plan_posts(platform="vk", vk_owner_id="-100", only_after_baseline=True)


def test_repeat_sync_updates_existing_products(store: Store, fixture_path) -> None:
    products = FakeWBSource(fixture_path).fetch_products()

    first_sync = store.upsert_products(products)
    second_sync = store.upsert_products(products)

    assert first_sync["created"] == 7
    assert second_sync == {"total": 7, "created": 0, "updated": 7}


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({}, True),
        ({"photos": []}, False),
        ({"photos": [""]}, False),
        ({"photos": ["not-a-url"]}, False),
        ({"url": "not-a-url"}, False),
        ({"price": 0}, False),
        ({"price": -10}, False),
        ({"price": None}, False),
        ({"stock": 0}, False),
        ({"stock": -1}, False),
        ({"brand": "   "}, False),
        ({"title": "   "}, False),
    ],
)
def test_publishable_validation_rejects_bad_inputs(updates: dict[str, object], expected: bool) -> None:
    assert is_publishable(make_product().model_copy(update=updates)) is expected


def test_build_payload_rejects_unpublishable_product() -> None:
    with pytest.raises(ValueError, match="is not publishable"):
        build_pinterest_payload(make_product(photo="not-a-url"), "demo-board")


def test_build_payload_can_add_pinterest_tracking_params() -> None:
    product = make_product(nm_id=123, url="https://www.wildberries.ru/catalog/123/detail.aspx?existing=1")

    payload = build_pinterest_payload(
        product,
        "demo-board",
        tracking_params={
            "utm_source": "pinterest",
            "utm_medium": "social",
            "utm_campaign": "wb_new_arrivals",
        },
    )

    assert payload["pinterest"]["link"] == (
        "https://www.wildberries.ru/catalog/123/detail.aspx?"
        "existing=1&utm_source=pinterest&utm_medium=social"
        "&utm_campaign=wb_new_arrivals&utm_content=123"
    )


def test_build_vk_payload_uses_text_link_photo_and_tracking_params() -> None:
    product = make_product(nm_id=123, url="https://www.wildberries.ru/catalog/123/detail.aspx")

    payload = build_vk_payload(
        product,
        "-100",
        tracking_params={"utm_source": "vk", "utm_medium": "social", "utm_campaign": "wb_new_arrivals"},
    )

    vk_payload = payload["vk"]
    assert vk_payload["owner_id"] == "-100"
    assert vk_payload["from_group"] == 1
    assert vk_payload["image_url"] == product.photos[0]
    assert vk_payload["upload_photo"] is True
    assert "utm_source=vk" in vk_payload["link"]
    assert vk_payload["link"] in vk_payload["message"]
    assert vk_payload["attachments"] == [vk_payload["link"]]


def test_build_vk_payload_without_photo_upload_keeps_link_only_in_message() -> None:
    product = make_product(nm_id=123, url="https://www.wildberries.ru/catalog/123/detail.aspx")

    payload = build_vk_payload(product, "-100", upload_photo=False)

    assert payload["vk"]["upload_photo"] is False
    assert payload["vk"]["attachments"] == []
    assert payload["vk"]["link"] in payload["vk"]["message"]


def test_plan_posts_can_create_vk_posts(store: Store) -> None:
    product = make_product()
    store.upsert_products([product])

    result = store.plan_posts(platform="vk", vk_owner_id="-100")

    assert result == {"planned": 1, "skipped_existing": 0, "skipped_ineligible": 0}
    post = store.list_posts(platform="vk", status=PostStatus.PLANNED)[0]
    assert post.payload["vk"]["owner_id"] == "-100"
    assert post.payload["vk"]["image_url"] == product.photos[0]


def test_build_tracked_link_keeps_original_link_without_tracking_params() -> None:
    assert build_tracked_link("https://example.com/item", 123, None) == "https://example.com/item"


def test_planned_payload_refreshes_after_product_update(store: Store) -> None:
    product = make_product(price=1000, title="Old title", photo="https://example.com/old.jpg")
    store.upsert_products([product])
    store.plan_posts(platform="pinterest", board_id="demo-board")

    updated = product.model_copy(
        update={
            "title": "New title",
            "price": 2500,
            "photos": ["https://example.com/new.jpg"],
            "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )
    store.upsert_products([updated])
    result = store.plan_posts(platform="pinterest", board_id="demo-board")

    assert result == {"planned": 0, "skipped_existing": 1, "skipped_ineligible": 0}
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    assert post.payload["pinterest"]["title"] == "New title"
    assert post.payload["pinterest"]["media_source"]["url"] == "https://example.com/new.jpg"
    assert "2 500" in post.payload["pinterest"]["description"]


def test_planned_post_becomes_failed_if_product_is_no_longer_publishable(store: Store) -> None:
    product = make_product(stock=5)
    store.upsert_products([product])
    store.plan_posts(platform="pinterest", board_id="demo-board")

    store.upsert_products([product.model_copy(update={"stock": 0})])
    store.plan_posts(platform="pinterest", board_id="demo-board")

    assert store.list_posts(platform="pinterest", status=PostStatus.PLANNED) == []
    failed_posts = store.list_posts(platform="pinterest", status=PostStatus.FAILED)
    assert len(failed_posts) == 1
    assert failed_posts[0].error == "Product is no longer publishable."


def test_duplicate_insert_is_ignored_without_aborting_transaction(store: Store) -> None:
    product = make_product()
    store.upsert_products([product])
    payload_json = json.dumps(build_pinterest_payload(product, "demo-board"), ensure_ascii=False)

    with store.session_factory.begin() as session:
        first = _post_record(product.nm_id, payload_json)
        duplicate = _post_record(product.nm_id, payload_json)

        assert Store._add_post_record_idempotently(session, first)
        assert not Store._add_post_record_idempotently(session, duplicate)

    assert len(store.list_posts(platform="pinterest", status=PostStatus.PLANNED)) == 1


def test_mark_publishing_rejects_non_planned_post(store: Store) -> None:
    product = make_product()
    store.upsert_products([product])
    store.plan_posts(platform="pinterest", board_id="demo-board")
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)
    store.update_post_result(post.id, PostStatus.DRY_RUN_PUBLISHED, "external", None)

    with pytest.raises(ValueError, match="is not planned"):
        store.mark_post_publishing(post.id)


def test_update_post_result_rejects_missing_post(store: Store) -> None:
    with pytest.raises(ValueError, match="Post not found"):
        store.update_post_result(404, PostStatus.FAILED, None, "missing")


def test_retry_failed_moves_publishable_failed_post_back_to_planned(store: Store) -> None:
    product = make_product()
    store.upsert_products([product])
    store.plan_posts(platform="pinterest", board_id="demo-board")
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)
    store.update_post_result(post.id, PostStatus.FAILED, None, "temporary failure")

    result = store.retry_failed_posts(platform="pinterest", board_id="demo-board")

    assert result == {"retried": 1, "skipped_ineligible": 0, "skipped_missing_product": 0}
    planned_posts = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)
    assert len(planned_posts) == 1
    assert planned_posts[0].error is None


def test_retry_failed_skips_ineligible_product(store: Store) -> None:
    product = make_product()
    store.upsert_products([product])
    store.plan_posts(platform="pinterest", board_id="demo-board")
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)
    store.update_post_result(post.id, PostStatus.FAILED, None, "temporary failure")
    store.upsert_products([product.model_copy(update={"stock": 0})])

    result = store.retry_failed_posts(platform="pinterest", board_id="demo-board")

    assert result == {"retried": 0, "skipped_ineligible": 1, "skipped_missing_product": 0}
    assert len(store.list_posts(platform="pinterest", status=PostStatus.FAILED)) == 1


def test_retry_failed_skips_missing_product(store: Store) -> None:
    with store.session_factory.begin() as session:
        session.add(
            PostRecord(
                product_nm_id=12345,
                platform="pinterest",
                status=PostStatus.FAILED.value,
                payload_json="{}",
                error="missing product",
                created_at=datetime.now(UTC),
            )
        )

    result = store.retry_failed_posts(platform="pinterest", board_id="demo-board")

    assert result == {"retried": 0, "skipped_ineligible": 0, "skipped_missing_product": 1}


def test_recover_publishing_marks_posts_failed_by_default(store: Store) -> None:
    product = make_product()
    store.upsert_products([product])
    store.plan_posts(platform="pinterest", board_id="demo-board")
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)

    result = store.recover_publishing_posts(platform="pinterest")

    assert result == {"recovered": 1, "skipped_ineligible": 0, "skipped_missing_product": 0}
    failed_post = store.list_posts(platform="pinterest", status=PostStatus.FAILED)[0]
    assert "Recovered from stuck publishing state" in (failed_post.error or "")


def test_recover_publishing_can_retry_stuck_posts(store: Store) -> None:
    product = make_product()
    store.upsert_products([product])
    store.plan_posts(platform="pinterest", board_id="old-board")
    post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    store.mark_post_publishing(post.id)

    result = store.recover_publishing_posts(platform="pinterest", action="retry", board_id="new-board")

    assert result == {"recovered": 1, "skipped_ineligible": 0, "skipped_missing_product": 0}
    planned_post = store.list_posts(platform="pinterest", status=PostStatus.PLANNED)[0]
    assert planned_post.payload["pinterest"]["board_id"] == "new-board"
    assert planned_post.error is None


def test_report_summary_on_empty_database(store: Store) -> None:
    assert store.summary() == {
        "products_total": 0,
        "products_publishable": 0,
        "posts_total": 0,
        "posts_by_status": {},
        "last_sync_at": None,
        "baseline_at": None,
    }


def _post_record(nm_id: int, payload_json: str) -> PostRecord:
    return PostRecord(
        product_nm_id=nm_id,
        platform="pinterest",
        status=PostStatus.PLANNED.value,
        payload_json=payload_json,
        created_at=datetime.now(UTC),
    )
