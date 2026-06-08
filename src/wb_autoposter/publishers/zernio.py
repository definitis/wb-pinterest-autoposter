from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from wb_autoposter.models import PostStatus, PublishResult
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
    ) -> None:
        if not api_key.strip():
            raise ValueError("Zernio API key is required.")
        self.api_key = api_key
        self.out_dir = out_dir
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30)

    def publish_pinterest(
        self,
        post_id: int,
        payload: dict[str, Any],
        *,
        account_id: str,
        board_id: str,
    ) -> PublishResult:
        request_body = build_zernio_pinterest_post(payload, account_id=account_id, board_id=board_id)
        request_json = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        response = self.client.post(
            "/posts",
            headers={**self._headers(), "x-request-id": _request_id("pinterest", post_id, request_body)},
            content=request_json,
        )
        response.raise_for_status()
        body = response.json()
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
    ) -> None:
        if not account_id.strip():
            raise ValueError("Zernio Pinterest account_id is required.")
        if not board_id.strip():
            raise ValueError("Zernio Pinterest board_id is required.")
        self.account_id = account_id.strip()
        self.board_id = board_id.strip()
        self.publisher = ZernioPublisher(api_key, out_dir=out_dir, client=client)

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        return self.publisher.publish_pinterest(
            post_id,
            payload,
            account_id=self.account_id,
            board_id=self.board_id,
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
