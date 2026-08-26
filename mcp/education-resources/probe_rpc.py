#!/usr/bin/env python3
"""Drive one JSON-RPC call through the real MCP server process (stdio).

Usage:
  probe_rpc.py METHOD '{"param": ...}' [data_dir]

Prints the text content of the tool result (or the raw message on error).
DATA_DIR defaults to a fresh temp dir; pass a real dir to reuse sessions/jobs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent
SRC = SERVICE_ROOT / "src"
METHOD = sys.argv[1] if len(sys.argv) > 1 else "tools/list"
PARAMS_ARG = sys.argv[2] if len(sys.argv) > 2 else None
if PARAMS_ARG and PARAMS_ARG.startswith("@"):
    with open(PARAMS_ARG[1:], encoding="utf-8") as handle:
        PARAMS = json.load(handle)
else:
    PARAMS = json.loads(PARAMS_ARG) if PARAMS_ARG else None
DATA_DIR = sys.argv[3] if len(sys.argv) > 3 else None

if DATA_DIR:
    data_dir = Path(DATA_DIR).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
else:
    data_dir = Path(tempfile.mkdtemp(prefix="probe-"))

env = dict(os.environ)
env.update({
    "PYTHONPATH": str(SRC),
    "EDUCATION_RESOURCE_MCP_DATA_DIR": str(data_dir),
    "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(data_dir / "library"),
    "EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT": "60",
    "EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT": "600",
})

proc = subprocess.Popen(
    [sys.executable, "-m", "education_resource_mcp.server"],
    cwd=SERVICE_ROOT,
    env=env,
    text=True,
    encoding="utf-8",
    errors="replace",
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)


def rpc(request_id, method, params=None):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        msg = json.loads(line)
        if msg.get("id") == request_id:
            return msg


def result_text(msg):
    try:
        content = msg["result"]["content"]
        return "".join(c.get("text", "") for c in content if c.get("type") == "text")
    except Exception:
        return json.dumps(msg, ensure_ascii=False)[:4000]


rpc(1, "initialize", {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "probe-rpc", "version": "1.0"},
})
rpc(2, "notifications/initialized", {}) if False else None
proc.stdin.write(json.dumps({
    "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
}) + "\n")
proc.stdin.flush()

if METHOD == "tools/list":
    out = rpc(3, "tools/list")
else:
    out = rpc(3, "tools/call", {"name": METHOD, "arguments": PARAMS or {}})

print(json.dumps(out, ensure_ascii=False, indent=1)[:12000] if out.get("error") else result_text(out))
proc.stdin.close()
proc.wait(timeout=15)
