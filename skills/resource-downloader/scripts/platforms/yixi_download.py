#!/usr/bin/env python3
"""Download one public Yixi video or its public transcript."""

from __future__ import annotations

import argparse
import email
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from http_client import ensure_public_http_url


BASE_URL = "https://www.yixi.tv"
PLAY_DETAIL_URL = BASE_URL + "/v3/api/h5/play_detail/"
DRAFT_URL = BASE_URL + "/v3/api/site/draft/"
AUTHCODE = "$yf&cpup8d%@s2h%"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_HLS_SEGMENT_BYTES = 64 * 1024 * 1024
MAX_HLS_SEGMENTS = 20_000


class DownloadError(RuntimeError):
    """A concise, user-facing download failure."""


@dataclass(frozen=True)
class SourceSpec:
    source_url: str
    kind: str
    video_id: str
    video_type: int
    album_id: str
    draft_type: int | None


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    level: str
    artifact_type: str
    title: str


def parse_source_url(source_url: str) -> SourceSpec:
    source_url = source_url.strip()
    parsed = urllib.parse.urlsplit(source_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or hostname not in {"yixi.tv", "www.yixi.tv"}:
        raise DownloadError("仅支持 www.yixi.tv 的公开详情页")
    if parsed.username or parsed.password:
        raise DownloadError("来源链接不得包含用户名或密码")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DownloadError("来源链接端口无效") from exc
    if port not in {None, 80, 443}:
        raise DownloadError("来源链接使用了不受支持的端口")

    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    path = parsed.path.rstrip("/")

    if path == "/speech/detail":
        video_id = _required_numeric_query(query, "id")
        raw_type = (query.get("videotype") or ["0"])[0]
        if raw_type not in {"", "0", "10"}:
            raise DownloadError("speech/detail 的 videotype 仅支持 0 或 10")
        return SourceSpec(source_url, "speech", video_id, int(raw_type or "0"), "0", 0)

    if path == "/record/detail":
        video_id = _required_numeric_query(query, "id")
        return SourceSpec(source_url, "record", video_id, 4, "0", 2)

    if path == "/zhiya/detail":
        album_id = _required_numeric_query(query, "id")
        video_id = _required_numeric_query(query, "episodeId")
        return SourceSpec(source_url, "zhiya", video_id, 2, album_id, None)

    raise DownloadError("链接不是 speech、record 或 zhiya 详情页")


def _required_numeric_query(query: dict[str, list[str]], name: str) -> str:
    value = (query.get(name) or [""])[0]
    if not re.fullmatch(r"[1-9]\d*", value):
        raise DownloadError(f"详情页缺少有效的 {name}")
    return value


def _headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": BASE_URL + "/",
        "authcode": AUTHCODE,
    }


def _read_url_bytes(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    accept: str = "*/*",
    referer: str = BASE_URL + "/",
) -> bytes:
    ensure_public_http_url(url)
    request = urllib.request.Request(
        url,
        headers={**_headers(accept), "Referer": referer},
    )
    try:
        opener = urllib.request.build_opener(_PublicRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length") if response.headers else None
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise DownloadError("响应超过允许的大小")
                except ValueError:
                    pass
            body = response.read(max_bytes + 1)
    except urllib.error.URLError as exc:
        if not _should_use_curl(exc):
            raise
        body = _curl_read_limited(request, timeout, max_bytes)
    if len(body) > max_bytes:
        raise DownloadError("响应超过允许的大小")
    return body


def _curl_read_limited(
    request: urllib.request.Request,
    timeout: float,
    max_bytes: int,
) -> bytes:
    current_url = request.full_url
    headers = request.header_items()
    for _ in range(6):
        _validate_media_url(current_url)
        with tempfile.TemporaryDirectory(prefix="yixi-read-") as directory:
            temp_dir = Path(directory)
            header_file = temp_dir / "headers.txt"
            body_file = temp_dir / "body.bin"
            command = [
                "curl.exe",
                "--ssl-no-revoke",
                "--silent",
                "--show-error",
                "--connect-timeout",
                str(max(1, int(timeout))),
                "--max-redirs",
                "0",
                "--max-filesize",
                str(max_bytes),
                "--dump-header",
                str(header_file),
                "--output",
                str(body_file),
            ]
            for name, value in headers:
                command.extend(["--header", f"{name}: {value}"])
            command.append(current_url)
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            raw_headers = header_file.read_text(encoding="iso-8859-1", errors="replace") if header_file.exists() else ""
            status, reason, response_headers = _parse_curl_headers(raw_headers)
            if status in {301, 302, 303, 307, 308} and response_headers.get("Location"):
                current_url = urllib.parse.urljoin(current_url, response_headers["Location"])
                continue
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip() or f"curl exit {completed.returncode}"
                raise DownloadError(f"响应读取失败：{detail}")
            if status >= 400:
                raise DownloadError(f"请求失败：HTTP {status} {reason}".strip())
            body = body_file.read_bytes() if body_file.exists() else b""
        if len(body) > max_bytes:
            raise DownloadError("响应超过允许的大小")
        return body
    raise DownloadError("请求重定向次数过多")


def request_api(url: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
    request_url = url + "?" + urllib.parse.urlencode(params)
    raw = _read_url_bytes(
        request_url,
        timeout=timeout,
        max_bytes=MAX_JSON_BYTES,
        accept="application/json, text/plain, */*",
    )
    try:
        document = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise DownloadError("一席公开接口返回了无效 JSON") from exc
    if not isinstance(document, dict):
        raise DownloadError("一席公开接口响应结构无效")
    if document.get("error_code") not in {0, "0"}:
        raise DownloadError(str(document.get("error_msg") or "一席公开接口请求失败"))
    data = document.get("data")
    if not isinstance(data, dict):
        raise DownloadError("一席公开接口缺少 data")
    return data


def fetch_play_metadata(spec: SourceSpec, timeout: float) -> dict[str, Any]:
    data = request_api(
        PLAY_DETAIL_URL,
        {
            "video_type": str(spec.video_type),
            "video_id": spec.video_id,
            "album_id": spec.album_id,
        },
        timeout,
    )
    base_items = data.get("base_items")
    if not isinstance(base_items, dict):
        raise DownloadError("一席播放接口缺少资源详情")
    return base_items


def _member_type(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("member_type")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def select_media_urls(metadata: dict[str, Any]) -> list[str]:
    entries = metadata.get("video_url")
    if not isinstance(entries, list):
        return []
    ranked: list[tuple[int, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("video_url") or "").strip()
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        if parsed.scheme == "http":
            url = urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
        try:
            rank = int(entry.get("type") or 0)
        except (TypeError, ValueError):
            rank = 0
        ranked.append((rank, url))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in ranked]


def _safe_filename(value: str, fallback: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or fallback)[:80].rstrip(" .") or fallback


def _artifact_stem(spec: SourceSpec, title: str) -> str:
    safe_title = _safe_filename(title, "untitled")
    return f"yixi-{spec.kind}-{spec.video_id}-{safe_title}"


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        _validate_media_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def _validate_media_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DownloadError("媒体地址必须是公开 HTTPS URL")
    ensure_public_http_url(url)


def _looks_like_text_error(content_type: str, first_chunk: bytes) -> bool:
    content_type = content_type.lower()
    stripped = first_chunk.lstrip().lower()
    return (
        "text/html" in content_type
        or "application/json" in content_type
        or stripped.startswith(b"<!doctype html")
        or stripped.startswith(b"<html")
        or stripped.startswith(b"{")
    )


def _should_use_curl(exc: urllib.error.URLError) -> bool:
    if os.name != "nt" or shutil.which("curl.exe") is None:
        return False
    reason = getattr(exc, "reason", exc)
    message = str(reason).lower()
    return (
        isinstance(reason, ssl.SSLCertVerificationError)
        or "certificate_verify_failed" in message
        or "certificate verify failed" in message
        or "unexpected_eof_while_reading" in message
    )


def _stream_with_urllib(
    url: str,
    destination: Path,
    timeout: float,
    max_bytes: int,
) -> None:
    opener = urllib.request.build_opener(_PublicRedirectHandler())
    request = urllib.request.Request(
        url,
        headers=_headers("video/mp4,video/*;q=0.9,application/octet-stream;q=0.8,*/*;q=0.5"),
    )
    with opener.open(request, timeout=timeout) as response:
        content_length = response.headers.get("Content-Length") if response.headers else None
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    raise DownloadError("公开视频超过允许的大小")
            except ValueError:
                pass
        content_type = response.headers.get("Content-Type", "") if response.headers else ""
        total = 0
        first_chunk = True
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if first_chunk:
                    if _looks_like_text_error(content_type, chunk[:512]):
                        raise DownloadError("媒体地址返回了网页或 JSON，而不是视频")
                    first_chunk = False
                total += len(chunk)
                if total > max_bytes:
                    raise DownloadError("公开视频超过允许的大小")
                handle.write(chunk)
    if not destination.exists() or destination.stat().st_size == 0:
        raise DownloadError("公开视频下载结果为空")


def _parse_curl_headers(raw: str) -> tuple[int, str, Any]:
    blocks = [block for block in raw.replace("\r\n", "\n").split("\n\n") if block.strip()]
    for block in reversed(blocks):
        lines = block.splitlines()
        if not lines or not lines[0].startswith("HTTP/"):
            continue
        parts = lines[0].split(" ", 2)
        try:
            status = int(parts[1])
        except (IndexError, ValueError):
            continue
        reason = parts[2] if len(parts) > 2 else ""
        return status, reason, email.message_from_string("\n".join(lines[1:]))
    return 0, "", email.message_from_string("")


def _stream_with_curl(
    url: str,
    destination: Path,
    timeout: float,
    max_bytes: int,
) -> None:
    current_url = url
    for _ in range(6):
        _validate_media_url(current_url)
        header_file = destination.with_suffix(destination.suffix + ".headers")
        destination.unlink(missing_ok=True)
        command = [
            "curl.exe",
            "--ssl-no-revoke",
            "--silent",
            "--show-error",
            "--connect-timeout",
            str(max(1, int(timeout))),
            "--max-redirs",
            "0",
            "--max-filesize",
            str(max_bytes),
            "--dump-header",
            str(header_file),
            "--output",
            str(destination),
            "--header",
            f"User-Agent: {USER_AGENT}",
            "--header",
            f"Referer: {BASE_URL}/",
            current_url,
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        raw_headers = header_file.read_text(encoding="iso-8859-1", errors="replace") if header_file.exists() else ""
        header_file.unlink(missing_ok=True)
        status, reason, headers = _parse_curl_headers(raw_headers)
        if status in {301, 302, 303, 307, 308} and headers.get("Location"):
            destination.unlink(missing_ok=True)
            current_url = urllib.parse.urljoin(current_url, headers["Location"])
            continue
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"curl exit {completed.returncode}"
            raise DownloadError(f"公开视频下载失败：{detail}")
        if status >= 400:
            raise DownloadError(f"公开视频请求失败：HTTP {status} {reason}".strip())
        if not destination.exists() or destination.stat().st_size == 0:
            raise DownloadError("公开视频下载结果为空")
        if destination.stat().st_size > max_bytes:
            raise DownloadError("公开视频超过允许的大小")
        with destination.open("rb") as handle:
            first_chunk = handle.read(512)
        if _looks_like_text_error(headers.get("Content-Type", ""), first_chunk):
            raise DownloadError("媒体地址返回了网页或 JSON，而不是视频")
        return
    raise DownloadError("公开视频重定向次数过多")


def _validate_media_file(path: Path, suffix: str) -> None:
    with path.open("rb") as handle:
        header = handle.read(16)
    suffix = suffix.lower()
    if suffix in {".mp4", ".m4v", ".mov"} and (len(header) < 8 or header[4:8] != b"ftyp"):
        raise DownloadError("下载结果不是有效的 MP4/MOV 文件")
    if suffix == ".webm" and not header.startswith(b"\x1aE\xdf\xa3"):
        raise DownloadError("下载结果不是有效的 WebM 文件")
    if suffix == ".ts" and not header.startswith(b"G"):
        raise DownloadError("下载结果不是 MPEG-TS 文件")


def _download_direct_media(
    url: str,
    destination: Path,
    timeout: float,
    max_bytes: int,
) -> Path:
    _validate_media_url(url)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    temporary.unlink(missing_ok=True)
    try:
        try:
            _stream_with_urllib(url, temporary, timeout, max_bytes)
        except urllib.error.URLError as exc:
            temporary.unlink(missing_ok=True)
            if not _should_use_curl(exc):
                raise
            _stream_with_curl(url, temporary, timeout, max_bytes)
        _validate_media_file(temporary, destination.suffix)
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_lines(raw: bytes) -> list[str]:
    text = raw.decode("utf-8-sig", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise DownloadError("HLS 清单缺少 #EXTM3U")
    return lines


def _attribute_int(line: str, name: str) -> int:
    match = re.search(rf"(?:^|,){re.escape(name)}=(\d+)", line)
    return int(match.group(1)) if match else 0


def _select_hls_playlist(url: str, timeout: float, depth: int = 0) -> tuple[str, list[str]]:
    if depth > 3:
        raise DownloadError("HLS 主清单嵌套过深")
    raw = _read_url_bytes(
        url,
        timeout=timeout,
        max_bytes=MAX_MANIFEST_BYTES,
        accept="application/vnd.apple.mpegurl, application/x-mpegURL, text/plain, */*",
        referer=BASE_URL + "/",
    )
    lines = _manifest_lines(raw)
    variants: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:"):
            if index + 1 >= len(lines) or lines[index + 1].startswith("#"):
                raise DownloadError("HLS 主清单缺少变体地址")
            variants.append(
                (
                    _attribute_int(line.split(":", 1)[1], "BANDWIDTH"),
                    urllib.parse.urljoin(url, lines[index + 1]),
                )
            )
    if variants:
        _, selected = max(variants, key=lambda item: item[0])
        _validate_media_url(selected)
        return _select_hls_playlist(selected, timeout, depth + 1)

    for line in lines:
        if line.startswith("#EXT-X-KEY:") and "METHOD=NONE" not in line.upper():
            raise DownloadError("HLS 清单包含加密密钥；为避免绕过保护，不予下载")
        if line.startswith("#EXT-X-MAP:"):
            raise DownloadError("HLS 使用 fMP4 分片，不能安全合并为 TS")
        if line.startswith("#EXT-X-BYTERANGE:"):
            raise DownloadError("HLS 使用 BYTERANGE，当前下载器不支持")
    if "#EXT-X-ENDLIST" not in lines:
        raise DownloadError("HLS 不是完整点播清单，不下载直播或动态流")
    if not any(line.startswith("#EXTINF:") for line in lines):
        raise DownloadError("HLS 清单没有媒体分片")
    segments = [urllib.parse.urljoin(url, line) for line in lines if not line.startswith("#")]
    if not segments or len(segments) > MAX_HLS_SEGMENTS:
        raise DownloadError("HLS 分片数量无效或过多")
    for segment in segments:
        _validate_media_url(segment)
    return url, segments


def _download_hls(
    url: str,
    destination: Path,
    timeout: float,
    max_bytes: int,
) -> Path:
    playlist_url, segments = _select_hls_playlist(url, timeout)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    temporary.unlink(missing_ok=True)
    total = 0
    try:
        with temporary.open("wb") as handle:
            for index, segment_url in enumerate(segments, start=1):
                remaining = max_bytes - total
                if remaining <= 0:
                    raise DownloadError("HLS 合并结果超过允许的大小")
                segment = _read_url_bytes(
                    segment_url,
                    timeout=timeout,
                    max_bytes=min(remaining, MAX_HLS_SEGMENT_BYTES),
                    accept="video/mp2t, application/octet-stream, */*",
                    referer=playlist_url,
                )
                if not segment or segment[0] != 0x47:
                    raise DownloadError(f"HLS 第 {index} 个分片不是 MPEG-TS")
                total += len(segment)
                handle.write(segment)
        if total == 0:
            raise DownloadError("HLS 合并结果为空")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _download_media_candidate(
    url: str,
    output_dir: Path,
    stem: str,
    timeout: float,
    max_bytes: int,
) -> Path:
    suffix = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).suffix.lower()
    if suffix == ".m3u8":
        return _download_hls(url, output_dir / f"{stem}.ts", timeout, max_bytes)
    if suffix not in {".mp4", ".m4v", ".mov", ".webm", ".ts"}:
        raise DownloadError(f"不支持的公开视频格式：{suffix or 'unknown'}")
    return _download_direct_media(url, output_dir / f"{stem}{suffix}", timeout, max_bytes)


class _DraftMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"p", "div", "blockquote"}:
            self.parts.append("\n\n")
        elif tag in {"h1", "h2", "h3", "h4"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "img":
            src = str(attributes.get("src") or "").strip()
            alt = str(attributes.get("alt") or "图片").strip()
            if src.startswith("http://"):
                src = "https://" + src[len("http://") :]
            if src:
                self.parts.append(f"\n\n![{alt}]({src})\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "blockquote", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def markdown(self) -> str:
        text = "".join(self.parts).replace("\r\n", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _draft_to_markdown(draft: str) -> str:
    if re.search(r"<\s*[a-zA-Z][^>]*>", draft):
        parser = _DraftMarkdownParser()
        parser.feed(draft)
        parser.close()
        return parser.markdown()
    text = html.unescape(draft).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _save_public_draft(
    spec: SourceSpec,
    metadata: dict[str, Any],
    output_dir: Path,
    stem: str,
    timeout: float,
) -> Path:
    if spec.draft_type is None:
        raise DownloadError("该枝桠资源没有公开原视频，也没有公开完整文稿")
    data = request_api(
        DRAFT_URL,
        {"id": spec.video_id, "type": str(spec.draft_type)},
        timeout,
    )
    draft = data.get("draft")
    if not isinstance(draft, str) or not draft.strip():
        raise DownloadError("该资源没有公开原视频或完整文稿")
    body = _draft_to_markdown(draft)
    if len(re.sub(r"\s+", "", body)) < 40:
        raise DownloadError("公开文稿内容过短，不能作为 Level 2 产物")
    title = str(metadata.get("title") or "一席公开文稿").strip()
    speaker = metadata.get("speaker") if isinstance(metadata.get("speaker"), dict) else {}
    speaker_name = str(speaker.get("name") or "").strip()
    lines = [
        f"# {title}",
        "",
        f"- 来源：{spec.source_url}",
        "- 产物级别：Level 2（公开完整文稿，非原视频）",
    ]
    if speaker_name:
        lines.append(f"- 讲者：{speaker_name}")
    lines.extend(["", body, ""])
    destination = output_dir / f"{stem}.md"
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    try:
        temporary.write_text("\n".join(lines), encoding="utf-8")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def download_resource(
    source_url: str,
    output_dir: str | Path,
    *,
    timeout: float = 30.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> DownloadResult:
    spec = parse_source_url(source_url)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target_dir.is_dir():
        raise DownloadError("输出路径不是目录")

    metadata = fetch_play_metadata(spec, timeout)
    title = str(metadata.get("title") or f"Yixi {spec.video_id}").strip()
    if _member_type(metadata) == 2:
        raise DownloadError("该资源标记为会员专享；下载器不会绕过登录或付费限制")

    stem = _artifact_stem(spec, title)
    media_errors: list[str] = []
    for media_url in select_media_urls(metadata):
        try:
            path = _download_media_candidate(media_url, target_dir, stem, timeout, max_bytes)
            return DownloadResult(path, "Level 1", "public-video", title)
        except (DownloadError, urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            media_errors.append(str(exc))

    try:
        path = _save_public_draft(spec, metadata, target_dir, stem, timeout)
        return DownloadResult(path, "Level 2", "public-transcript", title)
    except DownloadError as draft_error:
        if media_errors:
            raise DownloadError(
                "公开视频候选均下载失败，且无法保存公开完整文稿："
                + "; ".join(media_errors[:3])
                + f"; {draft_error}"
            ) from draft_error
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="下载一席公开单资源视频或完整文稿")
    subparsers = parser.add_subparsers(dest="command")
    command = subparsers.add_parser("download", help="下载 speech/record/zhiya 单资源")
    command.add_argument("source_url")
    command.add_argument("-o", "--output", required=True, help="输出目录")
    command.add_argument("--timeout", type=float, default=30.0, help="连接超时秒数")
    command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "download":
        parser.print_help(sys.stderr)
        return 2
    try:
        result = download_resource(
            args.source_url,
            args.output,
            timeout=max(1.0, args.timeout),
            max_bytes=max(1, args.max_bytes),
        )
    except DownloadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        print(f"一席请求失败：HTTP {exc.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        print(f"一席网络请求失败：{reason}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"一席产物写入失败：{exc}", file=sys.stderr)
        return 1

    label = "公开原视频" if result.level == "Level 1" else "公开完整文稿，非原视频"
    print(f"{result.level} ({label}): {result.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
