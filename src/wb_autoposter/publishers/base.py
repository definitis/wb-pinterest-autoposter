from __future__ import annotations

from typing import Any, Protocol

from wb_autoposter.models import PublishResult


class SocialPublisher(Protocol):
    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        """Publish or simulate publication of one social post."""
