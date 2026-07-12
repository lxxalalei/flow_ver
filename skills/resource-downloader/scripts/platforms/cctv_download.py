#!/usr/bin/env python3
"""Download one public CCTV video from its standard unencrypted HLS feed."""

from __future__ import annotations

import argparse
import email
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from http_client import ensure_public_http_url


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
VIDEO_INFO_API = "https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 1800.0
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
HARD_MAX_BYTES = 4 * 1024 * 1024 * 1024
HARD_MAX_TIMEOUT_SECONDS = 120.0
HARD_MAX_TOTAL_TIMEOUT_SECONDS = 3600.0
PAGE_MAX_BYTES = 2 * 1024 * 1024
API_MAX_BYTES = 1024 * 1024
PLAYLIST_MAX_BYTES = 2 * 1024 * 1024
SEGMENT_MAX_BYTES = 64 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_PLAYLIST_DEPTH = 3
MAX_SEGMENTS = 10_000
TS_PACKET_SIZE = 188


class DownloadError(RuntimeError):
    """A concise, user-facing CCTV download failure."""


@dataclass(frozen=True)
class FetchedResponse:
    body: bytes
    url: str
    headers: Any
    status: int = 200


UrlValidator = Callable[[str], None]
Fetcher = Callable[..., FetchedResponse]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _validate_https_url(url: str, allowed_host: Callable[[str], bool], label: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise DownloadError(f"{label}必须是无凭据的 HTTPS 地址")
    if parsed.port not in {None, 443}:
        raise DownloadError(f"{label}使用了不允许的端口")
    if not allowed_host(hostname):
        raise DownloadError(f"{label}域名不在 CCTV 允许列表中: {hostname}")


def _source_url_validator(url: str) -> None:
    _validate_https_url(url, lambda host: host == "tv.cctv.com", "CCTV 来源页")


def _api_url_validator(url: str) -> None:
    _validate_https_url(url, lambda host: host == "vdn.apps.cntv.cn", "CCTV 视频 API")


def _is_media_host(hostname: str) -> bool:
    if hostname in {"hls.cntv.lxdns.com", "newcntv.qcloudcdn.com"}:
        return True
    suffixes = (
        ".v.cntv.cn",
        ".cntv.lxdns.com",
        ".cntv.cdn20.com",
        ".cntv.qcloudcdn.com",
    )
    if not hostname.endswith(suffixes):
        return False
    first_label = hostname.split(".", 1)[0]
    return bool(re.fullmatch(r"(?:d?hls|dh5|newcntv)[a-z0-9-]*", first_label))


def _media_url_validator(url: str) -> None:
    _validate_https_url(url, _is_media_host, "CCTV HLS 资源")


def parse_source(source_url: str) -> str:
    _source_url_validator(source_url)
    parsed = urllib.parse.urlsplit(source_url)
    filename = PurePosixPath(parsed.path).name
    match = re.fullmatch(r"(VIDE[A-Za-z0-9]+)\.shtml", filename)
    if not match:
        raise DownloadError("来源链接不是 CCTV 单视频公开页面")
    if parsed.query:
        raise DownloadError("CCTV 单视频来源页不应包含查询参数")
    return match.group(1)


def extract_guid(page_html: str) -> str:
    match = re.search(
        r"\bvar\s+guid\s*=\s*['\"]([0-9a-fA-F]{32})['\"]\s*;?",
        page_html,
    )
    if not match:
        raise DownloadError("CCTV 页面未公开提供有效视频 GUID")
    return match.group(1).lower()


def _flag(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value).strip().lower()


def extract_public_hls_url(document: Any, guid: str, cvid: str) -> str:
    if not isinstance(document, dict):
        raise DownloadError("CCTV 视频 API 响应结构无效")
    if document.get("ack") != "yes" or str(document.get("status")) != "001":
        raise DownloadError("CCTV 视频 API 未返回可播放资源")
    api_guid = str(document.get("vid") or "").strip().lower()
    if api_guid and api_guid != guid:
        raise DownloadError("CCTV 视频 API 返回了不匹配的 GUID")
    api_cvid = str(document.get("cvid") or "")
    if api_cvid and api_cvid != cvid:
        raise DownloadError("CCTV 视频 API 返回了不匹配的页面 ID")
    if _flag(document.get("public")) != "1":
        raise DownloadError("该 CCTV 视频未标记为公开资源")
    if _flag(document.get("is_preview")) != "0":
        raise DownloadError("该 CCTV 视频仅提供预览，不下载")
    if _flag(document.get("is_protected")) != "0":
        raise DownloadError("该 CCTV 视频受保护，不下载")
    if _flag(document.get("is_invalid_copyright")) != "0":
        raise DownloadError("该 CCTV 视频当前版权状态不允许播放")
    if str(document.get("asp_error_code")) != "0":
        raise DownloadError("CCTV HLS 服务未返回可用公开流")
    hls_url = str(document.get("hls_url") or "").strip()
    if not hls_url:
        raise DownloadError("CCTV 视频 API 未提供标准 HLS 地址")
    _media_url_validator(hls_url)
    hls_path_parts = {
        part.lower() for part in PurePosixPath(urllib.parse.urlsplit(hls_url).path).parts
    }
    if guid not in hls_path_parts:
        raise DownloadError("CCTV HLS 地址与页面 GUID 不匹配")
    return hls_url


def _content_length(headers: Any) -> int | None:
    raw = headers.get("Content-Length") if headers is not None else None
    if raw in {None, ""}:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise DownloadError("HTTP Content-Length 无效") from exc
    if value < 0:
        raise DownloadError("HTTP Content-Length 无效")
    return value


def _read_limited(response: Any, max_bytes: int) -> bytes:
    declared = _content_length(getattr(response, "headers", None))
    if declared is not None and declared > max_bytes:
        raise DownloadError("HTTP 响应超过允许大小")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise DownloadError("HTTP 响应超过允许大小")
    return b"".join(chunks)


def _urllib_fetch_once(
    url: str,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> FetchedResponse:
    opener = urllib.request.build_opener(_NoRedirectHandler())
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            body = _read_limited(response, max_bytes)
            return FetchedResponse(
                body=body,
                url=response.geturl(),
                headers=response.headers,
                status=getattr(response, "status", 200),
            )
    except urllib.error.HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            return FetchedResponse(b"", url, exc.headers, exc.code)
        raise


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
    raise DownloadError("curl 未返回有效 HTTP 响应头")


def _curl_fetch_once(
    url: str,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> FetchedResponse:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise DownloadError("HTTPS 证书校验失败，且系统未安装 curl 备用客户端")
    with tempfile.TemporaryDirectory(prefix="cctv-http-") as directory:
        root = Path(directory)
        header_path = root / "headers.txt"
        body_path = root / "body.bin"
        command = [
            curl,
            "--ssl-no-revoke",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--max-time",
            str(max(1, math.ceil(timeout))),
            "--max-filesize",
            str(max_bytes),
            "--dump-header",
            str(header_path),
            "--output",
            str(body_path),
        ]
        for name, value in headers.items():
            command.extend(["--header", f"{name}: {value}"])
        command.append(url)
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if completed.returncode == 63:
            raise DownloadError("HTTP 响应超过允许大小")
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise urllib.error.URLError(detail or f"curl exit {completed.returncode}")
        raw_headers = header_path.read_text(encoding="iso-8859-1", errors="replace")
        status, reason, parsed_headers = _parse_curl_headers(raw_headers)
        body_size = body_path.stat().st_size if body_path.exists() else 0
        if body_size > max_bytes:
            raise DownloadError("HTTP 响应超过允许大小")
        body = body_path.read_bytes() if body_path.exists() else b""
    if status >= 400:
        raise urllib.error.HTTPError(url, status, reason, parsed_headers, None)
    return FetchedResponse(body, url, parsed_headers, status)


def _is_certificate_error(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", exc)
    message = str(reason).lower()
    return (
        isinstance(reason, ssl.SSLCertVerificationError)
        or "certificate_verify_failed" in message
        or "certificate verify failed" in message
        or "unexpected_eof_while_reading" in message
    )


def fetch_bytes(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
    url_validator: UrlValidator,
) -> FetchedResponse:
    current_url = url
    for _redirect in range(MAX_REDIRECTS + 1):
        url_validator(current_url)
        ensure_public_http_url(current_url)
        try:
            response = _urllib_fetch_once(current_url, headers, timeout, max_bytes)
        except urllib.error.URLError as exc:
            if not _is_certificate_error(exc):
                raise
            response = _curl_fetch_once(current_url, headers, timeout, max_bytes)
        if response.status in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location") if response.headers is not None else None
            if not location:
                raise DownloadError("HTTP 重定向缺少 Location")
            current_url = urllib.parse.urljoin(current_url, location)
            continue
        url_validator(response.url)
        if len(response.body) > max_bytes:
            raise DownloadError("HTTP 响应超过允许大小")
        return response
    raise DownloadError("HTTP 重定向次数过多")


def _response_text(response: FetchedResponse) -> str:
    charset = None
    headers = response.headers
    if headers is not None and callable(getattr(headers, "get_content_charset", None)):
        charset = headers.get_content_charset()
    return response.body.decode(charset or "utf-8", errors="replace")


def _parse_attribute_list(value: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for match in re.finditer(r"(?:^|,)([A-Z0-9-]+)=(\"[^\"]*\"|[^,]*)", value):
        raw = match.group(2).strip()
        attributes[match.group(1)] = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
    return attributes


def _reject_encrypted_playlist(lines: list[str]) -> None:
    for line in lines:
        upper = line.upper()
        if upper.startswith("#EXT-X-SESSION-KEY"):
            raise DownloadError("CCTV HLS 使用会话密钥，不下载")
        if upper.startswith("#EXT-X-KEY:"):
            method = _parse_attribute_list(line.split(":", 1)[1]).get("METHOD", "").upper()
            if method != "NONE":
                raise DownloadError("CCTV HLS 使用加密密钥，不下载")


def parse_playlist(playlist_url: str, content: str) -> tuple[str, list[str]]:
    lines = [line.strip() for line in content.lstrip("\ufeff").splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise DownloadError("CCTV HLS 播放列表格式无效")
    _reject_encrypted_playlist(lines)
    if any(line.upper().startswith("#EXT-X-MEDIA:") and "URI=" in line.upper() for line in lines):
        raise DownloadError("CCTV HLS 含独立媒体轨道，当前不安全合并")

    variants: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        if not line.upper().startswith("#EXT-X-STREAM-INF:"):
            continue
        attributes = _parse_attribute_list(line.split(":", 1)[1])
        uri = ""
        for following in lines[index + 1 :]:
            if following.startswith("#"):
                continue
            uri = following
            break
        if not uri:
            raise DownloadError("CCTV HLS 主播放列表缺少清晰度地址")
        try:
            bandwidth = int(attributes.get("BANDWIDTH", "0"))
        except ValueError:
            bandwidth = 0
        resolution = attributes.get("RESOLUTION", "")
        resolution_match = re.fullmatch(r"(\d+)x(\d+)", resolution)
        area = int(resolution_match.group(1)) * int(resolution_match.group(2)) if resolution_match else 0
        variant_url = urllib.parse.urljoin(playlist_url, uri)
        _media_url_validator(variant_url)
        variants.append((bandwidth, area, variant_url))
    if variants:
        variants.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return "master", [variants[0][2]]

    forbidden_tags = ("#EXT-X-BYTERANGE", "#EXT-X-MAP")
    if any(line.upper().startswith(forbidden_tags) for line in lines):
        raise DownloadError("CCTV HLS 使用当前不支持的分段封装")
    if not any(line.upper() == "#EXT-X-ENDLIST" for line in lines):
        raise DownloadError("CCTV HLS 不是已结束的 VOD 播放列表")
    segments = [
        urllib.parse.urljoin(playlist_url, line)
        for line in lines
        if not line.startswith("#")
    ]
    if not segments:
        raise DownloadError("CCTV HLS 播放列表没有媒体分片")
    if len(segments) > MAX_SEGMENTS:
        raise DownloadError("CCTV HLS 分片数量超过安全上限")
    for segment_url in segments:
        _media_url_validator(segment_url)
    return "media", segments


def _remaining_timeout(deadline: float, request_timeout: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DownloadError("CCTV 下载超过总超时限制")
    return min(request_timeout, remaining)


def resolve_segments(
    hls_url: str,
    source_url: str,
    request_timeout: float,
    deadline: float,
    fetcher: Fetcher,
) -> list[str]:
    playlist_url = hls_url
    seen: set[str] = set()
    for _depth in range(MAX_PLAYLIST_DEPTH):
        if playlist_url in seen:
            raise DownloadError("CCTV HLS 播放列表形成循环")
        seen.add(playlist_url)
        response = fetcher(
            playlist_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*",
                "Referer": source_url,
            },
            timeout=_remaining_timeout(deadline, request_timeout),
            max_bytes=PLAYLIST_MAX_BYTES,
            url_validator=_media_url_validator,
        )
        _media_url_validator(response.url)
        kind, urls = parse_playlist(response.url, _response_text(response))
        if kind == "media":
            return urls
        playlist_url = urls[0]
    raise DownloadError("CCTV HLS 播放列表嵌套过深")


def validate_ts_segment(data: bytes) -> None:
    if len(data) < TS_PACKET_SIZE or len(data) % TS_PACKET_SIZE != 0:
        raise DownloadError("CCTV HLS 分片不是完整 MPEG-TS 数据")
    if any(data[offset] != 0x47 for offset in range(0, len(data), TS_PACKET_SIZE)):
        raise DownloadError("CCTV HLS 分片缺少 MPEG-TS 同步字节")


def validate_transport_stream(path: Path) -> None:
    size = path.stat().st_size
    if size < TS_PACKET_SIZE or size % TS_PACKET_SIZE != 0:
        raise DownloadError("CCTV 下载产物不是完整 MPEG-TS 文件")
    chunk_size = TS_PACKET_SIZE * 4096
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            if len(chunk) % TS_PACKET_SIZE != 0:
                raise DownloadError("CCTV 下载产物的 MPEG-TS 包长度无效")
            if any(chunk[offset] != 0x47 for offset in range(0, len(chunk), TS_PACKET_SIZE)):
                raise DownloadError("CCTV 下载产物缺少 MPEG-TS 同步字节")


def _validate_limits(timeout: float, total_timeout: float, max_bytes: int) -> None:
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > HARD_MAX_TIMEOUT_SECONDS:
        raise DownloadError(f"单请求超时必须在 0 到 {HARD_MAX_TIMEOUT_SECONDS:g} 秒之间")
    if (
        not isinstance(total_timeout, (int, float))
        or total_timeout <= 0
        or total_timeout > HARD_MAX_TOTAL_TIMEOUT_SECONDS
    ):
        raise DownloadError(f"总超时必须在 0 到 {HARD_MAX_TOTAL_TIMEOUT_SECONDS:g} 秒之间")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise DownloadError("最大下载字节数必须是正整数")
    if max_bytes > HARD_MAX_BYTES:
        raise DownloadError(f"最大下载字节数不得超过 {HARD_MAX_BYTES}")


def download_video(
    source_url: str,
    output_dir: str | Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    fetcher: Fetcher = fetch_bytes,
) -> Path:
    _validate_limits(timeout, total_timeout, max_bytes)
    cvid = parse_source(source_url)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target_dir.is_dir():
        raise DownloadError("输出路径不是目录")
    deadline = time.monotonic() + total_timeout

    page_response = fetcher(
        source_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        timeout=_remaining_timeout(deadline, timeout),
        max_bytes=PAGE_MAX_BYTES,
        url_validator=_source_url_validator,
    )
    _source_url_validator(page_response.url)
    guid = extract_guid(_response_text(page_response))

    api_url = VIDEO_INFO_API + "?" + urllib.parse.urlencode(
        {"pid": guid, "serviceId": "tvcctv"}
    )
    api_response = fetcher(
        api_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Referer": source_url,
        },
        timeout=_remaining_timeout(deadline, timeout),
        max_bytes=API_MAX_BYTES,
        url_validator=_api_url_validator,
    )
    _api_url_validator(api_response.url)
    try:
        api_document = json.loads(_response_text(api_response))
    except json.JSONDecodeError as exc:
        raise DownloadError("CCTV 视频 API 返回了无效 JSON") from exc
    hls_url = extract_public_hls_url(api_document, guid, cvid)
    segments = resolve_segments(hls_url, source_url, timeout, deadline, fetcher)

    destination = target_dir / f"cctv-{guid}.ts"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=target_dir
    )
    temporary_path = Path(temporary)
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            for segment_url in segments:
                remaining_bytes = max_bytes - total
                if remaining_bytes <= 0:
                    raise DownloadError("CCTV 视频超过允许的最大下载大小")
                response = fetcher(
                    segment_url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "video/mp2t,application/octet-stream,*/*",
                        "Referer": source_url,
                    },
                    timeout=_remaining_timeout(deadline, timeout),
                    max_bytes=min(remaining_bytes, SEGMENT_MAX_BYTES),
                    url_validator=_media_url_validator,
                )
                _media_url_validator(response.url)
                validate_ts_segment(response.body)
                total += len(response.body)
                if total > max_bytes:
                    raise DownloadError("CCTV 视频超过允许的最大下载大小")
                handle.write(response.body)
        if total == 0:
            raise DownloadError("CCTV 视频下载结果为空")
        validate_transport_stream(temporary_path)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="下载央视网单个公开视频")
    subparsers = parser.add_subparsers(dest="command")
    command = subparsers.add_parser("download", help="下载单个 CCTV 公公开视频")
    command.add_argument("source_url")
    command.add_argument("-o", "--output", required=True, help="输出目录")
    command.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    command.add_argument("--total-timeout", type=float, default=DEFAULT_TOTAL_TIMEOUT_SECONDS)
    command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    if args.command != "download":
        parser.print_help(sys.stderr)
        return 2
    try:
        path = download_video(
            args.source_url,
            args.output,
            timeout=args.timeout,
            total_timeout=args.total_timeout,
            max_bytes=args.max_bytes,
        )
    except DownloadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        print(f"CCTV 请求失败: HTTP {exc.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        print(f"CCTV 网络请求失败: {reason}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"CCTV 文件写入失败: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
