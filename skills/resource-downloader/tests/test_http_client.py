from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from http_client import ensure_public_http_url


class HttpClientSafetyTests(unittest.TestCase):
    def test_rejects_localhost_by_default(self) -> None:
        previous = os.environ.pop("LRS_ALLOW_PRIVATE_NETWORK", None)
        try:
            with self.assertRaisesRegex(ValueError, "本机.*内网|本机、内网"):
                ensure_public_http_url("http://127.0.0.1/resource")
        finally:
            if previous is not None:
                os.environ["LRS_ALLOW_PRIVATE_NETWORK"] = previous

    def test_private_network_override_is_explicit(self) -> None:
        previous = os.environ.get("LRS_ALLOW_PRIVATE_NETWORK")
        os.environ["LRS_ALLOW_PRIVATE_NETWORK"] = "1"
        try:
            ensure_public_http_url("http://127.0.0.1/resource")
        finally:
            if previous is None:
                os.environ.pop("LRS_ALLOW_PRIVATE_NETWORK", None)
            else:
                os.environ["LRS_ALLOW_PRIVATE_NETWORK"] = previous

    def test_allows_public_hostname_mapped_to_sandbox_proxy_range(self) -> None:
        previous = os.environ.pop("LRS_ALLOW_PRIVATE_NETWORK", None)
        try:
            with mock.patch(
                "http_client.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("198.18.0.49", 443))],
            ):
                ensure_public_http_url("https://public.example/resource")
        finally:
            if previous is not None:
                os.environ["LRS_ALLOW_PRIVATE_NETWORK"] = previous


if __name__ == "__main__":
    unittest.main()
