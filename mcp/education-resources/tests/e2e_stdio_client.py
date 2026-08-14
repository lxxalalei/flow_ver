"""Small synchronous JSON-RPC client for process-level MCP E2E tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = SERVICE_ROOT / "tests" / "stdio_e2e_fixture_server.py"

# The fixture server is an offline subprocess, not a child of a developer's
# configured production MCP.  It only needs enough of the host environment to
# start Python portably; every MCP/runtime location is supplied below.
_PLATFORM_ENVIRONMENT_NAMES = frozenset(
    {
        "path",
        "systemroot",
        "windir",
        "comspec",
        "pathext",
        "lang",
        "lc_all",
        "lc_ctype",
        "tz",
    }
)


def _existing_parent_pycache_directory() -> Path | None:
    """Return an explicitly configured, already-owned parent cache directory.

    The standard test runner creates one isolated cache for the whole run.  An
    E2E child may reuse that cache, but it must not create or otherwise trust an
    arbitrary path merely because the developer environment named it.
    """

    configured = os.environ.get("PYTHONPYCACHEPREFIX", "").strip()
    authorized = os.environ.get("EDUCATION_RESOURCE_TEST_PYCACHE_DIR", "").strip()
    if not configured or not authorized:
        return None
    candidate = Path(configured)
    authorized_candidate = Path(authorized)
    if (
        not candidate.is_absolute()
        or not authorized_candidate.is_absolute()
        or not candidate.is_dir()
        or not authorized_candidate.is_dir()
    ):
        return None
    resolved = candidate.resolve()
    if resolved != authorized_candidate.resolve():
        return None
    if resolved.is_relative_to(SERVICE_ROOT.resolve()):
        return None
    return resolved


def build_fixture_subprocess_environment(
    data_dir: str | Path, *, mode: str | None = None
) -> dict[str, str]:
    """Build the hermetic environment shared by every stdio fixture process.

    Do not forward an externally configured MCP data, library, session manager,
    search backend, credential, proxy, or Python import path.  The only parent
    runtime state deliberately reused is an existing ``PYTHONPYCACHEPREFIX``
    owned by the standard isolated test runner.
    """

    resolved_data_dir = Path(data_dir).resolve()
    library_dir = resolved_data_dir / "library"
    home_dir = resolved_data_dir / "home"
    tmp_dir = resolved_data_dir / "tmp"
    parent_pycache_dir = _existing_parent_pycache_directory()
    pycache_dir = parent_pycache_dir or resolved_data_dir / "pycache"
    xdg_cache_dir = resolved_data_dir / "xdg-cache"
    xdg_config_dir = resolved_data_dir / "xdg-config"
    xdg_data_dir = resolved_data_dir / "xdg-data"
    owned_directories = [
        resolved_data_dir,
        library_dir,
        home_dir,
        tmp_dir,
        xdg_cache_dir,
        xdg_config_dir,
        xdg_data_dir,
    ]
    if parent_pycache_dir is None:
        owned_directories.append(pycache_dir)
    for directory in owned_directories:
        directory.mkdir(parents=True, exist_ok=True)

    # ``sys.executable`` is invoked by absolute path.  Keep only operating
    # system/locale variables required by common Linux, WSL, and Windows Python
    # runtimes; do not copy the caller's application configuration.
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.casefold() in _PLATFORM_ENVIRONMENT_NAMES
    }
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(
                [str(SERVICE_ROOT / "src"), str(SERVICE_ROOT / "tests")]
            ),
            # The cache is either owned by this fixture data directory or is the
            # existing isolated cache owned by the standard test runner.  Keep
            # writes enabled so no child repeatedly pays the cold-compile cost;
            # no bytecode can land in the repository.
            "PYTHONPYCACHEPREFIX": str(pycache_dir),
            # On Windows, PYTHONPYCACHEPREFIX can deadlock the import phase of a
            # subprocess started with inherited pipe handles (the child blocks
            # inside the interpreter's first bytecode-write and never reaches the
            # event loop).  Suppress bytecode generation there; the cache prefix
            # above still applies on POSIX.
            "PYTHONDONTWRITEBYTECODE": "1" if sys.platform == "win32" else "0",
            "PYTHONHASHSEED": "0",
            "HOME": str(home_dir),
            "USERPROFILE": str(home_dir),
            "APPDATA": str(xdg_data_dir),
            "LOCALAPPDATA": str(xdg_data_dir),
            "XDG_CACHE_HOME": str(xdg_cache_dir),
            "XDG_CONFIG_HOME": str(xdg_config_dir),
            "XDG_DATA_HOME": str(xdg_data_dir),
            "TMPDIR": str(tmp_dir),
            "TMP": str(tmp_dir),
            "TEMP": str(tmp_dir),
            "EDUCATION_RESOURCE_MCP_DATA_DIR": str(resolved_data_dir),
            "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(library_dir),
        }
    )
    if mode is not None:
        environment["EDUCATION_RESOURCE_E2E_MODE"] = mode
    return environment


class RawMcpClient:
    def __init__(self, data_dir: str | Path, mode: str = "standard", timeout: float = 15.0) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.mode = mode
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._stderr = None
        self._reader_queue: queue.Queue[str | None] | None = None
        self._reader_thread: threading.Thread | None = None

    def __enter__(self) -> "RawMcpClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _subprocess_environment(self) -> dict[str, str]:
        return build_fixture_subprocess_environment(self.data_dir, mode=self.mode)

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("MCP process already started")
        environment = self._subprocess_environment()
        try:
            self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, str(SERVER_SCRIPT)],
                cwd=SERVICE_ROOT,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            # ``select`` cannot watch a pipe on Windows, so drain stdout on a
            # daemon thread into a queue and wait on the queue instead.
            self._reader_queue = queue.Queue()
            stream = self.process.stdout
            self._reader_thread = threading.Thread(
                target=self._pump_stdout,
                args=(stream, self._reader_queue),
                name="e2e-mcp-stdout-reader",
                daemon=True,
            )
            self._reader_thread.start()
            initialized = self.request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "flow-e2e", "version": "1.0"},
                },
            )
            if initialized.get("serverInfo", {}).get("name") != "education-resources":
                raise RuntimeError(f"unexpected MCP server info: {initialized!r}")
            self.notify("notifications/initialized", {})
        except BaseException:
            # Startup errors must not leak a real child process or its stderr file.
            # Cleanup is deliberately best effort so the original startup failure wins.
            try:
                self.close(abrupt=True)
            except BaseException:
                pass
            raise

    def _diagnostics(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.flush()
        self._stderr.seek(0)
        return self._stderr.read()[-4000:]

    @staticmethod
    def _pump_stdout(stream: Any, out: "queue.Queue[str | None]") -> None:
        """Read subprocess stdout lines into *out*; a ``None`` sentinel marks EOF."""
        try:
            for line in stream:
                out.put(line)
        except Exception:
            # A closed/aborted pipe should surface as EOF, not as a reader crash.
            pass
        finally:
            out.put(None)

    def _write(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("MCP process is not running")
        self.process.stdin.write(
            json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        deadline = time.monotonic() + self.timeout
        reader_queue = self._reader_queue
        while time.monotonic() < deadline:
            if reader_queue is None:
                break
            remaining = max(0.0, deadline - time.monotonic())
            try:
                line = reader_queue.get(timeout=remaining)
            except queue.Empty:
                break
            if line is None:
                break
            response = json.loads(line)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"JSON-RPC error: {response['error']!r}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"invalid JSON-RPC result: {response!r}")
            return result
        status = self.process.poll() if self.process is not None else None
        raise TimeoutError(
            f"MCP request timed out: method={method} process_status={status} "
            f"stderr={self._diagnostics()!r}"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("tools/list did not return a list")
        return tools

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("structuredContent")
        if not isinstance(content, dict):
            raise RuntimeError(f"tool {name} returned no structuredContent: {result!r}")
        return content

    @staticmethod
    def _close_stream(stream: Any) -> None:
        if stream is None or getattr(stream, "closed", False):
            return
        try:
            stream.close()
        except Exception:
            # Pipe/file cleanup should not hide the lifecycle error that caused it.
            pass

    def close(self, *, abrupt: bool = False) -> None:
        process = self.process
        stderr = self._stderr
        try:
            if process is not None and process.poll() is None:
                if abrupt:
                    process.kill()
                else:
                    self._close_stream(process.stdin)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        finally:
            if process is not None:
                self._close_stream(process.stdout)
                self._close_stream(process.stdin)
            self._close_stream(stderr)
            # The reader thread exits on stdout EOF; join best-effort so it can
            # never outlive the client on Windows where the pipe handle closes
            # asynchronously.
            thread = self._reader_thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2)
            self._reader_thread = None
            self._reader_queue = None
            # On Windows, a killed child's SQLite WAL/SHM handles can linger
            # briefly after process exit; give the OS a moment to release them
            # before the caller's TemporaryDirectory cleanup runs.
            if sys.platform == "win32" and process is not None:
                time.sleep(0.2)
            # Popen can fail after stderr is created, so reset both fields even
            # when there is no process to wait for.
            self.process = None
            self._stderr = None

    def kill(self) -> None:
        self.close(abrupt=True)
