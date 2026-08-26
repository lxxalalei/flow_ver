"""Retry the throttled Anna's Archive download with a fresh job (patient poll)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent
SRC = SERVICE_ROOT / "src"

URL = "https://wbsg8v.xyz/d4/y/anon/s/1787729719/1798/g2/ia1lcpdf/i/isbn_9787556041756.pdf~/4pk85wc2jJsr8MO7cvAApw/isbn_9787556041756%20--%20Unknown%20--%201800%20--%20%E9%95%BF%E6%B1%9F%E5%B0%91%E5%B9%B4%E5%84%BF%E7%AB%A5%E5%87%BA%E7%89%88%E7%A4%BE%20--%20isbn13%209787556041756%20--%20485fd9c7418512aee9b7cd04e84dae62%20--%20Anna%E2%80%99s%20Archive.pdf"


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
    content = msg["result"]["content"]
    return "".join(c.get("text", "") for c in content if c.get("type") == "text")


def main() -> int:
    root = Path("smoke_web3")
    root.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(SRC),
        "EDUCATION_RESOURCE_MCP_DATA_DIR": str(root),
        "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(root / "library"),
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "education_resource_mcp.server"],
        cwd=SERVICE_ROOT, env=env, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        rpc(proc, 1, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "book-retry", "version": "1.0"},
        })
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }) + "\n")
        proc.stdin.flush()
        imp = json.loads(result_text(rpc(proc, 2, "tools/call", {
            "name": "resource_import_url", "arguments": {"source_url": URL},
        })))
        rid = imp["resource_id"]
        dl = json.loads(result_text(rpc(proc, 3, "tools/call", {
            "name": "resource_download", "arguments": {"resource_ids": [rid]},
        })))
        job_id = dl["job_id"]
        print("job:", job_id, flush=True)
        job_dir = root / "jobs" / job_id
        t0 = time.time()
        while time.time() - t0 < 900:  # 15 min budget
            time.sleep(10)
            d = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            s = d.get("status")
            part = job_dir / "payload.part"
            size = part.stat().st_size if part.exists() else sum(
                f.stat().st_size for f in job_dir.glob("*.pdf")
            ) or 0
            if s in ("succeeded", "partial", "failed", "cancelled", "interrupted"):
                print(f"terminal: {s} at t+{time.time()-t0:.0f}s", flush=True)
                for f in d.get("files") or []:
                    print("file:", f.get("filename"), f"{f.get('size_bytes', 0)/1e6:.1f} MB")
                    print("path:", f.get("path"))
                for fail in d.get("failures") or []:
                    print("failure:", fail.get("code"), str(fail.get("message"))[:200])
                return 0
            print(f"t+{time.time()-t0:4.0f}s {s} {size/1024:.0f}KB", flush=True)
        print("TIMEOUT after 15min", flush=True)
        return 1
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
