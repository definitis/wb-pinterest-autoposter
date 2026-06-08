from __future__ import annotations

from typing import Any

import httpx

from wb_autoposter.models import PostStatus, PublishResult


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
        instagram_payload = payload.get("instagram")
        if not isinstance(instagram_payload, dict):
            raise ValueError("Payload does not include instagram section.")

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
