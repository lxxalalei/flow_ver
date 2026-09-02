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
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

# Console-subsystem children (curl fallback) must not pop a visible console
# window when the MCP server runs under a hidden gateway parent on Windows.
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class _NoRedirectHandler(HTTPRedirectHandler):
    """Keep redirect responses visible to application-owned policy loops."""

    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
        return None


class CurlResponse:
    """Small urllib-compatible response wrapper for curl fallback output."""

    def __init__(self, url: str, status: int, reason: str, headers: Any, body: bytes) -> None:
        self.url = url
        self.status = status
        self.reason = reason
        self.headers = headers
        self._body = body
        self._offset = 0

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            amount = len(self._body) - self._offset
        value = self._body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def __enter__(self) -> "CurlResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def urlopen_with_fallback(
    request: Request | str,
    timeout: float = 20,
    *,
    follow_redirects: bool = True,
    curl_on_status: frozenset[int] | None = None,
    **kwargs: Any,
) -> Any:
    """Open URL with urllib, falling back to Windows curl for local CA issues.

    ``curl_on_status`` optionally lists HTTP status codes (e.g. ``403``) for
    which a system curl retry is attempted when the primary urllib request is
    rejected, e.g. by bot fingerprinting. A failed curl retry preserves the
    normal HTTP error behaviour.
    """

    try:
        if follow_redirects:
            return urlopen(request, timeout=timeout, **kwargs)
        if kwargs:
            raise TypeError("no-redirect requests do not accept urlopen keyword options")
        return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)
    except URLError as exc:
        if (
            isinstance(exc, HTTPError)
            and curl_on_status is not None
            and exc.code in curl_on_status
            and _curl_available()
        ):
            return _curl_open(request, timeout, follow_redirects=follow_redirects)
        if not _should_try_curl_fallback(exc):
            raise
        return _curl_open(request, timeout, follow_redirects=follow_redirects)


def probe_with_headers(
    url: str, headers: dict[str, str] | None = None, timeout: float = 10.0
) -> tuple[int, str]:
    """GET *url* with arbitrary request headers and return ``(status_code, body_text)``.

    Used by the session store to verify whether a stored platform session is
    still accepted — pass a ``Cookie`` header for cookie platforms, or
    ``Authorization`` / custom headers for token platforms.  An HTTP error
    status (4xx/5xx) is returned as the status code rather than raised — the
    caller interprets a 401/403 as "session invalid".  ``URLError``
    (connection refused, timeout, DNS) is re-raised so the caller can mark
    the probe as a transient error.
    """
    merged = {
        "User-Agent": "education-resource-mcp-session-probe/1.0",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    if headers:
        merged.update(headers)
    request = Request(url, headers=merged)
    try:
        with urlopen_with_fallback(request, timeout=timeout) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            status = getattr(response, "status", 200)
            return status, body.decode(charset, errors="replace")
    except HTTPError as exc:
        raw = exc.read()
        charset = (exc.headers.get_content_charset() if exc.headers else None) or "utf-8"
        body = raw.decode(charset, errors="replace") if raw else ""
        return exc.code, body


def probe_with_cookies(
    url: str, cookie_header: str = "", timeout: float = 10.0
) -> tuple[int, str]:
    """Shorthand for :func:`probe_with_headers` with a single Cookie header."""
    headers = {"Cookie": cookie_header} if cookie_header else None
    return probe_with_headers(url, headers, timeout)


def _curl_available() -> bool:
    binary = "curl.exe" if os.name == "nt" else "curl"
    return shutil.which(binary) is not None


def _should_try_curl_fallback(exc: URLError) -> bool:
    if os.environ.get("LRS_HTTP_DISABLE_CURL_FALLBACK"):
        return False
    # Preserve the original Windows-only certificate workaround. Other
    # platforms use curl only when a caller explicitly opts into a status code.
    if os.name != "nt":
        return False
    if not _curl_available():
        return False
    reason = getattr(exc, "reason", exc)
    message = str(reason).lower()
    return (
        isinstance(reason, ssl.SSLCertVerificationError)
        or "certificate_verify_failed" in message
        or "certificate verify failed" in message
        or "unexpected_eof_while_reading" in message
    )


def _curl_open(
    request: Request | str,
    timeout: float,
    *,
    follow_redirects: bool = True,
) -> CurlResponse:
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
            "curl.exe" if os.name == "nt" else "curl",
            "--silent",
            "--show-error",
        ]
        if os.name == "nt":
            command.append("--ssl-no-revoke")
        if follow_redirects:
            command.append("--location")
        command.extend(
            [
                "--max-time",
                str(max(1, int(timeout))),
                "--dump-header",
                str(header_file),
                "--output",
                str(body_file),
                "--request",
                method,
            ]
        )
        for name, value in headers:
            command.extend(["--header", f"{name}: {value}"])
        if data is not None:
            data_file.write_bytes(data)
            command.extend(["--data-binary", f"@{data_file}"])
        command.append(url)

        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            creationflags=_SUBPROCESS_FLAGS,
        )
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
