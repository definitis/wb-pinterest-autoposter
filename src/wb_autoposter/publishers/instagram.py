from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from wb_autoposter.models import PostStatus, PublishResult


class InstagramDryRunPublisher:
    """Writes Instagram payloads to disk instead of calling a real API."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        instagram_payload = validate_instagram_payload(payload)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        nm_id = payload.get("product_nm_id", "unknown")
        payload_path = self.out_dir / f"instagram_post_{post_id}_{nm_id}.json"
        body = {
            "dry_run": True,
            "created_at": datetime.now(UTC).isoformat(),
            "post_id": post_id,
            "request": {
                "method": "POST",
                "url": "https://graph.facebook.com/v25.0/{instagram_user_id}/media",
                "form": instagram_payload,
            },
            "full_payload": {**payload, "instagram": instagram_payload},
            "source_product_nm_id": nm_id,
        }
        payload_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

        return PublishResult(
            status=PostStatus.DRY_RUN_PUBLISHED,
            external_id=f"dryrun-instagram-{post_id}",
            payload_path=str(payload_path),
        )


class InstagramApiPublisher:
    """Instagram Graph API client prepared for feed image publishing.

    Expected payload shape:
    {
        "instagram": {
            "image_url": "https://...",
            "caption": "..."
        }
    }

    Feed captions do not provide the same clickable external traffic path as
    Pinterest, so this publisher is a later-stage integration.
    """

    root_url = "https://graph.facebook.com"

    def __init__(
        self,
        access_token: str,
        instagram_user_id: str,
        *,
        graph_version: str = "v25.0",
        client: httpx.Client | None = None,
    ) -> None:
        self.access_token = access_token
        self.instagram_user_id = instagram_user_id
        self.graph_version = graph_version
        self.client = client or httpx.Client(base_url=f"{self.root_url}/{graph_version}", timeout=30)

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        instagram_payload = validate_instagram_payload(payload)

        container_response = self.client.post(
            f"/{self.instagram_user_id}/media",
            data={**instagram_payload, "access_token": self.access_token},
        )
        container_response.raise_for_status()
        container_body = container_response.json()
        creation_id = str(container_body.get("id") or "")
        if not creation_id:
            raise ValueError("Instagram API response does not include media container id.")

        publish_response = self.client.post(
            f"/{self.instagram_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": self.access_token},
        )
        publish_response.raise_for_status()
        publish_body = publish_response.json()
        media_id = str(publish_body.get("id") or "")
        if not media_id:
            raise ValueError("Instagram API response does not include published media id.")

        return PublishResult(status=PostStatus.PUBLISHED, external_id=media_id)


def validate_instagram_payload(payload: dict[str, Any]) -> dict[str, Any]:
    instagram_payload = payload.get("instagram")
    if not isinstance(instagram_payload, dict):
        raise ValueError("Payload does not include instagram section.")

    image_url = _required_http_url(instagram_payload, "image_url")
    caption = _required_str(instagram_payload, "caption")
    return {
        "image_url": image_url,
        "caption": caption,
    }


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Instagram payload field '{field}' is required.")
    return value.strip()


def _required_http_url(payload: dict[str, Any], field: str) -> str:
    value = _required_str(payload, field)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Instagram payload field '{field}' must be an http/https URL.")
    return value
