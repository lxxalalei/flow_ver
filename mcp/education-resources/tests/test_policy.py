from __future__ import annotations

import ipaddress
from pathlib import Path, PurePosixPath
import sys
import tempfile
import unittest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from education_resource_mcp.policy import (  # noqa: E402
    NetworkPolicy,
    PolicyError,
    PolicyViolation,
    ensure_within_root,
    resolve_client_path,
    validate_client_path,
    validate_public_http_url,
)


class RecordingResolver:
    def __init__(self, answers: dict[str, tuple[str, ...]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int]] = []

    def __call__(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        return self.answers.get(hostname, ())


class NetworkPolicyTests(unittest.TestCase):
    def make_policy(
        self,
        answers: dict[str, tuple[str, ...]] | None = None,
        *,
        allowed_hosts: tuple[str, ...] = ("assets.example",),
        max_redirects: int = 5,
    ) -> tuple[NetworkPolicy, RecordingResolver]:
        resolver = RecordingResolver(
            answers or {"assets.example": ("93.184.216.34",)}
        )
        return (
            NetworkPolicy(
                allowed_hosts=allowed_hosts,
                resolver=resolver,
                max_redirects=max_redirects,
            ),
            resolver,
        )

    def assert_policy_code(self, code: str, callback) -> None:
        with self.assertRaises(PolicyViolation) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_accepts_allowlisted_http_and_https_urls(self) -> None:
        policy, resolver = self.make_policy()

        http = policy.validate_url("http://assets.example/resource?id=1")
        https = policy.validate_url("https://assets.example:8443/resource")

        self.assertEqual(http.hostname, "assets.example")
        self.assertEqual(http.port, 80)
        self.assertEqual(http.addresses, (ipaddress.ip_address("93.184.216.34"),))
        self.assertEqual(https.port, 8443)
        self.assertEqual(
            resolver.calls,
            [("assets.example", 80), ("assets.example", 8443)],
        )

    def test_rejects_non_http_schemes_empty_hosts_and_credentials(self) -> None:
        policy, _resolver = self.make_policy()

        cases = (
            ("ftp://assets.example/file", "unsupported_scheme"),
            ("file:///etc/passwd", "unsupported_scheme"),
            ("https:///missing-host", "empty_host"),
            ("https://user@assets.example/file", "url_credentials"),
            ("https://user:secret@assets.example/file", "url_credentials"),
        )
        for url, code in cases:
            with self.subTest(url=url):
                self.assert_policy_code(code, lambda url=url: policy.validate_url(url))

    def test_rejects_hosts_outside_the_allowlist(self) -> None:
        policy, resolver = self.make_policy()

        self.assert_policy_code(
            "host_not_allowed", lambda: policy.validate_url("https://evil.example/file")
        )
        self.assertEqual(resolver.calls, [])

    def test_supports_explicit_subdomain_patterns(self) -> None:
        policy, _resolver = self.make_policy(
            {"cdn.assets.example": ("93.184.216.34",)},
            allowed_hosts=("*.assets.example",),
        )

        policy.validate_url("https://cdn.assets.example/file")
        self.assert_policy_code(
            "host_not_allowed",
            lambda: policy.validate_url("https://assets.example/file"),
        )

    def test_rejects_empty_and_invalid_resolver_answers(self) -> None:
        empty_policy, _resolver = self.make_policy({"assets.example": ()})
        invalid_policy, _resolver = self.make_policy(
            {"assets.example": ("not-an-ip",)}
        )

        self.assert_policy_code(
            "dns_no_addresses",
            lambda: empty_policy.validate_url("https://assets.example"),
        )
        self.assert_policy_code(
            "resolver_invalid_address",
            lambda: invalid_policy.validate_url("https://assets.example"),
        )

    def test_ip_literals_are_checked_without_calling_dns(self) -> None:
        policy, resolver = self.make_policy(
            allowed_hosts=("93.184.216.34",),
        )

        result = policy.validate_url("https://93.184.216.34/file")

        self.assertEqual(result.addresses, (ipaddress.ip_address("93.184.216.34"),))
        self.assertEqual(resolver.calls, [])

    def test_redirect_targets_are_allowlisted_and_resolved_at_every_hop(self) -> None:
        policy, resolver = self.make_policy(
            {
                "assets.example": ("93.184.216.34",),
                "cdn.example": ("142.250.72.14",),
            },
            allowed_hosts=("assets.example", "cdn.example"),
        )

        result = policy.validate_redirect_chain(
            "https://assets.example/start",
            ("/middle", "https://cdn.example/final"),
        )

        self.assertEqual(result.hostname, "cdn.example")
        self.assertEqual(
            resolver.calls,
            [
                ("assets.example", 443),
                ("assets.example", 443),
                ("cdn.example", 443),
            ],
        )

    def test_redirect_cannot_escape_host_policy(self) -> None:
        host_policy, _resolver = self.make_policy()

        self.assert_policy_code(
            "host_not_allowed",
            lambda: host_policy.validate_redirect(
                "https://assets.example/start", "//evil.example/file"
            ),
        )

    def test_redirect_limit_is_enforced(self) -> None:
        policy, _resolver = self.make_policy(max_redirects=1)

        self.assert_policy_code(
            "too_many_redirects",
            lambda: policy.validate_redirect_chain(
                "https://assets.example/start", ("/one", "/two")
            ),
        )

    def test_redirect_rejects_control_characters_before_url_join(self) -> None:
        policy, _resolver = self.make_policy()

        self.assert_policy_code(
            "redirect_control_character",
            lambda: policy.validate_redirect(
                "https://assets.example/start", "\n//evil.example/file"
            ),
        )

    def test_compatibility_url_helper_supports_injected_dns_and_allowlist(self) -> None:
        resolver = RecordingResolver({"assets.example": ("93.184.216.34",)})

        result = validate_public_http_url(
            "https://assets.example/file",
            allowed_hosts=("assets.example",),
            resolver=resolver,
        )

        self.assertEqual(result.hostname, "assets.example")
        self.assertIs(PolicyError, PolicyViolation)
        self.assertEqual(resolver.calls, [("assets.example", 443)])


class ClientPathPolicyTests(unittest.TestCase):
    def assert_policy_code(self, code: str, value: str) -> None:
        with self.assertRaises(PolicyViolation) as caught:
            validate_client_path(value)
        self.assertEqual(caught.exception.code, code)

    def test_accepts_and_normalizes_relative_client_paths(self) -> None:
        self.assertEqual(
            validate_client_path("courses/./math/lesson.pdf"),
            PurePosixPath("courses/math/lesson.pdf"),
        )
        self.assertEqual(
            validate_client_path(r"courses\math\lesson.pdf"),
            PurePosixPath("courses/math/lesson.pdf"),
        )

    def test_rejects_absolute_posix_windows_drive_and_unc_paths(self) -> None:
        cases = (
            "/etc/passwd",
            r"C:\Windows\system.ini",
            r"C:relative-but-drive-qualified.txt",
            r"\\server\share\file.txt",
            "%2Fetc%2Fpasswd",
        )
        for value in cases:
            with self.subTest(value=value):
                self.assert_policy_code("absolute_client_path", value)

    def test_rejects_plain_encoded_and_double_encoded_traversal(self) -> None:
        cases = (
            "../secret.txt",
            "courses/../../secret.txt",
            r"courses\..\secret.txt",
            "courses/%2e%2e/secret.txt",
            "courses/%252e%252e/secret.txt",
            "courses/%2525252e%2525252e/secret.txt",
            "courses%2f..%2fsecret.txt",
        )
        for value in cases:
            with self.subTest(value=value):
                self.assert_policy_code("path_traversal", value)

    def test_resolves_safe_path_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            root.mkdir()

            result = resolve_client_path(root, "courses/math.pdf")

            self.assertEqual(result, (root / "courses" / "math.pdf").resolve())

    def test_rejects_symlink_escape_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "assets"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            link = root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaises(PolicyViolation) as caught:
                resolve_client_path(root, "linked/secret.txt")
            self.assertEqual(caught.exception.code, "path_traversal")

    def test_ensure_within_root_accepts_server_paths_and_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            root.mkdir()

            self.assertEqual(
                ensure_within_root(root / "job" / "asset.bin", root),
                (root / "job" / "asset.bin").resolve(),
            )
            with self.assertRaises(PolicyViolation) as caught:
                ensure_within_root(root.parent / "outside.bin", root)
            self.assertEqual(caught.exception.code, "path_traversal")


if __name__ == "__main__":
    unittest.main()
