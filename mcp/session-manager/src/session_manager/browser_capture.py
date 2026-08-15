"""Server-side cookie capture from the OpenClaw-managed browser via CDP.

Reads the browser's full cookie store through the Chrome DevTools Protocol
(``Storage.getCookies``), which includes httpOnly cookies that page-context
reads like ``document.cookie`` can never see.  Credential bytes stay inside
this process and go straight into the session store; they are never returned
to the caller.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_CDP_PORT = 18800
_LOOPBACK_HOST = "127.0.0.1"
_HANDSHAKE_TIMEOUT = 10.0
_IO_TIMEOUT = 20.0
_MAX_MESSAGE_BYTES = 64 * 1024 * 1024
_CDP_PORT_ENV = "SESSION_MANAGER_BROWSER_CDP_PORT"
_VALID_SAME_SITE = ("Strict", "Lax", "None")

_OPCODE_CONT = 0x0
_OPCODE_TEXT = 0x1
_OPCODE_BINARY = 0x2
_OPCODE_CLOSE = 0x8
_OPCODE_PING = 0x9
_OPCODE_PONG = 0xA


class BrowserUnavailableError(RuntimeError):
    """The managed browser's CDP endpoint is not reachable right now."""


class CdpProtocolError(RuntimeError):
    """The CDP endpoint answered, but the exchange was malformed."""


def cdp_port_from_env() -> int:
    raw = os.environ.get(_CDP_PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_CDP_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise CdpProtocolError(f"{_CDP_PORT_ENV} 必须是端口号数字") from exc
    if not 1 <= port <= 65535:
        raise CdpProtocolError(f"{_CDP_PORT_ENV} 超出合法端口范围")
    return port


def discover_ws_url(port: int) -> str:
    """Find the browser-level WebSocket debugger URL from the CDP HTTP endpoint."""
    url = f"http://{_LOOPBACK_HOST}:{port}/json/version"
    try:
        with urlopen(url, timeout=_HANDSHAKE_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except (URLError, OSError, ValueError) as exc:
        raise BrowserUnavailableError(
            "受控浏览器 CDP 端点不可达，请先打开 OpenClaw 浏览器再重试"
        ) from exc
    ws_url = body.get("webSocketDebuggerUrl")
    if not isinstance(ws_url, str) or not ws_url.startswith(
        f"ws://{_LOOPBACK_HOST}:{port}/"
    ):
        # Only ever talk to the loopback browser we discovered; anything else
        # would turn this module into a generic remote credential reader.
        raise CdpProtocolError("CDP 端点返回了非预期的 webSocketDebuggerUrl")
    return ws_url


def fetch_browser_cookies(port: int | None = None) -> list[dict[str, Any]]:
    """Return normalized browser cookies (values included; caller must not log)."""
    if port is None:
        port = cdp_port_from_env()
    ws_url = discover_ws_url(port)
    with _CdpConnection(ws_url) as connection:
        result = connection.command("Storage.getCookies")
    raw_cookies = result.get("cookies")
    if not isinstance(raw_cookies, list):
        raise CdpProtocolError("Storage.getCookies 返回结构异常")
    return _normalize_cookies(raw_cookies)


def _normalize_cookies(raw_cookies: list[Any]) -> list[dict[str, Any]]:
    """Map CDP cookie objects onto the store's broad-capture cookie schema.

    Empty-name entries are real browser junk observed in the wild (they make
    ``resource_session_save`` reject the whole payload); drop them here and let
    the store count anything else it discards.
    """
    normalized: list[dict[str, Any]] = []
    for cookie in raw_cookies:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        if not isinstance(name, str) or not name:
            continue
        item: dict[str, Any] = {
            "name": name,
            "value": cookie.get("value") if isinstance(cookie.get("value"), str) else "",
            "domain": cookie.get("domain") if isinstance(cookie.get("domain"), str) else "",
            "path": cookie.get("path") if isinstance(cookie.get("path"), str) else "/",
        }
        for flag in ("secure", "httpOnly"):
            if isinstance(cookie.get(flag), bool):
                item[flag] = cookie[flag]
        expires = cookie.get("expires")
        if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > 0:
            item["expires"] = expires
        if cookie.get("sameSite") in _VALID_SAME_SITE:
            item["sameSite"] = cookie["sameSite"]
        normalized.append(item)
    return normalized


class _CdpConnection:
    """One-command WebSocket client for a CDP browser endpoint.

    Implements just enough of RFC 6455 for a single masked text request and
    one fragmented-or-not text response, so the package needs no WebSocket
    dependency for this capture path.
    """

    def __init__(self, ws_url: str) -> None:
        self._ws_url = ws_url
        self._socket: socket.socket | None = None
        self._buffer = b""
        self._next_id = 1

    def __enter__(self) -> "_CdpConnection":
        prefix, _, rest = self._ws_url.partition("://")
        if prefix != "ws" or "/" not in rest:
            raise CdpProtocolError("CDP WebSocket URL 非法")
        host_port, _, path = rest.partition("/")
        host, _, port_text = host_port.rpartition(":")
        if host != _LOOPBACK_HOST:
            raise CdpProtocolError("CDP 客户端只允许连接 loopback 浏览器")
        try:
            self._socket = socket.create_connection(
                (host, int(port_text)), timeout=_HANDSHAKE_TIMEOUT
            )
        except OSError as exc:
            raise BrowserUnavailableError(
                "受控浏览器 CDP 端点不可达，请先打开 OpenClaw 浏览器再重试"
            ) from exc
        self._handshake(f"/{path}")
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._socket is not None:
            try:
                self._send_frame(_OPCODE_CLOSE, b"")
            except OSError:
                pass
            self._socket.close()
            self._socket = None

    def command(self, method: str) -> dict[str, Any]:
        call_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"id": call_id, "method": method}).encode("utf-8")
        assert self._socket is not None
        self._socket.settimeout(_IO_TIMEOUT)
        self._send_frame(_OPCODE_TEXT, payload)
        while True:
            message = self._read_message()
            try:
                decoded = json.loads(message.decode("utf-8", errors="strict"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise CdpProtocolError("CDP 响应不是合法 JSON") from exc
            if decoded.get("id") == call_id:
                if "error" in decoded:
                    raise CdpProtocolError(
                        f"CDP 命令 {method} 被拒绝：{decoded['error'].get('message', '')}"
                    )
                result = decoded.get("result")
                return result if isinstance(result, dict) else {}

    # -- WebSocket plumbing -------------------------------------------------

    def _handshake(self, path: str) -> None:
        assert self._socket is not None
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {_LOOPBACK_HOST}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode("ascii"))
        while b"\r\n\r\n" not in self._buffer:
            chunk = self._recv_exact_needed()
            if not chunk:
                raise CdpProtocolError("CDP 握手中断")
        header, _, self._buffer = self._buffer.partition(b"\r\n\r\n")
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise CdpProtocolError("CDP WebSocket 握手被拒绝")

    def _recv_exact_needed(self) -> bytes:
        assert self._socket is not None
        try:
            chunk = self._socket.recv(65536)
        except TimeoutError as exc:
            raise CdpProtocolError("CDP 响应超时") from exc
        self._buffer += chunk
        return chunk

    def _read_exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            if not self._recv_exact_needed():
                raise CdpProtocolError("CDP 连接中断")
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _read_message(self) -> bytes:
        fragments = b""
        total = 0
        while True:
            header = self._read_exact(2)
            fin = header[0] & 0x80
            opcode = header[0] & 0x0F
            masked = header[1] & 0x80
            length = header[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            if length > _MAX_MESSAGE_BYTES:
                raise CdpProtocolError("CDP 响应帧超过大小上限")
            mask_key = self._read_exact(4) if masked else b""
            payload = bytearray(self._read_exact(length))
            if masked:
                for index in range(length):
                    payload[index] ^= mask_key[index & 3]
            if opcode == _OPCODE_PING:
                self._send_frame(_OPCODE_PONG, bytes(payload))
                continue
            if opcode == _OPCODE_CLOSE:
                raise CdpProtocolError("CDP 连接在响应前被关闭")
            if opcode in (_OPCODE_TEXT, _OPCODE_BINARY, _OPCODE_CONT):
                fragments += bytes(payload)
                total += length
                if total > _MAX_MESSAGE_BYTES:
                    raise CdpProtocolError("CDP 响应消息超过大小上限")
                if fin:
                    return fragments

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        assert self._socket is not None
        header = bytearray([0x80 | opcode])
        mask_bit = 0x80  # client frames are always masked
        length = len(payload)
        if length < 126:
            header.append(mask_bit | length)
        elif length < 65536:
            header.append(mask_bit | 126)
            header += struct.pack(">H", length)
        else:
            header.append(mask_bit | 127)
            header += struct.pack(">Q", length)
        mask_key = os.urandom(4)
        header += mask_key
        masked = bytes(byte ^ mask_key[index & 3] for index, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + masked)
