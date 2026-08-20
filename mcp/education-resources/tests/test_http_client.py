"""Tests for the shared HTTP helpers, focused on the curl_on_status retry channel."""

from __future__ import annotations

import io
import os
import shutil
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from education_resource_mcp.adapters.http_client import (
    CurlResponse,
    _curl_available,
    urlopen_with_fallback,
)


def _http_error(url: str, code: int) -> HTTPError:
    return HTTPError(url, code, "err", {}, io.BytesIO(b""))


class UrlopenWithFallbackCurlOnStatusTests(unittest.TestCase):
    URL = "https://example.test/page"

    def setUp(self) -> None:
        self.request = Request(self.URL)

    def test_403_with_curl_on_status_retries_via_curl(self) -> None:
        response = CurlResponse(self.URL, 200, "OK", {}, b"<html>ok</html>")
        with patch(
            "education_resource_mcp.adapters.http_client.urlopen",
            side_effect=_http_error(self.URL, 403),
        ), patch(
            "education_resource_mcp.adapters.http_client._curl_available",
            return_value=True,
        ), patch(
            "education_resource_mcp.adapters.http_client._curl_open",
            return_value=response,
        ) as mocked:
            result = urlopen_with_fallback(
                self.request, timeout=5, curl_on_status=frozenset({403})
            )
        self.assertIs(result, response)
        mocked.assert_called_once()

    def test_403_without_curl_on_status_raises(self) -> None:
        with patch(
            "education_resource_mcp.adapters.http_client.urlopen",
            side_effect=_http_error(self.URL, 403),
        ):
            with self.assertRaises(HTTPError):
                urlopen_with_fallback(self.request, timeout=5)

    def test_status_not_listed_raises_without_curl(self) -> None:
        with patch(
            "education_resource_mcp.adapters.http_client.urlopen",
            side_effect=_http_error(self.URL, 404),
        ), patch(
            "education_resource_mcp.adapters.http_client._curl_available",
            return_value=True,
        ), patch(
            "education_resource_mcp.adapters.http_client._curl_open"
        ) as mocked:
            with self.assertRaises(HTTPError):
                urlopen_with_fallback(
                    self.request, timeout=5, curl_on_status=frozenset({403})
                )
        mocked.assert_not_called()

    def test_curl_availability_uses_platform_binary_name(self) -> None:
        expected = "curl.exe" if os.name == "nt" else "curl"
        with patch.object(shutil, "which", return_value="/usr/bin/curl") as mocked:
            self.assertTrue(_curl_available())
        mocked.assert_called_once_with(expected)

    def test_403_without_curl_binary_raises(self) -> None:
        with patch(
            "education_resource_mcp.adapters.http_client.urlopen",
            side_effect=_http_error(self.URL, 403),
        ), patch(
            "education_resource_mcp.adapters.http_client._curl_available",
            return_value=False,
        ), patch(
            "education_resource_mcp.adapters.http_client._curl_open"
        ) as mocked:
            with self.assertRaises(HTTPError):
                urlopen_with_fallback(
                    self.request, timeout=5, curl_on_status=frozenset({403})
                )
        mocked.assert_not_called()
