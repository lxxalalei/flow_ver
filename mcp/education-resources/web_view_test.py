"""User-view test: generic web materialization of a real page.

resource_import_url -> resource_download -> job_status -> verify artifacts.
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

import sys as _sys

URL = _sys.argv[1] if len(_sys.argv) > 1 else "https://www.gushiwenku.cn/shiren/wangwei/"


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
    root = Path("smoke_web")
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
            "clientInfo": {"name": "web-view-test", "version": "1.0"},
        })
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }) + "\n")
        proc.stdin.flush()

        print("=" * 60)
        print(f"STEP 1: resource_import_url {URL}")
        print("=" * 60)
        imp = rpc(proc, 2, "tools/call", {
            "name": "resource_import_url",
            "arguments": {"source_url": URL},
        })
        imp_text = result_text(imp)
        print(imp_text[:600])
        try:
            data = json.loads(imp_text)
            resource_id = data.get("resource_id")
        except json.JSONDecodeError:
            resource_id = None
        if not resource_id:
            print("!! no resource_id")
            return 2

        print("\n" + "=" * 60)
        print(f"STEP 2: resource_download {{resource_ids: [{resource_id}]}}")
        print("=" * 60)
        dl = rpc(proc, 3, "tools/call", {
            "name": "resource_download",
            "arguments": {"resource_ids": [resource_id]},
        })
        dl_text = result_text(dl)
        print(dl_text[:500])
        try:
            job_id = json.loads(dl_text).get("job_id")
        except json.JSONDecodeError:
            job_id = None

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
            if attempt < 2 or s in ("succeeded", "partial", "failed", "cancelled", "interrupted"):
                print(f"[t+{(attempt + 1) * 3:4d}s] status={s}")
                if s in ("succeeded", "partial", "failed", "cancelled", "interrupted"):
                    print(st[:800])
            if s in ("succeeded", "partial", "failed", "cancelled", "interrupted"):
                terminal = True
                break
        print(f"\n>>> TERMINAL={terminal}")

        if job_id:
            job_dir = root / "jobs" / job_id
            print("\n--- artifacts ---")
            for name in ("source.html", "index.html", "content.md", "metadata.json", "webbundle.zip"):
                p = job_dir / name
                if p.exists():
                    print(f"  {name}: {p.stat().st_size / 1024:.1f} KB")
                else:
                    print(f"  {name}: MISSING")
            md = job_dir / "metadata.json"
            if md.exists():
                meta = json.loads(md.read_text(encoding="utf-8"))
                print("\n--- metadata ---")
                for key in ("http_status", "extraction_status", "reader_template",
                            "reader_images_embedded", "embedded_image_count",
                            "failed_image_count", "warnings", "completion"):
                    if key in meta:
                        print(f"  {key}: {meta[key]}")
            idx = job_dir / "index.html"
            if idx.exists():
                html = idx.read_text(encoding="utf-8", errors="replace")
                print("\n--- index.html check ---")
                print(f"  size: {len(html) / 1024:.1f} KB")
                print(f"  external http refs: {html.count('src=\"http') + html.count('href=\"http')}")
                print(f"  data: images: {html.count('data:image/')}")
                print(f"  css inline: {'<style>' in html}")
        log = root / "jobs" / job_id / "worker.log"
        if log.exists():
            print("\n--- worker.log tail ---")
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]:
                print(line[:150])
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
