from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from wb_autoposter.models import PostStatus, PublishResult


class PinterestDryRunPublisher:
    """Writes Pinterest API payloads to disk instead of calling Pinterest."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        pin_payload = validate_pinterest_payload(payload)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        nm_id = payload.get("product_nm_id", "unknown")
        payload_path = self.out_dir / f"pinterest_pin_{post_id}_{nm_id}.json"
        body = {
            "dry_run": True,
            "created_at": datetime.now(UTC).isoformat(),
            "post_id": post_id,
            "request": {
                "method": "POST",
                "url": "https://api.pinterest.com/v5/pins",
                "json": pin_payload,
            },
            "full_payload": {**payload, "pinterest": pin_payload},
            "source_product_nm_id": nm_id,
        }
        payload_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

        return PublishResult(
            status=PostStatus.DRY_RUN_PUBLISHED,
            external_id=f"dryrun-pinterest-{post_id}",
            payload_path=str(payload_path),
        )


class PinterestApiPublisher:
    """Pinterest API publisher prepared for real Pin creation."""

    base_url = "https://api.pinterest.com/v5"

    def __init__(self, access_token: str, *, client: httpx.Client | None = None) -> None:
        self.access_token = access_token
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30)

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        pin_payload = validate_pinterest_payload(payload)
        response = self.client.post(
            "/pins",
            headers=self._headers(),
            json=pin_payload,
        )
        response.raise_for_status()
        body = response.json()
        pin_id = str(body.get("id") or "")
        if not pin_id:
            raise ValueError("Pinterest API response does not include pin id.")

        return PublishResult(status=PostStatus.PUBLISHED, external_id=pin_id)

    def get_board(self, board_id: str) -> dict[str, Any]:
        if not board_id.strip():
            raise ValueError("Pinterest board_id is required.")

        response = self.client.get(f"/boards/{board_id}", headers=self._headers())
        response.raise_for_status()
        body = response.json()
        if str(body.get("id") or "") != board_id:
            raise ValueError("Pinterest API response does not match requested board_id.")
        return body

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }


def validate_pinterest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    pin_payload = payload.get("pinterest")
    if not isinstance(pin_payload, dict):
        raise ValueError("Payload does not include pinterest section.")

    title = _required_str(pin_payload, "title")
    description = _required_str(pin_payload, "description")
    board_id = _required_str(pin_payload, "board_id")
    link = _required_http_url(pin_payload, "link")

    media_source = pin_payload.get("media_source")
    if not isinstance(media_source, dict):
        raise ValueError("Pinterest payload media_source must be an object.")
    source_type = _required_str(media_source, "source_type")
    if source_type != "image_url":
        raise ValueError("Pinterest media_source.source_type must be 'image_url'.")
    image_url = _required_http_url(media_source, "url")

    return {
        "title": title,
        "description": description,
        "board_id": board_id,
        "link": link,
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Pinterest payload field '{field}' is required.")
    return value.strip()


def _required_http_url(payload: dict[str, Any], field: str) -> str:
    value = _required_str(payload, field)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Pinterest payload field '{field}' must be an http/https URL.")
    return value
