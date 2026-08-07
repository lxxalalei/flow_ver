"""Render web pages into standard visual-archive files via Chrome DevTools Protocol.

This module drives a fresh headless Chrome instance over CDP using only the
standard library plus ``websocket-client`` (already a dependency of this
package).  It is used for web-page resources whose content is rendered by
JavaScript and therefore cannot be captured with a plain HTTP GET.

Supported output formats, all produced natively by Chromium:

* ``mhtml`` -> ``Page.captureSnapshot`` (the browser's own "Save as MHTML", a
  standard self-contained web-archive format; Edge/Chrome open it directly)
* ``pdf``   -> ``Page.printToPDF``
* ``png``   -> ``Page.captureScreenshot`` (full-page)

The browser is always spawned as a short-lived, isolated child process with its
own user-data dir and is terminated once rendering finishes.  We deliberately do
not attach to a shared Chrome (e.g. the one OpenClaw drives) so a render job can
never disturb an interactive session.

Security follows the same rules as :class:`PublicHttpDownloader`: the target URL
is validated by the shared outbound policy before navigation, output paths stay
inside the job directory via ``ensure_within_root``, and every produced file is
checked against the configured size limit.
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .errors import DomainError
from .policy import ensure_within_root


class _CDPSession:
    """Minimal CDP client over a browser-level websocket with flattened sessions."""

    def __init__(self, ws_url: str, *, timeout: float = 30.0) -> None:
        import websocket  # lazy import — websocket-client is optional at module load

        self.ws = websocket.create_connection(ws_url, timeout=timeout)
        self._id = 0
        self._lock = threading.Lock()

    def cmd(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            mid = self._id
            payload: dict[str, Any] = {
                "id": mid,
                "method": method,
                "params": params or {},
            }
            if session_id:
                payload["sessionId"] = session_id
            self.ws.send(json.dumps(payload))
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "渲染任务已取消")
                message = json.loads(self.ws.recv())
                if message.get("id") == mid:
                    if "error" in message:
                        raise RuntimeError(
                            f"{method} failed: {message['error']['message']}"
                        )
                    return message.get("result", {})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


_WS_URL_RE = re.compile(rb"DevTools listening on (ws://\S+)")


def _wait_for_devtools_url(
    proc: subprocess.Popen[bytes], timeout: float = 20.0
) -> str:
    """Parse 'DevTools listening on ws://...' from Chrome's stderr."""
    stderr_lines: list[bytes] = []
    found: list[bytes] = []
    lock = threading.Lock()
    deadline = time.monotonic() + timeout

    def drain() -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            with lock:
                stderr_lines.append(line)
                if _WS_URL_RE.search(line) and not found:
                    found.append(line)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    while time.monotonic() < deadline:
        with lock:
            if found:
                match = _WS_URL_RE.search(found[0])
                if match:
                    return match.group(1).decode("utf-8")
        time.sleep(0.05)
    raise DomainError(
        "RENDER_BROWSER_FAILED",
        "无法启动无头 Chrome（未收到 DevTools 监听地址）",
        retryable=True,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _default_chrome() -> str:
    env = os.environ.get("EDUCATION_RESOURCE_MCP_CHROME_BIN", "").strip()
    if env:
        return env
    return "/opt/google/chrome/chrome"


def _render_format(method: str, session: _CDPSession, sid: str) -> bytes:
    """Call the CDP method for one format and return raw file bytes."""
    if method == "mhtml":
        snapshot = session.cmd(
            "Page.captureSnapshot", {"format": "mhtml"}, session_id=sid
        )
        return str(snapshot.get("data", "")).encode("utf-8")
    if method == "pdf":
        result = session.cmd(
            "Page.printToPDF",
            {"printBackground": True, "preferCSSPageSize": False},
            session_id=sid,
        )
        return base64.b64decode(result["data"])
    # png
    shot = session.cmd(
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
        session_id=sid,
    )
    return base64.b64decode(shot["data"])


# Media types are stored without parameters so they match the contract's
# ``^[a-z0-9.+-]+/[a-z0-9.+-]+$`` pattern for asset media_type.
_MEDIA_TYPES = {
    "mhtml": "multipart/related",
    "pdf": "application/pdf",
    "png": "image/png",
}
_SUFFIXES = {"mhtml": ".mhtml", "pdf": ".pdf", "png": ".png"}


class CDPRenderer:
    """Render a URL into MHTML / PDF / PNG using a short-lived headless Chrome."""

    def __init__(
        self,
        *,
        chrome_executable: str | None = None,
        page_timeout_seconds: float = 30.0,
    ) -> None:
        self.chrome_executable = chrome_executable
        self.page_timeout_seconds = page_timeout_seconds

    def _chrome_binary(self) -> str:
        return self.chrome_executable or _default_chrome()

    def _spawn(self) -> tuple[subprocess.Popen[bytes], str, str]:
        """Start a headless Chrome and return ``(process, ws_url, user_data)``."""
        port = _free_port()
        user_data = tempfile.mkdtemp(prefix="edu-render-")
        command = [
            self._chrome_binary(),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_data}",
            "--no-first-run",
            "--noerrdialogs",
            "--hide-scrollbars",
            "--ozone-platform=headless",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise DomainError(
                "RENDER_BROWSER_FAILED",
                f"无法启动无头 Chrome（{exc}）",
                retryable=False,
            ) from exc
        ws_url = _wait_for_devtools_url(process, timeout=20.0)
        return process, ws_url, user_data

    @staticmethod
    def _shutdown(process: subprocess.Popen[bytes], user_data: str) -> None:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        try:
            if os.path.isdir(user_data):
                os.removedirs(user_data)
        except OSError:
            pass

    def render(
        self,
        url: str,
        job_dir: Path,
        *,
        formats: set[str],
        max_bytes: int,
        cancel_event: threading.Event,
        cookies: str = "",
    ) -> list[tuple[Path, str, str, str]]:
        """Render *url* and write requested files under *job_dir*.

        Returns a list of ``(path, media_type, suffix, description)`` tuples,
        one per produced file.  Raises :class:`DomainError` on cancellation,
        oversized output, or rendering failure.
        """
        valid = {"mhtml", "pdf", "png"}
        if not formats:
            raise DomainError("INVALID_ARGUMENT", "不支持的渲染格式")
        wanted = formats & valid
        if not wanted:
            raise DomainError("INVALID_ARGUMENT", "不支持的渲染格式")

        job_dir = ensure_within_root(job_dir, job_dir.parent)  # sanity
        job_dir.mkdir(parents=True, exist_ok=True)
        process: subprocess.Popen[bytes] | None = None
        user_data = ""
        session: _CDPSession | None = None
        produced: list[tuple[Path, str, str, str]] = []
        try:
            process, ws_url, user_data = self._spawn()
            session = _CDPSession(ws_url, timeout=self.page_timeout_seconds + 10)
            created = session.cmd(
                "Target.createTarget", {"url": "about:blank"},
                cancel_event=cancel_event,
            )
            sid = session.cmd(
                "Target.attachToTarget",
                {"targetId": created["targetId"], "flatten": True},
                cancel_event=cancel_event,
            )["sessionId"]
            session.cmd("Page.enable", session_id=sid, cancel_event=cancel_event)
            if cookies:
                session.cmd("Network.enable", session_id=sid, cancel_event=cancel_event)
                cookie_params: list[dict[str, str]] = []
                for part in cookies.split(";"):
                    name, _, value = part.strip().partition("=")
                    if name and value is not None:
                        cookie_params.append({"name": name.strip(), "value": value})
                if cookie_params:
                    session.cmd(
                        "Network.setCookies", {"cookies": cookie_params},
                        session_id=sid, cancel_event=cancel_event,
                    )
            session.cmd(
                "Page.navigate", {"url": url}, session_id=sid,
                cancel_event=cancel_event,
            )
            self._wait_for_page_load(session, sid, cancel_event)

            for fmt in sorted(wanted):
                data_bytes = _render_format(fmt, session, sid)
                if not data_bytes:
                    raise DomainError(
                        "CONTENT_VALIDATION_FAILED",
                        f"{fmt.upper()} 渲染结果为空",
                    )
                if len(data_bytes) > max_bytes:
                    raise DomainError(
                        "DOWNLOAD_TOO_LARGE",
                        f"{fmt.upper()} 超过大小上限",
                        details={"max_bytes": max_bytes, "byte_size": len(data_bytes)},
                    )
                suffix = _SUFFIXES[fmt]
                destination = job_dir / f"page{suffix}"
                destination = ensure_within_root(destination, job_dir)
                destination.write_bytes(data_bytes)
                produced.append(
                    (destination, _MEDIA_TYPES[fmt], suffix, f"rendered {fmt}")
                )
            return produced
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "RENDER_FAILED",
                f"页面渲染失败：{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc
        finally:
            if session is not None:
                session.close()
            self._shutdown(process, user_data)

    def _wait_for_page_load(
        self,
        session: _CDPSession,
        sid: str,
        cancel_event: threading.Event,
    ) -> None:
        """Wait for the DOM to reach ``complete`` before capturing."""
        deadline = time.monotonic() + self.page_timeout_seconds
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise DomainError("JOB_CANCELLED", "渲染任务已取消")
            try:
                result = session.cmd(
                    "Runtime.evaluate",
                    {
                        "expression": (
                            "document.readyState === 'complete' ? 'ready' : 'pending'"
                        ),
                        "returnByValue": True,
                    },
                    session_id=sid,
                    cancel_event=cancel_event,
                )
                if (result.get("result") or {}).get("value") == "ready":
                    return
            except Exception:
                # Target may not be ready yet; keep polling.
                pass
            time.sleep(0.25)
        raise DomainError(
            "RENDER_TIMEOUT",
            f"页面渲染超时（>{self.page_timeout_seconds:.0f}s）",
            retryable=True,
        )
