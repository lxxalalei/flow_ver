"""Tests for the SmartEdu ndvideo-key AES-128 key-exchange protocol."""

from __future__ import annotations

import base64
import hashlib
import unittest
from urllib.request import Request

from education_resource_mcp.adapters.smartedu_download import (
    _SMARTEDU_ALLOWED_HOSTS,
    _aes_ecb_unwrap,
    _hls_fetch_decryption_key,
)

_KEY_HOST = "https://ndvideo-key.ykt.eduyun.cn"
_KEY_ID = "4671b9fe85684b7bb785911f5a612e7f"
_KEY_URI = _KEY_HOST + "/v1/resource_keys/" + _KEY_ID


def _pkcs7_pad(payload: bytes) -> bytes:
    pad = 16 - (len(payload) % 16)
    return payload + bytes([pad]) * pad


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.status = 200
        self.offset = 0

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self.body) - self.offset
        value = self.body[self.offset : self.offset + amount]
        self.offset += len(value)
        return value

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def close(self) -> None:
        pass


class _FakeClient:
    """Route URLs to canned bodies and record every request."""

    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes = routes
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float = 30.0):  # noqa: ANN001
        self.requests.append(request)
        url = request.full_url
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                return _FakeResponse(body)
        raise AssertionError("unexpected URL: " + url)


class SmartEduHlsKeyExchangeTests(unittest.TestCase):
    def test_key_host_is_allowlisted(self) -> None:
        self.assertIn("ndvideo-key.ykt.eduyun.cn", _SMARTEDU_ALLOWED_HOSTS)

    def test_key_exchange_returns_material_key(self) -> None:
        material = bytes(range(16))
        nonce = "1788241165041:YnY41K"
        sign = hashlib.md5((nonce + _KEY_ID).encode("utf-8")).hexdigest()[:16]
        from Crypto.Cipher import AES

        sealed = AES.new(sign.encode("utf-8"), AES.MODE_ECB).encrypt(
            _pkcs7_pad(material)
        )
        client = _FakeClient(
            {
                _KEY_URI + "/signs": ('{"nonce": "' + nonce + '"}').encode("utf-8"),
                _KEY_URI: (
                    '{"key": "' + base64.b64encode(sealed).decode("ascii") + '"}'
                ).encode("utf-8"),
            }
        )

        resolved = _hls_fetch_decryption_key(client, _KEY_URI)

        self.assertEqual(resolved, material)
        # 第二个请求必须带 nonce/sign 参数且命中 key 资源本身
        second = client.requests[1]
        self.assertIn("nonce=" + nonce.split(":")[0], second.full_url)
        self.assertIn("sign=" + sign, second.full_url)

    def test_key_exchange_requests_are_bare(self) -> None:
        nonce = "1788241165041:YnY41K"
        sign = hashlib.md5((nonce + _KEY_ID).encode("utf-8")).hexdigest()[:16]
        from Crypto.Cipher import AES

        sealed = AES.new(sign.encode("utf-8"), AES.MODE_ECB).encrypt(
            _pkcs7_pad(bytes(16))
        )
        client = _FakeClient(
            {
                _KEY_URI + "/signs": ('{"nonce": "' + nonce + '"}').encode("utf-8"),
                _KEY_URI: (
                    '{"key": "' + base64.b64encode(sealed).decode("ascii") + '"}'
                ).encode("utf-8"),
            }
        )

        _hls_fetch_decryption_key(client, _KEY_URI)

        for request in client.requests:
            self.assertNotIn("x-nd-auth", {k.lower() for k in request.headers})
            self.assertNotIn("Cookie", {k.lower() for k in request.headers})

    def test_unwrap_rejects_bad_payload_length(self) -> None:
        with self.assertRaises(Exception):
            _aes_ecb_unwrap(b"short", b"0" * 16)


if __name__ == "__main__":
    unittest.main()
