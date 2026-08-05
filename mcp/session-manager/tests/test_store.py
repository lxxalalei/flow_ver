"""Behavior and security tests for the standalone local session store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SERVICE_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from session_manager.http_client import probe_with_headers  # noqa: E402
from session_manager.store import (  # noqa: E402
    MAX_COOKIE_COUNT,
    SessionError,
    SessionStore,
)
from session_manager.windows_dpapi import (  # noqa: E402
    WindowsDpapiError,
    WindowsDpapiProtector,
)


def _future_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _home_temp_directory(prefix: str = "session-manager-test-"):
    return tempfile.TemporaryDirectory(prefix=prefix, dir=Path.home())


def _permission_mode(path: Path) -> int:
    """Read actual POSIX mode bits, including in hosts that mask Python stat results."""
    python_mode = stat.S_IMODE(path.stat().st_mode)
    if os.name != "posix":
        return python_mode
    try:
        completed = subprocess.run(
            ["stat", "-c", "%a", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return int(completed.stdout.strip(), 8)
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return python_mode


def _cookie(
    name: str = "SESSDATA",
    value: str = "cookie-secret",
    domain: str = ".bilibili.com",
    **extra: object,
) -> dict[str, object]:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        **extra,
    }


class _FakeCredentialProtector:
    format_name = "test-protector-v1"

    def protect(self, plaintext: bytes, *, purpose: str) -> bytes:
        return b"protected:" + purpose.encode("ascii") + b":" + plaintext[::-1]

    def unprotect(self, ciphertext: bytes, *, purpose: str) -> bytes:
        prefix = b"protected:" + purpose.encode("ascii") + b":"
        if not ciphertext.startswith(prefix):
            raise WindowsDpapiError("invalid test ciphertext")
        return ciphertext[len(prefix) :][::-1]


class _FailingCredentialProtector(_FakeCredentialProtector):
    def unprotect(self, ciphertext: bytes, *, purpose: str) -> bytes:
        raise WindowsDpapiError("simulated DPAPI failure")


class SessionStoreSecurityTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable to Windows")
    def test_directories_and_records_are_owner_only(self) -> None:
        # This test must run on a filesystem that preserves POSIX modes. Some
        # sandboxed /tmp mounts intentionally report a fixed 0777 and ignore chmod.
        with _home_temp_directory("session-manager-permissions-") as temp_dir:
            root = Path(temp_dir) / "session-data"
            root.mkdir(mode=0o777)
            os.chmod(root, 0o777)

            store = SessionStore(root)
            result = store.save(
                "bilibili",
                {"cookies": [_cookie()]},
                idempotency_key="permission-save-01",
            )

            self.assertFalse(result["idempotent_replay"])
            self.assertEqual(_permission_mode(root), 0o700)
            self.assertEqual(_permission_mode(store.sessions_dir), 0o700)
            self.assertEqual(_permission_mode(store.operations_dir), 0o700)

            session_path = store.sessions_dir / "bilibili.json"
            ledger_paths = list(store.operations_dir.glob("*.json"))
            self.assertEqual(_permission_mode(session_path), 0o600)
            self.assertEqual(len(ledger_paths), 1)
            self.assertEqual(_permission_mode(ledger_paths[0]), 0o600)

    def test_relative_data_directory_is_rejected(self) -> None:
        with self.assertRaises(SessionError) as caught:
            SessionStore(Path("relative-session-data"))

        self.assertEqual(caught.exception.code, "UNSAFE_DATA_PATH")

    def test_native_windows_dpapi_initialization_failure_is_fail_closed(self) -> None:
        data_dir = Path.home() / "unused-native-windows-session-data"
        with patch("session_manager.store.os.name", "nt"), patch(
            "session_manager.store.WindowsDpapiProtector",
            side_effect=WindowsDpapiError("unavailable"),
        ):
            with self.assertRaises(SessionError) as caught:
                SessionStore(data_dir)

        self.assertEqual(caught.exception.code, "SECURE_STORAGE_UNAVAILABLE")

    @unittest.skipIf(os.name != "posix", "POSIX permission failures are not portable")
    def test_directory_permission_failure_is_rejected(self) -> None:
        with _home_temp_directory("session-manager-permission-failure-") as temp_dir:
            root = Path(temp_dir) / "session-data"
            with patch.object(Path, "chmod", side_effect=PermissionError("denied")):
                with self.assertRaises(SessionError) as caught:
                    SessionStore(root)

            self.assertEqual(caught.exception.code, "UNSAFE_DATA_PATH")

    @unittest.skipIf(os.name != "posix", "POSIX permission failures are not portable")
    def test_non_owner_only_record_is_rejected_on_read(self) -> None:
        with _home_temp_directory("session-manager-unsafe-record-") as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            store.save("bilibili", {"cookies": [_cookie()]})
            record_path = store.sessions_dir / "bilibili.json"
            record_path.chmod(0o640)

            with self.assertRaises(SessionError) as caught:
                store.get_status(["bilibili"])

            self.assertEqual(caught.exception.code, "UNSAFE_DATA_PATH")

    @unittest.skipIf(not hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_symlink_data_directory_is_rejected(self) -> None:
        with _home_temp_directory() as temp_dir:
            root = Path(temp_dir)
            target = root / "real"
            target.mkdir()
            link = root / "linked"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"当前环境不能创建目录链接：{exc}")

            with self.assertRaises(SessionError) as caught:
                SessionStore(link)

            self.assertEqual(caught.exception.code, "UNSAFE_DATA_PATH")

    def test_atomic_write_leaves_no_temporary_credential_file(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            with patch("session_manager.store.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    store.save("bilibili", {"cookies": [_cookie()]})

            self.assertFalse((store.sessions_dir / "bilibili.json").exists())
            self.assertEqual(list(store.sessions_dir.glob(".bilibili.json.*")), [])

    def test_protected_session_record_is_not_plaintext_and_round_trips(self) -> None:
        with _home_temp_directory() as temp_dir:
            root = Path(temp_dir) / "data"
            protector = _FakeCredentialProtector()
            store = SessionStore(root, _credential_protector=protector)
            secret = "cookie-value-must-be-encrypted"

            store.save("bilibili", {"cookies": [_cookie(value=secret)]})
            record_path = store.sessions_dir / "bilibili.json"
            stored_bytes = record_path.read_bytes()
            envelope = json.loads(stored_bytes.decode("ascii"))

            self.assertNotIn(secret.encode("utf-8"), stored_bytes)
            self.assertEqual(envelope["format"], protector.format_name)
            reopened = SessionStore(root, _credential_protector=protector)
            session_data = reopened.get_session_data("bilibili")
            self.assertEqual(session_data["cookies"][0]["value"], secret)

    def test_protected_temporary_record_is_ciphertext_before_replace(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(
                Path(temp_dir) / "data",
                _credential_protector=_FakeCredentialProtector(),
            )
            secret = "temporary-file-must-never-contain-this-cookie"
            observed: dict[str, bytes] = {}

            def inspect_then_fail(source: str | os.PathLike[str], _target: object) -> None:
                observed["temporary"] = Path(source).read_bytes()
                raise OSError("replace failed after inspection")

            with patch("session_manager.store.os.replace", side_effect=inspect_then_fail):
                with self.assertRaises(OSError):
                    store.save("bilibili", {"cookies": [_cookie(value=secret)]})

            self.assertIn("temporary", observed)
            self.assertNotIn(secret.encode("utf-8"), observed["temporary"])
            self.assertIn(b"test-protector-v1", observed["temporary"])
            self.assertEqual(list(store.sessions_dir.glob(".bilibili.json.*")), [])

    def test_protected_store_rejects_plaintext_credential_record(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(
                Path(temp_dir) / "data",
                _credential_protector=_FakeCredentialProtector(),
            )
            path = store.sessions_dir / "bilibili.json"
            path.write_text(
                json.dumps(
                    {
                        "platform": "bilibili",
                        "auth_kind": "cookie",
                        "session_data": {"cookies": [_cookie()]},
                    }
                ),
                encoding="utf-8",
            )
            if os.name == "posix":
                path.chmod(0o600)

            with self.assertRaises(SessionError) as caught:
                store.get_status(["bilibili"])

            self.assertEqual(caught.exception.code, "SECURE_STORAGE_UNAVAILABLE")

    def test_protected_store_reports_decryption_failure(self) -> None:
        with _home_temp_directory() as temp_dir:
            root = Path(temp_dir) / "data"
            SessionStore(
                root, _credential_protector=_FakeCredentialProtector()
            ).save("bilibili", {"cookies": [_cookie()]})
            failing = SessionStore(
                root, _credential_protector=_FailingCredentialProtector()
            )

            with self.assertRaises(SessionError) as caught:
                failing.get_session_data("bilibili")

            self.assertEqual(caught.exception.code, "SECURE_STORAGE_UNAVAILABLE")

    def test_protected_session_is_bound_to_platform_purpose(self) -> None:
        with _home_temp_directory() as temp_dir:
            root = Path(temp_dir) / "data"
            store = SessionStore(
                root, _credential_protector=_FakeCredentialProtector()
            )
            store.save("bilibili", {"cookies": [_cookie()]})
            source = store.sessions_dir / "bilibili.json"
            target = store.sessions_dir / "zhihu.json"
            target.write_bytes(source.read_bytes())
            if os.name == "posix":
                target.chmod(0o600)

            with self.assertRaises(SessionError) as caught:
                store.get_status(["zhihu"])

            self.assertEqual(caught.exception.code, "SECURE_STORAGE_UNAVAILABLE")

    @unittest.skipUnless(os.name == "nt", "requires native Windows DPAPI")
    def test_native_windows_dpapi_round_trip(self) -> None:
        with _home_temp_directory("session-manager-windows-dpapi-") as temp_dir:
            root = Path(temp_dir) / "data"
            store = SessionStore(root)
            secret = "native-windows-dpapi-cookie"

            store.save("bilibili", {"cookies": [_cookie(value=secret)]})
            stored_bytes = (store.sessions_dir / "bilibili.json").read_bytes()

            self.assertNotIn(secret.encode("utf-8"), stored_bytes)
            self.assertIn(b"windows-dpapi-v1", stored_bytes)
            self.assertEqual(
                store.get_session_data("bilibili")["cookies"][0]["value"],
                secret,
            )


    @unittest.skipUnless(os.name == "nt", "requires native Windows paths")
    def test_native_windows_rejects_unc_data_directory(self) -> None:
        with self.assertRaises(SessionError) as caught:
            SessionStore(Path(r"\\localhost\openclaw-session-manager-test"))

        self.assertEqual(caught.exception.code, "UNSAFE_DATA_PATH")

    @unittest.skipUnless(os.name == "nt", "requires native Windows DPAPI")
    def test_native_windows_unicode_path_and_child_process_round_trip(self) -> None:
        with _home_temp_directory("session-manager-windows-child-") as temp_dir:
            root = Path(temp_dir) / "OpenClaw 登录态 测试"
            secret = "native-windows-child-process-cookie"
            SessionStore(root).save(
                "bilibili", {"cookies": [_cookie(value=secret)]}
            )
            environment = {
                **os.environ,
                "PYTHONPATH": str(SOURCE_ROOT),
                "SESSION_MANAGER_TEST_DATA_DIR": str(root),
                "SESSION_MANAGER_TEST_SECRET": secret,
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            script = """
import os
from pathlib import Path
from session_manager.store import SessionStore

data = SessionStore(Path(os.environ["SESSION_MANAGER_TEST_DATA_DIR"])).get_session_data("bilibili")
expected = os.environ["SESSION_MANAGER_TEST_SECRET"]
raise SystemExit(0 if data and data["cookies"][0]["value"] == expected else 3)
"""

            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=SERVICE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(
                completed.returncode,
                0,
                msg=f"child stderr: {completed.stderr}",
            )
            self.assertNotIn(secret, completed.stdout)
            self.assertNotIn(secret, completed.stderr)


class WindowsDpapiTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires native Windows DPAPI")
    def test_current_user_dpapi_protects_and_unprotects_bytes(self) -> None:
        protector = WindowsDpapiProtector()
        plaintext = b"openclaw-native-windows-dpapi-smoke"

        ciphertext = protector.protect(plaintext, purpose="unit-test")

        self.assertNotEqual(ciphertext, plaintext)
        self.assertEqual(
            protector.unprotect(ciphertext, purpose="unit-test"), plaintext
        )
        with self.assertRaises(WindowsDpapiError):
            protector.unprotect(ciphertext, purpose="different-purpose")

    def test_public_results_never_echo_cookie_or_token_values(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            cookie_secret = "cookie-value-must-not-leak"
            token_secret = "token-value-must-not-leak"

            cookie_result = store.save(
                "bilibili", {"cookies": [_cookie(value=cookie_secret)]}
            )
            token_result = store.save(
                "smartedu", {"tokens": {"accessToken": token_secret}}
            )
            status_result = [entry.to_dict() for entry in store.get_status()]
            guide_result = store.login_guide("smartedu")
            public_json = json.dumps(
                [cookie_result, token_result, status_result, guide_result],
                ensure_ascii=False,
            )

            self.assertNotIn(cookie_secret, public_json)
            self.assertNotIn(token_secret, public_json)
            self.assertNotIn("session_data", public_json)

    def test_account_and_password_fields_are_rejected_recursively(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            payload = {
                "cookies": [_cookie()],
                "metadata": {"password": "must-not-be-stored"},
            }

            with self.assertRaises(SessionError) as caught:
                store.save("bilibili", payload)

            self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_INVALID")
            self.assertFalse((store.sessions_dir / "bilibili.json").exists())

    def test_cookie_count_limit_is_enforced_before_persistence(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            cookies = [
                _cookie(name=f"cookie_{index}", value=str(index))
                for index in range(MAX_COOKIE_COUNT + 1)
            ]

            with self.assertRaises(SessionError) as caught:
                store.save("bilibili", {"cookies": cookies})

            self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_TOO_LARGE")
            self.assertFalse((store.sessions_dir / "bilibili.json").exists())


class CookieDomainFilteringTests(unittest.TestCase):
    def test_only_exact_or_subdomain_cookies_are_persisted(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            payload = {
                "cookies": [
                    _cookie(name="root", domain=".BILIBILI.COM"),
                    _cookie(name="sub", domain="api.bilibili.com"),
                    _cookie(name="suffix-attack", domain="evilbilibili.com"),
                    _cookie(name="unrelated", domain="example.com"),
                ]
            }

            result = store.save("bilibili", payload)
            saved = store.get_session_data("bilibili")

            self.assertEqual(result["stored_credential_count"], 2)
            self.assertEqual(result["discarded_credential_count"], 2)
            self.assertIsNotNone(saved)
            self.assertEqual(
                {cookie["name"] for cookie in saved["cookies"]},
                {"root", "sub"},
            )

    def test_all_out_of_scope_cookies_produce_session_empty(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "bilibili",
                    {"cookies": [_cookie(domain="evilbilibili.com")]},
                )

            self.assertEqual(caught.exception.code, "SESSION_EMPTY")

    def test_expired_cookie_is_discarded_but_live_cookie_is_saved(self) -> None:
        now = datetime.now(timezone.utc).timestamp()
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            result = store.save(
                "bilibili",
                {
                    "cookies": [
                        _cookie(name="expired", expires=now - 60),
                        _cookie(name="live", expires=now + 3600),
                    ]
                },
            )
            saved = store.get_session_data("bilibili")

            self.assertEqual(result["stored_credential_count"], 1)
            self.assertEqual(result["discarded_credential_count"], 1)
            self.assertEqual(saved["cookies"][0]["name"], "live")

    def test_broad_browser_cookie_capture_is_filtered_and_browser_metadata_is_dropped(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            result = store.save(
                "bilibili",
                {
                    "cookies": [
                        _cookie(value="wanted", priority="High", sourcePort=443),
                        _cookie(
                            name="other",
                            value="discarded",
                            domain="unrelated.example",
                            hostOnly=True,
                        ),
                    ],
                    "storage_origin": "https://www.bilibili.com",
                    "local_storage": {"username": "not-persisted", "theme": "dark"},
                    "session_storage": {"temporary": "not-persisted"},
                },
            )
            saved = store.get_session_data("bilibili")

            self.assertEqual(result["stored_credential_count"], 1)
            self.assertEqual(result["discarded_credential_count"], 4)
            self.assertEqual(saved["cookies"][0]["value"], "wanted")
            self.assertNotIn("priority", saved["cookies"][0])
            self.assertNotIn("sourcePort", saved["cookies"][0])
            self.assertNotIn("local_storage", saved)
            self.assertNotIn("session_storage", saved)

    def test_partition_key_is_accepted_but_not_persisted(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            result = store.save(
                "bilibili",
                {
                    "cookies": [
                        _cookie(
                            partitionKey={
                                "topLevelSite": "https://www.bilibili.com",
                                "hasCrossSiteAncestor": False,
                            }
                        )
                    ]
                },
            )
            saved = store.get_session_data("bilibili")
            record = json.loads(
                (store.sessions_dir / "bilibili.json").read_text(encoding="utf-8")
            )

            self.assertEqual(result["status"], "stored")
            self.assertNotIn("partitionKey", saved["cookies"][0])
            self.assertNotIn("partitionKey", record["session_data"]["cookies"][0])


class TokenSessionTests(unittest.TestCase):
    def test_smartedu_token_payload_is_minimized_and_saved(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            result = store.save(
                "smartedu",
                {"tokens": {"accessToken": "access-secret", "x-nd-auth": "auth-secret"}},
            )
            saved = store.get_session_data("smartedu")

            self.assertEqual(result["auth_kind"], "token")
            self.assertEqual(result["stored_credential_count"], 2)
            self.assertEqual(
                saved,
                {"tokens": {"accessToken": "access-secret", "x-nd-auth": "auth-secret"}},
            )

    def test_smartedu_dynamic_local_storage_json_is_extracted_and_raw_capture_is_not_persisted(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            dynamic_key = "ND_UC_AUTH-test-id&ncet-xedu&token"
            result = store.save(
                "smartedu",
                {
                    "cookies": [
                        _cookie(
                            name="irrelevant",
                            value="not-persisted",
                            domain="unrelated.example",
                        )
                    ],
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {
                        "username": "not-persisted",
                        "unrelated": "not-persisted",
                        dynamic_key: json.dumps(
                            {
                                "account": {"session": {"access_token": "dynamic-secret"}},
                                "display_name": "not-persisted",
                            }
                        ),
                    },
                    "session_storage": {"temporary": "not-persisted"},
                },
            )
            saved = store.get_session_data("smartedu")
            record_text = (store.sessions_dir / "smartedu.json").read_text(encoding="utf-8")

            self.assertEqual(saved, {"tokens": {"accessToken": "dynamic-secret"}})
            self.assertEqual(result["stored_credential_count"], 1)
            self.assertEqual(result["discarded_credential_count"], 4)
            self.assertNotIn(dynamic_key, record_text)
            self.assertNotIn("username", record_text)
            self.assertNotIn("display_name", record_text)

    def test_smartedu_constrained_cookie_can_supply_access_token_fallback(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            result = store.save(
                "smartedu",
                {
                    "cookies": [
                        _cookie(
                            name="UC_TOKEN-test-id-ncet-xedu",
                            value="cookie-fallback-secret",
                            domain=".auth.smartedu.cn",
                        ),
                        _cookie(
                            name="UC_TOKEN-test-id-ncet-xedu",
                            value="wrong-domain-secret",
                            domain="evilsmartedu.cn",
                        ),
                    ],
                    "storage_origin": "https://auth.smartedu.cn",
                    "local_storage": {"unrelated": "not-persisted"},
                },
            )
            saved = store.get_session_data("smartedu")

            self.assertEqual(
                saved, {"tokens": {"accessToken": "cookie-fallback-secret"}}
            )
            self.assertEqual(result["stored_credential_count"], 1)
            self.assertEqual(result["discarded_credential_count"], 2)

    def test_smartedu_expired_cookie_cannot_supply_fallback(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            with self.assertRaises(SessionError) as caught:
                store.save(
                    "smartedu",
                    {
                        "cookies": [
                            _cookie(
                                name="UC_TOKEN-expired-id-ncet-xedu",
                                value="expired-fallback-secret",
                                domain=".smartedu.cn",
                                expires=datetime.now(timezone.utc).timestamp() - 60,
                            )
                        ],
                        "storage_origin": "https://basic.smartedu.cn",
                        "local_storage": {"unrelated": "ignored"},
                    },
                )

            self.assertEqual(caught.exception.code, "SESSION_EMPTY")
            self.assertNotIn("expired-fallback-secret", str(caught.exception))

    def test_smartedu_local_storage_has_priority_over_session_storage(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            store.save(
                "smartedu",
                {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {
                        "ND_UC_AUTH-local-id&ncet-xedu&token": json.dumps(
                            {"access_token": "local-secret"}
                        )
                    },
                    "session_storage": {
                        "ND_UC_AUTH-session-id&ncet-xedu&token": json.dumps(
                            {"access_token": "session-secret"}
                        )
                    },
                },
            )

            self.assertEqual(
                store.get_session_data("smartedu"),
                {"tokens": {"accessToken": "local-secret"}},
            )

    def test_smartedu_rejects_unrelated_dynamic_keys_and_cookie_names(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "smartedu",
                    {
                        "cookies": [
                            _cookie(
                                name="UC_TOKEN-test-id-other-app",
                                value="not-accepted",
                                domain=".smartedu.cn",
                            )
                        ],
                        "storage_origin": "https://basic.smartedu.cn",
                        "local_storage": {
                            "ND_UC_AUTH-test-id&other-app&token": json.dumps(
                                {"access_token": "not-accepted"}
                            )
                        },
                    },
                )

            self.assertEqual(caught.exception.code, "SESSION_EMPTY")

    def test_smartedu_session_storage_fallback_uses_official_origin(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            store.save(
                "smartedu",
                {
                    "storage_origin": "https://www.smartedu.cn",
                    "local_storage": {"unrelated": "ignored"},
                    "session_storage": {
                        "ND_UC_AUTH-session-id&ncet-xedu&token": json.dumps(
                            {"access_token": "session-storage-secret"}
                        )
                    },
                },
            )

            self.assertEqual(
                store.get_session_data("smartedu"),
                {"tokens": {"accessToken": "session-storage-secret"}},
            )

    def test_smartedu_storage_origin_requires_true_domain_boundary(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "smartedu",
                    {
                        "storage_origin": "https://evilsmartedu.cn",
                        "local_storage": {
                            "ND_UC_AUTH-test-id&ncet-xedu&token": json.dumps(
                                {"access_token": "not-accepted"}
                            )
                        },
                    },
                )

            self.assertEqual(caught.exception.code, "SESSION_EMPTY")
            self.assertFalse((store.sessions_dir / "smartedu.json").exists())

    def test_smartedu_storage_origin_rejects_path_query_and_userinfo(self) -> None:
        invalid_origins = (
            "https://basic.smartedu.cn/path",
            "https://basic.smartedu.cn?query=1",
            "https://user@basic.smartedu.cn",
        )
        for index, origin in enumerate(invalid_origins):
            with self.subTest(origin=origin), _home_temp_directory(
                f"session-manager-origin-{index}-"
            ) as temp_dir:
                store = SessionStore(Path(temp_dir) / "data")
                with self.assertRaises(SessionError) as caught:
                    store.save(
                        "smartedu",
                        {
                            "storage_origin": origin,
                            "local_storage": {"accessToken": "origin-secret"},
                        },
                    )
                self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_INVALID")

    def test_smartedu_matching_storage_json_must_be_valid(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "smartedu",
                    {
                        "storage_origin": "https://basic.smartedu.cn",
                        "local_storage": {
                            "ND_UC_AUTH-test-id&ncet-xedu&token": "{not-json"
                        },
                    },
                )

            self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_INVALID")
            self.assertNotIn("not-json", str(caught.exception))

    def test_smartedu_conflicting_same_priority_candidates_are_rejected(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "smartedu",
                    {
                        "storage_origin": "https://basic.smartedu.cn",
                        "local_storage": {
                            "ND_UC_AUTH-first-id&ncet-xedu&token": json.dumps(
                                {"access_token": "first-secret"}
                            ),
                            "ND_UC_AUTH-second-id&ncet-xedu&token": json.dumps(
                                {"access_token": "second-secret"}
                            ),
                        },
                    },
                )

            self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_INVALID")
            self.assertNotIn("first-secret", str(caught.exception))
            self.assertNotIn("second-secret", str(caught.exception))

    def test_required_token_is_enforced(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save("smartedu", {"tokens": {"x-nd-auth": "auth-secret"}})

            self.assertEqual(caught.exception.code, "SESSION_EMPTY")

    def test_unknown_token_key_is_rejected(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "smartedu",
                    {"tokens": {"accessToken": "access-secret", "refreshToken": "no"}},
                )

            self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_INVALID")


class ExpirationTests(unittest.TestCase):
    def test_past_top_level_expiration_is_rejected(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "bilibili",
                    {"cookies": [_cookie()]},
                    expires_at=_past_iso(),
                )

            self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_INVALID")

    def test_expired_local_record_is_reported_and_not_returned(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            store.save(
                "bilibili",
                {"cookies": [_cookie()]},
                expires_at=_future_iso(),
            )
            record_path = store.sessions_dir / "bilibili.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["expires_at"] = _past_iso()
            record_path.write_text(json.dumps(record), encoding="utf-8")

            status = store.get_status(["bilibili"])[0]

            self.assertEqual(status.status, "expired")
            self.assertIsNone(store.get_session_data("bilibili"))

    def test_invalid_local_record_is_reported_and_not_returned(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            store.save("bilibili", {"cookies": [_cookie()]})
            record_path = store.sessions_dir / "bilibili.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["platform"] = "zhihu"
            record_path.write_text(json.dumps(record), encoding="utf-8")

            status = store.get_status(["bilibili"])[0]

            self.assertEqual(status.status, "invalid")
            self.assertIsNone(store.get_session_data("bilibili"))

    def test_expiration_without_timezone_is_rejected(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "bilibili",
                    {"cookies": [_cookie()]},
                    expires_at="2099-01-01T00:00:00",
                )

            self.assertEqual(caught.exception.code, "SESSION_PAYLOAD_INVALID")


class IdempotencyTests(unittest.TestCase):
    def test_save_replay_returns_original_result_without_rewriting(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            payload = {"cookies": [_cookie()]}

            first = store.save(
                "bilibili", payload, idempotency_key="save-replay-key-01"
            )
            second = store.save(
                "bilibili", payload, idempotency_key="save-replay-key-01"
            )

            self.assertEqual(first["status"], "stored")
            self.assertRegex(first["session_revision"], r"^[0-9a-f]{32}$")
            self.assertFalse(first["idempotent_replay"])
            self.assertTrue(second["idempotent_replay"])
            self.assertEqual(first["captured_at"], second["captured_at"])
            self.assertEqual(first["session_revision"], second["session_revision"])

    def test_save_replay_is_stale_after_session_revision_changes(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            original_payload = {"cookies": [_cookie(value="original")]}
            first = store.save(
                "bilibili",
                original_payload,
                idempotency_key="save-stale-key-01",
            )
            replacement = store.save(
                "bilibili", {"cookies": [_cookie(value="replacement")]}
            )

            self.assertNotEqual(
                first["session_revision"], replacement["session_revision"]
            )
            with self.assertRaises(SessionError) as caught:
                store.save(
                    "bilibili",
                    original_payload,
                    idempotency_key="save-stale-key-01",
                )

            self.assertEqual(caught.exception.code, "IDEMPOTENCY_STALE")

    def test_save_key_reuse_with_different_payload_conflicts(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            store.save(
                "bilibili",
                {"cookies": [_cookie(value="first")]},
                idempotency_key="save-conflict-key-01",
            )

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "bilibili",
                    {"cookies": [_cookie(value="second")]},
                    idempotency_key="save-conflict-key-01",
                )

            self.assertEqual(caught.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_broad_capture_idempotency_uses_minimized_credentials_not_noise(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            key = "smartedu-broad-save-key-01"
            dynamic_key = "ND_UC_AUTH-idempotent-id&ncet-xedu&token"
            first = store.save(
                "smartedu",
                {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {
                        dynamic_key: json.dumps({"access_token": "stable-secret"}),
                        "noise": "first",
                    },
                },
                idempotency_key=key,
            )
            second = store.save(
                "smartedu",
                {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {
                        dynamic_key: json.dumps({"access_token": "stable-secret"}),
                        "noise": "changed",
                    },
                    "cookies": [
                        _cookie(
                            name="unrelated",
                            value="changed-noise",
                            domain="unrelated.example",
                        )
                    ],
                },
                idempotency_key=key,
            )

            self.assertFalse(first["idempotent_replay"])
            self.assertTrue(second["idempotent_replay"])
            self.assertEqual(first["session_revision"], second["session_revision"])

    def test_broad_capture_idempotency_conflicts_when_extracted_token_changes(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            key = "smartedu-broad-conflict-key-01"
            dynamic_key = "ND_UC_AUTH-conflict-id&ncet-xedu&token"
            first = store.save(
                "smartedu",
                {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {
                        dynamic_key: json.dumps({"access_token": "first-secret"})
                    },
                },
                idempotency_key=key,
            )

            with self.assertRaises(SessionError) as caught:
                store.save(
                    "smartedu",
                    {
                        "storage_origin": "https://basic.smartedu.cn",
                        "local_storage": {
                            dynamic_key: json.dumps(
                                {"access_token": "second-secret"}
                            )
                        },
                    },
                    idempotency_key=key,
                )

            self.assertEqual(caught.exception.code, "IDEMPOTENCY_CONFLICT")
            self.assertEqual(
                store.get_session_data("smartedu"),
                {"tokens": {"accessToken": "first-secret"}},
            )
            record = store._read(store.sessions_dir / "smartedu.json")
            self.assertEqual(record["revision"], first["session_revision"])

    def test_delete_replay_preserves_first_deleted_result(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            store.save("bilibili", {"cookies": [_cookie()]})

            first = store.delete(
                "bilibili", idempotency_key="delete-replay-key-01"
            )
            second = store.delete(
                "bilibili", idempotency_key="delete-replay-key-01"
            )

            self.assertTrue(first["deleted"])
            self.assertFalse(first["idempotent_replay"])
            self.assertTrue(second["deleted"])
            self.assertTrue(second["idempotent_replay"])

    def test_invalid_idempotency_key_is_rejected(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")

            with self.assertRaises(SessionError) as caught:
                store.delete("bilibili", idempotency_key="short")

            self.assertEqual(caught.exception.code, "INVALID_IDEMPOTENCY_KEY")


class CookieProbeScopeTests(unittest.TestCase):
    def test_cookie_header_enforces_domain_path_secure_and_expiry_scope(self) -> None:
        now = datetime.now(timezone.utc).timestamp()
        session_data = {
            "cookies": [
                _cookie(name="host-only", domain="bilibili.com"),
                _cookie(name="domain", domain=".bilibili.com"),
                _cookie(name="root", domain=".bilibili.com", path="/"),
                _cookie(name="account", domain=".bilibili.com", path="/account"),
                _cookie(name="wrong-path", domain=".bilibili.com", path="/video"),
                _cookie(name="secure", domain=".bilibili.com", secure=True),
                _cookie(name="expired", domain=".bilibili.com", expires=now - 60),
                _cookie(name="live", domain=".bilibili.com", expires=now + 3600),
            ]
        }

        https_header = SessionStore._cookie_header(
            session_data, "https://api.bilibili.com/account/settings"
        )
        http_header = SessionStore._cookie_header(
            session_data, "http://api.bilibili.com/account/settings"
        )
        boundary_header = SessionStore._cookie_header(
            session_data, "https://api.bilibili.com/accounting"
        )

        self.assertNotIn("host-only=", https_header)
        self.assertIn("domain=", https_header)
        self.assertIn("account=", https_header)
        self.assertNotIn("wrong-path=", https_header)
        self.assertIn("secure=", https_header)
        self.assertNotIn("secure=", http_header)
        self.assertNotIn("expired=", https_header)
        self.assertIn("live=", https_header)
        self.assertLess(https_header.index("account="), https_header.index("root="))
        self.assertNotIn("account=", boundary_header)


class HttpProbeRedirectTests(unittest.TestCase):
    def test_probe_does_not_follow_redirects(self) -> None:
        class RedirectHandler(BaseHTTPRequestHandler):
            target_hits = 0

            def do_GET(self) -> None:
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.end_headers()
                    return
                type(self).target_hits += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"redirect target")

            def log_message(self, _format: str, *_args: object) -> None:
                return

        with ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                status, _body = probe_with_headers(
                    f"http://{host}:{port}/start", headers={"Cookie": "secret=value"}
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)

        self.assertEqual(status, 302)
        self.assertEqual(RedirectHandler.target_hits, 0)


if __name__ == "__main__":
    unittest.main()
