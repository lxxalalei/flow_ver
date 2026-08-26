#!/usr/bin/env python3
"""Run a multi-step JSON-RPC flow against the real MCP server in one process.

Usage:
  probe_flow.py '[[method, params], [method, params], ...]' [data_dir]

Each step is [method, params]; params omitted -> {}. Prints per-step the text
result (or error). resource_id handles survive across steps in this process.
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
STEPS = json.loads(sys.argv[1])
DATA_DIR = sys.argv[2] if len(sys.argv) > 2 else None

if DATA_DIR:
    data_dir = Path(DATA_DIR).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
else:
    data_dir = Path(tempfile.mkdtemp(prefix="probe-flow-"))

env = dict(os.environ)
env.update({
    "PYTHONPATH": str(SRC),
    "EDUCATION_RESOURCE_MCP_DATA_DIR": str(data_dir),
    "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(data_dir / "library"),
    "EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT": "60",
    "EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT": "900",
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
    "clientInfo": {"name": "probe-flow", "version": "1.0"},
})
proc.stdin.write(json.dumps({
    "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
}) + "\n")
proc.stdin.flush()

req_id = 10
prev_id = None
prev_ids: list[str] = []
for step in STEPS:
    method, params = (step + [{}])[:2]
    params = dict(params)
    for k, v in list(params.items()):
        if v == "@prev_id":
            params[k] = prev_id
        elif v == "@prev_ids":
            params[k] = prev_ids
        elif isinstance(v, list):
            params[k] = [
                prev_id if item == "@prev_id" else item for item in v
            ]
    req_id += 1
    out = rpc(req_id, "tools/call", {"name": method, "arguments": params})
    text = result_text(out)
    print(f"=== {method} ===")
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            if d.get("resource_id") and str(d["resource_id"]).startswith("res_"):
                prev_id = d["resource_id"]
            for item in (d.get("items") or []):
                rid = str(item.get("resource_id") or "")
                if rid.startswith("res_") and rid not in prev_ids:
                    prev_ids.append(rid)
            if d.get("ok") is False and isinstance(d.get("error"), dict):
                print("ERROR:", json.dumps(d["error"], ensure_ascii=False)[:1500])
                continue
            if d.get("failures"):
                print("FAILURES:", json.dumps(d["failures"], ensure_ascii=False)[:800])
            keys = {k: (v if not isinstance(v, (list, dict)) else f"<{len(v)} items>" if isinstance(v, list) else "<obj>") for k, v in list(d.items())[:8]}
            print(json.dumps(keys, ensure_ascii=False)[:800])
            if "--dump" in sys.argv and method in {"resource_inspect", "resource_import_url"}:
                print(text[:4000])
            continue
    except Exception:
        pass
    if method in {"resource_inspect", "resource_import_url"} and "--dump" in sys.argv:
        print(text[:4000])
    else:
        print(text[:1500])

proc.stdin.close()
proc.wait(timeout=15)
