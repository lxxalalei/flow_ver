"""SmartEdu (国家中小学智慧教育平台) resource downloader.

Uses the public CDN detail API to resolve file URLs, then downloads
PDFs directly and videos via ffmpeg (m3u8 → mp4).

Reference: tchMaterial-parser (happycola233) and smartedu-dl-go (hantang).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse
from urllib.request import Request

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..sessions import SessionStore
from ..policy import PolicyError, ensure_within_root
from .http_client import urlopen_with_fallback


CDN_BASE = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2"
CDN_SPECIAL = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrs"
STORAGE_PREFIX = "https://r1-ndr-private.ykt.cbern.com.cn"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _resolve_content(url: str) -> tuple[str, str]:
    """Extract content_id and content_type from a smartedu URL."""
    params = parse_qs(urlparse(url, "https").query)

    if "contentId" in params:
        content_id = params["contentId"][0]
        content_type = params.get("contentType", ["assets_document"])[0]
    elif "activityId" in params:
        content_id = params["activityId"][0]
        content_type = "national_lesson"
    elif "courseId" in params:
        content_id = params["courseId"][0]
        content_type = "quality_course"
    elif "resourceId" in params:
        content_id = params["resourceId"][0]
        content_type = params.get("resourceType", ["prepare_sub_type"])[0]
    else:
        raise DomainError("DOWNLOAD_FAILED", f"无法解析智慧教育 URL: {url}")

    return content_id, content_type


def _detail_api_url(content_id: str, content_type: str, url: str) -> str:
    """Build the CDN detail API URL based on content type."""
    if "/tchMaterial/" in url and content_type == "assets_document":
        return f"{CDN_BASE}/resources/tch_material/details/{content_id}.json"
    if content_type == "national_lesson":
        return f"{CDN_BASE}/national_lesson/resources/details/{content_id}.json"
    if content_type == "quality_course":
        return f"{CDN_BASE}/resources/{content_id}.json"
    if content_type == "prepare_sub_type":
        return f"{CDN_BASE}/prepare_sub_type/resources/details/{content_id}.json"
    if content_type == "thematic_course":
        return f"{CDN_SPECIAL}/special_edu/thematic_course/{content_id}/resources/list.json"
    # Generic fallback
    return f"{CDN_BASE}/{content_type}/resources/details/{content_id}.json"


def _fix_storage_url(raw: str) -> str:
    """Convert internal storage path to public CDN URL."""
    if not raw:
        return ""
    if raw.startswith("http"):
        url = raw
    else:
        url = raw.replace("cs_path:${ref-path}", STORAGE_PREFIX)
    # Percent-encode the path to handle Chinese characters and spaces.
    parsed = urlparse(url)
    return urlunparse((
        parsed.scheme, parsed.netloc,
        quote(parsed.path, safe="/"),
        parsed.params, parsed.query, parsed.fragment,
    ))


def _find_files(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan detail JSON for all downloadable files.

    Returns list of {url, format, size, title, type} dicts.
    """
    results: list[dict[str, Any]] = []

    def _extract_ti_items(obj: dict[str, Any], label: str = "") -> None:
        for item in obj.get("ti_items") or []:
            if item.get("ti_format") == "folder":
                continue
            flag = str(item.get("ti_file_flag") or "")
            fmt = str(item.get("ti_format") or "")
            # Accept source files, pdfs, and known formats.
            if not (item.get("ti_is_source_file") or flag in (
                "source", "pdf", "ppt", "pptx", "doc", "docx",
                "href", "href-720p-m3u8", "href-480p-m3u8", "href-360p-m3u8",
            )):
                continue
            raw_url = item.get("ti_storage") or ""
            if not raw_url and item.get("ti_storages"):
                raw_url = item["ti_storages"][0]
            url = _fix_storage_url(raw_url)
            if not url:
                continue
            title_data = obj.get("global_title") or obj.get("title") or label
            if isinstance(title_data, dict):
                title_data = title_data.get("zh-CN") or title_data.get("en") or label
            results.append({
                "url": url,
                "format": fmt,
                "size": int(item.get("ti_size") or 0),
                "title": str(title_data)[:120],
                "flag": flag,
            })

    # Direct files
    _extract_ti_items(data)

    # Sub-resources in relations
    for rel_key, rel_items in (data.get("relations") or {}).items():
        if not isinstance(rel_items, list):
            continue
        for item in rel_items:
            if isinstance(item, dict):
                _extract_ti_items(item, label=rel_key)

    return results


def _pick_best_file(files: list[dict[str, Any]], content_type: str = "", allow_video: bool = True) -> dict[str, Any] | None:
    """Pick the most valuable downloadable file.

    For courses (national_lesson, quality_course): video first, then PDF.
    For textbooks/documents: PDF first.
    When *allow_video* is False, skip m3u8/mp4 (e.g. no auth token).
    """
    if not files:
        return None

    # Find best m3u8 (prefer 720p).
    best_m3u8 = None
    if allow_video:
        for f in files:
            if f["format"] == "m3u8" and "720p" in f.get("flag", ""):
                best_m3u8 = f
                break
        if not best_m3u8:
            for f in files:
                if f["format"] == "m3u8":
                    best_m3u8 = f
                    break

    is_course = content_type in ("national_lesson", "quality_course", "thematic_course")

    if is_course and allow_video:
        priority = [("m3u8", best_m3u8), ("mp4", None), ("pdf", None), ("mp3", None)]
    else:
        priority = [("pdf", None), ("mp4", None) if allow_video else ("_skip", None),
                    ("epub", None), ("m3u8", best_m3u8), ("mp3", None)]

    for fmt, specific in priority:
        if specific:
            return specific
        if fmt == "_skip":
            continue
        for f in files:
            if f["format"] == fmt and (fmt != "pdf" or f["size"] > 1024):
                return f

    return files[0]


def _smartedu_headers(token: str = "") -> dict[str, str]:
    """Build auth headers for smartedu CDN requests.

    Uses only x-nd-auth header (matching smartedu-dl-go). Without a token,
    uses dummy auth that works for public resources.
    """
    t = token or "0"
    return {
        "User-Agent": UA,
        "Origin": "https://basic.smartedu.cn",
        "Referer": "https://basic.smartedu.cn/",
        "x-nd-auth": f'MAC id="{t}",nonce="0",mac="0"',
    }


def _stream_download(
    url: str, dest: Path, cancel_event: threading.Event, max_bytes: int,
    token: str = "",
) -> int:
    """Download a direct file (PDF, MP3, etc.).

    Tries x-nd-auth header first, then ?accessToken= query param as fallback.
    """
    request = Request(url, headers=_smartedu_headers())
    written = 0
    with urlopen_with_fallback(request, timeout=120) as response:
        with dest.open("wb") as f:
            while True:
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                chunk = response.read(min(64 * 1024, max_bytes - written + 1))
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise DomainError("DOWNLOAD_TOO_LARGE", "文件超过大小上限")
                f.write(chunk)
    return written


def _get_decryption_key(key_url: str, token: str) -> bytes:
    """Obtain the AES decryption key for video segments.

    Implements the SmartEdu key derivation algorithm (ported from
    smartedu-dl-go):
      1. GET {keyURL}/signs → nonce
      2. sign = MD5(nonce + keyID)[:16]
      3. GET {keyURL}?nonce={nonce}&sign={sign} → base64 encrypted key
      4. AES-ECB decrypt with sign as key → raw decryption key
    """
    headers = _smartedu_headers(token)

    # Extract keyID from URL (last path segment).
    key_id = key_url.rstrip("/").rsplit("/", 1)[-1]

    # 1. Get nonce.
    signs_url = f"{key_url}/signs"
    req = Request(signs_url, headers=headers)
    with urlopen_with_fallback(req, timeout=15) as resp:
        signs_data = json.loads(resp.read().decode("utf-8", "replace"))
    nonce = signs_data.get("nonce")
    if not nonce:
        raise DomainError("DOWNLOAD_FAILED", "密钥服务未返回 nonce")

    # 2. Compute sign = MD5(nonce + keyID)[:16].
    sign = hashlib.md5(f"{nonce}{key_id}".encode()).hexdigest()[:16]

    # 3. Get encrypted key.
    key_req_url = f"{key_url}?nonce={nonce}&sign={sign}"
    req2 = Request(key_req_url, headers=headers)
    with urlopen_with_fallback(req2, timeout=15) as resp2:
        key_data = json.loads(resp2.read().decode("utf-8", "replace"))
    encrypted_key_b64 = key_data.get("key")
    if not encrypted_key_b64:
        raise DomainError("DOWNLOAD_FAILED", "密钥服务未返回 key")

    # 4. AES-ECB decrypt.
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    encrypted_key = base64.b64decode(encrypted_key_b64)
    cipher = AES.new(sign.encode()[:16], AES.MODE_ECB)
    return unpad(cipher.decrypt(encrypted_key), 16)


def _decrypt_segment(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-CBC decrypt a video segment."""
    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(data)
    # PKCS7 unpad
    pad_len = decrypted[-1]
    if 0 < pad_len <= 16:
        decrypted = decrypted[:-pad_len]
    return decrypted


def _download_m3u8(
    url: str, dest: Path, cancel_event: threading.Event,
    token: str = "",
) -> int:
    """Download HLS video: parse m3u8, download segments, decrypt, merge.

    No ffmpeg needed — implements SmartEdu's custom key derivation and
    AES-CBC segment decryption in pure Python (requires pycryptodome).
    """
    from urllib.parse import urljoin

    # 1. Download m3u8.
    full_url = f"{url}?accessToken={token}" if token and "?" not in url else url
    request = Request(full_url, headers={
        "User-Agent": UA,
        "Referer": "https://basic.smartedu.cn/",
    })
    with urlopen_with_fallback(request, timeout=20) as resp:
        m3u8_text = resp.read().decode("utf-8", "replace")

    # 2. Parse m3u8: extract key info and segment URLs.
    base = url.rsplit("/", 1)[0] + "/"
    key_url = ""
    iv = b"\x00" * 16  # Default IV (IV=0 in m3u8)
    segments: list[str] = []

    for line in m3u8_text.split("\n"):
        line = line.strip()
        if line.startswith("#EXT-X-KEY:"):
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                key_url = uri_match.group(1)
            iv_match = re.search(r"IV=0x([0-9a-fA-F]+)", line)
            if iv_match:
                iv_hex = iv_match.group(1)
                iv = bytes.fromhex(iv_hex.zfill(32))
        elif line and not line.startswith("#"):
            seg_url = urljoin(base, line)
            segments.append(seg_url)

    if not segments:
        raise DomainError("DOWNLOAD_FAILED", "m3u8 无分段")

    # 3. Get decryption key (if encrypted).
    key = None
    if key_url:
        key = _get_decryption_key(key_url, token)

    # 4. Download + decrypt + merge segments.
    seg_headers = _smartedu_headers(token)

    try:
        with dest.open("wb") as out:
            for i, seg_url in enumerate(segments):
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")

                req = Request(seg_url, headers=seg_headers)
                with urlopen_with_fallback(req, timeout=60) as resp:
                    seg_data = resp.read()

                if key:
                    seg_data = _decrypt_segment(seg_data, key, iv)

                out.write(seg_data)

        return dest.stat().st_size
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError("DOWNLOAD_FAILED", f"视频分段下载失败: {type(exc).__name__}: {exc}", retryable=True)


class SmartEduDownloader:
    """Download resources from SmartEdu via the public CDN detail API.

    Handles textbooks (PDF), course videos (m3u8→mp4), documents, and audio.
    Access token is optional — most resources are publicly downloadable.
    """

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.settings = settings

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        url = str(resource["source_url"])
        title = str(resource.get("title") or "smartedu_resource")

        # 1. Resolve content_id and type
        content_id, content_type = _resolve_content(url)

        # Get optional access token from SessionStore
        session_data = self.session_store.get_session_data("smartedu")
        token = ""
        if session_data:
            tokens = session_data.get("tokens") or {}
            raw_token = tokens.get("accessToken") or ""
            if raw_token:
                token = raw_token[7:] if raw_token.lower().startswith("bearer ") else raw_token

        # 2. Get detail JSON from CDN
        api_url = _detail_api_url(content_id, content_type, url)
        request = Request(api_url, headers=_smartedu_headers(token))
        try:
            with urlopen_with_fallback(request, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            raise DomainError("DOWNLOAD_FAILED", f"获取资源详情失败: {type(exc).__name__}: {exc}", retryable=True)

        # 3. Find downloadable files
        files = _find_files(data)

        # 3b. For textbooks, also check for companion audio (e.g., English listening).
        if content_type == "assets_document":
            audio_api = f"{CDN_SPECIAL}/resources/{content_id}/relation_audios.json"
            try:
                audio_req = Request(audio_api, headers=_smartedu_headers(token))
                with urlopen_with_fallback(audio_req, timeout=10) as audio_resp:
                    audios = json.loads(audio_resp.read().decode("utf-8", "replace"))
                if isinstance(audios, list):
                    for audio in audios:
                        for item in (audio.get("ti_items") or []):
                            if item.get("ti_format") != "mp3":
                                continue
                            raw_url = item.get("ti_storage") or ""
                            if not raw_url and item.get("ti_storages"):
                                raw_url = item["ti_storages"][0]
                            url = _fix_storage_url(raw_url)
                            if url:
                                title_data = audio.get("global_title") or audio.get("title") or ""
                                if isinstance(title_data, dict):
                                    title_data = title_data.get("zh-CN") or str(title_data)
                                files.append({
                                    "url": url,
                                    "format": "mp3",
                                    "size": int(item.get("ti_size") or 0),
                                    "title": str(title_data)[:120],
                                    "flag": item.get("ti_file_flag", "href"),
                                })
            except Exception:
                pass  # Audio companions are optional
        if not files:
            raise DomainError("DOWNLOAD_FAILED", "该资源无可下载文件", retryable=False)

        # 4. Group files by sub-resource type and pick best from each group.
        # A course typically has: video (m3u8), learning_task (pdf),
        # after_class_exercise (pdf).  Download ALL of them.
        has_token = bool(token)
        is_course = content_type in ("national_lesson", "quality_course", "thematic_course")

        # Group by file format — each format = one sub-resource to download.
        groups: dict[str, list[dict[str, Any]]] = {}
        for f in files:
            fmt = f["format"]
            # Skip thumbnails and non-content files.
            if f.get("flag", "").startswith("thumbnail"):
                continue
            groups.setdefault(fmt, []).append(f)

        # Pick best file from each group.
        ext_map = {"pdf": ".pdf", "mp4": ".mp4", "m3u8": ".mp4", "mp3": ".mp3",
                    "epub": ".epub", "doc": ".doc", "docx": ".docx", "ppt": ".ppt", "pptx": ".pptx"}

        to_download: list[dict[str, Any]] = []
        if is_course and len(groups) > 1:
            # Multi-file course: download best from each format group.
            for fmt, group_files in groups.items():
                if fmt == "m3u8":
                    if not has_token:
                        continue  # Can't download video without token
                    best_in_group = None
                    for f in group_files:
                        if "720p" in f.get("flag", ""):
                            best_in_group = f
                            break
                    if not best_in_group:
                        best_in_group = group_files[0]
                    to_download.append(best_in_group)
                elif fmt in ("pdf", "mp3", "epub", "doc", "docx", "ppt", "pptx"):
                    # Pick largest PDF/doc (likely the actual content, not thumbnail).
                    content_files = [f for f in group_files if f.get("size", 0) > 1024]
                    if content_files:
                        to_download.append(max(content_files, key=lambda f: f["size"]))
        else:
            # Single resource (textbook, etc.) — just pick the best file.
            best = _pick_best_file(files, content_type, allow_video=has_token)
            if best:
                to_download.append(best)

        if not to_download:
            # Fallback: try everything we have.
            to_download = [f for f in files if not f.get("flag", "").startswith("thumbnail")]

        if not to_download:
            raise DomainError("DOWNLOAD_FAILED", "未找到可下载文件", retryable=False)

        # 5. Download all selected files.
        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        results: list[DownloadResult] = []
        errors: list[str] = []

        for candidate in to_download:
            c_format = candidate["format"]
            c_url = candidate["url"]
            c_title = candidate.get("title") or title
            ext = ext_map.get(c_format, ".bin")
            safe_title = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", c_title).strip("-._")[:80] or "resource"
            filename = f"{safe_title}{ext}"
            destination = job_dir / filename
            ensure_within_root(destination, self.settings.jobs_dir)
            destination.unlink(missing_ok=True)

            try:
                if c_format == "m3u8":
                    byte_size = _download_m3u8(c_url, destination, cancel_event, token)
                    media_type = "video/mp4"
                else:
                    byte_size = _stream_download(c_url, destination, cancel_event, max_bytes, token)
                    media_type = {
                        ".pdf": "application/pdf", ".mp3": "audio/mpeg",
                        ".mp4": "video/mp4", ".epub": "application/epub+zip",
                    }.get(ext, "application/octet-stream")

                sha = hashlib.sha256()
                with destination.open("rb") as f:
                    for chunk in iter(lambda: f.read(64 * 1024), b""):
                        sha.update(chunk)

                results.append(DownloadResult(
                    destination, byte_size, media_type, sha.hexdigest(), filename,
                ))
            except DomainError as exc:
                destination.unlink(missing_ok=True)
                errors.append(f"{c_title}: {exc.message}")
                continue
            except Exception as exc:
                destination.unlink(missing_ok=True)
                errors.append(f"{c_title}: {type(exc).__name__}: {str(exc)[:80]}")
                continue

        if not results:
            raise DomainError("DOWNLOAD_FAILED", f"所有文件下载失败: {'; '.join(errors)}", retryable=False)

        return results
