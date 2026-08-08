from __future__ import annotations

from pathlib import Path
import sys
import threading
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition.web_fetch import (  # noqa: E402
    BoundedWebFetcher,
    FETCH_AUTH_REQUIRED,
    FETCH_CANCELLED,
    FETCH_CONTENT_INVALID,
    FETCH_NETWORK_BLOCKED,
    FETCH_PLATFORM_UNAVAILABLE,
    FETCH_REDIRECT_BLOCKED,
    FETCH_TIMEOUT,
    FETCH_TOO_LARGE,
    FETCH_TOO_MANY_REDIRECTS,
    FetchError,
    detect_image_format,
    validate_html_payload,
    validate_image_payload,
)


PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        final_url: str | None = None,
        chunks: list[bytes] | None = None,
        on_read=None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._offset = 0
        self._chunks = list(chunks) if chunks is not None else None
        self._final_url = final_url
        self._on_read = on_read
        self.read_calls = 0
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        self.read_calls += 1
        if self._on_read is not None:
            self._on_read(self.read_calls)
        if self._chunks is not None:
            return self._chunks.pop(0) if self._chunks else b""
        if amount < 0:
            amount = len(self._body) - self._offset
        value = self._body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def geturl(self) -> str:
        return self._final_url or "https://public.test/resource"

    def close(self) -> None:
        self.closed = True


class QueueTransport:
    def __init__(self, *responses: FakeResponse, error: BaseException | None = None) -> None:
        self.responses = list(responses)
        self.error = error
        self.requests: list[tuple[object, float | None]] = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if response._final_url is None:
            response._final_url = request.full_url
        return response


def public_resolver(hostname: str, port: int):
    if hostname == "private.test":
        return ("10.0.0.8",)
    if hostname == "link-local.test":
        return ("169.254.169.254",)
    return (PUBLIC_IP,)


def fetcher(transport: QueueTransport, **kwargs) -> BoundedWebFetcher:
    return BoundedWebFetcher(
        resolver=public_resolver,
        transport=transport,
        timeout=0.25,
        **kwargs,
    )


def error_code(callback) -> str:
    with unittest.TestCase().assertRaises(FetchError) as caught:
        callback()
    return caught.exception.code


class WebFetchTests(unittest.TestCase):
    def test_initial_private_link_local_and_metadata_targets_are_blocked(self) -> None:
        for url in (
            "http://127.0.0.1/private",
            "http://localhost/private",
            "http://10.0.0.8/private",
            "https://169.254.169.254/latest/meta-data",
            "https://metadata.google.internal/computeMetadata/v1",
            "https://private.test/private",
            "https://link-local.test/private",
        ):
            with self.subTest(url=url):
                transport = QueueTransport()
                self.assertEqual(
                    FETCH_NETWORK_BLOCKED,
                    error_code(lambda url=url: fetcher(transport).fetch(url)),
                )
                self.assertEqual([], transport.requests)

    def test_redirects_are_explicitly_followed_and_request_has_no_auth_or_cookie(self) -> None:
        first = FakeResponse(
            status=302,
            headers={"Location": "https://public.test/final"},
        )
        second = FakeResponse(
            headers={"Content-Type": "text/plain"},
            body=b"ok",
        )
        transport = QueueTransport(first, second)
        result = fetcher(transport).fetch("https://public.test/start")

        self.assertEqual("https://public.test/final", result.url)
        self.assertEqual(1, result.redirect_count)
        self.assertEqual(2, len(transport.requests))
        for request, timeout in transport.requests:
            self.assertEqual(0.25, timeout)
            header_names = {name.casefold() for name in request.headers}
            self.assertNotIn("cookie", header_names)
            self.assertNotIn("authorization", header_names)
            self.assertNotIn("proxy-authorization", header_names)

    def test_redirect_target_and_final_url_are_validated_before_use(self) -> None:
        malicious_redirect = FakeResponse(
            status=302,
            headers={"Location": "http://127.0.0.1/metadata"},
        )
        transport = QueueTransport(malicious_redirect)
        self.assertEqual(
            FETCH_REDIRECT_BLOCKED,
            error_code(lambda: fetcher(transport).fetch("https://public.test/start")),
        )
        self.assertEqual(1, len(transport.requests))

        unsafe_final = FakeResponse(
            headers={"Content-Type": "text/plain"},
            body=b"secret",
            final_url="http://127.0.0.1/metadata",
        )
        transport = QueueTransport(unsafe_final)
        self.assertEqual(
            FETCH_REDIRECT_BLOCKED,
            error_code(lambda: fetcher(transport).fetch("https://public.test/start")),
        )

    def test_redirect_limit_is_five(self) -> None:
        responses = [
            FakeResponse(
                status=302,
                headers={"Location": f"https://public.test/hop-{index}"},
            )
            for index in range(6)
        ]
        transport = QueueTransport(*responses)
        self.assertEqual(
            FETCH_TOO_MANY_REDIRECTS,
            error_code(lambda: fetcher(transport).fetch("https://public.test/start")),
        )
        self.assertEqual(6, len(transport.requests))

    def test_transport_that_auto_follows_is_rejected(self) -> None:
        response = FakeResponse(
            headers={"Content-Type": "text/plain"},
            body=b"followed",
            final_url="https://public.test/final",
        )
        transport = QueueTransport(response)
        self.assertEqual(
            FETCH_REDIRECT_BLOCKED,
            error_code(lambda: fetcher(transport).fetch("https://public.test/start")),
        )

    def test_declared_and_streaming_byte_limits_are_enforced(self) -> None:
        declared = FakeResponse(
            headers={"Content-Type": "text/plain", "Content-Length": "11"},
            body=b"not-read",
        )
        transport = QueueTransport(declared)
        self.assertEqual(
            FETCH_TOO_LARGE,
            error_code(lambda: fetcher(transport, max_bytes=10).fetch("https://public.test/start")),
        )
        self.assertEqual(0, declared.read_calls)

        streaming = FakeResponse(
            headers={"Content-Type": "text/plain"},
            chunks=[b"123456", b"7"],
        )
        transport = QueueTransport(streaming)
        self.assertEqual(
            FETCH_TOO_LARGE,
            error_code(lambda: fetcher(transport, max_bytes=6).fetch("https://public.test/start")),
        )

    def test_cancellation_is_checked_before_request_and_between_chunks(self) -> None:
        event = threading.Event()
        transport = QueueTransport()
        event.set()
        self.assertEqual(
            FETCH_CANCELLED,
            error_code(
                lambda: fetcher(transport).fetch(
                    "https://public.test/start", cancel_event=event
                )
            ),
        )
        self.assertEqual([], transport.requests)

        def cancel_after_first_read(read_calls: int) -> None:
            if read_calls == 1:
                event.set()

        response = FakeResponse(
            headers={"Content-Type": "text/plain"},
            chunks=[b"first", b"second"],
            on_read=cancel_after_first_read,
        )
        transport = QueueTransport(response)
        event.clear()
        self.assertEqual(
            FETCH_CANCELLED,
            error_code(
                lambda: fetcher(transport).fetch(
                    "https://public.test/start", cancel_event=event
                )
            ),
        )
        self.assertTrue(response.closed)

    def test_timeout_and_auth_statuses_are_stable(self) -> None:
        transport = QueueTransport(error=TimeoutError())
        with self.assertRaises(FetchError) as caught:
            fetcher(transport).fetch("https://public.test/start")
        self.assertEqual(FETCH_TIMEOUT, caught.exception.code)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(FETCH_TIMEOUT, caught.exception.failure.to_dict()["code"])

        auth = QueueTransport(FakeResponse(status=403))
        self.assertEqual(
            FETCH_AUTH_REQUIRED,
            error_code(lambda: fetcher(auth).fetch("https://public.test/start")),
        )

        unavailable = QueueTransport(FakeResponse(status=503))
        with self.assertRaises(FetchError) as caught:
            fetcher(unavailable).fetch("https://public.test/start")
        self.assertEqual(FETCH_PLATFORM_UNAVAILABLE, caught.exception.code)
        self.assertTrue(caught.exception.retryable)


class ContentValidationTests(unittest.TestCase):
    def test_html_requires_supported_mime_and_basic_magic(self) -> None:
        body = b"<!doctype html><html><body><p>hello</p></body></html>"
        self.assertEqual("text/html", validate_html_payload(body, "text/html; charset=utf-8"))

        for media_type, invalid_body in (
            ("text/plain", body),
            ("text/html", b"plain text without markup"),
            (None, body),
        ):
            with self.subTest(media_type=media_type):
                with self.assertRaises(FetchError) as caught:
                    validate_html_payload(invalid_body, media_type)
                self.assertEqual(FETCH_CONTENT_INVALID, caught.exception.code)

    def test_fetch_html_runs_the_same_validation(self) -> None:
        response = FakeResponse(
            headers={"Content-Type": "application/xhtml+xml; charset=utf-8"},
            body=b"<html><body>safe</body></html>",
        )
        result = fetcher(QueueTransport(response)).fetch_html("https://public.test/page")
        self.assertEqual("application/xhtml+xml", result.media_type)

    def test_image_magic_helper_supports_only_four_raster_formats(self) -> None:
        cases = (
            (b"\xff\xd8\xff" + b"jpeg", "image/jpeg"),
            (b"\x89PNG\r\n\x1a\n" + b"png", "image/png"),
            (b"GIF89a" + b"gif", "image/gif"),
            (b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"webp", "image/webp"),
        )
        for body, media_type in cases:
            with self.subTest(media_type=media_type):
                detected = detect_image_format(body)
                self.assertIsNotNone(detected)
                self.assertEqual(media_type, detected.media_type)
                self.assertEqual(media_type, validate_image_payload(body, media_type).media_type)

    def test_image_mime_must_match_magic_and_svg_is_rejected(self) -> None:
        png = b"\x89PNG\r\n\x1a\nminimal"
        with self.assertRaises(FetchError) as caught:
            validate_image_payload(png, "image/jpeg")
        self.assertEqual(FETCH_CONTENT_INVALID, caught.exception.code)

        with self.assertRaises(FetchError) as caught:
            validate_image_payload(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml")
        self.assertEqual(FETCH_CONTENT_INVALID, caught.exception.code)

        with self.assertRaises(FetchError) as caught:
            validate_image_payload(b"not an image", "image/png")
        self.assertEqual(FETCH_CONTENT_INVALID, caught.exception.code)

    def test_fetch_image_validates_declared_mime_and_magic(self) -> None:
        response = FakeResponse(
            headers={"Content-Type": "image/gif"},
            body=b"GIF87a" + b"payload",
        )
        result, image_format = BoundedWebFetcher(
            resolver=public_resolver,
            transport=QueueTransport(response),
        ).fetch_image("https://public.test/image")
        self.assertEqual("image/gif", result.media_type)
        self.assertEqual(".gif", image_format.extension)


if __name__ == "__main__":
    unittest.main()
