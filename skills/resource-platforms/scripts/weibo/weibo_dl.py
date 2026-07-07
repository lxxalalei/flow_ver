#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微博用户微博爬取下载器
===========================
给定微博用户主页链接，爬取该用户所有个人微博（图文+视频）并下载到本地。

用法:
  python weibo_dl.py https://weibo.com/u/1669879400 -o D:\\weibo_output
  python weibo_dl.py https://weibo.com/n/迪丽热巴 -o D:\\weibo_output --max-pages 5
  python weibo_dl.py --uid 1669879400 -o D:\\weibo_output

依赖: requests (无其他第三方依赖)
Cookie: 需要有效的 SUB cookie（Cookie Bridge 方式获取）
"""

import argparse
import json
import os
import re
import sys
import time
import random
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared.utils import safe_filename
from shared.logger import getLogger

log = getLogger("weibo")

# ============================================================
# Constants
# ============================================================

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

API_BASE = "https://weibo.com/ajax"
COMMENTS_API = "https://m.weibo.cn/comments/hotflow"

# safe_filename provided by shared.utils


def _extract_mid_from_md(content: str) -> str:
    """Extract the post's own mid from md footer line '> ID: xxx | 来源:'.
    Scans from bottom up to avoid matching '转载原帖 ID:' in repost sections."""
    for line in reversed(content.strip().split("\n")):
        m = re.match(r'^>\s*ID:\s*(\d+)', line.strip())
        if m:
            return m.group(1)
    return ""


# ============================================================
# Cookie Loader
# ============================================================

def load_cookies(cookie_path: str | None) -> str:
    """Load cookies from an explicit file or the runtime environment."""
    if not cookie_path:
        cookies = os.environ.get("WEIBO_COOKIE", "").strip()
        if cookies:
            if "SUB=" not in cookies:
                log.error("WEIBO_COOKIE does not contain SUB cookie (login required)")
                sys.exit(1)
            return cookies
        cookie_path = os.environ.get("WEIBO_COOKIE_FILE")
    if not cookie_path:
        log.error("Weibo search requires WEIBO_COOKIE or WEIBO_COOKIE_FILE")
        sys.exit(1)
    p = Path(cookie_path)
    # Try workspace-relative paths
    if not p.is_absolute():
        candidates = [
            p,
            Path(__file__).parent.parent / cookie_path,
            Path(__file__).parent / cookie_path,
            Path.cwd() / cookie_path,
        ]
        for c in candidates:
            if c.exists():
                p = c
                break

    if not p.exists():
        log.error("Cookie file not found: %s", p)
        log.error("Please login via browser_use and save cookies to weibo_cookies.txt")
        log.error("Or specify path with --cookie")
        sys.exit(1)

    with open(p, encoding="utf-8-sig") as f:
        cookies = f.read().strip()

    if "SUB=" not in cookies:
        log.error("Cookie file does not contain SUB cookie (login required)")
        sys.exit(1)

    return cookies


def make_headers(cookie_str: str, referer: str = "https://weibo.com/") -> dict:
    """Build request headers with cookie."""
    xsrf = ""
    m = re.search(r"XSRF-TOKEN=([^;]+)", cookie_str)
    if m:
        xsrf = m.group(1)
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_str,
        "X-XSRF-TOKEN": xsrf,
    }


# ============================================================
# UID Resolution
# ============================================================

def parse_uid_from_url(url: str) -> Optional[str]:
    """Extract uid from weibo URL patterns."""
    # https://weibo.com/u/1669879400
    m = re.search(r"weibo\.com/u/(\d+)", url)
    if m:
        return m.group(1)
    # https://m.weibo.cn/u/1669879400
    m = re.search(r"m\.weibo\.cn/u/(\d+)", url)
    if m:
        return m.group(1)
    # https://weibo.com/1669879400 (direct profile)
    m = re.search(r"weibo\.com/(\d{6,})", url)
    if m:
        return m.group(1)
    return None


def resolve_uid(url: str, headers: dict) -> str:
    """Resolve uid from URL (handles /n/昵称 and /u/uid patterns)."""
    uid = parse_uid_from_url(url)
    if uid:
        return uid

    # /n/昵称 pattern → need to resolve via API
    # Try loading the page and checking redirect
    import requests as req
    try:
        r = req.get(url, headers=headers, timeout=15, allow_redirects=True)
        final_url = r.url
        uid = parse_uid_from_url(final_url)
        if uid:
            return uid

        # Try to find uid in HTML
        m = re.search(r'\$CONFIG\[\'uid\'\]\s*=\s*[\'"](\d+)', r.text)
        if m:
            return m.group(1)
        m = re.search(r'"id"\s*:\s"(\d{6,})"', r.text)
        if m:
            return m.group(1)
    except Exception:
        pass

    log.error("Cannot resolve uid from URL: %s", url)
    log.error("Please use URL format: https://weibo.com/u/{uid}")
    sys.exit(1)


# ============================================================
# Weibo API Client
# ============================================================

class WeiboClient:
    """Lightweight weibo.com/ajax API client with cookie auto-refresh."""

    def __init__(self, cookie_str: str, cookie_path: str = ""):
        self.cookie_str = cookie_str
        self.cookie_path = cookie_path  # for writing back refreshed cookies
        self.headers = make_headers(cookie_str)
        self._session = None
        self._refresh_count = 0

    def _capture_cookies(self, response):
        """Capture refreshed SUB cookie from response and save to file."""
        # requests.Session auto-updates its cookie jar, we just need to persist
        sub_cookie = None
        for cookie in self._session.cookies:
            if cookie.name == "SUB" and cookie.value:
                sub_cookie = f"{cookie.name}={cookie.value}"
                break
        if sub_cookie and sub_cookie != self.cookie_str.split(";")[0].strip():
            self._refresh_count += 1
            # Update our header + session
            self.cookie_str = sub_cookie
            self.headers["Cookie"] = sub_cookie
            if self._session:
                self._session.headers["Cookie"] = sub_cookie
            # Write back to file
            if self.cookie_path:
                try:
                    Path(self.cookie_path).write_text(sub_cookie, encoding="utf-8")
                except Exception:
                    pass

    @property
    def session(self):
        """Lazy init requests.Session for connection reuse."""
        if self._session is None:
            import requests as req
            self._session = req.Session()
            self._session.headers.update(self.headers)
        return self._session

    def _get(self, url, params=None, timeout=15):
        """GET with auto-retry on cookie expiry."""
        r = self.session.get(url, params=params, timeout=timeout)
        self._capture_cookies(r)
        d = r.json()
        # If cookie expired mid-session, try once with refreshed cookie
        if d.get("ok") == -100:
            log.warning("Cookie 返回 -100，尝试用新 Cookie 重试...")
            # Force update session headers
            self._session.headers["Cookie"] = self.cookie_str
            r = self.session.get(url, params=params, timeout=timeout)
            self._capture_cookies(r)
            d = r.json()
        return d

    def get_user_info(self, uid: str) -> dict:
        """Get user profile info."""
        d = self._get(f"{API_BASE}/profile/info", params={"uid": uid})
        if d.get("ok") != 1:
            raise RuntimeError(f"Failed to get user info: ok={d.get('ok')}, msg={d.get('msg', '')}")
        return d["data"]["user"]

    def get_user_posts(self, uid: str, page: int = 1, feature: int = 0) -> list:
        """Get user posts (mymblog). Returns list of post dicts."""
        d = self._get(f"{API_BASE}/statuses/mymblog", params={"uid": uid, "page": page, "feature": feature})
        if d.get("ok") != 1:
            if d.get("ok") == -100:
                raise PermissionError("Cookie expired (got -100 after retry). Please re-login.")
            return []
        return d.get("data", {}).get("list", [])

    def get_post_detail(self, mid: str) -> dict:
        """Get single post detail."""
        d = self._get(f"{API_BASE}/statuses/show", params={"id": mid})
        if d.get("ok") != 1:
            return {}
        return d

    def get_longtext(self, mid: str) -> str:
        """Get full text for long posts. Returns longTextContent or empty string."""
        d = self._get(f"{API_BASE}/statuses/longtext", params={"id": mid})
        if d.get("ok") == 1 and "data" in d:
            content = d["data"].get("longTextContent", "")
            if content:
                # longTextContent may be plain text or HTML
                content = re.sub(r'<br\s*/?\s*>', '\n', content, flags=re.IGNORECASE)
                content = re.sub(r'<[^>]+>', '', content)
                return content.strip()
        return ""

    def get_full_text(self, mid: str, fallback_raw: str = "") -> str:
        """Get full text for any post, avoiding mymblog truncation.
        
        Strategy: try longtext API first (for isLongText posts),
        then detail API (returns full text_raw for all posts),
        finally fallback to the raw text from list API.
        """
        # Try longtext API (most reliable for long posts)
        lt = self.get_longtext(mid)
        if lt and len(lt) > len(sanitize_text_md(fallback_raw)) + 20:
            return lt
        
        # Try detail API (returns full text_raw without truncation)
        try:
            d = self._get(f"{API_BASE}/statuses/show", params={"id": mid})
            text_raw = d.get("text_raw", d.get("text", ""))
            if text_raw:
                full = sanitize_text_md(text_raw)
                if len(full) > len(sanitize_text_md(fallback_raw)) + 20:
                    return full
        except Exception:
            pass
        
        # Fallback: use whatever we have
        return sanitize_text_md(fallback_raw)

    def get_all_posts(self, uid: str, max_pages: int = 0, since_id: str = "") -> list:
        """
        Fetch all user posts with pagination.
        max_pages=0 means fetch all.
        since_id: stop when we encounter this post id (for incremental).
        """
        all_posts = []
        page = 1
        empty_count = 0
        api_total = None  # API-reported total (first page)

        while True:
            if max_pages and page > max_pages:
                log.info("Reached max pages limit (%d)", max_pages)
                break

            log.info("Fetching page %d...", page)
            try:
                d = self._get(f"{API_BASE}/statuses/mymblog",
                              params={"uid": uid, "page": page, "feature": 0})
                if d.get("ok") != 1:
                    if d.get("ok") == -100:
                        raise PermissionError("Cookie expired")
                    log.warning("API error (ok=%s)", d.get('ok'))
                    break
                posts = d.get("data", {}).get("list", [])
                # Capture API total from first page
                if api_total is None and "data" in d:
                    api_total = d["data"].get("total")
            except PermissionError:
                log.error("Cookie expired during pagination")
                break
            except Exception as e:
                log.error("分页错误: %s", e)
                empty_count += 1
                if empty_count >= 3:
                    log.warning("错误过多，停止分页")
                    break
                time.sleep(random.uniform(3, 6))
                continue

            if not posts:
                log.info("0 posts (empty)")
                empty_count += 1
                if empty_count >= 2:
                    log.warning("Consecutive empty pages, stopping")
                    break
            else:
                log.info("%d posts", len(posts))
                empty_count = 0
                for p in posts:
                    # Check if we've seen this post (incremental)
                    pid = str(p.get("id", p.get("mid", "")))
                    if since_id and pid == since_id:
                        log.info("Reached since_id=%s, stopping", since_id)
                        return all_posts
                    all_posts.append(p)

            page += 1
            # Rate limit: 2-4 seconds between pages
            time.sleep(random.uniform(2, 4))

        # Report coverage
        if api_total is not None and api_total != len(all_posts):
            gap = api_total - len(all_posts)
            log.info("API total=%s, fetched=%d, 差距=%s", api_total, len(all_posts), gap)
            log.info("差距原因: 被删除/仅自己可见/审核中/置顶帖重复等")

        return all_posts

    def search(self, keyword: str, page: int = 1, count: int = 10) -> dict:
        """搜索微博。基于 weibo.com/ajax/searchall API。

        返回原始 API 响应 dict，包含 note 和 statuses 列表。
        需要 Cookie（SUB cookie 登录态）。
        """
        params = {
            "q": keyword,
            "page": page,
            "count": count,
        }
        d = self._get(f"{API_BASE}/searchall", params=params)
        if d.get("ok") == -100:
            raise PermissionError("Cookie expired (got -100). Please re-login.")
        return d


# ============================================================
# Search
# ============================================================

def search_weibo(keyword: str, cookie_str: str, max_results: int = 20) -> list[dict]:
    """搜索微博内容，返回标准候选列表。

    需要有效的 SUB cookie。
    """
    all_candidates: list[dict] = []
    seen_mids: set[str] = set()
    page = 1

    while len(all_candidates) < max_results:
        log.info("搜索微博 (page %d): '%s'...", page, keyword)
        try:
            params = urllib.parse.urlencode({"q": keyword, "page": page, "count": 10})
            request = urllib.request.Request(
                f"{API_BASE}/searchall?{params}",
                headers=make_headers(cookie_str),
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("ok") == -100:
                raise PermissionError("Cookie expired (got -100). Please re-login.")
        except PermissionError as e:
            log.error("%s", e)
            break
        except Exception as e:
            log.error("搜索失败: %s", e)
            break

        if data.get("ok") != 1:
            log.warning("API 返回 ok=%s", data.get('ok'))
            break

        # searchall 返回格式：data.data.notes 或 data.data.statuses
        inner = data.get("data", {})
        notes = inner.get("notes") or inner.get("statuses") or []

        if not notes:
            log.info("0 条 (空)")
            break

        new_count = 0
        for note in notes:
            mid = str(note.get("id") or note.get("mid") or note.get("note_id") or "")
            if not mid or mid in seen_mids:
                continue
            seen_mids.add(mid)

            # 提取标题和内容
            text_raw = note.get("text_raw") or note.get("text") or note.get("note") or ""
            text_clean = sanitize_text(text_raw)
            title = text_clean[:60] if text_clean else f"微博 {mid}"

            # 构建 URL
            bid = note.get("bid") or ""
            uid = note.get("user", {}).get("id", "") if isinstance(note.get("user"), dict) else ""
            if bid:
                url = f"https://weibo.com/{uid}/{bid}" if uid else f"https://weibo.com/detail/{mid}"
            else:
                url = f"https://weibo.com/detail/{mid}"

            # 资源类型判断
            has_video = bool(extract_video_url(note))
            image_urls = extract_image_urls(note)
            if has_video:
                resource_type = "视频"
                fmt = "mp4"
            elif image_urls:
                resource_type = "图文"
                fmt = "md"
            else:
                resource_type = "图文"
                fmt = "md"

            author = ""
            user = note.get("user")
            if isinstance(user, dict):
                author = user.get("screen_name", "")

            all_candidates.append({
                "source": "weibo-post",
                "source_name": "Weibo (微博)",
                "source_platform": "weibo",
                "source_url": url,
                "resource_id": mid,
                "title": title,
                "resource_type": resource_type,
                "format": fmt,
                "provider": author,
                "downloadable": True,
                "requires_auth": True,
                "metadata_confidence": 0.5,
                "snippet": text_clean[:200],
                "raw": {"page": page, "bid": bid},
            })
            new_count += 1
            if len(all_candidates) >= max_results:
                break

        log.info("%d 条 (累计 %d)", new_count, len(all_candidates))

        if new_count == 0 or len(all_candidates) >= max_results:
            break
        page += 1
        time.sleep(random.uniform(2, 4))

    return all_candidates[:max_results]


def output_candidates(results: list[dict], keyword: str, output_file: str = "") -> dict:
    """输出标准 candidate JSON。"""
    data = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "weibo-post",
        "query": keyword,
        "searched_at": datetime.now().isoformat(),
        "candidates": results,
    }
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).write_text(output + "\n", encoding="utf-8")
        log.info("候选列表已保存: %s", output_file)
    else:
        print(output)
    return data


# ============================================================
# Downloaders
# ============================================================

def download_file(url: str, output_path: str, referer: str = "https://weibo.com/",
                  max_retries: int = 3, cookie_str: str = "") -> bool:
    """Download file using urllib with retries and backoff."""
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer,
    }
    if cookie_str:
        headers["Cookie"] = cookie_str

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                tmp_path = str(output_path) + ".tmp"
                with open(tmp_path, "wb") as f:
                    downloaded = 0
                    while True:
                        chunk = resp.read(1024 * 1024)  # 1MB chunks
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                # Atomic rename
                os.replace(tmp_path, output_path)
                return True
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            if attempt < max_retries:
                wait = attempt * 3
                log.warning("下载失败 (尝试 %d/%d)，%ds 后重试: %s", attempt, max_retries, wait, e)
                time.sleep(wait)
            else:
                log.error("下载失败 (已重试 %d 次): %s", max_retries, e)
                return False
        except Exception as e:
            if attempt < max_retries:
                wait = attempt * 2
                time.sleep(wait)
            else:
                log.error("下载错误: %s", e)
                return False
    return False


def extract_video_url(post: dict) -> Optional[str]:
    """Extract best video URL from post.
    
    Checks both page_info.media_info and mix_media_info.items[].data.media_info.
    Some posts (especially reposts) put video in mix_media_info instead.
    """
    # Source 1: page_info.media_info (standard location)
    pi = post.get("page_info", {})
    if pi:
        mi = pi.get("media_info", {})
        if mi:
            for key in ["stream_url_hd", "mp4_hd_url", "stream_url", "mp4_sd_url"]:
                url = mi.get(key, "")
                if url and url.startswith("http"):
                    return url

    # Source 2: mix_media_info.items[].data.media_info (reposts, mixed media)
    mmi = post.get("mix_media_info", {})
    if mmi:
        for item in mmi.get("items", []):
            if item.get("type") == "video":
                mi = item.get("data", {}).get("media_info", {})
                if mi:
                    for key in ["stream_url_hd", "mp4_hd_url", "stream_url", "mp4_sd_url"]:
                        url = mi.get(key, "")
                        if url and url.startswith("http"):
                            return url

    return None


def extract_image_urls(post: dict) -> list:
    """Extract all image URLs from post.
    
    Priority: pic_infos (with actual URLs) > pic_ids (fallback CDN URL).
    Reposts often have pic_ids but empty pic_infos.
    """
    urls = []
    pic_infos = post.get("pic_infos", {})
    pic_ids = post.get("pic_ids", [])

    if pic_infos:
        for pic_id, info in pic_infos.items():
            # Try original → large → mw2000
            for quality in ["original", "large", "mw2000"]:
                q_info = info.get(quality, {})
                url = q_info.get("url", "")
                if url and url.startswith("http"):
                    urls.append(url)
                    break
            else:
                # Fallback to top-level url
                url = info.get("url", "")
                if url and url.startswith("http"):
                    urls.append(url)

    # Fallback: if pic_infos empty but pic_ids exist, construct CDN URLs
    if not urls and pic_ids:
        for pid in pic_ids:
            urls.append(f"https://wx1.sinaimg.cn/large/{pid}.jpg")

    return urls


def sanitize_text(text: str) -> str:
    """Clean HTML tags from post text (single line)."""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def sanitize_text_md(text: str) -> str:
    """Clean HTML but keep line breaks for Markdown output."""
    # Replace <br> with actual newlines
    text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up excessive blank lines but keep intentional ones
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def sanitize_filename(name: str) -> str:
    """Sanitize string for use as directory/file name. Keep CJK + alphanumeric only."""
    # Keep only CJK, alphanumeric, underscore, dash
    name = re.sub(r'[^\u4e00-\u9fff\w\-]', '', name)
    # Collapse underscores
    name = re.sub(r'_+', '_', name.strip('_'))
    name = name.rstrip('._')
    return name[:50] if name else "post"


# ============================================================
# HTML Generator
# ============================================================

_HTML_CSS = """<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"Microsoft YaHei","PingFang SC",sans-serif;background:#f0f0f0;color:#333;line-height:1.7}
.post{max-width:680px;margin:20px auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
h1{font-size:19px;font-weight:600;margin-bottom:8px}
.meta{color:#999;font-size:13px;margin-bottom:16px}
.meta span{margin-right:16px}
video{width:100%;border-radius:8px;margin:8px 0 16px;background:#000}
.text{margin:12px 0 16px;white-space:pre-wrap;word-break:break-word}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin:8px 0 16px}
.gallery img{width:100%;border-radius:6px;cursor:pointer;transition:transform .15s}
.gallery img:hover{transform:scale(1.02)}
.repost{border-left:3px solid #ff8200;background:#fffbf5;border-radius:0 8px 8px 0;padding:16px 20px;margin:16px 0}
.repost h2{font-size:15px;color:#ff8200;margin-bottom:8px}
.repost .meta{font-size:12px}
.repost .text{font-size:14px}
.repost video{border-radius:6px}
.repost .gallery img{border-radius:4px}
.footer{color:#bbb;font-size:11px;margin-top:20px;padding-top:12px;border-top:1px solid #f0f0f0}
.video-link{display:inline-block;background:#ff8200;color:#fff;padding:6px 16px;border-radius:6px;text-decoration:none;font-size:13px;margin:8px 0 16px}
.video-link:hover{background:#e67300}
</style>"""


def _build_html(title, created, likes, comments, reposts,
                text, has_video, video_url, video_size_mb,
                local_images, all_image_urls,
                retweeted, download_media, mid, source):
    """Build a standalone index.html for one weibo post."""
    parts = [f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
{_HTML_CSS}
</head><body><div class="post">
<h1>{_esc(title)}</h1>
<div class="meta">"""]

    if created:
        parts.append(f'<span>📅 {_esc(created)}</span>')
    if likes:
        parts.append(f'<span>👍 {_fmt(likes)}</span>')
    if comments:
        parts.append(f'<span>💬 {_fmt(comments)}</span>')
    if reposts:
        parts.append(f'<span>🔄 {_fmt(reposts)}</span>')
    parts.append('</div>')

    # Video
    if has_video:
        local_v = "video.mp4"
        v_exists = download_media  # we'll check path later, simplify
        parts.append('<div class="video-block">')
        if download_media and video_size_mb is not None:
            parts.append(f'<video controls preload="metadata" src="{local_v}"></video>')
            parts.append(f'<div style="font-size:12px;color:#999;margin-bottom:8px">{video_size_mb} MB</div>')
        else:
            parts.append(f'<a class="video-link" href="{_esc(video_url)}" target="_blank">▶ 播放视频</a>')
        parts.append('</div>')

    # Text
    parts.append(f'<div class="text">{_esc(text)}</div>')

    # Images
    if local_images:
        parts.append('<div class="gallery">')
        for img_rel in local_images:
            parts.append(f'<img src="{_esc(img_rel)}" loading="lazy">')
        parts.append('</div>')
    elif not download_media and all_image_urls:
        parts.append('<div class="gallery">')
        for url in all_image_urls:
            parts.append(f'<img src="{_esc(url)}" loading="lazy">')
        parts.append('</div>')

    # Repost
    if retweeted:
        rs = retweeted
        rs_user = rs.get("user", {})
        rs_name = rs_user.get("screen_name", "未知用户")
        rs_created = rs.get("created_at", "")
        rs_likes = rs.get("attitudes_count", 0)
        rs_comments = rs.get("comments_count", 0)
        rs_reposts = rs.get("reposts_count", 0)
        rs_text = rs.get("text_raw", rs.get("text", ""))

        parts.append('<div class="repost">')
        parts.append(f'<h2>📎 转载自 @{_esc(rs_name)}</h2>')
        meta_items = []
        if rs_created:
            meta_items.append(f'<span>📅 {_esc(rs_created)}</span>')
        if rs_likes:
            meta_items.append(f'<span>👍 {_fmt(rs_likes)}</span>')
        if rs_comments:
            meta_items.append(f'<span>💬 {_fmt(rs_comments)}</span>')
        if rs_reposts:
            meta_items.append(f'<span>🔄 {_fmt(rs_reposts)}</span>')
        if meta_items:
            parts.append(f'<div class="meta">{"".join(meta_items)}</div>')

        # Repost video
        rs_video_url = extract_video_url(rs)
        if rs_video_url:
            rs_v_local = "repost_video.mp4"
            if download_media:
                parts.append(f'<video controls preload="metadata" src="{rs_v_local}" style="width:100%;border-radius:6px;background:#000;margin:8px 0"></video>')
            else:
                parts.append(f'<a class="video-link" href="{_esc(rs_video_url)}" target="_blank">▶ 播放视频</a>')

        parts.append(f'<div class="text">{_esc(sanitize_text_md(rs_text))}</div>')

        # Repost images
        rs_img_urls = extract_image_urls(rs)
        if rs_img_urls:
            rs_local = []
            if download_media:
                # check what was actually downloaded
                for j, _ in enumerate(rs_img_urls):
                    # just list images/repost/* files
                    pass
                # We don't have the list here, use glob pattern
                parts.append('<div class="gallery">')
                # Use the same pattern as md: images/repost/001.jpg etc.
                for j in range(len(rs_img_urls)):
                    ext = ".jpg"
                    parts.append(f'<img src="images/repost/{j+1:03d}{ext}" loading="lazy" onerror="this.style.display=\'none\'">')
                parts.append('</div>')
            else:
                parts.append('<div class="gallery">')
                for url in rs_img_urls:
                    parts.append(f'<img src="{_esc(url)}" loading="lazy">')
                parts.append('</div>')

        rs_mid = rs.get("mid", "")
        rs_uid = rs_user.get("id", "")
        footer = f"转载原帖 ID: {rs_mid}"
        if rs_uid:
            footer += f" | 原作者 UID: {rs_uid}"
        parts.append(f'<div style="font-size:11px;color:#bbb;margin-top:8px">{_esc(footer)}</div>')
        parts.append('</div>')  # .repost

    # Footer
    footer_text = f"ID: {mid}"
    if source:
        footer_text += f" | 来源: {sanitize_text(source)}"
    parts.append(f'<div class="footer">{_esc(footer_text)}</div>')
    parts.append('</div></body></html>')

    return "\n".join(parts)


def _esc(s):
    """HTML escape."""
    if not s:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _fmt(n):
    """Format large numbers: 1047894 → 104.8万"""
    if not n:
        return "0"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


# ============================================================
# Main Pipeline
# ============================================================

def process_user(url_or_uid: str, output_dir: str, cookie_path: str,
                 max_pages: int = 0, skip_existing: bool = True,
                 download_media: bool = True):
    """Main pipeline: resolve user → fetch all posts → download media."""

    # Load cookies
    cookie_str = load_cookies(cookie_path)
    client = WeiboClient(cookie_str, cookie_path=cookie_path)

    # Resolve UID
    if url_or_uid.isdigit():
        uid = url_or_uid
    else:
        uid = resolve_uid(url_or_uid, client.headers)
    log.info("UID: %s", uid)

    # Get user info
    log.info("Fetching user profile...")
    user = client.get_user_info(uid)
    screen_name = user.get("screen_name", f"user_{uid}")
    followers = user.get("followers_count", 0)
    statuses = user.get("statuses_count", 0)
    log.info("%s | 粉丝: %s | 微博: %s", screen_name, followers, statuses)

    # Prepare output directory
    out_dir = Path(output_dir) / safe_filename(screen_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("Output: %s", out_dir)

    # Fetch all posts
    log.info("Fetching all posts (max_pages=%s)...", max_pages or 'unlimited')
    posts = client.get_all_posts(uid, max_pages=max_pages)
    log.info("Total posts fetched: %d", len(posts))

    if statuses and len(posts) < statuses:
        gap = statuses - len(posts)
        log.info("用户资料显示 %s 条微博，API 返回 %d 条", statuses, len(posts))
        log.info("差距 %s 条可能是: 已删除/仅自己可见/审核中/置顶重复", gap)

    if not posts:
        log.warning("No posts found. Cookie may be expired.")
        return

    # ---- Incremental: load done-mids set + find max seq ----
    done_mids_path = out_dir / "_done_mids.json"
    done_mids = set()
    start_seq = 0
    if skip_existing:
        # Load done-mids set
        if done_mids_path.exists():
            try:
                done_mids = set(json.loads(done_mids_path.read_text(encoding="utf-8")))
                if done_mids:
                    log.info("已有 %d 条完成记录，将增量追加", len(done_mids))
            except Exception:
                pass
        # Scan existing dirs for max sequence number
        for d in out_dir.iterdir():
            if d.is_dir() and not d.name.startswith("_"):
                m = re.match(r"^(\d{3,})", d.name)
                if m:
                    seq = int(m.group(1))
                    if seq > start_seq:
                        start_seq = seq
        # Also collect mids from existing _done files (legacy compat)
        if not done_mids:
            for d in out_dir.iterdir():
                if d.is_dir() and not d.name.startswith("_"):
                    md_path = d / "index.md"
                    if md_path.exists():
                        mid = _extract_mid_from_md(md_path.read_text(encoding="utf-8"))
                        if mid:
                            done_mids.add(mid)
            if done_mids:
                log.info("从已有目录提取 %d 个 mid（兼容旧格式）", len(done_mids))

    # Load existing index for reference
    index_path = out_dir / "_posts_index.json"

    index = {
        "uid": uid,
        "screen_name": screen_name,
        "fetched_at": datetime.now().isoformat(),
        "total_posts": len(posts),
        "posts": [],
    }
    # Preserve old index posts if exists
    if index_path.exists():
        try:
            old_index = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(old_index.get("posts"), list):
                index["posts"] = old_index["posts"]
        except Exception:
            pass

    def save_index():
        """Save index to disk (atomic)."""
        tmp = str(index_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        os.replace(tmp, index_path)

    def save_done_mids():
        """Save done-mids set to disk (atomic)."""
        tmp = str(done_mids_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(done_mids), f, ensure_ascii=False)
        os.replace(tmp, done_mids_path)

    # Stats
    stats = {"text_only": 0, "with_images": 0, "with_video": 0,
             "images_downloaded": 0, "videos_downloaded": 0, "skipped": 0}

    log.info("Processing %d posts (start_seq=%d)...", len(posts), start_seq)
    seq = start_seq  # will be incremented per new post
    for i, post in enumerate(posts):
        mid = str(post.get("mid", post.get("id", f"unknown_{i}")))
        created = post.get("created_at", "")
        text_raw = post.get("text_raw", post.get("text", ""))
        text_clean = sanitize_text(text_raw)[:100]

        # ---- Skip if already done (by mid, not by dir name) ----
        if skip_existing and mid in done_mids:
            stats["skipped"] += 1
            continue

        # Parse date for sorting
        try:
            dt = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")
            date_str = dt.strftime("%Y%m%d_%H%M%S")
        except Exception:
            dt = None
            date_str = f"unknown_{i:04d}"

        # Post directory: 序号_日期_简短标题
        seq += 1
        title_brief = sanitize_filename(sanitize_text(text_raw).split("\n")[0][:20]) or f"post_{mid}"
        if dt:
            post_dir_name = f"{seq:03d}_{dt.strftime('%Y%m%d')}_{title_brief}"
        else:
            post_dir_name = f"{seq:03d}_{title_brief}"
        post_dir = out_dir / post_dir_name

        # Classify post
        video_url = extract_video_url(post)
        image_urls = extract_image_urls(post)
        has_video = bool(video_url)
        has_images = bool(image_urls)

        if has_video:
            stats["with_video"] += 1
        elif has_images:
            stats["with_images"] += 1
        else:
            stats["text_only"] += 1

        # Index entry
        entry = {
            "mid": mid,
            "created_at": created,
            "text": text_clean,
            "has_video": has_video,
            "has_images": has_images,
            "image_count": len(image_urls),
        }

        # ---- Build markdown content (图文一体) ----
        md_lines = []

        # Title = first line of text or date
        title_text = sanitize_text(text_raw).split("\n")[0][:60] or f"微博 {mid}"
        md_lines.append(f"# {title_text}")
        md_lines.append("")

        # Metadata line
        likes = post.get("attitudes_count", 0)
        comments_count = post.get("comments_count", 0)
        reposts_count = post.get("reposts_count", 0)
        meta_parts = [f"📅 {created}"]
        if likes:
            meta_parts.append(f"👍 {likes}")
        if comments_count:
            meta_parts.append(f"💬 {comments_count}")
        if reposts_count:
            meta_parts.append(f"🔄 {reposts_count}")
        md_lines.append(" | ".join(meta_parts))
        md_lines.append("")

        # Download & embed video
        if has_video:
            md_lines.append("## 视频")
            md_lines.append("")
            if download_media:
                post_dir.mkdir(parents=True, exist_ok=True)
                video_path = post_dir / "video.mp4"
                if not video_path.exists():
                    if download_file(video_url, str(video_path), cookie_str=client.cookie_str):
                        stats["videos_downloaded"] += 1
                        sz = video_path.stat().st_size
                        entry["video_file"] = "video.mp4"
                        entry["video_size_mb"] = round(sz / 1024 / 1024, 1)
                if video_path.exists():
                    md_lines.append(f"[▶ 播放视频](video.mp4) ({entry.get('video_size_mb', '?')} MB)")
                else:
                    md_lines.append(f"[▶ 视频链接]({video_url}) (下载失败)")
            else:
                md_lines.append(f"[▶ 视频链接]({video_url})")
            md_lines.append("")

        # Full text — always fetch from detail API to avoid truncation
        # mymblog API truncates text_raw even when isLongText=False
        md_lines.append("## 正文")
        md_lines.append("")
        full_text = client.get_full_text(mid, text_raw)
        md_lines.append(full_text)
        md_lines.append("")

        # Download & embed images
        downloaded_images = []
        if has_images:
            downloaded_images = []
            if download_media:
                post_dir.mkdir(parents=True, exist_ok=True)
                img_dir = post_dir / "images"
                img_dir.mkdir(exist_ok=True)
                for j, img_url in enumerate(image_urls):
                    ext = ".jpg"
                    if ".png" in img_url:
                        ext = ".png"
                    elif ".gif" in img_url:
                        ext = ".gif"
                    elif ".webp" in img_url:
                        ext = ".webp"
                    img_path = img_dir / f"{j+1:03d}{ext}"
                    if img_path.exists() or download_file(img_url, str(img_path), cookie_str=client.cookie_str):
                        if img_path.exists():
                            downloaded_images.append(f"images/{j+1:03d}{ext}")
                            stats["images_downloaded"] += 1

            if downloaded_images or not download_media:
                md_lines.append("## 图片")
                md_lines.append("")
                if download_media:
                    for img_rel in downloaded_images:
                        md_lines.append(f"![图片]({img_rel})")
                        md_lines.append("")
                else:
                    for j, img_url in enumerate(image_urls):
                        md_lines.append(f"![图片{j+1}]({img_url})")
                        md_lines.append("")
        elif not has_images:
            pass  # downloaded_images stays []

        # ---- 转载原帖 ----
        retweeted = post.get("retweeted_status")
        if retweeted:
            rs_user = retweeted.get("user", {})
            rs_screen_name = rs_user.get("screen_name", "未知用户")
            rs_uid = rs_user.get("id", "")
            rs_mid = retweeted.get("mid", "")
            rs_text_raw = retweeted.get("text_raw", retweeted.get("text", ""))
            # Always fetch full text for repost too (avoid truncation)
            rs_text_clean = client.get_full_text(str(rs_mid), rs_text_raw)
            rs_likes = retweeted.get("attitudes_count", 0)
            rs_comments = retweeted.get("comments_count", 0)
            rs_reposts = retweeted.get("reposts_count", 0)
            rs_created = retweeted.get("created_at", "")

            md_lines.append("")
            md_lines.append("---")
            md_lines.append("")
            md_lines.append(f"## 📎 转载自 @{rs_screen_name}")
            md_lines.append("")

            # 转载帖元数据
            rs_meta = []
            if rs_created:
                rs_meta.append(f"📅 {rs_created}")
            if rs_likes:
                rs_meta.append(f"👍 {rs_likes}")
            if rs_comments:
                rs_meta.append(f"💬 {rs_comments}")
            if rs_reposts:
                rs_meta.append(f"🔄 {rs_reposts}")
            if rs_meta:
                md_lines.append(" | ".join(rs_meta))
                md_lines.append("")

            # 转载帖视频
            rs_video_url = extract_video_url(retweeted)
            if rs_video_url:
                md_lines.append("### 视频")
                md_lines.append("")
                if download_media:
                    post_dir.mkdir(parents=True, exist_ok=True)
                    rs_video_path = post_dir / "repost_video.mp4"
                    if not rs_video_path.exists():
                        download_file(rs_video_url, str(rs_video_path), cookie_str=client.cookie_str)
                    if rs_video_path.exists():
                        rs_sz = rs_video_path.stat().st_size
                        rs_sz_mb = round(rs_sz / 1024 / 1024, 1)
                        stats["videos_downloaded"] += 1
                        md_lines.append(f"[▶ 播放视频](repost_video.mp4) ({rs_sz_mb} MB)")
                    else:
                        md_lines.append(f"[▶ 视频链接]({rs_video_url}) (下载失败)")
                else:
                    md_lines.append(f"[▶ 视频链接]({rs_video_url})")
                md_lines.append("")

            # 转载帖正文
            md_lines.append("### 正文")
            md_lines.append("")
            md_lines.append(rs_text_clean)
            md_lines.append("")

            # 转载帖图片
            rs_image_urls = extract_image_urls(retweeted)
            if rs_image_urls:
                rs_downloaded = []
                if download_media:
                    post_dir.mkdir(parents=True, exist_ok=True)
                    rs_img_dir = post_dir / "images" / "repost"
                    rs_img_dir.mkdir(parents=True, exist_ok=True)
                    for j, img_url in enumerate(rs_image_urls):
                        ext = ".jpg"
                        if ".png" in img_url:
                            ext = ".png"
                        elif ".gif" in img_url:
                            ext = ".gif"
                        elif ".webp" in img_url:
                            ext = ".webp"
                        img_path = rs_img_dir / f"{j+1:03d}{ext}"
                        if img_path.exists() or download_file(img_url, str(img_path), cookie_str=client.cookie_str):
                            if img_path.exists():
                                rs_downloaded.append(f"images/repost/{j+1:03d}{ext}")
                                stats["images_downloaded"] += 1

                if rs_downloaded or not download_media:
                    md_lines.append("### 图片")
                    md_lines.append("")
                    if download_media:
                        for img_rel in rs_downloaded:
                            md_lines.append(f"![转载图片]({img_rel})")
                            md_lines.append("")
                    else:
                        for j, img_url in enumerate(rs_image_urls):
                            md_lines.append(f"![转载图片{j+1}]({img_url})")
                            md_lines.append("")

            # 转载帖 footer
            md_lines.append(f"> 转载原帖 ID: {rs_mid}")
            if rs_uid:
                md_lines[-1] += f" | 原作者 UID: {rs_uid}"

            entry["retweeted_from"] = {
                "screen_name": rs_screen_name,
                "uid": str(rs_uid),
                "mid": str(rs_mid),
            }

        # Footer
        source = post.get("source", "")
        md_lines.append("---")
        footer = f"> ID: {mid}"
        if source:
            footer += f" | 来源: {sanitize_text(source)}"
        md_lines.append(footer)

        # Write markdown + html
        post_dir.mkdir(parents=True, exist_ok=True)
        md_path = post_dir / "index.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

        # ---- Build index.html ----
        html = _build_html(title_text, created, likes, comments_count,
                           reposts_count, full_text,
                           has_video, video_url if has_video else None,
                           entry.get("video_size_mb"),
                           downloaded_images if has_images else [],
                           image_urls if has_images else [],
                           retweeted, download_media,
                           mid, source)
        html_path = post_dir / "index.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        # Mark as done (store mid for future dedup)
        done_marker = post_dir / "_done"
        done_marker.write_text(json.dumps({"mid": mid}, ensure_ascii=False), encoding="utf-8")
        done_mids.add(mid)

        index["posts"].append(entry)

        # Save index every 10 posts (crash-safe)
        if (i + 1) % 10 == 0:
            save_index()
            save_done_mids()

        # Progress
        media_info = ""
        if has_video:
            media_info = "🎬"
        elif has_images:
            media_info = f"🖼×{len(image_urls)}"
        else:
            media_info = "📝"
        log.info("[%d/%d] %s %s %s...", i+1, len(posts), date_str, media_info, text_clean[:40])

        # Small delay between downloads
        if download_media and (has_video or has_images):
            time.sleep(random.uniform(0.5, 1.5))

    # Final save
    save_index()
    save_done_mids()

    # Print summary
    log.info("%s", "=" * 50)
    log.info("%s 微博爬取完成", screen_name)
    log.info("总帖子数: %d", len(posts))
    log.info("纯文字: %s", stats['text_only'])
    log.info("含图片: %s (下载 %s 张)", stats['with_images'], stats['images_downloaded'])
    log.info("含视频: %s (下载 %s 个)", stats['with_video'], stats['videos_downloaded'])
    log.info("跳过已存在: %s", stats['skipped'])
    log.info("输出目录: %s", out_dir)
    log.info("索引文件: %s", index_path)
    log.info("%s", "=" * 50)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="微博用户微博爬取下载器 / 搜索",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 下载用户微博
  %(prog)s https://weibo.com/u/1669879400 -o D:\\weibo
  %(prog)s --uid 1669879400 -o D:\\weibo --max-pages 10
  %(prog)s https://weibo.com/u/1669879400 -o D:\\weibo --cookie my_cookies.txt

  # 搜索微博
  %(prog)s search "教育方法" --max 20 --cookie my_cookies.txt
  %(prog)s search "科普知识" --max 20 --cookie my_cookies.txt -o candidates.json
        """,
    )
    sub = parser.add_subparsers(dest="cmd")

    # download 子命令（默认行为：下载用户微博）
    dl = sub.add_parser("download", help="下载用户微博")
    dl.add_argument("url", help="微博用户主页链接")
    dl.add_argument("--uid", help="直接指定用户 UID")
    dl.add_argument("-o", "--output", default=".", help="输出目录 (默认: 当前目录)")
    dl.add_argument("--cookie", default="weibo_cookies.txt", help="Cookie 文件路径 (默认: weibo_cookies.txt)")
    dl.add_argument("--max-pages", type=int, default=0, help="最大翻页数 (0=全部)")
    dl.add_argument("--no-media", action="store_true", help="不下载媒体文件，仅保存索引")
    dl.add_argument("--no-skip", action="store_true", help="不跳过已下载的帖子")
    dl.add_argument("--cdp", default=None, help="CDP URL（可选，本平台通常不需要）")

    # search 子命令
    sp = sub.add_parser("search", help="搜索微博内容")
    sp.add_argument("keyword", help="搜索关键词")
    sp.add_argument("--max", type=int, default=20, help="最大返回数（默认 20）")
    sp.add_argument("--cookie", default=None, help="Cookie 文件路径；优先使用 WEIBO_COOKIE/WEIBO_COOKIE_FILE")
    sp.add_argument("-o", "--output", default=None, help="输出 candidate JSON 文件路径")

    # 兼容旧用法：无子命令时走 download 逻辑
    parser.add_argument("url", nargs="?", help="微博用户主页链接（兼容旧用法，建议使用 download 子命令）")
    parser.add_argument("--uid", help="直接指定用户 UID")
    parser.add_argument("-o", "--output", default=".")
    parser.add_argument("--cookie", default="weibo_cookies.txt")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--no-media", action="store_true")
    parser.add_argument("--no-skip", action="store_true")

    args = parser.parse_args()

    if args.cmd == "search":
        # 搜索模式
        cookie_str = load_cookies(args.cookie)
        log.info("搜索微博: '%s' (max=%d)", args.keyword, args.max)
        candidates = search_weibo(args.keyword, cookie_str, max_results=args.max)
        if candidates:
            log.info("搜索到 %d 条微博", len(candidates))
            output_candidates(candidates, args.keyword, args.output)
            if not args.output:
                for i, c in enumerate(candidates, 1):
                    log.info("[%d] [%s] %s...", i, c.get('provider', '?'), c['title'][:40])
                    log.info("    %s", c['source_url'])
        else:
            log.warning("未搜索到结果（Cookie 可能过期或无匹配内容）")
        return

    # download 模式（子命令或兼容旧用法）
    target = args.uid or args.url
    if not target:
        parser.error("请提供微博用户主页链接或 --uid，或使用 search 子命令")

    process_user(
        url_or_uid=target,
        output_dir=args.output,
        cookie_path=args.cookie,
        max_pages=args.max_pages,
        skip_existing=not args.no_skip,
        download_media=not args.no_media,
    )


if __name__ == "__main__":
    main()
