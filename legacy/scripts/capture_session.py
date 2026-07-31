#!/usr/bin/env python3
"""自动捕获平台登录 cookie 并保存到 MCP session store。

用法:
    python capture_session.py bilibili     # 打开 B站登录页，自动检测登录
    python capture_session.py zhihu        # 知乎
    python capture_session.py --list       # 查看所有平台状态

全部通过 OpenClaw 浏览器（localhost CDP）操作，无需手动干预。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# --- 配置 ------------------------------------------------------------------

OPENCLAW = Path.home() / ".local" / "bin" / "openclaw"
MCP_SRC = Path.home() / "projects/quanxiao/collector_flow_ver/mcp/education-resources/src"
DATA_DIR = Path.home() / ".local" / "education-resource-mcp-data"
DATA_DIR = Path.home() / ".local" / "share" / "quanxiao" / "education-resource-mcp-data"

sys.path.insert(0, str(MCP_SRC))
from education_resource_mcp.sessions import SessionStore, PLATFORM_REGISTRY  # noqa: E402

# 每个平台的认证 cookie 判定规则
AUTH_COOKIES: dict[str, list[str]] = {
    "bilibili": ["SESSDATA"],
    "zhihu": ["z_c0"],
    "smartedu": [],
    "douyin": ["sessionid"],
    "weibo": ["SUB", "SUBP"],
    "ximalaya": ["_xmLog"],
    "generic": [],
}

POLL_INTERVAL = 3  # 秒
MAX_WAIT = 300     # 最长等待 5 分钟


# --- OpenClaw 浏览器操作 ---------------------------------------------------

def oc_browser(*args: str, json_output: bool = False) -> dict | str:
    """调用 openclaw browser 命令。"""
    cmd = [str(OPENCLAW), "browser", *args]
    if json_output:
        cmd.append("--json")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"openclaw browser {' '.join(args)}: {result.stderr.strip()}")
    if json_output:
        return json.loads(result.stdout)
    return result.stdout.strip()


def browser_ready() -> bool:
    """检查 OpenClaw 浏览器是否在运行。"""
    try:
        r = oc_browser("doctor", json_output=True)
        for check in r.get("checks", []):
            if check.get("name") == "browser":
                return check.get("ok", False)
        return False
    except Exception:
        return False


def ensure_browser() -> None:
    """确保浏览器在运行。"""
    if browser_ready():
        return
    print("⏳ 启动 OpenClaw 浏览器...", flush=True)
    oc_browser("start")
    time.sleep(3)
    if not browser_ready():
        raise RuntimeError("浏览器启动失败，请手动运行: openclaw browser start")


def get_cookies() -> list[dict]:
    """通过 OpenClaw 读取浏览器全部 cookie（含 HttpOnly）。"""
    r = oc_browser("cookies", json_output=True)
    return r.get("cookies", []) if isinstance(r, dict) else []


def navigate(url: str) -> None:
    """导航到指定 URL。"""
    oc_browser("navigate", url)


# --- 核心 ------------------------------------------------------------------

def capture(platform: str) -> bool:
    """打开登录页 → 轮询认证 cookie → 保存。返回是否成功。"""
    cfg = PLATFORM_REGISTRY.get(platform)
    if not cfg:
        print(f"❌ 未知平台: {platform}")
        print(f"   可选: {', '.join(PLATFORM_REGISTRY)}")
        return False

    if not cfg.requires_auth:
        print(f"ℹ️  {cfg.label} 不需要登录")
        return True

    auth_keys = AUTH_COOKIES.get(platform, [])
    if not auth_keys:
        print(f"⚠️  {cfg.label} 没有定义认证 cookie 判定规则，无法自动检测")
        return False

    # 0. 确保浏览器运行
    ensure_browser()

    # 1. 导航到登录页
    print(f"📄 打开 {cfg.label} 登录页: {cfg.login_url}", flush=True)
    navigate(cfg.login_url)
    print(f"🔔 请在 OpenClaw 浏览器窗口完成 {cfg.label} 登录", flush=True)
    print(f"   自动检测中（每 {POLL_INTERVAL}s 检查一次，最多 {MAX_WAIT}s）...\n", flush=True)

    # 2. 轮询等待认证 cookie
    store = SessionStore(DATA_DIR)
    for i in range(MAX_WAIT // POLL_INTERVAL):
        time.sleep(POLL_INTERVAL)
        try:
            cookies = get_cookies()
        except Exception as e:
            if i == 0:
                print(f"   连接异常: {e}", flush=True)
            continue

        # 筛选当前平台的 cookie
        platform_cookies = [
            c for c in cookies
            if any(d in c.get("domain", "") for d in cfg.cookie_domains)
        ]
        found = [c for c in platform_cookies if c["name"] in auth_keys and c.get("value")]

        if found:
            # 检测到登录！保存
            session_data = {"cookies": platform_cookies}

            # 过期时间取认证 cookie 中最短的
            expires_candidates = [
                c["expires"] for c in found
                if isinstance(c.get("expires"), (int, float)) and c["expires"] > 0
            ]
            expires_at = None
            if expires_candidates:
                min_expire = min(expires_candidates)
                expires_at = datetime.fromtimestamp(min_expire, timezone.utc).isoformat()

            result = store.save(platform, session_data, expires_at=expires_at)

            print(f"\n✅ {cfg.label} 登录成功！cookie 已保存", flush=True)
            print(f"   认证凭证: {', '.join(c['name'] for c in found)}", flush=True)
            print(f"   Cookie 总数: {len(platform_cookies)}", flush=True)
            print(f"   过期时间: {expires_at or '未知'}", flush=True)
            return True

        # 进度提示
        elapsed = (i + 1) * POLL_INTERVAL
        if i % 10 == 9:
            print(f"   ⏳ 仍在等待登录... ({elapsed}s)", flush=True)

    print(f"\n⏰ 超时：{MAX_WAIT}s 内未检测到 {cfg.label} 登录", flush=True)
    return False


def show_status() -> None:
    """显示所有平台的 session 状态。"""
    store = SessionStore(DATA_DIR)
    for s in store.get_status():
        icon = {"valid": "✅", "expired": "⏰", "missing": "⬜"}.get(s.status, "❓")
        print(f"{icon} {s.label:8s} ({s.platform:10s})  {s.status:8s}  过期={s.expires_at or 'N/A'}")


# --- 入口 ------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        show_status()
        return

    if sys.argv[1] in ("--list", "-l", "list", "status"):
        show_status()
        return

    platform = sys.argv[1].lower().strip()
    ok = capture(platform)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
