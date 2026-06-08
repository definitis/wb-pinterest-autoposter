from __future__ import annotations

import httpx
import pytest

from wb_autoposter.models import PostStatus
from wb_autoposter.publishers.instagram import InstagramApiPublisher
from wb_autoposter.publishers.vk import VKApiPublisher, VKDryRunPublisher, build_vk_oauth_url, validate_vk_payload
from wb_autoposter.publishers.vk_browser import VKBrowserPublisher


def test_vk_api_publisher_posts_to_wall() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"response": {"post_id": 77}})

    client = httpx.Client(base_url=VKApiPublisher.base_url, transport=httpx.MockTransport(handler))
    payload = {
        "vk": {
            "message": "New arrival",
            "link": "https://example.com/item",
            "image_url": "https://example.com/photo.jpg",
            "attachments": ["https://example.com/item"],
            "upload_photo": False,
        }
    }

    result = VKApiPublisher("token", owner_id="-100", client=client).publish(1, payload)

    assert result.status == PostStatus.PUBLISHED
    assert result.external_id == "-100_77"
    assert requests[0].url.path == "/method/wall.post"
    form = requests[0].content.decode("utf-8")
    assert "access_token=token" in form
    assert "owner_id=-100" in form
    assert "attachments=https%3A%2F%2Fexample.com%2Fitem" in form


def test_vk_api_publisher_raises_for_api_error() -> None:
    client = httpx.Client(
        base_url=VKApiPublisher.base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"error": {"error_msg": "bad"}})),
    )

    with pytest.raises(ValueError, match="VK API error"):
        VKApiPublisher("token", owner_id="-100", client=client).publish(
            1,
            {
                "vk": {
                    "message": "x",
                    "link": "https://example.com/item",
                    "image_url": "https://example.com/photo.jpg",
                    "attachments": ["https://example.com/item"],
                    "upload_photo": False,
                }
            },
        )


def test_vk_dry_run_publisher_writes_payload(tmp_path) -> None:
    payload = {
        "product_nm_id": 123,
        "vk": {
            "owner_id": "-100",
            "message": "New arrival",
            "link": "https://example.com/item",
            "image_url": "https://example.com/photo.jpg",
            "attachments": ["https://example.com/item"],
            "upload_photo": True,
        },
    }

    result = VKDryRunPublisher(tmp_path).publish(5, payload)

    assert result.status == PostStatus.DRY_RUN_PUBLISHED
    assert result.external_id == "dryrun-vk-5"


def test_vk_browser_publisher_downloads_photo_and_calls_automation(tmp_path) -> None:
    calls: list[tuple[dict[str, object], str, int]] = []

    class FakeAutomation:
        def publish_to_vk(self, vk_payload, media_path, post_id):
            calls.append((vk_payload, media_path.read_text(encoding="utf-8"), post_id))
            return "browser-post-1"

    download_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"image-bytes", headers={"content-type": "image/jpeg"})
        )
    )
    payload = {
        "product_nm_id": 123,
        "vk": {
            "owner_id": "-100",
            "message": "New arrival",
            "link": "https://example.com/item",
            "image_url": "https://example.com/photo.jpg",
            "attachments": ["https://example.com/item"],
            "upload_photo": True,
        },
    }

    result = VKBrowserPublisher(
        state_path=tmp_path / "state.json",
        out_dir=tmp_path,
        group_url="https://vk.com/club100",
        download_client=download_client,
        automation=FakeAutomation(),
    ).publish(5, payload)

    assert result.status == PostStatus.PUBLISHED
    assert result.external_id == "browser-post-1"
    assert result.payload_path is not None
    assert result.payload_path.endswith("vk_post_5_123.jpg")
    assert calls == [
        (
            {
                "owner_id": "-100",
                "from_group": 1,
                "message": "New arrival",
                "attachments": ["https://example.com/item"],
                "link": "https://example.com/item",
                "image_url": "https://example.com/photo.jpg",
                "upload_photo": True,
                "group_url": "https://vk.com/club100",
            },
            "image-bytes",
            5,
        )
    ]


def test_vk_browser_publisher_reuses_batch_automation(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    class FakeBatchAutomation:
        def __init__(self, **kwargs) -> None:
            calls.append(("init", 0))

        def publish_to_vk(self, vk_payload, media_path, post_id):
            calls.append(("publish", post_id))
            return f"browser-post-{post_id}"

        def close(self):
            calls.append(("close", 0))

    monkeypatch.setattr("wb_autoposter.publishers.vk_browser._PlaywrightVKBrowserAutomation", FakeBatchAutomation)
    download_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"image-bytes", headers={"content-type": "image/jpeg"})
        )
    )
    payload = {
        "product_nm_id": 123,
        "vk": {
            "owner_id": "-100",
            "message": "New arrival",
            "link": "https://example.com/item",
            "image_url": "https://example.com/photo.jpg",
            "attachments": ["https://example.com/item"],
            "upload_photo": True,
        },
    }
    publisher = VKBrowserPublisher(
        state_path=tmp_path / "state.json",
        out_dir=tmp_path,
        download_client=download_client,
    )

    publisher.open()
    publisher.publish(5, payload)
    publisher.publish(6, payload)
    publisher.close()

    assert calls == [("init", 0), ("publish", 5), ("publish", 6), ("close", 0)]


def test_vk_browser_publisher_retries_image_download(tmp_path) -> None:
    attempts = 0

    class FakeAutomation:
        def publish_to_vk(self, vk_payload, media_path, post_id):
            return "browser-post-1"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("connection reset")
        return httpx.Response(200, content=b"image-bytes", headers={"content-type": "image/jpeg"})

    payload = {
        "product_nm_id": 123,
        "vk": {
            "owner_id": "-100",
            "message": "New arrival",
            "link": "https://example.com/item",
            "image_url": "https://example.com/photo.jpg",
            "attachments": ["https://example.com/item"],
            "upload_photo": True,
        },
    }

    result = VKBrowserPublisher(
        state_path=tmp_path / "state.json",
        out_dir=tmp_path,
        download_client=httpx.Client(transport=httpx.MockTransport(handler)),
        automation=FakeAutomation(),
    ).publish(5, payload)

    assert result.status == PostStatus.PUBLISHED
    assert attempts == 2


def test_vk_api_publisher_uploads_photo_before_wall_post() -> None:
    requests: list[httpx.Request] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/photos.getWallUploadServer"):
            return httpx.Response(200, json={"response": {"upload_url": "https://upload.vk.test/photo"}})
        if request.url.host == "upload.vk.test":
            return httpx.Response(200, json={"photo": "[]", "server": 1, "hash": "hash"})
        if request.url.path.endswith("/photos.saveWallPhoto"):
            return httpx.Response(200, json={"response": [{"owner_id": -100, "id": 555}]})
        return httpx.Response(200, json={"response": {"post_id": 77}})

    image_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"image-bytes"))
    )
    api_client = httpx.Client(base_url=VKApiPublisher.base_url, transport=httpx.MockTransport(api_handler))
    payload = {
        "vk": {
            "owner_id": "-100",
            "message": "New arrival",
            "link": "https://example.com/item",
            "image_url": "https://example.com/photo.jpg",
            "attachments": ["https://example.com/item"],
            "upload_photo": True,
        }
    }

    result = VKApiPublisher("token", client=api_client, download_client=image_client).publish(1, payload)

    assert result.external_id == "-100_77"
    assert [request.url.path for request in requests] == [
        "/method/photos.getWallUploadServer",
        "/photo",
        "/method/photos.saveWallPhoto",
        "/method/wall.post",
    ]


def test_vk_api_publisher_wall_check_falls_back_to_group_check_for_community_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/wall.get"):
            return httpx.Response(
                200,
                json={"error": {"error_code": 27, "error_msg": "Group authorization failed"}},
            )
        return httpx.Response(200, json={"response": [{"id": 239286699, "name": "Test"}]})

    client = httpx.Client(base_url=VKApiPublisher.base_url, transport=httpx.MockTransport(handler))

    result = VKApiPublisher("token", owner_id="-239286699", group_id=239286699, client=client).check_wall_access()

    assert result["check"] == "group"
    assert [request.url.path for request in requests] == ["/method/wall.get", "/method/groups.getById"]


def test_vk_api_publisher_checks_photo_upload_access() -> None:
    client = httpx.Client(
        base_url=VKApiPublisher.base_url,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"response": {"upload_url": "https://upload.vk.test/photo"}})
        ),
    )

    result = VKApiPublisher("token", owner_id="-239286699", group_id=239286699, client=client).check_photo_upload_access()

    assert result == {"check": "photo_upload", "group_id": 239286699, "upload_url_available": True}


def test_build_vk_oauth_url() -> None:
    url = build_vk_oauth_url("123", api_version="5.199")

    assert url.startswith("https://oauth.vk.com/authorize?")
    assert "client_id=123" in url
    assert "scope=wall%2Cphotos%2Cgroups" in url


def test_build_vk_oauth_url_can_omit_redirect_uri() -> None:
    url = build_vk_oauth_url("123", redirect_uri=None)

    assert "client_id=123" in url
    assert "redirect_uri" not in url


def test_validate_vk_payload_rejects_bad_link() -> None:
    with pytest.raises(ValueError, match="link"):
        validate_vk_payload(
            {
                "vk": {
                    "owner_id": "-100",
                    "message": "x",
                    "link": "not-a-url",
                    "image_url": "https://example.com/photo.jpg",
                }
            }
        )


def test_instagram_api_publisher_creates_container_then_publishes_media() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "media-123"})
        return httpx.Response(200, json={"id": "container-123"})

    client = httpx.Client(base_url="https://graph.facebook.com/v25.0", transport=httpx.MockTransport(handler))
    payload = {"instagram": {"image_url": "https://example.com/photo.jpg", "caption": "New arrival"}}

    result = InstagramApiPublisher("token", "ig-user-1", client=client).publish(1, payload)

    assert result.status == PostStatus.PUBLISHED
    assert result.external_id == "media-123"
    assert requests[0].url.path == "/v25.0/ig-user-1/media"
    assert requests[1].url.path == "/v25.0/ig-user-1/media_publish"
    assert "creation_id=container-123" in requests[1].content.decode("utf-8")


def test_instagram_api_publisher_raises_without_container_id() -> None:
    client = httpx.Client(
        base_url="https://graph.facebook.com/v25.0",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )

    with pytest.raises(ValueError, match="media container id"):
        InstagramApiPublisher("token", "ig-user-1", client=client).publish(
            1,
            {"instagram": {"image_url": "https://example.com/photo.jpg", "caption": "x"}},
        )
