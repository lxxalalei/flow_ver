"""HTTP helpers shared by platform scripts."""

from __future__ import annotations

import email
import io
import os
import shutil
import ssl
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CurlResponse:
    """Small urllib-compatible response wrapper for curl fallback output."""

    def __init__(self, url: str, status: int, reason: str, headers: Any, body: bytes) -> None:
        self.url = url
        self.status = status
        self.reason = reason
        self.headers = headers
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "CurlResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def urlopen_with_fallback(request: Request | str, timeout: float = 20, **kwargs: Any) -> Any:
    """Open URL with urllib, falling back to Windows curl for local CA issues."""

    try:
        return urlopen(request, timeout=timeout, **kwargs)
    except URLError as exc:
        if not _should_try_curl_fallback(exc):
            raise
        return _curl_open(request, timeout)


def _should_try_curl_fallback(exc: URLError) -> bool:
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


def _curl_open(request: Request | str, timeout: float) -> CurlResponse:
    url = request.full_url if isinstance(request, Request) else str(request)
    method = request.get_method() if isinstance(request, Request) else "GET"
    data = request.data if isinstance(request, Request) else None
    headers = request.header_items() if isinstance(request, Request) else []

    with tempfile.TemporaryDirectory(prefix="lrs-curl-") as temp_dir:
        temp_path = Path(temp_dir)
        header_file = temp_path / "headers.txt"
        body_file = temp_path / "body.bin"
        data_file = temp_path / "request.bin"
        command = [
            "curl.exe",
            "--ssl-no-revoke",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(max(1, int(timeout))),
            "--dump-header",
            str(header_file),
            "--output",
            str(body_file),
            "--request",
            method,
        ]
        for name, value in headers:
            command.extend(["--header", f"{name}: {value}"])
        if data is not None:
            data_file.write_bytes(data)
            command.extend(["--data-binary", f"@{data_file}"])
        command.append(url)

        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"curl exit {completed.returncode}"
            raise URLError(detail)

        raw_headers = header_file.read_text(encoding="iso-8859-1", errors="replace")
        body = body_file.read_bytes() if body_file.exists() else b""
    status, reason, parsed_headers = _parse_curl_headers(raw_headers)
    if status >= 400:
        raise HTTPError(url, status, reason or f"HTTP {status}", parsed_headers, io.BytesIO(body))
    return CurlResponse(url, status, reason, parsed_headers, body)


def _parse_curl_headers(raw: str) -> tuple[int, str, Any]:
    blocks = [block for block in raw.replace("\r\n", "\n").split("\n\n") if block.strip()]
    for block in reversed(blocks):
        lines = block.splitlines()
        if not lines or not lines[0].startswith("HTTP/"):
            continue
        status_line = lines[0].strip()
        parts = status_line.split(" ", 2)
        try:
            status = int(parts[1])
        except (IndexError, ValueError):
            continue
        reason = parts[2] if len(parts) > 2 else ""
        headers = email.message_from_string("\n".join(lines[1:]))
        return status, reason, headers
    return 0, "", email.message_from_string("")
