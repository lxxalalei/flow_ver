"""Browser-driven Douyin collection (mix) enumeration.

The mix list API (``/aweme/v1/web/mix/aweme/``) is gated by ByteDance's
Argus device-signature layer: direct a_bogus-signed requests fail with 403
``ArgusSecurityPlugin Uifid/Signature Not Found`` regardless of cookie
validity (verified 2026-09-03 — the wall sits in front of authentication).
Instead we open the real collection modal in headless Chromium with the saved
login cookies and harvest the front-end's own mix responses; the page signs
everything for us.

Flow: ``/collection/{mix_id}`` redirects to an episode video page (seed
aweme); the direct detail API (not Argus-gated) resolves the creator
``sec_uid``; the creator page with ``modal_id`` opens the collection player;
ArrowDown presses and playlist scrolling drive pagination until the front-end
reports ``has_more=0``. Items arrive in playlist order; the mix response does
not carry episode numbers (only the detail API's ``current_episode`` does).
"""

from __future__ import annotations

import logging
import random
import re
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from ..errors import DomainError

LOGGER = logging.getLogger(__name__)

MIX_LIST_PATH = "/aweme/v1/web/mix/aweme/"
_VIDEO_URL_RE = re.compile(r"/video/(\d+)")

# Timing knobs as module constants so tests can shrink them to zero.
INITIAL_PAGE_WAIT_SECONDS = 6.0
REDIRECT_WAIT_SECONDS = 30.0
MODAL_OPEN_WAIT_SECONDS = 8.0
KEY_PRESS_INTERVAL_SECONDS = (1.2, 2.0)
COMPLETE_STALE_ROUNDS = 3
STALE_STOP_ROUNDS = 20
NO_ITEM_STOP_ROUNDS = 10
MAX_DRIVE_ROUNDS = 150

# Scroll every scrollable container in the right half of the viewport — one of
# them is the collection playlist panel, which lazy-loads the next batch.
SCROLL_PLAYLIST_JS = """
() => {
  const vw = window.innerWidth;
  let scrolled = 0;
  document.querySelectorAll('div,ul,section').forEach(el => {
    if (el.scrollHeight > el.clientHeight + 60 && el.clientHeight > 150) {
      const r = el.getBoundingClientRect();
      if (r.left > vw * 0.4 && r.width < vw * 0.6) {
        el.scrollTop = el.scrollHeight;
        scrolled++;
      }
    }
  });
  return scrolled;
}
"""

# The author link on a video page carries the creator sec_uid — resolving it
# from the DOM keeps the browser flow free of direct API calls (which can be
# Argus-gated independently of the mix endpoint).
FIND_AUTHOR_LINK_JS = """
() => {
  for (const a of document.querySelectorAll('a[href*="/user/"]')) {
    const m = (a.getAttribute('href') || '').match(/\\/user\\/(MS4[^\\/?#]+)/);
    if (m) return m[1];
  }
  return null;
}
"""


def _require_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DomainError(
            "DEPENDENCY_MISSING",
            "抖音合集枚举需要 playwright 可选依赖"
            "（安装: pip install 'playwright>=1.61,<1.62'，"
            "浏览器复用 %LOCALAPPDATA%\\ms-playwright 缓存）",
            False,
        ) from exc
    return sync_playwright


class _MixHarvest:
    """Collect the front-end's mix list responses, deduped by aweme_id."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.has_more: bool | None = None

    def handle(self, response: Any) -> None:
        try:
            path = urllib.parse.urlparse(response.url).path
        except Exception:  # noqa: BLE001
            return
        if MIX_LIST_PATH not in path:
            return
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return
        if not isinstance(data, dict):
            return
        if data.get("has_more") is not None:
            self.has_more = bool(data.get("has_more"))
        for item in data.get("aweme_list") or []:
            if isinstance(item, dict):
                aid = str(item.get("aweme_id") or "")
                if aid:
                    self.items.setdefault(aid, item)


def _drive(
    page: Any, harvest: _MixHarvest, cancel_event: Any
) -> tuple[bool, bool]:
    """Advance the playlist until complete or stalled.

    Returns ``(confirmed_complete, cancelled)``: the front-end reported
    ``has_more=0`` and produced no new items for a few rounds, versus the
    drive stopped on cancellation or a long stale streak without completion.
    """

    stale = 0
    last_n = -1
    for round_index in range(1, MAX_DRIVE_ROUNDS + 1):
        if cancel_event is not None and cancel_event.is_set():
            return False, True
        page.keyboard.press("ArrowDown")
        if round_index % 3 == 0:
            try:
                page.evaluate(SCROLL_PLAYLIST_JS)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(random.uniform(*KEY_PRESS_INTERVAL_SECONDS))
        count = len(harvest.items)
        stale = stale + 1 if count == last_n else 0
        last_n = count
        if round_index % 20 == 0:
            LOGGER.info(
                "mix drive round %d: %d items (has_more=%s, stale=%d)",
                round_index,
                count,
                harvest.has_more,
                stale,
            )
        if count and harvest.has_more is False and stale >= COMPLETE_STALE_ROUNDS:
            return True, False
        if count and stale >= STALE_STOP_ROUNDS:
            return False, False
        if not count and stale >= NO_ITEM_STOP_ROUNDS:
            return False, False
    return False, False


def _enumerate_on_page(
    page: Any,
    harvest: _MixHarvest,
    *,
    mix_id: str,
    fetch_detail: Callable[[str], dict[str, Any]],
    cancel_event: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page.on("response", harvest.handle)
    # 1) /collection/{mix_id} redirects to an episode page -> seed aweme.
    # The redirect is client-side and can trail the domcontentloaded event.
    page.goto(
        f"https://www.douyin.com/collection/{mix_id}",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    try:
        page.wait_for_url(_VIDEO_URL_RE, timeout=int(REDIRECT_WAIT_SECONDS * 1000))
    except Exception:  # noqa: BLE001 - fall through to the explicit check
        pass
    time.sleep(INITIAL_PAGE_WAIT_SECONDS)
    match = _VIDEO_URL_RE.search(page.url or "")
    if not match:
        raise DomainError(
            "PARTIAL_FAILURE", "抖音合集页未重定向到视频，无法定位起始作品", True
        )
    seed_aweme = match.group(1)
    LOGGER.info("mix %s: seed aweme %s from redirect", mix_id, seed_aweme)
    if cancel_event is not None and cancel_event.is_set():
        return [], {
            "mix_id": mix_id,
            "cancelled": True,
            "confirmed_complete": False,
            "item_count": 0,
        }

    # 2) resolve the creator sec_uid. Prefer the page's own author link so the
    # browser flow never needs a direct API call; fall back to the detail API
    # (normally not Argus-gated) only when the DOM does not expose it.
    sec_uid = ""
    detail: dict[str, Any] = {}
    try:
        sec_uid = str(page.evaluate(FIND_AUTHOR_LINK_JS) or "").strip()
    except Exception:  # noqa: BLE001
        sec_uid = ""
    creator_source = "page dom"
    if not sec_uid:
        creator_source = "detail api"
        detail = fetch_detail(seed_aweme) or {}
        sec_uid = str((detail.get("author") or {}).get("sec_uid") or "").strip()
    if not sec_uid:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED", "无法定位合集作者 sec_uid", False
        )
    LOGGER.info("mix %s: creator resolved from %s", mix_id, creator_source)

    # 3) open the collection modal and drive the playlist
    page.goto(
        f"https://www.douyin.com/user/{sec_uid}"
        f"?showTab=post&showSubTab=compilation&modal_id={seed_aweme}",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    time.sleep(MODAL_OPEN_WAIT_SECONDS)
    confirmed_complete, cancelled = _drive(page, harvest, cancel_event)
    if not harvest.items:
        raise DomainError(
            "PARTIAL_FAILURE", "抖音合集弹窗未触发列表请求（页面结构可能变化）", True
        )
    mix_info = detail.get("mix_info") if detail else None
    if not (mix_info and mix_info.get("mix_name")) and harvest.items:
        first = next(iter(harvest.items.values()))
        mix_info = first.get("mix_info") or {}
    return list(harvest.items.values()), {
        "mix_id": mix_id,
        "mix_name": (mix_info or {}).get("mix_name"),
        "creator_sec_uid": sec_uid,
        "confirmed_complete": confirmed_complete,
        "cancelled": cancelled,
        "item_count": len(harvest.items),
    }


def enumerate_collection(
    session_data: dict[str, Any],
    *,
    mix_id: str,
    fetch_detail: Callable[[str], dict[str, Any]],
    cancel_event: Any = None,
    page: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Enumerate one mix via the real front-end.

    Returns ``(raw_aweme_items_in_playlist_order, info)``. ``page`` injects an
    already-open page (tests); otherwise a headless Chromium context is
    launched with the saved login cookies. Callers normalize the raw items.
    """

    harvest = _MixHarvest()
    if page is not None:
        return _enumerate_on_page(
            page,
            harvest,
            mix_id=mix_id,
            fetch_detail=fetch_detail,
            cancel_event=cancel_event,
        )

    cookies = [
        cookie
        for cookie in (session_data or {}).get("cookies") or []
        if isinstance(cookie, dict) and cookie.get("name")
    ]
    sync_playwright = _require_playwright()
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    headless=True, channel="chromium"
                )
            except Exception as exc:  # noqa: BLE001
                raise DomainError(
                    "DEPENDENCY_MISSING",
                    f"无法启动 Chromium（{type(exc).__name__}）。"
                    "请运行 python -m playwright install chromium 安装浏览器",
                    False,
                ) from exc
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}, locale="zh-CN"
            )
            context.add_cookies(cookies)
            browser_page = context.new_page()
            try:
                return _enumerate_on_page(
                    browser_page,
                    harvest,
                    mix_id=mix_id,
                    fetch_detail=fetch_detail,
                    cancel_event=cancel_event,
                )
            finally:
                browser.close()
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "code"):  # adapter errors keep their classification
            raise
        raise DomainError(
            "PARTIAL_FAILURE",
            f"抖音合集页面驱动失败: {type(exc).__name__}: {exc}",
            True,
        ) from exc


__all__ = ["enumerate_collection"]
