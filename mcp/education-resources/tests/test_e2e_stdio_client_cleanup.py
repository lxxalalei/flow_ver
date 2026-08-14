"""Regression tests for RawMcpClient startup cleanup."""


from __future__ import annotations

import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import e2e_stdio_client
from e2e_stdio_client import RawMcpClient


class _Pipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Process:
    def __init__(self) -> None:
        self.stdin = _Pipe()
        self.stdout = _Pipe()
        self.killed = False
        self.wait_calls: list[float | None] = []

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return -9 if self.killed else 0


class RawMcpClientStartupCleanupTests(unittest.TestCase):
    def _assert_start_failure_cleans_up(
        self, request_result: object, error_type: type[Exception]
    ) -> None:
        process = _Process()
        with tempfile.TemporaryDirectory() as data_dir:
            client = RawMcpClient(data_dir, timeout=0.01)
            if isinstance(request_result, BaseException):
                request_patch = mock.patch.object(
                    client, "request", side_effect=request_result
                )
            else:
                request_patch = mock.patch.object(
                    client, "request", return_value=request_result
                )
            with (
                mock.patch.object(e2e_stdio_client.subprocess, "Popen", return_value=process),
                request_patch,
            ):
                with self.assertRaises(error_type):
                    client.start()

        self.assertTrue(process.killed)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.wait_calls)
        self.assertIsNone(client.process)
        self.assertIsNone(client._stderr)

    def test_initialize_timeout_kills_and_closes_started_process(self) -> None:
        self._assert_start_failure_cleans_up(TimeoutError("initialize timed out"), TimeoutError)

    def test_invalid_initialize_response_kills_and_closes_started_process(self) -> None:
        self._assert_start_failure_cleans_up(
            {"serverInfo": {"name": "unexpected-server"}}, RuntimeError
        )

    def test_popen_failure_closes_stderr_and_resets_client(self) -> None:
        stderr = _Pipe()
        with tempfile.TemporaryDirectory() as data_dir:
            client = RawMcpClient(data_dir)
            with (
                mock.patch.object(
                    e2e_stdio_client.tempfile, "TemporaryFile", return_value=stderr
                ),
                mock.patch.object(
                    e2e_stdio_client.subprocess,
                    "Popen",
                    side_effect=OSError("cannot start fixture server"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "cannot start fixture server"):
                    client.start()

        self.assertTrue(stderr.closed)
        self.assertIsNone(client.process)
        self.assertIsNone(client._stderr)

    def test_start_builds_an_isolated_subprocess_environment(self) -> None:
        """Parent MCP/session/library overrides must not reach fixture child."""

        process = _Process()
        stderr = _Pipe()
        captured_environment: dict[str, str] = {}

        def capture_popen(*args, **kwargs):
            captured_environment.update(kwargs["env"])
            return process

        parent_environment = {
            "PATH": "/host/bin",
            "SystemRoot": r"C:\\Windows",
            "EDUCATION_RESOURCE_MCP_DATA_DIR": "/host/mcp-data",
            "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": "/host/real-library",
            "EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR": "/host/session-store",
            "EDUCATION_RESOURCE_MCP_SEARXNG_URL": "https://host-search.invalid",
            "EDUCATION_RESOURCE_MCP_MAX_WORKERS": "99",
            "PYTHONPATH": "/host/pythonpath",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUSERBASE": "/host/python-user-base",
            "QIANFAN_API_KEY": "host-secret",
            "BING_COOKIE": "host-cookie",
            "UNRELATED_SECRET": "host-secret",
        }
        with tempfile.TemporaryDirectory() as data_dir:
            client = RawMcpClient(data_dir, mode="restart", timeout=0.01)
            root = Path(data_dir).resolve()
            untrusted_parent_pycache = root / "untrusted-parent-pycache"
            untrusted_parent_pycache.mkdir()
            parent_environment["PYTHONPYCACHEPREFIX"] = str(untrusted_parent_pycache)
            with (
                mock.patch.dict(e2e_stdio_client.os.environ, parent_environment, clear=True),
                mock.patch.object(
                    e2e_stdio_client.tempfile, "TemporaryFile", return_value=stderr
                ),
                mock.patch.object(
                    e2e_stdio_client.subprocess, "Popen", side_effect=capture_popen
                ),
                mock.patch.object(
                    client, "request", side_effect=TimeoutError("initialize timed out")
                ),
            ):
                with self.assertRaises(TimeoutError):
                    client.start()
            self.assertEqual([], list(untrusted_parent_pycache.iterdir()))

        self.assertEqual(str(root), captured_environment["EDUCATION_RESOURCE_MCP_DATA_DIR"])
        self.assertEqual(
            str(root / "library"),
            captured_environment["EDUCATION_RESOURCE_MCP_LIBRARY_DIR"],
        )
        self.assertEqual(str(root / "home"), captured_environment["HOME"])
        self.assertEqual(str(root / "home"), captured_environment["USERPROFILE"])
        self.assertEqual(str(root / "tmp"), captured_environment["TMPDIR"])
        self.assertEqual(str(root / "tmp"), captured_environment["TMP"])
        self.assertEqual(str(root / "tmp"), captured_environment["TEMP"])
        self.assertEqual(str(root / "xdg-cache"), captured_environment["XDG_CACHE_HOME"])
        self.assertEqual(str(root / "xdg-config"), captured_environment["XDG_CONFIG_HOME"])
        self.assertEqual(str(root / "xdg-data"), captured_environment["XDG_DATA_HOME"])
        self.assertEqual(str(root / "pycache"), captured_environment["PYTHONPYCACHEPREFIX"])
        # On Windows PYTHONDONTWRITEBYTECODE=1 is intentionally injected to avoid a
        # subprocess import deadlock; on POSIX the parent's value must not leak.
        if sys.platform != "win32":
            self.assertNotIn("PYTHONDONTWRITEBYTECODE", captured_environment)
        self.assertEqual("restart", captured_environment["EDUCATION_RESOURCE_E2E_MODE"])
        self.assertEqual("/host/bin", captured_environment["PATH"])
        # Windows stores environment-variable keys in uppercase; POSIX preserves casing.
        systemroot_key = "SYSTEMROOT" if sys.platform == "win32" else "SystemRoot"
        self.assertEqual(r"C:\\Windows", captured_environment[systemroot_key])
        self.assertEqual(
            os.pathsep.join(
                [
                    str(e2e_stdio_client.SERVICE_ROOT / "src"),
                    str(e2e_stdio_client.SERVICE_ROOT / "tests"),
                ]
            ),
            captured_environment["PYTHONPATH"],
        )
        self.assertEqual("0", captured_environment["PYTHONHASHSEED"])
        self.assertEqual(
            {
                "EDUCATION_RESOURCE_MCP_DATA_DIR",
                "EDUCATION_RESOURCE_MCP_LIBRARY_DIR",
            },
            {
                name
                for name in captured_environment
                if name.startswith("EDUCATION_RESOURCE_MCP_")
            },
        )
        for forbidden_name in (
            "EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR",
            "EDUCATION_RESOURCE_MCP_SEARXNG_URL",
            "EDUCATION_RESOURCE_MCP_MAX_WORKERS",
            "PYTHONUSERBASE",
            "QIANFAN_API_KEY",
            "BING_COOKIE",
            "UNRELATED_SECRET",
        ):
            self.assertNotIn(forbidden_name, captured_environment)
        self.assertTrue(process.killed)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(stderr.closed)

    def test_start_reuses_existing_parent_test_pycache(self) -> None:
        """All children in one isolated test run may share compiled imports."""

        process = _Process()
        stderr = _Pipe()
        captured_environment: dict[str, str] = {}

        def capture_popen(*args, **kwargs):
            captured_environment.update(kwargs["env"])
            return process

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root).resolve()
            shared_pycache = root / "shared-pycache"
            shared_pycache.mkdir()
            client = RawMcpClient(root / "client-data", timeout=0.01)
            with (
                mock.patch.dict(
                    e2e_stdio_client.os.environ,
                    {
                        "PYTHONPYCACHEPREFIX": str(shared_pycache),
                        "EDUCATION_RESOURCE_TEST_PYCACHE_DIR": str(shared_pycache),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    clear=True,
                ),
                mock.patch.object(
                    e2e_stdio_client.tempfile, "TemporaryFile", return_value=stderr
                ),
                mock.patch.object(
                    e2e_stdio_client.subprocess, "Popen", side_effect=capture_popen
                ),
                mock.patch.object(
                    client, "request", side_effect=TimeoutError("initialize timed out")
                ),
            ):
                with self.assertRaises(TimeoutError):
                    client.start()

        self.assertEqual(
            str(shared_pycache), captured_environment["PYTHONPYCACHEPREFIX"]
        )
        # On Windows PYTHONDONTWRITEBYTECODE=1 is injected to avoid the import
        # deadlock; on POSIX the parent's value must not reach the child.
        if sys.platform != "win32":
            self.assertNotIn("PYTHONDONTWRITEBYTECODE", captured_environment)
        self.assertTrue(process.killed)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(stderr.closed)


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
