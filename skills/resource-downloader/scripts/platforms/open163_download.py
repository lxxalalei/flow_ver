#!/usr/bin/env python3
"""Download one publicly accessible NetEase Open Course video."""

from __future__ import annotations

import argparse
import email
import html
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
from pathlib import Path
from typing import Any, Callable


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from http_client import urlopen_with_fallback


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_PLAYLIST_BYTES = 2 * 1024 * 1024
MAX_HLS_SEGMENTS = 20_000
SOURCE_HOST = "open.163.com"


class DownloadError(RuntimeError):
    """A concise, user-facing download failure."""


class SizeLimitError(DownloadError):
    """The remote or downloaded content exceeded the configured limit."""


def parse_source_url(source_url: str) -> str:
    parsed = urllib.parse.urlsplit(source_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise DownloadError("source_url 必须是公开的 http/https 地址")
    if parsed.username or parsed.password:
        raise DownloadError("source_url 不允许包含认证信息")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DownloadError("source_url 端口无效") from exc
    if (parsed.hostname or "").rstrip(".").lower() != SOURCE_HOST:
        raise DownloadError("仅支持 open.163.com 的网易公开课链接")
    if port not in {None, 80, 443}:
        raise DownloadError("source_url 不允许使用非标准端口")
    path = parsed.path.rstrip("/")
    query = urllib.parse.parse_qs(parsed.query)
    pid = (query.get("pid") or [""])[0]
    mid = (query.get("mid") or [""])[0]
    if path == "/newview/movie/free":
        if not re.fullmatch(r"[A-Za-z0-9]+", pid):
            raise DownloadError("网易公开课链接缺少有效 pid")
        if mid and not re.fullmatch(r"[A-Za-z0-9]+", mid):
            raise DownloadError("网易公开课链接包含无效 mid")
        normalized_query = {"pid": pid}
        if mid:
            normalized_query["mid"] = mid
        return urllib.parse.urlunsplit(
            (parsed.scheme, SOURCE_HOST, path, urllib.parse.urlencode(normalized_query), "")
        )
    legacy = re.fullmatch(r"/movie/.+/([A-Za-z0-9]+)_([A-Za-z0-9]+)\.html", path)
    if legacy:
        return (
            f"https://{SOURCE_HOST}/newview/movie/free?"
            + urllib.parse.urlencode({"pid": legacy.group(1), "mid": legacy.group(2)})
        )
    raise DownloadError("链接不是网易公开课公开视频详情页")


def ensure_media_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloadError("媒体地址必须是绝对 http/https URL")
    if parsed.username or parsed.password:
        raise DownloadError("媒体地址不允许包含认证信息")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DownloadError("媒体地址端口无效") from exc
    if port not in {None, 80, 443}:
        raise DownloadError("媒体地址不允许使用非标准端口")
    host = parsed.hostname.rstrip(".").lower()
    allowed = (
        host == "mov.bn.netease.com"
        or re.fullmatch(r"(?:flv|mov)\d*\.bn\.netease\.com", host) is not None
        or re.fullmatch(r"vod[a-z0-9-]*\.vod\.126\.net", host) is not None
    )
    if not allowed:
        raise DownloadError(f"媒体域名不在网易公开课允许列表中: {host}")


def common_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": referer,
    }


def _response_url(response: Any, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    return str(getter() if callable(getter) else fallback)


def _read_limited(response: Any, max_bytes: int) -> bytes:
    content_length = response.headers.get("Content-Length") if response.headers else None
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise SizeLimitError("远程内容超过允许大小")
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise SizeLimitError("远程内容超过允许大小")
        chunks.append(chunk)
    return b"".join(chunks)


def _response_charset(response: Any) -> str:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get_content_charset", None)
    if callable(getter):
        return getter() or "utf-8"
    return "utf-8"


def fetch_source_page(
    source_url: str,
    timeout: float,
    opener: Callable[..., Any] | None = None,
) -> tuple[str, str]:
    request = urllib.request.Request(
        source_url,
        headers={**common_headers(f"https://{SOURCE_HOST}/"), "Accept": "text/html,application/xhtml+xml"},
    )
    open_url = opener or urlopen_with_fallback
    with open_url(request, timeout=timeout) as response:
        final_url = _response_url(response, source_url)
        final_parsed = urllib.parse.urlsplit(final_url)
        if (final_parsed.hostname or "").rstrip(".").lower() != SOURCE_HOST:
            raise DownloadError("详情页重定向到了非网易公开课域名")
        body = _read_limited(response, MAX_PAGE_BYTES)
        charset = _response_charset(response)
    return body.decode(charset, errors="replace"), final_url


def _decode_embedded_urls(page: str) -> str:
    decoded = html.unescape(page)
    replacements = {
        r"\u002F": "/",
        r"\u002f": "/",
        r"\u003A": ":",
        r"\u003a": ":",
        r"\u0026": "&",
        r"\u003D": "=",
        r"\u003d": "=",
    }
    for escaped, value in replacements.items():
        decoded = decoded.replace(escaped, value)
    return decoded.replace(r"\/", "/")


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()


def extract_title(page: str) -> str:
    patterns = (
        r'<div[^>]+class=["\'][^"\']*video-title[^"\']*["\'][^>]*>(.*?)</div>',
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r"<title[^>]*>(.*?)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, page, re.I | re.S)
        if match:
            title = _clean_title(match.group(1))
            if title:
                return title
    return "网易公开课"


def _media_family(url: str) -> str:
    name = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).stem.lower()
    name = re.sub(r"(?:_|-)(?:shd|hd|sd|list|1080p?|720p?|480p?)$", "", name)
    return name


def _quality_rank(url: str) -> tuple[int, int]:
    name = Path(urllib.parse.urlsplit(url).path).stem.lower()
    if re.search(r"(?:_|-)(?:shd|1080p?)$", name):
        quality = 4
    elif re.search(r"(?:_|-)(?:hd|720p?)$", name):
        quality = 3
    elif re.search(r"(?:_|-)(?:sd|480p?)$", name):
        quality = 2
    else:
        quality = 1
    return quality, -len(url)


def extract_media_options(page: str, final_url: str) -> tuple[list[str], str | None, str]:
    decoded = _decode_embedded_urls(page)
    video_match = re.search(r'<video[^>]+\bsrc=["\']([^"\']+)', decoded, re.I)
    current_url = urllib.parse.urljoin(final_url, video_match.group(1)) if video_match else None
    media_pattern = re.compile(
        r'https?://[^\s"\'<>\\]+?\.(?:mp4|m3u8)(?:\?[^\s"\'<>\\]*)?',
        re.I,
    )
    urls: list[str] = []
    for match in media_pattern.finditer(decoded):
        url = match.group(0)
        if url not in urls:
            ensure_media_url(url)
            urls.append(url)
    if current_url:
        ensure_media_url(current_url)
        if current_url not in urls:
            urls.insert(0, current_url)

    mp4_urls = [url for url in urls if urllib.parse.urlsplit(url).path.lower().endswith(".mp4")]
    hls_url = current_url if current_url and urllib.parse.urlsplit(current_url).path.lower().endswith(".m3u8") else None
    direct: list[str] = []
    if current_url and urllib.parse.urlsplit(current_url).path.lower().endswith(".mp4"):
        direct.append(current_url)
    elif current_url:
        family = _media_family(current_url)
        same_family = [url for url in mp4_urls if _media_family(url) == family]
        if same_family:
            direct.extend(sorted(same_family, key=_quality_rank, reverse=True))
        else:
            try:
                current_index = urls.index(current_url)
            except ValueError:
                current_index = -1
            for url in urls[current_index + 1 :]:
                if urllib.parse.urlsplit(url).path.lower().endswith(".mp4"):
                    direct.append(url)
                    break
                if urllib.parse.urlsplit(url).path.lower().endswith(".m3u8") and url != current_url:
                    break
    elif len(mp4_urls) == 1:
        direct = mp4_urls
    elif len(mp4_urls) > 1:
        raise DownloadError("详情页包含多个课时，但无法确定当前课时媒体")

    if not hls_url:
        hls_urls = [url for url in urls if urllib.parse.urlsplit(url).path.lower().endswith(".m3u8")]
        if len(hls_urls) == 1:
            hls_url = hls_urls[0]
    if not direct and not hls_url:
        raise DownloadError("详情页未公开提供可下载的 MP4 或 HLS")
    return direct, hls_url, extract_title(decoded)


class _MediaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        ensure_media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urllib_media_open(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.build_opener(_MediaRedirectHandler()).open(request, timeout=timeout)


def _should_use_curl(exc: BaseException) -> bool:
    if os.name != "nt" or shutil.which("curl.exe") is None:
        return False
    reason = getattr(exc, "reason", exc)
    message = str(reason).lower()
    return (
        isinstance(reason, ssl.SSLCertVerificationError)
        or "certificate_verify_failed" in message
        or "certificate verify failed" in message
    )


def _parse_curl_headers(raw: str) -> tuple[int, Any]:
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
        return status, email.message_from_string("\n".join(lines[1:]))
    raise DownloadError("curl 未返回有效 HTTP 响应头")


def _curl_download(
    url: str,
    destination: Path,
    referer: str,
    timeout: float,
    max_bytes: int,
) -> Any:
    current_url = url
    for _redirect in range(6):
        ensure_media_url(current_url)
        destination.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="open163-curl-") as directory:
            header_path = Path(directory) / "headers.txt"
            command = [
                "curl.exe",
                "--ssl-no-revoke",
                "--silent",
                "--show-error",
                "--max-time",
                str(max(1, int(timeout))),
                "--max-filesize",
                str(max_bytes),
                "--dump-header",
                str(header_path),
                "--output",
                str(destination),
                "--header",
                f"User-Agent: {USER_AGENT}",
                "--header",
                f"Referer: {referer}",
                current_url,
            ]
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            raw_headers = header_path.read_text(encoding="iso-8859-1", errors="replace") if header_path.exists() else ""
        if completed.returncode == 63:
            raise SizeLimitError("媒体文件超过允许大小")
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"curl exit {completed.returncode}"
            raise urllib.error.URLError(detail)
        status, headers = _parse_curl_headers(raw_headers)
        location = headers.get("Location")
        if status in {301, 302, 303, 307, 308} and location:
            current_url = urllib.parse.urljoin(current_url, location)
            continue
        if status >= 400:
            raise urllib.error.HTTPError(current_url, status, f"HTTP {status}", headers, None)
        if status not in {200, 206}:
            raise DownloadError(f"媒体请求返回异常状态: HTTP {status}")
        if not destination.is_file() or destination.stat().st_size == 0:
            raise DownloadError("媒体下载结果为空")
        if destination.stat().st_size > max_bytes:
            raise SizeLimitError("媒体文件超过允许大小")
        return current_url
    raise DownloadError("媒体重定向次数过多")


def stream_media(
    url: str,
    destination: Path,
    referer: str,
    timeout: float,
    max_bytes: int,
    opener: Callable[..., Any] | None = None,
) -> Any:
    ensure_media_url(url)
    request = urllib.request.Request(url, headers={**common_headers(referer), "Accept": "*/*"})
    open_url = opener or _urllib_media_open
    try:
        response = open_url(request, timeout=timeout)
    except urllib.error.URLError as exc:
        if opener is not None or not _should_use_curl(exc):
            raise
        return _curl_download(url, destination, referer, timeout, max_bytes)

    try:
        with response:
            final_url = _response_url(response, url)
            ensure_media_url(final_url)
            content_length = response.headers.get("Content-Length") if response.headers else None
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise SizeLimitError("媒体文件超过允许大小")
                except ValueError:
                    pass
            content_type = (response.headers.get("Content-Type") or "").lower() if response.headers else ""
            if content_type.startswith("text/") or "html" in content_type or "json" in content_type:
                raise DownloadError(f"媒体地址返回了非媒体内容: {content_type or 'unknown'}")
            total = 0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise SizeLimitError("媒体文件超过允许大小")
                    handle.write(chunk)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise DownloadError("媒体下载结果为空")
        return final_url
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def validate_mp4(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 16:
        raise DownloadError("下载结果不是有效 MP4 文件")
    with path.open("rb") as handle:
        head = handle.read(64)
    if len(head) < 12 or head[4:8] != b"ftyp" or int.from_bytes(head[:4], "big") < 8:
        raise DownloadError("下载结果缺少有效 MP4 ftyp 文件头")


def _fetch_playlist(
    url: str,
    referer: str,
    timeout: float,
    opener: Callable[..., Any] | None,
) -> tuple[str, str]:
    descriptor, temporary_name = tempfile.mkstemp(prefix="open163-playlist-", suffix=".m3u8")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        final_url = stream_media(
            url, temporary, referer, timeout, MAX_PLAYLIST_BYTES, opener=opener
        )
        data = temporary.read_bytes()
    finally:
        temporary.unlink(missing_ok=True)
    text = data.decode("utf-8-sig", errors="replace")
    if not text.lstrip().startswith("#EXTM3U"):
        raise DownloadError("HLS 地址未返回有效 M3U8 清单")
    return text, final_url


def _attribute_value(line: str, name: str) -> str | None:
    match = re.search(rf"(?:^|,){re.escape(name)}=(?:\"([^\"]*)\"|([^,]*))", line, re.I)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def select_hls_media_playlist(text: str, base_url: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()]
    if any(line.upper().startswith("#EXT-X-MEDIA:") and "TYPE=AUDIO" in line.upper() for line in lines):
        raise DownloadError("不下载带独立音轨的复杂 HLS，避免生成缺音频产物")
    variants: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        if not line.upper().startswith("#EXT-X-STREAM-INF:"):
            continue
        next_uri = next((item for item in lines[index + 1 :] if item and not item.startswith("#")), "")
        if not next_uri:
            raise DownloadError("HLS 主清单缺少变体地址")
        bandwidth_text = _attribute_value(line.split(":", 1)[1], "BANDWIDTH") or "0"
        resolution = _attribute_value(line.split(":", 1)[1], "RESOLUTION") or "0x0"
        try:
            bandwidth = int(bandwidth_text)
        except ValueError:
            bandwidth = 0
        resolution_match = re.fullmatch(r"(\d+)x(\d+)", resolution, re.I)
        pixels = int(resolution_match.group(1)) * int(resolution_match.group(2)) if resolution_match else 0
        variant_url = urllib.parse.urljoin(base_url, next_uri)
        ensure_media_url(variant_url)
        variants.append((bandwidth, pixels, variant_url))
    if not variants:
        return None
    return max(variants)[2]


def prepare_hls_media_playlist(text: str, base_url: str) -> tuple[list[str], list[tuple[int, str]], str]:
    lines = text.splitlines()
    upper_lines = [line.strip().upper() for line in lines]
    if any(line.startswith("#EXT-X-SESSION-KEY") for line in upper_lines):
        raise DownloadError("拒绝下载带会话密钥的 HLS")
    for line in lines:
        if line.strip().upper().startswith("#EXT-X-KEY:"):
            method = (_attribute_value(line.split(":", 1)[1], "METHOD") or "").upper()
            if method != "NONE":
                raise DownloadError("拒绝下载加密或 DRM HLS")
    if any(line.startswith("#EXT-X-BYTERANGE") for line in upper_lines):
        raise DownloadError("暂不下载需要字节范围拼接的 HLS")
    if any(line.startswith("#EXT-X-I-FRAMES-ONLY") for line in upper_lines):
        raise DownloadError("不下载仅包含关键帧的 HLS")
    if "#EXT-X-ENDLIST" not in upper_lines:
        raise DownloadError("仅支持已结束的点播 HLS，不下载直播流")

    resources: list[str] = []
    replacements: list[tuple[int, str]] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXT-X-MAP:"):
            if _attribute_value(line.split(":", 1)[1], "BYTERANGE"):
                raise DownloadError("暂不下载初始化段使用字节范围的 HLS")
            uri = _attribute_value(line.split(":", 1)[1], "URI")
            if not uri:
                raise DownloadError("HLS 初始化段缺少 URI")
            resource_url = urllib.parse.urljoin(base_url, uri)
            ensure_media_url(resource_url)
            resources.append(resource_url)
            replacements.append((index, resource_url))
        elif not line.startswith("#"):
            resource_url = urllib.parse.urljoin(base_url, line)
            ensure_media_url(resource_url)
            resources.append(resource_url)
            replacements.append((index, resource_url))
    if not resources:
        raise DownloadError("HLS 清单不包含媒体分片")
    if len(resources) > MAX_HLS_SEGMENTS:
        raise DownloadError("HLS 分片数量超过安全限制")
    return lines, replacements, "\n".join(lines) + "\n"


def download_hls(
    playlist_url: str,
    destination: Path,
    referer: str,
    timeout: float,
    max_bytes: int,
    opener: Callable[..., Any] | None = None,
    ffmpeg_path: str | None = None,
) -> None:
    ensure_media_url(playlist_url)
    playlist_text, playlist_url = _fetch_playlist(
        playlist_url, referer, timeout, opener
    )
    selected = select_hls_media_playlist(playlist_text, playlist_url)
    if selected:
        playlist_text, playlist_url = _fetch_playlist(
            selected, referer, timeout, opener
        )
        if select_hls_media_playlist(playlist_text, playlist_url):
            raise DownloadError("HLS 变体清单嵌套过深")

    lines, replacements, _original = prepare_hls_media_playlist(playlist_text, playlist_url)
    executable = ffmpeg_path or shutil.which("ffmpeg")
    if not executable:
        raise DownloadError("仅发现 HLS，但本机没有 ffmpeg，无法安全合并为 MP4")

    with tempfile.TemporaryDirectory(prefix="open163-hls-", dir=destination.parent) as directory:
        workdir = Path(directory)
        remaining = max_bytes
        local_by_url: dict[str, str] = {}
        for sequence, (_line_index, resource_url) in enumerate(replacements):
            if resource_url in local_by_url:
                continue
            suffix = Path(urllib.parse.urlsplit(resource_url).path).suffix
            if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
                suffix = ".bin"
            local_name = f"segment-{sequence:05d}{suffix}"
            local_path = workdir / local_name
            stream_media(resource_url, local_path, referer, timeout, remaining, opener=opener)
            size = local_path.stat().st_size
            remaining -= size
            if remaining < 0:
                raise SizeLimitError("HLS 分片总大小超过允许限制")
            local_by_url[resource_url] = local_name

        for line_index, resource_url in replacements:
            original = lines[line_index].strip()
            local_name = local_by_url[resource_url]
            if original.upper().startswith("#EXT-X-MAP:"):
                lines[line_index] = re.sub(
                    r'URI=(?:"[^"]*"|[^,]*)', f'URI="{local_name}"', lines[line_index], flags=re.I
                )
            else:
                lines[line_index] = local_name
        local_playlist = workdir / "local.m3u8"
        local_playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary_output = workdir / "output.mp4"
        command = [
            str(executable),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-allowed_extensions",
            "ALL",
            "-i",
            str(local_playlist),
            "-map",
            "0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            str(temporary_output),
        ]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=max(60.0, min(timeout * 4, 900.0)),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"ffmpeg exit {completed.returncode}"
            raise DownloadError(f"HLS 合并失败: {detail}")
        if not temporary_output.is_file() or temporary_output.stat().st_size > max_bytes:
            raise SizeLimitError("HLS 合并产物超过允许大小或为空")
        validate_mp4(temporary_output)
        os.replace(temporary_output, destination)


def _safe_filename(title: str, identifier: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")[:100]
    if not cleaned:
        cleaned = "open163"
    return f"{cleaned}-{identifier}.mp4"


def download_open163(
    source_url: str,
    output_dir: str | Path,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    page_opener: Callable[..., Any] | None = None,
    media_opener: Callable[..., Any] | None = None,
    ffmpeg_path: str | None = None,
) -> Path:
    normalized_source = parse_source_url(source_url)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target_dir.is_dir():
        raise DownloadError("输出路径不是目录")
    page, final_url = fetch_source_page(normalized_source, timeout, opener=page_opener)
    direct_urls, hls_url, title = extract_media_options(page, final_url)
    final_query = urllib.parse.parse_qs(urllib.parse.urlsplit(final_url).query)
    identifier = (final_query.get("mid") or final_query.get("pid") or ["video"])[0]
    if not re.fullmatch(r"[A-Za-z0-9]+", identifier):
        identifier = "video"
    destination = target_dir / _safe_filename(title, identifier)

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix=".open163-", dir=target_dir) as directory:
        workdir = Path(directory)
        for index, media_url in enumerate(direct_urls):
            temporary = workdir / f"direct-{index}.mp4"
            try:
                stream_media(media_url, temporary, final_url, timeout, max_bytes, opener=media_opener)
                validate_mp4(temporary)
                os.replace(temporary, destination)
                return destination
            except (DownloadError, OSError, TimeoutError, urllib.error.URLError) as exc:
                errors.append(f"MP4 {index + 1}: {exc}")
                temporary.unlink(missing_ok=True)
        if hls_url:
            temporary = workdir / "hls.mp4"
            try:
                download_hls(
                    hls_url,
                    temporary,
                    final_url,
                    timeout,
                    max_bytes,
                    opener=media_opener,
                    ffmpeg_path=ffmpeg_path,
                )
                os.replace(temporary, destination)
                return destination
            except (DownloadError, OSError, TimeoutError, subprocess.SubprocessError, urllib.error.URLError) as exc:
                errors.append(f"HLS: {exc}")
    detail = "; ".join(errors[-4:]) or "没有可用公开媒体"
    raise DownloadError(f"网易公开课公开媒体下载失败: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="下载单个网易公开课公开资源")
    subparsers = parser.add_subparsers(dest="command")
    command = subparsers.add_parser("download", help="下载一个公开课视频")
    command.add_argument("source_url")
    command.add_argument("-o", "--output", required=True, help="输出目录")
    command.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    if args.command != "download":
        parser.print_help(sys.stderr)
        return 2
    try:
        path = download_open163(
            args.source_url,
            args.output,
            timeout=max(1.0, min(args.timeout, 600.0)),
            max_bytes=max(1, min(args.max_bytes, 4 * 1024 * 1024 * 1024)),
        )
    except DownloadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        print(f"网易公开课请求失败: HTTP {exc.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        print(f"网易公开课网络请求失败: {reason}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"网易公开课文件写入失败: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
