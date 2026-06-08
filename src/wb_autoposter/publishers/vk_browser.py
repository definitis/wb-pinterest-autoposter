from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from wb_autoposter.models import PostStatus, PublishResult
from wb_autoposter.publishers.vk import validate_vk_payload

RU_CREATE = "\u0421\u043e\u0437\u0434\u0430\u0442\u044c"
RU_POST = "\u041f\u043e\u0441\u0442"
RU_WRITE_SOMETHING = "\u041d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0447\u0442\u043e-\u043d\u0438\u0431\u0443\u0434\u044c"
RU_WHATS_NEW = "\u0427\u0442\u043e \u0443 \u0432\u0430\u0441 \u043d\u043e\u0432\u043e\u0433\u043e?"
RU_PHOTO = "\u0424\u043e\u0442\u043e"
RU_NEXT = "\u0414\u0430\u043b\u0435\u0435"
RU_PUBLISH = "\u041e\u043f\u0443\u0431\u043b\u0438\u043a\u043e\u0432\u0430\u0442\u044c"
RU_SEND = "\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c"


class VKBrowserAutomation(Protocol):
    def publish_to_vk(self, vk_payload: dict[str, Any], media_path: Path, post_id: int) -> str | None:
        """Publish a prepared VK wall post through a browser session."""


class BatchVKBrowserAutomation(Protocol):
    def close(self) -> None:
        """Close the browser session."""

    def publish_to_vk(self, vk_payload: dict[str, Any], media_path: Path, post_id: int) -> str | None:
        """Publish a prepared VK wall post through a browser session."""


class VKBrowserPublisher:
    """VK publisher that uses a logged-in browser session instead of VK API.

    This is a local MVP fallback for cases where VK API photo publishing is blocked
    by token restrictions. It is intentionally separate from VKApiPublisher because
    browser automation is less stable than the official API.
    """

    def __init__(
        self,
        *,
        state_path: Path,
        out_dir: Path,
        group_url: str | None = None,
        headless: bool = False,
        confirm_before_post: bool = True,
        download_client: httpx.Client | None = None,
        automation: VKBrowserAutomation | None = None,
    ) -> None:
        self.state_path = state_path
        self.out_dir = out_dir
        self.group_url = group_url
        self.headless = headless
        self.confirm_before_post = confirm_before_post
        self.download_client = download_client or httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                )
            },
        )
        self.automation = automation
        self._batch_automation: VKBrowserAutomation | None = None

    def __enter__(self) -> VKBrowserPublisher:
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def open(self) -> None:
        if self.automation is not None or self._batch_automation is not None:
            return
        self._batch_automation = _PlaywrightVKBrowserAutomation(
            state_path=self.state_path,
            headless=self.headless,
            confirm_before_post=self.confirm_before_post,
            keep_open=True,
        )

    def close(self) -> None:
        automation = self._batch_automation
        if automation is not None and hasattr(automation, "close"):
            automation.close()
        self._batch_automation = None

    def publish(self, post_id: int, payload: dict[str, Any]) -> PublishResult:
        vk_payload = validate_vk_payload(payload)
        if self.group_url:
            vk_payload = {**vk_payload, "group_url": self.group_url}
        media_path = self._download_media(post_id, payload.get("product_nm_id"), vk_payload["image_url"])
        automation = self.automation or self._batch_automation or _PlaywrightVKBrowserAutomation(
            state_path=self.state_path,
            headless=self.headless,
            confirm_before_post=self.confirm_before_post,
        )
        external_id = automation.publish_to_vk(vk_payload, media_path, post_id) or f"browser-vk-{post_id}"
        return PublishResult(status=PostStatus.PUBLISHED, external_id=external_id, payload_path=str(media_path))

    def _download_media(self, post_id: int, nm_id: Any, image_url: str) -> Path:
        media_dir = self.out_dir / "vk_browser_media"
        media_dir.mkdir(parents=True, exist_ok=True)
        response = self._get_media_with_retries(image_url)
        suffix = _media_suffix(image_url, response.headers.get("content-type", ""))
        media_path = media_dir / f"vk_post_{post_id}_{nm_id or 'unknown'}{suffix}"
        media_path.write_bytes(response.content)
        return media_path

    def _get_media_with_retries(self, image_url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self.download_client.get(image_url)
                response.raise_for_status()
                if not response.content:
                    raise ValueError("Downloaded VK post image is empty.")
                return response
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 3:
                    sleep(1)
        raise ValueError(f"Could not download VK post image after 3 attempts: {last_error}") from last_error


@dataclass(frozen=True)
class VKBrowserLoginResult:
    state_path: Path


def save_vk_browser_login(
    *,
    state_path: Path,
    start_url: str = "https://vk.com/",
    headless: bool = False,
) -> VKBrowserLoginResult:
    """Open VK login page and save browser storage state after manual login."""
    sync_playwright = _load_sync_playwright()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(state_path) if state_path.exists() else None)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        input("Log in to VK in the opened browser, then press Enter here to save the session...")
        context.storage_state(path=str(state_path))
        browser.close()
    return VKBrowserLoginResult(state_path=state_path)


class _PlaywrightVKBrowserAutomation:
    def __init__(
        self,
        *,
        state_path: Path,
        headless: bool,
        confirm_before_post: bool,
        keep_open: bool = False,
    ) -> None:
        self.state_path = state_path
        self.headless = headless
        self.confirm_before_post = confirm_before_post
        self.keep_open = keep_open
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.storage_state(path=str(self.state_path))
            except Exception:
                pass
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def publish_to_vk(self, vk_payload: dict[str, Any], media_path: Path, post_id: int) -> str | None:
        if not self.state_path.exists():
            raise ValueError(
                "VK browser session is missing. Run vk-browser-login first or set VK_BROWSER_STATE_PATH."
            )

        if self.keep_open:
            page = self._ensure_page()
            try:
                return self._publish_on_page(page, vk_payload, media_path, post_id)
            except Exception as exc:
                debug_dir = _save_debug_artifacts(page, post_id)
                raise ValueError(f"{exc} Debug artifacts: {debug_dir}") from exc

        sync_playwright = _load_sync_playwright()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            context = browser.new_context(storage_state=str(self.state_path))
            page = context.new_page()
            try:
                external_id = self._publish_on_page(page, vk_payload, media_path, post_id)
                context.storage_state(path=str(self.state_path))
                return external_id
            except Exception as exc:
                debug_dir = _save_debug_artifacts(page, post_id)
                raise ValueError(f"{exc} Debug artifacts: {debug_dir}") from exc
            finally:
                browser.close()

    def _ensure_page(self) -> Any:
        if self._page is not None:
            return self._page
        sync_playwright = _load_sync_playwright()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(storage_state=str(self.state_path))
        self._page = self._context.new_page()
        return self._page

    def _publish_on_page(self, page: Any, vk_payload: dict[str, Any], media_path: Path, post_id: int) -> str:
        group_url = str(vk_payload.get("group_url") or _group_url_from_payload(vk_payload))
        if _normalize_vk_url(page.url) != _normalize_vk_url(group_url):
            page.goto(group_url, wait_until="domcontentloaded")
        else:
            _close_post_modal_if_open(page)
        page.wait_for_timeout(1000)
        _open_post_editor(page)
        _fill_post_message(page, str(vk_payload["message"]))
        _attach_post_photo(page, media_path)
        if self.confirm_before_post:
            input("Review the prepared VK post in the browser, then press Enter here to publish...")
        _click_publish(page)
        page.wait_for_timeout(2500)
        _wait_until_post_modal_closes(page)
        return _best_effort_wall_url(page.url, post_id)


def _load_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on local install
        raise RuntimeError(
            "Playwright is required for VK browser publishing. "
            "Run: python -m pip install -e \".[dev]\" && python -m playwright install chromium"
        ) from exc
    return sync_playwright


def _open_post_editor(page: Any) -> None:
    candidates = [
        f"text={RU_WHATS_NEW}",
        f"text={RU_WRITE_SOMETHING}",
        "[contenteditable='true']",
        "[role='textbox']",
    ]
    if _click_text(page, RU_CREATE, exact=True, timeout=5000):
        page.wait_for_timeout(700)
        if _click_text(page, RU_POST, exact=True, timeout=5000):
            page.wait_for_timeout(1500)
            if _click_first_locator(page, candidates, timeout=5000):
                return

    if _click_first_locator(page, candidates, timeout=2500):
        return

    raise ValueError("Could not find VK post editor. Make sure the account can post in this community.")


def _fill_post_message(page: Any, message: str) -> None:
    candidates = [
        "[contenteditable='true']",
        "[role='textbox']",
        "textarea",
    ]
    for selector in candidates:
        locator = page.locator(selector).first
        try:
            locator.fill(message, timeout=5000)
            return
        except Exception:
            try:
                locator.click(timeout=2000)
                locator.press_sequentially(message, delay=2, timeout=15000)
                return
            except Exception:
                continue
    raise ValueError("Could not fill VK post message.")


def _attach_post_photo(page: Any, media_path: Path) -> None:
    file_inputs = page.locator("input[type='file']")
    try:
        if file_inputs.count() > 0:
            file_inputs.first.set_input_files(str(media_path), timeout=5000)
            page.wait_for_timeout(1500)
            return
    except Exception:
        pass

    photo_buttons = [
        f"text={RU_PHOTO}",
        "[aria-label*='фото' i]",
        "[aria-label*='photo' i]",
    ]
    for selector in photo_buttons:
        try:
            page.locator(selector).first.click(timeout=3000)
            page.locator("input[type='file']").first.set_input_files(str(media_path), timeout=5000)
            page.wait_for_timeout(1500)
            return
        except Exception:
            continue
    raise ValueError("Could not attach VK post photo.")


def _click_publish(page: Any) -> None:
    next_candidates = [
        f"button:has-text('{RU_NEXT}')",
        f"text={RU_NEXT}",
    ]
    final_candidates = [
        f"button:has-text('{RU_PUBLISH}')",
        f"button:has-text('{RU_SEND}')",
        f"text={RU_PUBLISH}",
        f"text={RU_SEND}",
    ]
    if _click_last_locator(page, next_candidates, timeout=5000):
        page.wait_for_timeout(1200)
        if not _click_last_locator(page, final_candidates, timeout=5000):
            raise ValueError("Could not find VK final publish button after clicking Next.")
        return
    if _click_last_locator(page, final_candidates, timeout=5000):
        return
    raise ValueError("Could not find VK publish button.")


def _click_first_locator(page: Any, selectors: list[str], *, timeout: int) -> bool:
    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _click_last_locator(page: Any, selectors: list[str], *, timeout: int) -> bool:
    for selector in selectors:
        try:
            page.locator(selector).last.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _click_text(page: Any, text: str, *, exact: bool, timeout: int) -> bool:
    try:
        page.get_by_text(text, exact=exact).first.click(timeout=timeout)
        return True
    except Exception:
        return False


def _save_debug_artifacts(page: Any, post_id: int) -> Path:
    debug_dir = Path("out") / "vk_browser_debug" / f"post_{post_id}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(debug_dir / "page.png"), full_page=True)
    except Exception:
        pass
    try:
        (debug_dir / "page.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        (debug_dir / "page.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
    except Exception:
        pass
    return debug_dir


def _close_post_modal_if_open(page: Any) -> None:
    try:
        if page.get_by_text(RU_WRITE_SOMETHING).count() == 0:
            return
        close_buttons = [
            "[aria-label='Закрыть']",
            "button:has-text('×')",
            ".vkuiModalDismissButton",
        ]
        _click_last_locator(page, close_buttons, timeout=1000)
        page.wait_for_timeout(500)
    except Exception:
        pass


def _wait_until_post_modal_closes(page: Any) -> None:
    try:
        page.get_by_text(RU_WRITE_SOMETHING).first.wait_for(state="detached", timeout=5000)
    except Exception:
        page.wait_for_timeout(1000)


def _normalize_vk_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not parsed.netloc:
        return url
    return f"{parsed.netloc}/{path}"


def _group_url_from_payload(vk_payload: dict[str, Any]) -> str:
    owner_id = str(vk_payload["owner_id"])
    try:
        parsed_owner_id = int(owner_id)
    except ValueError:
        return "https://vk.com/"
    if parsed_owner_id < 0:
        return f"https://vk.com/club{abs(parsed_owner_id)}"
    return f"https://vk.com/id{parsed_owner_id}"


def _best_effort_wall_url(current_url: str, post_id: int) -> str:
    parsed = urlparse(current_url)
    if parsed.scheme and parsed.netloc:
        return current_url
    return f"browser-vk-{post_id}"


def _media_suffix(image_url: str, content_type: str) -> str:
    parsed_suffix = Path(urlparse(image_url).path).suffix.lower()
    if parsed_suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return parsed_suffix
    normalized = content_type.split(";")[0].strip().lower()
    if normalized == "image/png":
        return ".png"
    if normalized == "image/webp":
        return ".webp"
    return ".jpg"
