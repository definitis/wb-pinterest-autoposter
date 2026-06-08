from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from wb_autoposter.models import PostStatus
from wb_autoposter.publishers.pinterest import PinterestDryRunPublisher
from wb_autoposter.publishers.pinterest import PinterestApiPublisher
from wb_autoposter.publishers.pinterest import validate_pinterest_payload
from wb_autoposter.publishers.zernio import ZernioPinterestPublisher, ZernioPublisher
from wb_autoposter.publishers.zernio import build_zernio_pinterest_post
from wb_autoposter.storage import build_pinterest_payload

from helpers import make_product


def test_pinterest_dry_run_publisher_writes_request_payload(tmp_path: Path) -> None:
    product = make_product()
    payload = build_pinterest_payload(product, "demo-board")

    result = PinterestDryRunPublisher(tmp_path).publish(12, payload)

    output_path = Path(result.payload_path or "")
    assert output_path.exists()
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["dry_run"] is True
    assert written["request"]["method"] == "POST"
    assert written["request"]["url"] == "https://api.pinterest.com/v5/pins"
    assert written["request"]["json"]["media_source"]["url"] == product.photos[0]
    assert written["full_payload"] == payload
    assert result.external_id == "dryrun-pinterest-12"


def test_pinterest_api_publisher_posts_pin_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "pin-123"})

    client = httpx.Client(
        base_url=PinterestApiPublisher.base_url,
        transport=httpx.MockTransport(handler),
    )
    payload = build_pinterest_payload(make_product(), "board-1")

    result = PinterestApiPublisher("token", client=client).publish(7, payload)

    assert result.status == PostStatus.PUBLISHED
    assert result.external_id == "pin-123"
    assert requests[0].url.path == "/v5/pins"
    assert requests[0].headers["Authorization"] == "Bearer token"
    assert json.loads(requests[0].content)["board_id"] == "board-1"


def test_pinterest_api_publisher_gets_board() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "board-1", "name": "New arrivals"})

    client = httpx.Client(
        base_url=PinterestApiPublisher.base_url,
        transport=httpx.MockTransport(handler),
    )

    board = PinterestApiPublisher("token", client=client).get_board("board-1")

    assert board["name"] == "New arrivals"
    assert requests[0].url.path == "/v5/boards/board-1"
    assert requests[0].headers["Authorization"] == "Bearer token"


def test_pinterest_api_publisher_rejects_board_id_mismatch() -> None:
    client = httpx.Client(
        base_url=PinterestApiPublisher.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "other-board"})),
    )

    with pytest.raises(ValueError, match="does not match"):
        PinterestApiPublisher("token", client=client).get_board("board-1")


def test_pinterest_api_publisher_raises_without_pin_id() -> None:
    client = httpx.Client(
        base_url=PinterestApiPublisher.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(201, json={})),
    )
    payload = build_pinterest_payload(make_product(), "board-1")

    with pytest.raises(ValueError, match="does not include pin id"):
        PinterestApiPublisher("token", client=client).publish(7, payload)


def test_pinterest_api_publisher_raises_for_http_errors() -> None:
    client = httpx.Client(
        base_url=PinterestApiPublisher.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"code": 1})),
    )
    payload = build_pinterest_payload(make_product(), "board-1")

    with pytest.raises(httpx.HTTPStatusError):
        PinterestApiPublisher("bad-token", client=client).publish(7, payload)


def test_validate_pinterest_payload_rejects_bad_media_source() -> None:
    payload = build_pinterest_payload(make_product(), "board-1")
    payload["pinterest"]["media_source"]["source_type"] = "video_id"

    with pytest.raises(ValueError, match="source_type"):
        validate_pinterest_payload(payload)


def test_validate_pinterest_payload_rejects_bad_link() -> None:
    payload = build_pinterest_payload(make_product(), "board-1")
    payload["pinterest"]["link"] = "not-a-url"

    with pytest.raises(ValueError, match="link"):
        validate_pinterest_payload(payload)


def test_build_zernio_pinterest_post_maps_existing_pinterest_payload() -> None:
    product = make_product()
    payload = build_pinterest_payload(product, "old-board")

    zernio_payload = build_zernio_pinterest_post(payload, account_id="acc-1", board_id="board-1")

    assert zernio_payload["content"] == payload["pinterest"]["description"]
    assert zernio_payload["mediaItems"] == [
        {"type": "image", "url": product.photos[0], "title": payload["pinterest"]["title"]}
    ]
    assert zernio_payload["platforms"] == [
        {
            "platform": "pinterest",
            "accountId": "acc-1",
            "platformSpecificData": {
                "title": payload["pinterest"]["title"],
                "boardId": "board-1",
                "link": payload["pinterest"]["link"],
            },
        }
    ]
    assert zernio_payload["publishNow"] is True
    assert zernio_payload["metadata"]["productNmId"] == product.nm_id


def test_zernio_pinterest_publisher_posts_to_zernio(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"post": {"_id": "zp-123", "status": "publishing"}})

    client = httpx.Client(
        base_url=ZernioPublisher.base_url,
        transport=httpx.MockTransport(handler),
    )
    payload = build_pinterest_payload(make_product(), "board-1")

    result = ZernioPinterestPublisher(
        "token",
        account_id="acc-1",
        board_id="board-1",
        out_dir=tmp_path,
        client=client,
    ).publish(7, payload)

    assert result.status == PostStatus.PUBLISHED
    assert result.external_id == "zp-123"
    assert result.payload_path is not None
    assert Path(result.payload_path).exists()
    assert requests[0].url.path == "/api/v1/posts"
    assert requests[0].headers["Authorization"] == "Bearer token"
    assert "x-request-id" in requests[0].headers
    request_json = json.loads(requests[0].content)
    assert request_json["platforms"][0]["platform"] == "pinterest"
    assert request_json["platforms"][0]["accountId"] == "acc-1"


def test_zernio_publisher_lists_accounts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"accounts": [{"_id": "acc-1", "platform": "pinterest"}]})

    client = httpx.Client(
        base_url=ZernioPublisher.base_url,
        transport=httpx.MockTransport(handler),
    )

    result = ZernioPublisher("token", client=client).list_accounts(platform="pinterest")

    assert result["accounts"][0]["_id"] == "acc-1"
    assert requests[0].url.path == "/api/v1/accounts"
    assert requests[0].url.params["platform"] == "pinterest"
