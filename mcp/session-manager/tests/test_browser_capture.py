"""Server-side CDP cookie capture tests (browser_capture + store integration)."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SERVICE_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from session_manager.browser_capture import (  # noqa: E402
    BrowserUnavailableError,
    CdpProtocolError,
    _normalize_cookies,
    fetch_browser_cookies,
)
from session_manager.store import SessionStore  # noqa: E402


def _cdp_cookie(name: str = "sessionid", **overrides: object) -> dict[str, object]:
    cookie: dict[str, object] = {
        "name": name,
        "value": f"value-of-{name}",
        "domain": ".douyin.com",
        "path": "/",
        "expires": 1893456000.0,
        "size": 24,
        "httpOnly": True,
        "secure": True,
        "session": False,
        "sameSite": "Strict",
        "priority": "Medium",
        "sameParty": False,
        "sourceScheme": "Secure",
    }
    cookie.update(overrides)
    return cookie


class _FakeCdpEndpoint(threading.Thread):
    """Loopback CDP stand-in: HTTP /json/version + one WebSocket round trip."""

    def __init__(self, cookies: list[dict[str, object]]) -> None:
        super().__init__(daemon=True)
        self._cookies = cookies
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._received_command: dict[str, object] | None = None
        self._stop = threading.Event()

    def __enter__(self) -> "_FakeCdpEndpoint":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._server.close()

    @property
    def received_command(self) -> dict[str, object]:
        assert self._received_command is not None
        return self._received_command

    def run(self) -> None:
        self._server.settimeout(2)
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except (OSError, socket.timeout):
                return
            with connection:
                try:
                    self._serve(connection)
                except OSError:
                    return

    def _serve(self, connection: socket.socket) -> None:
        connection.settimeout(10)
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = connection.recv(4096)
            if not chunk:
                return
            request += chunk
        if b"/json/version" in request:
            body = json.dumps(
                {
                    "Browser": "FakeCDP",
                    "webSocketDebuggerUrl": (
                        f"ws://127.0.0.1:{self.port}/devtools/browser/fake"
                    ),
                }
            ).encode("utf-8")
            connection.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                + body
            )
            return
        connection.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: fake\r\n\r\n"
        )
        command = self._read_client_frame(connection)
        self._received_command = json.loads(command.decode("utf-8"))
        response = json.dumps(
            {"id": self._received_command.get("id"), "result": {"cookies": self._cookies}}
        ).encode("utf-8")
        self._write_server_frame(connection, response)

    @staticmethod
    def _read_client_frame(connection: socket.socket) -> bytes:
        header = connection.recv(2)
        if len(header) < 2:
            raise OSError("short frame header")
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", connection.recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", connection.recv(8))[0]
        mask_key = connection.recv(4) if masked else b""
        payload = bytearray()
        while len(payload) < length:
            payload += connection.recv(length - len(payload))
        if masked:
            payload = bytes(
                byte ^ mask_key[index & 3] for index, byte in enumerate(payload)
            )
        return bytes(payload)

    @staticmethod
    def _write_server_frame(connection: socket.socket, payload: bytes) -> None:
        header = bytearray([0x81])  # FIN + text
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header += struct.pack(">H", length)
        else:
            header.append(127)
            header += struct.pack(">Q", length)
        connection.sendall(bytes(header) + payload)


class NormalizeCookieTests(unittest.TestCase):
    def test_drops_empty_name_and_non_dict_entries(self) -> None:
        normalized = _normalize_cookies(
            [_cdp_cookie(), {"name": "", "value": "x", "domain": ".douyin.com"}, "junk"]
        )
        self.assertEqual([cookie["name"] for cookie in normalized], ["sessionid"])

    def test_maps_only_store_schema_fields(self) -> None:
        normalized = _normalize_cookies([_cdp_cookie()])
        self.assertEqual(
            set(normalized[0]),
            {"name", "value", "domain", "path", "secure", "httpOnly", "expires", "sameSite"},
        )
        self.assertTrue(normalized[0]["httpOnly"])
        self.assertEqual(normalized[0]["sameSite"], "Strict")

    def test_session_and_invalid_expires_are_omitted(self) -> None:
        normalized = _normalize_cookies(
            [_cdp_cookie(name="a", expires=-1), _cdp_cookie(name="b", expires="soon")]
        )
        self.assertNotIn("expires", normalized[0])
        self.assertNotIn("expires", normalized[1])

    def test_unknown_samesite_is_dropped(self) -> None:
        normalized = _normalize_cookies([_cdp_cookie(sameSite="NoRestrictions")])
        self.assertNotIn("sameSite", normalized[0])


class FetchBrowserCookiesTests(unittest.TestCase):
    def test_round_trip_against_fake_cdp_endpoint(self) -> None:
        with _FakeCdpEndpoint([_cdp_cookie(), _cdp_cookie(name="")]) as endpoint:
            cookies = fetch_browser_cookies(port=endpoint.port)
        self.assertEqual(
            endpoint.received_command["method"], "Storage.getCookies"
        )
        self.assertEqual([cookie["name"] for cookie in cookies], ["sessionid"])
        self.assertEqual(cookies[0]["value"], "value-of-sessionid")

    def test_unreachable_endpoint_raises_browser_unavailable(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()
        with self.assertRaises(BrowserUnavailableError):
            fetch_browser_cookies(port=closed_port)

    def test_non_loopback_debugger_url_is_rejected(self) -> None:
        with _FakeCdpEndpoint([]) as endpoint:
            with mock.patch(
                "session_manager.browser_capture.discover_ws_url",
                return_value=f"ws://10.9.8.7:{endpoint.port}/devtools/browser/x",
            ):
                with self.assertRaises(CdpProtocolError):
                    fetch_browser_cookies(port=endpoint.port)

    def test_port_env_override(self) -> None:
        with _FakeCdpEndpoint([_cdp_cookie()]) as endpoint:
            with mock.patch.dict(
                "os.environ", {"SESSION_MANAGER_BROWSER_CDP_PORT": str(endpoint.port)}
            ):
                cookies = fetch_browser_cookies()
        self.assertEqual(len(cookies), 1)


class CaptureBrowserToolTests(unittest.TestCase):
    def test_capture_saves_store_schema_and_hides_values(self) -> None:
        from session_manager.server import create_server

        with tempfile.TemporaryDirectory(prefix="sm-capture-") as temp_dir, \
                _FakeCdpEndpoint(
                    [
                        _cdp_cookie(),
                        _cdp_cookie(name="", domain=".douyin.com"),
                        _cdp_cookie(name="other", domain=".example.com"),
                    ]
                ) as endpoint:
            store = SessionStore(Path(temp_dir))
            with mock.patch.dict(
                "os.environ", {"SESSION_MANAGER_BROWSER_CDP_PORT": str(endpoint.port)}
            ):
                server = create_server(store)
                tool = self._tool(server, "resource_session_capture_browser")
                result = tool(
                    contract_version="1.0.0",
                    platform="douyin",
                    idempotency_key="capture-test-0001",
                )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["stored_credential_count"], 1)
        self.assertEqual(result["discarded_credential_count"], 1)
        self.assertEqual(result["captured_cookie_count"], 2)
        self.assertNotIn(
            "value-of-sessionid", json.dumps(result, ensure_ascii=False)
        )

    def test_browser_down_maps_to_retriable_failure(self) -> None:
        from session_manager.server import create_server

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()
        with tempfile.TemporaryDirectory(prefix="sm-capture-down-") as temp_dir:
            store = SessionStore(Path(temp_dir))
            with mock.patch.dict(
                "os.environ", {"SESSION_MANAGER_BROWSER_CDP_PORT": str(closed_port)}
            ):
                server = create_server(store)
                tool = self._tool(server, "resource_session_capture_browser")
                result = tool(contract_version="1.0.0", platform="douyin")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "BROWSER_UNAVAILABLE")
        self.assertTrue(result["error"]["retriable"])

    @staticmethod
    def _tool(server: object, name: str):
        tools = server._tool_manager.list_tools()  # noqa: SLF001 - test seam
        for entry in tools:
            if entry.name == name:
                return entry.fn
        raise AssertionError(f"tool {name} not registered")


if __name__ == "__main__":
    unittest.main()
