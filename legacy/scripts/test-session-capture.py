#!/usr/bin/env python3
"""端到端测试：浏览器登录 → 提取 cookie → 存入 MCP session store

用法:
  python scripts/test-session-capture.py bilibili

流程:
  1. 启动 Chrome（带远程调试）
  2. 打开指定平台的登录页
  3. 等待用户在浏览器中登录
  4. 用户按 Enter 确认后，通过 CDP 提取 cookie
  5. 存入 MCP session store
  6. 验证 session 状态
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket

# --- 配置 -------------------------------------------------------------

CHROME_PATH = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
CDP_PORT = 9333  # 避开 OpenClaw 可能占用的端口
PROFILE_DIR = "C:\\Temp\\session-capture-test"
MCP_PYTHON = "/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv/bin/python"
MCP_DATA_DIR = os.environ.get(
    "EDUCATION_RESOURCE_MCP_DATA_DIR",
    "/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-data",
)

PLATFORMS = {
    "bilibili": {
        "login_url": "https://passport.bilibili.com/login",
        "check_url": "https://www.bilibili.com/",
        "cookie_domain": "bilibili.com",
    },
    "zhihu": {
        "login_url": "https://www.zhihu.com/signin",
        "check_url": "https://www.zhihu.com/",
        "cookie_domain": "zhihu.com",
    },
}


def launch_chrome(url: str) -> subprocess.Popen:
    """启动带远程调试的 Chrome。"""
    proc = subprocess.Popen(
        [
            CHROME_PATH,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--restore-last-session=false",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Chrome 已启动 (PID={proc.pid}, CDP port={CDP_PORT})")
    return proc


def wait_for_cdp(timeout: float = 15) -> None:
    """等待 CDP 端口就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"CDP 端口 {CDP_PORT} 未就绪")


def get_tab_ws_url() -> str:
    """获取第一个标签页的 WebSocket 调试 URL。"""
    with urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json") as resp:
        tabs = json.loads(resp.read())
    for tab in tabs:
        if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
            return tab["webSocketDebuggerUrl"]
    raise RuntimeError("没有找到可用的标签页")


def get_cookies_via_cdp(ws_url: str) -> list[dict]:
    """通过 CDP 的 Network.getAllCookies 获取所有 cookie（含 httpOnly）。"""
    ws = websocket.create_connection(ws_url, timeout=10)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        while True:
            resp = json.loads(ws.recv())
            if resp.get("id") == 1:
                cookies = resp.get("result", {}).get("cookies", [])
                return cookies
    finally:
        ws.close()


def filter_cookies(cookies: list[dict], domain: str) -> list[dict]:
    """过滤出属于指定域名的 cookie。"""
    return [c for c in cookies if domain in (c.get("domain") or "")]


def save_to_mcp(platform: str, cookies: list[dict]) -> dict:
    """调用 MCP service 保存 session。"""
    result = subprocess.run(
        [
            MCP_PYTHON, "-c",
            f"""
import json, sys
sys.path.insert(0, "src")
from education_resource_mcp.service import ResourceService
from education_resource_mcp.config import Settings
from pathlib import Path

settings = Settings.from_env()
svc = ResourceService(settings=settings)
result = svc.session_save({platform!r}, {{"cookies": {cookies!r}}})
svc.close()
print(json.dumps(result, ensure_ascii=False))
""",
        ],
        capture_output=True,
        text=True,
        cwd="/home/admin_quanxiao/projects/quanxiao/collector_flow_ver/mcp/education-resources",
        env={**os.environ, "EDUCATION_RESOURCE_MCP_DATA_DIR": MCP_DATA_DIR},
    )
    if result.returncode != 0:
        print(f"MCP 错误:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError("MCP session_save 失败")
    return json.loads(result.stdout.strip().split("\n")[-1])


def check_mcp_status(platform: str) -> dict:
    """查询 MCP session 状态。"""
    result = subprocess.run(
        [
            MCP_PYTHON, "-c",
            f"""
import json, sys
sys.path.insert(0, "src")
from education_resource_mcp.service import ResourceService
from education_resource_mcp.config import Settings

settings = Settings.from_env()
svc = ResourceService(settings=settings)
result = svc.session_status([{platform!r}])
svc.close()
print(json.dumps(result, ensure_ascii=False))
""",
        ],
        capture_output=True,
        text=True,
        cwd="/home/admin_quanxiao/projects/quanxiao/collector_flow_ver/mcp/education-resources",
        env={**os.environ, "EDUCATION_RESOURCE_MCP_DATA_DIR": MCP_DATA_DIR},
    )
    return json.loads(result.stdout.strip().split("\n")[-1])


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in PLATFORMS:
        print(f"用法: python {sys.argv[0]} <{'|'.join(PLATFORMS)}>")
        return 1

    platform = sys.argv[1]
    cfg = PLATFORMS[platform]

    print(f"\n=== {platform} Session 捕获测试 ===\n")

    # 1. 检查当前状态
    print("1. 检查当前 session 状态...")
    status = check_mcp_status(platform)
    sessions = status.get("sessions", [])
    if sessions:
        print(f"   当前状态: {sessions[0]['status']}")
    print()

    # 2. 启动 Chrome
    print(f"2. 启动浏览器，打开 {cfg['login_url']}")
    proc = launch_chrome(cfg["login_url"])
    wait_for_cdp()

    # 3. 等待用户登录（自动轮询）
    login_cookie = {"bilibili": "SESSDATA", "zhihu": "z_c0"}[platform]
    print(f"\n3. 请在浏览器中登录{platform}...")
    print(f"   脚本会自动检测登录（检测 cookie: {login_cookie}）")

    ws_url = get_tab_ws_url()
    all_cookies: list[dict] = []
    platform_cookies: list[dict] = []
    deadline = time.time() + 180  # 3 分钟超时
    while time.time() < deadline:
        time.sleep(3)
        try:
            ws_url = get_tab_ws_url()
            all_cookies = get_cookies_via_cdp(ws_url)
        except Exception:
            continue
        platform_cookies = filter_cookies(all_cookies, cfg["cookie_domain"])
        cookie_names = {c["name"] for c in platform_cookies}
        if login_cookie in cookie_names:
            print(f"   ✅ 检测到登录成功！")
            break
        print(f"   等待登录... ({platform} cookie 数: {len(platform_cookies)})")
    else:
        print(f"\n   ❌ 3 分钟内未检测到登录。")
        proc.terminate()
        return 1

    # 4. 提取 cookie
    print(f"\n4. 提取 cookie...")
    print(f"   总 cookie 数: {len(all_cookies)}")
    print(f"   {platform} cookie 数: {len(platform_cookies)}")

    if not platform_cookies:
        print(f"\n   ❌ 没有找到 {cfg['cookie_domain']} 的 cookie。")
        print("   可能登录未成功，请重试。")
        proc.terminate()
        return 1

    # 展示 cookie 概要（不显示值）
    for c in platform_cookies[:5]:
        print(f"   - {c['name']} (domain={c.get('domain')}, httpOnly={c.get('httpOnly', False)})")
    if len(platform_cookies) > 5:
        print(f"   ... 还有 {len(platform_cookies) - 5} 个")

    # 5. 存入 MCP
    print(f"\n5. 存入 MCP session store...")
    save_result = save_to_mcp(platform, platform_cookies)
    print(f"   ✅ 保存成功: {save_result['status']}")
    print(f"   captured_at: {save_result['captured_at']}")

    # 6. 验证
    print(f"\n6. 验证 session 状态...")
    status = check_mcp_status(platform)
    sessions = status.get("sessions", [])
    if sessions:
        print(f"   ✅ 状态: {sessions[0]['status']}")
        needs_login = status.get("needs_login", [])
        if needs_login:
            print(f"   ⚠️  仍需登录: {[p['platform'] for p in needs_login]}")
        else:
            print(f"   ✅ 不需要登录，session 有效")

    # 清理
    proc.terminate()
    print(f"\n=== 测试完成 ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
