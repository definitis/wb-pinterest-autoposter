from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from wb_autoposter.models import PostStatus, PublishResult


class VKDryRunPublisher:
    """Writes VK API payloads to disk instead of calling VK."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        vk_payload = validate_vk_payload(payload)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        nm_id = payload.get("product_nm_id", "unknown")
        payload_path = self.out_dir / f"vk_wall_post_{post_id}_{nm_id}.json"
        body = {
            "dry_run": True,
            "created_at": datetime.now(UTC).isoformat(),
            "post_id": post_id,
            "request": {
                "method": "POST",
                "url": "https://api.vk.com/method/wall.post",
                "form": _wall_post_form(vk_payload, access_token="<VK_ACCESS_TOKEN>", api_version="5.199"),
            },
            "photo_upload_chain": _dry_run_photo_upload_chain(vk_payload),
            "full_payload": {**payload, "vk": vk_payload},
            "source_product_nm_id": nm_id,
        }
        payload_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

        return PublishResult(
            status=PostStatus.DRY_RUN_PUBLISHED,
            external_id=f"dryrun-vk-{post_id}",
            payload_path=str(payload_path),
        )


class VKApiPublisher:
    """VK API publisher for wall posts.

    The real image path is:
    photos.getWallUploadServer -> upload image -> photos.saveWallPhoto -> wall.post.
    """

    base_url = "https://api.vk.com/method"

    def __init__(
        self,
        access_token: str,
        *,
        owner_id: str | None = None,
        group_id: int | None = None,
        api_version: str = "5.199",
        client: httpx.Client | None = None,
        download_client: httpx.Client | None = None,
    ) -> None:
        self.access_token = access_token
        self.owner_id = owner_id
        self.group_id = group_id
        self.api_version = api_version
        self.client = client or httpx.Client(base_url=self.base_url, timeout=30)
        self.download_client = download_client or httpx.Client(timeout=30)

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        raw_vk_payload = payload.get("vk")
        if isinstance(raw_vk_payload, dict) and self.owner_id and "owner_id" not in raw_vk_payload:
            payload = {**payload, "vk": {**raw_vk_payload, "owner_id": self.owner_id}}
        vk_payload = validate_vk_payload(payload)

        attachments = list(vk_payload.get("attachments") or [])
        if vk_payload.get("upload_photo"):
            attachments.insert(0, self._upload_wall_photo(vk_payload))
        vk_payload["attachments"] = attachments

        response = self.client.post(
            "/wall.post",
            data=_wall_post_form(vk_payload, access_token=self.access_token, api_version=self.api_version),
        )
        response.raise_for_status()
        body = response.json()
        _raise_for_vk_error(body)

        vk_response = body.get("response") or {}
        vk_post_id = str(vk_response.get("post_id") or "")
        if not vk_post_id:
            raise ValueError("VK API response does not include post_id.")

        owner = vk_payload.get("owner_id")
        external_id = f"{owner}_{vk_post_id}" if owner else vk_post_id
        return PublishResult(status=PostStatus.PUBLISHED, external_id=external_id)

    def check_wall_access(self, owner_id: str | None = None) -> dict[str, Any]:
        wall_owner_id = owner_id or self.owner_id
        if not wall_owner_id:
            raise ValueError("VK owner_id is required.")

        response = self.client.post(
            "/wall.get",
            data={
                "owner_id": wall_owner_id,
                "count": "1",
                "access_token": self.access_token,
                "v": self.api_version,
            },
        )
        response.raise_for_status()
        body = response.json()
        if _vk_error_code(body) == 27:
            return self.check_group_access(group_id=self.group_id or _derive_group_id(wall_owner_id))
        _raise_for_vk_error(body)
        return {"check": "wall", "response": body.get("response") or {}}

    def check_group_access(self, group_id: int | None = None) -> dict[str, Any]:
        if group_id is None:
            raise ValueError("VK group_id is required.")

        response = self.client.post(
            "/groups.getById",
            data={
                "group_id": str(group_id),
                "access_token": self.access_token,
                "v": self.api_version,
            },
        )
        response.raise_for_status()
        body = response.json()
        _raise_for_vk_error(body)
        return {"check": "group", "response": body.get("response") or {}}

    def check_photo_upload_access(self, group_id: int | None = None) -> dict[str, Any]:
        upload_group_id = group_id or self.group_id or _derive_group_id(self.owner_id)
        if upload_group_id is None:
            raise ValueError("VK group_id is required to check photo upload access.")

        response = self.client.post(
            "/photos.getWallUploadServer",
            data={
                "group_id": str(upload_group_id),
                "access_token": self.access_token,
                "v": self.api_version,
            },
        )
        response.raise_for_status()
        body = response.json()
        _raise_for_vk_error(body)
        upload_url = str((body.get("response") or {}).get("upload_url") or "")
        if not upload_url:
            raise ValueError("VK upload server response does not include upload_url.")
        return {"check": "photo_upload", "group_id": upload_group_id, "upload_url_available": True}

    def _upload_wall_photo(self, vk_payload: dict[str, Any]) -> str:
        group_id = self.group_id or _derive_group_id(vk_payload.get("owner_id"))
        if group_id is None:
            raise ValueError("VK group_id is required to upload a wall photo.")

        upload_server_response = self.client.post(
            "/photos.getWallUploadServer",
            data={
                "group_id": str(group_id),
                "access_token": self.access_token,
                "v": self.api_version,
            },
        )
        upload_server_response.raise_for_status()
        upload_server_body = upload_server_response.json()
        _raise_for_vk_error(upload_server_body)
        upload_url = str((upload_server_body.get("response") or {}).get("upload_url") or "")
        if not upload_url:
            raise ValueError("VK upload server response does not include upload_url.")

        image_response = self.download_client.get(vk_payload["image_url"])
        image_response.raise_for_status()
        upload_response = self.client.post(
            upload_url,
            files={"photo": ("product.jpg", image_response.content)},
        )
        upload_response.raise_for_status()
        uploaded = upload_response.json()

        save_response = self.client.post(
            "/photos.saveWallPhoto",
            data={
                "group_id": str(group_id),
                "photo": uploaded.get("photo"),
                "server": uploaded.get("server"),
                "hash": uploaded.get("hash"),
                "access_token": self.access_token,
                "v": self.api_version,
            },
        )
        save_response.raise_for_status()
        save_body = save_response.json()
        _raise_for_vk_error(save_body)
        photos = save_body.get("response") or []
        if not photos:
            raise ValueError("VK saveWallPhoto response does not include saved photo.")

        photo = photos[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        access_key = photo.get("access_key")
        if access_key:
            attachment += f"_{access_key}"
        return attachment


def validate_vk_payload(payload: dict[str, Any]) -> dict[str, Any]:
    vk_payload = payload.get("vk")
    if not isinstance(vk_payload, dict):
        raise ValueError("Payload does not include vk section.")

    owner_id = _required_str(vk_payload, "owner_id")
    message = _required_str(vk_payload, "message")
    link = _required_http_url(vk_payload, "link")
    image_url = _required_http_url(vk_payload, "image_url")
    attachments = vk_payload.get("attachments")
    if attachments is None:
        attachments = []
    if isinstance(attachments, str):
        attachments = [attachments]
    if not isinstance(attachments, list) or not all(isinstance(item, str) and item.strip() for item in attachments):
        raise ValueError("VK payload attachments must be a string list.")

    return {
        "owner_id": owner_id,
        "from_group": 1 if bool(vk_payload.get("from_group", 1)) else 0,
        "message": message,
        "attachments": [item.strip() for item in attachments],
        "link": link,
        "image_url": image_url,
        "upload_photo": bool(vk_payload.get("upload_photo", True)),
    }


def build_vk_oauth_url(
    app_id: str,
    *,
    api_version: str = "5.199",
    scope: str = "wall,photos,groups",
    redirect_uri: str | None = "https://oauth.vk.com/blank.html",
    display: str = "page",
) -> str:
    if not app_id.strip():
        raise ValueError("VK app_id is required.")
    params = {
        "client_id": app_id.strip(),
        "display": display,
        "scope": scope,
        "response_type": "token",
        "v": api_version,
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    return "https://oauth.vk.com/authorize?" + urlencode(params)


def _wall_post_form(vk_payload: dict[str, Any], *, access_token: str, api_version: str) -> dict[str, str]:
    form = {
        "owner_id": str(vk_payload["owner_id"]),
        "from_group": "1" if bool(vk_payload.get("from_group")) else "0",
        "message": str(vk_payload["message"]),
        "attachments": ",".join(vk_payload.get("attachments") or []),
        "access_token": access_token,
        "v": api_version,
    }
    return {key: value for key, value in form.items() if value != ""}


def _dry_run_photo_upload_chain(vk_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not vk_payload.get("upload_photo"):
        return []
    return [
        {"method": "POST", "url": "https://api.vk.com/method/photos.getWallUploadServer"},
        {"method": "GET", "url": vk_payload["image_url"]},
        {"method": "POST", "url": "<upload_url from VK>"},
        {"method": "POST", "url": "https://api.vk.com/method/photos.saveWallPhoto"},
    ]


def _derive_group_id(owner_id: Any) -> int | None:
    try:
        normalized = int(str(owner_id))
    except (TypeError, ValueError):
        return None
    if normalized < 0:
        return abs(normalized)
    return None


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"VK payload field '{field}' is required.")
    return value.strip()


def _required_http_url(payload: dict[str, Any], field: str) -> str:
    value = _required_str(payload, field)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"VK payload field '{field}' must be an http/https URL.")
    return value


def _raise_for_vk_error(body: dict[str, Any]) -> None:
    if "error" in body:
        raise ValueError(f"VK API error: {body['error']}")


def _vk_error_code(body: dict[str, Any]) -> int | None:
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("error_code")
    return int(code) if code is not None else None
