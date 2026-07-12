#!/usr/bin/env python3
"""Download public NLC Yuewen EPUB files with the standard library."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024


class DownloadError(RuntimeError):
    """A concise, user-facing download failure."""


def parse_source(source_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != "read.nlc.cn":
        raise DownloadError("仅支持 read.nlc.cn 的公开阅文资源链接")
    if parsed.path.rstrip("/") not in {"/yuewen/detail", "/yuewen/read"}:
        raise DownloadError("链接不是阅文详情页或阅读页")
    yuewen_id = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
    if not re.fullmatch(r"\d+", yuewen_id):
        raise DownloadError("链接缺少有效的阅文资源 ID")
    return f"{parsed.scheme}://{parsed.netloc}", yuewen_id


def build_opener() -> urllib.request.OpenerDirector:
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))


def common_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }


def response_charset(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is not None and callable(getattr(headers, "get_content_charset", None)):
        return headers.get_content_charset() or "utf-8"
    return "utf-8"


def read_response_text(opener: Any, request: urllib.request.Request, timeout: float) -> str:
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode(response_charset(response), errors="replace")


def extract_reader_parameters(page: str) -> tuple[str, str, str]:
    cbid_match = re.search(r"\bcbid\s*:\s*['\"]([^'\"]+)['\"]", page, re.I)
    ccid_match = re.search(r"\bccid\s*:\s*['\"]([^'\"]*)['\"]", page, re.I)
    format_match = re.search(r"\bsupportFormat\s*:\s*['\"]([^'\"]+)['\"]", page, re.I)
    if not cbid_match:
        raise DownloadError("阅读页未提供 EPUB 内容标识")
    support_format = format_match.group(1).strip() if format_match else ""
    if support_format != "2":
        raise DownloadError("该阅文资源未公开提供 EPUB 格式")
    return cbid_match.group(1).strip(), (ccid_match.group(1).strip() if ccid_match else ""), support_format


def request_download_token(
    opener: Any,
    origin: str,
    read_url: str,
    cbid: str,
    ccid: str,
    support_format: str,
    timeout: float,
) -> str:
    payload = urllib.parse.urlencode(
        {"cbid": cbid, "ccid": ccid, "supportFormat": support_format}
    ).encode("ascii")
    request = urllib.request.Request(
        f"{origin}/yuewen/readContent",
        data=payload,
        method="POST",
        headers={
            **common_headers(),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": origin,
            "Referer": read_url,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    raw = read_response_text(opener, request, timeout)
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DownloadError("阅文内容接口返回了无效响应") from exc
    token = document.get("obj") if isinstance(document, dict) and document.get("success") is True else None
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._-]+\.epub", token):
        message = document.get("msg") if isinstance(document, dict) else None
        raise DownloadError(str(message or "阅文内容接口未返回 EPUB 文件"))
    return token


def validate_epub(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise DownloadError("下载结果不是有效的 EPUB ZIP 文件")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or entries[0].filename != "mimetype":
                raise DownloadError("EPUB 缺少首项 mimetype")
            if entries[0].compress_type != zipfile.ZIP_STORED:
                raise DownloadError("EPUB mimetype 不应压缩")
            if archive.read("mimetype").strip() != b"application/epub+zip":
                raise DownloadError("EPUB mimetype 内容无效")
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        raise DownloadError("EPUB ZIP 结构无效") from exc


def stream_epub(
    opener: Any,
    download_url: str,
    read_url: str,
    destination: Path,
    timeout: float,
    max_bytes: int,
) -> None:
    request = urllib.request.Request(
        download_url,
        headers={
            **common_headers(),
            "Accept": "application/epub+zip,application/zip,*/*",
            "Referer": read_url,
        },
    )
    temporary_path: Path | None = None
    try:
        with opener.open(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length") if response.headers else None
            if content_length and int(content_length) > max_bytes:
                raise DownloadError("EPUB 文件超过允许的大小")
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
            )
            temporary_path = Path(temporary)
            total = 0
            with os.fdopen(descriptor, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadError("EPUB 文件超过允许的大小")
                    handle.write(chunk)
        if not temporary_path or temporary_path.stat().st_size == 0:
            raise DownloadError("EPUB 下载结果为空")
        validate_epub(temporary_path)
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def download_epub(
    source_url: str,
    output_dir: str | Path,
    timeout: float = 30.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    opener: Any | None = None,
) -> Path:
    origin, yuewen_id = parse_source(source_url)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target_dir.is_dir():
        raise DownloadError("输出路径不是目录")
    session = opener or build_opener()
    read_url = f"{origin}/yuewen/read?" + urllib.parse.urlencode({"id": yuewen_id})
    read_request = urllib.request.Request(
        read_url,
        headers={**common_headers(), "Accept": "text/html,application/xhtml+xml"},
    )
    reader_page = read_response_text(session, read_request, timeout)
    cbid, ccid, support_format = extract_reader_parameters(reader_page)
    token = request_download_token(
        session, origin, read_url, cbid, ccid, support_format, timeout
    )
    download_url = f"{origin}/yuewen/download/{urllib.parse.quote(token, safe='.')}"
    destination = target_dir / f"nlc-yuewen-{yuewen_id}.epub"
    stream_epub(session, download_url, read_url, destination, timeout, max_bytes)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="下载国家图书馆阅文公开 EPUB")
    subparsers = parser.add_subparsers(dest="command")
    command = subparsers.add_parser("download", help="下载单个阅文 EPUB")
    command.add_argument("source_url")
    command.add_argument("-o", "--output", required=True, help="输出目录")
    command.add_argument("--timeout", type=float, default=30.0)
    command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    if args.command != "download":
        parser.print_help(sys.stderr)
        return 2
    try:
        path = download_epub(
            args.source_url,
            args.output,
            timeout=max(1.0, args.timeout),
            max_bytes=max(1, args.max_bytes),
        )
    except DownloadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        print(f"阅文请求失败：HTTP {exc.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        print(f"阅文网络请求失败：{reason}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"EPUB 写入失败：{exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
