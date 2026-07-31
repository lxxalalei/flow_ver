"""Small HTTP helper with a Windows certificate-store fallback."""

from __future__ import annotations

import email
import io
import ipaddress
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


SANDBOX_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class BufferedResponse:
    def __init__(self, url: str, status: int, reason: str, headers: Any, body: bytes) -> None:
        self._url = url
        self.status = status
        self.reason = reason
        self.headers = headers
        self._body = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "BufferedResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        self._body.close()


def urlopen_with_fallback(request: Request | str, timeout: float = 20, **kwargs: Any) -> Any:
    url = request.full_url if isinstance(request, Request) else str(request)
    ensure_public_http_url(url)
    try:
        opener = build_opener(_SafeRedirectHandler())
        return opener.open(request, timeout=timeout, **kwargs)
    except URLError as exc:
        if not _should_use_curl(exc):
            raise
        return _curl_open(request, timeout)


def ensure_public_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL 必须是绝对 http/https 地址")
    if os.environ.get("LRS_ALLOW_PRIVATE_NETWORK") == "1":
        return
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("不允许访问本机或内网地址")
    try:
        literal_ip = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise ValueError("不允许直接访问本机、内网或保留 IP 地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 0, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise URLError(f"DNS 解析失败: {hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if literal_ip is None and ip in SANDBOX_PROXY_NETWORK:
            continue
        if not ip.is_global:
            raise ValueError("不允许访问本机、内网或保留地址")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:
        ensure_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _should_use_curl(exc: URLError) -> bool:
    if os.environ.get("LRS_HTTP_DISABLE_CURL_FALLBACK"):
        return False
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


def _curl_open(request: Request | str, timeout: float) -> BufferedResponse:
    current_url = request.full_url if isinstance(request, Request) else str(request)
    method = request.get_method() if isinstance(request, Request) else "GET"
    data = request.data if isinstance(request, Request) else None
    headers = request.header_items() if isinstance(request, Request) else []
    for _redirect in range(10):
        ensure_public_http_url(current_url)
        with tempfile.TemporaryDirectory(prefix="downloader-http-") as temp_dir:
            temp_path = Path(temp_dir)
            header_file = temp_path / "headers.txt"
            body_file = temp_path / "body.bin"
            data_file = temp_path / "request.bin"
            command = [
                "curl.exe", "--ssl-no-revoke", "--silent", "--show-error",
                "--max-time", str(max(1, int(timeout))), "--dump-header", str(header_file),
                "--output", str(body_file), "--request", method,
            ]
            for name, value in headers:
                command.extend(["--header", f"{name}: {value}"])
            if data is not None:
                data_file.write_bytes(data)
                command.extend(["--data-binary", f"@{data_file}"])
            command.append(current_url)
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip() or f"curl exit {completed.returncode}"
                raise URLError(detail)
            raw_headers = header_file.read_text(encoding="iso-8859-1", errors="replace")
            body = body_file.read_bytes() if body_file.exists() else b""
        status, reason, parsed_headers = _parse_headers(raw_headers)
        location = parsed_headers.get("Location")
        if status in {301, 302, 303, 307, 308} and location:
            current_url = urljoin(current_url, location)
            if status in {301, 302, 303} and method not in {"GET", "HEAD"}:
                method, data = "GET", None
            continue
        if status >= 400:
            raise HTTPError(current_url, status, reason or f"HTTP {status}", parsed_headers, io.BytesIO(body))
        return BufferedResponse(current_url, status, reason, parsed_headers, body)
    raise URLError("重定向次数过多")


def _parse_headers(raw: str) -> tuple[int, str, Any]:
    blocks = [block for block in raw.replace("\r\n", "\n").split("\n\n") if block.strip()]
    for block in reversed(blocks):
        lines = block.splitlines()
        if not lines or not lines[0].startswith("HTTP/"):
            continue
        parts = lines[0].strip().split(" ", 2)
        try:
            status = int(parts[1])
        except (IndexError, ValueError):
            continue
        reason = parts[2] if len(parts) > 2 else ""
        return status, reason, email.message_from_string("\n".join(lines[1:]))
    return 0, "", email.message_from_string("")
