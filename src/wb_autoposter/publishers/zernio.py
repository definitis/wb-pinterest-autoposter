from __future__ import annotations

import json
import uuid
from io import BytesIO
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from wb_autoposter.models import PostStatus, PublishResult
from wb_autoposter.publishers.instagram import validate_instagram_payload
from wb_autoposter.publishers.pinterest import validate_pinterest_payload


class ZernioPublisher:
    """Zernio API publisher for social platforms not covered by the MVP direct flow."""

    base_url = "https://zernio.com/api/v1"

    def __init__(
        self,
        api_key: str,
        *,
        out_dir: Path | None = None,
        client: httpx.Client | None = None,
        download_client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Zernio API key is required.")
        self.api_key = api_key
        self.out_dir = out_dir
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30)
        self.download_client = download_client or httpx.Client(timeout=30)

    def publish_pinterest(
        self,
        post_id: int,
        payload: dict[str, Any],
        *,
        account_id: str,
        board_id: str,
    ) -> PublishResult:
        request_body = build_zernio_pinterest_post(payload, account_id=account_id, board_id=board_id)
        body = self._post_with_utf8("pinterest", post_id, request_body)
        zernio_post_id = _extract_post_id(body)

        payload_path = self._write_artifact(
            post_id,
            payload.get("product_nm_id", "unknown"),
            request_body,
            body,
        )
        return PublishResult(status=PostStatus.PUBLISHED, external_id=zernio_post_id, payload_path=payload_path)

    def publish_instagram(
        self,
        post_id: int,
        payload: dict[str, Any],
        *,
        account_id: str,
        content_type: str,
    ) -> PublishResult:
        request_body = build_zernio_instagram_post(payload, account_id=account_id, content_type=content_type)
        self._prepare_instagram_media(request_body, post_id=post_id, nm_id=payload.get("product_nm_id"))
        body = self._post_with_utf8("instagram", post_id, request_body)
        zernio_post_id = _extract_post_id(body)

        payload_path = self._write_artifact(
            post_id,
            payload.get("product_nm_id", "unknown"),
            request_body,
            body,
        )
        return PublishResult(status=PostStatus.PUBLISHED, external_id=zernio_post_id, payload_path=payload_path)

    def list_accounts(self, *, platform: str | None = None) -> dict[str, Any]:
        params = {"platform": platform} if platform else None
        response = self.client.get("/accounts", headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _post_with_utf8(
        self,
        platform: str,
        post_id: int,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        request_json = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        response = self.client.post(
            "/posts",
            headers={**self._headers(), "x-request-id": _request_id(platform, post_id, request_body)},
            content=request_json,
        )
        if response.status_code >= 400:
            raise ValueError(f"Zernio API error {response.status_code}: {_short_response_text(response)}")
        return response.json()

    def _prepare_instagram_media(self, request_body: dict[str, Any], *, post_id: int, nm_id: object) -> None:
        media_items = request_body.get("mediaItems")
        if not isinstance(media_items, list):
            return
        for index, media_item in enumerate(media_items, start=1):
            if not isinstance(media_item, dict) or media_item.get("type") != "image":
                continue
            image_url = str(media_item.get("url") or "").strip()
            if _is_instagram_supported_image_url(image_url):
                continue
            media_item["url"] = self._upload_jpeg_media(image_url, post_id=post_id, nm_id=nm_id, index=index)

    def _upload_jpeg_media(self, image_url: str, *, post_id: int, nm_id: object, index: int) -> str:
        image_response = self.download_client.get(image_url)
        image_response.raise_for_status()
        jpeg_bytes = _image_response_to_jpeg(image_response)
        filename = f"wb_{nm_id or 'unknown'}_{post_id}_{index}.jpg"

        presign_response = self.client.post(
            "/media/presign",
            headers=self._headers(),
            content=json.dumps(
                {
                    "filename": filename,
                    "contentType": "image/jpeg",
                    "size": len(jpeg_bytes),
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        if presign_response.status_code >= 400:
            raise ValueError(f"Zernio media presign error {presign_response.status_code}: {_short_response_text(presign_response)}")
        presign_body = presign_response.json()
        upload_url = str(presign_body.get("uploadUrl") or "")
        public_url = str(presign_body.get("publicUrl") or "")
        if not upload_url or not public_url:
            raise ValueError("Zernio media presign response does not include uploadUrl/publicUrl.")

        upload_response = self.client.put(
            upload_url,
            headers={"Content-Type": "image/jpeg"},
            content=jpeg_bytes,
        )
        if upload_response.status_code >= 400:
            raise ValueError(f"Zernio media upload error {upload_response.status_code}: {_short_response_text(upload_response)}")
        return public_url

    def _write_artifact(
        self,
        post_id: int,
        nm_id: object,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
    ) -> str | None:
        if self.out_dir is None:
            return None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        payload_path = self.out_dir / f"zernio_post_{post_id}_{nm_id}.json"
        payload_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(UTC).isoformat(),
                    "post_id": post_id,
                    "request": {
                        "method": "POST",
                        "url": f"{self.base_url}/posts",
                        "json": request_body,
                    },
                    "response": response_body,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(payload_path)


class ZernioPinterestPublisher:
    """Adapter that matches the existing SocialPublisher publish(post_id, payload) shape."""

    def __init__(
        self,
        api_key: str,
        *,
        account_id: str,
        board_id: str,
        out_dir: Path | None = None,
        client: httpx.Client | None = None,
        download_client: httpx.Client | None = None,
    ) -> None:
        if not account_id.strip():
            raise ValueError("Zernio Pinterest account_id is required.")
        if not board_id.strip():
            raise ValueError("Zernio Pinterest board_id is required.")
        self.account_id = account_id.strip()
        self.board_id = board_id.strip()
        self.publisher = ZernioPublisher(api_key, out_dir=out_dir, client=client, download_client=download_client)

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        return self.publisher.publish_pinterest(
            post_id,
            payload,
            account_id=self.account_id,
            board_id=self.board_id,
        )


class ZernioInstagramPublisher:
    """Adapter that matches the existing SocialPublisher publish(post_id, payload) shape."""

    def __init__(
        self,
        api_key: str,
        *,
        account_id: str,
        content_type: str = "feed",
        out_dir: Path | None = None,
        client: httpx.Client | None = None,
        download_client: httpx.Client | None = None,
    ) -> None:
        if not account_id.strip():
            raise ValueError("Zernio Instagram account_id is required.")
        if not content_type.strip():
            raise ValueError("Zernio Instagram content_type is required.")
        self.account_id = account_id.strip()
        self.content_type = content_type.strip()
        self.publisher = ZernioPublisher(api_key, out_dir=out_dir, client=client, download_client=download_client)

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        return self.publisher.publish_instagram(
            post_id,
            payload,
            account_id=self.account_id,
            content_type=self.content_type,
        )


def build_zernio_pinterest_post(
    payload: dict[str, Any],
    *,
    account_id: str,
    board_id: str,
) -> dict[str, Any]:
    if not account_id.strip():
        raise ValueError("Zernio Pinterest account_id is required.")
    if not board_id.strip():
        raise ValueError("Zernio Pinterest board_id is required.")

    pin_payload = validate_pinterest_payload(payload)
    media_source = pin_payload["media_source"]
    return {
        "content": pin_payload["description"],
        "mediaItems": [
            {
                "type": "image",
                "url": media_source["url"],
                "title": pin_payload["title"],
            }
        ],
        "platforms": [
            {
                "platform": "pinterest",
                "accountId": account_id.strip(),
                "platformSpecificData": {
                    "title": pin_payload["title"],
                    "boardId": board_id.strip(),
                    "link": pin_payload["link"],
                },
            }
        ],
        "publishNow": True,
        "metadata": {
            "source": "wb-autoposter",
            "productNmId": payload.get("product_nm_id"),
        },
    }


def build_zernio_instagram_post(
    payload: dict[str, Any],
    *,
    account_id: str,
    content_type: str,
) -> dict[str, Any]:
    if not account_id.strip():
        raise ValueError("Zernio Instagram account_id is required.")
    if not content_type.strip():
        raise ValueError("Zernio Instagram content_type is required.")

    instagram_payload = validate_instagram_payload(payload)
    return {
        "content": instagram_payload["caption"],
        "mediaItems": [
            {
                "type": "image",
                "url": instagram_payload["image_url"],
            }
        ],
        "platforms": [
            {
                "platform": "instagram",
                "accountId": account_id.strip(),
                "platformSpecificData": {
                    "contentType": content_type.strip(),
                },
            }
        ],
        "publishNow": True,
        "metadata": {
            "source": "wb-autoposter",
            "productNmId": payload.get("product_nm_id"),
        },
    }


def _extract_post_id(body: dict[str, Any]) -> str:
    post = body.get("post")
    if isinstance(post, dict):
        post_id = str(post.get("_id") or post.get("id") or "")
    else:
        post_id = str(body.get("_id") or body.get("id") or "")
    if not post_id:
        raise ValueError("Zernio API response does not include post id.")
    return post_id


def _request_id(platform: str, post_id: int, request_body: dict[str, Any]) -> str:
    body_hash = sha256(json.dumps(request_body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wb-autoposter:zernio:{platform}:{post_id}:{body_hash}"))


def _short_response_text(response: httpx.Response, *, limit: int = 600) -> str:
    text = response.text.strip()
    if not text:
        return "<empty response>"
    return text[:limit]


def _is_instagram_supported_image_url(image_url: str) -> bool:
    suffix = Path(urlparse(image_url).path).suffix.lower()
    return suffix in {".jpg", ".jpeg", ".png"}


def _image_response_to_jpeg(response: httpx.Response) -> bytes:
    with Image.open(BytesIO(response.content)) as image:
        if image.mode in {"RGBA", "LA"}:
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=92, optimize=True)
        return output.getvalue()
