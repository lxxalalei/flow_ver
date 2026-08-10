"""Regression coverage for the lightweight retrieval import boundary."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
import sys


SERVICE_ROOT = Path(__file__).resolve().parents[1]
# Do not resolve the virtualenv launcher symlink: resolving it can bypass the
# selected environment's site-packages in the isolated child process.
PYTHON_UNDER_TEST = Path(sys.executable)

_CHILD_CODE = """
import importlib.abc
import socket
import ssl
import sys

BLOCKED_MODULE = "education_resource_mcp.retrieval.adaptive"


class BlockAdaptiveImport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == BLOCKED_MODULE:
            raise ImportError(
                "adaptive retrieval must not load during service import"
            )
        return None


class NetworkDisabledSocket(socket.socket):
    def connect(self, *args, **kwargs):
        raise AssertionError("network access is forbidden in this regression test")

    def connect_ex(self, *args, **kwargs):
        raise AssertionError("network access is forbidden in this regression test")


def block_network(*args, **kwargs):
    raise AssertionError("network access is forbidden in this regression test")


# Import ssl before replacing socket.socket so import-time class construction in
# standard-library modules remains unaffected.  The target import and static
# helper below can neither resolve hosts nor establish a connection.
socket.socket = NetworkDisabledSocket
socket.create_connection = block_network
socket.getaddrinfo = block_network
sys.meta_path.insert(0, BlockAdaptiveImport())

from education_resource_mcp.service import ResourceService

assert BLOCKED_MODULE not in sys.modules, sorted(
    name
    for name in sys.modules
    if name.startswith("education_resource_mcp.retrieval")
)

coverage = ResourceService._fact_coverage(
    [
        {
            "resource_id": "res-import-boundary",
            "platform": "generic",
            "resource_type": "article",
        }
    ],
    [],
    [],
)
assert coverage["kind"] == "factual", coverage
assert coverage["candidate_count"] == 1, coverage
"""


class RetrievalImportBoundaryTests(unittest.TestCase):
    def test_service_import_does_not_load_adaptive_retrieval(self) -> None:
        """Service facts remain usable when adaptive retrieval is unavailable."""
        self.assertTrue(
            PYTHON_UNDER_TEST.is_file(),
            f"current test interpreter is unavailable: {PYTHON_UNDER_TEST}",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            isolation_root = Path(temp_dir)
            for directory in (
                isolation_root / "home",
                isolation_root / "tmp",
                isolation_root / "mcp-data",
                isolation_root / "pycache",
                isolation_root / "xdg-cache",
                isolation_root / "xdg-config",
                isolation_root / "xdg-data",
            ):
                directory.mkdir()

            environment = os.environ.copy()
            source_root = str(SERVICE_ROOT / "src")
            existing_pythonpath = environment.get("PYTHONPATH")
            environment.update(
                {
                    "PYTHONPATH": os.pathsep.join(
                        value
                        for value in (source_root, existing_pythonpath)
                        if value
                    ),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPYCACHEPREFIX": str(isolation_root / "pycache"),
                    "EDUCATION_RESOURCE_MCP_DATA_DIR": str(isolation_root / "mcp-data"),
                    "HOME": str(isolation_root / "home"),
                    "TMPDIR": str(isolation_root / "tmp"),
                    "TEMP": str(isolation_root / "tmp"),
                    "TMP": str(isolation_root / "tmp"),
                    "XDG_CACHE_HOME": str(isolation_root / "xdg-cache"),
                    "XDG_CONFIG_HOME": str(isolation_root / "xdg-config"),
                    "XDG_DATA_HOME": str(isolation_root / "xdg-data"),
                }
            )
            result = subprocess.run(
                [str(PYTHON_UNDER_TEST), "-c", textwrap.dedent(_CHILD_CODE)],
                cwd=isolation_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(
            0,
            result.returncode,
            "isolated service import failed with adaptive retrieval blocked:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
