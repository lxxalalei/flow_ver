"""Minimal HTTP helpers for credential-bearing session probes."""

from __future__ import annotations

from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent credential-bearing probes from forwarding headers to redirects."""

    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def urlopen_with_fallback(
    request: Request | str,
    timeout: float = 20,
    *,
    follow_redirects: bool = True,
    **kwargs: Any,
) -> Any:
    """Open a URL with urllib.

    The historical function name is retained for compatibility, but this
    standalone package deliberately has no curl fallback: putting Cookie or
    Authorization values on a subprocess command line would expose them to
    local process inspection. Credential-bearing probes also disable redirects.
    """

    if follow_redirects:
        return urlopen(request, timeout=timeout, **kwargs)
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def probe_with_headers(
    url: str, headers: dict[str, str] | None = None, timeout: float = 10.0
) -> tuple[int, str]:
    """GET *url* without redirects and return ``(status_code, body_text)``.

    An HTTP error, including a redirect response, is returned as a status code
    rather than raised. Network and TLS failures remain exceptions so the
    caller can report a transient ``probe_error``. Raw credentials are never
    forwarded to a redirected target or passed through a curl command line.
    """

    merged = {
        "User-Agent": "openclaw-session-manager-probe/0.3",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    if headers:
        merged.update(headers)
    request = Request(url, headers=merged)
    try:
        with urlopen_with_fallback(
            request, timeout=timeout, follow_redirects=False
        ) as response:
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
