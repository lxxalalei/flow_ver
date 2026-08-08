"""Small synchronous JSON-RPC client for process-level MCP E2E tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = SERVICE_ROOT / "tests" / "stdio_e2e_fixture_server.py"


class RawMcpClient:
    def __init__(self, data_dir: str | Path, mode: str = "standard", timeout: float = 5.0) -> None:
        self.data_dir = Path(data_dir)
        self.mode = mode
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._stderr = None

    def __enter__(self) -> "RawMcpClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("MCP process already started")
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONPATH": os.pathsep.join(
                    [str(SERVICE_ROOT / "src"), str(SERVICE_ROOT / "tests")]
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
                "EDUCATION_RESOURCE_MCP_DATA_DIR": str(self.data_dir),
                "EDUCATION_RESOURCE_E2E_MODE": self.mode,
            }
        )
        self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT)],
            cwd=SERVICE_ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )
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

    def _diagnostics(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.flush()
        self._stderr.seek(0)
        return self._stderr.read()[-4000:]

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
        while time.monotonic() < deadline:
            if self.process is None or self.process.stdout is None:
                break
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                break
            line = self.process.stdout.readline()
            if not line:
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

    def close(self, *, abrupt: bool = False) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            if abrupt:
                process.kill()
            else:
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if process.stdout is not None:
            process.stdout.close()
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if self._stderr is not None:
            self._stderr.close()
        self.process = None
        self._stderr = None

    def kill(self) -> None:
        self.close(abrupt=True)
