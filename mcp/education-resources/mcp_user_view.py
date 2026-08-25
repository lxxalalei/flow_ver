"""Simulate a user-facing Agent call through the MCP stdio boundary.

Spawns the real education-resources MCP server and issues the same JSON-RPC
tool calls an OpenClaw Agent would: resource_search -> resource_download ->
resource_job_status. Prints what the Agent sees at each step.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent
SRC = SERVICE_ROOT / "src"


def rpc(proc, request_id, method, params=None):
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
        return json.dumps(msg, ensure_ascii=False)[:500]


def main() -> int:
    root = Path("smoke_user_data")
    root.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(SRC),
        "EDUCATION_RESOURCE_MCP_DATA_DIR": str(root),
        "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(root / "library"),
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
    try:
        rpc(proc, 1, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "user-view-test", "version": "1.0"},
        })
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }) + "\n")
        proc.stdin.flush()

        print("=" * 60)
        print("STEP 1: resource_search {search_tasks: [{platform: cctv, queries: [地球脉动]}]}")
        print("=" * 60)
        search = rpc(proc, 2, "tools/call", {
            "name": "resource_search",
            "arguments": {
                "search_tasks": [
                    {"platform": "cctv", "queries": ["地球脉动"]}
                ]
            },
        })
        text = result_text(search)
        print(text[:1500])
        print("...")

        try:
            data = json.loads(text)
            resources = data.get("candidates") or data.get("resources") or data.get("items") or []
        except json.JSONDecodeError:
            resources = []
        print(f"\n>>> Agent sees {len(resources)} candidates")

        resource_id = None
        for r in resources:
            rid = r.get("resource_id") or r.get("id")
            if rid:
                resource_id = rid
                break
        if not resource_id:
            print("!! no resource_id found in search results")
            return 2

        print("\n" + "=" * 60)
        print(f"STEP 2: resource_download {{resource_ids: [{resource_id}]}}")
        print("=" * 60)
        dl = rpc(proc, 3, "tools/call", {
            "name": "resource_download",
            "arguments": {"resource_ids": [resource_id]},
        })
        dl_text = result_text(dl)
        print(dl_text[:800])
        try:
            job_id = json.loads(dl_text).get("job_id")
        except json.JSONDecodeError:
            job_id = None
        if not job_id:
            print("!! no job_id returned")
            return 3

        print("\n" + "=" * 60)
        print("STEP 3: polling resource_job_status")
        print("=" * 60)
        terminal = False
        for attempt in range(120):
            time.sleep(3)
            status = rpc(proc, 4, "tools/call", {
                "name": "resource_job_status",
                "arguments": {"job_id": job_id},
            })
            st = result_text(status)
            try:
                s = json.loads(st).get("status", "")
            except json.JSONDecodeError:
                s = ""
            if attempt < 2 or s in ("completed", "failed", "cancelled"):
                print(f"[t+{(attempt + 1) * 3}s] {st[:700]}")
            if s in ("succeeded", "partial", "failed", "cancelled", "interrupted"):
                terminal = True
                break
        print(f"\n>>> TERMINAL={terminal}")

        log = root / "jobs" / job_id / "worker.log"
        if log.exists():
            print("\n--- worker.log tail ---")
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-20:]:
                print(line[:160])
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
