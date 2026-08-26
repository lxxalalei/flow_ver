"""User-view test of resource_html_design: materialize -> context -> render.

The Agent reads the design context (title/excerpt/outline), makes a semantic
design decision, and submits an HtmlDesignSpec; the MCP renders the final
styled HTML deterministically.
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

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.gushiwenku.cn/shiren/wangwei/"


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
    root = Path("smoke_design")
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
            "clientInfo": {"name": "design-test", "version": "1.0"},
        })
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }) + "\n")
        proc.stdin.flush()

        # 1) import + download
        imp = json.loads(result_text(rpc(proc, 2, "tools/call", {
            "name": "resource_import_url", "arguments": {"source_url": URL},
        })))
        rid = imp.get("resource_id")
        print("import:", rid)
        dl = json.loads(result_text(rpc(proc, 3, "tools/call", {
            "name": "resource_download", "arguments": {"resource_ids": [rid]},
        })))
        job_id = dl.get("job_id")
        print("job:", job_id)
        for _ in range(60):
            time.sleep(2)
            s = json.loads(result_text(rpc(proc, 4, "tools/call", {
                "name": "resource_job_status", "arguments": {"job_id": job_id},
            }))).get("status")
            if s in ("succeeded", "partial", "failed", "cancelled", "interrupted"):
                break
        print("job status:", s)

        # 2) design context (what the Agent sees)
        ctx_text = result_text(rpc(proc, 5, "tools/call", {
            "name": "resource_html_design",
            "arguments": {"action": "context", "job_id": job_id},
        }))
        print("\n===== design context (Agent 视角) =====")
        print(ctx_text[:1200])

        # 3) Agent makes a semantic design decision (classical poetry page)
        spec = {
            "theme_name": "辋川诗笺",
            "subject": "王维山水田园诗",
            "audience": "中小学生与古典诗词爱好者",
            "page_purpose": "离线阅读王维代表作与诗人小传",
            "rationale": "山水田园诗适合安静的传统书卷气质，用宋体与青绿点缀呼应诗中有画",
            "treatment": "editorial",
            "light_palette": {
                "background": "#F7F3E8", "surface": "#FCFAF2", "text": "#26332B",
                "muted": "#6B7A6E", "accent": "#2F6B4F", "accent_soft": "#DCE8DD",
                "border": "#D8D2BE",
            },
            "dark_palette": {
                "background": "#15201A", "surface": "#1C2A22", "text": "#E4EAE2",
                "muted": "#9AAA9C", "accent": "#7FBF9E", "accent_soft": "#24382C",
                "border": "#2C3E33",
            },
            "type_system": "classical",
            "layout": "focused",
            "hero": "understated",
            "section_style": "ruled",
            "image_style": "framed",
            "density": "spacious",
            "signature": "accent_rule",
        }
        render_text = result_text(rpc(proc, 6, "tools/call", {
            "name": "resource_html_design",
            "arguments": {"action": "render", "job_id": job_id, "design_spec": spec},
        }))
        print("\n===== render result =====")
        print(render_text[:600])
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
